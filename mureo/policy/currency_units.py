"""Meta minor units → currency units, for the strategy gate's caps (#783).

The ``## Guardrails`` caps are written in the account's CURRENCY units, and
every other channel the gate reads arrives that way: Google's ``*_micros`` are
divided by 1e6, the caller-supplied ``current_daily_budget`` /
``projected_total_daily_budget`` are currency units by mureo's own convention.
Meta is the exception. Its write tools take ``daily_budget`` /
``lifetime_budget`` / ``bid_amount`` in the account currency's MINOR units
(``mureo/meta_ads/_campaigns.py``, ``mureo/meta_ads/_ad_sets.py``: "cents for
USD, whole yen for JPY"), and the gate used to compare those raw figures with
the caps. On a zero-decimal account (JPY) the two units coincide and nothing
showed; on a EUR/USD account ``max_daily_budget_per_campaign: 250`` refused a
``daily_budget`` of ``25000`` (= €250.00) and allowed nothing above €2.50.

The gate is synchronous, pure and I/O-free by the ``PolicyGate`` v1 contract,
so it cannot ask Meta what the account currency is — the operator declares it
in a ``currency`` bullet, and this module turns that declaration into the
divisor. No declaration ⇒ no conversion ⇒ exactly the old behaviour, which is
correct for zero-decimal currencies and documented as the fallback.

This module also owns :func:`_amount`, the deny-message number format: once a
comparison can carry cents, ``:,.0f`` would print "250 exceeds the cap of 250"
for a proposal of 250.50.
"""

from __future__ import annotations

import logging

from mureo.core.providers.models import minor_units_per_unit

logger = logging.getLogger(__name__)

__all__ = [
    "META_MINOR_UNIT_KEYS",
    "META_TOOL_PREFIX",
    "NO_CONVERSION_DIVISOR",
    "minor_unit_divisor",
    "parse_currency_code",
    "to_currency_units",
]

#: The native Meta tool namespace. Only these tools carry minor units; a
#: Google tool's amounts are micros or currency units, and a plugin tool owns
#: its own vocabulary (and declares it — see
#: :mod:`mureo.policy.declarations`), so neither is ever converted here.
META_TOOL_PREFIX = "meta_ads_"

#: The Meta write-tool arguments documented as account-currency MINOR units.
#: Deliberately exact rather than shape-matched: the sibling spellings the
#: built-in scan also accepts (``proposed_daily_budget``, ``amount``,
#: ``total_amount``, the ``*_micros`` keys) are already currency units, and
#: dividing one of those would under-enforce the cap by 100x.
META_MINOR_UNIT_KEYS = frozenset({"daily_budget", "lifetime_budget", "bid_amount"})

#: "Leave the amount as it is" — no declared currency, or a zero-decimal one
#: whose minor unit IS its currency unit.
NO_CONVERSION_DIVISOR = 1


def parse_currency_code(raw: str | None) -> str | None:
    """Validate one ``currency`` bullet value, or ``None`` when unusable.

    Upper-cased and validated against Meta's own offset table
    (:func:`~mureo.core.providers.models.minor_units_per_unit`). An
    unrecognized code is DROPPED with one warning rather than guessed at —
    the same "a malformed value drops that one rule" policy the rest of the
    ``## Guardrails`` parser follows. Dropping it leaves Meta amounts
    compared in minor units, which is the fail-closed direction on an
    offset-100 account.
    """
    if raw is None:
        return None
    code = raw.strip().upper()
    if not code:
        return None
    try:
        minor_units_per_unit(code)
    except ValueError:
        logger.warning(
            "STRATEGY.md Guardrails: unknown currency %r ignored; Meta amounts "
            "are compared in minor units",
            raw,
        )
        return None
    return code


def minor_unit_divisor(tool_name: str, currency: str | None) -> int:
    """How many minor units one currency unit is worth, for THIS call.

    :data:`NO_CONVERSION_DIVISOR` unless the call is a native Meta tool and
    the operator declared a currency; then Meta's per-currency offset (1 for
    a zero-decimal currency such as JPY, 100 otherwise).

    A ``ValueError`` from an unknown code is left to propagate: the code was
    validated by :func:`parse_currency_code` when the bullet was read, so an
    invalid one here is a programming error, and the gate's blanket
    ``except`` (abstain) is the existing contract for those.
    """
    if currency is None or not tool_name.startswith(META_TOOL_PREFIX):
        return NO_CONVERSION_DIVISOR
    return minor_units_per_unit(currency)


def to_currency_units(value: float, divisor: int) -> float:
    """``value`` in minor units → currency units.

    A non-finite input stays non-finite (``inf / 100`` is ``inf``), so an
    oversized int that :func:`~mureo.policy.declarations._saturate` turned
    into ``inf`` still fails closed at the caller's finiteness check instead
    of being divided back into range.
    """
    if divisor == NO_CONVERSION_DIVISOR:
        return value
    return value / divisor


def _amount(value: float) -> str:
    """A money figure for a deny message: ``250`` / ``250.50`` / ``1,234.56``.

    Once a Meta amount is divided into currency units a comparison can carry
    cents, and the old ``:,.0f`` printed 250.50 as "250" — a refusal reading
    "250 exceeds the cap of 250". An integral value renders exactly as it did
    before, so the messages operators (and the suite) already know are
    unchanged. An ``int`` (a ``Guardrails`` built in code rather than parsed
    carries them) is integral by definition, so it is formatted without
    consulting ``float.is_integer``.
    """
    if isinstance(value, int) or value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"
