"""The Amazon Ads bridge provider (#113 Phase 1, task #24).

Shape matches the #114 ``MCPToolProvider`` Protocol so it can ride the
exact same collect/dispatch + safety layer (audit / throttle /
strategy / rollback) as entry-point plugins:

- ``mcp_tools()`` — PURE: reads the tool manifest only (beside the
  runtime-resolved ``credentials.json``, ``~/.mureo/amazon_tools.json``
  by default — see :func:`mureo.amazon_ads.manifest.manifest_path`). No
  credentials, no network, and it NEVER raises (it runs at mureo server
  start; a missing/broken manifest ⇒ no Amazon tools, not a crash).
- ``handle_mcp_tool()`` — lazily opens one authenticated MCP session
  to the region endpoint (creds from ``~/.mureo/credentials.json``)
  and forwards the call. Tool names are Amazon's own (no taxonomy
  remap), consistent with how mureo treats other official MCPs.
- ``capture_reversal()`` — the #327 ``MCPReversibleToolProvider`` hook
  (#121): before a paired mutation, read the entity's current state
  through this same dispatch so the recorded ``reversible_params`` are
  executable by ``rollback_apply``. Best-effort — see
  :mod:`mureo.amazon_ads.reversal` for the pair table and its limits.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from mureo.amazon_ads.batch import SessionBatch
from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.amazon_ads.lwa import refresh_access_token
from mureo.amazon_ads.manifest import (
    _default_connect,
    document_age_days,
    is_stale,
    manifest_path,
)
from mureo.amazon_ads.reversal import capture_reversal as _capture_reversal
from mureo.amazon_ads.reversal import is_reversible_tool
from mureo.amazon_ads.session_auth import (
    AmazonBridgeError,
    CredsLoader,
    Refresher,
    SessionCredentials,
    TokenSaver,
    runtime_token_saver,
    scrub_secrets,
)
from mureo.auth import AmazonAdsCredentials, load_amazon_ads_credentials
from mureo.core.control_flow import STOP_EXCEPTIONS
from mureo.core.providers.credentials import AccountCredentialField

logger = logging.getLogger(__name__)

ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]
#: What :meth:`AmazonAdsBridge.batch_dispatch` yields — the SAME
#: ``(name, arguments) -> awaitable`` seam ``handle_mcp_tool`` already
#: satisfies, so a batched sequence and a one-shot call are interchangeable to
#: every caller (:data:`mureo.amazon_ads.reversal.Dispatch`).
Dispatch = Callable[[str, dict[str, Any]], Awaitable[list[Any]]]

#: Process-wide latch for the stale-manifest warning. ``mcp_tools()`` runs at
#: server start and on every tool-list refresh, so warning per call would be
#: spam; the latch arms only when a warning is actually emitted, so a fresh
#: read never silences a later stale one.
_stale_manifest_warned = False


#: Opening of Amazon's plain-text schema-validation failure. Kept as a
#: belt-and-braces second signal beside ``CallToolResult.isError`` (see
#: :func:`_normalize_failure`): no success message plausibly begins with it,
#: and it costs one ``str.startswith``.
_VALIDATION_FAILURE_PREFIX = "Validation failed:"

#: Stand-in when a failure arrives with no text at all — the envelope must
#: still be produced (a failure with an empty body is still a failure), and it
#: must still say something.
_NO_FAILURE_TEXT = "Amazon reported a tool error with no message"

#: Prefix for a body that carries no usable ``message``. Since the redactor
#: masks most ``code`` values, such a body would otherwise reach the agent as
#: an opaque ``{"code":"***"}`` with nothing to act on. Saying so plainly is
#: the only honest option, and it tells the agent what to report.
_NO_MESSAGE_TEXT = "Amazon returned no error message; raw body:"

#: Hard cap on the failure text handed to the agent, with an explicit marker
#: so a truncated diagnostic can never be mistaken for a complete one.
#:
#: 4000 characters. The longest failure observed live is ~150 characters, and
#: a ``Validation errors: [...]`` list with a dozen entries still lands well
#: under 1000, so every plausible real diagnostic survives whole (>25x the
#: observed maximum). Past that it is a runaway or adversarial body, and an
#: unbounded one would dump megabytes into the agent's context — the audit
#: line has always been capped (``plugin_audit._MAX_STR``); this is the same
#: protection for the side that reaches the model.
_MAX_FAILURE_TEXT = 4000
_TRUNCATION_MARKER = "…<truncated>"


def _flatten_for_display(scrubbed: str) -> str:
    """PRESENTATION ONLY: ``{"code": X, "message": Y, …}`` ⇒ ``X: Y (…)``.

    Runs strictly AFTER a failure has been established by
    :func:`_normalize_failure`, so it CANNOT influence whether something is a
    failure — that is ``CallToolResult.isError``'s job alone.

    **The input must already be scrubbed**, and the ordering is a security
    property, not a style choice. The shared redactor keys on the literal
    ``"code":`` anchor to mask what may be an LwA authorization code
    (:func:`mureo.mcp.plugin_audit._scrub`). Flattening first would delete that
    anchor and hand a credential to the agent AND to ``plugin_audit.jsonl`` in
    cleartext. Scrub, then reshape what the redactor has already cleared.

    The consequence is accepted deliberately: the redactor cannot tell an
    Amazon error code from an OAuth code — and must not guess, since a wrong
    guess here leaks a credential — so a ``code`` long enough to trip the rule
    renders as ``***``. ``FIELD_VALUE_IS_INVALID`` is one of those, verified:
    the live failure reads ``API error: ***: Multi marketplace query requests
    only support query by primary resource id``. The message carries the
    actionable content, which is what the agent needs to correct its call.

    Every key that is not rendered into the summary is appended verbatim
    rather than dropped, so a future Amazon shape does not lose information
    silently. A body with NO usable ``message`` (absent, empty, ``null``, or
    not a string) is prefixed with :data:`_NO_MESSAGE_TEXT`: with the code
    masked there is nothing left to read, and an opaque ``{"code":"***"}``
    would leave the agent guessing. A ``message`` with no usable ``code``
    renders as the message alone — it is a perfectly good diagnosis.

    Anything that does not parse is returned untouched — including a body deep
    enough to exhaust the parser's stack (``RecursionError`` is a
    ``RuntimeError``, so it needs naming explicitly beside ``ValueError``).
    """
    try:
        payload = json.loads(scrubbed)
        if not isinstance(payload, dict):
            return scrubbed
        raw_message = payload.get("message")
        message = raw_message.strip() if isinstance(raw_message, str) else ""
        if not message:
            return f"{_NO_MESSAGE_TEXT} {scrubbed}"
        rendered = message
        rendered_keys = {"message"}
        code = payload.get("code")
        if not isinstance(code, bool) and isinstance(code, (str, int)):
            rendered = f"{code}: {message}"
            rendered_keys.add("code")
        extras = {k: v for k, v in payload.items() if k not in rendered_keys}
        if extras:
            rendered = f"{rendered} ({json.dumps(extras, ensure_ascii=False)})"
        return rendered
    except (ValueError, RecursionError):
        return scrubbed


def _failure_text(content: list[Any]) -> str:
    """Amazon's own failure text — scrubbed, reshaped and bounded.

    Scrubbing happens HERE, at the point the string is taken out of the
    response and before anything reshapes it, so every caller gets a redacted
    string and the redactor still sees the payload in its original form
    (see :func:`_flatten_for_display`). The result is capped last, so the
    bound holds for every path through this function.
    """
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return _bounded(_flatten_for_display(scrub_secrets(text.strip())))
    return _NO_FAILURE_TEXT


def _bounded(text: str) -> str:
    """Cap ``text`` at :data:`_MAX_FAILURE_TEXT`, marking any truncation."""
    if len(text) <= _MAX_FAILURE_TEXT:
        return text
    return text[:_MAX_FAILURE_TEXT] + _TRUNCATION_MARKER


def _is_validation_failure(content: list[Any]) -> bool:
    """True if the first block opens with Amazon's validation-failure text.

    Belt-and-braces ONLY, and deliberately not load-bearing: the live probe
    (2026-08-05) shows Amazon flags BOTH known failure shapes — this one
    included — with ``isError=True``, so this check has never been the thing
    that catches a real failure. It exists in case a future shape arrives
    unflagged. ``isError`` is the primary signal; do not promote this one.
    """
    if not content:
        return False
    text = getattr(content[0], "text", None)
    return isinstance(text, str) and text.strip().startswith(_VALIDATION_FAILURE_PREFIX)


def _normalize_failure(content: list[Any], *, is_error: bool) -> list[Any]:
    """Rewrite an Amazon-declared failure into mureo's ``API error:`` envelope.

    ``mureo.mcp._helpers.is_error_result`` — the single detector both
    promotion paths use to skip recording a mutation that did not happen —
    knows exactly one shape: the ``API error:`` prefix mureo's own
    ``api_error_handler`` stamps. Bridged tools never pass through that
    decorator, so an Amazon-side failure was promoted into ``STATE.json``'s
    ``action_log`` as a successful mutation, complete with an
    ``observation_due`` and possibly a captured reversal for a change that
    never happened (#528). Normalising here keeps the shared detector
    platform-agnostic.

    The discriminator is ``CallToolResult.isError``
    ------------------------------------------------
    ``is_error`` is MCP's own field: the SERVER's declaration that the call
    failed. It is a fact about the call, not an inference from the payload,
    so no property of the response body can make it wrong.

    LIVE-VERIFIED against the real account (region ``fe``, 2026-08-05), by
    replaying the two failures from #528 as read-only calls and logging the
    raw ``CallToolResult``:

    - ``account_management-query_advertiser_account`` ``{"body": {}}``
      (success) ⇒ ``isError=False``
    - ``campaign_management-query_campaign`` by ``advertiserAccountId`` on a
      global account ⇒ ``isError=True``, body
      ``{"code": "FIELD_VALUE_IS_INVALID", "message": "Multi marketplace
      query requests only support query by primary resource id"}``
    - ``campaign_management-query_campaign`` with no ``adProductFilter`` ⇒
      ``isError=True``, body ``Validation failed: provided input does not
      match tool input schema. …``

    The payload shape is therefore NOT examined, with one belt-and-braces
    exception: content opening with ``Validation failed:``
    (:func:`_is_validation_failure`) is also treated as a failure, since no
    success message plausibly begins that way. Nothing else about the body
    is read — in particular no ``code``/``message`` heuristic, which
    misclassified plausible mutation acks (``{"code": "CREATED", …}``) as
    failures and would have DROPPED the ``action_log`` entry for a change
    that really happened.

    A failure replaces the whole result with the canonical envelope carrying
    Amazon's own text, scrubbed then reshaped for legibility
    (:func:`_failure_text`). The text comes from the response, never from an
    exception, so no traceback can reach it. An empty body still yields the
    envelope: ``isError`` alone settles it.
    """
    if not (is_error or _is_validation_failure(content)):
        return content
    # Call-time import for the same load-bearing reason as ``scrub_secrets``:
    # this module is reached from ``mureo.mcp.server``'s import-time plugin
    # collection, so a module-level ``mureo.mcp.*`` import would re-enter a
    # partially-initialized bridge. By dispatch time ``mureo.mcp._helpers`` is
    # long since imported — the dispatcher that calls us imports it itself.
    from mureo.mcp._helpers import API_ERROR_PREFIX

    return [
        TextContent(type="text", text=f"{API_ERROR_PREFIX} {_failure_text(content)}")
    ]


def _warn_once_if_stale(path: Path, doc: Any) -> None:
    """Warn (once per process) that the served manifest is stale.

    Deliberately advisory: the tools are still exposed. The manifest is a
    snapshot of a tool surface mureo does not own, so an old one means the
    exposed list has probably drifted — worth saying out loud, not worth
    refusing to work over. Never raises; ``mcp_tools()`` runs at server start.
    """
    global _stale_manifest_warned
    if _stale_manifest_warned:
        return
    try:
        age = document_age_days(doc)
        if not is_stale(age):
            return
        logger.warning(
            "Amazon tool manifest is stale (%.0f days old, %s); the exposed "
            "tool list may no longer match Amazon's. Run `mureo amazon "
            "refresh-manifest` to regenerate it.",
            age,
            path,
        )
    except Exception:  # noqa: BLE001 — a freshness hint must never break start
        return
    _stale_manifest_warned = True


# Per-account credentials the operator supplies (#121). One field per
# key ``mureo.auth.load_amazon_ads_credentials`` reads out of the
# ``amazon_ads`` section, in the same order, so the configure UI's
# generic form (``mureo.web.plugin_credentials``) writes a section the
# loader accepts verbatim. Adding a key here without teaching the
# loader about it — or vice versa — silently strands operator input.
#
# Only ``client_id`` is required: mureo accepts EITHER a pasted
# ``access_token`` OR the durable ``refresh_token`` + ``client_secret``
# pair it can mint one from, so neither can be marked required alone.
_ACCOUNT_CREDENTIAL_FIELDS: tuple[AccountCredentialField, ...] = (
    AccountCredentialField(
        key="client_id",
        display_name="Client ID",
        placeholder="amzn1.application-oa2-client.xxxxx",
        required=True,
        description=(
            "Login with Amazon (LwA) application client id. Find it in "
            "the Amazon Developer console under Login with Amazon > "
            "your Security Profile > Web Settings."
        ),
        display_name_i18n={"en": "Client ID", "ja": "クライアント ID"},
        description_i18n={
            "en": (
                "Login with Amazon (LwA) application client id. Find it "
                "in the Amazon Developer console under Login with Amazon "
                "> your Security Profile > Web Settings."
            ),
            "ja": (
                "Login with Amazon（LwA）アプリのクライアント ID。Amazon "
                "Developer コンソールの「Login with Amazon」＞対象の"
                "セキュリティプロファイル＞ウェブ設定で確認できます。"
            ),
        },
    ),
    AccountCredentialField(
        key="access_token",
        display_name="Access Token",
        placeholder="Atza|xxxxx",
        required=False,
        secret=True,
        description=(
            "LwA access token — it expires after about 60 minutes. "
            "Optional when refresh_token and client_secret are set: "
            "mureo then mints one on the first call and refreshes it "
            "for you. Leave blank unless you are pasting a token by hand."
        ),
        display_name_i18n={"en": "Access Token", "ja": "アクセストークン"},
        description_i18n={
            "en": (
                "LwA access token — it expires after about 60 minutes. "
                "Optional when refresh_token and client_secret are set: "
                "mureo then mints one on the first call and refreshes it "
                "for you. Leave blank unless you are pasting a token by "
                "hand."
            ),
            "ja": (
                "LwA アクセストークン（約 60 分で失効）。refresh_token と "
                "client_secret を設定していれば任意です。その場合は初回"
                "呼び出し時に mureo が発行し、以後も自動更新します。手動で"
                "貼り付けるとき以外は空欄で構いません。"
            ),
        },
    ),
    AccountCredentialField(
        key="refresh_token",
        display_name="Refresh Token",
        placeholder="Atzr|xxxxx",
        required=False,
        secret=True,
        description=(
            "LwA refresh token. With client_secret it lets mureo mint "
            "and refresh the access token for you. Amazon expires "
            "refresh tokens after about a year — paste a fresh one here "
            "when calls start failing with an invalid_grant "
            "re-authorize error."
        ),
        display_name_i18n={"en": "Refresh Token", "ja": "リフレッシュトークン"},
        description_i18n={
            "en": (
                "LwA refresh token. With client_secret it lets mureo "
                "mint and refresh the access token for you. Amazon "
                "expires refresh tokens after about a year — paste a "
                "fresh one here when calls start failing with an "
                "invalid_grant re-authorize error."
            ),
            "ja": (
                "LwA リフレッシュトークン。client_secret と揃うと mureo が"
                "アクセストークンの発行・更新を自動で行います。Amazon の"
                "リフレッシュトークンは約 1 年で失効します。invalid_grant"
                "（再認可が必要）で呼び出しが失敗するようになったら、新しい"
                "トークンをここに貼り直してください。"
            ),
        },
    ),
    AccountCredentialField(
        key="client_secret",
        display_name="Client Secret",
        placeholder="amzn1.oa2-cs.v1.xxxxx",
        required=False,
        secret=True,
        description=(
            "LwA application client secret, from the same Security "
            "Profile as the client id. Required together with "
            "refresh_token for automatic access-token refresh."
        ),
        display_name_i18n={"en": "Client Secret", "ja": "クライアントシークレット"},
        description_i18n={
            "en": (
                "LwA application client secret, from the same Security "
                "Profile as the client id. Required together with "
                "refresh_token for automatic access-token refresh."
            ),
            "ja": (
                "LwA アプリのクライアントシークレット（クライアント ID と"
                "同じセキュリティプロファイル）。アクセストークンの自動更新"
                "には refresh_token と両方が必要です。"
            ),
        },
    ),
    AccountCredentialField(
        key="region",
        display_name="Region",
        placeholder="na | eu | fe",
        required=False,
        description=(
            "Amazon Ads region, which picks the MCP endpoint: na "
            "(North America), eu (Europe), fe (Far East). Defaults to na."
        ),
        display_name_i18n={"en": "Region", "ja": "リージョン"},
        description_i18n={
            "en": (
                "Amazon Ads region, which picks the MCP endpoint: na "
                "(North America), eu (Europe), fe (Far East). Defaults "
                "to na."
            ),
            "ja": (
                "接続先エンドポイントを決める Amazon Ads のリージョン。"
                "na（北米）/ eu（欧州）/ fe（極東）。既定は na です。"
            ),
        },
    ),
    AccountCredentialField(
        key="account_mode",
        display_name="Account Mode",
        placeholder="dynamic | fixed",
        required=False,
        description=(
            "dynamic lets the AI pick the advertiser account per call; "
            "fixed pins it to the profile / account ids below. Defaults "
            "to dynamic."
        ),
        display_name_i18n={"en": "Account Mode", "ja": "アカウントモード"},
        description_i18n={
            "en": (
                "dynamic lets the AI pick the advertiser account per "
                "call; fixed pins it to the profile / account ids below. "
                "Defaults to dynamic."
            ),
            "ja": (
                "dynamic は呼び出しごとに AI が広告アカウントを選びます。"
                "fixed は下のプロファイル / アカウント ID に固定します。"
                "既定は dynamic です。"
            ),
        },
    ),
    AccountCredentialField(
        key="profile_id",
        display_name="Profile ID",
        placeholder="1234567890",
        required=False,
        description=(
            "Amazon Advertising profile id, sent as the "
            "Amazon-Advertising-API-Scope header. Fixed account mode only."
        ),
        display_name_i18n={"en": "Profile ID", "ja": "プロファイル ID"},
        description_i18n={
            "en": (
                "Amazon Advertising profile id, sent as the "
                "Amazon-Advertising-API-Scope header. Fixed account mode "
                "only."
            ),
            "ja": (
                "Amazon-Advertising-API-Scope ヘッダーに送る Amazon "
                "Advertising のプロファイル ID。fixed モード専用です。"
            ),
        },
    ),
    AccountCredentialField(
        key="account_id",
        display_name="Account ID",
        placeholder="ENTITY1234567890",
        required=False,
        description=(
            "Advertiser account id, sent as the Amazon-Ads-AccountID "
            "header. Fixed account mode only."
        ),
        display_name_i18n={"en": "Account ID", "ja": "アカウント ID"},
        description_i18n={
            "en": (
                "Advertiser account id, sent as the Amazon-Ads-AccountID "
                "header. Fixed account mode only."
            ),
            "ja": (
                "Amazon-Ads-AccountID ヘッダーに送る広告アカウント ID。"
                "fixed モード専用です。"
            ),
        },
    ),
    AccountCredentialField(
        key="manager_account_id",
        display_name="Manager Account ID",
        placeholder="1234567890",
        required=False,
        description=(
            "Manager account id, sent as the "
            "Amazon-Ads-Manager-AccountID header. Fixed account mode only."
        ),
        display_name_i18n={
            "en": "Manager Account ID",
            "ja": "マネージャーアカウント ID",
        },
        description_i18n={
            "en": (
                "Manager account id, sent as the "
                "Amazon-Ads-Manager-AccountID header. Fixed account mode "
                "only."
            ),
            "ja": (
                "Amazon-Ads-Manager-AccountID ヘッダーに送るマネージャー"
                "アカウント ID。fixed モード専用です。"
            ),
        },
    ),
)


class AmazonAdsBridge:
    """Internal (non-entry-point) provider bridging to Amazon's MCP."""

    name = "amazon_ads"
    display_name = "Amazon Ads"
    # #236 heading translations for the configure UI's provider card.
    display_name_i18n = {"en": "Amazon Ads", "ja": "Amazon 広告"}

    # Per-account credential fields (#121). Declared at module level
    # as ``_ACCOUNT_CREDENTIAL_FIELDS`` — see there for the copy and
    # the loader-parity contract; this is the class attribute
    # ``mureo.core.providers.get_account_credential_fields`` reads.
    account_credential_fields: tuple[AccountCredentialField, ...] = (
        _ACCOUNT_CREDENTIAL_FIELDS
    )

    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        creds_loader: CredsLoader | None = None,
        connect: ConnectFactory | None = None,
        refresher: Refresher | None = None,
        token_saver: TokenSaver | None = None,
    ) -> None:
        self._manifest_path = manifest_path or _default_manifest_path()
        self._connect: ConnectFactory = connect or _default_connect
        # The credential seam both session paths share (#520) — see
        # :class:`mureo.amazon_ads.session_auth.SessionCredentials`. Every
        # default is still chosen HERE: an injected saver always wins, and the
        # default routes through the runtime capability seam (see
        # :func:`mureo.amazon_ads.session_auth.runtime_token_saver`).
        self._auth = SessionCredentials(
            loader=creds_loader or load_amazon_ads_credentials,
            refresher=refresher or refresh_access_token,
            token_saver=token_saver or runtime_token_saver,
        )

    # -- collection-time (pure, never raises) -------------------------------

    def mcp_tools(self) -> tuple[Tool, ...]:
        try:
            raw = json.loads(Path(self._manifest_path).read_text(encoding="utf-8"))
            items = raw.get("tools", []) if isinstance(raw, dict) else []
        except (OSError, ValueError, TypeError):
            return ()  # missing / unreadable / malformed ⇒ no Amazon tools
        _warn_once_if_stale(Path(self._manifest_path), raw)
        tools: list[Tool] = []
        for entry in items if isinstance(items, list) else []:
            try:
                tools.append(Tool.model_validate(entry))
            except Exception:  # noqa: BLE001 — one bad tool ≠ crash start
                continue
        return tuple(tools)

    # -- dispatch-time (authenticated, network) -----------------------------

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        """Forward one call, refreshing the LwA token once if it fails.

        A **stop is never a refreshable failure — anywhere in the bridge**
        (:data:`mureo.core.control_flow.STOP_EXCEPTIONS`). The retry below
        re-issues the call, so treating a cancellation as a failure would send
        a second request — for a mutating tool, a second WRITE to a live ad
        account — on behalf of a caller that has already disconnected, and
        returning the retry's result would swallow the cancellation whole.
        Measured, not theorised: before this guard a cancelled call came back
        ``['RESULT#2']`` with two attempts and one LwA exchange spent.
        """
        creds, minted = self._auth.resolve()
        try:
            return await self._call(creds, name, arguments)
        except STOP_EXCEPTIONS:
            raise
        except BaseException as first_exc:
            # The Amazon access token expires after 60 min. We do not
            # observe the MCP transport's exact 401 shape, so on ANY
            # first failure — when refresh creds are present — attempt
            # exactly one LwA refresh + persist + retry. Bounded (one
            # extra POST + one retry). Accepted trade-off: a *non-auth*
            # first failure also triggers one wasted refresh (a token
            # rotation + a credentials.json write) before the same
            # error recurs; this is intentional until the 401 shape is
            # observed and can be narrowed. The original error is always
            # chained (``from first_exc``) so it is never lost.
            if minted or not (creds.refresh_token and creds.client_secret):
                raise
            return await self._refresh_and_retry(creds, name, arguments, first_exc)

    # -- session-scoped batch (#520) ----------------------------------------

    @asynccontextmanager
    async def batch_dispatch(self) -> AsyncIterator[Dispatch]:
        """Yield a dispatch bound to ONE session for a whole sequence of calls.

        The single-call :meth:`handle_mcp_tool` remains the default and is
        unchanged; this is the opt-in for a caller that issues several calls
        back to back, where the per-call handshake — not the query — dominates
        (:mod:`mureo.amazon_ads.reversal`'s probe sequence is the one such
        caller today). What is yielded is a plain
        ``(name, arguments) -> awaitable`` callable of exactly the same shape,
        so no transport object leaves the bridge and no caller changes its
        calling convention.

        Refresh budget: **one LwA exchange for the whole batch** — a refresh
        closes the session, opens a new one on the new token, and retries only
        the call that triggered it; a second failure is reported, never
        refreshed again. Minting a missing access token counts as that
        exchange. See :mod:`mureo.amazon_ads.batch` for why the session lives
        in its own task and how a partial sequence is preserved.

        The session is opened lazily on the first call and closed on exit —
        including the exception path, so a failing call can never leak an open
        transport.
        """
        batch = SessionBatch(
            connect=self._connect, invoke=self._invoke, auth=self._auth
        )
        try:
            yield batch.dispatch
        finally:
            await batch.aclose()

    # -- reversal capture (#121, MCPReversibleToolProvider) -----------------

    async def capture_reversal(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Capture the before-state of a mutation, as a runtime-correct reversal.

        mureo's dispatch path calls this **before** a mutating Amazon tool
        runs (see :class:`mureo.mcp.tool_provider.MCPReversibleToolProvider`).
        The reads are issued through :meth:`batch_dispatch`, so the whole probe
        sequence shares ONE session instead of paying a handshake per probe
        (#520) while inheriting the same authentication and bounded token
        refresh a single call gets, and the returned
        ``{"operation": <same tool>, "params": {...previous values...}}`` is
        what lands in ``STATE.json``'s ``action_log`` — executable as-is by
        the rollback planner. :mod:`mureo.amazon_ads.reversal` owns the pair
        table and states plainly what is live-verified and what is inferred.

        Best-effort, unconditionally: any *failure* returns ``None`` (the
        mutation is then recorded audit-only) and NEVER prevents or alters
        the write. The failure's *text* is never logged — only its exception
        type, alongside the tool name. That is deliberately stronger than
        redacting it: a capture failure is diagnosed from which tool failed
        and how, and dropping the message (and the traceback with it) means
        no credential material can reach the log even if it were shaped in a
        way no redactor recognises.

        A **stop is not a failure** (:data:`~mureo.core.control_flow
        .STOP_EXCEPTIONS`: cancellation, KeyboardInterrupt, SystemExit) and is
        re-raised, not swallowed.
        mureo's MCP server runs each tool call in a task and cancels it when
        the client goes away, so degrading a cancelled capture to "no
        reversal" would suppress the caller's own cancellation and let the
        dispatch carry on into the mutation — and, since #520 gave the capture
        a session of its own, would do so while its teardown was still
        unwinding. Cancelling means the call is over; only a genuine read
        failure means "record the write without a reversal".
        """
        # Cheap first: the vast majority of Amazon mutations have no query
        # counterpart, and they must not pay for an exception handler or a
        # dispatch-shaped call path to find that out.
        if not is_reversible_tool(name):
            return None
        try:
            async with self.batch_dispatch() as dispatch:
                return await _capture_reversal(dispatch, name, arguments)
        except STOP_EXCEPTIONS:
            raise
        except BaseException as exc:  # noqa: BLE001 — capture never blocks a write
            logger.warning(
                "Amazon before-state capture failed for %r (%s); the mutation "
                "is recorded without a reversal",
                name,
                type(exc).__name__,
            )
            return None

    async def _refresh_and_retry(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
        first_exc: BaseException,
    ) -> list[Any]:
        """Refresh the LwA token once, persist it, and retry ``name``.

        Every failure mode is reported as an ``AmazonBridgeError`` with an
        actionable message, always chaining ``first_exc`` so the original
        call failure is never lost.
        """
        refreshed = self._auth.refresh_and_persist(
            creds,
            cause=first_exc,
            auth_failure_prefix="Amazon access token expired and refresh failed",
        )
        try:
            return await self._call(refreshed, name, arguments)
        except STOP_EXCEPTIONS:
            raise  # a stop is not "the retry failed"; do not chain it
        except BaseException as retry_exc:
            raise retry_exc from first_exc

    async def _call(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
    ) -> list[Any]:
        """Open one session for one call and forward it (the default path).

        A batched sequence opens its session elsewhere
        (:class:`mureo.amazon_ads.batch.SessionBatch`) and reaches Amazon
        through the same :meth:`_invoke`, so both paths forward and normalise
        identically; only the session's lifetime differs.
        """
        url = endpoint_url(creds.region)
        headers = request_headers(creds)
        async with self._connect(url, headers) as session:
            await session.initialize()
            return await self._invoke(session, name, arguments)

    async def _invoke(
        self, session: Any, name: str, arguments: dict[str, Any]
    ) -> list[Any]:
        """Forward one call on an OPEN session, normalising an Amazon-declared
        failure (#528).

        The normalisation sits here rather than in ``handle_mcp_tool`` so every
        way a forwarded response reaches a caller — the first attempt, the
        post-refresh retry, and every call in a batched sequence — is covered
        by one call site, and because this is where ``CallToolResult.isError``
        is still in scope: everything above sees only ``content``.

        ``getattr`` rather than attribute access, because the session is an
        injection seam (tests, embedders) and a stand-in result object need
        not carry the field; absent ⇒ not a failure.
        """
        result = await session.call_tool(name, arguments)
        return _normalize_failure(
            list(result.content),
            is_error=bool(getattr(result, "isError", False)),
        )


def _default_manifest_path() -> Path:
    """Delegate — :func:`mureo.amazon_ads.manifest.manifest_path` owns the
    location (runtime-aware since #516); this indirection only exists so
    tests can patch one seam."""
    return manifest_path()


__all__ = ["AmazonAdsBridge", "AmazonBridgeError"]
