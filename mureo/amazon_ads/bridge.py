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

import dataclasses
import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.amazon_ads.lwa import AmazonAuthError as _LwaAuthError
from mureo.amazon_ads.lwa import LwaTokens, refresh_access_token
from mureo.amazon_ads.manifest import (
    _default_connect,
    document_age_days,
    is_stale,
    manifest_path,
)
from mureo.amazon_ads.reversal import capture_reversal as _capture_reversal
from mureo.amazon_ads.reversal import is_reversible_tool
from mureo.auth import (
    AmazonAdsCredentials,
    load_amazon_ads_credentials,
    save_amazon_access_token,
)
from mureo.core.atomic_json import ConfigWriteError
from mureo.core.providers.credentials import AccountCredentialField

logger = logging.getLogger(__name__)

ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]
CredsLoader = Callable[[], AmazonAdsCredentials | None]
Refresher = Callable[[AmazonAdsCredentials], LwaTokens]
TokenSaver = Callable[[str, str | None], None]

#: Process-wide latch for the stale-manifest warning. ``mcp_tools()`` runs at
#: server start and on every tool-list refresh, so warning per call would be
#: spam; the latch arms only when a warning is actually emitted, so a fresh
#: read never silences a later stale one.
_stale_manifest_warned = False


def _scrub_secrets(text: str) -> str:
    """Redact secret-shaped substrings from an operator-facing error string.

    Delegates to the audit trail's redactor so there is ONE definition of
    "what a token looks like" across every string mureo shows a human or an
    agent (the audit log, the CLI, and here).

    Imported lazily, and that is load-bearing rather than stylistic:
    ``mureo.mcp.__init__`` imports ``mureo.mcp.server``, which builds its
    plugin tool list at import time and reaches this bridge through
    ``mureo.amazon_ads.provider``. A module-level ``from mureo.mcp.plugin_audit
    import _scrub`` therefore re-enters a partially-initialized
    ``mureo.amazon_ads.bridge`` and collapses plugin discovery to an
    ImportError — observed, not hypothetical. Resolving it at call time breaks
    the cycle; by then both modules are fully imported.

    Fail-safe: if the redactor cannot be resolved at all, the text is dropped
    rather than passed through unredacted. An unhelpful message is a much
    smaller problem than a leaked token.
    """
    try:
        from mureo.mcp.plugin_audit import _scrub
    except Exception:  # noqa: BLE001 — never leak because an import failed
        return "<error text withheld: redactor unavailable>"
    return _scrub(text)


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
            return _bounded(_flatten_for_display(_scrub_secrets(text.strip())))
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
    # Call-time import for the same load-bearing reason as ``_scrub_secrets``:
    # this module is reached from ``mureo.mcp.server``'s import-time plugin
    # collection, so a module-level ``mureo.mcp.*`` import would re-enter a
    # partially-initialized bridge. By dispatch time ``mureo.mcp._helpers`` is
    # long since imported — the dispatcher that calls us imports it itself.
    from mureo.mcp._helpers import API_ERROR_PREFIX

    return [
        TextContent(type="text", text=f"{API_ERROR_PREFIX} {_failure_text(content)}")
    ]


def _runtime_token_saver(access_token: str, refresh_token: str | None) -> None:
    """Persist a runtime-refreshed LwA token, honoring the active runtime.

    The default ``token_saver`` when none is injected at construction —
    which is every deployment, since the plugin collection path builds the
    bridge zero-arg. Two destinations, decided at persist time (#511):

    - The active ``RuntimeContext``'s ``SecretStore`` offers an
      ``amazon_token_saver`` capability ⇒ write through it. A multi-tenant
      host binds the refresh to the ACTIVE tenant's store, which is the
      only place its own reads will look. Without this, refreshes land in
      the operator-shared base whose reads strip per-client token fields,
      so every dispatch would re-mint from a refresh token Amazon has
      already rotated.
    - No capability (single-tenant OSS, or a backend that did not opt in)
      ⇒ :func:`mureo.auth.save_amazon_access_token`, i.e. the
      runtime-resolved ``credentials.json`` exactly as before (#512).

    Resolved per call, not at construction: the capability belongs to the
    runtime context, which a host may install after the bridge is built.

    The import is deliberately at call time, for the same load-bearing
    reason as :func:`_scrub_secrets` — this module is reached from
    ``mureo.mcp.server``'s import-time plugin collection, so a module-level
    import into that graph risks re-entering a partially-initialized module.

    Raises whatever the chosen saver raises; ``_refresh_and_persist`` maps
    ``ConfigWriteError`` / ``OSError`` onto :class:`AmazonBridgeError` for
    both destinations alike.
    """
    from mureo.core.runtime_context import runtime_amazon_token_saver

    saver = runtime_amazon_token_saver()
    if saver is not None:
        saver(access_token, refresh_token)
        return
    save_amazon_access_token(access_token, refresh_token)


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


class AmazonBridgeError(RuntimeError):
    """Raised by ``handle_mcp_tool`` when the bridge cannot proceed
    (e.g. ``amazon_ads`` credentials are not configured)."""


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
        self._creds_loader: CredsLoader = creds_loader or load_amazon_ads_credentials
        self._connect: ConnectFactory = connect or _default_connect
        self._refresher: Refresher = refresher or refresh_access_token
        # An injected saver always wins; the default routes through the
        # runtime capability seam (see ``_runtime_token_saver``).
        self._token_saver: TokenSaver = token_saver or _runtime_token_saver

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
        creds = self._creds_loader()
        if creds is None:
            raise AmazonBridgeError(
                "amazon_ads credentials not configured in "
                "~/.mureo/credentials.json (run `mureo configure` and fill "
                "in the Amazon Ads card, or set the AMAZON_ADS_* env vars)"
            )
        # #121 — the configure UI / env-var setup path stores only the
        # durable LwA material, leaving access_token empty. Mint it here,
        # BEFORE the first forwarded call: spending a guaranteed-to-fail
        # round trip just to discover the obvious would be wasteful and
        # would surface Amazon's error instead of ours. Minting consumes
        # the single-LwA-exchange budget, so a failure afterwards is
        # reported as-is rather than triggering a second exchange.
        minted = False
        if not creds.access_token:
            creds = self._refresh_and_persist(
                creds,
                cause=None,
                auth_failure_prefix=(
                    "no amazon_ads access_token is stored and one could not "
                    "be obtained from the refresh token"
                ),
            )
            minted = True
        try:
            return await self._call(creds, name, arguments)
        except KeyboardInterrupt:
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

    # -- reversal capture (#121, MCPReversibleToolProvider) -----------------

    async def capture_reversal(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Capture the before-state of a mutation, as a runtime-correct reversal.

        mureo's dispatch path calls this **before** a mutating Amazon tool
        runs (see :class:`mureo.mcp.tool_provider.MCPReversibleToolProvider`).
        The read is issued through :meth:`handle_mcp_tool`, so it inherits the
        bridge's authentication and one-shot token refresh, and the returned
        ``{"operation": <same tool>, "params": {...previous values...}}`` is
        what lands in ``STATE.json``'s ``action_log`` — executable as-is by
        the rollback planner. :mod:`mureo.amazon_ads.reversal` owns the pair
        table and states plainly what is live-verified and what is inferred.

        Best-effort, unconditionally: any failure returns ``None`` (the
        mutation is then recorded audit-only) and NEVER prevents or alters
        the write. The failure's *text* is never logged — only its exception
        type, alongside the tool name. That is deliberately stronger than
        redacting it: a capture failure is diagnosed from which tool failed
        and how, and dropping the message (and the traceback with it) means
        no credential material can reach the log even if it were shaped in a
        way no redactor recognises.
        """
        # Cheap first: the vast majority of Amazon mutations have no query
        # counterpart, and they must not pay for an exception handler or a
        # dispatch-shaped call path to find that out.
        if not is_reversible_tool(name):
            return None
        try:
            return await _capture_reversal(self.handle_mcp_tool, name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001 — capture never blocks a write
            logger.warning(
                "Amazon before-state capture failed for %r (%s); the mutation "
                "is recorded without a reversal",
                name,
                type(exc).__name__,
            )
            return None

    def _refresh_and_persist(
        self,
        creds: AmazonAdsCredentials,
        *,
        cause: BaseException | None,
        auth_failure_prefix: str,
    ) -> AmazonAdsCredentials:
        """Mint a fresh LwA access token, persist it, return updated creds.

        Shared by the two paths that may perform the single permitted LwA
        exchange: the proactive mint (no ``access_token`` stored yet) and
        the refresh-and-retry after a failed call. ``cause`` is the
        original call failure on the retry path — chained onto every
        raised :class:`AmazonBridgeError` so it is never lost — and
        ``None`` on the mint path, where the LwA error is its own cause.
        ``auth_failure_prefix`` names which of the two situations failed.

        Where the token lands is the ``_token_saver``'s business: an
        injected saver (tests, embedders) is used verbatim, while the
        default binds the write to the active runtime — the ACTIVE tenant's
        store when a multi-tenant host offers one, and the
        runtime-resolved ``credentials.json`` otherwise (#511; see
        :func:`_runtime_token_saver`). Single-tenant installs are
        unaffected. Either destination's ``ConfigWriteError`` / ``OSError``
        is mapped to the same :class:`AmazonBridgeError` below.
        """
        try:
            tokens = self._refresher(creds)
        except _LwaAuthError as auth_exc:
            raise AmazonBridgeError(
                f"{auth_failure_prefix}: {_scrub_secrets(str(auth_exc))}"
            ) from (cause if cause is not None else auth_exc)
        try:
            self._token_saver(tokens.access_token, tokens.refresh_token)
        except (ConfigWriteError, OSError) as save_exc:
            # The new token is valid but is not on disk, so every later call
            # would re-mint from a refresh token Amazon has already rotated
            # against. Surface the underlying reason — typically a malformed
            # credentials.json that mureo deliberately refuses to overwrite —
            # instead of letting a raw traceback out.
            #
            # Both nested messages are scrubbed on the way into ours. mureo's
            # own LwA and writer errors are token-free by construction, but
            # neither is guaranteed to be: ``_token_saver`` is injectable, an
            # OSError carries whatever filename or payload the OS put in it,
            # and this text lands in an agent-visible tool result. Scrubbing at
            # the point the string is BUILT is the only place that stays true
            # as those inputs change.
            raise AmazonBridgeError(
                f"Amazon access token was refreshed but could not be saved to "
                f"~/.mureo/credentials.json: {_scrub_secrets(str(save_exc))}"
            ) from (cause if cause is not None else save_exc)
        return dataclasses.replace(
            creds,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

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
        refreshed = self._refresh_and_persist(
            creds,
            cause=first_exc,
            auth_failure_prefix="Amazon access token expired and refresh failed",
        )
        try:
            return await self._call(refreshed, name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as retry_exc:
            raise retry_exc from first_exc

    async def _call(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
    ) -> list[Any]:
        """Forward one call, normalising an Amazon-declared failure (#528).

        The normalisation sits here rather than in ``handle_mcp_tool`` so the
        first attempt and the post-refresh retry — the only two ways a
        forwarded response reaches a caller — are covered by one call site,
        and because this is where ``CallToolResult.isError`` is still in
        scope: everything above sees only ``content``.

        ``getattr`` rather than attribute access, because the session is an
        injection seam (tests, embedders) and a stand-in result object need
        not carry the field; absent ⇒ not a failure.
        """
        url = endpoint_url(creds.region)
        headers = request_headers(creds)
        async with self._connect(url, headers) as session:
            await session.initialize()
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
