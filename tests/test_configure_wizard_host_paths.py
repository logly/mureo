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


# ---------------------------------------------------------------------------
# #407 — host + host_paths must be captured as one atomic, consistent pair.
# Reading ``session.host`` and ``host_paths`` as two separate accesses lets a
# concurrent ``set_host`` land between them and pair one host with another
# host's paths bundle. ``host_snapshot()`` captures both under one lock.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_host_snapshot_pairs_host_with_its_own_paths(tmp_path: Path) -> None:
    wizard = server_mod.ConfigureWizard(home=tmp_path)
    snap = wizard.host_snapshot()
    assert snap.host == wizard.session.host
    assert snap.paths is wizard.host_paths
    # The bundle was built for that same host — never a cross-host mismatch.
    assert snap.paths.host == snap.host


@pytest.mark.unit
def test_host_snapshot_reflects_a_host_switch(tmp_path: Path) -> None:
    wizard = server_mod.ConfigureWizard(home=tmp_path)
    assert wizard.host_snapshot().host == "claude-code"
    wizard.set_host("codex")
    snap = wizard.host_snapshot()
    assert snap.host == "codex"
    assert snap.paths.host == "codex"


@pytest.mark.unit
def test_host_snapshot_is_immutable(tmp_path: Path) -> None:
    import dataclasses

    wizard = server_mod.ConfigureWizard(home=tmp_path)
    snap = wizard.host_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.host = "codex"  # type: ignore[misc]
    # A later switch must not mutate an already-captured snapshot.
    wizard.set_host("codex")
    assert snap.host == "claude-code"


@pytest.mark.unit
def test_concurrent_switch_keeps_snapshots_consistent(tmp_path: Path) -> None:
    """Under a concurrent host switch, every snapshot pairs a host with ITS
    OWN paths bundle — never host A with host B's paths (#407)."""
    wizard = server_mod.ConfigureWizard(home=tmp_path)
    hosts = ("claude-code", "codex")
    stop = threading.Event()
    errors: list[str] = []

    def flip() -> None:
        for i in range(400):
            wizard.set_host(hosts[i % 2])
        stop.set()

    def observe() -> None:
        while not stop.is_set():
            snap = wizard.host_snapshot()
            if snap.paths.host != snap.host:
                errors.append(f"{snap.host} paired with {snap.paths.host}'s paths")

    switcher = threading.Thread(target=flip)
    observer = threading.Thread(target=observe)
    switcher.start()
    observer.start()
    switcher.join(timeout=10)
    observer.join(timeout=10)
    assert not switcher.is_alive() and not observer.is_alive()
    assert not errors, errors[:3]


@pytest.mark.unit
def test_pairing_handlers_use_the_atomic_snapshot() -> None:
    """The two handlers that read BOTH host and host_paths in one request now
    go through host_snapshot() rather than two separate wizard reads (#407)."""
    src = (Path(server_mod.__file__).resolve().parent / "handlers.py").read_text(
        encoding="utf-8"
    )
    assert src.count("host_snapshot()") >= 2
    # The old torn pairing (a separate session.host read feeding collect_status
    # alongside the live host_paths) is gone.
    assert "paths=self.wizard.host_paths" not in src
