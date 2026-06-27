"""Tests for ``mureo.web.codex_mcp`` — the Codex ``config.toml`` writer.

Codex stores MCP servers as TOML; this module manages tagged
``[mcp_servers.<id>]`` regions surgically, preserving every other byte of
the operator's file (mirrors the JSON ``desktop_mcp`` surface for parity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mureo.web import codex_mcp as cx

if TYPE_CHECKING:
    from pathlib import Path


def _cfg(tmp_path: Path) -> Path:
    return tmp_path / ".codex" / "config.toml"


@pytest.mark.unit
def test_resolve_config_path_is_home_aware(tmp_path: Path) -> None:
    assert cx.resolve_codex_config_path(tmp_path) == tmp_path / ".codex" / "config.toml"


@pytest.mark.unit
def test_install_mcp_block_then_idempotent(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"]) is True
    text = cfg.read_text()
    assert "[mcp_servers.mureo]" in text
    assert 'args = ["-m", "mureo.mcp"]' in text
    # Presence-based idempotency: a second install is a no-op.
    assert cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"]) is False


@pytest.mark.unit
def test_install_server_block_preserves_user_content(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '# my notes\n[mcp_servers.other]\ncommand = "foo"\n', encoding="utf-8"
    )
    cx.install_codex_server_block(
        cfg, "google-ads-official", {"command": "uvx", "args": ["x"], "env": {"K": "v"}}
    )
    text = cfg.read_text()
    assert "# my notes" in text
    assert "[mcp_servers.other]" in text  # untouched
    assert "[mcp_servers.google-ads-official]" in text
    assert "[mcp_servers.google-ads-official.env]" in text
    assert 'K = "v"' in text


@pytest.mark.unit
def test_install_server_block_idempotent_on_identical(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    block = {"command": "uvx", "args": ["a"], "env": {"K": "v"}}
    assert cx.install_codex_server_block(cfg, "p", block) is True
    assert cx.install_codex_server_block(cfg, "p", dict(block)) is False


@pytest.mark.unit
def test_install_server_block_replaces_changed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cx.install_codex_server_block(cfg, "p", {"command": "old", "args": []})
    assert (
        cx.install_codex_server_block(cfg, "p", {"command": "new", "args": []}) is True
    )
    text = cfg.read_text()
    assert 'command = "new"' in text
    assert "old" not in text
    # Exactly one region for "p".
    assert text.count("# >>> mureo-mcp:p >>>") == 1


@pytest.mark.unit
def test_untagged_block_raises_conflict(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[mcp_servers.mureo]\ncommand = "x"\n', encoding="utf-8")
    with pytest.raises(cx.CodexConfigConflictError):
        cx.install_codex_server_block(cfg, "mureo", {"command": "y", "args": []})


@pytest.mark.unit
def test_untagged_subtable_not_a_conflict(tmp_path: Path) -> None:
    """``[mcp_servers.mureo.env]`` is a sub-table, not the block header —
    it must not be mistaken for an untagged conflicting block."""
    cfg = _cfg(tmp_path)
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])
    # Re-render via set-env touches the sub-table; no conflict raised.
    assert cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_GOOGLE") is True


@pytest.mark.unit
def test_set_and_unset_disable_env_preserve_others(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])
    assert cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_GOOGLE") is True
    assert cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_GOOGLE") is False  # idem
    assert cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_META") is True
    env = cx.read_codex_server_env(cfg, "mureo")
    assert env == {"MUREO_DISABLE_GOOGLE": "1", "MUREO_DISABLE_META": "1"}
    # command/args survive the env re-render.
    assert 'args = ["-m", "mureo.mcp"]' in cfg.read_text()
    # Unsetting one keeps the other.
    assert cx.unset_mureo_disable_env_codex(cfg, "MUREO_DISABLE_META") is True
    assert cx.read_codex_server_env(cfg, "mureo") == {"MUREO_DISABLE_GOOGLE": "1"}


@pytest.mark.unit
def test_set_disable_env_noop_without_mureo_block(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# empty\n", encoding="utf-8")
    assert cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_GOOGLE") is False


@pytest.mark.unit
def test_remove_block_idempotent_and_preserves_user_content(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# keep me\n", encoding="utf-8")
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])
    assert cx.remove_codex_mcp_block(cfg) is True
    assert cx.remove_codex_mcp_block(cfg) is False  # idempotent
    assert "# keep me" in cfg.read_text()
    assert "mcp_servers.mureo" not in cfg.read_text()


@pytest.mark.unit
def test_installed_ids_and_is_installed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert cx.installed_codex_server_ids(cfg) == set()  # missing file
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])
    cx.install_codex_server_block(cfg, "ga4-official", {"command": "g", "args": []})
    assert cx.installed_codex_server_ids(cfg) == {"mureo", "ga4-official"}
    assert cx.is_codex_server_installed(cfg, "ga4-official") is True
    assert cx.is_codex_server_installed(cfg, "absent") is False


@pytest.mark.unit
def test_toml_string_escaping_roundtrips(tmp_path: Path) -> None:
    """A value with quotes/backslashes survives render → parse."""
    cfg = _cfg(tmp_path)
    cx.install_codex_mcp_block(cfg, 'C:\\Program Files\\py "x"', ["-m", "mureo.mcp"])
    # The mureo block parses back to the exact command via read of args/env
    # path (command parsing is exercised indirectly by the env re-render
    # preserving it). Assert the rendered TOML escaped the quotes/backslash.
    text = cfg.read_text()
    assert '\\"x\\"' in text
    assert "\\\\" in text


@pytest.mark.unit
def test_windows_command_survives_env_retoggle(tmp_path: Path) -> None:
    """Regression: a backslash command (Windows ``sys.executable``) must NOT
    be corrupted when the mureo region is re-rendered by an env toggle —
    chained-replace unescaping used to turn ``C:\\nina`` into ``C:<NL>ina``,
    producing invalid TOML that breaks the whole file."""
    cfg = _cfg(tmp_path)
    win_cmd = r"C:\Users\nina\Programs\python.exe"
    cx.install_codex_mcp_block(cfg, win_cmd, ["-m", "mureo.mcp"])
    cx.set_mureo_disable_env_codex(cfg, "MUREO_DISABLE_GOOGLE")
    text = cfg.read_text()
    # The command line must not contain a raw newline (which would be
    # invalid TOML for a basic string).
    command_line = next(ln for ln in text.splitlines() if ln.startswith("command = "))
    assert "\n" not in command_line  # trivially true post-split; documents intent
    span = cx._region_span(text, "mureo")
    assert span is not None
    block = cx._parse_region(text[span[0] : span[1]], "mureo")
    assert block["command"] == win_cmd  # round-trip lossless
    assert block["args"] == ["-m", "mureo.mcp"]


@pytest.mark.unit
def test_remove_preserves_operator_blank_lines_elsewhere(tmp_path: Path) -> None:
    """Region removal tidies only its own seam — an operator's intentional
    multi-blank-line spacing elsewhere is preserved verbatim."""
    cfg = _cfg(tmp_path)
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "[a]\nx = 1\n\n\n\n[b]\ny = 2\n", encoding="utf-8"
    )  # 3 blank lines between [a] and [b]
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])  # appended at end
    assert cx.remove_codex_mcp_block(cfg) is True
    # The operator's 3-blank-line gap is untouched.
    assert "[a]\nx = 1\n\n\n\n[b]\ny = 2\n" in cfg.read_text()


@pytest.mark.unit
def test_remove_middle_region_collapses_only_its_seam(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cx.install_codex_mcp_block(cfg, "python", ["-m", "mureo.mcp"])
    cx.install_codex_server_block(cfg, "ga4-official", {"command": "g", "args": []})
    # Remove the FIRST (now middle) region.
    cx.remove_codex_mcp_block(cfg)
    text = cfg.read_text()
    assert "\n\n\n" not in text  # no 3+ newline run left at the seam
    assert "[mcp_servers.ga4-official]" in text  # the other region intact
