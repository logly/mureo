"""The Meta Graph API version is one constant, and nothing re-pins it (#770).

Before this, the version travelled as a literal in five places — the client's
``BASE_URL``, the account-listing base, the OAuth token URL, the OAuth dialog
URL and a docstring — and they drifted: the pin sat at v21.0 long after
Marketing API v21.0 expired (2025-09-09), which left Meta silently
auto-upgrading our ads calls to whatever the oldest live version happened to
be. A bump has to be a deliberate migration walked against Meta's changelog,
which is only possible if there is a single place to bump.

The source scan is the part that keeps it that way: a new literal
``https://graph.facebook.com/v26.0/...`` pasted into any module is exactly how
the drift started, and it reads as correct at review time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mureo
from mureo import auth, auth_setup
from mureo.meta_ads import accounts
from mureo.meta_ads._api_version import (
    GRAPH_API_BASE,
    META_GRAPH_API_VERSION,
    OAUTH_DIALOG_URL,
    OAUTH_TOKEN_URL,
)
from mureo.meta_ads.client import MetaAdsApiClient

#: A Graph API version is ``v<major>.0`` — Meta has never shipped a non-zero
#: minor. Anything else is a typo (``26.0``, ``v26``, ``v26.1``).
_VERSION_RE = re.compile(r"^v\d+\.0$")

#: The literal pin, in either host form Meta serves it on. ``(?=\d)`` is what
#: makes this a version and not a path segment starting with "v". Matched
#: against bytes so packaged assets (skills, web bundles) are scanned too,
#: whatever their encoding.
_LITERAL_PIN_RE = re.compile(rb"(?:graph\.)?facebook\.com/v(?=\d)")

#: The one module allowed to spell the version out.
_VERSION_MODULE = Path("meta_ads/_api_version.py")


@pytest.mark.unit
def test_version_constant_is_well_formed() -> None:
    """``META_GRAPH_API_VERSION`` is a Graph API version string."""
    assert _VERSION_RE.match(META_GRAPH_API_VERSION), META_GRAPH_API_VERSION


@pytest.mark.unit
def test_derived_urls_carry_the_version() -> None:
    """Every URL the constant derives is built from it, not beside it."""
    assert f"https://graph.facebook.com/{META_GRAPH_API_VERSION}" == GRAPH_API_BASE
    assert f"{GRAPH_API_BASE}/oauth/access_token" == OAUTH_TOKEN_URL
    assert (
        f"https://www.facebook.com/{META_GRAPH_API_VERSION}/dialog/oauth"
        == OAUTH_DIALOG_URL
    )


@pytest.mark.unit
def test_every_call_site_speaks_the_pinned_version() -> None:
    """The four call sites resolve to the constant, not to a copy of it."""
    call_sites = {
        "MetaAdsApiClient.BASE_URL": MetaAdsApiClient.BASE_URL,
        "accounts._META_GRAPH_API_BASE": accounts._META_GRAPH_API_BASE,
        "auth._META_GRAPH_TOKEN_URL": auth._META_GRAPH_TOKEN_URL,
        "auth_setup._META_AUTH_URL": auth_setup._META_AUTH_URL,
    }
    for name, url in call_sites.items():
        assert META_GRAPH_API_VERSION in url, f"{name} does not carry the pin: {url}"


@pytest.mark.unit
def test_version_is_exported_from_the_package() -> None:
    """``mureo.meta_ads`` re-exports the pin so callers need not reach in."""
    from mureo import meta_ads

    assert meta_ads.META_GRAPH_API_VERSION == META_GRAPH_API_VERSION
    assert "META_GRAPH_API_VERSION" in meta_ads.__all__


@pytest.mark.unit
def test_no_file_hardcodes_a_graph_api_version() -> None:
    """No file under ``mureo/`` spells a version into a facebook.com URL.

    ``meta_ads/_api_version.py`` is the single exception — it is the file that
    defines the pin. Packaged data (skills, web assets) is scanned as well:
    a version baked into a skill misleads the agent the same way a version
    baked into a module misleads the client.
    """
    package_root = Path(mureo.__file__).parent
    offenders = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(package_root)
        if relative == _VERSION_MODULE:
            continue
        if _LITERAL_PIN_RE.search(path.read_bytes()):
            offenders.append(str(relative))
    assert not offenders, (
        "hardcoded Graph API version pin(s) found — import from "
        f"mureo.meta_ads._api_version instead: {offenders}"
    )
