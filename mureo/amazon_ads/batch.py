"""One MCP session shared across a sequence of bridged calls (#520).

:meth:`mureo.amazon_ads.bridge.AmazonAdsBridge._call` opens a fresh
``streamablehttp_client`` + ``ClientSession.initialize()`` handshake for every
forwarded call. That is right for a one-shot dispatch, but the #121
before-state capture issues one read per ad product probed, and the handshake
— not the query — is that sequence's dominant latency term.

This module implements the session-scoped batch behind
:meth:`AmazonAdsBridge.batch_dispatch`: ONE session for a whole sequence,
exposed as the same ``(name, arguments) -> awaitable`` dispatch the capture
module and every test fake already depend on. No transport object leaves the
bridge.

Why the session lives in its own task
-------------------------------------
The transport is anyio-based (task groups, cancel scopes), and a cancel scope
MUST be exited by the task that entered it. A caller may legitimately drive
each call from a different task — ``asyncio.wait_for`` wraps the awaited
coroutine in a Task on Python 3.10/3.11, and that is exactly how
:func:`mureo.amazon_ads.reversal._read_once` applies its per-read timeout — so
a session opened inside one call and closed at batch exit would be entered and
exited in different tasks. :class:`SessionBatch` therefore parks the session's
whole lifetime (open, reopen, close) in one long-lived task and hands the
*session object* to callers: using a session across tasks is safe, entering and
exiting its scopes is not.

Refresh budget: ONE per batch
-----------------------------
``request_headers(creds)`` is baked into a session at open time, so a token
refreshed mid-sequence cannot apply to an already-open session. A refresh
therefore invalidates the batch session: the old one is closed, a new one is
opened on the new token, and the call that triggered the refresh — and only
that call — is retried on it. The budget is **one LwA exchange per batch**
(minting a missing access token counts as it), so a sequence of N calls can
never turn into N refreshes; the existing single-call path keeps its own
one-shot-per-call budget, unchanged. A capture stops probing at its first
failure anyway, so at most one refresh is ever reachable in practice.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.core.control_flow import STOP_EXCEPTIONS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mureo.amazon_ads.bridge import ConnectFactory
    from mureo.amazon_ads.session_auth import SessionCredentials
    from mureo.auth import AmazonAdsCredentials

    #: Forward one call on an already-open session, normalising an
    #: Amazon-declared failure — ``AmazonAdsBridge._invoke``.
    Invoke = Callable[[Any, str, dict[str, Any]], Awaitable[list[Any]]]

logger = logging.getLogger(__name__)

#: Ceiling on how long :meth:`SessionBatch.aclose` waits for the session-owner
#: task to close the transport politely (the MCP session-termination request,
#: which is why a graceful close is worth a moment at all — the same one every
#: single-call session already performs today, now once per sequence instead of
#: once per read). An idle session unwinds in a single event-loop turn; only a
#: transport hung *inside* its own close can reach this bound, and it is then
#: cancelled and cut loose rather than held on to. Reads stay bounded by
#: :data:`mureo.amazon_ads.reversal.CAPTURE_DEADLINE_SECONDS`; this is the only
#: thing that can be spent after them, and only on a pathological close.
SESSION_CLOSE_TIMEOUT = 2.0

#: Raised to a caller waiting on a session the batch will never produce
#: (teardown won the race). Message only — the caller treats any failure the
#: same way.
_CLOSED_MESSAGE = "the Amazon batch session is closed"


class SessionBatch:
    """One live MCP session, shared by every call made through :meth:`dispatch`.

    Lazy: nothing is opened until the first dispatch, so a batch that probes
    nothing costs nothing. Sequential by construction — the capture probes one
    read at a time, and the lock makes that an invariant rather than an
    assumption, which is what lets the reopen handshake be raced-free.
    """

    def __init__(
        self,
        *,
        connect: ConnectFactory,
        invoke: Invoke,
        auth: SessionCredentials,
    ) -> None:
        self._connect = connect
        self._invoke = invoke
        self._auth = auth
        self._creds: AmazonAdsCredentials | None = None
        self._owner: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[Any] | None = None
        self._reopen = asyncio.Event()
        self._lock = asyncio.Lock()
        self._closing = False
        self._refresh_spent = False

    # -- the dispatch handed to callers -------------------------------------

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        """Forward one call on the batch's session — the ``Dispatch`` seam.

        Same shape and same failure contract as
        :meth:`AmazonAdsBridge.handle_mcp_tool`: an Amazon-declared failure
        comes back as the normalised ``API error:`` envelope, and anything
        raised is raised. A raised failure spends the batch's single refresh
        (see the module docstring) if one is still available.

        A stop — :data:`mureo.core.control_flow.STOP_EXCEPTIONS` — is never a
        refreshable failure, here or on the single-call path: a cancellation
        means the caller stopped waiting, not that the token expired, and a
        retry would re-issue the call for nobody while an LwA exchange and a
        reopened session are spent on it. One rule across the whole bridge.
        """
        async with self._lock:
            try:
                session = await self._session()
                return await self._invoke(session, name, arguments)
            except STOP_EXCEPTIONS:
                raise
            except BaseException as first_exc:
                creds = self._creds
                if creds is None or not self._may_refresh(creds):
                    raise
                return await self._refresh_and_retry(creds, name, arguments, first_exc)

    def _may_refresh(self, creds: AmazonAdsCredentials) -> bool:
        """Is the batch's single LwA exchange still available and usable?"""
        return bool(
            not self._refresh_spent
            and not self._closing
            and creds.refresh_token
            and creds.client_secret
        )

    async def _refresh_and_retry(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
        first_exc: BaseException,
    ) -> list[Any]:
        """Refresh the token once, reopen the session, retry exactly this call.

        The budget is marked spent BEFORE the exchange, so a refresh that
        itself fails cannot be attempted twice. ``first_exc`` is always chained
        so the original failure is never lost, exactly as on the single-call
        path.
        """
        self._refresh_spent = True
        self._creds = self._auth.refresh_and_persist(
            creds,
            cause=first_exc,
            auth_failure_prefix="Amazon access token expired and refresh failed",
        )
        try:
            session = await self._reopen_session()
            return await self._invoke(session, name, arguments)
        except STOP_EXCEPTIONS:
            raise  # a stop is not "the retry failed"; do not chain it
        except BaseException as retry_exc:
            raise retry_exc from first_exc

    # -- session lifetime, all of it inside ``_serve``'s task ---------------

    async def _session(self) -> Any:
        """The batch's live session, starting the owner task on first use.

        Shielded: a caller cancelled while waiting for the handshake must not
        cancel the handshake itself — the session is shared, and the next call
        (or the teardown) still needs it.
        """
        if self._ready is None:
            creds, minted = self._auth.resolve()
            self._creds = creds
            self._refresh_spent = minted
            self._ready = asyncio.get_running_loop().create_future()
            self._owner = asyncio.create_task(self._serve())
        return await asyncio.shield(self._ready)

    async def _reopen_session(self) -> Any:
        """Ask the owner task to close this session and open one on the new token."""
        ready: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._ready = ready
        self._reopen.set()
        return await asyncio.shield(ready)

    async def _serve(self) -> None:
        """Own every session this batch opens — open, publish, close — here.

        One task for the batch's whole life, because the transport's cancel
        scopes must be entered and exited by the same task (see the module
        docstring). An open that fails is published to whoever is waiting and
        then the task STAYS ALIVE, so the refresh path can still ask for a new
        session; only teardown ends it.
        """
        ready = self._ready
        if ready is None:  # pragma: no cover — set before the task is created
            return
        try:
            while not self._closing:
                self._reopen = asyncio.Event()
                try:
                    await self._round(ready)
                except STOP_EXCEPTIONS:
                    raise
                except BaseException as exc:  # noqa: BLE001 — reported, not swallowed
                    if not _publish_failure(ready, exc):
                        # Nobody was waiting — typically a close that raised
                        # during teardown, after the session had been handed
                        # out. It has no caller to be reported to, so it would
                        # vanish completely unless it is said here.
                        logger.debug(
                            "Amazon batch session failed with %s (no caller "
                            "was waiting on it)",
                            type(exc).__name__,
                        )
                    if self._closing:
                        return
                    await self._reopen.wait()
                ready = self._ready if self._ready is not None else ready
        finally:
            # Nobody else can resolve this future once the owner is gone, and a
            # caller awaiting it would hang forever.
            _publish_failure(self._ready, RuntimeError(_CLOSED_MESSAGE))

    async def _round(self, ready: asyncio.Future[Any]) -> None:
        """Open one session, publish it, and hold it until it is no longer wanted.

        The ``async with`` is what makes teardown exception-safe: a failed
        handshake, a failed probe or a cancelled batch all leave through it, so
        the transport is closed on every path.
        """
        creds = self._creds
        if creds is None:  # pragma: no cover — set before the task is created
            raise RuntimeError(_CLOSED_MESSAGE)
        async with self._connect(
            endpoint_url(creds.region), request_headers(creds)
        ) as session:
            await session.initialize()
            if not ready.done():
                ready.set_result(session)
            await self._reopen.wait()

    # -- teardown ------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the batch's session. Never raises.

        Graceful first — the owner task is parked inside the session's
        ``async with``, so waking it unwinds through the transport's own close
        (including the MCP session-termination request). If that does not
        finish within :data:`SESSION_CLOSE_TIMEOUT` the task is cancelled and
        cut loose rather than allowed to hold up the mutation waiting behind
        this capture.

        The wait is wrapped in ``try/finally`` because this cleanup must be
        immune to the very cancellation it exists to clean up after. mureo's
        MCP server runs each tool call in a task and cancels it when the client
        goes away, so a cancellation can land ON this await — and
        ``asyncio.wait``, unlike ``asyncio.wait_for``, raises without
        cancelling what it was waiting on. Leaving through the ``finally`` is
        therefore the only path that cannot end with the owner task still
        running, detached, holding a live Amazon session that nothing is left
        to cancel — provided this coroutine runs at all: a caller cancelled
        before it takes its first step executes none of this body. That is
        unreachable here (it is awaited from the ``finally`` of an already
        running ``batch_dispatch``), but the guarantee is the ``finally``'s,
        not the coroutine object's.
        """
        self._closing = True
        self._reopen.set()
        owner, self._owner = self._owner, None
        if owner is None:
            return
        try:
            await asyncio.wait({owner}, timeout=SESSION_CLOSE_TIMEOUT)
        finally:
            if not owner.done():
                logger.warning(
                    "Amazon batch session did not close within %.1fs (or its "
                    "close was cancelled); cancelling the session task",
                    SESSION_CLOSE_TIMEOUT,
                )
                owner.cancel()
                owner.add_done_callback(_drain)
            else:
                _drain(owner)


def _publish_failure(future: asyncio.Future[Any] | None, exc: BaseException) -> bool:
    """Hand ``exc`` to whoever is waiting for a session, at most once.

    Returns whether the failure was actually handed to a caller, so a late one
    that reaches nobody can be logged rather than lost.

    The result is marked retrieved immediately: a waiter cancelled by its own
    timeout may already be gone, and an unretrieved future exception would
    reach the operator's log as asyncio noise about a failure that was in fact
    reported.
    """
    if future is None or future.done():
        return False
    future.set_exception(exc)
    future.exception()
    return True


def _drain(owner: asyncio.Task[None]) -> None:
    """Retrieve the owner task's outcome so asyncio never logs it as unretrieved.

    Only the *type* is logged, matching the capture path: a session-teardown
    failure is diagnosed from what failed, and its text could carry anything
    the platform put in it.
    """
    if owner.cancelled():
        return
    exc = owner.exception()
    if exc is not None:
        logger.debug("Amazon batch session ended with %s", type(exc).__name__)


__all__ = ["SESSION_CLOSE_TIMEOUT", "SessionBatch"]
