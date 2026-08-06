"""One ad account, one platform key — the shared join (Issues #533 / #534).

STATE.json's ``platforms`` map is keyed by a free-form string, and nothing in
the key tells you which ad account it describes. Two spellings of the same
platform — the key an agent chose while running a skill, and the key a separate
automated writer used — therefore produce **two entries for one real ad
account**, and the reporting view sums every entry, so spend, conversions and
CPA all inflate together (#533).

Detecting that is one rule with **three** consumers:

- the STATE.json write guards in :mod:`mureo.context.state`, which refuse a
  write that would CREATE a second key for an account another key already
  holds, and warn (never reject) when a whole document arrives already
  carrying one;
- the read-only Reports view, which surfaces an existing conflict rather than
  silently adding the entries together;
- out-of-tree writers (mureo-agency) that assemble a whole ``StateDocument``
  themselves and never call the upsert helpers.

This module is the single source of that rule. Reimplementing it in any of the
three would let the definitions drift, and drift here re-creates the bug.

The join has exactly one subtlety, and it is load-bearing: **an empty
``account_id`` means UNKNOWN, never a value.** The tolerant read path
synthesizes ``""`` for a missing ``account_id``
(:func:`mureo.context.state._platform_account_id`), so treating ``""`` as a
value would join every id-less entry in a document into one bogus "account".

Deliberately dependency-free — stdlib plus the frozen ``PlatformState`` model
(for typing only), so every consumer can import it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.models import PlatformState

ACCOUNT_ID_PREFIX = "act_"
"""Optional prefix Meta ad account ids carry (``act_123`` == ``123``).

The MCP setter stores whatever id the operator/agent passed, while the live
clients enforce the ``act_*`` form — so a join that did not fold this would
read two spellings of one account as two accounts.
"""


@dataclass(frozen=True)
class DuplicateAccountEntry:
    """Two or more ``platforms`` keys that resolve to one ad account.

    ``account_id`` is the id **as stored** on the first of ``platform_keys``
    (not the normalized form), so an operator can find it in the file.
    ``platform_keys`` is in document order and always has at least two
    entries.

    Frozen and hashable, so a caller can use it directly as a warn-once latch
    key (see :func:`mureo.context.state._warn_on_duplicate_accounts`).
    """

    account_id: str
    platform_keys: tuple[str, ...]


def normalize_account_id(account_id: object) -> str:
    """Fold ``account_id`` to the form the join compares.

    Strips surrounding whitespace and an optional ``act_`` prefix. An
    **unknown** id (``None``, empty, or whitespace-only) folds to ``""``, which
    :func:`account_ids_match` treats as matching nothing at all — including
    another unknown id.

    Case: the **prefix** folds case-insensitively (``ACT_1`` == ``act_1`` ==
    ``1``), the rest of the id does **not** (``AbC`` != ``abc``). Real ad
    account ids are numeric so this is nearly moot, but a plugin platform may
    use a case-significant alphanumeric id, and folding the whole string would
    silently join two genuinely different accounts — the exact failure this
    module exists to prevent.

    Type: takes ``object``, not ``str``, on purpose. A non-string (a
    hand-edited ``"account_id": 12345``, i.e. a JSON number) is folded to its
    ``str()`` form rather than raising. This module is consumed out-of-tree by
    writers that assemble ``PlatformState`` from loosely-typed sources, and it
    is a **detection** helper — raising here would surface as an unrelated
    ``AttributeError`` from inside a write guard, whereas coercing keeps the
    duplicate detectable, which is the whole point. ``None`` is the one
    non-string that is NOT coerced: ``str(None) == "None"`` would join every
    id-less entry under a bogus account.
    """
    if account_id is None:
        return ""
    text = account_id if isinstance(account_id, str) else str(account_id)
    text = text.strip()
    if text[: len(ACCOUNT_ID_PREFIX)].lower() == ACCOUNT_ID_PREFIX:
        return text[len(ACCOUNT_ID_PREFIX) :]
    return text


def account_ids_match(a: object, b: object) -> bool:
    """Return ``True`` when ``a`` and ``b`` are the same KNOWN ad account.

    An unknown id on either side never matches — ``account_ids_match("", "")``
    is ``False``. That is the whole point: ``""`` means "this entry did not say
    which account it describes", and two entries that both declined to say are
    not thereby the same account.
    """
    normalized = normalize_account_id(a)
    return bool(normalized) and normalized == normalize_account_id(b)


def platform_keys_for_account(
    platforms: Mapping[str, PlatformState] | None, account_id: object
) -> tuple[str, ...]:
    """Return every key in ``platforms`` whose entry describes ``account_id``.

    Document order. Empty when ``account_id`` is unknown, when ``platforms``
    is ``None``/empty, or when no entry matches — so a caller can read the
    result as "the keys this account is already stored under".
    """
    if not platforms or not normalize_account_id(account_id):
        return ()
    return tuple(
        key
        for key, entry in platforms.items()
        if account_ids_match(entry.account_id, account_id)
    )


def duplicate_account_entries(
    platforms: Mapping[str, PlatformState] | None,
) -> tuple[DuplicateAccountEntry, ...]:
    """Group ``platforms`` keys that resolve to ONE ad account.

    Returns one :class:`DuplicateAccountEntry` per account held under two or
    more keys, in the document order of each group's first key; an account
    under a single key, and every entry with an unknown ``account_id``, are
    omitted. An empty result means the document has no duplicate to report.

    This is *detection*, not repair: the grouped entries typically hold
    different **partial** figures, so dropping either under-counts as much as
    summing over-counts. What to do about a group is the caller's decision —
    the write path refuses to create a new one, the read path surfaces it, and
    neither merges or deletes anything.
    """
    if not platforms:
        return ()
    grouped: dict[str, tuple[str, list[str]]] = {}
    for key, entry in platforms.items():
        normalized = normalize_account_id(entry.account_id)
        if not normalized:  # unknown — never a join key
            continue
        if normalized not in grouped:
            grouped[normalized] = (entry.account_id, [])
        grouped[normalized][1].append(key)
    return tuple(
        DuplicateAccountEntry(account_id=stored_id, platform_keys=tuple(keys))
        for stored_id, keys in grouped.values()
        if len(keys) > 1
    )


__all__ = [
    "ACCOUNT_ID_PREFIX",
    "DuplicateAccountEntry",
    "account_ids_match",
    "duplicate_account_entries",
    "normalize_account_id",
    "platform_keys_for_account",
]
