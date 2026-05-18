"""Amazon endpoint + auth-header resolution (TDD, #113 Phase 1).

Pure / no network — region picks the URL, account_mode picks the
Dynamic vs Fixed header set. Source of truth = Phase 0 verified facts
(advertising-ai[.|-eu|-fe].amazon.com/mcp).
"""

from __future__ import annotations

import pytest

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.auth import AmazonAdsCredentials


@pytest.mark.unit
class TestEndpointUrl:
    def test_region_map(self) -> None:
        assert endpoint_url("na") == "https://advertising-ai.amazon.com/mcp"
        assert endpoint_url("eu") == "https://advertising-ai-eu.amazon.com/mcp"
        assert endpoint_url("fe") == "https://advertising-ai-fe.amazon.com/mcp"

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            endpoint_url("antarctica")


@pytest.mark.unit
class TestRequestHeaders:
    def _c(self, **kw) -> AmazonAdsCredentials:
        base = {"client_id": "cid", "access_token": "Atza|tok"}
        base.update(kw)
        return AmazonAdsCredentials(**base)

    def test_dynamic_minimal_headers(self) -> None:
        h = request_headers(self._c())
        assert h["Authorization"] == "Bearer Atza|tok"
        assert h["Amazon-Ads-ClientId"] == "cid"
        assert "application/json" in h["Accept"]
        # Dynamic ⇒ no FIXED / account headers
        assert "Amazon-Ads-AI-Account-Selection-Mode" not in h
        assert "Amazon-Advertising-API-Scope" not in h

    def test_fixed_mode_emits_scope_and_marker(self) -> None:
        h = request_headers(self._c(account_mode="fixed", profile_id="111"))
        assert h["Amazon-Ads-AI-Account-Selection-Mode"] == "FIXED"
        assert h["Amazon-Advertising-API-Scope"] == "111"

    def test_fixed_mode_account_and_manager_ids(self) -> None:
        h = request_headers(
            self._c(
                account_mode="fixed",
                account_id="222",
                manager_account_id="333",
            )
        )
        assert h["Amazon-Ads-AccountID"] == "222"
        assert h["Amazon-Ads-Manager-AccountID"] == "333"
        assert h["Amazon-Ads-AI-Account-Selection-Mode"] == "FIXED"

    def test_fixed_without_any_id_does_not_emit_broken_fixed(self) -> None:
        # Fixed mode requires >=1 account id; with none, do NOT emit the
        # FIXED marker (would 4xx) — degrade to the Dynamic header set.
        h = request_headers(self._c(account_mode="fixed"))
        assert "Amazon-Ads-AI-Account-Selection-Mode" not in h
        assert h["Authorization"] == "Bearer Atza|tok"

    def test_access_token_not_double_prefixed(self) -> None:
        # token already stored without "Bearer "; we add exactly one.
        h = request_headers(self._c(access_token="Atza|abc"))
        assert h["Authorization"] == "Bearer Atza|abc"
