"""Meta Ads Conversions API hashing utilities.

Meta CAPI requires PII fields such as em(email), ph(phone), fn(first name),
ln(last name), etc. to be SHA-256 hashed before sending.
"""

from __future__ import annotations

import hashlib
import re

# PII fields subject to hashing
# em, ph use specific logic (email normalization, phone digit extraction)
# Others are normalized with lowercase + strip
_PII_FIELDS_LOWERCASE: frozenset[str] = frozenset(
    {"em", "ph", "fn", "ln", "ct", "st", "zp", "country", "db", "ge"}
)

# Non-PII fields (not hashed)
_NON_PII_FIELDS: frozenset[str] = frozenset(
    {
        "client_ip_address",
        "client_user_agent",
        "fbc",
        "fbp",
        "external_id",
        "subscription_id",
        "lead_id",
    }
)

# SHA-256 hash value regex (64-character hex string)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _is_already_hashed(value: str) -> bool:
    """Determine whether the value is already SHA-256 hashed."""
    return bool(_SHA256_PATTERN.match(value))


def _sha256(value: str) -> str:
    """Hash a string with SHA-256."""
    return hashlib.sha256(value.encode()).hexdigest()


def hash_email(email: str) -> str:
    """Hash an email address with SHA-256.

    Meta API requirements:
    - Strip leading/trailing whitespace
    - Convert to lowercase
    - Hash with SHA-256

    Args:
        email: Email address (plaintext)

    Returns:
        SHA-256 hash value (64-character hex string)
    """
    normalized = email.strip().lower()
    return _sha256(normalized)


def hash_phone(phone: str) -> str:
    """Hash a phone number with SHA-256.

    Meta API requirements:
    - Remove non-digit characters (hyphens, spaces, parentheses, +)
    - Hash with SHA-256

    Args:
        phone: Phone number (plaintext, may include country code)

    Returns:
        SHA-256 hash value (64-character hex string)
    """
    digits_only = re.sub(r"[^\d]", "", phone)
    return _sha256(digits_only)


def _hash_pii_value(key: str, value: str) -> str:
    """Hash a PII field value.

    em uses hash_email, ph uses hash_phone, others use lowercase + SHA-256.
    Returns as-is if already hashed.
    """
    if _is_already_hashed(value):
        return value

    if key == "em":
        return hash_email(value)
    if key == "ph":
        return hash_phone(value)

    # fn, ln, ct, st, zp, country, db, ge: lowercase + strip + hash
    return _sha256(value.strip().lower())


def normalize_user_data(user_data: dict[str, object]) -> dict[str, object]:
    """Auto-hash PII fields in user_data.

    SHA-256 hashes PII fields in the user_data dict for sending to Meta
    Conversions API. Skips already-hashed values.

    Args:
        user_data: user_data dictionary

    Returns:
        New dictionary with PII fields hashed (original dict is not modified)
    """
    result: dict[str, object] = {}

    for key, value in user_data.items():
        if key in _NON_PII_FIELDS or key not in _PII_FIELDS_LOWERCASE:
            result[key] = value
            continue

        if isinstance(value, list):
            result[key] = [
                _hash_pii_value(key, v) if isinstance(v, str) else v for v in value
            ]
        elif isinstance(value, str):
            result[key] = _hash_pii_value(key, value)
        else:
            result[key] = value

    return result
