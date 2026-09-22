"""The three Amazon error paths scrub a BOUNDED prefix (#791).

#779 bounded four call sites with ``scrub_capped`` and missed these
three. The cost is linear in the input and the bridge's is on the MCP
dispatch path, where ``tests/test_amazon_bridge.py`` already feeds a 2 MB
body: half a second of regex work on the event loop to produce a
4000-character diagnostic.

Bounding means slicing BEFORE scrubbing, and a slice can cut a credential
in half. :data:`~mureo.core.scrub.STRADDLE_MARGIN` is what makes that
safe — the scrubber reads that far past the cap, so a credential that
STARTS inside the surviving prefix is still recognised whole. That is the
property this file pins, once per site, the same way
``tests/test_core_scrub_window.py`` pins it for #779's four.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from mureo.amazon_ads import bridge
from mureo.amazon_ads.lwa import AmazonAuthError, LwaTokens
from mureo.amazon_ads.session_auth import (
    MAX_ERROR_TEXT,
    AmazonBridgeError,
    SessionCredentials,
)
from mureo.auth import AmazonAdsCredentials
from mureo.cli.main import app
from mureo.core import scrub
from mureo.core.scrub import STRADDLE_MARGIN

#: The binding straddle shape, as in ``tests/test_core_scrub_window.py``:
#: ``Basic `` plus the 16-character minimum base64 value is the longest
#: thing the scrubber must SEE to recognise a credential.
_BASIC = "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ=="

#: How far before the cap the credential starts. 13 characters in — so it
#: starts inside the text that survives the cut and ends 21 characters
#: past it, which is exactly the case the margin exists for.
_START_BEFORE_CAP = 13


def _straddling(cap: int) -> str:
    """Filler + a credential that starts just before ``cap`` and ends past it."""
    return "x" * (cap - _START_BEFORE_CAP) + _BASIC


def _masked(cap: int) -> str:
    """What the straddling credential must be reduced to."""
    return "x" * (cap - _START_BEFORE_CAP) + "***"


@pytest.mark.unit
class TestTheBridgeFailureBody:
    """Site 1 — ``_failure_text``, on the MCP dispatch path."""

    def test_a_credential_straddling_the_scrub_cap_is_masked(self) -> None:
        out = bridge._display_text(_straddling(bridge._MAX_SCRUB_INPUT))
        assert "QWxhZGRpbj" not in out
        assert out == _masked(bridge._MAX_SCRUB_INPUT)

    def test_it_never_scrubs_more_than_the_cap_plus_the_margin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: the work is a constant, not the body's size."""
        seen: list[int] = []

        def _spy(text: str, **kwargs: object) -> str:
            seen.append(len(text))
            return text

        monkeypatch.setattr(scrub, "scrub_text", _spy)
        bridge._display_text('{"code":"BAD","message":"%s"}' % ("x" * 2_000_000))

        assert seen == [bridge._MAX_SCRUB_INPUT + STRADDLE_MARGIN]

    def test_an_oversized_body_says_so_instead_of_passing_off_a_fragment(
        self,
    ) -> None:
        """Cut AND unparseable is the one case flattening cannot serve.

        The slice lands inside the JSON, so what is left is a fragment.
        Handing it over as though it were Amazon's diagnostic is the
        test-green regression #791 was opened about; saying what happened
        is the honest answer.
        """
        out = bridge._display_text('{"code":"BAD","message":"%s"}' % ("x" * 2_000_000))
        assert out.startswith(bridge._OVERSIZE_BODY_TEXT)
        assert len(out) == len(bridge._OVERSIZE_BODY_TEXT) + 1 + bridge._MAX_SCRUB_INPUT

    def test_a_body_over_the_cap_that_still_parses_is_still_flattened(self) -> None:
        """Over the cap is not the same as unparseable — trailing filler
        cuts away without touching the object, and then the agent gets the
        flattened form exactly as it does for a small body."""
        out = bridge._display_text('{"code":"BAD","message":"m"}' + " " * 20_000)
        assert out == "BAD: m"

    def test_a_short_body_is_untouched_by_the_cap(self) -> None:
        body = '{"code":"BAD","message":"rejected"}'
        assert bridge._display_text(body) == "BAD: rejected"


@pytest.mark.unit
class TestTheSessionCredentialSeam:
    """Site 2 — ``SessionCredentials.refresh_and_persist``, both raises."""

    _CREDS = AmazonAdsCredentials(
        client_id="cid", access_token="", refresh_token="Atzr|R", client_secret="sec"
    )

    def _seam(self, *, refresher: Any = None, token_saver: Any = None) -> Any:
        return SessionCredentials(
            loader=lambda: None,
            refresher=refresher or (lambda c: LwaTokens("Atza|NEW", "Atzr|R", 3600)),
            token_saver=token_saver or (lambda a, r: None),
        )

    def _refresh(self, seam: Any) -> str:
        with pytest.raises(AmazonBridgeError) as ei:
            seam.refresh_and_persist(
                self._CREDS, cause=None, auth_failure_prefix="mint failed"
            )
        return str(ei.value)

    def test_a_credential_straddling_the_cap_is_masked_on_the_lwa_path(self) -> None:
        def _boom(creds: Any) -> LwaTokens:
            raise AmazonAuthError(_straddling(MAX_ERROR_TEXT))

        message = self._refresh(self._seam(refresher=_boom))
        assert "QWxhZGRpbj" not in message
        assert message == f"mint failed: {_masked(MAX_ERROR_TEXT)}"

    def test_a_credential_straddling_the_cap_is_masked_on_the_save_path(self) -> None:
        from mureo.core.atomic_json import ConfigWriteError

        def _boom(access: str, refresh: str | None) -> None:
            raise ConfigWriteError(_straddling(MAX_ERROR_TEXT))

        message = self._refresh(self._seam(token_saver=_boom))
        assert "QWxhZGRpbj" not in message
        assert message.endswith(f": {_masked(MAX_ERROR_TEXT)}")

    def test_a_runaway_exception_text_is_cut_to_the_cap(self) -> None:
        def _boom(creds: Any) -> LwaTokens:
            raise AmazonAuthError("y" * 2_000_000)

        message = self._refresh(self._seam(refresher=_boom))
        assert message == "mint failed: " + "y" * MAX_ERROR_TEXT


@pytest.mark.unit
class TestTheAmazonCli:
    """Site 3 — ``mureo amazon refresh-manifest``'s three error echoes."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, exc: Exception):
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.manifest_path",
            lambda: tmp_path / "amazon_tools.json",
        )
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials",
            lambda *a, **k: AmazonAdsCredentials(client_id="cid", access_token="tok"),
        )

        def _boom(creds: Any) -> Any:
            raise exc

        monkeypatch.setattr("mureo.cli.amazon_cmd.generate_manifest_sync", _boom)
        return CliRunner().invoke(app, ["amazon", "refresh-manifest"])

    def test_a_credential_straddling_the_cap_is_masked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result = self._run(
            monkeypatch, tmp_path, RuntimeError(_straddling(MAX_ERROR_TEXT))
        )
        assert result.exit_code == 1
        assert "QWxhZGRpbj" not in result.output
        assert _masked(MAX_ERROR_TEXT) in result.output

    def test_a_runaway_exception_text_is_cut_to_the_cap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result = self._run(monkeypatch, tmp_path, RuntimeError("y" * 2_000_000))
        assert result.exit_code == 1
        assert "y" * MAX_ERROR_TEXT in result.output
        assert "y" * (MAX_ERROR_TEXT + 1) not in result.output
