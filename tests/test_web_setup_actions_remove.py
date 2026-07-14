"""Unit tests for the ``remove_*`` wrappers in ``mureo.web.setup_actions``.

Pins the symmetric uninstall wrappers added per planner HANDOFF
``feat-web-config-ui-phase1-uninstall.md``:

- ``remove_mureo_mcp(home)``     → wraps ``settings_remove.remove_mcp_config``.
- ``remove_auth_hook(home)``     → wraps ``settings_remove.remove_credential_guard``.
- ``remove_workflow_skills(home)``→ wraps ``setup_cmd.remove_skills``.

None of them records anything: the dashboard detects each part on disk on
every status read (#423), so there is no flag to keep in sync.
- ``clear_all_setup(home)``      → orchestrates the 4 individual removes
                                   + ``remove_legacy_commands`` + iterates
                                   ``mcpServers`` for installed official
                                   providers. Fail-safe: partial failure
                                   does NOT abort the chain. Per CTO
                                   decision #3, does NOT touch
                                   ``~/.mureo/credentials.json``.

The wrappers return ``ActionResult`` shaped envelopes (status: ok/noop/error).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.web.setup_actions import ActionResult

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# remove_mureo_mcp
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveMureoMcp:
    def test_returns_ok_when_remove_changed(self, tmp_path: Path) -> None:
        """When ``remove_mcp_config`` returns ``changed=True``, the
        wrapper returns ``status="ok"``."""
        from mureo.web import setup_actions

        fake = MagicMock(changed=True)
        with patch(
            "mureo.web.setup_actions.remove_mcp_config", return_value=fake
        ) as mock_remove:
            result = setup_actions.remove_mureo_mcp(home=tmp_path)

        assert isinstance(result, ActionResult)
        assert result.status == "ok"
        mock_remove.assert_called_once()

    def test_returns_noop_when_not_changed(self, tmp_path: Path) -> None:
        """When ``remove_mcp_config`` returns ``changed=False``
        (idempotent re-call), the wrapper returns ``status="noop"``."""
        from mureo.web import setup_actions

        fake = MagicMock(changed=False)
        with patch("mureo.web.setup_actions.remove_mcp_config", return_value=fake):
            result = setup_actions.remove_mureo_mcp(home=tmp_path)

        assert result.status == "noop"

    def test_returns_error_on_exception(self, tmp_path: Path) -> None:
        """An unexpected exception from the underlying remove is captured
        and surfaced as ``status="error"``."""
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_mcp_config",
            side_effect=RuntimeError("disk full"),
        ):
            result = setup_actions.remove_mureo_mcp(home=tmp_path)

        assert result.status == "error"
        # The detail should surface the exception type, not the raw message.
        assert result.detail == "RuntimeError"

    # The two tests that lived here asserted that a remove flipped — and a
    # FAILED remove did not flip — the ``setup_state.json`` flag the status
    # used to be read from. The second one named the hazard exactly: "a
    # transient failure would leave the dashboard reporting 'not installed'
    # while the on-disk MCP block remains intact."
    #
    # That hazard is now structural rather than defended: the status is
    # DETECTED from the MCP registry on every read (#423), so a remove that
    # failed leaves the block on disk and the next status read simply finds it
    # and says "installed". There is no flag left to flip, in either
    # direction. What the status now reports off disk is covered by
    # ``TestSetupPartsComeFromDisk`` in ``test_web_status_collector.py``.

    def test_as_dict_serializable(self, tmp_path: Path) -> None:
        """The returned ``ActionResult`` round-trips through ``as_dict``
        (handlers serialize this to JSON)."""
        from mureo.web import setup_actions

        fake = MagicMock(changed=True)
        with patch("mureo.web.setup_actions.remove_mcp_config", return_value=fake):
            result = setup_actions.remove_mureo_mcp(home=tmp_path)

        envelope = result.as_dict()
        assert envelope["status"] == "ok"


# ---------------------------------------------------------------------------
# remove_auth_hook
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveAuthHook:
    def test_returns_ok_when_remove_changed(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        fake = MagicMock(changed=True)
        with patch(
            "mureo.web.setup_actions.remove_credential_guard", return_value=fake
        ) as mock_remove:
            result = setup_actions.remove_auth_hook(home=tmp_path)

        assert result.status == "ok"
        mock_remove.assert_called_once()

    def test_returns_noop_when_not_changed(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        fake = MagicMock(changed=False)
        with patch(
            "mureo.web.setup_actions.remove_credential_guard", return_value=fake
        ):
            result = setup_actions.remove_auth_hook(home=tmp_path)

        assert result.status == "noop"

    def test_returns_error_on_exception(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_credential_guard",
            side_effect=PermissionError("readonly fs"),
        ):
            result = setup_actions.remove_auth_hook(home=tmp_path)

        assert result.status == "error"
        assert result.detail == "PermissionError"

    # The flag-flip tests that lived here are gone with the flag (#423): the
    # hook's status is now detected from the host's real hook surface, by the
    # guard's tag, on every status read.


# ---------------------------------------------------------------------------
# remove_workflow_skills
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveWorkflowSkills:
    def test_returns_ok_when_skills_removed(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        # ``remove_skills`` returns ``(count, dest)`` per signature.
        with patch(
            "mureo.web.setup_actions.remove_skills",
            return_value=(5, tmp_path / "skills"),
        ) as mock_remove:
            result = setup_actions.remove_workflow_skills(home=tmp_path)

        assert result.status == "ok"
        # Detail should communicate the removed count.
        assert result.detail is not None
        assert "5" in result.detail
        mock_remove.assert_called_once()

    def test_returns_noop_when_no_skills_present(self, tmp_path: Path) -> None:
        """When ``count == 0`` (nothing to remove), surface as ``noop``."""
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_skills",
            return_value=(0, tmp_path / "skills"),
        ):
            result = setup_actions.remove_workflow_skills(home=tmp_path)

        assert result.status == "noop"

    def test_returns_error_on_exception(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_skills",
            side_effect=FileNotFoundError("bundle missing"),
        ):
            result = setup_actions.remove_workflow_skills(home=tmp_path)

        assert result.status == "error"
        assert result.detail == "FileNotFoundError"

    # The flag-flip tests that lived here are gone with the flag (#423). One of
    # them existed only to paper over the flag drifting from disk: a *noop*
    # remove (nothing on disk to delete) still had to force the flag to False
    # because, as its docstring put it, "installed" was "already inaccurate".
    # Detecting the skills on every status read removes the class of bug those
    # tests were patching around — there is nothing left to keep in sync.


# ---------------------------------------------------------------------------
# clear_all_setup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClearAllSetup:
    def test_runs_all_individual_remove_steps(self, tmp_path: Path) -> None:
        """``clear_all_setup`` invokes mureo MCP + hook + skills wrappers
        (plus legacy commands + provider iteration). Acceptance criteria
        L132-L134."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ) as mock_mcp,
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ) as mock_hook,
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ) as mock_skills,
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=["onboard.md"],
            ),
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        mock_mcp.assert_called_once()
        mock_hook.assert_called_once()
        mock_skills.assert_called_once()
        assert isinstance(result, dict)

    def test_returns_envelope_with_per_step_status(self, tmp_path: Path) -> None:
        """The returned dict carries one entry per step (mcp / hook /
        skills / legacy / providers). Acceptance criteria L132-L134."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        # The envelope's keys cover every step the bulk action ran.
        for key in ("mureo_mcp", "auth_hook", "skills", "legacy_commands"):
            assert key in result, f"missing step {key!r} in clear_all envelope"

    def test_partial_failure_does_not_abort_chain(self, tmp_path: Path) -> None:
        """A failure in step 1 (mureo_mcp) does NOT prevent steps 2..N
        from running. Acceptance criteria L132-L134 (planner HANDOFF
        L281-L284)."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="error", detail="boom"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ) as mock_hook,
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ) as mock_skills,
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ) as mock_legacy,
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        # Step 1 errored …
        assert result["mureo_mcp"]["status"] == "error"
        # … but step 2..N all ran.
        mock_hook.assert_called_once()
        mock_skills.assert_called_once()
        mock_legacy.assert_called_once()

    def test_uncaught_exception_in_step_is_isolated(self, tmp_path: Path) -> None:
        """If a wrapper itself raises (not returning an ActionResult),
        ``clear_all_setup`` still runs subsequent steps and reports the
        exception in the envelope. Acceptance criteria L132-L134."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                side_effect=RuntimeError("unexpected"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ) as mock_hook,
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ) as mock_skills,
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        assert result["mureo_mcp"]["status"] == "error"
        mock_hook.assert_called_once()
        mock_skills.assert_called_once()

    def test_iterates_installed_official_providers(self, tmp_path: Path) -> None:
        """Bulk path enumerates installed official providers from the
        real registry (``~/.claude.json`` for Claude Code, NOT
        settings.json) and calls ``remove_provider`` for each. CTO
        decision #3, acceptance criteria L132-L134."""
        from mureo.web import setup_actions

        # Registration lives in ~/.claude.json (user scope). Seed it and
        # force the no-CLI fallback so enumeration is deterministic.
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(
            (
                '{"mcpServers": {"mureo": {"command":"python"}, '
                '"google-ads-official": {"command":"pipx"}, '
                '"meta-ads-official": {"command":"pipx"}}}'
            ),
            encoding="utf-8",
        )

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value=None,
            ),
            patch(
                "mureo.providers.config_writer.Path.home",
                return_value=tmp_path,
            ),
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
            patch(
                "mureo.web.setup_actions.remove_provider",
                return_value=ActionResult(status="ok"),
            ) as mock_remove_provider,
        ):
            setup_actions.clear_all_setup(home=tmp_path)

        called_ids = {call.args[0] for call in mock_remove_provider.call_args_list}
        # The two installed official providers are removed.
        assert "google-ads-official" in called_ids
        assert "meta-ads-official" in called_ids
        # The mureo native key is NOT routed through remove_provider —
        # it's handled by remove_mureo_mcp.
        assert "mureo" not in called_ids

    def test_does_not_touch_credentials_json(self, tmp_path: Path) -> None:
        """CTO decision #3 (planner HANDOFF L207, L250-L254): the bulk
        path MUST NOT delete or rewrite ``~/.mureo/credentials.json``."""
        from mureo.web import setup_actions

        credentials_path = tmp_path / ".mureo" / "credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        # Synthetic redacted credential payload (NOT production data).
        credentials_path.write_text(
            '{"google_ads": {"developer_token": "REDACTED"}}',
            encoding="utf-8",
        )
        pre_bytes = credentials_path.read_bytes()

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            setup_actions.clear_all_setup(home=tmp_path)

        assert credentials_path.exists()
        assert credentials_path.read_bytes() == pre_bytes

    def test_envelope_values_are_jsonable_dicts(self, tmp_path: Path) -> None:
        """Each per-step value in the envelope is an ``ActionResult.as_dict()``
        shape (status + optional detail) — handlers serialize this to
        JSON."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok", detail="installed_path"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="noop", detail="not_installed"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=["onboard.md"],
            ),
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        for value in result.values():
            # Each entry is either a dict (ActionResult.as_dict()) or a
            # list / plain dict envelope for legacy / providers.
            assert isinstance(value, (dict, list))
        # mureo_mcp specifically is the as_dict shape.
        assert result["mureo_mcp"]["status"] == "ok"

    def test_runs_with_home_none(self) -> None:
        """``home=None`` defaults to ``Path.home`` — must not crash."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            result = setup_actions.clear_all_setup(home=None)

        assert isinstance(result, dict)

    def test_passes_home_through_to_individual_steps(self, tmp_path: Path) -> None:
        """``home`` is propagated to each per-step wrapper so the
        per-step ``clear_part`` call hits the same state file."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ) as mock_mcp,
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="ok"),
            ) as mock_hook,
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ) as mock_skills,
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            setup_actions.clear_all_setup(home=tmp_path)

        for mock_fn in (mock_mcp, mock_hook, mock_skills):
            kwargs = mock_fn.call_args.kwargs
            # Implementer may pass home positionally or by kwarg; accept either.
            home_arg: Any = kwargs.get("home")
            if home_arg is None and mock_fn.call_args.args:
                home_arg = mock_fn.call_args.args[0]
            assert home_arg == tmp_path


# ---------------------------------------------------------------------------
# Signature / type contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveActionsSignatures:
    def test_remove_mureo_mcp_accepts_optional_home(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_mcp_config",
            return_value=MagicMock(changed=False),
        ):
            r1 = setup_actions.remove_mureo_mcp()
            r2 = setup_actions.remove_mureo_mcp(home=None)
            r3 = setup_actions.remove_mureo_mcp(home=tmp_path)

        for r in (r1, r2, r3):
            assert isinstance(r, ActionResult)

    def test_remove_auth_hook_accepts_optional_home(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_credential_guard",
            return_value=MagicMock(changed=False),
        ):
            r1 = setup_actions.remove_auth_hook()
            r2 = setup_actions.remove_auth_hook(home=None)
            r3 = setup_actions.remove_auth_hook(home=tmp_path)

        for r in (r1, r2, r3):
            assert isinstance(r, ActionResult)

    def test_remove_workflow_skills_accepts_optional_home(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_skills",
            return_value=(0, tmp_path / "skills"),
        ):
            r1 = setup_actions.remove_workflow_skills()
            r2 = setup_actions.remove_workflow_skills(home=None)
            r3 = setup_actions.remove_workflow_skills(home=tmp_path)

        for r in (r1, r2, r3):
            assert isinstance(r, ActionResult)

    def test_clear_all_setup_returns_dict(self) -> None:
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="noop"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            result = setup_actions.clear_all_setup(home=None)

        assert isinstance(result, dict)
