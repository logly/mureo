"""Unit tests for ``mureo.providers.catalog``.

Pins the integrity of the Phase 1 catalog (Google Ads / Meta Ads / GA4 official
MCP servers) and ``ProviderSpec`` immutability. See planner HANDOFF
``feat-providers-cli-phase1.md`` for the full acceptance criteria.

This module is part of the RED phase: every test must fail with
``ImportError`` / ``AttributeError`` until ``mureo.providers.catalog`` is
implemented by the test-implementer.
"""

from __future__ import annotations

import dataclasses

import pytest


@pytest.mark.unit
def test_catalog_has_phase1_providers() -> None:
    """``CATALOG`` contains exactly the three Phase 1 ids.

    Search Console is intentionally absent (mureo's native MCP remains
    canonical for it). No Cursor- or Codex-only entries in Phase 1.
    """
    from mureo.providers.catalog import CATALOG

    ids = {spec.id for spec in CATALOG}
    assert ids == {"google-ads-official", "meta-ads-official", "ga4-official"}


@pytest.mark.unit
def test_catalog_ids_unique() -> None:
    """Every ``spec.id`` is unique across ``CATALOG``."""
    from mureo.providers.catalog import CATALOG

    ids = [spec.id for spec in CATALOG]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_catalog_specs_are_frozen() -> None:
    """``ProviderSpec`` is a frozen dataclass; mutation raises."""
    from mureo.providers.catalog import CATALOG

    spec = CATALOG[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.id = "tampered"  # type: ignore[misc]


@pytest.mark.unit
def test_install_argv_is_sequence_form() -> None:
    """Every spec uses tuple argv (no shell strings, no in-place mutation).

    The argv must be a tuple rather than a list so the catalog is immutable
    by interface — ``frozen=True`` on the dataclass blocks attribute
    reassignment but not in-place mutation of a contained list.

    Hosted entries (``install_kind="hosted_http"``) use an empty tuple
    because no subprocess install is invoked. Non-hosted entries must be
    non-empty (the installer would otherwise raise ``ValueError``).
    """
    from mureo.providers.catalog import CATALOG

    for spec in CATALOG:
        assert isinstance(spec.install_argv, tuple), spec.id
        for token in spec.install_argv:
            assert isinstance(token, str), spec.id
        if spec.install_kind != "hosted_http":
            assert len(spec.install_argv) >= 1, spec.id


@pytest.mark.unit
def test_install_argv_executable_in_allowlist() -> None:
    """First argv element must be in the ``{pipx, npm}`` allow-list.

    Defense against catalog tampering allowing arbitrary commands. Hosted
    entries (``install_kind="hosted_http"``) are exempt because they
    invoke no subprocess — their ``install_argv`` is empty by design.
    """
    from mureo.providers.catalog import CATALOG

    allowed = {"pipx", "npm"}
    for spec in CATALOG:
        if spec.install_kind == "hosted_http":
            # Empty argv is correct for hosted entries; allow-list does not
            # apply (no executable is ever invoked).
            assert spec.install_argv == (), spec.id
            continue
        assert spec.install_argv[0] in allowed, (
            f"{spec.id} install_argv[0]={spec.install_argv[0]!r} " f"not in {allowed}"
        )


@pytest.mark.unit
def test_get_provider_by_id() -> None:
    """``get_provider`` returns matching spec; unknown id raises ``KeyError``."""
    from mureo.providers.catalog import get_provider

    spec = get_provider("google-ads-official")
    assert spec.id == "google-ads-official"

    with pytest.raises(KeyError):
        get_provider("does-not-exist")


@pytest.mark.unit
def test_required_env_documents_credentials() -> None:
    """Required env vars are documented for every Phase 1 provider.

    Hosted entries (Meta Ads, ``install_kind="hosted_http"``) authenticate
    via interactive browser OAuth on first connect, so they correctly
    declare ``required_env=()`` — no env vars to pre-populate.
    """
    from mureo.providers.catalog import get_provider

    google = get_provider("google-ads-official")
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in google.required_env

    meta = get_provider("meta-ads-official")
    # Meta uses interactive OAuth — no pre-populated env vars expected.
    assert meta.required_env == ()

    ga4 = get_provider("ga4-official")
    assert len(ga4.required_env) >= 1


@pytest.mark.unit
def test_coexists_with_mureo_platform_correctly_set() -> None:
    """Every Phase 1 provider declares the mureo platform it overlaps with."""
    from mureo.providers.catalog import get_provider

    google = get_provider("google-ads-official")
    assert google.coexists_with_mureo_platform == "google_ads"

    meta = get_provider("meta-ads-official")
    assert meta.coexists_with_mureo_platform == "meta_ads"

    ga4 = get_provider("ga4-official")
    assert ga4.coexists_with_mureo_platform == "ga4"
