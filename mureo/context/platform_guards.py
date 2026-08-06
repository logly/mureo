"""Write-time guards for STATE.json's ``platforms`` map (Issue #534).

Two guards, at two different layers, doing deliberately different jobs:

- :func:`guard_platform_entry_write` **refuses** a targeted write that would
  create a second platform key for one ad account. It is called by the
  ``platforms``-touching writers in :mod:`mureo.context.state`, from inside
  their locked ``_build``, so a rejection lands before anything is written.
- :func:`warn_on_duplicate_accounts` only **reports**. It hangs off
  ``write_state_file``, the funnel every whole-document writer passes through,
  and exists because such a writer never calls the targeted helpers at all.

Both delegate the "is this the same ad account?" question to
:mod:`mureo.context.platform_accounts`, which is the single source of that
rule (shared with the read-only Reports view and with out-of-tree writers).
This module is the **policy** layer over that join: what to refuse, what to
merely report, and what to leave alone. It lives beside ``state.py`` rather
than inside it because nothing else in that module needs it.

The rule :func:`guard_platform_entry_write` enforces
--------------------------------------------------

"Would create a duplicate" is **not** "the target key is absent": reusing an
existing key while changing which account it points at manufactures a new
duplicate just as surely. So the decision branches on what the entry already
says:

1. **The key does not exist.** A true create: validate the key's shape
   (:func:`reject_unusable_platform_key`) and refuse if another key already
   holds ``account_id``.
2. **The key exists and its stored id matches the incoming one.** A plain
   update — nothing about identity changes, so allow it. The match is
   ``act_``-tolerant, so re-writing ``123456`` as ``act_123456`` is still an
   update, not a re-point.
3. **The key exists and its stored id is UNKNOWN (``""``).** Allow — even if
   the incoming id is already held by another key. This branch is deliberate
   and is not a hole: stamping an identity onto an entry that had none cannot
   create a real-world duplicate. If the two keys really are one account, that
   was *already true* and merely invisible; the write is what makes it
   **detectable** by
   :func:`~mureo.context.platform_accounts.duplicate_account_entries` and
   therefore surfaceable to the operator. Rejecting here would block the very
   write that reveals the problem, so this is the repair path and it stays
   open.
4. **The key exists and its stored id is known and different.** A re-point:
   refuse if another key already holds the incoming account, allow if nobody
   does (an operator legitimately switching which account a platform tracks).
   The key's shape is *not* re-validated — the entry already exists, and
   refusing here would strand an operator holding a padded or unusable key
   rather than letting them keep working.

The thread through all four: **refuse to create a new problem, never strand an
operator who already has one.** Nothing here deletes or merges an entry either
— the two halves of a duplicate typically hold different *partial* figures, so
the repair is the operator's call, informed by the read side.

One corner this does **not** defend: writing an explicit ``account_id=""``
onto an entry that holds a known id silently reverts that entry to "unknown",
because ``""`` is by contract free rather than taken. The MCP surface blocks
it (schema ``minLength`` plus the handler's own check), so a caller reaching
these functions from **outside** that gate — anything assembling
``PlatformState`` from loosely-typed sources — must pass the entry's existing
id, never ``""`` to mean "leave it alone".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mureo.context.platform_accounts import (
    DuplicateAccountEntry,
    account_ids_match,
    duplicate_account_entries,
    normalize_account_id,
    platform_keys_for_account,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import PlatformState, StateDocument

logger = logging.getLogger(__name__)

_DUPLICATE_ACCOUNT_WARNED: set[tuple[str, DuplicateAccountEntry]] = set()
"""Process-wide latch for the duplicate-account warning.

Keyed by ``(state file path, group)``: :func:`warn_on_duplicate_accounts` runs
on EVERY state write, so warning per call would flood the log for an operator
whose document already carries a duplicate — while keying by group means one
reported pair can never silence another, and including the path means one
workspace's duplicate cannot silence the identical duplicate in a different
workspace (an agency process serves many).

Growth is bounded by :data:`_DUPLICATE_ACCOUNT_WARN_LATCH_MAX`. Without that
cap the set would grow with the number of distinct (workspace, duplicate
group) pairs a long-lived multi-tenant process encounters — small in practice,
since a duplicate is a defect an operator repairs, but not bounded by
anything structural. On reaching the cap the latch is cleared rather than
evicted selectively: the failure mode of a cleared latch is warning again,
which is the safe direction for a visibility feature.
"""

_DUPLICATE_ACCOUNT_WARN_LATCH_MAX = 256
"""Cap on :data:`_DUPLICATE_ACCOUNT_WARNED` before it is cleared."""


def reject_unusable_platform_key(platform: str) -> None:
    """Reject a ``platform`` string that cannot serve as a map key (#534).

    Three shapes are refused, and **nothing is rewritten**:

    - an empty / whitespace-only key, which indexes an entry no surface can
      resolve a platform from;
    - a key with surrounding whitespace (``" google_ads"``), which is a
      distinct dict key from the unpadded one and so is another route to two
      entries for one account — never intentional;
    - a key that claims the plugin namespace without being canonical
      (a bare ``"plugin:"`` carries no distribution, so it joins with
      nothing — see :mod:`mureo.core.platform_keys`).

    Why reject rather than silently canonicalize or strip: the write path
    cannot tell a bare distribution name from a built-in key or an arbitrary
    string, so ``plugin_platform_key()`` applied here would fabricate
    ``plugin:google_ads`` from a built-in. Where the canonical form IS knowable
    — a key that is already canonical — that call is a no-op by construction.
    And rewriting the key an operator passed changes the key they see in
    STATE.json and on the dashboard without saying so, which is the same class
    of silent divergence this guard exists to stop.

    Create-only; see :func:`guard_platform_entry_write`.
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context`` ->
    # ``state_store`` -> ``mureo.context.state``, which imports this module —
    # a module-level import here would be a cycle.
    from mureo.core.platform_keys import (
        PLUGIN_PLATFORM_PREFIX,
        is_plugin_platform_key,
    )

    if not platform.strip():
        raise ValueError("platform must be a non-empty platform key")
    if platform != platform.strip():
        raise ValueError(
            f"platform {platform!r} has surrounding whitespace, which makes it "
            f"a different key from {platform.strip()!r} — pass the key without "
            f"it (it is not stripped for you, so the stored key always stays "
            f"the one you passed)"
        )
    if platform.startswith(PLUGIN_PLATFORM_PREFIX) and not is_plugin_platform_key(
        platform
    ):
        raise ValueError(
            f"platform {platform!r} is not a usable platform key: a plugin "
            f"platform key is {PLUGIN_PLATFORM_PREFIX}<distribution> "
            f"(e.g. {PLUGIN_PLATFORM_PREFIX}mureo-logly-bridge)"
        )


def _reject_account_already_taken(
    platforms: dict[str, PlatformState],
    platform: str,
    account_id: str,
    *,
    creating: bool,
) -> None:
    """Refuse when ``account_id`` is already stored under a different key.

    ``platforms`` is keyed by an arbitrary string and ``account_id`` was never
    consulted, so a writer using a different spelling of the same platform
    silently produced a second entry for one real account — which the reports
    view then adds to the first (#533).

    ``creating`` only picks the verb in the message: refusing to *create* a
    key and refusing to *re-point* an existing one at a taken account are the
    same rule, and the operator needs to be told which of the two they just
    attempted.

    The join lives in :mod:`mureo.context.platform_accounts` — ``act_``
    tolerant, and treating an empty ``account_id`` as UNKNOWN rather than as a
    value, because the tolerant read path synthesizes ``""`` for a missing one.
    """
    existing_keys = platform_keys_for_account(platforms, account_id)
    if not existing_keys:
        return
    named = ", ".join(repr(k) for k in existing_keys)
    what = "create" if creating else "re-point"
    raise ValueError(
        f"refusing to {what} platform {platform!r}: account_id "
        f"{account_id!r} is already stored under platform {named}. Two "
        f"platform keys for one ad account are summed by the reporting view, "
        f"so the KPIs would double-count. Write to {existing_keys[0]!r} "
        f"instead, or repair STATE.json first if these are genuinely "
        f"different accounts."
    )


def guard_platform_entry_write(
    platforms: dict[str, PlatformState], platform: str, account_id: str
) -> None:
    """Refuse a write that would create a duplicate ad-account entry (#534).

    The four branches below, and the reasoning for each, are set out in this
    module's docstring — including why branch (3) allows a write that looks
    like it should be refused, and the one corner this does not defend.

    Raises ``ValueError`` on a rejected write. Called from inside each writer's
    ``_build``, i.e. under the state lock against the document just read, so a
    rejection propagates out of ``_locked_state_mutation`` before anything is
    written.
    """
    existing = platforms.get(platform)
    if existing is None:  # (1) create
        reject_unusable_platform_key(platform)
        _reject_account_already_taken(platforms, platform, account_id, creating=True)
        return
    if account_ids_match(existing.account_id, account_id):  # (2) plain update
        return
    if not normalize_account_id(existing.account_id):  # (3) stamping an id on
        return
    # (4) re-point. The stored id differs from the incoming one, so this key
    # cannot be among the matches — no need to exclude it.
    _reject_account_already_taken(platforms, platform, account_id, creating=False)


def warn_on_duplicate_accounts(path: Path, doc: StateDocument) -> None:
    """Log one warning per ad account held under two or more platform keys.

    **Detection, not enforcement — this must never reject a write.** A document
    that already carries a duplicate has to stay writable, or the operator
    holding that state can neither sync nor repair it. Enforcement cannot live
    here for a second reason: a whole-document write carries no notion of which
    entry is "new", so there is nothing to refuse — the create-vs-update
    distinction only exists in the targeted writers
    (:func:`guard_platform_entry_write`), which is why they do the refusing.

    What this covers that they cannot: a writer that assembles a complete
    :class:`~mureo.context.models.StateDocument` itself and writes it wholesale
    — mureo-agency's digest sync is the observed one — never calls
    ``upsert_campaign`` / ``set_platform_metrics`` /
    ``set_conversion_action_types``, so the create-time guard never sees it.
    Every such writer still funnels through ``write_state_file``
    (``FilesystemStateStore.write_state`` included), so the duplicate is at
    least made visible in the log instead of silently double-counting on a
    client card.

    Warns once per process per ``(path, group)`` — this runs on every write.
    Never raises: a detection failure must not take down a state write.
    """
    try:
        for group in duplicate_account_entries(doc.platforms):
            key = (str(path), group)
            if key in _DUPLICATE_ACCOUNT_WARNED:
                continue
            logger.warning(
                "%s: ad account %s is stored under %d platform keys (%s). The "
                "reporting view sums every entry, so this account's spend / "
                "conversions / CPA are double-counted. Keep one key per ad "
                "account; mureo does not merge or drop either entry because "
                "they may hold different partial figures.",
                path,
                group.account_id,
                len(group.platform_keys),
                ", ".join(group.platform_keys),
            )
            if len(_DUPLICATE_ACCOUNT_WARNED) >= _DUPLICATE_ACCOUNT_WARN_LATCH_MAX:
                # Bounded, and biased towards visibility: a cleared latch
                # re-warns, it never goes quiet.
                _DUPLICATE_ACCOUNT_WARNED.clear()
            _DUPLICATE_ACCOUNT_WARNED.add(key)
    except Exception:  # noqa: BLE001 — a detection hint must never break a write
        logger.debug("duplicate-account detection failed", exc_info=True)


__all__ = [
    "guard_platform_entry_write",
    "reject_unusable_platform_key",
    "warn_on_duplicate_accounts",
]
