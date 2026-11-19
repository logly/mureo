"""How ChatGPT Ads audience identifiers are normalised and hashed (#995).

Pure functions, no I/O. Pinned here: the reference's known vector, the email
and phone normalisation the reference documents (trim, lowercase, dots and
plus tags kept; E.164 with the ``+`` hashed), the shape checks for the
pre-hashed types and the advertising id, and the type each one is sent as.
"""

from __future__ import annotations

import hashlib

import pytest

from mureo.chatgpt_ads._hashing import (
    IDENTIFIER_TYPES,
    SENT_IDENTIFIER_TYPES,
    normalized_identifier,
    sha256_hex,
    without_identifiers,
)

pytestmark = pytest.mark.unit

#: SHA-256 of ``jamie@example.com``, as the API reference prints it.
_JAMIE = "057a0fff4c78ae3e14236c36b611061cbdd54ccd72a34b23f77d7a8c4bca4963"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestVocabulary:
    def test_the_five_input_types(self) -> None:
        assert IDENTIFIER_TYPES == (
            "email",
            "phone",
            "gaid",
            "email_sha256",
            "phone_number_sha256",
        )

    def test_plaintext_is_never_a_sent_type(self) -> None:
        assert SENT_IDENTIFIER_TYPES == {
            "email": "email_sha256",
            "phone": "phone_number_sha256",
            "gaid": "gaid",
            "email_sha256": "email_sha256",
            "phone_number_sha256": "phone_number_sha256",
        }


class TestEmail:
    def test_the_known_vector(self) -> None:
        assert sha256_hex("jamie@example.com") == _JAMIE
        assert normalized_identifier("email", "jamie@example.com") == _JAMIE

    @pytest.mark.parametrize(
        "raw", ["  Jamie@Example.COM  ", "JAMIE@EXAMPLE.COM", "\tjamie@example.com\r"]
    )
    def test_trimmed_and_lowercased(self, raw: str) -> None:
        assert normalized_identifier("email", raw) == _JAMIE

    @pytest.mark.parametrize(
        "address", ["first.last@example.com", "jamie+ads@example.com"]
    )
    def test_dots_and_plus_tags_are_kept(self, address: str) -> None:
        assert normalized_identifier("email", address) == _digest(address)
        assert normalized_identifier("email", address) != _digest(
            address.replace(".", "", 1).replace("+ads", "")
        )

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "jamie.example.com",
            "jamie@@example.com",
            "a@b@example.com",
            "@example.com",
            "jamie@",
            "jamie @example.com",
            "jamie@exam ple.com",
        ],
    )
    def test_an_address_without_exactly_one_at_or_with_spaces_is_invalid(
        self, raw: str
    ) -> None:
        assert normalized_identifier("email", raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            "jamie@example.com,+15550100000",
            '"jamie@example.com"',
            "mailto:jamie@example.com",
            "jamie​@example.com",
            "﻿jamie@example.com",
            "jamie\x00@example.com",
            "ｊamie@example.com",
            "a@b",
            "jamie;x@example.com",
            "<jamie@example.com>",
            "jamie(x)@example.com",
            "jamie[x]@example.com",
            "jam\\ie@example.com",
            "jamie@.example.com",
            "jamie@example.com.",
            "jamie@-example.com",
            "jamie@example.com-",
            "jérôme@example.com",
        ],
        ids=[
            "two-cells",
            "quoted",
            "mailto",
            "zero-width-space",
            "mid-file-bom",
            "nul",
            "full-width",
            "no-dot",
            "semicolon",
            "angle-brackets",
            "round-brackets",
            "square-brackets",
            "backslash",
            "domain-leading-dot",
            "domain-trailing-dot",
            "domain-leading-hyphen",
            "domain-trailing-hyphen",
            "non-ascii",
        ],
    )
    def test_anything_but_a_plain_ascii_address_is_invalid(self, raw: str) -> None:
        assert normalized_identifier("email", raw) is None

    def test_an_apostrophe_and_a_plus_tag_stay_valid(self) -> None:
        address = "o'brien+tag@mail.example.com"
        assert normalized_identifier("email", address) == _digest(address)

    def test_the_known_vector_survives_case_and_spaces(self) -> None:
        assert normalized_identifier("email", "  Jamie@Example.com ") == _JAMIE


class TestPhone:
    @pytest.mark.parametrize(
        "raw",
        [
            "+15555550123",
            "+1 555 555 0123",
            "+1-555-555-0123",
            "+1 (555) 555.0123",
            "  +1 555 555 0123 ",
        ],
    )
    def test_separators_removed_and_the_plus_hashed(self, raw: str) -> None:
        assert normalized_identifier("phone", raw) == _digest("+15555550123")
        assert normalized_identifier("phone", raw) != _digest("15555550123")

    @pytest.mark.parametrize(
        "raw",
        [
            "15555550123",
            "555-555-0123",
            "+05555550123",
            "+123456",
            "+1234567890123456",
            "+1555abc0123",
            "++15555550123",
            "",
        ],
    )
    def test_without_plus_and_country_code_or_outside_e164_is_invalid(
        self, raw: str
    ) -> None:
        assert normalized_identifier("phone", raw) is None

    def test_e164_length_bounds(self) -> None:
        assert normalized_identifier("phone", "+1234567") is not None
        assert normalized_identifier("phone", "+123456789012345") is not None

    @pytest.mark.parametrize("raw", ["+44 (0)20 7946 0958", "+44 ( 0 ) 20 7946 0958"])
    def test_a_bracketed_trunk_zero_is_invalid(self, raw: str) -> None:
        assert normalized_identifier("phone", raw) is None

    def test_a_bracketed_area_code_stays_valid(self) -> None:
        assert normalized_identifier("phone", "+1 (415) 555-2671") == _digest(
            "+14155552671"
        )


class TestPrehashed:
    @pytest.mark.parametrize("kind", ["email_sha256", "phone_number_sha256"])
    def test_hex_is_lowercased_and_sent_as_given(self, kind: str) -> None:
        assert normalized_identifier(kind, _JAMIE.upper()) == _JAMIE
        assert normalized_identifier(kind, f"  {_JAMIE}  ") == _JAMIE

    @pytest.mark.parametrize(
        "raw", [_JAMIE[:-1], _JAMIE + "0", _JAMIE[:-1] + "g", "jamie@example.com"]
    )
    @pytest.mark.parametrize("kind", ["email_sha256", "phone_number_sha256"])
    def test_anything_but_64_hex_characters_is_invalid(
        self, kind: str, raw: str
    ) -> None:
        assert normalized_identifier(kind, raw) is None


class TestGaid:
    _GAID = "38400000-8cf0-11bd-b23e-10b96e40000d"

    def test_sent_raw_and_lowercased(self) -> None:
        assert normalized_identifier("gaid", self._GAID.upper()) == self._GAID
        assert normalized_identifier("gaid", f" {self._GAID} ") == self._GAID

    @pytest.mark.parametrize(
        "raw",
        [
            "384000008cf011bdb23e10b96e40000d",
            "38400000-8cf0-11bd-b23e-10b96e40000",
            "38400000-8cf0-11bd-b23e-10b96e40000dz",
            "{38400000-8cf0-11bd-b23e-10b96e40000d}",
            "00000000-0000-0000-0000-000000000000",
            "",
        ],
    )
    def test_anything_but_a_nonzero_hyphenated_uuid_is_invalid(self, raw: str) -> None:
        assert normalized_identifier("gaid", raw) is None


def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(ValueError, match="identifier_type"):
        normalized_identifier("idfa", "x")


class TestWithoutIdentifiers:
    _GAID = "38400000-8CF0-11BD-B23E-10B96E40000D"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (f"bad {_JAMIE}", "bad ***"),
            (f"bad {_JAMIE.upper()}.", "bad ***."),
            (f"{_JAMIE},{_digest('a@example.com')}", "***,***"),
            (f"id={_GAID}!", "id=***!"),
            (f"id {_GAID.lower()}", "id ***"),
            (f"bad {_JAMIE}{_digest('a@example.com')}.", "bad ***."),
            (f"bad a{_JAMIE}", "bad ***"),
        ],
        ids=[
            "digest",
            "upper-case",
            "two-digests",
            "gaid",
            "gaid-lower",
            "joined-digests",
            "65-hex",
        ],
    )
    def test_identifier_shaped_runs_are_masked(self, text: str, expected: str) -> None:
        assert without_identifiers(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            _JAMIE[:-1],
            "k" * 64,
            "0123456789abcdef0123456789abcdef",
            "plain text",
        ],
        ids=["63-hex", "not-hex", "32-hex-key", "prose"],
    )
    def test_other_text_is_unchanged(self, text: str) -> None:
        assert without_identifiers(text) == text
