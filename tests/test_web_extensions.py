"""Tests for ``mureo.web.extensions`` — types and entry-point discovery.

The web-extension layer is structurally analogous to
``mureo.core.providers.registry``: a third-party distribution
registers an entry point in the ``mureo.web_extensions`` group whose
target satisfies the ``WebExtension`` Protocol; discovery iterates the
group exactly once at startup, isolates faults per entry, and exposes
the survivors as frozen ``WebExtensionEntry`` records.

Coverage:
  - Protocol / dataclass shape (frozen, runtime_checkable, validation)
  - Identifier regexes (``name``, ``filename``, ``subpath``)
  - Static-HTML sanitisation (no inline script/style, no on-* attrs)
  - Entry-point discovery: 0/1/N entry points, broken load,
    routes()/view() raising, duplicate-name first-wins + warning,
    discovery caching + refresh
"""

from __future__ import annotations

import warnings
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Type-shape tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_web_extension_protocol_is_runtime_checkable() -> None:
    from mureo.web.extensions import (
        RouteContribution,
        ViewContribution,
        WebExtension,
    )

    class _Fake:
        name = "demo"
        display_name = "Demo"

        def routes(self) -> tuple[RouteContribution, ...]:
            return ()

        def view(self) -> ViewContribution | None:
            return None

    assert isinstance(_Fake(), WebExtension)


@pytest.mark.unit
def test_web_extension_protocol_rejects_incomplete_impl() -> None:
    from mureo.web.extensions import WebExtension

    class _Incomplete:
        name = "demo"
        display_name = "Demo"
        # missing routes() and view()

    assert not isinstance(_Incomplete(), WebExtension)


@pytest.mark.unit
def test_route_contribution_is_frozen() -> None:
    from mureo.web.extensions import RouteContribution

    def _handler(_req: Any, _payload: dict[str, Any]) -> None:
        return None

    r = RouteContribution(method="GET", subpath="/ping", handler=_handler)
    with pytest.raises(FrozenInstanceError):
        r.method = "POST"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH", "get", "post", ""])
def test_route_contribution_rejects_non_get_post(method: str) -> None:
    from mureo.web.extensions import RouteContribution

    def _h(_req: Any, _payload: dict[str, Any]) -> None:
        return None

    with pytest.raises(ValueError, match="method"):
        RouteContribution(method=method, subpath="/x", handler=_h)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize(
    "subpath",
    [
        "ping",
        "//ping",
        "/ping/../etc",
        "/ping//x",
        "",
        "/ping?q=1",
        "/ping#x",
        "/ping/",  # trailing slash — force canonical form
        "/",
    ],
)
def test_route_contribution_rejects_unsafe_subpath(subpath: str) -> None:
    from mureo.web.extensions import RouteContribution

    def _h(_req: Any, _payload: dict[str, Any]) -> None:
        return None

    with pytest.raises(ValueError, match="subpath"):
        RouteContribution(method="GET", subpath=subpath, handler=_h)


@pytest.mark.unit
def test_route_contribution_accepts_well_formed_subpath() -> None:
    from mureo.web.extensions import RouteContribution

    def _h(_req: Any, _payload: dict[str, Any]) -> None:
        return None

    for sp in ("/ping", "/health/check", "/v1/things/42"):
        r = RouteContribution(method="GET", subpath=sp, handler=_h)
        assert r.subpath == sp


@pytest.mark.unit
def test_static_asset_is_frozen() -> None:
    from mureo.web.extensions import StaticAsset

    a = StaticAsset(filename="app.js", content_type="application/javascript", body=b"")
    with pytest.raises(FrozenInstanceError):
        a.filename = "evil.js"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    [
        "../evil.js",
        "..\\evil.js",
        "sub/dir.js",
        "",
        ".hidden",
        "UPPER.js",
        "name with space.js",
    ],
)
def test_static_asset_rejects_unsafe_filename(filename: str) -> None:
    from mureo.web.extensions import StaticAsset

    with pytest.raises(ValueError, match="filename"):
        StaticAsset(filename=filename, content_type="application/javascript", body=b"")


@pytest.mark.unit
def test_static_asset_accepts_well_formed_filename() -> None:
    from mureo.web.extensions import StaticAsset

    for fn in (
        "app.js",
        "app.css",
        "app-v2.js",
        "logo.png",
        "i18n.json",
        "app.min.js",
        "vendor.bundle.js",
        "i18n.en-us.json",
    ):
        a = StaticAsset(filename=fn, content_type="text/plain", body=b"")
        assert a.filename == fn


@pytest.mark.unit
def test_view_contribution_is_frozen() -> None:
    from mureo.web.extensions import ViewContribution

    v = ViewContribution(html_fragment="<p>hi</p>")
    with pytest.raises(FrozenInstanceError):
        v.html_fragment = "<p>evil</p>"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script>",
        "  <SCRIPT>x</SCRIPT>  ",
        "<p onclick=evil()>x</p>",
        "<p ONCLICK=evil()>x</p>",
        '<a href="javascript:alert(1)">x</a>',
        "<style>body{display:none}</style>",
    ],
)
def test_view_contribution_rejects_inline_executable_content(html: str) -> None:
    from mureo.web.extensions import ViewContribution

    with pytest.raises(ValueError, match="html_fragment"):
        ViewContribution(html_fragment=html)


@pytest.mark.unit
def test_view_contribution_accepts_safe_html() -> None:
    from mureo.web.extensions import ViewContribution

    v = ViewContribution(
        html_fragment='<section><h2>Vault</h2><p class="muted">Connected.</p></section>'
    )
    assert "Vault" in v.html_fragment


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class _FakeEP:
    """Minimal stand-in for ``importlib.metadata.EntryPoint`` — only
    ``.name``, ``.load()``, and ``.dist`` are read by the resolver."""

    def __init__(self, name: str, target: Any, dist_name: str | None = None) -> None:
        self.name = name
        self._target = target
        if dist_name is not None:
            self.dist = type("D", (), {"name": dist_name})()
        else:
            self.dist = None

    def load(self) -> Any:
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.web_extensions"
        return eps

    monkeypatch.setattr("mureo.web.extensions.entry_points", fake_entry_points)


class _DemoExtension:
    """Reference WebExtension implementation used by discovery tests."""

    name = "demo"
    display_name = "Demo"

    def routes(self) -> tuple[Any, ...]:
        from mureo.web.extensions import RouteContribution

        def _h(_req: Any, _payload: dict[str, Any]) -> None:
            return None

        return (RouteContribution(method="GET", subpath="/ping", handler=_h),)

    def view(self) -> Any:
        from mureo.web.extensions import ViewContribution

        return ViewContribution(html_fragment="<p>demo</p>")


class _BrokenLoad:
    """Sentinel — load() raises so the entry is skipped."""


def _broken_loader() -> Any:
    raise RuntimeError("plugin import blew up")


class _BadRoutes:
    name = "bad-routes"
    display_name = "Bad routes"

    def routes(self) -> tuple[Any, ...]:
        raise RuntimeError("routes() exploded")

    def view(self) -> Any:
        return None


class _BadView:
    name = "bad-view"
    display_name = "Bad view"

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        raise RuntimeError("view() exploded")


class _UpperName:
    name = "UPPER"
    display_name = "Upper"

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


@pytest.mark.unit
def test_discover_returns_empty_when_no_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(monkeypatch, [])
    assert discover_web_extensions() == ()


@pytest.mark.unit
def test_discover_registers_well_formed_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(
        monkeypatch, [_FakeEP("demo", _DemoExtension, dist_name="mureo-demo")]
    )
    entries = discover_web_extensions()
    assert len(entries) == 1
    e = entries[0]
    assert e.name == "demo"
    assert e.display_name == "Demo"
    assert e.source_distribution == "mureo-demo"
    assert len(e.routes) == 1
    assert e.view is not None
    assert e.routes[0].subpath == "/ping"


@pytest.mark.unit
def test_discover_skips_broken_load_and_keeps_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("broken", _broken_loader),
            _FakeEP("demo", _DemoExtension),
        ],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(issubclass(w.category, WebExtensionWarning) for w in caught)
    assert any("broken" in str(w.message) for w in caught)


@pytest.mark.unit
def test_discover_isolates_routes_call_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [_FakeEP("bad-routes", _BadRoutes), _FakeEP("demo", _DemoExtension)],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "bad-routes" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_isolates_view_call_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [_FakeEP("bad-view", _BadView), _FakeEP("demo", _DemoExtension)],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any("bad-view" in str(w.message) for w in caught)


@pytest.mark.unit
def test_duplicate_names_first_wins_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    class _Dup:
        name = "demo"
        display_name = "Duplicate"

        def routes(self) -> tuple[Any, ...]:
            return ()

        def view(self) -> Any:
            return None

    _patch_entry_points(
        monkeypatch, [_FakeEP("demo", _DemoExtension), _FakeEP("dup", _Dup)]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    # first-wins: original 'demo' stays
    assert len(entries) == 1
    assert entries[0].display_name == "Demo"
    assert any(
        issubclass(w.category, WebExtensionWarning) and "demo" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_rejects_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(monkeypatch, [_FakeEP("upper", _UpperName)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert entries == ()
    assert any(issubclass(w.category, WebExtensionWarning) for w in caught)


@pytest.mark.unit
def test_discover_does_not_consult_entry_points_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery is cached so each ``discover_web_extensions()`` call
    after the first is a dict lookup, not an entry-points iteration."""
    from mureo.web.extensions import discover_web_extensions, reset_web_extensions

    reset_web_extensions()
    calls: list[str] = []

    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        calls.append(group)
        return [_FakeEP("demo", _DemoExtension)]

    monkeypatch.setattr("mureo.web.extensions.entry_points", fake_entry_points)
    first = discover_web_extensions()
    second = discover_web_extensions()
    assert first is second  # exact tuple reuse
    assert len(calls) == 1


@pytest.mark.unit
def test_reset_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.web.extensions import discover_web_extensions, reset_web_extensions

    reset_web_extensions()
    _patch_entry_points(monkeypatch, [_FakeEP("demo", _DemoExtension)])
    first = discover_web_extensions()
    reset_web_extensions()
    _patch_entry_points(monkeypatch, [])
    second = discover_web_extensions()
    assert first != second
    assert second == ()


# ---------------------------------------------------------------------------
# display_name_i18n — optional per-locale labels for the nav tab
# ---------------------------------------------------------------------------


class _DemoI18nExtension:
    """Extension that ships per-locale labels alongside the English default."""

    name = "demo-i18n"
    display_name = "Demo (en fallback)"
    display_name_i18n = {"en": "Demo", "ja": "デモ"}

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


class _BadI18nMappingType:
    name = "bad-i18n-type"
    display_name = "Bad i18n type"
    display_name_i18n = ["en", "Foo"]  # list, not mapping

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


class _BadI18nValueType:
    name = "bad-i18n-value"
    display_name = "Bad i18n value"
    display_name_i18n = {"en": 123}  # value is not a str

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


class _BadI18nKeyType:
    name = "bad-i18n-key"
    display_name = "Bad i18n key"
    display_name_i18n = {1: "Foo"}  # key is not a str

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


@pytest.mark.unit
def test_web_extension_entry_defaults_display_name_i18n_to_empty_dict() -> None:
    """Existing callers that construct ``WebExtensionEntry`` without the
    new ``display_name_i18n`` field must continue to work."""
    from mureo.web.extensions import WebExtensionEntry

    entry = WebExtensionEntry(
        name="legacy",
        display_name="Legacy",
        routes=(),
        view=None,
        source_distribution=None,
    )
    assert entry.display_name_i18n == {}


@pytest.mark.unit
def test_web_extension_entry_accepts_display_name_i18n() -> None:
    from mureo.web.extensions import WebExtensionEntry

    entry = WebExtensionEntry(
        name="i18n",
        display_name="I18n",
        routes=(),
        view=None,
        source_distribution=None,
        display_name_i18n={"en": "I18n", "ja": "国際化"},
    )
    assert entry.display_name_i18n == {"en": "I18n", "ja": "国際化"}


@pytest.mark.unit
def test_discover_picks_up_display_name_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(monkeypatch, [_FakeEP("demo-i18n", _DemoI18nExtension)])
    entries = discover_web_extensions()
    assert len(entries) == 1
    assert entries[0].display_name_i18n == {"en": "Demo", "ja": "デモ"}


@pytest.mark.unit
def test_discover_defaults_missing_display_name_i18n_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An extension that does not declare ``display_name_i18n`` — i.e. every
    extension shipped before this feature existed — must continue to load."""
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(monkeypatch, [_FakeEP("demo", _DemoExtension)])
    entries = discover_web_extensions()
    assert len(entries) == 1
    assert entries[0].display_name_i18n == {}


@pytest.mark.unit
def test_discover_skips_extension_with_non_mapping_display_name_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("bad-i18n-type", _BadI18nMappingType),
            _FakeEP("demo", _DemoExtension),
        ],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning)
        and "bad-i18n-type" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_skips_extension_with_non_str_i18n_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("bad-i18n-value", _BadI18nValueType),
            _FakeEP("demo", _DemoExtension),
        ],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning)
        and "bad-i18n-value" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_skips_extension_with_non_str_i18n_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("bad-i18n-key", _BadI18nKeyType),
            _FakeEP("demo", _DemoExtension),
        ],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "bad-i18n-key" in str(w.message)
        for w in caught
    )


class _NoneI18n:
    name = "none-i18n"
    display_name = "None i18n"
    display_name_i18n = None  # explicit None — not a Mapping

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> Any:
        return None


@pytest.mark.unit
def test_discover_skips_extension_with_none_display_name_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``None`` value is distinct from the attribute being
    absent (which defaults to ``{}`` via ``getattr``). ``None`` is not a
    ``Mapping`` so discovery must skip the entry."""
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    _patch_entry_points(
        monkeypatch,
        [_FakeEP("none-i18n", _NoneI18n), _FakeEP("demo", _DemoExtension)],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "none-i18n" in str(w.message)
        for w in caught
    )


# ---------------------------------------------------------------------------
# #189 — surface overrides: hidden_builtin_tabs / replaces_landing
# ---------------------------------------------------------------------------


def _make_view_extension(
    ext_name: str,
    *,
    hidden_tabs: Any = None,
    replaces: Any = None,
    with_view: bool = True,
) -> type:
    """Build a synthetic extension class with optional override attrs."""
    from mureo.web.extensions import ViewContribution

    class _Ext:
        name = ext_name
        display_name = ext_name.title()

        def routes(self) -> tuple[Any, ...]:
            return ()

        def view(self) -> Any:
            if with_view:
                return ViewContribution(html_fragment="<p>x</p>")
            return None

    if hidden_tabs is not None:
        _Ext.hidden_builtin_tabs = hidden_tabs  # type: ignore[attr-defined]
    if replaces is not None:
        _Ext.replaces_landing = replaces  # type: ignore[attr-defined]
    return _Ext


@pytest.mark.unit
def test_web_extension_entry_defaults_surface_overrides() -> None:
    """Existing callers constructing ``WebExtensionEntry`` without the
    new #189 fields must keep working — both attributes default to the
    no-op values."""
    from mureo.web.extensions import WebExtensionEntry

    entry = WebExtensionEntry(
        name="legacy",
        display_name="Legacy",
        routes=(),
        view=None,
        source_distribution=None,
    )
    assert entry.hidden_builtin_tabs == ()
    assert entry.replaces_landing is False


@pytest.mark.unit
def test_discover_defaults_missing_surface_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-#189 extensions (no override attrs declared) load unchanged."""
    from mureo.web.extensions import discover_web_extensions

    _patch_entry_points(monkeypatch, [_FakeEP("demo", _DemoExtension)])
    [entry] = discover_web_extensions()
    assert entry.hidden_builtin_tabs == ()
    assert entry.replaces_landing is False


@pytest.mark.unit
def test_discover_picks_up_hidden_builtin_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    ext = _make_view_extension("full-surface", hidden_tabs=("setup", "demo"))
    _patch_entry_points(monkeypatch, [_FakeEP("full-surface", ext)])
    [entry] = discover_web_extensions()
    assert entry.hidden_builtin_tabs == ("setup", "demo")


@pytest.mark.unit
def test_discover_drops_unknown_hidden_tab_keys_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown keys are soft-dropped (extension survives) — matches the
    issue's stated soft-fail discipline for value-level problems."""
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    ext = _make_view_extension("squatter", hidden_tabs=("setup", "bogus-tab"))
    _patch_entry_points(monkeypatch, [_FakeEP("squatter", ext)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        [entry] = discover_web_extensions()
    assert entry.hidden_builtin_tabs == ("setup",)
    assert any(
        issubclass(w.category, WebExtensionWarning) and "bogus-tab" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_dedupes_hidden_tab_keys_preserving_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    ext = _make_view_extension("dup", hidden_tabs=("danger", "setup", "danger"))
    _patch_entry_points(monkeypatch, [_FakeEP("dup", ext)])
    [entry] = discover_web_extensions()
    assert entry.hidden_builtin_tabs == ("danger", "setup")


@pytest.mark.unit
def test_discover_skips_extension_with_non_tuple_hidden_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Type-level problems are packaging bugs — the whole extension is
    skipped, mirroring the ``display_name_i18n`` type discipline."""
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    ext = _make_view_extension("list-tabs", hidden_tabs=["setup"])  # list, not tuple
    _patch_entry_points(
        monkeypatch, [_FakeEP("list-tabs", ext), _FakeEP("demo", _DemoExtension)]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "list-tabs" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_skips_extension_with_non_str_hidden_tab_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    ext = _make_view_extension("int-tab", hidden_tabs=(1,))
    _patch_entry_points(
        monkeypatch, [_FakeEP("int-tab", ext), _FakeEP("demo", _DemoExtension)]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "int-tab" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_picks_up_replaces_landing_with_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import discover_web_extensions

    ext = _make_view_extension("landing-owner", replaces=True, with_view=True)
    _patch_entry_points(monkeypatch, [_FakeEP("landing-owner", ext)])
    [entry] = discover_web_extensions()
    assert entry.replaces_landing is True


@pytest.mark.unit
def test_discover_downgrades_replaces_landing_without_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``replaces_landing=True`` with no ``view()`` leaves the operator
    nowhere to land — the flag is downgraded (extension survives)."""
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    ext = _make_view_extension("headless", replaces=True, with_view=False)
    _patch_entry_points(monkeypatch, [_FakeEP("headless", ext)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        [entry] = discover_web_extensions()
    assert entry.replaces_landing is False
    assert any(
        issubclass(w.category, WebExtensionWarning) and "headless" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_skips_extension_with_non_bool_replaces_landing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    ext = _make_view_extension("stringy", replaces="yes")
    _patch_entry_points(
        monkeypatch, [_FakeEP("stringy", ext), _FakeEP("demo", _DemoExtension)]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    assert [e.name for e in entries] == ["demo"]
    assert any(
        issubclass(w.category, WebExtensionWarning) and "stringy" in str(w.message)
        for w in caught
    )


@pytest.mark.unit
def test_discover_first_replaces_landing_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two installed extensions both claiming the landing: first
    discovered keeps the flag; the second is downgraded with a warning
    (mirrors the duplicate-name discipline)."""
    from mureo.web.extensions import WebExtensionWarning, discover_web_extensions

    first = _make_view_extension("first-owner", replaces=True, with_view=True)
    second = _make_view_extension("second-owner", replaces=True, with_view=True)
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("first-owner", first), _FakeEP("second-owner", second)],
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entries = discover_web_extensions()
    by_name = {e.name: e for e in entries}
    assert by_name["first-owner"].replaces_landing is True
    assert by_name["second-owner"].replaces_landing is False
    assert any(
        issubclass(w.category, WebExtensionWarning) and "second-owner" in str(w.message)
        for w in caught
    )


@pytest.fixture(autouse=True)
def _reset_extensions_cache() -> Iterator[None]:
    """Every test starts with a clean discovery cache."""
    from mureo.web.extensions import reset_web_extensions

    reset_web_extensions()
    yield
    reset_web_extensions()
