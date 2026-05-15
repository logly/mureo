"""Host-aware unit tests for ``mureo.web.setup_actions``.

Pins the ``host: str = "claude-code"`` parameter added per planner
HANDOFF ``feat-web-config-ui-phase1-desktop-host.md`` to:
``install_mureo_mcp``, ``install_auth_hook``, ``install_workflow_skills``,
``remove_mureo_mcp``, ``remove_auth_hook``, ``clear_all_setup``.

Behaviour matrix asserted (RED until the param exists):

- ``host="claude-code"`` (default) → byte-for-byte SAME behaviour as
  today (regression guards; ``install_mcp_config(scope="global")`` /
  ``install_credential_guard`` / ``install_skills`` still called, Code
  ``~/.claude/settings.json`` path).
- ``host="claude-desktop"``:
  - mcp install/remove → routed through ``mureo.web.desktop_mcp``
    (writes ``claude_desktop_config.json``, NOT ``settings.json``);
  - auth_hook install/remove → ``ActionResult(status="noop",
    detail="unsupported_on_desktop")``, NOTHING written,
    ``install_credential_guard`` / ``remove_credential_guard`` NOT
    called, ``PART_HOOK`` state NOT marked/cleared;
  - skills → host-agnostic (still ``~/.claude/skills``).
- ``clear_all_setup(host="claude-desktop")`` symmetric; never touches
  ``~/.mureo/credentials.json``.

All FS via ``tmp_path``; ``platform.system`` monkeypatched where the
Desktop path needs Darwin vs non-Darwin. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mureo.web.setup_actions import ActionResult


def _desktop_cfg(tmp_path: Path) -> Path:
    return (
        tmp_path
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


# ---------------------------------------------------------------------------
# install_mureo_mcp — host matrix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallMureoMcpHost:
    def test_code_host_default_unchanged(self, tmp_path: Path) -> None:
        """Regression guard: default host delegates to
        ``install_mcp_config(scope="global")`` exactly as today."""
        from mureo.web import setup_actions

        with patch(
            "mureo.auth_setup.install_mcp_config",
            return_value="/p/.claude/settings.json",
        ) as mock_cfg:
            result = setup_actions.install_mureo_mcp(home=tmp_path)

        assert result.status == "ok"
        mock_cfg.assert_called_once_with(scope="global")

    def test_code_host_explicit_unchanged(self, tmp_path: Path) -> None:
        """Explicit ``host="claude-code"`` is identical to the default."""
        from mureo.web import setup_actions

        with patch(
            "mureo.auth_setup.install_mcp_config", return_value=None
        ) as mock_cfg:
            result = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-code"
            )

        assert result.status == "noop"
        assert result.detail == "already_configured"
        mock_cfg.assert_called_once_with(scope="global")

    def test_desktop_host_writes_desktop_config_darwin(
        self, tmp_path: Path
    ) -> None:
        """``host="claude-desktop"`` on macOS writes the Desktop config
        (``mcpServers.mureo``), NOT ``settings.json``."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.auth_setup.install_mcp_config",
                side_effect=AssertionError("Code path must NOT run on Desktop"),
            ),
        ):
            result = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "mureo" in payload["mcpServers"]
        # The Code settings.json must NOT have been written.
        assert not (tmp_path / ".claude" / "settings.json").exists()

    def test_desktop_host_already_configured_is_noop(
        self, tmp_path: Path
    ) -> None:
        """An existing Desktop ``mureo`` entry → ``noop already_configured``;
        file unchanged."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "old"}}}),
            encoding="utf-8",
        )
        before = cfg.read_bytes()

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "noop"
        assert result.detail == "already_configured"
        assert cfg.read_bytes() == before

    def test_desktop_host_preserves_other_servers(
        self, tmp_path: Path
    ) -> None:
        """A pre-existing non-mureo Desktop server + unrelated top-level
        key survive the Desktop install."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps(
                {
                    "mcpServers": {"other": {"command": "node"}},
                    "theme": "dark",
                }
            ),
            encoding="utf-8",
        )

        with patch.object(platform, "system", return_value="Darwin"):
            setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert payload["mcpServers"]["other"] == {"command": "node"}
        assert payload["theme"] == "dark"
        assert "mureo" in payload["mcpServers"]

    def test_desktop_host_corrupt_config_returns_error(
        self, tmp_path: Path
    ) -> None:
        """Corrupt Desktop config → ``status="error"`` (degrades, no
        500); original file untouched."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("{ not json", encoding="utf-8")
        before = cfg.read_bytes()

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "error"
        assert cfg.read_bytes() == before

    def test_desktop_host_non_darwin_falls_back_no_raise(
        self, tmp_path: Path
    ) -> None:
        """Non-macOS + Desktop → host_paths fallback to
        ``<home>/.claude/settings.json``; no unsupported-platform error,
        mureo block present (acceptance criteria L23 / L118)."""
        from mureo.web import setup_actions

        with patch.object(platform, "system", return_value="Linux"):
            result = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status in {"ok", "noop"}
        fallback = tmp_path / ".claude" / "settings.json"
        payload = json.loads(fallback.read_text(encoding="utf-8"))
        assert "mureo" in payload["mcpServers"]


# ---------------------------------------------------------------------------
# install_auth_hook — unsupported on Desktop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallAuthHookHost:
    def test_code_host_default_unchanged(self, tmp_path: Path) -> None:
        """Regression guard: default host still calls
        ``install_credential_guard``."""
        from mureo.web import setup_actions

        with patch(
            "mureo.auth_setup.install_credential_guard",
            return_value="/p/.claude/settings.json",
        ) as mock_guard:
            result = setup_actions.install_auth_hook(home=tmp_path)

        assert result.status == "ok"
        mock_guard.assert_called_once()

    def test_desktop_host_returns_noop_unsupported(
        self, tmp_path: Path
    ) -> None:
        """``host="claude-desktop"`` → ``noop`` /
        ``detail="unsupported_on_desktop"``."""
        from mureo.web import setup_actions

        with patch(
            "mureo.auth_setup.install_credential_guard"
        ) as mock_guard:
            result = setup_actions.install_auth_hook(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "noop"
        assert result.detail == "unsupported_on_desktop"
        mock_guard.assert_not_called()

    def test_desktop_host_writes_no_file(self, tmp_path: Path) -> None:
        """The Desktop auth-hook branch touches no file at all."""
        from mureo.web import setup_actions

        before = sorted(p.name for p in tmp_path.rglob("*"))
        setup_actions.install_auth_hook(home=tmp_path, host="claude-desktop")
        after = sorted(p.name for p in tmp_path.rglob("*"))

        assert before == after

    def test_desktop_host_does_not_mark_part_hook(
        self, tmp_path: Path
    ) -> None:
        """Desktop hook is a no-op so ``PART_HOOK`` must NOT be marked
        installed (dashboard must show "not applicable", not "installed").
        Planner HANDOFF Q2 / risk L146."""
        from mureo.web import setup_actions
        from mureo.web.setup_state import read_setup_state

        setup_actions.install_auth_hook(home=tmp_path, host="claude-desktop")

        assert read_setup_state(home=tmp_path).auth_hook is False


# ---------------------------------------------------------------------------
# install_workflow_skills — host-agnostic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallWorkflowSkillsHost:
    def test_code_host_default_unchanged(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.cli.setup_cmd.install_skills",
            return_value=(7, tmp_path / ".claude" / "skills"),
        ) as mock_skills:
            result = setup_actions.install_workflow_skills(home=tmp_path)

        assert result.status == "ok"
        mock_skills.assert_called_once()

    def test_desktop_host_same_dir_and_count_as_code(
        self, tmp_path: Path
    ) -> None:
        """Skills behaviour is identical for both hosts (shared
        ``~/.claude/skills`` — planner HANDOFF Q3)."""
        from mureo.web import setup_actions

        dest = tmp_path / ".claude" / "skills"
        with patch(
            "mureo.cli.setup_cmd.install_skills", return_value=(7, dest)
        ) as mock_code:
            code_result = setup_actions.install_workflow_skills(
                home=tmp_path, host="claude-code"
            )
        with patch(
            "mureo.cli.setup_cmd.install_skills", return_value=(7, dest)
        ) as mock_desktop:
            desktop_result = setup_actions.install_workflow_skills(
                home=tmp_path, host="claude-desktop"
            )

        assert code_result.as_dict() == desktop_result.as_dict()
        mock_code.assert_called_once()
        mock_desktop.assert_called_once()


# ---------------------------------------------------------------------------
# remove_mureo_mcp — host matrix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveMureoMcpHost:
    def test_code_host_default_unchanged(self, tmp_path: Path) -> None:
        """Regression guard: default host delegates to
        ``remove_mcp_config`` exactly as today."""
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_mcp_config",
            return_value=MagicMock(changed=True),
        ) as mock_remove:
            result = setup_actions.remove_mureo_mcp(home=tmp_path)

        assert result.status == "ok"
        mock_remove.assert_called_once()

    def test_desktop_host_removes_only_mureo_preserves_others(
        self, tmp_path: Path
    ) -> None:
        """Desktop remove drops only ``mureo`` from
        ``claude_desktop_config.json``; ``other`` survives."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "mureo": {"command": "x"},
                        "other": {"command": "node"},
                    }
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.web.setup_actions.remove_mcp_config",
                side_effect=AssertionError("Code remove must NOT run on Desktop"),
            ),
        ):
            result = setup_actions.remove_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "ok"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        assert "mureo" not in payload["mcpServers"]
        assert payload["mcpServers"]["other"] == {"command": "node"}

    def test_desktop_host_idempotent_noop_when_absent(
        self, tmp_path: Path
    ) -> None:
        """Second Desktop remove (mureo already gone) → ``noop``."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"other": {"command": "node"}}}),
            encoding="utf-8",
        )

        with patch.object(platform, "system", return_value="Darwin"):
            result = setup_actions.remove_mureo_mcp(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "noop"


# ---------------------------------------------------------------------------
# remove_auth_hook — unsupported on Desktop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveAuthHookHost:
    def test_code_host_default_unchanged(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_credential_guard",
            return_value=MagicMock(changed=True),
        ) as mock_remove:
            result = setup_actions.remove_auth_hook(home=tmp_path)

        assert result.status == "ok"
        mock_remove.assert_called_once()

    def test_desktop_host_returns_noop_unsupported(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_credential_guard"
        ) as mock_remove:
            result = setup_actions.remove_auth_hook(
                home=tmp_path, host="claude-desktop"
            )

        assert result.status == "noop"
        assert result.detail == "unsupported_on_desktop"
        mock_remove.assert_not_called()

    def test_desktop_host_touches_no_file(self, tmp_path: Path) -> None:
        from mureo.web import setup_actions

        before = sorted(p.name for p in tmp_path.rglob("*"))
        setup_actions.remove_auth_hook(home=tmp_path, host="claude-desktop")
        after = sorted(p.name for p in tmp_path.rglob("*"))

        assert before == after


# ---------------------------------------------------------------------------
# clear_all_setup — host-aware symmetry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClearAllSetupHost:
    def test_code_host_envelope_unchanged(self, tmp_path: Path) -> None:
        """Regression guard: default host produces the same envelope
        keys / per-step dispatch as before the change."""
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
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            result = setup_actions.clear_all_setup(home=tmp_path)

        for key in ("mureo_mcp", "auth_hook", "skills", "legacy_commands", "providers"):
            assert key in result
        mock_mcp.assert_called_once()
        mock_hook.assert_called_once()

    def test_desktop_host_propagates_host_to_mcp_and_hook(
        self, tmp_path: Path
    ) -> None:
        """``clear_all_setup(host="claude-desktop")`` passes
        ``host="claude-desktop"`` into the per-step mcp + hook removers."""
        from mureo.web import setup_actions

        with (
            patch(
                "mureo.web.setup_actions.remove_mureo_mcp",
                return_value=ActionResult(status="ok"),
            ) as mock_mcp,
            patch(
                "mureo.web.setup_actions.remove_auth_hook",
                return_value=ActionResult(
                    status="noop", detail="unsupported_on_desktop"
                ),
            ) as mock_hook,
            patch(
                "mureo.web.setup_actions.remove_workflow_skills",
                return_value=ActionResult(status="ok"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            setup_actions.clear_all_setup(
                home=tmp_path, host="claude-desktop"
            )

        for mock_fn in (mock_mcp, mock_hook):
            kwargs = mock_fn.call_args.kwargs
            assert kwargs.get("host") == "claude-desktop"

    def test_desktop_host_auth_hook_step_is_noop_unsupported(
        self, tmp_path: Path
    ) -> None:
        """End-to-end (only the leaf primitives mocked): on Desktop the
        ``auth_hook`` envelope entry is ``noop unsupported_on_desktop``
        and ``remove_credential_guard`` is never called."""
        from mureo.web import setup_actions

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "x"}}}),
            encoding="utf-8",
        )

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.web.setup_actions.remove_credential_guard"
            ) as mock_guard,
            patch(
                "mureo.web.setup_actions.remove_skills",
                return_value=(0, tmp_path / ".claude" / "skills"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            envelope = setup_actions.clear_all_setup(
                home=tmp_path, host="claude-desktop"
            )

        assert envelope["auth_hook"]["status"] == "noop"
        assert envelope["auth_hook"]["detail"] == "unsupported_on_desktop"
        mock_guard.assert_not_called()

    def test_desktop_host_never_touches_credentials_json(
        self, tmp_path: Path
    ) -> None:
        """CTO decision #3 holds on the Desktop bulk path too."""
        from mureo.web import setup_actions

        creds = tmp_path / ".mureo" / "credentials.json"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text('{"google_ads": {"developer_token": "X"}}', "utf-8")
        before = creds.read_bytes()

        cfg = _desktop_cfg(tmp_path)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "x"}}}),
            encoding="utf-8",
        )

        with (
            patch.object(platform, "system", return_value="Darwin"),
            patch(
                "mureo.web.setup_actions.remove_credential_guard"
            ),
            patch(
                "mureo.web.setup_actions.remove_skills",
                return_value=(0, tmp_path / ".claude" / "skills"),
            ),
            patch(
                "mureo.web.setup_actions.remove_legacy_commands",
                return_value=[],
            ),
        ):
            setup_actions.clear_all_setup(
                home=tmp_path, host="claude-desktop"
            )

        assert creds.exists()
        assert creds.read_bytes() == before


# ---------------------------------------------------------------------------
# Signature / back-compat contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostParamSignatures:
    def test_install_mureo_mcp_accepts_host_kwarg(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.auth_setup.install_mcp_config", return_value=None
        ):
            r1 = setup_actions.install_mureo_mcp(home=tmp_path)
            r2 = setup_actions.install_mureo_mcp(
                home=tmp_path, host="claude-code"
            )

        assert isinstance(r1, ActionResult)
        assert isinstance(r2, ActionResult)

    def test_remove_mureo_mcp_accepts_host_kwarg(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import setup_actions

        with patch(
            "mureo.web.setup_actions.remove_mcp_config",
            return_value=MagicMock(changed=False),
        ):
            r = setup_actions.remove_mureo_mcp(
                home=tmp_path, host="claude-code"
            )

        assert isinstance(r, ActionResult)

    def test_clear_all_setup_accepts_host_kwarg(
        self, tmp_path: Path
    ) -> None:
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
            result = setup_actions.clear_all_setup(
                home=tmp_path, host="claude-code"
            )

        assert isinstance(result, dict)
