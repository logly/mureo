"""Integration tests for the ``mureo providers`` CLI subcommand group.

Covers ``list``, ``add``, ``remove``, ``add --all``, ``--dry-run``, the
coexistence warning, idempotency, and the regression guard that the
existing ``mureo setup claude-code`` flow continues to work alongside the
new providers commands. See planner HANDOFF
``feat-providers-cli-phase1.md``.

``subprocess.run`` is patched at the production-code boundary
(``mureo.providers.installer.subprocess.run``). ``Path.home`` is monkey-
patched to ``tmp_path`` for every test so no test ever writes to the
operator's real ``~/.claude/``.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect ``Path.home()`` to ``tmp_path`` and mock ``subprocess.run``.

    Every CLI integration test in this module uses this fixture so that
    no test touches the operator's real ``~/.claude/`` and no test ever
    invokes a live ``pipx`` / ``npm`` process.
    """
    monkeypatch.setattr("mureo.providers.config_writer.Path.home", lambda: tmp_path)
    # Also patch auth_setup.Path.home so the regression test that calls
    # install_mcp_config() writes into tmp_path rather than the user's home.
    monkeypatch.setattr("mureo.auth_setup.Path.home", lambda: tmp_path)
    # Force the no-CLI fallback everywhere so integration tests are
    # deterministic and never shell out to a real ``claude`` binary
    # (which would mutate the developer's actual ~/.claude.json).
    monkeypatch.setattr(
        "mureo.providers.config_writer.shutil.which", lambda _: None
    )
    monkeypatch.setattr("mureo.auth_setup.shutil.which", lambda _: None)

    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
    )
    monkeypatch.setattr("mureo.providers.installer.subprocess.run", mock_run)
    yield tmp_path


def _get_subprocess_mock() -> Any:
    """Return the current ``subprocess.run`` mock on the installer module."""
    import mureo.providers.installer as installer_mod

    return installer_mod.subprocess.run  # type: ignore[attr-defined]


def _invoke(*args: str) -> Any:
    """Run the ``mureo`` CLI with the given arguments."""
    from mureo.cli.main import app

    runner = CliRunner()
    return runner.invoke(app, list(args))


@pytest.mark.integration
def test_list_empty_state(home: Path) -> None:
    """`mureo providers list` shows every catalog id as 'not installed'."""
    result = _invoke("providers", "list")

    assert result.exit_code == 0, result.output
    assert "google-ads-official" in result.output
    assert "meta-ads-official" in result.output
    assert "ga4-official" in result.output
    assert "not installed" in result.output.lower()


@pytest.mark.integration
def test_list_after_add_shows_installed(home: Path) -> None:
    """After ``add``, ``list`` marks that provider as installed."""
    add_result = _invoke("providers", "add", "google-ads-official")
    assert add_result.exit_code == 0, add_result.output

    list_result = _invoke("providers", "list")
    assert list_result.exit_code == 0, list_result.output
    lines = [
        line
        for line in list_result.output.splitlines()
        if "google-ads-official" in line
    ]
    assert lines, list_result.output
    assert any("installed" in line.lower() for line in lines)


@pytest.mark.integration
def test_add_invokes_pipx_for_google_ads(home: Path) -> None:
    """``add google-ads-official`` calls ``subprocess.run`` with argv[0]='pipx'."""
    result = _invoke("providers", "add", "google-ads-official")
    assert result.exit_code == 0, result.output

    mock_run = _get_subprocess_mock()
    assert mock_run.call_count == 1
    call_args, call_kwargs = mock_run.call_args
    argv = call_args[0] if call_args else call_kwargs.get("args")
    assert argv[0] == "pipx"


@pytest.mark.integration
def test_add_meta_does_not_register_dead_http_entry(home: Path) -> None:
    """``add meta-ads-official`` must NOT write a raw http entry.

    Meta's hosted Ads MCP has no OAuth Dynamic Client Registration, so a
    raw ``~/.claude.json`` http entry can never connect ("✗ Failed to
    connect"). The CLI must therefore NOT register it and NOT disable
    mureo-native Meta; it prints guidance to add it via Claude's
    account-level Connectors instead. Exit code is 0 (manual setup is
    expected, not a failure) and no subprocess runs.
    """
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)

    result = _invoke("providers", "add", "meta-ads-official")
    assert result.exit_code == 0, result.output

    mock_run = _get_subprocess_mock()
    mock_run.assert_not_called()

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "meta-ads-official" not in payload["mcpServers"]
    # mureo-native Meta is NOT auto-disabled.
    assert "MUREO_DISABLE_META_ADS" not in payload["mcpServers"]["mureo"].get(
        "env", {}
    )

    combined = (result.output or "") + (result.stderr or "")
    lowered = combined.lower()
    assert "connector" in lowered
    assert "mcp.facebook.com/ads" in combined


@pytest.mark.integration
def test_add_meta_dry_run_marks_manual_connector_setup(home: Path) -> None:
    """``--dry-run meta-ads-official`` states it will NOT register the
    entry and points at the manual Connectors path (no misleading
    "would merge mcpServers entry" / "would set MUREO_DISABLE")."""
    result = _invoke("providers", "add", "meta-ads-official", "--dry-run")
    assert result.exit_code == 0, result.output

    mock_run = _get_subprocess_mock()
    mock_run.assert_not_called()

    settings_path = home / ".claude.json"
    assert not settings_path.exists()

    out = result.output
    lowered = out.lower()
    assert "connector" in lowered
    assert "meta-ads-official" in out
    # Must NOT promise a registration / disable that no longer happens.
    assert "would merge mcpservers entry" not in lowered
    assert "mureo_disable_meta_ads" not in lowered


@pytest.mark.integration
def test_add_writes_settings_json(home: Path) -> None:
    """``add`` writes ``mcpServers.<id>`` to ``~/.claude.json``."""
    result = _invoke("providers", "add", "google-ads-official")
    assert result.exit_code == 0, result.output

    settings_path = home / ".claude.json"
    assert settings_path.exists()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "google-ads-official" in payload["mcpServers"]


@pytest.mark.integration
def test_add_is_idempotent(home: Path) -> None:
    """Two ``add`` calls produce a byte-equal settings file and exit 0 each."""
    first = _invoke("providers", "add", "google-ads-official")
    assert first.exit_code == 0, first.output
    settings_path = home / ".claude.json"
    first_bytes = settings_path.read_bytes()

    second = _invoke("providers", "add", "google-ads-official")
    assert second.exit_code == 0, second.output
    second_bytes = settings_path.read_bytes()

    assert first_bytes == second_bytes
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert list(payload["mcpServers"].keys()).count("google-ads-official") == 1


@pytest.mark.integration
def test_add_all_installs_every_catalog_entry(home: Path) -> None:
    """``add --all`` writes every catalog entry; subprocess runs only for non-hosted.

    Hosted entries (``install_kind="hosted_http"``) skip the subprocess
    step entirely, so the subprocess call count equals the number of
    *non-hosted* catalog entries — not ``len(CATALOG)``.
    """
    result = _invoke("providers", "add", "--all")
    assert result.exit_code == 0, result.output

    from mureo.providers.catalog import CATALOG

    expected_subprocess_calls = sum(
        1 for spec in CATALOG if spec.install_kind != "hosted_http"
    )
    mock_run = _get_subprocess_mock()
    assert mock_run.call_count == expected_subprocess_calls

    settings_path = home / ".claude.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    for spec in CATALOG:
        if spec.install_kind == "hosted_http":
            # Hosted (no-DCR) entries are NOT registered — they require
            # the manual Connectors path; a raw http entry can't connect.
            assert spec.id not in payload.get("mcpServers", {}), spec.id
        else:
            assert spec.id in payload["mcpServers"], spec.id


@pytest.mark.integration
def test_add_all_continues_on_per_provider_failure(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If one provider fails mid-batch, the others still install; exit non-zero.

    Hosted entries skip ``subprocess.run`` entirely, so ``calls`` only
    records invocations from non-hosted providers. The loop must still
    iterate the full ``CATALOG`` — the regression we guard against is
    "abort on first failure" — and the final exit code must be non-zero.
    """
    from mureo.providers.catalog import CATALOG

    expected_subprocess_calls = sum(
        1 for spec in CATALOG if spec.install_kind != "hosted_http"
    )
    # Failure path requires at least one non-hosted entry to exercise.
    assert expected_subprocess_calls >= 1

    calls: list[list[str]] = []

    def _side_effect(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        argv = args[0] if args else kwargs.get("args", [])
        calls.append(list(argv))
        # Fail on the second non-hosted invocation only (when present;
        # otherwise on the first). Ensures at least one provider before the
        # failure succeeds and at least one after is still attempted when
        # the catalog grows.
        fail_at = 2 if expected_subprocess_calls >= 2 else 1
        if len(calls) == fail_at:
            return subprocess.CompletedProcess(
                args=argv, returncode=1, stdout="", stderr="install boom"
            )
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("mureo.providers.installer.subprocess.run", _side_effect)

    result = _invoke("providers", "add", "--all")

    assert result.exit_code != 0
    # All non-hosted providers were attempted (loop did not abort on failure).
    assert len(calls) == expected_subprocess_calls
    combined = (result.output or "") + (result.stderr or "")
    assert "fail" in combined.lower() or "error" in combined.lower()


@pytest.mark.integration
def test_add_dry_run_does_not_call_subprocess(home: Path) -> None:
    """``--dry-run`` prints the plan but neither runs pipx/npm nor writes disk."""
    result = _invoke("providers", "add", "google-ads-official", "--dry-run")
    assert result.exit_code == 0, result.output

    mock_run = _get_subprocess_mock()
    mock_run.assert_not_called()

    settings_path = home / ".claude.json"
    assert not settings_path.exists()

    # The output should describe what would happen.
    assert "pipx" in result.output
    assert "google-ads-official" in result.output


@pytest.mark.integration
def test_add_emits_coexistence_warning(home: Path) -> None:
    """Adding an official provider emits a coexistence warning for mureo."""
    result = _invoke("providers", "add", "google-ads-official")
    assert result.exit_code == 0, result.output
    combined = (result.output or "") + (result.stderr or "")
    lowered = combined.lower()
    assert "google" in lowered and "ads" in lowered
    assert "mureo" in lowered


@pytest.mark.integration
def test_remove_deletes_key(home: Path) -> None:
    """``remove`` pops the provider key but leaves the native ``mureo`` entry."""
    settings_path = home / ".claude.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mureo": {"command": "python", "args": ["-m", "mureo.mcp"]}
                }
            }
        ),
        encoding="utf-8",
    )

    add = _invoke("providers", "add", "google-ads-official")
    assert add.exit_code == 0, add.output

    remove = _invoke("providers", "remove", "google-ads-official")
    assert remove.exit_code == 0, remove.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "google-ads-official" not in payload["mcpServers"]
    assert "mureo" in payload["mcpServers"]


@pytest.mark.integration
def test_remove_unknown_id_exits_nonzero_with_helpful_message(home: Path) -> None:
    """Removing an unknown id exits non-zero and lists valid ids."""
    result = _invoke("providers", "remove", "no-such-provider")

    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    assert "no-such-provider" in combined
    assert (
        "google-ads-official" in combined
        or "meta-ads-official" in combined
        or "ga4-official" in combined
    )


@pytest.mark.integration
def test_existing_setup_claude_code_still_works(home: Path) -> None:
    """Regression: ``install_mcp_config`` + new providers ``add`` coexist."""
    from mureo.auth_setup import install_mcp_config

    # ``home`` fixture forces the no-CLI fallback (no real ``claude``
    # shell-out), so this writes into tmp_path/.claude.json.
    result_path = install_mcp_config(scope="global")
    assert result_path is not None
    assert result_path.exists()

    add = _invoke("providers", "add", "google-ads-official")
    assert add.exit_code == 0, add.output

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert "mureo" in payload["mcpServers"]
    assert "google-ads-official" in payload["mcpServers"]


@pytest.mark.integration
def test_main_registers_providers_app(home: Path) -> None:
    """``mureo --help`` mentions the ``providers`` subcommand."""
    result = _invoke("--help")
    assert result.exit_code == 0, result.output
    assert "providers" in result.output.lower()


# ---------------------------------------------------------------------------
# Disable-mureo extension (added 2026-05-12 per Founder Q1/Q2)
# ---------------------------------------------------------------------------
#
# These tests verify that ``mureo providers add`` also writes the matching
# ``MUREO_DISABLE_*`` env var into ``mcpServers.mureo.env`` when the native
# mureo block is present, so the mureo MCP server can auto-disable the tool
# family for the platform whose official MCP was just registered.
#
# When the native mureo block is absent the official provider is still
# added but the auto-disable step is skipped with an informational note —
# the CLI must not invent a mureo block (that's ``mureo setup …``'s job).


def _seed_mureo_block(settings_path: Path) -> None:
    """Pre-seed ``~/.claude.json`` with the native mureo entry.

    Represents the state after the user has previously run
    ``mureo setup claude-code``.
    """
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


@pytest.mark.integration
def test_add_google_ads_sets_mureo_disable_env(home: Path) -> None:
    """``add google-ads-official`` writes ``MUREO_DISABLE_GOOGLE_ADS=1``."""
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)

    result = _invoke("providers", "add", "google-ads-official")
    assert result.exit_code == 0, result.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "google-ads-official" in payload["mcpServers"]
    mureo_env = payload["mcpServers"]["mureo"].get("env", {})
    assert mureo_env.get("MUREO_DISABLE_GOOGLE_ADS") == "1"


@pytest.mark.integration
def test_add_meta_ads_does_not_disable_native(home: Path) -> None:
    """``add meta-ads-official`` (hosted_http, no DCR) must NOT disable
    mureo-native Meta.

    The raw http entry can't connect, so disabling native would strand
    the user with zero Meta capability (observed regression). Native
    stays until the user has the official Connector working.
    """
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)

    result = _invoke("providers", "add", "meta-ads-official")
    assert result.exit_code == 0, result.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "meta-ads-official" not in payload["mcpServers"]
    mureo_env = payload["mcpServers"]["mureo"].get("env", {})
    assert "MUREO_DISABLE_META_ADS" not in mureo_env


@pytest.mark.integration
def test_add_ga4_sets_mureo_disable_env(home: Path) -> None:
    """``add ga4-official`` writes ``MUREO_DISABLE_GA4=1``."""
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)

    result = _invoke("providers", "add", "ga4-official")
    assert result.exit_code == 0, result.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "ga4-official" in payload["mcpServers"]
    mureo_env = payload["mcpServers"]["mureo"].get("env", {})
    assert mureo_env.get("MUREO_DISABLE_GA4") == "1"


@pytest.mark.integration
def test_remove_provider_unsets_mureo_disable_env(home: Path) -> None:
    """``remove`` pops only the ``MUREO_DISABLE_*`` key; user-added env keys survive.

    Seeds a user-added ``PYTHONPATH`` env entry before ``add`` so we can
    verify that ``remove`` does NOT pop it alongside the MUREO_DISABLE key.
    """
    settings_path = home / ".claude.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mureo": {
                        "command": "python",
                        "args": ["-m", "mureo.mcp"],
                        "env": {"PYTHONPATH": "/custom"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    add = _invoke("providers", "add", "google-ads-official")
    assert add.exit_code == 0, add.output

    # Sanity: after ``add``, the disable env var IS present (locks in that
    # the round-trip actually exercised the writer in the first place — a
    # regression-only assertion to make this test fail today, not just
    # after implementation).
    after_add = json.loads(settings_path.read_text(encoding="utf-8"))
    after_add_env = after_add["mcpServers"]["mureo"].get("env", {})
    assert after_add_env.get("MUREO_DISABLE_GOOGLE_ADS") == "1"
    assert after_add_env.get("PYTHONPATH") == "/custom"

    remove = _invoke("providers", "remove", "google-ads-official")
    assert remove.exit_code == 0, remove.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    mureo_env = payload["mcpServers"]["mureo"].get("env", {})
    assert "MUREO_DISABLE_GOOGLE_ADS" not in mureo_env
    # User-added env key survives the remove.
    assert mureo_env.get("PYTHONPATH") == "/custom"


@pytest.mark.integration
def test_add_without_existing_mureo_block_skips_disable_env_gracefully(
    home: Path,
) -> None:
    """No mureo block ⇒ add the official provider; do NOT invent a mureo block.

    The CLI must emit an informational note when it cannot apply the
    auto-disable because no mureo block exists. The official provider
    registration still happens (existing Phase 1 behavior).
    """
    settings_path = home / ".claude.json"
    assert not settings_path.exists()

    result = _invoke("providers", "add", "google-ads-official")
    assert result.exit_code == 0, result.output

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "google-ads-official" in payload["mcpServers"]
    # mureo block was NOT invented.
    assert "mureo" not in payload["mcpServers"]

    # CLI surfaces the degraded path in output (mentions ``mureo`` and that
    # nothing was auto-disabled / no native block was found).
    lowered = (result.output or "").lower()
    assert "mureo" in lowered
    assert (
        "not registered" in lowered
        or "no mureo" in lowered
        or "skipping" in lowered
        or "skipped" in lowered
        or "not found" in lowered
    )


# ---------------------------------------------------------------------------
# `mureo providers confirm <id>` — disable native ONCE the official hosted
# connector is verified Connected (closes the post-setup coexistence gap
# without ever auto-disabling native before the official path works).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_confirm_unknown_provider_exit_2(home: Path) -> None:
    result = _invoke("providers", "confirm", "nope")
    assert result.exit_code == 2
    assert "unknown provider" in (result.output + (result.stderr or "")).lower()


@pytest.mark.integration
def test_confirm_non_hosted_is_rejected(home: Path) -> None:
    result = _invoke("providers", "confirm", "google-ads-official")
    assert result.exit_code == 2
    assert "hosted" in result.output.lower()


@pytest.mark.integration
def test_confirm_not_connected_does_not_disable_native(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connector not yet authorised → guidance, exit 1, native untouched."""
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)
    monkeypatch.setattr(
        "mureo.cli.providers_cmd.is_hosted_provider_connected",
        lambda spec: False,
    )

    result = _invoke("providers", "confirm", "meta-ads-official")
    assert result.exit_code == 1
    out = result.output.lower()
    assert "connector" in out and "claude mcp list" in out
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "MUREO_DISABLE_META_ADS" not in payload["mcpServers"]["mureo"].get(
        "env", {}
    )


@pytest.mark.integration
def test_confirm_connected_disables_native(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = home / ".claude.json"
    _seed_mureo_block(settings_path)
    monkeypatch.setattr(
        "mureo.cli.providers_cmd.is_hosted_provider_connected",
        lambda spec: True,
    )

    result = _invoke("providers", "confirm", "meta-ads-official")
    assert result.exit_code == 0, result.output
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert (
        payload["mcpServers"]["mureo"]["env"]["MUREO_DISABLE_META_ADS"] == "1"
    )
    assert "restart" in result.output.lower()


@pytest.mark.integration
def test_confirm_connected_no_mureo_block_informative(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mureo.cli.providers_cmd.is_hosted_provider_connected",
        lambda spec: True,
    )
    result = _invoke("providers", "confirm", "meta-ads-official")
    assert result.exit_code == 0
    assert "setup claude-code" in result.output.lower()
