"""Tests for the RDA (Responsive Display Ad) validator.

Exercises the pure validation logic in _rda_validator.py.
Runs without a database or external API.
"""

from __future__ import annotations

import logging

import pytest

from mureo.google_ads._rda_validator import (
    BUSINESS_NAME_MAX_WIDTH,
    DESCRIPTION_MAX_WIDTH,
    HEADLINE_MAX_WIDTH,
    LONG_HEADLINE_MAX_WIDTH,
    MAX_DESCRIPTIONS,
    MAX_FINAL_URL_LENGTH,
    MAX_HEADLINES,
    MAX_LOGO_IMAGES,
    MAX_MARKETING_IMAGES,
    MAX_SQUARE_IMAGES,
    MIN_DESCRIPTIONS,
    MIN_HEADLINES,
    MIN_LOGO_IMAGES,
    MIN_MARKETING_IMAGES,
    MIN_SQUARE_IMAGES,
    RDAValidationResult,
    _is_valid_url,
    _preview,
    validate_rda_inputs,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    def test_headline_max_width_is_30(self) -> None:
        assert HEADLINE_MAX_WIDTH == 30

    def test_long_headline_max_width_is_90(self) -> None:
        assert LONG_HEADLINE_MAX_WIDTH == 90

    def test_description_max_width_is_90(self) -> None:
        assert DESCRIPTION_MAX_WIDTH == 90

    def test_business_name_max_width_is_25(self) -> None:
        assert BUSINESS_NAME_MAX_WIDTH == 25

    def test_min_headlines_is_1(self) -> None:
        assert MIN_HEADLINES == 1

    def test_max_headlines_is_5(self) -> None:
        assert MAX_HEADLINES == 5

    def test_min_descriptions_is_1(self) -> None:
        assert MIN_DESCRIPTIONS == 1

    def test_max_descriptions_is_5(self) -> None:
        assert MAX_DESCRIPTIONS == 5

    def test_min_marketing_images_is_1(self) -> None:
        assert MIN_MARKETING_IMAGES == 1

    def test_max_marketing_images_is_15(self) -> None:
        assert MAX_MARKETING_IMAGES == 15

    def test_min_square_images_is_1(self) -> None:
        assert MIN_SQUARE_IMAGES == 1

    def test_max_square_images_is_15(self) -> None:
        assert MAX_SQUARE_IMAGES == 15

    def test_min_logo_images_is_0(self) -> None:
        assert MIN_LOGO_IMAGES == 0

    def test_max_logo_images_is_5(self) -> None:
        assert MAX_LOGO_IMAGES == 5

    def test_max_final_url_length_is_2048(self) -> None:
        assert MAX_FINAL_URL_LENGTH == 2048


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPreview:
    def test_short_text_returned_unchanged(self) -> None:
        assert _preview("hello") == "hello"

    def test_long_text_truncated(self) -> None:
        long_text = "a" * 100
        result = _preview(long_text)
        assert result.endswith("...")
        assert len(result) < len(long_text)


@pytest.mark.unit
class TestIsValidUrl:
    def test_https_OK(self) -> None:
        assert _is_valid_url("https://example.com") is True

    def test_http_OK(self) -> None:
        assert _is_valid_url("http://example.com") is True

    def test_missing_scheme_rejected(self) -> None:
        assert _is_valid_url("example.com") is False

    def test_javascript_scheme_rejected(self) -> None:
        assert _is_valid_url("javascript:alert(1)") is False

    def test_url_with_space_rejected(self) -> None:
        assert _is_valid_url("https://exam ple.com") is False

    def test_url_with_control_char_rejected(self) -> None:
        assert _is_valid_url("https://example.com\x00") is False

    def test_missing_host_rejected(self) -> None:
        assert _is_valid_url("https://") is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateRdaInputsHappyPath:
    def test_succeeds_with_minimal_inputs(self) -> None:
        result = validate_rda_inputs(
            headlines=["見出し1"],
            long_headline="長い見出しのサンプルテキスト",
            descriptions=["説明文のサンプル"],
            business_name="サンプル会社",
            marketing_image_asset_resource_names=["customers/1/assets/100"],
            square_marketing_image_asset_resource_names=["customers/1/assets/200"],
            logo_image_asset_resource_names=None,
            final_url="https://example.com",
        )
        assert isinstance(result, RDAValidationResult)
        assert result.headlines == ("見出し1",)
        assert result.long_headline == "長い見出しのサンプルテキスト"
        assert result.descriptions == ("説明文のサンプル",)
        assert result.business_name == "サンプル会社"

    def test_succeeds_with_all_fields(self) -> None:
        result = validate_rda_inputs(
            headlines=["A", "B", "C", "D", "E"],
            long_headline="a" * 50,
            descriptions=["Desc1", "Desc2", "Desc3", "Desc4", "Desc5"],
            business_name="Acme Inc",
            marketing_image_asset_resource_names=[
                "customers/1/assets/1",
                "customers/1/assets/2",
                "customers/1/assets/3",
            ],
            square_marketing_image_asset_resource_names=[
                "customers/1/assets/10",
                "customers/1/assets/20",
            ],
            logo_image_asset_resource_names=["customers/1/assets/100"],
            final_url="https://example.com/landing",
        )
        assert len(result.headlines) == 5
        assert len(result.descriptions) == 5
        assert result.logo_image_asset_resource_names == ("customers/1/assets/100",)

    def test_succeeds_with_logo_image_none(self) -> None:
        result = validate_rda_inputs(
            headlines=["見出し1"],
            long_headline="長い見出し",
            descriptions=["説明文"],
            business_name="ビジネス名",
            marketing_image_asset_resource_names=["customers/1/assets/1"],
            square_marketing_image_asset_resource_names=["customers/1/assets/2"],
            logo_image_asset_resource_names=None,
            final_url="https://example.com",
        )
        assert result.logo_image_asset_resource_names == ()


# ---------------------------------------------------------------------------
# Headline validation
# ---------------------------------------------------------------------------


def _base_args() -> dict:
    return {
        "long_headline": "Long Headline サンプル",
        "descriptions": ["Description"],
        "business_name": "Business",
        "marketing_image_asset_resource_names": ["customers/1/assets/1"],
        "square_marketing_image_asset_resource_names": ["customers/1/assets/2"],
        "logo_image_asset_resource_names": None,
        "final_url": "https://example.com",
    }


@pytest.mark.unit
class TestHeadlinesValidation:
    def test_empty_list_rejected(self) -> None:
        args = _base_args()
        with pytest.raises(ValueError, match="At least 1 headline"):
            validate_rda_inputs(headlines=[], **args)

    def test_more_than_5_truncated_to_5(self, caplog) -> None:
        args = _base_args()
        with caplog.at_level(logging.INFO):
            result = validate_rda_inputs(
                headlines=["H1", "H2", "H3", "H4", "H5", "H6", "H7"], **args
            )
        assert len(result.headlines) == 5
        assert result.headlines == ("H1", "H2", "H3", "H4", "H5")
        # The truncation log should be emitted.
        assert any("Truncating RDA headlines" in r.message for r in caplog.records)

    def test_headline_over_30_width_rejected(self) -> None:
        args = _base_args()
        # 31 half-width chars = 31 width
        too_long = "a" * 31
        with pytest.raises(ValueError, match="Headline.*exceeds.*30"):
            validate_rda_inputs(headlines=[too_long], **args)

    def test_full_width_headline_over_30_width_rejected(self) -> None:
        args = _base_args()
        # 16 full-width chars = 32 width
        too_long_jp = "あ" * 16
        with pytest.raises(ValueError, match="Headline.*exceeds.*30"):
            validate_rda_inputs(headlines=[too_long_jp], **args)

    def test_exactly_30_width_accepted(self) -> None:
        args = _base_args()
        ok = "a" * 30
        result = validate_rda_inputs(headlines=[ok], **args)
        assert result.headlines == (ok,)

    def test_15_full_width_chars_at_30_width_accepted(self) -> None:
        args = _base_args()
        ok = "あ" * 15  # = 30 width
        result = validate_rda_inputs(headlines=[ok], **args)
        assert result.headlines == (ok,)

    def test_overlong_headline_error_message_truncated(self) -> None:
        args = _base_args()
        very_long = "a" * 200
        with pytest.raises(ValueError) as exc_info:
            validate_rda_inputs(headlines=[very_long], **args)
        # The error message is truncated, so it's much shorter than 200 chars.
        assert len(str(exc_info.value)) < 200


# ---------------------------------------------------------------------------
# Long headline validation
# ---------------------------------------------------------------------------


def _base_args_for_long_headline() -> dict:
    return {
        "headlines": ["Headline"],
        "descriptions": ["Description"],
        "business_name": "Business",
        "marketing_image_asset_resource_names": ["customers/1/assets/1"],
        "square_marketing_image_asset_resource_names": ["customers/1/assets/2"],
        "logo_image_asset_resource_names": None,
        "final_url": "https://example.com",
    }


@pytest.mark.unit
class TestLongHeadlineValidation:
    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="long_headline.*required"):
            validate_rda_inputs(long_headline="", **_base_args_for_long_headline())

    def test_over_90_width_rejected(self) -> None:
        too_long = "a" * 91
        with pytest.raises(ValueError, match="long_headline.*exceeds.*90"):
            validate_rda_inputs(
                long_headline=too_long, **_base_args_for_long_headline()
            )

    def test_exactly_90_width_accepted(self) -> None:
        ok = "a" * 90
        result = validate_rda_inputs(long_headline=ok, **_base_args_for_long_headline())
        assert result.long_headline == ok


# ---------------------------------------------------------------------------
# Description validation
# ---------------------------------------------------------------------------


def _base_args_for_descriptions() -> dict:
    return {
        "headlines": ["Headline"],
        "long_headline": "Long Headline",
        "business_name": "Business",
        "marketing_image_asset_resource_names": ["customers/1/assets/1"],
        "square_marketing_image_asset_resource_names": ["customers/1/assets/2"],
        "logo_image_asset_resource_names": None,
        "final_url": "https://example.com",
    }


@pytest.mark.unit
class TestDescriptionsValidation:
    def test_empty_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="At least 1 description"):
            validate_rda_inputs(descriptions=[], **_base_args_for_descriptions())

    def test_more_than_5_truncated_to_5(self, caplog) -> None:
        with caplog.at_level(logging.INFO):
            result = validate_rda_inputs(
                descriptions=["D1", "D2", "D3", "D4", "D5", "D6"],
                **_base_args_for_descriptions(),
            )
        assert len(result.descriptions) == 5
        assert any("Truncating RDA descriptions" in r.message for r in caplog.records)

    def test_over_90_width_rejected(self) -> None:
        too_long = "a" * 91
        with pytest.raises(ValueError, match="Description.*exceeds.*90"):
            validate_rda_inputs(
                descriptions=[too_long], **_base_args_for_descriptions()
            )


# ---------------------------------------------------------------------------
# Business name validation
# ---------------------------------------------------------------------------


def _base_args_for_business_name() -> dict:
    return {
        "headlines": ["Headline"],
        "long_headline": "Long Headline",
        "descriptions": ["Description"],
        "marketing_image_asset_resource_names": ["customers/1/assets/1"],
        "square_marketing_image_asset_resource_names": ["customers/1/assets/2"],
        "logo_image_asset_resource_names": None,
        "final_url": "https://example.com",
    }


@pytest.mark.unit
class TestBusinessNameValidation:
    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="business_name.*required"):
            validate_rda_inputs(business_name="", **_base_args_for_business_name())

    def test_over_25_width_rejected(self) -> None:
        too_long = "a" * 26
        with pytest.raises(ValueError, match="business_name.*exceeds.*25"):
            validate_rda_inputs(
                business_name=too_long, **_base_args_for_business_name()
            )

    def test_exactly_25_width_accepted(self) -> None:
        ok = "a" * 25
        result = validate_rda_inputs(business_name=ok, **_base_args_for_business_name())
        assert result.business_name == ok


# ---------------------------------------------------------------------------
# Image asset validation
# ---------------------------------------------------------------------------


def _base_args_for_images() -> dict:
    return {
        "headlines": ["Headline"],
        "long_headline": "Long Headline",
        "descriptions": ["Description"],
        "business_name": "Business",
        "final_url": "https://example.com",
    }


@pytest.mark.unit
class TestImageAssetsValidation:
    def test_empty_marketing_images_rejected(self) -> None:
        with pytest.raises(ValueError, match="At least 1 marketing image"):
            validate_rda_inputs(
                marketing_image_asset_resource_names=[],
                square_marketing_image_asset_resource_names=["customers/1/assets/1"],
                logo_image_asset_resource_names=None,
                **_base_args_for_images(),
            )

    def test_16_marketing_images_rejected(self) -> None:
        ids = [f"customers/1/assets/{i}" for i in range(16)]
        with pytest.raises(ValueError, match="marketing.*images.*exceed.*15"):
            validate_rda_inputs(
                marketing_image_asset_resource_names=ids,
                square_marketing_image_asset_resource_names=["customers/1/assets/1"],
                logo_image_asset_resource_names=None,
                **_base_args_for_images(),
            )

    def test_empty_square_images_rejected(self) -> None:
        with pytest.raises(ValueError, match="At least 1 square marketing image"):
            validate_rda_inputs(
                marketing_image_asset_resource_names=["customers/1/assets/1"],
                square_marketing_image_asset_resource_names=[],
                logo_image_asset_resource_names=None,
                **_base_args_for_images(),
            )

    def test_16_square_images_rejected(self) -> None:
        ids = [f"customers/1/assets/{i}" for i in range(16)]
        with pytest.raises(ValueError, match="square marketing.*exceed.*15"):
            validate_rda_inputs(
                marketing_image_asset_resource_names=["customers/1/assets/1"],
                square_marketing_image_asset_resource_names=ids,
                logo_image_asset_resource_names=None,
                **_base_args_for_images(),
            )

    def test_6_logo_images_rejected(self) -> None:
        ids = [f"customers/1/assets/{i}" for i in range(6)]
        with pytest.raises(ValueError, match="logo images.*exceed.*5"):
            validate_rda_inputs(
                marketing_image_asset_resource_names=["customers/1/assets/1"],
                square_marketing_image_asset_resource_names=["customers/1/assets/2"],
                logo_image_asset_resource_names=ids,
                **_base_args_for_images(),
            )

    def test_5_logo_images_accepted(self) -> None:
        ids = [f"customers/1/assets/{i}" for i in range(5)]
        result = validate_rda_inputs(
            marketing_image_asset_resource_names=["customers/1/assets/1"],
            square_marketing_image_asset_resource_names=["customers/1/assets/2"],
            logo_image_asset_resource_names=ids,
            **_base_args_for_images(),
        )
        assert len(result.logo_image_asset_resource_names) == 5


# ---------------------------------------------------------------------------
# Final URL validation
# ---------------------------------------------------------------------------


def _base_args_for_url() -> dict:
    return {
        "headlines": ["Headline"],
        "long_headline": "Long Headline",
        "descriptions": ["Description"],
        "business_name": "Business",
        "marketing_image_asset_resource_names": ["customers/1/assets/1"],
        "square_marketing_image_asset_resource_names": ["customers/1/assets/2"],
        "logo_image_asset_resource_names": None,
    }


@pytest.mark.unit
class TestFinalUrlValidation:
    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="final_url.*required"):
            validate_rda_inputs(final_url="", **_base_args_for_url())

    def test_url_without_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="final_url.*invalid"):
            validate_rda_inputs(final_url="example.com", **_base_args_for_url())

    def test_https_accepted(self) -> None:
        result = validate_rda_inputs(
            final_url="https://example.com", **_base_args_for_url()
        )
        assert result.final_url == "https://example.com"

    def test_http_accepted(self) -> None:
        result = validate_rda_inputs(
            final_url="http://example.com", **_base_args_for_url()
        )
        assert result.final_url == "http://example.com"

    def test_over_2048_chars_rejected(self) -> None:
        too_long = "https://example.com/" + "a" * 2030
        assert len(too_long) > MAX_FINAL_URL_LENGTH
        with pytest.raises(ValueError, match="final_url exceeds 2048"):
            validate_rda_inputs(final_url=too_long, **_base_args_for_url())

    def test_url_with_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="final_url.*invalid"):
            validate_rda_inputs(
                final_url="https://exam ple.com", **_base_args_for_url()
            )
