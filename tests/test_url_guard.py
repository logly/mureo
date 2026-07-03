"""Tests for the shared SSRF URL guard (``mureo.core.url_guard``) and its use
in the Meta ad-image uploader.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from mureo.core.url_guard import UnsafeUrlError, validate_public_url


@pytest.mark.unit
class TestValidatePublicUrl:
    def test_allows_public_https(self) -> None:
        # Should not raise for a normal public URL (DNS resolves to a public IP).
        validate_public_url("https://example.com/image.png")

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://localhost:8080/",
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://metadata.google.internal/",
            "http://10.0.0.5/internal",  # private range (literal IP)
            "http://192.168.1.1/",
        ],
    )
    def test_blocks_internal_targets(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError):
            validate_public_url(url)

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "gopher://x"])
    def test_blocks_non_http_schemes(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError):
            validate_public_url(url)

    def test_blocks_dns_name_resolving_to_private(self) -> None:
        # A public-looking hostname that resolves to a private IP must be rejected.
        with patch(
            "mureo.core.url_guard.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.1.2.3", 0))],
        ), pytest.raises(UnsafeUrlError):
            validate_public_url("https://sneaky.example.com/x")


@pytest.mark.unit
class TestUploadAdImageSsrf:
    @pytest.fixture()
    def meta_client(self) -> Any:
        from mureo.meta_ads.client import MetaAdsApiClient

        return MetaAdsApiClient(access_token="t", ad_account_id="act_1")

    @pytest.mark.asyncio()
    async def test_rejects_metadata_url_without_fetching(
        self, meta_client: Any
    ) -> None:
        # The uploader must refuse an internal URL BEFORE any HTTP client is
        # constructed, so patch AsyncClient to blow up if it is ever used.
        with patch(
            "mureo.meta_ads._creatives.httpx.AsyncClient",
            side_effect=AssertionError("must not fetch an unsafe URL"),
        ):
            result = await meta_client.upload_ad_image(
                "http://169.254.169.254/latest/meta-data/iam/"
            )
        assert "error" in result
        assert "Refusing to fetch" in result["error"]
