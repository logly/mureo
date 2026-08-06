"""One MCP session per capture probe sequence (TDD, #520).

``AmazonAdsBridge._call`` opens a fresh ``streamablehttp_client`` +
``ClientSession.initialize()`` for EVERY forwarded call. That was fine while a
dispatch was one call, but the #121 before-state capture issues one read per ad
product probed, so a five-probe capture paid five handshakes — and the
handshake, not the query, is a capture's dominant latency term.

``AmazonAdsBridge.batch_dispatch()`` opens ONE session for a whole sequence and
yields the same ``(name, arguments) -> awaitable`` dispatch the capture module
and every fake already speak, so nothing outside the bridge changes.

Everything Amazon-side is faked, and what the fakes count is exactly the thing
under test: handshakes, sessions, and closes.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import time
from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads import reversal as rev
from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.amazon_ads.lwa import LwaTokens
from mureo.auth import AmazonAdsCredentials

# The same deterministic clock the non-batched deadline test drives, so both
# halves of the bound are exercised the same way rather than two ways.
from tests.test_amazon_reversal import _FakeClock

if TYPE_CHECKING:
    from pathlib import Path

_ACCOUNT = {"profileId": "1234567890"}

_MANIFEST: dict[str, Any] = {
    "generated_at": "2026-08-05T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [],
}


class _FakeSession:
    """Records its handshake and every call on the shared transport log."""

    def __init__(self, transport: _FakeTransport, number: int) -> None:
        self._transport = transport
        self._number = number

    async def initialize(self) -> None:
        if self._transport.fail_handshake:
            raise RuntimeError("handshake refused")
        self._transport.handshakes.append(self._number)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        from mcp.types import TextContent

        self._transport.calls.append((self._number, name, copy.deepcopy(arguments)))
        payload = self._transport.next_payload()
        if isinstance(payload, BaseException):
            raise payload
        if payload is _HANG:
            await asyncio.Event().wait()  # never returns
        return type(
            "R", (), {"content": [TextContent(type="text", text=json.dumps(payload))]}
        )()


class _FakeConnection:
    def __init__(self, transport: _FakeTransport, number: int) -> None:
        self._transport = transport
        self._number = number

    async def __aenter__(self) -> _FakeSession:
        return _FakeSession(self._transport, self._number)

    async def __aexit__(self, *exc: Any) -> bool:
        self._transport.closing.append(self._number)
        if self._transport.hang_close:
            # A transport that never finishes closing — the case the batch's
            # close bound, and its cancel-and-cut-loose fallback, exist for.
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self._transport.close_cancelled.append(self._number)
                raise
        self._transport.closed.append(self._number)
        return False


#: Sentinel payload: the call never returns (a hung endpoint).
_HANG = object()


class _FakeTransport:
    """Connect factory that makes handshakes countable.

    ``payloads`` is consumed in call order across every session it opens — a
    dict (JSON-encoded into a ``TextContent``), an exception to raise, or
    :data:`_HANG`. A missing entry yields an empty envelope.
    """

    def __init__(
        self,
        payloads: list[Any] | None = None,
        *,
        fail_handshake: bool = False,
        hang_close: bool = False,
    ) -> None:
        self._payloads = list(payloads or [])
        self.fail_handshake = fail_handshake
        self.hang_close = hang_close
        self.headers: list[dict[str, str]] = []
        self.handshakes: list[int] = []
        self.calls: list[tuple[int, str, dict[str, Any]]] = []
        self.closing: list[int] = []
        self.closed: list[int] = []
        self.close_cancelled: list[int] = []

    def __call__(self, url: str, headers: dict[str, str]) -> _FakeConnection:
        self.headers.append(dict(headers))
        return _FakeConnection(self, len(self.headers))

    def next_payload(self) -> Any:
        return self._payloads.pop(0) if self._payloads else {}

    @property
    def sessions(self) -> int:
        return len(self.headers)

    @property
    def call_sessions(self) -> list[int]:
        return [c[0] for c in self.calls]


def _creds(**kw: Any) -> AmazonAdsCredentials:
    base: dict[str, Any] = {"client_id": "cid", "access_token": "Atza|OLD"}
    base.update(kw)
    return AmazonAdsCredentials(**base)


def _refreshable() -> AmazonAdsCredentials:
    return _creds(refresh_token="Atzr|R", client_secret="sec")


def _bridge(
    tmp_path: Path,
    transport: _FakeTransport,
    *,
    creds: AmazonAdsCredentials | None = None,
    refresher: Any = None,
    token_saver: Any = None,
) -> AmazonAdsBridge:
    mp = tmp_path / "amazon_tools.json"
    mp.write_text(json.dumps(_MANIFEST))
    resolved = creds if creds is not None else _creds()
    return AmazonAdsBridge(
        manifest_path=mp,
        creds_loader=lambda: resolved,
        connect=transport,
        refresher=refresher,
        token_saver=token_saver,
    )


def _mutation(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"body": {"accessRequestedAccount": dict(_ACCOUNT), "campaigns": items}}


_UPDATE = "campaign_management-update_campaign_state"
_QUERY = "campaign_management-query_campaign"


@pytest.fixture(autouse=True)
def _no_learned_ad_products() -> Any:
    """The id → ad-product cache is process-local; isolate every test from it."""
    rev.clear_ad_product_cache()
    yield
    rev.clear_ad_product_cache()


@pytest.mark.unit
class TestOneSessionPerSequence:
    async def test_a_five_probe_capture_opens_exactly_one_session(
        self, tmp_path: Path
    ) -> None:
        """The whole point of #520: N reads, ONE handshake (was N)."""
        t = _FakeTransport(
            [
                {"campaigns": []},
                {"campaigns": []},
                {"campaigns": []},
                {"campaigns": []},
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
            ]
        )
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert len(t.calls) == 5  # one read per ad product, as before
        assert t.handshakes == [1]  # …but a single handshake for all five
        assert t.sessions == 1
        assert t.closed == [1]

    async def test_the_single_call_path_still_opens_one_session_per_call(
        self, tmp_path: Path
    ) -> None:
        """``handle_mcp_tool`` is unchanged: one session per forwarded call."""
        t = _FakeTransport([{"ok": 1}, {"ok": 2}])
        b = _bridge(tmp_path, t)
        await b.handle_mcp_tool("campaign_management-x", {})
        await b.handle_mcp_tool("campaign_management-x", {})
        assert t.handshakes == [1, 2]
        assert t.closed == [1, 2]

    async def test_the_batch_yields_a_plain_dispatch_callable(
        self, tmp_path: Path
    ) -> None:
        """No transport object may leak out of the bridge."""
        t = _FakeTransport([{"campaigns": []}, {"campaigns": []}])
        b = _bridge(tmp_path, t)
        async with b.batch_dispatch() as dispatch:
            assert asyncio.iscoroutinefunction(dispatch)
            assert not hasattr(dispatch, "call_tool")
            assert not hasattr(dispatch, "initialize")
            first = await dispatch(_QUERY, {"body": {}})
            await dispatch(_QUERY, {"body": {}})
            assert isinstance(first, list)
        assert t.handshakes == [1]
        assert t.closed == [1]

    async def test_a_batch_that_dispatches_nothing_opens_nothing(
        self, tmp_path: Path
    ) -> None:
        t = _FakeTransport([])
        b = _bridge(tmp_path, t)
        async with b.batch_dispatch():
            pass
        assert t.sessions == 0
        assert t.closed == []

    async def test_a_portfolio_capture_is_still_a_single_read(
        self, tmp_path: Path
    ) -> None:
        t = _FakeTransport(
            [{"portfolios": [{"portfolioId": "P1", "state": "ENABLED"}]}]
        )
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            "campaign_management-update_portfolio",
            {
                "body": {
                    "accessRequestedAccount": dict(_ACCOUNT),
                    "portfolios": [{"portfolioId": "P1", "state": "PAUSED"}],
                }
            },
        )
        assert out is not None
        assert t.handshakes == [1]
        assert len(t.calls) == 1


@pytest.mark.unit
class TestRefreshInvalidatesTheSession:
    """``request_headers`` is built per session, so a token refreshed
    mid-sequence cannot apply to an already-open one: the batch closes it,
    opens a new one on the new token, and retries just that call."""

    async def test_a_refresh_reopens_once_and_retries_only_that_call(
        self, tmp_path: Path
    ) -> None:
        saved: list[tuple[str, str | None]] = []
        refreshed: list[str] = []

        def refresher(c: AmazonAdsCredentials) -> LwaTokens:
            refreshed.append(c.access_token)
            return LwaTokens("Atza|NEW", "Atzr|R2", 3600)

        t = _FakeTransport(
            [
                {"campaigns": []},  # probe 1, session 1
                RuntimeError("401 token expired"),  # probe 2, session 1
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},  # retry
            ]
        )
        b = _bridge(
            tmp_path,
            t,
            creds=_refreshable(),
            refresher=refresher,
            token_saver=lambda a, r: saved.append((a, r)),
        )
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is not None
        assert refreshed == ["Atza|OLD"]  # exactly one LwA exchange
        assert saved == [("Atza|NEW", "Atzr|R2")]
        assert t.handshakes == [1, 2]  # reopened exactly once
        assert t.headers[0]["Authorization"] == "Bearer Atza|OLD"
        assert t.headers[1]["Authorization"] == "Bearer Atza|NEW"
        # Only the failing call is replayed — and on the NEW session.
        assert t.call_sessions == [1, 1, 2]
        assert t.calls[2][2] == t.calls[1][2]
        assert t.closed == [1, 2]  # the invalidated session is closed, not leaked

    async def test_the_refresh_budget_is_one_per_batch(self, tmp_path: Path) -> None:
        """A refresh must not become a way to retry indefinitely mid-sequence."""
        refreshed: list[str] = []

        def refresher(c: AmazonAdsCredentials) -> LwaTokens:
            refreshed.append(c.access_token)
            return LwaTokens("Atza|NEW", "Atzr|R2", 3600)

        t = _FakeTransport(
            [
                {"campaigns": []},  # probe 1
                RuntimeError("401 token expired"),  # probe 2 → refresh + retry
                {"campaigns": []},  # probe 2 retry, session 2
                RuntimeError("401 again"),  # probe 3 → budget spent, no refresh
            ]
        )
        b = _bridge(
            tmp_path,
            t,
            creds=_refreshable(),
            refresher=refresher,
            token_saver=lambda a, r: None,
        )
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is None  # nothing was readable
        assert refreshed == ["Atza|OLD"]  # ONE exchange for the whole sequence
        assert t.handshakes == [1, 2]
        assert len(t.calls) == 4

    async def test_without_refresh_material_a_failure_is_never_refreshed(
        self, tmp_path: Path
    ) -> None:
        refreshed: list[str] = []

        def refresher(c: AmazonAdsCredentials) -> LwaTokens:
            refreshed.append(c.access_token)
            return LwaTokens("Atza|NEW", "Atzr|R2", 3600)

        t = _FakeTransport([RuntimeError("boom")])
        b = _bridge(tmp_path, t, refresher=refresher)
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is None
        assert refreshed == []
        assert t.handshakes == [1]


@pytest.mark.unit
class TestPartialSequence:
    """A failure partway through leaves the already-completed probes usable —
    the contract ``reversal.py`` turns into caveats + a PARTIAL plan."""

    async def test_a_mid_sequence_failure_keeps_the_completed_probes(
        self, tmp_path: Path
    ) -> None:
        t = _FakeTransport(
            [
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
                RuntimeError("Amazon read failed"),
            ]
        )
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            _UPDATE,
            _mutation(
                [
                    {"campaignId": "C1", "state": "PAUSED"},
                    {"campaignId": "C2", "state": "PAUSED"},
                ]
            ),
        )
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("C2" in c for c in out["caveats"])
        assert t.closed == [1]  # a failing probe leaves no open transport

    async def test_a_failed_handshake_closes_the_transport(
        self, tmp_path: Path
    ) -> None:
        """A session that never finished opening must not leak either."""
        t = _FakeTransport([], fail_handshake=True)
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is None
        assert t.sessions == 1
        assert t.handshakes == []
        assert t.closed == [1]

    async def test_teardown_runs_when_the_body_raises(self, tmp_path: Path) -> None:
        t = _FakeTransport([{"campaigns": []}])
        b = _bridge(tmp_path, t)
        with pytest.raises(ValueError, match="boom"):
            async with b.batch_dispatch() as dispatch:
                await dispatch(_QUERY, {"body": {}})
                raise ValueError("boom")
        assert t.closed == [1]


@pytest.mark.unit
class TestBoundsStillHold:
    async def test_a_hung_read_is_bounded_and_still_tears_the_session_down(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The read hangs forever, so the PER-READ timeout is the only thing
        that can end this call at all — reaching the assertions IS the proof
        that the read was bounded. They are therefore on observable state,
        never on elapsed time: a wall-clock ceiling would add nothing a hung
        read has not already demonstrated, and a margin a loaded runner can
        overshoot (#542).

        The OUTER capture deadline is NOT exercised here. It is patched only
        so that it cannot be the binding half of ``min(READ_TIMEOUT_SECONDS,
        budget)``; the walk ends at the first hung probe, long before the
        deadline could expire. The test that drives the deadline itself — with
        reads that return well inside their own timeout, so only the deadline
        can stop the walk — is ``test_amazon_reversal.py::TestAdProductFilter
        ::test_slow_reads_stop_at_the_capture_deadline``.
        """
        monkeypatch.setattr(rev, "READ_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(rev, "CAPTURE_DEADLINE_SECONDS", 0.5)
        # ONE payload, because exactly one read happens: a timed-out probe ends
        # the walk, so the other four ad products are never probed. (Were the
        # walk to carry on, the missing payloads would return empty envelopes
        # and the read count below would catch it.)
        t = _FakeTransport([_HANG])
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            _UPDATE, _mutation([{"campaignId": "C1", "state": "PAUSED"}])
        )
        assert out is None
        assert len(t.calls) == 1  # not the whole ad-product enum
        assert t.closed == [1]  # the hung session is still torn down…
        assert t.close_cancelled == []  # …gracefully, without the cancel fallback
        assert _owner_tasks() == []  # nothing left holding a live session

    async def test_the_capture_deadline_stops_the_walk_on_the_batched_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The OUTER deadline against the batch — the combination that every
        real capture has run through since #520, and the one the test above
        does NOT reach.

        Every read returns immediately, well inside its own timeout (which is
        the whole remaining budget here: 9s, then 3s), so nothing except the
        capture deadline can end this walk. ``_monotonic`` is faked, so the
        deadline expires on a read COUNT and never on wall clock — every
        assertion below is a count or a state, none is an elapsed time (#542).
        The non-batched twin is ``test_amazon_reversal.py::TestAdProductFilter
        ::test_slow_reads_stop_at_the_capture_deadline``.
        """
        monkeypatch.setattr(rev, "CAPTURE_DEADLINE_SECONDS", 15.0)
        # 0.0 sets the deadline, then 6.0 and 12.0 leave a budget; 18.0 does
        # not, so the walk stops before a third probe rather than at the end
        # of the five-product enum.
        monkeypatch.setattr(rev, "_monotonic", _FakeClock(step=6.0))
        t = _FakeTransport(
            [
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
                {"campaigns": []},
                # Deliberately never read: were the deadline to stop bounding
                # the walk, this third probe would resolve C2 and the read
                # count below would say so.
                {"campaigns": [{"campaignId": "C2", "state": "ENABLED"}]},
            ]
        )
        b = _bridge(tmp_path, t)
        out = await b.capture_reversal(
            _UPDATE,
            _mutation(
                [
                    {"campaignId": "C1", "state": "PAUSED"},
                    {"campaignId": "C2", "state": "PAUSED"},
                ]
            ),
        )
        assert len(t.calls) == 2  # two probes fit the budget, the third does not
        assert t.sessions == 1  # …and the whole bounded walk shared ONE session
        assert t.handshakes == [1]
        assert t.closed == [1]
        # What was captured before the deadline is kept; the entity that ran
        # out of time is a caveat, not a guess.
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("C2" in c for c in out["caveats"])

    async def test_a_cancelled_call_still_leaves_the_session_closable(
        self, tmp_path: Path
    ) -> None:
        """Same rule: leaving the ``async with`` at all is the bound being
        demonstrated, so nothing here reads a clock either (#542)."""
        t = _FakeTransport([_HANG])
        b = _bridge(tmp_path, t)
        async with b.batch_dispatch() as dispatch:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(dispatch(_QUERY, {"body": {}}), timeout=0.1)
        assert t.closed == [1]
        assert t.close_cancelled == []  # closed gracefully, not cut loose
        assert _owner_tasks() == []


def _owner_tasks() -> list[asyncio.Task[Any]]:
    """The batch session-owner tasks currently alive on this loop."""
    return [
        t
        for t in asyncio.all_tasks()
        if "SessionBatch._serve" in repr(getattr(t, "get_coro", lambda: None)())
    ]


async def _until(predicate: Any, *, limit: float = 2.0) -> None:
    """Poll ``predicate`` on the loop instead of guessing at sleep lengths."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition was never reached")


@pytest.mark.unit
class TestCancellationDuringTeardown:
    """mureo's MCP server runs each tool call in a task and cancels it when the
    client goes away, so a capture can be cancelled *while it is closing*. The
    close must survive its own caller's cancellation: ``asyncio.wait`` does NOT
    cancel what it waits on, so a cancellation landing there would otherwise
    leave the session-owner task running detached with a live Amazon session
    and nothing left holding a reference to it.
    """

    async def test_cancelling_a_batch_mid_close_still_kills_the_session_owner(
        self, tmp_path: Path
    ) -> None:
        t = _FakeTransport([{"campaigns": []}], hang_close=True)
        b = _bridge(tmp_path, t)

        async def _body() -> None:
            async with b.batch_dispatch() as dispatch:
                await dispatch(_QUERY, {"body": {}})
            # …and the close hangs, so this task is now parked inside aclose().

        task = asyncio.create_task(_body())
        await _until(lambda: t.closing == [1])
        owners = _owner_tasks()
        assert len(owners) == 1
        task.cancel()  # lands on aclose()'s own await
        with pytest.raises(asyncio.CancelledError):
            await task
        await _until(lambda: owners[0].done())
        assert owners[0].done()  # not left running detached
        assert t.close_cancelled == [1]  # the transport was cut loose, not leaked

    async def test_a_capture_cancelled_during_teardown_propagates(
        self, tmp_path: Path
    ) -> None:
        """Capture is best-effort, but a cancellation is not a capture failure:
        swallowing it would suppress the caller's own cancellation."""
        t = _FakeTransport([{"campaigns": []}] * 5, hang_close=True)
        b = _bridge(tmp_path, t)
        task = asyncio.create_task(
            b.capture_reversal(_UPDATE, _mutation([{"campaignId": "C1"}]))
        )
        await _until(lambda: t.closing == [1])
        owners = _owner_tasks()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _until(lambda: all(o.done() for o in owners))
        assert t.close_cancelled == [1]

    async def test_an_ordinary_capture_failure_is_still_swallowed(
        self, tmp_path: Path
    ) -> None:
        """The best-effort contract is unchanged for everything that is NOT a
        cancellation: the mutation must never be blocked by a failed read."""
        t = _FakeTransport([RuntimeError("Amazon read failed")])
        b = _bridge(tmp_path, t)
        assert (
            await b.capture_reversal(_UPDATE, _mutation([{"campaignId": "C1"}])) is None
        )


_E2E_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"body": {"type": "object"}},
    "required": ["body"],
}

_E2E_MANIFEST: dict[str, Any] = {
    "generated_at": "2026-08-05T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [
        {
            "name": _UPDATE,
            "description": "Update campaign state.",
            "inputSchema": _E2E_UPDATE_SCHEMA,
        },
        {
            "name": _QUERY,
            "description": "Query campaigns.",
            "inputSchema": _E2E_UPDATE_SCHEMA,
            "annotations": {"readOnlyHint": True},
        },
    ],
}


class _E2ETransport(_FakeTransport):
    """Amazon side for the end-to-end plan test: the first read resolves C1,
    the second blows up, and the mutation itself always succeeds."""

    def next_payload(self) -> Any:
        name = self.calls[-1][1]
        if name != _QUERY:
            return {"success": True}
        return super().next_payload()


class _HangingWriteTransport(_FakeTransport):
    """The before-state read succeeds; the MUTATION never returns — so a
    cancellation lands while the write is in flight."""

    def next_payload(self) -> Any:
        if self.calls[-1][1] == _QUERY:
            return {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}
        return _HANG


class _HangingReadTransport(_FakeTransport):
    """The before-state READ never returns; the mutation would succeed if the
    dispatch ever got that far. Stands in for the ordinary case — a capture
    spends nearly all its wall clock inside a probe read, so that is where a
    client going away actually lands."""

    def next_payload(self) -> Any:
        return {"success": True} if self.calls[-1][1] != _QUERY else _HANG


def _reload_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transport: Any,
    *,
    creds: AmazonAdsCredentials | None = None,
    refresher: Any = None,
):
    from mureo.amazon_ads import bridge as bmod
    from mureo.mcp import plugin_audit

    mp = tmp_path / "amazon_tools.json"
    mp.write_text(json.dumps(_E2E_MANIFEST))
    resolved = creds if creds is not None else _creds(access_token="Atza|S")
    monkeypatch.setattr(
        "mureo.core.providers.registry.discover_providers", lambda **_kw: ()
    )
    monkeypatch.setattr(bmod, "manifest_path", lambda: mp)
    monkeypatch.setattr(bmod, "load_amazon_ads_credentials", lambda *a, **k: resolved)
    monkeypatch.setattr(bmod, "_default_connect", transport)
    if refresher is not None:
        # The server builds the bridge zero-arg at import, so the DEFAULT
        # refresher is what a cancelled call would reach for.
        monkeypatch.setattr(bmod, "refresh_access_token", refresher)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    from mureo.mcp import server as mod

    return importlib.reload(mod)


@pytest.mark.integration
class TestEndToEndPartialPlan:
    async def test_a_session_death_mid_sequence_still_yields_a_partial_plan(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.context.models import StateDocument
        from mureo.context.state import read_state_file, write_state_file
        from mureo.rollback.models import RollbackStatus
        from mureo.rollback.planner import plan_rollback

        write_state_file(tmp_path / "STATE.json", StateDocument())
        monkeypatch.chdir(tmp_path)
        t = _E2ETransport(
            [
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
                RuntimeError("the session died"),
            ]
        )
        mod = _reload_server(monkeypatch, tmp_path, t)
        try:
            args = {
                "body": {
                    "accessRequestedAccount": dict(_ACCOUNT),
                    "campaigns": [
                        {"campaignId": "C1", "state": "PAUSED"},
                        {"campaignId": "C2", "state": "PAUSED"},
                    ],
                }
            }
            out = await mod.handle_call_tool(_UPDATE, copy.deepcopy(args))
            assert out  # the mutation still ran
            entry = read_state_file(tmp_path / "STATE.json").action_log[0]
            assert entry.reversible_params is not None
            plan = plan_rollback(entry)
            assert plan is not None
            assert plan.status is RollbackStatus.PARTIAL
            assert plan.params is not None
            assert plan.params["body"]["campaigns"] == [
                {"campaignId": "C1", "state": "ENABLED"}
            ]
            assert any("C2" in c for c in plan.caveats)
            # Both probes shared ONE session; the mutation is an ordinary
            # single call and opens its own, exactly as before.
            assert t.call_sessions == [1, 1, 2]
            assert t.handshakes == [1, 2]
            assert t.closed == [1, 2]
        finally:
            importlib.reload(mod)

    async def test_a_cancel_during_the_read_propagates_and_never_mutates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A client that goes away mid-READ must not get a mutation anyway.

        The read is where a capture spends nearly all of its wall clock, so
        this — not the teardown — is where a real cancellation lands. The
        per-probe loop absorbs every read failure on purpose (that is what
        makes a capture best-effort), and a cancellation is NOT one: absorbing
        it here would suppress the caller's own cancellation UNDERNEATH every
        best-effort boundary above, and the write would go ahead for a caller
        that is no longer waiting for the result.
        """
        from mureo.context.models import StateDocument
        from mureo.context.state import read_state_file, write_state_file

        write_state_file(tmp_path / "STATE.json", StateDocument())
        monkeypatch.chdir(tmp_path)
        t = _HangingReadTransport()
        mod = _reload_server(monkeypatch, tmp_path, t)
        try:
            args = {
                "body": {
                    "accessRequestedAccount": dict(_ACCOUNT),
                    "campaigns": [{"campaignId": "C1", "state": "PAUSED"}],
                }
            }
            task = asyncio.create_task(mod.handle_call_tool(_UPDATE, args))
            await _until(lambda: bool(t.calls))  # the read is in flight
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert [c[1] for c in t.calls] == [_QUERY]  # the write never ran
            assert read_state_file(tmp_path / "STATE.json").action_log == ()
            await _until(lambda: t.closed == [1])  # …and the session is closed
        finally:
            importlib.reload(mod)

    async def test_a_cancel_during_the_write_never_re_issues_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The same rule on the ordinary single-call path.

        ``handle_mcp_tool`` refreshes and retries on any first failure while
        the 401 shape is unobserved. A cancellation is not a failure: retrying
        would issue a SECOND WRITE to a live ad account for a caller that has
        already disconnected, and returning its result would swallow the
        cancellation whole.
        """
        from mureo.amazon_ads.lwa import LwaTokens
        from mureo.context.models import StateDocument
        from mureo.context.state import read_state_file, write_state_file

        write_state_file(tmp_path / "STATE.json", StateDocument())
        monkeypatch.chdir(tmp_path)
        refreshed: list[int] = []
        t = _HangingWriteTransport()
        mod = _reload_server(
            monkeypatch,
            tmp_path,
            t,
            creds=_refreshable(),
            refresher=lambda c: (
                refreshed.append(1) or LwaTokens("Atza|NEW", "Atzr|R2", 3600)
            ),
        )
        try:
            args = {
                "body": {
                    "accessRequestedAccount": dict(_ACCOUNT),
                    "campaigns": [{"campaignId": "C1", "state": "PAUSED"}],
                }
            }
            task = asyncio.create_task(mod.handle_call_tool(_UPDATE, args))
            await _until(lambda: any(c[1] == _UPDATE for c in t.calls))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                # Bounded deliberately: an unguarded bridge re-issues the write
                # and blocks on the same never-returning call, so an unbounded
                # await would hang the suite instead of failing it.
                await asyncio.wait_for(task, timeout=5)
            # Exactly ONE write attempt, no second session for a retry, and no
            # LwA exchange spent on a caller that gave up.
            assert [c[1] for c in t.calls].count(_UPDATE) == 1
            assert refreshed == []
            assert read_state_file(tmp_path / "STATE.json").action_log == ()
        finally:
            importlib.reload(mod)
