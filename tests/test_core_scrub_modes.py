"""Prose rules versus argument rules in the scrubber (#779).

Split out of ``tests/test_mcp_plugin_audit.py``. One pattern set, two
modes: an error message and a tool argument leak differently and read
differently, so the ROOTS are declared once and the MODE decides how
strictly a key has to be punctuated to count. These tests pin both ends
of that — the ad copy that must survive an argument, and the credential
shapes that must not.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.mcp import plugin_audit
from mureo.mcp.plugin_audit import _mask


@pytest.mark.unit
class TestArgumentValuesAreNotAdCopy:
    """#779 review 2 — the bare roots were eating advertising copy.

    A root like ``secret`` or ``cookie`` matched on a space-padded colon,
    which is how English punctuates a sentence and how nobody writes a
    credential. ``headline``, ``description``, ``primary_text`` and a
    campaign ``name`` are the most-written arguments in this product, and
    the journal exists to record what the agent actually submitted.

    The fix is the separator, not the root list: in ``argument`` mode an
    ambiguous root needs the shape ``_CODE_KEY_VALUE`` already requires —
    ``key=value`` with no space before the ``=``, or the quoted dict-key
    form — so every machine-generated leak still matches.
    """

    @pytest.mark.parametrize(
        "copy",
        [
            "The secret: better ROAS in 30 days",
            "Trade secret: how we cut CPA 40%",
            "Cookie: the new flavour drop",
            "Signature: our chef's tasting menu",
            "Credential: ISO 27001 certified",
            "Password: freedom — a thriller",
            # Judged with the six above: ``authorization`` is an ordinary
            # English word in exactly the same way.
            "Landing page authorization: pending review",
        ],
    )
    def test_ad_copy_survives_the_argument_path(self, copy: str) -> None:
        assert _mask({"headline": copy}) == {"headline": copy}

    @pytest.mark.parametrize(
        ("text", "leaked"),
        [
            # ``=`` with no space: every form-encoded and query-string leak.
            ("app_secret=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("cookie=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("password=hunter2hunter2", "hunter2hunter2"),
            ("authorization=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # A signed GCS URL — the real reason these roots are here.
            (
                "https://storage.googleapis.com/b/o.png?X-Goog-Credential="
                "svc%40p.iam&X-Goog-Signature=abc123def456",
                "abc123def456",
            ),
            # The quoted dict-key form an exception repr produces.
            ('{"appSecret": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            ("{'cookie': 'SHHH_SECRET_VALUE'}", "SHHH_SECRET_VALUE"),
            # Unambiguous compounds keep the loose separator: they do not
            # occur in an English sentence, so a spaced colon is safe.
            ("developer-token: abc123XYZ", "abc123XYZ"),
            ("private_key: SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # Spelled out as a compound for exactly this reason: the bare
            # ``secret`` root would otherwise hand it the strict separator.
            ("client_secret: amzn1.oa2-cs.v1.abcdef", "amzn1.oa2-cs.v1.abcdef"),
        ],
    )
    def test_real_leak_shapes_still_match_in_an_argument(
        self, text: str, leaked: str
    ) -> None:
        out = _mask({"note": text})["note"]
        assert leaked not in out
        assert "***" in out

    @pytest.mark.parametrize(
        "copy",
        [
            "The secret: better ROAS in 30 days",
            "Cookie: the new flavour drop",
            "Password: freedom — a thriller",
            "Landing page authorization: pending review",
        ],
    )
    def test_prose_mode_is_deliberately_unchanged(self, copy: str) -> None:
        """The tightening is scoped to arguments. An error string, a
        ``reason`` and a ``rationale`` keep today's wider rule — prose is
        where a spaced colon really can introduce a credential, and where
        over-masking costs legibility rather than the record itself."""
        assert plugin_audit._scrub(copy) != copy


@pytest.mark.unit
class TestProseValuedArgumentKeys:
    """An argument named ``reason`` or ``rationale`` holds a SENTENCE.

    The mode split is keyed on what the text is, not on which function
    reached it, so the masker has to say so for the keys whose values it
    knows are prose. Otherwise the three built-ins that declare a
    ``reason`` of their own — their argument never goes through
    ``split_call_reason``, so it stays in ``args`` — would have that one
    sentence scrubbed one way into ``JOURNAL.jsonl`` and another way into
    ``STATE.json``.
    """

    @pytest.mark.parametrize("key", ["reason", "rationale", "Reason"])
    def test_a_prose_key_is_scrubbed_as_prose(self, key: str) -> None:
        sentence = "exchanging the grant with code=ANabcdefgh12 failed"
        out = _mask({"entry": {key: sentence}})["entry"][key]
        assert out == plugin_audit._scrub(sentence)
        assert "ANabcdefgh12" not in out

    def test_a_prose_key_at_the_top_level_too(self) -> None:
        out = _mask({"reason": "not collected: code=ANabcdefgh12"})["reason"]
        assert "ANabcdefgh12" not in out

    def test_an_ordinary_key_keeps_argument_rules(self) -> None:
        """The exception is scoped to prose keys — a ``final_url`` must
        still keep its query string."""
        url = "https://example.com/lp?promo_code=SUMMER2026"
        assert _mask({"final_url": url})["final_url"] == url

    def test_a_prose_key_holding_a_container_is_still_recursed(self) -> None:
        """``reason`` holding a container must not skip masking."""
        out = _mask({"reason": {"api_key": "SHHH", "note": "hi"}})
        assert out["reason"] == {"api_key": "***", "note": "hi"}

    @pytest.mark.parametrize(
        "wrapped",
        [
            {"reason": ["password: hunter2hunter2"]},
            {"reason": {"detail": "password: hunter2hunter2"}},
            {"reason": [{"detail": "password: hunter2hunter2"}]},
            {"entry": {"rationale": ["password: hunter2hunter2"]}},
        ],
        ids=["list", "dict", "list-of-dict", "nested-rationale"],
    )
    def test_prose_survives_being_wrapped_in_a_container(
        self, wrapped: dict[str, Any]
    ) -> None:
        """A plugin is free to declare ``reason`` as a list or an object.

        Reading the mode off the immediate value's type left the sentence
        scrubbed as an ARGUMENT once it was wrapped, so a space-padded
        colon — the one shape ARGUMENT mode deliberately ignores — went
        through verbatim while the identical text one level up was masked.
        """
        assert "hunter2hunter2" not in repr(_mask(wrapped))

    def test_an_ordinary_key_under_a_prose_key_is_prose_too(self) -> None:
        """The mode is sticky below a prose key, not re-derived per key.

        ``{"reason": {"headline": …}}`` is not ad copy on its way to a
        platform; it is whatever a plugin packed into its rationale. Prose
        is the wider reading, so the sticky choice can only redact more.
        """
        out = _mask({"reason": {"headline": "The secret: better ROAS"}})
        assert out["reason"]["headline"] == "The secret: *** ROAS"
        # ...and the same key outside a rationale still keeps ad copy.
        assert _mask({"headline": "The secret: better ROAS"}) == {
            "headline": "The secret: better ROAS"
        }

    def test_a_prose_key_is_still_capped(self) -> None:
        out = _mask({"reason": "y" * 2000})["reason"]
        assert len(out) == plugin_audit._MAX_STR
        assert out.endswith(plugin_audit._TRUNC)
