"""Shared CSV-injection defense for BYOD bundle adapters.

Cells starting with one of these characters are treated as formulas by
Excel / Google Sheets when the exported CSV is re-opened. A campaign
named ``=cmd|...`` would auto-execute on re-open, exfiltrating data. We
sanitize untrusted, user-controlled cell values by prefixing a single
quote. OWASP "CSV Injection" — the leading quote is stripped on display
by Excel and renders as a literal at the start of the field elsewhere.

This helper is shared by every ``mureo/byod/adapters/<platform>.py``
so the sanitization logic stays identical across adapters; each adapter
imports :func:`sanitize_cell` and applies it to its own user-controlled
columns (campaign / ad-set / ad names, keywords, search terms, etc.).
"""

from __future__ import annotations

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: str) -> str:
    """Defang user-controlled cell content against CSV-injection."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value
