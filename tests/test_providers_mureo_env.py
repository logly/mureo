"""Unit tests for ``mureo.providers.mureo_env``.

Pins the behavior of the per-platform ``MUREO_DISABLE_*`` env-var writers
that gate mureo's native MCP tools when an official provider is installed.

The module under test is expected to live at
``mureo.providers.mureo_env`` and to expose:

- ``set_mureo_disable_env(platform, *, settings_path=None) -> SetEnvResult``
- ``unset_mureo_disable_env(platform, *, settings_path=None) -> UnsetEnvResult``
- ``add_provider_and_disable_in_mureo(spec, *, settings_path=None) -> AddResult``
  (combined single-atomic-write helper used by the CLI on ``add``)
- ``SetEnvResult`` / ``UnsetEnvResult`` frozen dataclasses
- ``_PLATFORM_TO_ENV_VAR`` module-private mapping (catalog-controlled keys)

External calls are mocked at the
``mureo.providers.config_writer.os.replace`` boundary (since the new module
reuses ``_atomic_write_json`` from ``config_writer``). See planner HANDOFF
``feat-providers-cli-phase1.md`` (Disable-mureo Extension section).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _seed_settings(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write an initial ``settings.json`` containing ``payload``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_provider_spec(
    *,
    spec_id: str = "google-ads-official",
    coexists_with_mureo_platform: str | None = "google_ads",
) -> Any:
    """Build a real ``ProviderSpec`` for the combined-write helper tests."""
    from mureo.providers.catalog import ProviderSpec

    return ProviderSpec(
        id=spec_id,
        display_name=spec_id,
        install_kind="pipx",
        install_argv=("pipx", "run", "google-ads-mcp"),
        mcp_server_config={
            "command": "pipx",
            "args": ["run", "google-ads-mcp"],
        },
        required_env=(),
        notes="",
        coexists_with_mureo_platform=coexists_with_mureo_platform,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# set_mureo_disable_env
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_mureo_disable_env_creates_env_field_when_missing(tmp_path: Path) -> None:
    """A mureo block without ``env`` gets a fresh dict with the new key."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]},
            }
        },
    )

    result = set_mureo_disable_env("google_ads", settings_path=settings_path)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    mureo_entry = payload["mcpServers"]["mureo"]
    assert mureo_entry["env"] == {"MUREO_DISABLE_GOOGLE_ADS": "1"}
    # Other keys of the mureo block survive verbatim.
    assert mureo_entry["command"] == "python"
    assert mureo_entry["args"] == ["-m", "mureo.mcp"]
    assert result.changed is True
    assert result.mureo_block_present is True


@pytest.mark.unit
def test_set_mureo_disable_env_preserves_existing_env_entries(tmp_path: Path) -> None:
    """User-added env entries (e.g. PYTHONPATH) are not overwritten."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {
                    "command": "python",
                    "args": ["-m", "mureo.mcp"],
                    "env": {"PYTHONPATH": "/custom", "DEBUG": "1"},
                }
            }
        },
    )

    result = set_mureo_disable_env("meta_ads", settings_path=settings_path)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    env = payload["mcpServers"]["mureo"]["env"]
    assert env == {
        "PYTHONPATH": "/custom",
        "DEBUG": "1",
        "MUREO_DISABLE_META_ADS": "1",
    }
    assert result.changed is True


@pytest.mark.unit
def test_set_mureo_disable_env_idempotent(tmp_path: Path) -> None:
    """Calling twice yields byte-equal file and ``changed=False`` on 2nd call."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]},
            }
        },
    )

    first = set_mureo_disable_env("google_ads", settings_path=settings_path)
    first_bytes = settings_path.read_bytes()
    second = set_mureo_disable_env("google_ads", settings_path=settings_path)
    second_bytes = settings_path.read_bytes()

    assert first.changed is True
    assert second.changed is False
    assert first_bytes == second_bytes


@pytest.mark.unit
def test_set_mureo_disable_env_returns_mureo_block_absent_when_no_mureo_entry(
    tmp_path: Path,
) -> None:
    """No mureo block ⇒ no-op + ``mureo_block_present=False`` + no rewrite."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "google-ads-official": {"command": "pipx", "args": ["run", "x"]},
            }
        },
    )
    pre_bytes = settings_path.read_bytes()

    with patch("mureo.providers.config_writer.os.replace") as mock_replace:
        result = set_mureo_disable_env("google_ads", settings_path=settings_path)

    assert result.changed is False
    assert result.mureo_block_present is False
    assert settings_path.read_bytes() == pre_bytes
    mock_replace.assert_not_called()


@pytest.mark.unit
def test_set_mureo_disable_env_does_not_create_settings_file_when_absent(
    tmp_path: Path,
) -> None:
    """Missing settings file is a no-op; we never invent a mureo block."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"

    result = set_mureo_disable_env("google_ads", settings_path=settings_path)

    assert result.changed is False
    assert result.mureo_block_present is False
    assert not settings_path.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "platform,env_var",
    [
        ("google_ads", "MUREO_DISABLE_GOOGLE_ADS"),
        ("meta_ads", "MUREO_DISABLE_META_ADS"),
        ("ga4", "MUREO_DISABLE_GA4"),
    ],
)
def test_set_mureo_disable_env_per_platform_writes_correct_env_var_name(
    tmp_path: Path, platform: str, env_var: str
) -> None:
    """The platform→env-var-name mapping is exact and catalog-controlled."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {"mcpServers": {"mureo": {"command": "python"}}},
    )

    set_mureo_disable_env(platform, settings_path=settings_path)  # type: ignore[arg-type]

    env = json.loads(settings_path.read_text(encoding="utf-8"))["mcpServers"]["mureo"][
        "env"
    ]
    assert env[env_var] == "1"


@pytest.mark.unit
def test_set_mureo_disable_env_value_is_string_one_exact(tmp_path: Path) -> None:
    """The value written is literally the string ``"1"`` (not bool / int)."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(settings_path, {"mcpServers": {"mureo": {"command": "python"}}})

    set_mureo_disable_env("google_ads", settings_path=settings_path)

    value = json.loads(settings_path.read_text(encoding="utf-8"))["mcpServers"][
        "mureo"
    ]["env"]["MUREO_DISABLE_GOOGLE_ADS"]
    assert value == "1"
    assert isinstance(value, str)
    # Negative assertions guard against future refactor that coerces:
    assert value is not True  # type: ignore[comparison-overlap]
    assert value != 1  # type: ignore[comparison-overlap]


@pytest.mark.unit
def test_set_mureo_disable_env_writes_atomically(tmp_path: Path) -> None:
    """The atomic-replace tmp file lives in target.parent (POSIX rename rule)."""
    import os as _os

    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(settings_path, {"mcpServers": {"mureo": {"command": "python"}}})

    captured: dict[str, Any] = {}
    real_replace = _os.replace

    def _spy(src: Any, dst: Any) -> None:
        captured["src"] = _os.fspath(src)
        captured["dst"] = _os.fspath(dst)
        real_replace(src, dst)

    with patch("mureo.providers.config_writer.os.replace", side_effect=_spy):
        set_mureo_disable_env("google_ads", settings_path=settings_path)

    src = Path(captured["src"])
    dst = Path(captured["dst"])
    assert dst == settings_path
    assert src.parent == settings_path.parent
    assert ".tmp" in src.name


@pytest.mark.unit
def test_set_mureo_disable_env_uses_path_home_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting ``settings_path`` resolves to ``Path.home()/.claude/settings.json``."""
    from mureo.providers.mureo_env import set_mureo_disable_env

    monkeypatch.setattr("mureo.providers.config_writer.Path.home", lambda: tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(settings_path, {"mcpServers": {"mureo": {"command": "python"}}})

    result = set_mureo_disable_env("google_ads")

    assert result.changed is True
    env = json.loads(settings_path.read_text(encoding="utf-8"))["mcpServers"]["mureo"][
        "env"
    ]
    assert env["MUREO_DISABLE_GOOGLE_ADS"] == "1"


@pytest.mark.unit
def test_set_mureo_disable_env_rejects_unknown_platform(tmp_path: Path) -> None:
    """Defensive runtime check: passing ``search_console`` raises.

    The ``CoexistsPlatform`` ``Literal`` enforces this at type-check time;
    this runtime check defends against dynamic callers (CLI plumbing) that
    bypass mypy.
    """
    from mureo.providers.mureo_env import set_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(settings_path, {"mcpServers": {"mureo": {"command": "python"}}})

    with pytest.raises((KeyError, ValueError)):
        set_mureo_disable_env("search_console", settings_path=settings_path)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# unset_mureo_disable_env
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unset_mureo_disable_env_removes_key_only(tmp_path: Path) -> None:
    """Only the MUREO_DISABLE key is removed — user-added env keys survive."""
    from mureo.providers.mureo_env import unset_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {
                    "command": "python",
                    "env": {
                        "MUREO_DISABLE_GOOGLE_ADS": "1",
                        "PYTHONPATH": "/x",
                    },
                }
            }
        },
    )

    result = unset_mureo_disable_env("google_ads", settings_path=settings_path)

    env = json.loads(settings_path.read_text(encoding="utf-8"))["mcpServers"]["mureo"][
        "env"
    ]
    assert env == {"PYTHONPATH": "/x"}
    assert result.changed is True


@pytest.mark.unit
def test_unset_mureo_disable_env_keeps_empty_env_dict(tmp_path: Path) -> None:
    """Last key removed ⇒ ``env`` becomes ``{}`` (key not deleted entirely)."""
    from mureo.providers.mureo_env import unset_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {
                    "command": "python",
                    "env": {"MUREO_DISABLE_GOOGLE_ADS": "1"},
                }
            }
        },
    )

    unset_mureo_disable_env("google_ads", settings_path=settings_path)

    mureo_entry = json.loads(settings_path.read_text(encoding="utf-8"))["mcpServers"][
        "mureo"
    ]
    assert "env" in mureo_entry, "env key must be preserved as empty dict"
    assert mureo_entry["env"] == {}


@pytest.mark.unit
def test_unset_mureo_disable_env_noop_when_key_absent(tmp_path: Path) -> None:
    """Idempotent: removing an absent key returns ``changed=False`` + no rewrite."""
    from mureo.providers.mureo_env import unset_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {"mcpServers": {"mureo": {"command": "python", "env": {"PYTHONPATH": "/x"}}}},
    )
    pre_bytes = settings_path.read_bytes()

    with patch("mureo.providers.config_writer.os.replace") as mock_replace:
        result = unset_mureo_disable_env("google_ads", settings_path=settings_path)

    assert result.changed is False
    assert settings_path.read_bytes() == pre_bytes
    mock_replace.assert_not_called()


@pytest.mark.unit
def test_unset_mureo_disable_env_noop_when_mureo_absent(tmp_path: Path) -> None:
    """No mureo block ⇒ ``changed=False`` and no rewrite."""
    from mureo.providers.mureo_env import unset_mureo_disable_env

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {"mcpServers": {"google-ads-official": {"command": "pipx"}}},
    )
    pre_bytes = settings_path.read_bytes()

    with patch("mureo.providers.config_writer.os.replace") as mock_replace:
        result = unset_mureo_disable_env("google_ads", settings_path=settings_path)

    assert result.changed is False
    assert settings_path.read_bytes() == pre_bytes
    mock_replace.assert_not_called()


# ---------------------------------------------------------------------------
# add_provider_and_disable_in_mureo (combined atomic write)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_provider_and_disable_in_mureo_single_atomic_write(
    tmp_path: Path,
) -> None:
    """Both writes happen in a single ``os.replace`` call (no torn state).

    Regression guard for the risk that two sibling atomic writes (one for the
    new provider block, one for the env-var entry) leave the file half-updated
    if a crash interleaves them.
    """
    from mureo.providers.mureo_env import add_provider_and_disable_in_mureo

    settings_path = tmp_path / ".claude" / "settings.json"
    _seed_settings(
        settings_path,
        {
            "mcpServers": {
                "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]},
            }
        },
    )

    spec = _make_provider_spec()

    import os as _os

    real_replace = _os.replace
    call_count = {"n": 0}

    def _spy(src: Any, dst: Any) -> None:
        call_count["n"] += 1
        real_replace(src, dst)

    with patch("mureo.providers.config_writer.os.replace", side_effect=_spy):
        add_provider_and_disable_in_mureo(spec, settings_path=settings_path)

    assert call_count["n"] == 1, (
        f"expected exactly ONE os.replace call (single atomic write); "
        f"got {call_count['n']}"
    )

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert spec.id in payload["mcpServers"]
    env = payload["mcpServers"]["mureo"]["env"]
    assert env["MUREO_DISABLE_GOOGLE_ADS"] == "1"


@pytest.mark.unit
def test_add_provider_and_disable_in_mureo_preserves_other_top_level_keys(
    tmp_path: Path,
) -> None:
    """Top-level keys (``permissions``, ``hooks``, etc.) survive verbatim."""
    from mureo.providers.mureo_env import add_provider_and_disable_in_mureo

    settings_path = tmp_path / ".claude" / "settings.json"
    original = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PostToolUse": []},
        "mcpServers": {
            "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]},
        },
    }
    _seed_settings(settings_path, original)

    add_provider_and_disable_in_mureo(
        _make_provider_spec(), settings_path=settings_path
    )

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["permissions"] == original["permissions"]
    assert payload["hooks"] == original["hooks"]


# ---------------------------------------------------------------------------
# Result dataclass immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_env_result_is_frozen() -> None:
    """``SetEnvResult`` must be a frozen dataclass."""
    from mureo.providers.mureo_env import SetEnvResult

    result = SetEnvResult(changed=True, mureo_block_present=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.changed = False  # type: ignore[misc]


@pytest.mark.unit
def test_unset_env_result_is_frozen() -> None:
    """``UnsetEnvResult`` must be a frozen dataclass."""
    from mureo.providers.mureo_env import UnsetEnvResult

    result = UnsetEnvResult(changed=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.changed = True  # type: ignore[misc]
