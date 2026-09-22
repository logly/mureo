"""The scrubber's bounded window and the margin that makes it safe (#779).

Split out of ``tests/test_mcp_plugin_audit.py``. Every trail that scrubs
also caps, so the passes run over ``cap + STRADDLE_MARGIN`` characters
and no more: the cost per recorded string is a constant rather than the
size of whatever an MCP client sent. The margin is the part that has to
be argued rather than assumed — a credential straddling the cut must
still be recognised — so it is pinned at the boundary here.
"""

from __future__ import annotations

import pytest

from mureo.core import scrub
from mureo.core.scrub import ARGUMENT, STRADDLE_MARGIN, scrub_capped
from mureo.mcp import plugin_audit
from mureo.mcp.plugin_audit import _mask


@pytest.mark.unit
class TestTheStraddleMargin:
    """#779 review — why the window is ``_MAX_STR`` PLUS something.

    The window keeps the cost constant; the margin is what makes it safe.
    A credential only leaves something behind if it STARTS inside the text
    that survives truncation, and the scrubber has to see the whole shape
    to recognise it. ``Basic <base64>`` is the binding case at 22
    characters. Offset 484 alone did not pin any of this.
    """

    _BASIC = "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ=="

    def test_the_window_is_the_named_margin(self) -> None:
        assert plugin_audit.SCRUB_WINDOW == plugin_audit._MAX_STR + STRADDLE_MARGIN

    def test_a_credential_straddling_the_cut_is_masked_whole(self) -> None:
        """Starts at 499 — inside the surviving prefix — and ends at 532,
        past ``_MAX_STR``. Only the margin lets the scrubber see it."""
        out = _mask("x" * 499 + self._BASIC)
        assert "Basic" not in out
        assert "QWxhZGRpbj" not in out
        assert out == "x" * 499 + "***"

    def test_without_the_margin_a_fragment_would_survive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same input with the margin removed. This is the leak the 64
        buys off, measured rather than asserted: the cut lands inside the
        credential, the pattern no longer matches, and what the record
        keeps is the start of an ``Authorization`` header."""
        monkeypatch.setattr(plugin_audit, "SCRUB_WINDOW", plugin_audit._MAX_STR)
        out = _mask("x" * 499 + self._BASIC)
        assert out.endswith("B" + plugin_audit._TRUNC)

    @pytest.mark.parametrize("offset", [512, 540, 575, 577])
    def test_a_credential_past_the_surviving_prefix_is_cut_away(
        self, offset: int
    ) -> None:
        """Inside the margin (512-575) or beyond the window (577), the
        answer is the same and it is not "masked" — it is "absent". Text
        past the window is never returned at all, because
        :func:`_mask_string` slices before it scrubs."""
        out = _mask("x" * offset + self._BASIC)
        assert "Basic" not in out
        assert out == "x" * (plugin_audit._MAX_STR - len(plugin_audit._TRUNC)) + (
            plugin_audit._TRUNC
        )


@pytest.mark.unit
class TestScrubCapped:
    """#779 review — the same bounded window for the PROSE call sites.

    ``reason``, ``error`` and the wizard's ``detail`` were all scrubbed
    whole and cut afterwards, so a 2 MB string bought 2 MB of regex work
    on the event loop to produce 512 characters.
    """

    def test_it_agrees_with_the_unbounded_form_on_a_short_string(self) -> None:
        text = "exchange failed: client_secret=amzn1.oa2-cs.v1.abc code=ANabcdefgh12"
        assert scrub_capped(text, 512) == scrub.scrub_text(text)

    def test_the_result_is_never_longer_than_the_cap(self) -> None:
        assert len(scrub_capped("x" * 5_000_000, 512)) == 512

    def test_it_never_reads_more_than_the_cap_plus_the_margin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[int] = []

        def _spy(text: str, **kwargs: object) -> str:
            seen.append(len(text))
            return text

        monkeypatch.setattr(scrub, "scrub_text", _spy)
        scrub_capped("x" * 5_000_000, 512)

        assert seen == [512 + STRADDLE_MARGIN]

    def test_a_credential_straddling_the_cap_is_still_masked(self) -> None:
        out = scrub_capped("x" * 499 + "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==", 512)
        assert out == "x" * 499 + "***"

    def test_the_mode_is_forwarded(self) -> None:
        """Prose is the default, and ``argument`` has to be asked for —
        the same contract as :func:`scrub_text`."""
        assert scrub_capped("?code=ANabcdefgh12", 512) == "?code=***"
        assert (
            scrub_capped("?code=ANabcdefgh12", 512, mode=ARGUMENT)
            == "?code=ANabcdefgh12"
        )
