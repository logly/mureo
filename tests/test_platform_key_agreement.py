"""One answer to "is this platform key real?" (Issue #631).

Two functions answer that question for the same key on the same machine:

- the **write** side — :func:`~mureo.context.platform_guards.
  reject_unknown_platform_key` (#609), which also decides what
  ``mureo repair platform-key`` calls resolvable (via
  :func:`~mureo.context.platform_repair.is_unresolvable_platform_key`);
- the **read** side — :func:`~mureo.web.reports.platform_display_name`,
  whose "returns the key unchanged" is the Reports view's
  ``unrecognized_key`` signal.

They drifted: #609 made a bare provider name an installed plugin registered
(``logly_ads_context``) a valid write vocabulary and nothing taught the label
path about it, so ``mureo repair platform-key --all`` reported every client
``Clean`` while the Reports view told the same operator, about the same entry,
that mureo could not resolve its key.

The symptom was one key shape; the defect is that two functions can drift.
So the test that matters is the **agreement** across every shape, not a test
for the bare-name symptom — that is what would have caught #609 widening the
write vocabulary without touching the read side.

Every test here pins the entry-point set with a fake. The machine that
reported this really has the LOGLY and LINE/Yahoo bridges installed, so a test
leaning on the environment passes there and fails in CI.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mureo.context import platform_guards
from mureo.context.platform_guards import (
    installed_platform_names,
    reject_unknown_platform_key,
)
from mureo.context.platform_repair import is_unresolvable_platform_key
from mureo.web.reports import platform_display_name

pytestmark = pytest.mark.unit


def _pin_installed_platforms(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Pin which plugin platforms the environment reports as installed.

    The same pin the #609 guard tests and the #610 repair tests use, and for
    the same reason.
    """
    entries = tuple(SimpleNamespace(name=name) for name in names)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


# Every platform-key shape mureo has, and whether a machine with the LOGLY and
# LINE/Yahoo bridges installed can resolve it. One table, asked of both sides.
_KEY_SHAPES: tuple[tuple[str, bool], ...] = (
    # built-ins, including the hosted connector with no entry point at all
    ("google_ads", True),
    ("tiktok_ads", True),
    # canonical plugin key (#537) — accepted without the distribution being
    # installed, so it resolves for a bridge this machine does not have
    ("plugin:mureo-lineyahoo-bridge:yahoo_ads", True),
    ("plugin:not-installed-anywhere:some_ads", True),
    # the legacy short form (#481), still valid on read
    ("plugin:mureo-logly-bridge", True),
    # a bare provider name an installed plugin registered (#609) — the shape
    # this issue is about
    ("logly_ads_context", True),
    ("yahoo_ads", True),
    # the invented key from the field: the bridge's provider is
    # ``logly_ads_context``, so this one names nothing
    ("logly_ads", False),
    ("totally_made_up", False),
    # claims the plugin namespace without naming a platform
    ("plugin:", False),
    ("plugin:acme-ads:", False),
)


@pytest.mark.parametrize(("key", "resolvable"), _KEY_SHAPES)
def test_the_label_path_and_the_guard_agree_on_every_key_shape(
    monkeypatch: pytest.MonkeyPatch, key: str, resolvable: bool
) -> None:
    """The invariant, both directions, for every vocabulary mureo has.

    ``platform_display_name(key) == key`` is the Reports view's
    ``unrecognized_key`` condition and ``is_unresolvable_platform_key`` is
    what ``mureo repair platform-key`` prints ``Clean`` from. Whenever those
    two disagree, one surface warns an operator about a key another surface
    has just told them is fine.
    """
    _pin_installed_platforms(monkeypatch, "logly_ads_context", "yahoo_ads")

    labelled = platform_display_name(key) != key
    accepted = not is_unresolvable_platform_key(key)

    assert labelled == accepted, (
        f"{key!r}: the label path says resolvable={labelled} and the write "
        f"guard says resolvable={accepted} — one of them will warn about a "
        f"key the other accepts"
    )
    assert accepted is resolvable


def test_the_reported_entry_is_labelled_and_not_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The symptom itself: the key the guard accepted was reported unresolvable."""
    _pin_installed_platforms(monkeypatch, "logly_ads_context")

    reject_unknown_platform_key("logly_ads_context")  # accepted since #609
    assert platform_display_name("logly_ads_context") == "Logly Ads Context (plugin)"


def test_the_bare_form_reads_as_the_canonical_key_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One platform, one label.

    The entry comes from a plugin under either spelling, so the bare provider
    name carries the same ``" (plugin)"`` suffix as the canonical key for the
    same platform. Two labels for one platform on one dashboard would be a
    fresh inconsistency in place of the one being fixed.
    """
    _pin_installed_platforms(monkeypatch, "logly_ads_context", "yahoo_ads")

    assert platform_display_name(
        "plugin:mureo-logly-bridge:logly_ads_context"
    ) == platform_display_name("logly_ads_context")
    assert platform_display_name("yahoo_ads") == "Yahoo Ads (plugin)"


def test_the_label_path_fails_open_exactly_as_the_guard_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An environment that cannot be enumerated must not start flagging keys.

    The guard fails OPEN on it (#609): a broken ``importlib.metadata`` is not
    evidence that a key is wrong. A label path that failed closed would drift
    in the other direction — every plugin entry on that machine would be
    reported unrecognised.
    """
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: None)

    for key in ("logly_ads_context", "some_bridge_platform"):
        assert not is_unresolvable_platform_key(key)
        assert platform_display_name(key) != key


def test_a_key_claiming_the_plugin_namespace_is_never_labelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """…not even on an environment that cannot be enumerated.

    ``plugin:`` and ``plugin:<dist>:`` name no platform whatever the registry
    says, and the write path refuses them on shape alone
    (``reject_unusable_platform_key``), which no enumeration failure can
    change. Labelling them from the fail-open branch would dress up a
    malformed entry.
    """
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: None)

    for key in ("plugin:", "plugin:acme-ads:"):
        assert platform_display_name(key) == key


# ---------------------------------------------------------------------------
# The enumeration is shared, and cached
# ---------------------------------------------------------------------------


def test_both_surfaces_read_one_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not two copies: patching the single seam moves both answers."""
    _pin_installed_platforms(monkeypatch, "acme_ads")

    assert platform_display_name("acme_ads") == "Acme Ads (plugin)"
    assert not is_unresolvable_platform_key("acme_ads")


def test_the_entry_points_are_enumerated_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reports renders per platform per client; the scan costs ~43 ms."""
    calls = 0

    def _enumerate() -> tuple[SimpleNamespace, ...]:
        nonlocal calls
        calls += 1
        return (SimpleNamespace(name="logly_ads_context"),)

    monkeypatch.setattr(platform_guards, "_provider_entry_points", _enumerate)

    for _ in range(5):
        assert (
            platform_display_name("logly_ads_context") == "Logly Ads Context (plugin)"
        )
        reject_unknown_platform_key("logly_ads_context")

    assert calls == 1


def test_the_cache_cannot_serve_a_stale_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin appearing mid-process is seen, not answered from the cache.

    The cache is keyed by the enumeration itself, so swapping it — which is
    how every test installs a plugin — can never be served the previous
    answer, whatever order the suite runs in.
    """
    _pin_installed_platforms(monkeypatch, "logly_ads_context")
    assert platform_display_name("yahoo_ads") == "yahoo_ads"

    _pin_installed_platforms(monkeypatch, "logly_ads_context", "yahoo_ads")

    assert platform_display_name("yahoo_ads") == "Yahoo Ads (plugin)"
    assert not is_unresolvable_platform_key("yahoo_ads")


def test_a_failed_enumeration_is_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Could not enumerate" is a moment, not a fact about the machine.

    Caching it would make one unlucky call fail the whole process open for
    its lifetime.
    """
    outcomes: list[tuple[SimpleNamespace, ...] | None] = [
        None,
        (SimpleNamespace(name="logly_ads_context"),),
    ]
    monkeypatch.setattr(
        platform_guards, "_provider_entry_points", lambda: outcomes.pop(0)
    )

    assert installed_platform_names() is None
    assert installed_platform_names() == frozenset({"logly_ads_context"})
