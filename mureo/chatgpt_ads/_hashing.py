"""Normalising and hashing custom audience identifiers (#995).

Pure functions, no I/O. The API accepts plaintext emails and phone numbers,
but mureo hashes them here and sends only the SHA-256 types, so no plaintext
identifier leaves the process. The normalisation is the one the API
reference documents for audience identifiers: an email is trimmed and
lowercased with its dots and plus tags kept; a phone number is E.164
including the ``+`` and the country code; the digest is SHA-256 of the UTF-8
value as 64 lowercase hex characters. A Google Advertising ID is sent raw,
because the API requires it unhashed and hashes it itself. (The Conversions
API and the Pixel normalise phone numbers differently; that rule is not this
one.)

A value that does not fit its type is reported as invalid (``None``), never
repaired: a number without its country code is not guessed at, and an email
line must be a plain ASCII address.

:func:`without_identifiers` masks the same shapes inside a platform error
message, so an add or remove whose answer echoes its request body cannot
carry a digest or an advertising id into a tool result or a log line.
"""

from __future__ import annotations

import hashlib
import re

#: The ``identifier_type`` an operator names → the type it is sent as. The
#: two plaintext types are hashed first, so neither is ever sent.
SENT_IDENTIFIER_TYPES = {
    "email": "email_sha256",
    "phone": "phone_number_sha256",
    "gaid": "gaid",
    "email_sha256": "email_sha256",
    "phone_number_sha256": "phone_number_sha256",
}
IDENTIFIER_TYPES = tuple(SENT_IDENTIFIER_TYPES)

#: E.164: ``+``, a first digit 1-9, 7 to 15 digits in total.
_E164 = re.compile(r"\+[1-9][0-9]{6,14}")
#: Separators people write inside a phone number; removed before the check.
_PHONE_SEPARATORS = str.maketrans("", "", " -.()")
#: A bracketed zero, as in ``+44 (0)20 ...``: a national trunk prefix that is
#: not part of the E.164 number, and dropping the brackets would keep it.
_TRUNK_ZERO = re.compile(r"\(\s*0\s*\)")

#: The two identifier shapes, spelled once: the validators below match them
#: whole, and :func:`without_identifiers` finds them inside text.
_HEX = "[0-9a-f]"
_DIGEST_SHAPE = f"{_HEX}{{64}}"
_UUID_SHAPE = f"{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}"
_HEX_DIGEST = re.compile(_DIGEST_SHAPE)
_UUID = re.compile(_UUID_SHAPE)
#: A hex run of a digest's length or longer (digests echoed back to back
#: have no separator), or an advertising id, in any case. A shorter run is
#: left alone: a generated idempotency key is 32 hex characters.
_IDENTIFIER_RUN = re.compile(f"{_DIGEST_SHAPE}{_HEX}*|{_UUID_SHAPE}", re.IGNORECASE)
#: What replaces an identifier-shaped run; the mask secrets get elsewhere.
_MASK = "***"
#: The reference requires a nonzero advertising id.
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"

#: Characters an email line may not hold, each with its reason: ``"`` ``,``
#: ``;`` come from quoted or joined spreadsheet cells; ``:`` from a
#: ``mailto:`` prefix; angle, round and square brackets and the backslash
#: from display-name or comment syntax. Each would be hashed into a digest
#: that matches nobody.
_EMAIL_FORBIDDEN = frozenset('",;:<>()[]\\')
#: Printable ASCII other than space. Anything else is an invisible character
#: (a zero-width space, a byte-order mark, a NUL) or a non-ASCII letter, and
#: the reference does not say how the platform folds case or encodes a
#: non-ASCII address, so a digest computed here could silently match nobody.
_EMAIL_FIRST, _EMAIL_LAST = "!", "~"
#: The domain may neither start nor end with these.
_DOMAIN_EDGES = ".-"


def sha256_hex(value: str) -> str:
    """SHA-256 of ``value``'s UTF-8 bytes as 64 lowercase hex characters."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def without_identifiers(text: str) -> str:
    """``text`` with every digest- or advertising-id-shaped run masked."""
    return _IDENTIFIER_RUN.sub(_MASK, text)


def _plain_address(address: str) -> bool:
    """Is ``address`` (trimmed, lowercased) a plain ASCII email address?"""
    local, at, domain = address.partition("@")
    return (
        bool(at and local and domain)
        and "@" not in domain
        and all(_EMAIL_FIRST <= ch <= _EMAIL_LAST for ch in address)
        and _EMAIL_FORBIDDEN.isdisjoint(address)
        and "." in domain
        and domain[0] not in _DOMAIN_EDGES
        and domain[-1] not in _DOMAIN_EDGES
    )


def _email(raw: str) -> str | None:
    address = raw.strip().lower()
    return sha256_hex(address) if _plain_address(address) else None


def _phone(raw: str) -> str | None:
    trimmed = raw.strip()
    if _TRUNK_ZERO.search(trimmed):
        return None
    number = trimmed.translate(_PHONE_SEPARATORS)
    return sha256_hex(number) if _E164.fullmatch(number) else None


def _hex_digest(raw: str) -> str | None:
    digest = raw.strip().lower()
    return digest if _HEX_DIGEST.fullmatch(digest) else None


def _gaid(raw: str) -> str | None:
    value = raw.strip().lower()
    return value if _UUID.fullmatch(value) and value != _ZERO_UUID else None


_NORMALISERS = {
    "email": _email,
    "phone": _phone,
    "gaid": _gaid,
    "email_sha256": _hex_digest,
    "phone_number_sha256": _hex_digest,
}


def normalized_identifier(identifier_type: str, raw: str) -> str | None:
    """``raw`` as it is sent under ``SENT_IDENTIFIER_TYPES[identifier_type]``.

    ``None`` when ``raw`` does not fit the type. Raises ``ValueError`` for an
    unknown ``identifier_type``.
    """
    normalise = _NORMALISERS.get(identifier_type)
    if normalise is None:
        raise ValueError(
            f"identifier_type must be one of {', '.join(IDENTIFIER_TYPES)}"
        )
    return normalise(raw)


__all__ = [
    "IDENTIFIER_TYPES",
    "SENT_IDENTIFIER_TYPES",
    "normalized_identifier",
    "sha256_hex",
    "without_identifiers",
]
