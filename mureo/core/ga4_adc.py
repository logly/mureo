"""The GA4 credential file mureo derives from the Google authorization (#938).

The official GA4 MCP (``ga4-official``) authenticates through
``google.auth.default()``: it reads the file named by
``GOOGLE_APPLICATION_CREDENTIALS`` and never sees mureo's credential store.
When the Google OAuth flow was granted ``analytics.readonly``, the same
client id, client secret and refresh token are a complete Application
Default Credentials file of type ``authorized_user``, so mureo writes one
beside the credential store, named after it (``credentials.json`` ->
``credentials-ga4-adc.json``, so two stores in one directory never share
it), and points the ``ga4`` section at it. The operator then has nothing
more to enter for GA4.

The file duplicates the Google refresh token on purpose, because the
official MCP cannot read the credential store. It is therefore re-written
on every Google save (a re-authorization rotates the token) and on every
dashboard edit of a Google value, and removed together with the section
that points at it. A managed file must never outlive the authorization it
was derived from: when a new Google grant no longer carries GA4 read access,
or its client id carries no Cloud project number, the old copy would keep
answering with a token that no longer matches the ``google_ads`` section, so
the section and the file are removed instead.

``quota_project_id`` is set to the OAuth client's Cloud project number:
Analytics API calls made with user credentials are billed to, and must be
enabled on, a quota project, and the OAuth client's own project is that
project. Its number is embedded in the client id. A project id already
stored in a managed section is kept: the operator may have set a quota
project of their own.

A ``ga4`` section that points at any other file (a service-account key, a
gcloud file, an external account configuration) is never overwritten: only
an absent section, one without a credential file path, or one already
pointing at the managed file is written.

Depends on nothing above :mod:`mureo.core` (``mureo.core`` must not import
``mureo.auth``), so the values arrive as plain strings.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

from mureo.core.atomic_json import atomic_write_json, load_existing_json
from mureo.core.google_scopes import ANALYTICS_READONLY_SCOPE

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "ADC_SUFFIX",
    "ANALYTICS_READONLY_SCOPE",
    "GA4_PATH_FIELD",
    "GA4_PROJECT_FIELD",
    "GA4_ADC_GOOGLE_FIELDS",
    "GA4_SECTION",
    "drop_managed_ga4_section",
    "ga4_section_usable",
    "is_managed_ga4_section",
    "managed_adc_path",
    "oauth_client_project_number",
    "refresh_managed_ga4_adc",
    "store_has_managed_ga4",
    "sync_ga4_adc_from_google",
    "unlink_managed_ga4_adc",
]

logger = logging.getLogger(__name__)

GA4_SECTION = "ga4"
#: Historical name: the field holds the path of ANY ADC credential file.
GA4_PATH_FIELD = "service_account_path"
GA4_PROJECT_FIELD = "project_id"
#: Appended to the credential store's stem: ``credentials.json`` ->
#: ``credentials-ga4-adc.json``, beside the store.
ADC_SUFFIX = "-ga4-adc.json"

#: The ``google_ads`` values the derived ADC file copies, so an edit to any
#: of them must re-write the file.
GA4_ADC_GOOGLE_FIELDS = ("client_id", "client_secret", "refresh_token")

_GOOGLE_SECTION = "google_ads"
_CLIENT_ID_PATTERN = re.compile(r"(\d+)-[a-z0-9]+\.apps\.googleusercontent\.com")


def managed_adc_path(credentials_path: Path) -> Path:
    """The authorized_user ADC mureo writes beside ``credentials_path``."""
    return credentials_path.with_name(credentials_path.stem + ADC_SUFFIX)


def oauth_client_project_number(client_id: str) -> str | None:
    """The Cloud project number embedded in a Google OAuth client id
    (``<number>-<hash>.apps.googleusercontent.com``), or None."""
    match = _CLIENT_ID_PATTERN.fullmatch(client_id.strip())
    return match.group(1) if match else None


def ga4_section_usable(section: object) -> bool:
    """Both values the official MCP needs are set (a half-written section
    is possible: the configure UI saves them one env var at a time)."""
    if not isinstance(section, dict):
        return False
    return bool(section.get(GA4_PATH_FIELD) and section.get(GA4_PROJECT_FIELD))


def is_managed_ga4_section(section: object, credentials_path: Path) -> bool:
    """True when ``section`` is a dict whose path field names the managed
    ADC file (``~`` and ``.`` segments in a hand-typed path still match)."""
    if not isinstance(section, dict):
        return False
    value = section.get(GA4_PATH_FIELD)
    if not value:
        return False
    stored = os.path.normpath(os.path.expanduser(str(value)))
    return stored == os.path.normpath(str(managed_adc_path(credentials_path)))


def store_has_managed_ga4(credentials_path: Path) -> bool:
    """True when the store at ``credentials_path`` has a ``ga4`` section
    pointing at the managed ADC (False for a missing store)."""
    section = load_existing_json(credentials_path).get(GA4_SECTION)
    return is_managed_ga4_section(section, credentials_path)


def _skip_reason(
    existing: dict[str, Any],
    granted_scopes: Sequence[str],
    project_number: str | None,
    credentials_path: Path,
) -> str | None:
    """Why the managed ADC must not be written, or None when it may be."""
    if ANALYTICS_READONLY_SCOPE not in granted_scopes:
        # A token without the scope would make ga4-official fail at call
        # time with an insufficient-scope error instead of asking for a file.
        return "analytics.readonly was not granted"
    if project_number is None:
        return "the OAuth client id carries no Cloud project number"
    section = existing.get(GA4_SECTION)
    # A path-only section is the operator's too: its project id may simply
    # not be saved yet.
    if (
        isinstance(section, dict)
        and section.get(GA4_PATH_FIELD)
        and not is_managed_ga4_section(section, credentials_path)
    ):
        return "the ga4 section points at the operator's own credential file"
    return None


def _adc_payload(
    client_id: str, client_secret: str, refresh_token: str, quota_project_id: str
) -> dict[str, str]:
    """The ``authorized_user`` ADC document ``google.auth.default()`` reads."""
    return {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "quota_project_id": quota_project_id,
    }


def _write_adc(adc_path: Path, payload: dict[str, str]) -> bool:
    """Write the ADC file; an OSError is logged (type name only)."""
    try:
        atomic_write_json(payload, adc_path)
    except OSError as exc:
        logger.warning(
            "GA4 credential file not written (%s); enter the GA4 values by hand",
            type(exc).__name__,
        )
        return False
    return True


def _drop_stale_managed(
    existing: dict[str, Any], credentials_path: Path, reason: str
) -> None:
    """Remove a managed ``ga4`` section and its file once the authorization
    it was derived from no longer backs it. Mutates ``existing``."""
    if drop_managed_ga4_section(existing, credentials_path):
        unlink_managed_ga4_adc(credentials_path)
        logger.info("GA4 credential file removed: %s", reason)


def sync_ga4_adc_from_google(
    existing: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    granted_scopes: Sequence[str],
    credentials_path: Path,
) -> bool:
    """Write the managed ADC and point the ``ga4`` section at it.

    Mutates ``existing`` in place (the same contract as the other section
    merges of a credentials save); returns True when written, False when
    skipped or when the file could not be written (the reason is logged,
    never the values). A skip also removes a managed section and its file,
    which the new grant no longer backs. Best-effort on purpose: the file
    is derived from the Google section, so a failed write must not lose the
    authorization the caller is about to save.
    """
    project_number = oauth_client_project_number(client_id)
    reason = _skip_reason(existing, granted_scopes, project_number, credentials_path)
    if reason is not None or project_number is None:
        logger.info("GA4 credential file not written: %s", reason)
        _drop_stale_managed(existing, credentials_path, str(reason))
        return False
    prior = existing.get(GA4_SECTION)
    prior_section: dict[str, Any] = prior if isinstance(prior, dict) else {}
    managed = is_managed_ga4_section(prior_section, credentials_path)
    project = (managed and prior_section.get(GA4_PROJECT_FIELD)) or project_number
    adc_path = managed_adc_path(credentials_path)
    payload = _adc_payload(client_id, client_secret, refresh_token, project)
    if not _write_adc(adc_path, payload):
        return False
    existing[GA4_SECTION] = {
        **prior_section,
        GA4_PATH_FIELD: str(adc_path),
        GA4_PROJECT_FIELD: project,
    }
    logger.info("GA4 credential file written from the Google authorization")
    return True


def refresh_managed_ga4_adc(existing: dict[str, Any], credentials_path: Path) -> bool:
    """Re-write the managed ADC from the ``google_ads`` section when the
    ``ga4`` section points at it (the dashboard edited a Google value, so
    the copy the official MCP reads must follow). Returns True when written;
    False when the section is not managed, a Google value or the project id
    is missing, or the write failed (logged, type name only)."""
    section = existing.get(GA4_SECTION)
    if not isinstance(section, dict) or not is_managed_ga4_section(
        section, credentials_path
    ):
        return False
    google = existing.get(_GOOGLE_SECTION)
    values = [
        google.get(field) if isinstance(google, dict) else None
        for field in GA4_ADC_GOOGLE_FIELDS
    ]
    project = section.get(GA4_PROJECT_FIELD)
    if not all(values) or not project:
        logger.info("GA4 credential file not refreshed: a stored value is missing")
        return False
    client_id, client_secret, refresh_token = (str(value) for value in values)
    payload = _adc_payload(client_id, client_secret, refresh_token, str(project))
    return _write_adc(managed_adc_path(credentials_path), payload)


def drop_managed_ga4_section(existing: dict[str, Any], credentials_path: Path) -> bool:
    """Pop a ``ga4`` section that points at the managed ADC. Mutates ``existing``."""
    if not is_managed_ga4_section(existing.get(GA4_SECTION), credentials_path):
        return False
    existing.pop(GA4_SECTION, None)
    return True


def unlink_managed_ga4_adc(credentials_path: Path) -> bool:
    """Delete the managed ADC file. Returns True when a file was removed;
    an OSError is logged (type name only) and returns False."""
    try:
        managed_adc_path(credentials_path).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("GA4 credential file not removed (%s)", type(exc).__name__)
        return False
    return True
