"""What an authenticated Amazon session is built from: credentials + refresh.

Every path that opens a session to Amazon's MCP needs the same two operations
— resolve the credentials a session's headers are built from (minting an
access token when only the durable LwA material is stored), and perform the
single permitted LwA exchange when a token has expired. The single-call path
(:meth:`mureo.amazon_ads.bridge.AmazonAdsBridge.handle_mcp_tool`) and the
session-scoped batch (:mod:`mureo.amazon_ads.batch`, #520) both do, so they
share :class:`SessionCredentials` rather than one reaching into the other for
private methods.

Nothing here is network-transport-aware and nothing here holds a session: this
is the credential seam alone. It is deliberately the ONLY place that turns an
LwA or a config-write failure into an operator-facing
:class:`AmazonBridgeError`, and the only place that scrubs the text on the way.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING

from mureo.amazon_ads.lwa import AmazonAuthError as _LwaAuthError
from mureo.auth import save_amazon_access_token
from mureo.core.atomic_json import ConfigWriteError

if TYPE_CHECKING:
    from mureo.amazon_ads.lwa import LwaTokens
    from mureo.auth import AmazonAdsCredentials

CredsLoader = Callable[[], "AmazonAdsCredentials | None"]
Refresher = Callable[["AmazonAdsCredentials"], "LwaTokens"]
TokenSaver = Callable[[str, str | None], None]


class AmazonBridgeError(RuntimeError):
    """Raised by ``handle_mcp_tool`` when the bridge cannot proceed
    (e.g. ``amazon_ads`` credentials are not configured)."""


def scrub_secrets(text: str) -> str:
    """Redact secret-shaped substrings from an operator-facing error string.

    Delegates to the audit trail's redactor so there is ONE definition of
    "what a token looks like" across every string mureo shows a human or an
    agent (the audit log, the CLI, and here).

    Imported lazily, and that is load-bearing rather than stylistic:
    ``mureo.mcp.__init__`` imports ``mureo.mcp.server``, which builds its
    plugin tool list at import time and reaches the Amazon bridge through
    ``mureo.amazon_ads.provider``. A module-level ``from mureo.mcp.plugin_audit
    import _scrub`` therefore re-enters a partially-initialized
    ``mureo.amazon_ads`` module and collapses plugin discovery to an
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


def runtime_token_saver(access_token: str, refresh_token: str | None) -> None:
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
    reason as :func:`scrub_secrets` — this module is reached from
    ``mureo.mcp.server``'s import-time plugin collection, so a module-level
    import into that graph risks re-entering a partially-initialized module.

    Raises whatever the chosen saver raises;
    :meth:`SessionCredentials.refresh_and_persist` maps
    ``ConfigWriteError`` / ``OSError`` onto :class:`AmazonBridgeError` for
    both destinations alike.
    """
    from mureo.core.runtime_context import runtime_amazon_token_saver

    saver = runtime_amazon_token_saver()
    if saver is not None:
        saver(access_token, refresh_token)
        return
    save_amazon_access_token(access_token, refresh_token)


class SessionCredentials:
    """The credential seam a session is opened with: load, mint, refresh, save.

    The three collaborators are the bridge's injection points (tests,
    embedders) and are passed in already resolved — this class never picks a
    default, so where a token comes from and where it lands stays a decision
    made in one place.
    """

    def __init__(
        self,
        *,
        loader: CredsLoader,
        refresher: Refresher,
        token_saver: TokenSaver,
    ) -> None:
        self._loader = loader
        self._refresher = refresher
        self._token_saver = token_saver

    def resolve(self) -> tuple[AmazonAdsCredentials, bool]:
        """Load the credentials a session will be built from.

        Returns ``(creds, minted)``. #121 — the configure UI / env-var setup
        path stores only the durable LwA material, leaving access_token empty.
        Mint it here, BEFORE the first forwarded call: spending a
        guaranteed-to-fail round trip just to discover the obvious would be
        wasteful and would surface Amazon's error instead of ours. Minting
        consumes the single-LwA-exchange budget (``minted`` says so), so a
        failure afterwards is reported as-is rather than triggering a second
        exchange — on the single-call path and inside a batch alike.
        """
        creds = self._loader()
        if creds is None:
            raise AmazonBridgeError(
                "amazon_ads credentials not configured in "
                "~/.mureo/credentials.json (run `mureo configure` and fill "
                "in the Amazon Ads card, or set the AMAZON_ADS_* env vars)"
            )
        if creds.access_token:
            return creds, False
        return (
            self.refresh_and_persist(
                creds,
                cause=None,
                auth_failure_prefix=(
                    "no amazon_ads access_token is stored and one could not "
                    "be obtained from the refresh token"
                ),
            ),
            True,
        )

    def refresh_and_persist(
        self,
        creds: AmazonAdsCredentials,
        *,
        cause: BaseException | None,
        auth_failure_prefix: str,
    ) -> AmazonAdsCredentials:
        """Mint a fresh LwA access token, persist it, return updated creds.

        Shared by the paths that may perform the single permitted LwA
        exchange: the proactive mint (no ``access_token`` stored yet) and
        the refresh-and-retry after a failed call, one-shot per call on the
        single-call path and once per batch inside one (#520). ``cause`` is the
        original call failure on the retry path — chained onto every
        raised :class:`AmazonBridgeError` so it is never lost — and
        ``None`` on the mint path, where the LwA error is its own cause.
        ``auth_failure_prefix`` names which of the two situations failed.

        Where the token lands is the ``token_saver``'s business: an
        injected saver (tests, embedders) is used verbatim, while the
        bridge's default binds the write to the active runtime — the ACTIVE
        tenant's store when a multi-tenant host offers one, and the
        runtime-resolved ``credentials.json`` otherwise (#511; see
        :func:`mureo.amazon_ads.bridge._runtime_token_saver`). Single-tenant
        installs are unaffected. Either destination's ``ConfigWriteError`` /
        ``OSError`` is mapped to the same :class:`AmazonBridgeError` below.
        """
        try:
            tokens = self._refresher(creds)
        except _LwaAuthError as auth_exc:
            raise AmazonBridgeError(
                f"{auth_failure_prefix}: {scrub_secrets(str(auth_exc))}"
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
            # neither is guaranteed to be: ``token_saver`` is injectable, an
            # OSError carries whatever filename or payload the OS put in it,
            # and this text lands in an agent-visible tool result. Scrubbing at
            # the point the string is BUILT is the only place that stays true
            # as those inputs change.
            raise AmazonBridgeError(
                f"Amazon access token was refreshed but could not be saved to "
                f"~/.mureo/credentials.json: {scrub_secrets(str(save_exc))}"
            ) from (cause if cause is not None else save_exc)
        return dataclasses.replace(
            creds,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )


__all__ = [
    "AmazonBridgeError",
    "CredsLoader",
    "Refresher",
    "SessionCredentials",
    "TokenSaver",
    "runtime_token_saver",
    "scrub_secrets",
]
