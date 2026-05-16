"""Unit tests for ``mureo.providers.config_writer``.

Pins the atomic JSON merge / remove / idempotency behavior for
``~/.claude/settings.json``. The mureo-native ``mcpServers.mureo`` entry
must be preserved across operations (coexistence safety). See planner
HANDOFF ``feat-providers-cli-phase1.md``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _make_spec(
    *,
    spec_id: str = "google-ads-official",
    mcp_server_config: dict[str, Any] | None = None,
) -> Any:
    """Build a real ``ProviderSpec`` for config-writer tests."""
    from mureo.providers.catalog import ProviderSpec

    if mcp_server_config is None:
        mcp_server_config = {"command": "pipx", "args": ["run", "google-ads-mcp"]}

    return ProviderSpec(
        id=spec_id,
        display_name=spec_id,
        install_kind="pipx",
        install_argv=("pipx", "run", "google-ads-mcp"),
        mcp_server_config=mcp_server_config,
        required_env=(),
        notes="",
        coexists_with_mureo_platform=None,
    )


@pytest.mark.unit
def test_add_provider_creates_settings_file_when_absent(tmp_path: Path) -> None:
    """The file (and its parent dir) are created from scratch on first write."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()

    result = add_provider_to_claude_settings(spec, settings_path=settings_path)

    assert settings_path.exists()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    # Stdio entries are normalized with the required transport ``type``
    # (Claude Code's mcp schema rejects a typeless stdio entry).
    assert payload["mcpServers"][spec.id] == {
        "type": "stdio",
        **dict(spec.mcp_server_config),
    }
    assert result.changed is True


@pytest.mark.unit
def test_add_provider_preserves_existing_mureo_block(tmp_path: Path) -> None:
    """Adding an official provider must not drop the native ``mureo`` entry."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]},
                }
            }
        ),
        encoding="utf-8",
    )

    spec = _make_spec()
    add_provider_to_claude_settings(spec, settings_path=settings_path)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "mureo" in payload["mcpServers"]
    assert spec.id in payload["mcpServers"]


@pytest.mark.unit
def test_add_provider_preserves_unrelated_top_level_keys(tmp_path: Path) -> None:
    """Top-level keys other than ``mcpServers`` survive verbatim."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "mcpServers": {"mureo": {"command": "python", "args": ["-m", "mureo.mcp"]}},
    }
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    add_provider_to_claude_settings(_make_spec(), settings_path=settings_path)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["permissions"] == original["permissions"]


@pytest.mark.unit
def test_add_provider_idempotent(tmp_path: Path) -> None:
    """A second add returns ``changed=False`` and yields byte-equal output."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()

    first = add_provider_to_claude_settings(spec, settings_path=settings_path)
    first_bytes = settings_path.read_bytes()

    second = add_provider_to_claude_settings(spec, settings_path=settings_path)
    second_bytes = settings_path.read_bytes()

    assert first.changed is True
    assert second.changed is False
    assert first_bytes == second_bytes


@pytest.mark.unit
def test_add_provider_injects_extra_env(tmp_path: Path) -> None:
    """``extra_env`` is written into the provider block's ``env``.

    Without this the official upstream MCP (which reads ONLY env vars,
    never mureo's credentials.json) starts with zero credentials and is
    unusable despite being "registered" — the exact reported bug.
    """
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()

    result = add_provider_to_claude_settings(
        spec,
        settings_path=settings_path,
        extra_env={"GOOGLE_ADS_DEVELOPER_TOKEN": "DT", "GOOGLE_ADS_CLIENT_ID": "C"},
    )

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["mcpServers"][spec.id] == {
        "type": "stdio",
        **dict(spec.mcp_server_config),
        "env": {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT", "GOOGLE_ADS_CLIENT_ID": "C"},
    }
    assert result.changed is True


@pytest.mark.unit
def test_add_provider_extra_env_idempotent(tmp_path: Path) -> None:
    """Re-adding with the same ``extra_env`` is a byte-equal no-op."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()
    env = {"GOOGLE_ADS_REFRESH_TOKEN": "RT"}

    first = add_provider_to_claude_settings(
        spec, settings_path=settings_path, extra_env=env
    )
    first_bytes = settings_path.read_bytes()
    second = add_provider_to_claude_settings(
        spec, settings_path=settings_path, extra_env=env
    )

    assert first.changed is True
    assert second.changed is False
    assert first_bytes == settings_path.read_bytes()


@pytest.mark.unit
def test_add_provider_empty_extra_env_writes_no_env_key(tmp_path: Path) -> None:
    """An empty/omitted ``extra_env`` keeps the pre-fix bare-block shape."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()

    add_provider_to_claude_settings(spec, settings_path=settings_path, extra_env={})

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "env" not in payload["mcpServers"][spec.id]


@pytest.mark.unit
def test_add_provider_idempotent_with_real_catalog_spec(tmp_path: Path) -> None:
    """A re-add of the real frozen catalog spec returns ``changed=False``.

    Regression guard for the iter-1 ``_freeze_config`` migration: the real
    catalog payload's ``args`` field is a ``tuple`` (nested-list → tuple via
    ``_freeze_config``), but the on-disk JSON round-trip deserializes it as
    a ``list``. The idempotency check must compare values that have been
    normalized to JSON-shape so the equality holds; otherwise the writer
    rewrites the file on every invocation, violating both the docstring
    contract and the atomic-write durability budget.
    """
    from mureo.providers.catalog import get_provider
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = get_provider("google-ads-official")

    first = add_provider_to_claude_settings(spec, settings_path=settings_path)
    second = add_provider_to_claude_settings(spec, settings_path=settings_path)

    assert first.changed is True
    assert second.changed is False


@pytest.mark.unit
def test_add_provider_writes_atomically(tmp_path: Path) -> None:
    """The writer uses a ``.tmp`` file in the same dir + ``os.replace``."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    spec = _make_spec()

    captured: dict[str, Any] = {}
    real_replace = os.replace

    def _spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        captured["src"] = os.fspath(src)
        captured["dst"] = os.fspath(dst)
        real_replace(src, dst)

    with patch("mureo.providers.config_writer.os.replace", side_effect=_spy_replace):
        add_provider_to_claude_settings(spec, settings_path=settings_path)

    src = Path(captured["src"])
    dst = Path(captured["dst"])
    assert dst == settings_path
    assert src.parent == settings_path.parent
    assert ".tmp" in src.name


@pytest.mark.unit
def test_add_provider_does_not_leak_tmp_file_on_success(tmp_path: Path) -> None:
    """No ``*.tmp*`` debris remains after a successful write."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    spec = _make_spec()

    add_provider_to_claude_settings(spec, settings_path=settings_path)

    leftovers = list(settings_path.parent.glob("*.tmp*"))
    assert leftovers == []


@pytest.mark.unit
def test_add_provider_cleans_up_tmp_file_on_write_failure(tmp_path: Path) -> None:
    """If ``os.replace`` raises, the tmp file is unlinked + original intact."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    pre_existing = {"mcpServers": {"mureo": {"command": "python"}}}
    settings_path.write_text(json.dumps(pre_existing), encoding="utf-8")
    pre_bytes = settings_path.read_bytes()

    spec = _make_spec()

    def _boom(src: Any, dst: Any) -> None:
        raise OSError("simulated atomic replace failure")

    with (
        patch("mureo.providers.config_writer.os.replace", side_effect=_boom),
        pytest.raises(OSError),
    ):
        add_provider_to_claude_settings(spec, settings_path=settings_path)

    leftovers = list(settings_path.parent.glob("*.tmp*"))
    assert leftovers == []
    assert settings_path.read_bytes() == pre_bytes


@pytest.mark.unit
def test_remove_provider_pops_key(tmp_path: Path) -> None:
    """Removing one of two entries leaves the other intact."""
    from mureo.providers.config_writer import remove_provider_from_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mureo": {"command": "python"},
                    "google-ads-official": {"command": "pipx"},
                }
            }
        ),
        encoding="utf-8",
    )

    result = remove_provider_from_claude_settings(
        "google-ads-official", settings_path=settings_path
    )

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "google-ads-official" not in payload["mcpServers"]
    assert "mureo" in payload["mcpServers"]
    assert result.changed is True


@pytest.mark.unit
def test_remove_provider_noop_when_absent(tmp_path: Path) -> None:
    """Removing a missing key returns ``changed=False`` without error."""
    from mureo.providers.config_writer import remove_provider_from_claude_settings

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"mcpServers": {"mureo": {"command": "python"}}}),
        encoding="utf-8",
    )

    result = remove_provider_from_claude_settings(
        "nonexistent", settings_path=settings_path
    )

    assert result.changed is False


@pytest.mark.unit
def test_is_provider_installed_true_false(tmp_path: Path) -> None:
    """Read-only check: present/absent/missing-file/malformed all handled."""
    from mureo.providers.config_writer import is_provider_installed

    settings_path = tmp_path / ".claude" / "settings.json"
    assert (
        is_provider_installed("google-ads-official", settings_path=settings_path)
        is False
    )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"mcpServers": {"google-ads-official": {"command": "pipx"}}}),
        encoding="utf-8",
    )
    assert (
        is_provider_installed("google-ads-official", settings_path=settings_path)
        is True
    )
    assert (
        is_provider_installed("meta-ads-official", settings_path=settings_path) is False
    )

    # Malformed JSON does not raise — surface as False so ``list`` keeps working.
    settings_path.write_text("{not valid json", encoding="utf-8")
    assert (
        is_provider_installed("google-ads-official", settings_path=settings_path)
        is False
    )


@pytest.mark.unit
def test_add_provider_handles_malformed_existing_json(tmp_path: Path) -> None:
    """Malformed JSON is refused with ``ConfigWriteError`` naming the path."""
    from mureo.providers.config_writer import (
        ConfigWriteError,
        add_provider_to_claude_settings,
    )

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("{this is not json", encoding="utf-8")

    with pytest.raises(ConfigWriteError) as exc_info:
        add_provider_to_claude_settings(_make_spec(), settings_path=settings_path)

    assert str(settings_path) in str(exc_info.value)


@pytest.mark.unit
def test_add_provider_refuses_when_mcp_servers_is_not_dict(tmp_path: Path) -> None:
    """A non-object ``mcpServers`` value triggers ``ConfigWriteError``.

    We refuse to silently clobber a corrupted ``mcpServers`` entry the same
    way we refuse to clobber malformed top-level JSON — both paths must
    protect user data instead of overwriting it.
    """
    from mureo.providers.config_writer import (
        ConfigWriteError,
        add_provider_to_claude_settings,
    )

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"mcpServers": ["not", "a", "dict"]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigWriteError) as exc_info:
        add_provider_to_claude_settings(_make_spec(), settings_path=settings_path)

    msg = str(exc_info.value)
    assert str(settings_path) in msg
    assert "mcpServers" in msg
    assert "list" in msg


@pytest.mark.unit
def test_add_provider_tmp_file_is_mode_0600(tmp_path: Path) -> None:
    """The same-directory tmp file used for atomic replace is 0o600 before rename.

    Spying on ``os.replace`` lets us inspect the tmp file's mode while it
    exists. Skipped on platforms without POSIX file modes.
    """
    import stat
    from unittest.mock import patch

    from mureo.providers.config_writer import add_provider_to_claude_settings

    if os.name != "posix":
        pytest.skip("file-mode check only meaningful on POSIX")

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Any] = {}
    real_replace = os.replace

    def _spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        captured["mode"] = stat.S_IMODE(os.stat(src).st_mode)
        real_replace(src, dst)

    with patch("mureo.providers.config_writer.os.replace", side_effect=_spy_replace):
        add_provider_to_claude_settings(_make_spec(), settings_path=settings_path)

    assert captured["mode"] == 0o600


@pytest.mark.unit
def test_settings_path_default_is_claude_json_when_no_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``claude`` binary → fallback target is ``~/.claude.json`` root
    ``mcpServers`` (NOT settings.json — never read for MCP discovery)."""
    from mureo.providers.config_writer import add_provider_to_claude_settings

    monkeypatch.setattr(
        "mureo.providers.config_writer.shutil.which", lambda _: None
    )
    monkeypatch.setattr(
        "mureo.providers.config_writer.Path.home", lambda: tmp_path
    )

    spec = _make_spec()
    add_provider_to_claude_settings(spec)

    expected = tmp_path / ".claude.json"
    assert expected.exists()
    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert spec.id in payload["mcpServers"]


@pytest.mark.unit
class TestProviderClaudeCli:
    """Default (no ``settings_path``) delegates to the ``claude`` CLI."""

    def test_add_via_cli_self_heals(self) -> None:
        from types import SimpleNamespace

        from mureo.providers.config_writer import (
            AddResult,
            add_provider_to_claude_settings,
        )

        calls: list[list[str]] = []

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = add_provider_to_claude_settings(_make_spec())

        assert result == AddResult(changed=True)
        assert calls[0][1:3] == ["mcp", "remove"]  # self-heal first
        add = calls[1]
        assert add[1:3] == ["mcp", "add-json"]
        assert add[3] == "google-ads-official"
        assert add[add.index("--scope") + 1] == "user"
        # Normalized with the required stdio transport ``type``.
        assert json.loads(add[4]) == {
            "type": "stdio",
            "command": "pipx",
            "args": ["run", "google-ads-mcp"],
        }

    def test_add_via_cli_failure_raises(self) -> None:
        from types import SimpleNamespace

        from mureo.providers.config_writer import (
            ConfigWriteError,
            add_provider_to_claude_settings,
        )

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            rc = 0 if "remove" in argv else 2
            return SimpleNamespace(returncode=rc, stdout="", stderr="boom")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
            pytest.raises(ConfigWriteError, match="add-json"),
        ):
            add_provider_to_claude_settings(_make_spec())

    def test_add_via_cli_failure_redacts_secret_from_stderr(self) -> None:
        """A rejecting CLI that echoes the payload must NOT leak the
        injected credential env values into the raised/logged message."""
        from types import SimpleNamespace

        from mureo.providers.config_writer import (
            ConfigWriteError,
            add_provider_to_claude_settings,
        )

        secret = "1//0secret-refresh-token"

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            rc = 0 if "remove" in argv else 2
            # Simulate the CLI echoing the offending payload back.
            return SimpleNamespace(
                returncode=rc,
                stdout="",
                stderr=f"invalid config: {secret} rejected",
            )

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
            pytest.raises(ConfigWriteError) as exc_info,
        ):
            add_provider_to_claude_settings(
                _make_spec(),
                extra_env={"GOOGLE_ADS_REFRESH_TOKEN": secret},
            )

        message = str(exc_info.value)
        assert secret not in message
        assert "***" in message

    def test_remove_via_cli(self) -> None:
        from types import SimpleNamespace

        from mureo.providers.config_writer import (
            RemoveResult,
            remove_provider_from_claude_settings,
        )

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = remove_provider_from_claude_settings("google-ads-official")

        assert result == RemoveResult(changed=True)

    def test_remove_via_cli_noop_when_absent(self) -> None:
        from types import SimpleNamespace

        from mureo.providers.config_writer import (
            RemoveResult,
            remove_provider_from_claude_settings,
        )

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = remove_provider_from_claude_settings("google-ads-official")

        assert result == RemoveResult(changed=False)

    def test_injection_shaped_id_is_rejected(self) -> None:
        """An id that could be parsed as a ``claude`` option flag is
        refused before any subprocess (defense-in-depth)."""
        from mureo.providers.config_writer import (
            ConfigWriteError,
            is_provider_installed,
            remove_provider_from_claude_settings,
        )

        ran = False

        def fake_run(*_: object, **__: object) -> object:
            nonlocal ran
            ran = True
            raise AssertionError("subprocess must not run for a bad id")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            with pytest.raises(ConfigWriteError, match="invalid provider id"):
                remove_provider_from_claude_settings("--help")
            # Degraded-env contract: never raises, just "not installed".
            assert is_provider_installed("-x") is False

        assert ran is False

    def test_is_installed_via_cli(self) -> None:
        from types import SimpleNamespace

        from mureo.providers.config_writer import is_provider_installed

        def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
            rc = 0 if argv[3] == "google-ads-official" else 1
            return SimpleNamespace(returncode=rc, stdout="", stderr="")

        with (
            patch(
                "mureo.providers.config_writer.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "mureo.providers.config_writer.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            assert is_provider_installed("google-ads-official") is True
            assert is_provider_installed("meta-ads-official") is False
