"""Unit tests for ``mureo.providers.coexistence``.

Pins the user-facing warning text emitted when an official provider for a
platform that mureo also serves natively is added. Phase 1 = warning only;
the per-platform auto-disable is a documented follow-up. See planner
HANDOFF ``feat-providers-cli-phase1.md``.
"""

from __future__ import annotations

from typing import Any

import pytest


def _synthetic_spec(
    coexists_with_mureo_platform: str | None,
    spec_id: str = "synthetic",
) -> Any:
    """Build a real ``ProviderSpec`` with a configurable coexistence field."""
    from mureo.providers.catalog import ProviderSpec

    return ProviderSpec(
        id=spec_id,
        display_name=spec_id,
        install_kind="pipx",
        install_argv=("pipx", "run", "x"),
        mcp_server_config={"command": "pipx", "args": ["run", "x"]},
        required_env=(),
        notes="",
        coexists_with_mureo_platform=coexists_with_mureo_platform,  # type: ignore[arg-type]
    )


@pytest.mark.unit
def test_warning_emitted_for_google_ads_official() -> None:
    """Google Ads warning mentions both the platform and mureo's native server."""
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("google-ads-official")
    msg = coexistence_warning(spec)

    assert isinstance(msg, str) and msg.strip() != ""
    assert "google" in msg.lower() and "ads" in msg.lower()
    assert "mureo" in msg.lower()


@pytest.mark.unit
def test_warning_emitted_for_meta_ads_official() -> None:
    """Meta Ads warning mentions the platform."""
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("meta-ads-official")
    msg = coexistence_warning(spec)

    assert isinstance(msg, str) and msg.strip() != ""
    assert "meta" in msg.lower() and "ads" in msg.lower()


@pytest.mark.unit
def test_warning_emitted_for_ga4_official() -> None:
    """GA4 warning mentions the platform."""
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("ga4-official")
    msg = coexistence_warning(spec)

    assert isinstance(msg, str) and msg.strip() != ""
    assert "ga4" in msg.lower()


@pytest.mark.unit
def test_no_warning_when_coexists_field_is_none() -> None:
    """A spec with no coexistence overlap returns ``None``."""
    from mureo.providers.coexistence import coexistence_warning

    spec = _synthetic_spec(coexists_with_mureo_platform=None)
    assert coexistence_warning(spec) is None


@pytest.mark.unit
def test_warning_mentions_followup_disable() -> None:
    """Warning text flags that automatic disable is a documented follow-up.

    Phase 1 is warning-only; users currently have to disable mureo's native
    server manually. The string must say so explicitly.
    """
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    msg = coexistence_warning(get_provider("google-ads-official"))
    assert msg is not None
    lowered = msg.lower()
    assert (
        "follow-up" in lowered
        or "follow up" in lowered
        or "future" in lowered
        or "later" in lowered
        or "manually" in lowered
    )


# ---------------------------------------------------------------------------
# Disable-mureo extension (added 2026-05-12 per Founder Q1/Q2)
# ---------------------------------------------------------------------------
#
# After the disable-mureo extension lands, the warning helper gains an
# ``mureo_block_present: bool = True`` parameter. The default value matches
# the common case (the user ran ``mureo setup …`` before adding an official
# provider). When the mureo block is absent, the message degrades to point
# the user at ``mureo setup claude-code``.


@pytest.mark.unit
def test_warning_text_when_mureo_block_present_includes_auto_disabled() -> None:
    """Auto-disable path: message confirms the action + names the env var."""
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("google-ads-official")
    msg = coexistence_warning(spec, mureo_block_present=True)

    assert isinstance(msg, str) and msg.strip() != ""
    lowered = msg.lower()
    assert "auto-disabled" in lowered or "auto disabled" in lowered
    assert "MUREO_DISABLE_GOOGLE_ADS" in msg


@pytest.mark.unit
def test_warning_text_when_mureo_block_absent_is_degraded() -> None:
    """Degraded path: message points the user at ``mureo setup claude-code``."""
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("google-ads-official")
    msg = coexistence_warning(spec, mureo_block_present=False)

    assert isinstance(msg, str) and msg.strip() != ""
    lowered = msg.lower()
    # Mentions that nothing was auto-disabled / mureo block not registered.
    assert (
        "not registered" in lowered
        or "no mureo" in lowered
        or "nothing to auto-disable" in lowered
        or "nothing was auto-disabled" in lowered
    )
    # Points users at the setup remediation path.
    assert "mureo setup claude-code" in lowered or "setup claude-code" in lowered


@pytest.mark.unit
def test_warning_signature_default_preserves_backwards_compat() -> None:
    """Calling without ``mureo_block_present`` defaults to the auto-disabled wording.

    The default ``True`` matches the common case (the user previously ran
    ``mureo setup …``). Locks the default in so callers that don't pass the
    kwarg get the friendly confirmation, not the degraded message.
    """
    from mureo.providers.catalog import get_provider
    from mureo.providers.coexistence import coexistence_warning

    spec = get_provider("google-ads-official")
    msg = coexistence_warning(spec)  # no kwarg — default applies

    assert isinstance(msg, str) and msg.strip() != ""
    lowered = msg.lower()
    assert "auto-disabled" in lowered or "auto disabled" in lowered
