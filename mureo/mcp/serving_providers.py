"""Which tool family reaches this workspace's account on a built-in platform.

Why this exists
---------------
A plugin provider that declares ``serves_platform`` can publish a built-in
platform's tool surface again under its own prefix —
``meta_ads_acme_campaigns_list`` beside the built-in
``meta_ads_campaigns_list``: the same operations, separate credentials (see
``docs/plugin-authoring.md``, "Standing in for a built-in platform"). The
names alone do not say which family this workspace's account is configured
under, so an agent tends to try the built-in tool first; on a multi-account
backend that built-in call may even proceed, on whatever account the built-in
connection reaches.

Two answers come from here:

* the always-on notice (:func:`served_platforms_instructions`), one of the MCP
  server's ``instructions`` sections, naming per built-in platform the family
  this workspace's account is configured under;
* the refusal (:func:`builtin_refusal`) a built-in tool answers with at
  dispatch, before any handler, preflight read or network call, when the
  workspace scopes that platform to no built-in account and a provider serving
  it is configured — and the pointer (:func:`served_pointer`) the built-in
  no-credentials messages carry.

When the allow-list for the platform is empty, a built-in tool of that platform
is refused before its arguments are read, so the refusal is the same whatever
id the call carries; it names the plugin family and no id. When the allow-list
is non-empty, an explicit id it does not contain gets the allow-list's own
refusal, unchanged, with no pointer to another family. Which family holds
which account is stated up front by the notice. No pointer is given while a
credential source is active either: a plugin running a built-in handler under
:func:`~mureo.core.credential_source.use_credential_source` already is the
serving family, and pointing it at itself would send the agent in a loop.

The allow-list contract
-----------------------
With no credential source active, a workspace allow-list
(:func:`~mureo.core.runtime_context.runtime_meta_account_ids` and its
siblings) names the accounts the built-in connection may reach; an account
reached only through a serving plugin is not in it, and an empty set is what
makes the built-in family refuse and point at the plugin family. A plugin that
runs the built-in handlers under a credential source is still checked against
the allow-list, which the handler reads at call time inside the source's
context; a backend hosting such a plugin therefore returns, while that
plugin's source is active (``active_source_identity(platform)`` is not
``None``), the accounts that source may reach. A plugin that builds its own
client is outside this check and must scope its own account.

Static table, lazy check
------------------------
Which providers serve which platform, and under which prefix, is fixed when
the server loads (:func:`serving_providers`), from the same tool-ownership map
the other always-on blocks are scoped by, and only for platforms whose
built-in family this run serves: with the built-in family switched off there
is nothing to confuse. Whether a provider is *configured* is read at call time
from the runtime's secret store, and only when the table has an entry for the
platform, so an install without such a plugin never touches the store. Stored
values are only tested for presence; none is rendered or logged. The notice
is built once, when the server answers ``initialize``, so a credential or
allow-list change shows in the next session; the refusal and the pointer are
evaluated on every call.

The prefix is derived, not declared
-----------------------------------
A provider declares the platform, not a prefix. The prefix is what its tool
names have in front of the built-in operation they mirror
(:func:`mureo.policy.learning_reset.builtin_equivalent`): it must come out the
same for every such tool, start with ``<platform>_``, end with ``_``, pass the
always-on name rule and be the start of no built-in tool name, or the provider
gets no entry. A rendered prefix therefore cannot break a line, carry free
text or also name built-in tools.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from mureo.byod import runtime as byod_runtime
from mureo.core import runtime_context
from mureo.core.credential_source import current_credential_source
from mureo.core.platform_keys import BUILTIN_PLATFORM_DISPLAY_NAMES
from mureo.core.providers import (
    get_account_credential_fields,
    get_serves_platform,
    required_fields_stored,
)
from mureo.mcp._helpers import _no_creds_result
from mureo.mcp._plugin_tables import _SERVING_PROVIDERS
from mureo.policy.always_on_block import (
    is_renderable_name,
    is_single_line,
    render_block,
)
from mureo.policy.learning_reset import builtin_equivalent

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from mcp.types import TextContent

    from mureo.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

#: Longest the rendered notice may be — heading, platform lines, the newlines
#: joining them and the omission notice, all counted. The same budget the tool
#: notes block has.
MAX_TOTAL_CHARS = 1200

#: Built-in platform → its workspace allow-list resolver. ``None`` from the
#: resolver means the workspace is not account-scoped for that platform; an
#: empty set means it is scoped to no built-in account. Keyed by every
#: platform ``serves_platform`` may name (a test pins that).
_ALLOW_LISTS: Final[Mapping[str, Callable[[], frozenset[str] | None]]] = (
    MappingProxyType(
        {
            "google_ads": runtime_context.runtime_google_ads_customer_ids,
            "meta_ads": runtime_context.runtime_meta_account_ids,
            "search_console": runtime_context.runtime_search_console_sites,
        }
    )
)

_HEADING = (
    "Platform tool families — which tools reach this workspace's account. "
    "A plugin can serve a built-in platform under its own tool prefix: same "
    "operations, separate credentials."
)


@dataclass(frozen=True)
class ServingProvider:
    """A plugin provider that serves a built-in platform under its own prefix.

    Attributes:
        provider: The registry name, which is also its credentials section.
        tool_prefix: The prefix its tools carry in front of the built-in
            operation, e.g. ``"meta_ads_acme_"``.
        required_keys: The keys of its required
            ``account_credential_fields`` — what has to be stored for it to
            count as configured.
    """

    provider: str
    tool_prefix: str
    required_keys: tuple[str, ...]


# ---------------------------------------------------------------------------
# The static table, built at server load
# ---------------------------------------------------------------------------


def _platform_of(provider: object) -> str | None:
    """The built-in platform ``provider`` serves; a malformed claim drops it."""
    try:
        return get_serves_platform(provider)
    except (TypeError, ValueError) as exc:
        # Same handling as the configure UI: one provider's typo must not keep
        # the server from starting.
        logger.warning("plugin declaration rejected: %s", exc)
        return None


def _required_keys(provider: object) -> tuple[str, ...] | None:
    """Keys of ``provider``'s required fields; a malformed list drops it."""
    try:
        fields = get_account_credential_fields(provider)
    except TypeError as exc:
        logger.warning("plugin declaration rejected: %s", exc)
        return None
    return tuple(field.key for field in fields if field.required)


def _variant_prefixes(platform: str, tool_names: Iterable[str]) -> frozenset[str]:
    """Every prefix ``tool_names`` carry in front of a ``platform`` operation.

    A tool that mirrors no built-in operation of ``platform`` contributes
    nothing, so the set is empty for a provider whose ``serves_platform`` is
    only a configure-UI declaration.
    """
    builtin = f"{platform}_"
    prefixes: set[str] = set()
    for name in tool_names:
        equivalent = builtin_equivalent(name)
        if equivalent is None or equivalent == name:
            continue
        if not equivalent.startswith(builtin):
            continue
        operation = equivalent[len(builtin) :]
        prefixes.add(name[: len(name) - len(operation)])
    return frozenset(prefixes)


def _prefix_problem(
    platform: str, prefixes: frozenset[str], builtin_names: frozenset[str]
) -> str | None:
    """Why the one prefix ``prefixes`` should hold cannot be used, or ``None``."""
    if len(prefixes) != 1:
        return f"its tools carry {len(prefixes)} different prefixes"
    (prefix,) = prefixes
    shaped = prefix.startswith(f"{platform}_") and prefix.endswith("_")
    if not shaped or not is_renderable_name(prefix):
        return "its prefix is not a renderable <platform>_<suffix>_"
    if any(name.startswith(prefix) for name in builtin_names):
        return f"built-in tool names also start with {prefix}"
    return None


def _serving_provider(
    owner: str,
    provider: object,
    tool_names: Iterable[str],
    builtin_tool_names: Mapping[str, frozenset[str]],
) -> tuple[str, ServingProvider] | None:
    """``(platform, row)`` for one provider, or ``None`` when it serves none."""
    platform = _platform_of(provider)
    if platform is None or platform not in builtin_tool_names:
        return None
    prefixes = _variant_prefixes(platform, tool_names)
    if not prefixes:
        logger.debug("provider %r serves %s with no mirrored tool", owner, platform)
        return None
    if owner in BUILTIN_PLATFORM_DISPLAY_NAMES:
        # Its credentials section would be the built-in platform's own.
        logger.warning("provider %r is named like a built-in platform", owner)
        return None
    problem = _prefix_problem(platform, prefixes, builtin_tool_names[platform])
    if problem is not None:
        logger.warning(
            "provider %r serves %s but gets no routing entry: %s",
            owner,
            platform,
            problem,
        )
        return None
    keys = _required_keys(provider)
    if keys is None:
        return None
    (prefix,) = prefixes
    return platform, ServingProvider(owner, prefix, keys)


def serving_providers(
    tool_owners: Mapping[str, str],
    dispatch: Mapping[str, object],
    builtin_tool_names: Mapping[str, frozenset[str]],
) -> dict[str, tuple[ServingProvider, ...]]:
    """Built-in platform → the providers serving it, by provider name.

    ``tool_owners`` is the ownership map
    :func:`~mureo.mcp.tool_provider.served_tool_owners` returns (served plugin
    tools only), ``dispatch`` maps each of those tools to its provider object,
    and ``builtin_tool_names`` maps each built-in family this run serves to
    the tool names it serves; a provider serving any other platform gets no
    entry.
    """
    tools_by_owner: dict[str, list[str]] = {}
    for name, owner in tool_owners.items():
        tools_by_owner.setdefault(owner, []).append(name)
    table: dict[str, list[ServingProvider]] = {}
    for owner in sorted(tools_by_owner):
        names = sorted(tools_by_owner[owner])
        provider = dispatch.get(names[0])
        found = _serving_provider(owner, provider, names, builtin_tool_names)
        if found is not None:
            table.setdefault(found[0], []).append(found[1])
    return {platform: tuple(rows) for platform, rows in sorted(table.items())}


# ---------------------------------------------------------------------------
# The runtime check
# ---------------------------------------------------------------------------


def _section_configured(store: SecretStore, row: ServingProvider) -> bool:
    """Whether ``row``'s credentials section holds every required field."""
    try:
        saved = store.load(row.provider)
    # Any backend's store may raise; an unreadable section is not configured.
    except Exception as exc:  # noqa: BLE001 — unreadable means not configured
        logger.warning(
            "credentials section %r could not be read (%s); treated as not configured",
            row.provider,
            type(exc).__name__,
        )
        return False
    if not isinstance(saved, Mapping):
        return False
    return required_fields_stored(
        (True, bool(saved.get(key))) for key in row.required_keys
    )


def configured_serving_providers(platform: str) -> tuple[ServingProvider, ...]:
    """The providers serving ``platform`` whose credentials are configured.

    ``()`` without touching the runtime context when no provider serves
    ``platform``, and when the runtime-context factory is misconfigured — that
    error surfaces on the first tool call, as it already does.
    """
    rows = _SERVING_PROVIDERS.get(platform, ())
    if not rows:
        return ()
    try:
        store = runtime_context.get_runtime_context().secret_store
    except runtime_context.RuntimeContextFactoryError:
        return ()
    return tuple(row for row in rows if _section_configured(store, row))


def _allow_list(platform: str) -> frozenset[str] | None:
    """``platform``'s workspace allow-list; ``None`` when not scoped."""
    resolver = _ALLOW_LISTS.get(platform)
    if resolver is None:
        return None
    try:
        return resolver()
    except runtime_context.RuntimeContextFactoryError:
        return None


def builtin_without_account(platform: str) -> bool:
    """True when the workspace scopes ``platform`` to no built-in account."""
    allowed = _allow_list(platform)
    return allowed is not None and not allowed


# ---------------------------------------------------------------------------
# The sentences
# ---------------------------------------------------------------------------


def _label(platform: str) -> str:
    """The display name of built-in ``platform``."""
    return BUILTIN_PLATFORM_DISPLAY_NAMES.get(platform, platform)


def _families(rows: Iterable[ServingProvider]) -> str:
    """``rows`` as their ``<prefix>*`` tool families, joined by " or "."""
    return " or ".join(f"{row.tool_prefix}*" for row in rows)


def served_pointer(platform: str) -> str:
    """The sentence naming the configured serving family, or ``""``.

    ``""`` while a credential source is active: the caller is then a plugin
    running the built-in handler as the serving family itself.
    """
    if current_credential_source() is not None:
        return ""
    rows = configured_serving_providers(platform)
    if not rows:
        return ""
    return (
        f"This workspace's {_label(platform)} account is configured under the "
        f"{_families(rows)} tools — use those instead."
    )


def with_pointer(message: str, pointer: str) -> str:
    """``message``, followed by ``pointer`` when there is one."""
    return f"{message} {pointer}" if pointer else message


def builtin_refusal(tool_name: str, family: str) -> list[TextContent] | None:
    """The refusal a built-in platform tool answers with, or ``None``.

    ``family`` is the dispatcher family ``tool_name`` belongs to. Only when
    that is a built-in platform this run serves, the workspace scopes it to no
    built-in account, it is not served from a local data manifest (BYOD), and
    a provider serving it is configured. The shape is the built-in
    no-credentials result: the built-in family has no account here. It is
    decided before the call's arguments are read, so it is the same
    whatever id the call carries, and names the plugin family and no id.
    An allow-list read that raises propagates, so the call does not run.
    """
    if family not in _SERVING_PROVIDERS or not builtin_without_account(family):
        return None
    if byod_runtime.byod_has(family):
        return None
    pointer = served_pointer(family)
    if not pointer:
        return None
    return _no_creds_result(
        f"The built-in {family}_* tools have no {_label(family)} account "
        f"configured in this workspace, so {tool_name} was not run. {pointer}"
    )


# ---------------------------------------------------------------------------
# The always-on notice
# ---------------------------------------------------------------------------


def _omission_note(count: int) -> str:
    """The line that stops a truncated block reading as a complete one."""
    return (
        f"NOTE: this list is INCOMPLETE — {count} further platform line(s) did "
        f"not fit in this block's length budget."
    )


def _platform_line(platform: str) -> str | None:
    """One platform's line, by what the built-in side has, or ``None``."""
    rows = configured_serving_providers(platform)
    if not rows:
        return None
    label, families, builtin = _label(platform), _families(rows), f"{platform}_"
    allowed = _allow_list(platform)
    if allowed is None:
        return (
            f"- {label}: this workspace's account is configured under the "
            f"{families} tools; use them. The built-in {builtin}* tools work "
            f"only if the built-in connection is set up too."
        )
    if not allowed:
        return (
            f"- {label}: use the {families} tools. The built-in {builtin}* "
            f"tools have no account configured in this workspace and refuse."
        )
    return (
        f"- {label}: accounts are configured under both the built-in "
        f"{builtin}* tools and the {families} tools. Use each family only for "
        f"the account configured under it, and never read or change one "
        f"account through both."
    )


def _notice_line(platform: str) -> str | None:
    """:func:`_platform_line`, with a failure costing only that line."""
    try:
        return _platform_line(platform)
    # An allow-list resolver may be a backend store property that raises; the
    # notice is built while the server starts, which one line must not stop.
    except Exception as exc:  # noqa: BLE001 — one line must not stop startup
        logger.warning(
            "platform tool family line for %s omitted (%s)",
            platform,
            type(exc).__name__,
        )
        return None


def served_platforms_instructions() -> str:
    """Render the always-on platform tool families block, within budget.

    One line per built-in platform with a configured serving provider, in
    platform-key order. Returns ``""`` when there is none, which keeps a
    default install's ``InitializeResult`` byte-identical.
    """
    entries = []
    for platform in sorted(_SERVING_PROVIDERS):
        line = _notice_line(platform)
        if line is not None and is_single_line(line):
            entries.append((platform, line))
    block, dropped = render_block(_HEADING, entries, MAX_TOTAL_CHARS, _omission_note)
    if dropped:
        logger.warning(
            "platform tool family block exceeds %d characters; omitted: %s",
            MAX_TOTAL_CHARS,
            ", ".join(dropped),
        )
    return block


__all__ = [
    "MAX_TOTAL_CHARS",
    "ServingProvider",
    "builtin_refusal",
    "builtin_without_account",
    "configured_serving_providers",
    "served_platforms_instructions",
    "served_pointer",
    "serving_providers",
    "with_pointer",
]
