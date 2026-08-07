"""Registry registration for the in-tree Amazon Ads bridge (#121).

:class:`~mureo.amazon_ads.bridge.AmazonAdsBridge` is shipped inside
mureo rather than as a ``mureo.providers`` entry point, so
:meth:`Registry.discover` never sees it. Two surfaces need it in
:data:`~mureo.core.providers.default_registry` anyway:

- the MCP server, which feeds registry entries through
  ``collect_plugin_tools`` to expose Amazon's tools, and
- the ``mureo configure`` UI, whose plugin-credentials section renders
  a form for every registered provider declaring
  ``account_credential_fields``.

Both call :func:`register_amazon_provider`, so the synthetic
:class:`ProviderEntry` has exactly one definition. Registration is
idempotent — the second call returns the already-registered entry
without emitting a duplicate-name :class:`RegistryWarning` — and
first-wins: an ``amazon_ads`` provider registered earlier (by a
third-party plugin) is left in place, matching the registry's own
shadowing policy.

Ordering contract
-----------------
Callers MUST call :func:`register_amazon_provider` **before** running
entry-point discovery (``discover_providers``) for the shadowing policy
to hold. The registry is first-wins, so whichever registration lands
first owns the ``amazon_ads`` slot: registering first is what makes the
in-tree bridge deterministically beat a third-party distribution that
publishes a ``mureo.providers`` entry point under the same name. Both
in-tree callers honour this —
:func:`mureo.mcp.server._discover_with_amazon` and
:meth:`mureo.web.server.ConfigureWizard._discover_providers_safely` —
so the MCP process and the configure process resolve the name
identically.

Registering first does NOT override a foreign entry that was already in
the registry when this module's helper runs; that case keeps the
documented first-wins behaviour and :func:`register_amazon_provider`
returns the foreign entry.
"""

from __future__ import annotations

import os

from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.core.providers.registry import ProviderEntry, default_registry

#: Pip-distribution label recorded on the entry. It also names the
#: bridge in the audit trail (``source``) and, with
#: :data:`AMAZON_PROVIDER_NAME`, in ``STATE.json`` ``action_log`` entries
#: (``platform=plugin:<this>:<provider>``, #537), so renaming it would
#: orphan existing history.
AMAZON_SOURCE_DISTRIBUTION = "mureo-amazon-ads-bridge"

#: Registry key of the bridge — mirrors ``AmazonAdsBridge.name`` and the
#: ``amazon_ads`` section of ``~/.mureo/credentials.json``. It is also the
#: provider half of the canonical platform key
#: (``plugin:mureo-amazon-ads-bridge:amazon_ads``), so renaming it orphans
#: history for the same reason.
AMAZON_PROVIDER_NAME = "amazon_ads"

#: Coexistence control, matching ``MUREO_DISABLE_GOOGLE_ADS`` and friends
#: (:mod:`mureo.providers.mureo_env`). Set to the exact string ``"1"`` to keep
#: mureo from registering the bridge at all — the escape hatch for an operator
#: who has wired Amazon's own MCP into their host directly and does not want
#: the same tools exposed twice.
AMAZON_DISABLE_ENV_VAR = "MUREO_DISABLE_AMAZON_ADS"


def amazon_ads_disabled() -> bool:
    """Is the bridge switched off via :data:`AMAZON_DISABLE_ENV_VAR`?

    Exact-string ``== "1"``, the contract every other ``MUREO_DISABLE_*`` gate
    holds (``"0"`` / ``""`` / ``"true"`` / ``"  1  "`` leave it enabled). Read
    at CALL time rather than at import so both startup paths — the MCP server,
    which calls this during module import, and the configure UI, which calls it
    when the wizard is constructed — observe the same environment.
    """
    return os.environ.get(AMAZON_DISABLE_ENV_VAR) == "1"


def provider_entry() -> ProviderEntry:
    """Build the synthetic :class:`ProviderEntry` for the bridge.

    ``capabilities`` is empty on purpose: the bridge forwards Amazon's
    own MCP tools verbatim and implements none of mureo's domain
    Protocols, so it must not advertise a capability a
    capability-filtered lookup would then try to use.
    """
    return ProviderEntry(
        name=AMAZON_PROVIDER_NAME,
        display_name=AmazonAdsBridge.display_name,
        capabilities=frozenset(),
        provider_class=AmazonAdsBridge,
        source_distribution=AMAZON_SOURCE_DISTRIBUTION,
    )


def register_amazon_provider() -> ProviderEntry:
    """Register the bridge in ``default_registry``; return the live entry.

    Call this BEFORE entry-point discovery — see the module docstring's
    ordering contract; the built-in only beats a same-named third-party
    entry point if it registers first.

    Safe to call repeatedly and from either startup path. The membership
    check (rather than relying on ``register``'s first-wins branch) keeps
    a repeat call silent: ``Registry.register`` would otherwise emit a
    :class:`~mureo.core.providers.registry.RegistryWarning` every time,
    and deployments that run with ``filterwarnings("error")`` would turn
    a benign second call into a startup failure.

    Returns:
        The entry now registered under ``amazon_ads`` — this module's
        entry, or a previously registered one (first-wins).
    """
    if AMAZON_PROVIDER_NAME in default_registry:
        return default_registry.get(AMAZON_PROVIDER_NAME)
    entry = provider_entry()
    default_registry.register(entry)
    return entry


__all__ = [
    "AMAZON_DISABLE_ENV_VAR",
    "AMAZON_PROVIDER_NAME",
    "AMAZON_SOURCE_DISTRIBUTION",
    "amazon_ads_disabled",
    "provider_entry",
    "register_amazon_provider",
]
