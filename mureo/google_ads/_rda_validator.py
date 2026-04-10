"""RDA (Responsive Display Ad) input validation.

Validates the inputs required for creating a Responsive Display Ad
before issuing the API call. Unlike RSA validation, this module does
NOT auto-correct text — it only enforces hard limits and required
fields. Auto-correction (NFKC, emoji removal, etc.) can be added
later if needed; for now we keep the surface area small and
predictable.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass

from mureo.google_ads._rsa_validator import display_width

logger = logging.getLogger(__name__)

# === Google Ads RDA limits ===
# Source: https://developers.google.com/google-ads/api/reference/rpc/latest/ResponsiveDisplayAdInfo
HEADLINE_MAX_WIDTH = 30
LONG_HEADLINE_MAX_WIDTH = 90
DESCRIPTION_MAX_WIDTH = 90
BUSINESS_NAME_MAX_WIDTH = 25

MIN_HEADLINES = 1
MAX_HEADLINES = 5
MIN_DESCRIPTIONS = 1
MAX_DESCRIPTIONS = 5

MIN_MARKETING_IMAGES = 1
MAX_MARKETING_IMAGES = 15
MIN_SQUARE_IMAGES = 1
MAX_SQUARE_IMAGES = 15
MIN_LOGO_IMAGES = 0
MAX_LOGO_IMAGES = 5

# Google Ads enforces a 2048-byte limit on final URL strings.
MAX_FINAL_URL_LENGTH = 2048

# Number of leading characters to keep when echoing user-supplied text
# back into validation error messages. Avoids dumping arbitrarily long
# strings into logs.
_ERROR_TEXT_PREVIEW = 30


def _preview(text: str) -> str:
    """Return a short, log-safe preview of user-supplied text."""
    if len(text) <= _ERROR_TEXT_PREVIEW:
        return text
    return text[:_ERROR_TEXT_PREVIEW] + "..."


@dataclass(frozen=True)
class RDAValidationResult:
    """Validated and normalized inputs for a Responsive Display Ad.

    The `*_asset_resource_names` fields hold full Google Ads resource
    names like "customers/123/assets/456", not bare numeric IDs. They
    are named for clarity even though older releases of mureo had
    inconsistent naming conventions in this area.
    """

    headlines: tuple[str, ...]
    long_headline: str
    descriptions: tuple[str, ...]
    business_name: str
    marketing_image_asset_resource_names: tuple[str, ...]
    square_marketing_image_asset_resource_names: tuple[str, ...]
    logo_image_asset_resource_names: tuple[str, ...]
    final_url: str


def _is_valid_url(url: str) -> bool:
    """Basic URL structure check (scheme + hostname presence)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    # Reject URLs with whitespace or control characters anywhere — Google
    # rejects these and they are common copy/paste mistakes.
    return not any(ch.isspace() or ord(ch) < 0x20 for ch in url)


def validate_rda_inputs(
    *,
    headlines: list[str],
    long_headline: str,
    descriptions: list[str],
    business_name: str,
    marketing_image_asset_resource_names: list[str],
    square_marketing_image_asset_resource_names: list[str],
    logo_image_asset_resource_names: list[str] | None,
    final_url: str,
) -> RDAValidationResult:
    """Validate RDA inputs and return a normalized result.

    Truncates headline/description lists when they exceed the maximum
    allowed count, logging an INFO message when truncation happens.
    Raises ValueError when a hard requirement is missing (empty required
    fields, width overflow on individual texts, image count out of
    range, malformed URL).
    """
    # Headlines: at least MIN_HEADLINES, at most MAX_HEADLINES
    if len(headlines) < MIN_HEADLINES:
        raise ValueError(
            f"At least {MIN_HEADLINES} headline is required (got {len(headlines)})"
        )
    if len(headlines) > MAX_HEADLINES:
        logger.info("Truncating RDA headlines: %d -> %d", len(headlines), MAX_HEADLINES)
    truncated_headlines = headlines[:MAX_HEADLINES]
    for h in truncated_headlines:
        width = display_width(h)
        if width > HEADLINE_MAX_WIDTH:
            raise ValueError(
                f"Headline '{_preview(h)}' exceeds {HEADLINE_MAX_WIDTH} "
                f"display width (got {width})"
            )

    # Long headline: required, at most LONG_HEADLINE_MAX_WIDTH
    if not long_headline:
        raise ValueError("long_headline is required")
    long_headline_width = display_width(long_headline)
    if long_headline_width > LONG_HEADLINE_MAX_WIDTH:
        raise ValueError(
            f"long_headline exceeds {LONG_HEADLINE_MAX_WIDTH} display width "
            f"(got {long_headline_width})"
        )

    # Descriptions: at least MIN_DESCRIPTIONS, at most MAX_DESCRIPTIONS
    if len(descriptions) < MIN_DESCRIPTIONS:
        raise ValueError(
            f"At least {MIN_DESCRIPTIONS} description is required "
            f"(got {len(descriptions)})"
        )
    if len(descriptions) > MAX_DESCRIPTIONS:
        logger.info(
            "Truncating RDA descriptions: %d -> %d",
            len(descriptions),
            MAX_DESCRIPTIONS,
        )
    truncated_descriptions = descriptions[:MAX_DESCRIPTIONS]
    for d in truncated_descriptions:
        width = display_width(d)
        if width > DESCRIPTION_MAX_WIDTH:
            raise ValueError(
                f"Description '{_preview(d)}' exceeds {DESCRIPTION_MAX_WIDTH} "
                f"display width (got {width})"
            )

    # Business name: required, at most BUSINESS_NAME_MAX_WIDTH
    if not business_name:
        raise ValueError("business_name is required")
    business_name_width = display_width(business_name)
    if business_name_width > BUSINESS_NAME_MAX_WIDTH:
        raise ValueError(
            f"business_name exceeds {BUSINESS_NAME_MAX_WIDTH} display width "
            f"(got {business_name_width})"
        )

    # Marketing images (1.91:1): MIN_MARKETING_IMAGES..MAX_MARKETING_IMAGES
    if len(marketing_image_asset_resource_names) < MIN_MARKETING_IMAGES:
        raise ValueError(
            f"At least {MIN_MARKETING_IMAGES} marketing image is required "
            f"(got {len(marketing_image_asset_resource_names)})"
        )
    if len(marketing_image_asset_resource_names) > MAX_MARKETING_IMAGES:
        raise ValueError(
            f"marketing images exceed {MAX_MARKETING_IMAGES} "
            f"(got {len(marketing_image_asset_resource_names)})"
        )

    # Square marketing images (1:1): MIN_SQUARE_IMAGES..MAX_SQUARE_IMAGES
    if len(square_marketing_image_asset_resource_names) < MIN_SQUARE_IMAGES:
        raise ValueError(
            f"At least {MIN_SQUARE_IMAGES} square marketing image is required "
            f"(got {len(square_marketing_image_asset_resource_names)})"
        )
    if len(square_marketing_image_asset_resource_names) > MAX_SQUARE_IMAGES:
        raise ValueError(
            f"square marketing images exceed {MAX_SQUARE_IMAGES} "
            f"(got {len(square_marketing_image_asset_resource_names)})"
        )

    # Logo images (optional): MIN_LOGO_IMAGES..MAX_LOGO_IMAGES
    logos = (
        list(logo_image_asset_resource_names) if logo_image_asset_resource_names else []
    )
    if len(logos) < MIN_LOGO_IMAGES:
        # Defensive: MIN_LOGO_IMAGES is 0, so this branch is currently
        # unreachable. Kept for symmetry with the other image fields.
        raise ValueError(  # pragma: no cover
            f"At least {MIN_LOGO_IMAGES} logo image is required (got {len(logos)})"
        )
    if len(logos) > MAX_LOGO_IMAGES:
        raise ValueError(f"logo images exceed {MAX_LOGO_IMAGES} (got {len(logos)})")

    # Final URL
    if not final_url:
        raise ValueError("final_url is required")
    if len(final_url) > MAX_FINAL_URL_LENGTH:
        raise ValueError(
            f"final_url exceeds {MAX_FINAL_URL_LENGTH} characters "
            f"(got {len(final_url)})"
        )
    if not _is_valid_url(final_url):
        raise ValueError(f"final_url is invalid: '{_preview(final_url)}'")

    return RDAValidationResult(
        headlines=tuple(truncated_headlines),
        long_headline=long_headline,
        descriptions=tuple(truncated_descriptions),
        business_name=business_name,
        marketing_image_asset_resource_names=tuple(
            marketing_image_asset_resource_names
        ),
        square_marketing_image_asset_resource_names=tuple(
            square_marketing_image_asset_resource_names
        ),
        logo_image_asset_resource_names=tuple(logos),
        final_url=final_url,
    )
