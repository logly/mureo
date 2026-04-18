"""Tests for ``mureo setup gemini``.

Gemini CLI uses the extension directory structure:
``~/.gemini/extensions/<ext-name>/gemini-extension.json``. mureo
registers itself as one extension with MCP config + contextFileName.
No hooks, no commands (Gemini uses .toml which is out of scope for
this PR).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Module under test does not exist yet — drives RED.
from mureo.cli.setup_gemini import install_gemini_extension  # noqa: I001


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class TestInstallGeminiExtension:
    def test_creates_extension_manifest(self, home: Path) -> None:
        result = install_gemini_extension()
        assert result is not None
        manifest = home / ".gemini" / "extensions" / "mureo" / "gemini-extension.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))

        assert data["name"] == "mureo"
        assert "version" in data
        assert data["contextFileName"] == "CONTEXT.md"

        mcp = data.get("mcpServers", {})
        assert "mureo" in mcp
        assert mcp["mureo"]["command"] == "python"
        assert mcp["mureo"]["args"] == ["-m", "mureo.mcp"]

    def test_updates_stale_version_and_mcp(self, home: Path) -> None:
        manifest = home / ".gemini" / "extensions" / "mureo" / "gemini-extension.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "mureo", "version": "0.0.0-stale"}),
            encoding="utf-8",
        )

        install_gemini_extension()

        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["version"] != "0.0.0-stale"
        assert data["mcpServers"]["mureo"]["command"] == "python"

    def test_preserves_operator_added_fields(self, home: Path) -> None:
        """Unknown top-level keys and extra mcpServers entries survive reinstall."""
        manifest = home / ".gemini" / "extensions" / "mureo" / "gemini-extension.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "name": "mureo",
                    "version": "0.0.0-stale",
                    "contextFileName": "CUSTOM.md",
                    "excludeTools": ["google_ads.budgets.update"],
                    "mcpServers": {
                        "mureo": {"command": "old"},
                        "other": {"command": "other-server"},
                    },
                }
            ),
            encoding="utf-8",
        )

        install_gemini_extension()

        data = json.loads(manifest.read_text(encoding="utf-8"))
        # Operator's rename of the context file is kept.
        assert data["contextFileName"] == "CUSTOM.md"
        # Operator's allow/deny list is untouched.
        assert data["excludeTools"] == ["google_ads.budgets.update"]
        # mureo's mcpServers.mureo is refreshed, but extra servers survive.
        assert data["mcpServers"]["mureo"]["command"] == "python"
        assert data["mcpServers"]["other"] == {"command": "other-server"}

    def test_does_not_touch_other_extensions(self, home: Path) -> None:
        other = home / ".gemini" / "extensions" / "other-ext" / "gemini-extension.json"
        other.parent.mkdir(parents=True)
        other.write_text(
            json.dumps({"name": "other-ext", "version": "1.0.0"}),
            encoding="utf-8",
        )

        install_gemini_extension()

        data = json.loads(other.read_text(encoding="utf-8"))
        assert data == {"name": "other-ext", "version": "1.0.0"}

    def test_manifest_is_valid_json_with_trailing_newline(self, home: Path) -> None:
        install_gemini_extension()
        manifest = home / ".gemini" / "extensions" / "mureo" / "gemini-extension.json"
        text = manifest.read_text(encoding="utf-8")
        # JSON roundtrip works
        json.loads(text)
        # Conventional trailing newline
        assert text.endswith("\n")
