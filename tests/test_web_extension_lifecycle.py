"""Always-on lifecycle hooks for web extensions (#249).

A ``WebExtension`` MAY declare optional ``on_serve_start(ctx)`` /
``on_serve_stop()`` hooks. They fire ONLY in the always-on daemon
(``serve_forever`` — ``timeout_seconds is None``), never on a
short-lived interactive ``mureo configure`` (the same "only the
always-on service runs background jobs" guard #244 applies to the
update poller).

Discovery captures the bound hooks onto the frozen
:class:`WebExtensionEntry` — mirroring the existing optional-attr
capture (``display_name_i18n`` / ``hidden_builtin_tabs`` /
``replaces_landing``). :func:`start_serve_lifecycles` /
:func:`stop_serve_lifecycles` invoke them with per-extension fault
isolation so one bad plugin can neither crash the daemon nor block the
others, and only extensions whose ``on_serve_start`` ran are stopped.
"""

from __future__ import annotations

import dataclasses
import threading
import time
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.web.extensions import (
    ServeContext,
    WebExtensionEntry,
    WebExtensionWarning,
    discover_web_extensions,
    reset_web_extensions,
    start_serve_lifecycles,
    stop_serve_lifecycles,
)

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _entry(name: str = "agency", **overrides: Any) -> WebExtensionEntry:
    """Build a minimal :class:`WebExtensionEntry`, hooks overridable."""
    base: dict[str, Any] = dict(
        name=name,
        display_name=name.title(),
        routes=(),
        view=None,
        source_distribution=None,
    )
    base.update(overrides)
    return WebExtensionEntry(**base)


def _ctx(home: Path = Path("/home")) -> ServeContext:
    return ServeContext(
        stop_event=threading.Event(), request_stop=lambda: None, home=home
    )


class _FakeEP:
    """Minimal entry-point: ``.name``, ``.load()``, ``.dist`` (for discovery)."""

    def __init__(self, name: str, obj: object, dist_name: str | None = None) -> None:
        self.name = name
        self._obj = obj
        self.dist = type("D", (), {"name": dist_name})() if dist_name else None

    def load(self) -> object:
        return self._obj


class _Ext:
    """A WebExtension satisfying the structural Protocol, with hooks."""

    name = "agency"
    display_name = "Agency"

    def __init__(
        self,
        on_serve_start: Callable[..., None] | None = None,
        on_serve_stop: Callable[[], None] | None = None,
    ) -> None:
        if on_serve_start is not None:
            self.on_serve_start = on_serve_start  # type: ignore[assignment]
        if on_serve_stop is not None:
            self.on_serve_stop = on_serve_stop  # type: ignore[assignment]

    def routes(self) -> tuple[Any, ...]:
        return ()

    def view(self) -> None:
        return None


# ---------------------------------------------------------------------------
# ServeContext
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestServeContext:
    def test_carries_stop_event_request_stop_and_home(self) -> None:
        ev = threading.Event()
        called: list[int] = []
        ctx = ServeContext(
            stop_event=ev, request_stop=lambda: called.append(1), home=Path("/x")
        )
        assert ctx.stop_event is ev
        ctx.request_stop()
        assert called == [1]
        assert ctx.home == Path("/x")

    def test_is_frozen(self) -> None:
        ctx = _ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.home = Path("/other")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WebExtensionEntry backward compatibility
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEntryDefaults:
    def test_hooks_default_to_none(self) -> None:
        e = _entry()
        assert e.on_serve_start is None
        assert e.on_serve_stop is None


# ---------------------------------------------------------------------------
# start_serve_lifecycles / stop_serve_lifecycles
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLifecycleInvocation:
    def test_start_passes_ctx_and_stop_roundtrips(self) -> None:
        seen: dict[str, Any] = {}
        e = _entry(
            on_serve_start=lambda ctx: seen.__setitem__("ctx", ctx),
            on_serve_stop=lambda: seen.__setitem__("stopped", True),
        )
        ctx = _ctx(home=Path("/h"))
        started = start_serve_lifecycles((e,), ctx)
        assert started == (e,)
        assert seen["ctx"] is ctx
        stop_serve_lifecycles(started)
        assert seen["stopped"] is True

    def test_entry_without_start_is_not_started(self) -> None:
        e = _entry()  # no hooks
        assert start_serve_lifecycles((e,), _ctx()) == ()

    def test_entry_with_only_stop_is_not_stopped(self) -> None:
        """No ``on_serve_start`` means it never started — so never stopped."""
        seen: list[str] = []
        e = _entry(on_serve_stop=lambda: seen.append("stopped"))
        started = start_serve_lifecycles((e,), _ctx())
        assert started == ()
        stop_serve_lifecycles(started)
        assert seen == []

    def test_start_fault_isolation(self) -> None:
        order: list[str] = []

        def boom(_ctx: ServeContext) -> None:
            raise RuntimeError("start boom")

        bad = _entry(
            name="bad",
            on_serve_start=boom,
            on_serve_stop=lambda: order.append("bad-stop"),
        )
        good = _entry(
            name="good",
            on_serve_start=lambda _c: order.append("good-start"),
            on_serve_stop=lambda: order.append("good-stop"),
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            started = start_serve_lifecycles((bad, good), _ctx())
        # The bad one is isolated; the good one still starts.
        assert "good-start" in order
        assert good in started
        assert bad not in started
        assert any(issubclass(w.category, WebExtensionWarning) for w in caught)
        # A failed start must NOT receive a stop.
        stop_serve_lifecycles(started)
        assert "bad-stop" not in order
        assert "good-stop" in order

    def test_stop_fault_isolation(self) -> None:
        order: list[str] = []

        def boom() -> None:
            raise RuntimeError("stop boom")

        bad = _entry(name="bad", on_serve_start=lambda _c: None, on_serve_stop=boom)
        good = _entry(
            name="good",
            on_serve_start=lambda _c: None,
            on_serve_stop=lambda: order.append("good-stop"),
        )
        started = start_serve_lifecycles((bad, good), _ctx())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            stop_serve_lifecycles(started)  # must not raise
        assert "good-stop" in order
        assert any(issubclass(w.category, WebExtensionWarning) for w in caught)


# ---------------------------------------------------------------------------
# Discovery capture
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDiscoveryCapturesHooks:
    def _discover_with(self, monkeypatch: pytest.MonkeyPatch, ext: object) -> Any:
        ep = _FakeEP("agency", ext, dist_name="mureo-agency")

        def fake_entry_points(*, group: str) -> list[Any]:
            from mureo.web.extensions import WEB_EXTENSIONS_ENTRY_POINT_GROUP

            return [ep] if group == WEB_EXTENSIONS_ENTRY_POINT_GROUP else []

        monkeypatch.setattr("mureo.web.extensions.entry_points", fake_entry_points)
        reset_web_extensions()
        try:
            entries = discover_web_extensions()
        finally:
            reset_web_extensions()
        return entries

    def test_captures_bound_hooks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        marks: list[str] = []
        ext = _Ext(
            on_serve_start=lambda _c: marks.append("start"),
            on_serve_stop=lambda: marks.append("stop"),
        )
        (entry,) = self._discover_with(monkeypatch, ext)
        assert callable(entry.on_serve_start)
        assert callable(entry.on_serve_stop)
        entry.on_serve_start(_ctx())
        entry.on_serve_stop()
        assert marks == ["start", "stop"]

    def test_extension_without_hooks_yields_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (entry,) = self._discover_with(monkeypatch, _Ext())
        assert entry.on_serve_start is None
        assert entry.on_serve_stop is None

    def test_non_callable_hook_skips_extension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ext = _Ext()
        ext.on_serve_start = "not-callable"  # type: ignore[assignment]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entries = self._discover_with(monkeypatch, ext)
        assert entries == ()  # whole extension skipped (packaging bug)
        assert any(issubclass(w.category, WebExtensionWarning) for w in caught)


# ---------------------------------------------------------------------------
# Server integration: serve_forever fires, serve-once does NOT
# ---------------------------------------------------------------------------
@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir()
    return home


@pytest.fixture(autouse=True)
def _no_update_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the #244 background update poller (interval 0 = off) so these
    serve tests never spawn a real ``pip`` subprocess / network call."""
    monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "0")


def _run_wizard_with_extension(
    home_dir: Path, fake_entry: WebExtensionEntry, timeout: Any
) -> None:
    """Drive ``run_configure_wizard`` to ready, then stop it — with a single
    fake extension injected. Blocks until the wizard thread joins."""
    from mureo.web.server import ConfigureWizard, run_configure_wizard

    captured: dict[str, Any] = {}
    real_ctor = ConfigureWizard

    def _spy(**kwargs: object) -> ConfigureWizard:
        wiz = real_ctor(**kwargs)  # type: ignore[arg-type]
        captured["wiz"] = wiz
        return wiz

    with (
        patch("mureo.web.server.webbrowser.open"),
        patch("mureo.web.server.discover_web_extensions", return_value=(fake_entry,)),
        patch("mureo.web.server.ConfigureWizard", side_effect=_spy),
    ):
        thread = threading.Thread(
            target=run_configure_wizard,
            kwargs={
                "home": home_dir,
                "open_browser": False,
                "timeout_seconds": timeout,
            },
            daemon=True,
        )
        thread.start()
        for _ in range(100):
            if "wiz" in captured:
                break
            time.sleep(0.02)
        captured["wiz"].wait_until_ready(timeout=5.0)
        # Let any serve_forever start-hooks run before we stop.
        time.sleep(0.1)
        captured["wiz"].request_stop()
        thread.join(timeout=5.0)
    assert not thread.is_alive(), "wizard thread did not stop"


@pytest.mark.unit
class TestServerIntegration:
    def test_serve_forever_fires_start_and_stop(self, home_dir: Path) -> None:
        events: dict[str, Any] = {"start_ctx": None, "stopped": False}
        fake = _entry(
            on_serve_start=lambda ctx: events.__setitem__("start_ctx", ctx),
            on_serve_stop=lambda: events.__setitem__("stopped", True),
        )
        _run_wizard_with_extension(home_dir, fake, timeout=None)  # serve_forever
        assert events["start_ctx"] is not None, "on_serve_start never fired"
        assert isinstance(events["start_ctx"], ServeContext)
        assert events["start_ctx"].home == home_dir
        assert events["stopped"] is True, "on_serve_stop never fired"

    def test_serve_once_does_not_fire_lifecycle(self, home_dir: Path) -> None:
        events: dict[str, int] = {"start": 0, "stop": 0}
        fake = _entry(
            on_serve_start=lambda _c: events.__setitem__("start", events["start"] + 1),
            on_serve_stop=lambda: events.__setitem__("stop", events["stop"] + 1),
        )
        _run_wizard_with_extension(home_dir, fake, timeout=600.0)  # interactive
        assert events["start"] == 0, "serve-once must NOT fire on_serve_start"
        assert events["stop"] == 0, "serve-once must NOT fire on_serve_stop"

    def test_start_hook_requesting_stop_shuts_down_cleanly(
        self, home_dir: Path
    ) -> None:
        """An extension that calls ``ctx.request_stop()`` inside
        ``on_serve_start`` ends the daemon on its own — the wizard thread
        exits with NO external stop and ``on_serve_stop`` still fires."""
        from mureo.web.server import ConfigureWizard, run_configure_wizard

        events: dict[str, bool] = {"stopped": False}
        fake = _entry(
            on_serve_start=lambda ctx: ctx.request_stop(),
            on_serve_stop=lambda: events.__setitem__("stopped", True),
        )
        captured: dict[str, Any] = {}
        real_ctor = ConfigureWizard

        def _spy(**kwargs: object) -> ConfigureWizard:
            wiz = real_ctor(**kwargs)  # type: ignore[arg-type]
            captured["wiz"] = wiz
            return wiz

        with (
            patch("mureo.web.server.webbrowser.open"),
            patch("mureo.web.server.discover_web_extensions", return_value=(fake,)),
            patch("mureo.web.server.ConfigureWizard", side_effect=_spy),
        ):
            thread = threading.Thread(
                target=run_configure_wizard,
                kwargs={
                    "home": home_dir,
                    "open_browser": False,
                    "timeout_seconds": None,  # serve_forever
                },
                daemon=True,
            )
            thread.start()
            # No external request_stop: the start hook is the only stopper.
            thread.join(timeout=5.0)
        assert not thread.is_alive(), "hook request_stop did not end the daemon"
        assert events["stopped"] is True, "on_serve_stop never fired"
