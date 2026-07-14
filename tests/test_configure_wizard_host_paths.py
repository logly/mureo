"""``ConfigureWizard`` host-path resolution must be atomic (#406).

The configure server is threaded (``ThreadingMixIn``). ``set_host()``
used to publish the freshly rebuilt base ``HostPaths`` FIRST and only
then re-apply the credentials-path override (#194/#196), so any request
handled during that window read — or worse, wrote — the unresolved
host-default credentials path instead of the runtime-resolved one.
With a registered runtime-context factory the override resolution takes
long enough that a dashboard page load hit the window in 27/30 live
attempts, rendering every saved credential as ✗.

These tests pin the two halves of the fix: a no-op ``set_host`` (same
host — sent by every dashboard POST) must not rebuild at all, and a real
host switch must never expose a torn intermediate to other threads.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import mureo.web.server as server_mod


@pytest.mark.unit
def test_set_host_same_host_does_not_rebuild(tmp_path: Path) -> None:
    """Every dashboard POST carries the current host; re-resolving the
    bundle each time reopens the race window and repeats a potentially
    slow runtime-context resolution for nothing."""
    wizard = server_mod.ConfigureWizard(home=tmp_path)
    before = wizard.host_paths
    wizard.set_host(wizard.session.host)
    assert wizard.host_paths is before


@pytest.mark.unit
def test_set_host_never_publishes_unresolved_credentials_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the credentials override is still resolving, concurrent
    readers must keep seeing the previous fully-resolved bundle."""
    resolved_path = Path("/resolved/credentials.json")
    entered = threading.Event()
    release = threading.Event()

    def slow_resolve(default: Path) -> Path:
        entered.set()
        assert release.wait(timeout=10), "test deadlock: release never set"
        return resolved_path

    monkeypatch.setattr(server_mod, "runtime_credentials_path", slow_resolve)

    # __init__ resolves once — let it through immediately.
    release.set()
    wizard = server_mod.ConfigureWizard(home=None)
    assert wizard.host_paths.credentials_path == resolved_path

    # Now block the resolver and switch hosts from another thread.
    entered.clear()
    release.clear()
    switcher = threading.Thread(target=wizard.set_host, args=("claude-desktop",))
    switcher.start()
    try:
        assert entered.wait(timeout=10), "set_host never reached the resolver"
        # Mid-flight: the torn base bundle (host-default credentials path)
        # must NOT be visible — readers see the old resolved value.
        assert wizard.host_paths.credentials_path == resolved_path, (
            "set_host published an unresolved credentials path mid-rebuild "
            "(#406 race window)"
        )
    finally:
        release.set()
        switcher.join(timeout=10)

    assert not switcher.is_alive()
    assert wizard.host_paths.credentials_path == resolved_path
    assert wizard.host_paths.host == "claude-desktop"
