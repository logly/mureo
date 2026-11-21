"""Time zone names a platform reports, resolved without raising.

An ad account's time zone arrives as text in an API answer. The platform
packages that place account-local times (a reporting period, a change time)
share this one reading of it, so "a name ``zoneinfo`` cannot use" means the
same thing everywhere.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["zone_or_none"]


def zone_or_none(value: object) -> ZoneInfo | None:
    """``value`` as an IANA zone, or ``None`` when it names no usable zone.

    ``ZoneInfo`` raises :class:`~zoneinfo.ZoneInfoNotFoundError` for a key it
    has no data for and :class:`ValueError` for one that is not a plain key
    (an absolute path, a ``..`` segment). Where the zone data comes from the
    ``tzdata`` package rather than the system (always on Windows), a key that
    names a directory of the database (``America``) or is too long to be a
    file name surfaces as the :class:`OSError` of the failed open instead. A
    name taken from an API answer can therefore do no more than fail to
    resolve. The caller decides what an unknown zone means for it.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
