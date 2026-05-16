"""RED tests for ``mureo.web.demo_actions`` (does not exist yet).

Mirrors the wrapper / frozen-result-envelope pattern of
``mureo.web.setup_actions``. The module is expected to expose:

- ``list_demo_scenarios() -> ...`` — JSON-friendly list of registered
  demo scenarios sourced from ``mureo.demo.scenarios.SCENARIOS``.
- ``init_demo(scenario_name, target, force, skip_import) -> ...`` — wraps
  ``mureo.demo.installer.materialize`` with strict target-path
  validation and degrades exceptions to an ``error`` envelope.

All filesystem-touching internals (``materialize``) are mocked: no real
scenario scaffolding, no real XLSX, no real ``~/.mureo`` writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# list_demo_scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDemoScenarios:
    def test_returns_ok_envelope(self) -> None:
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "ok"

    def test_lists_every_registered_scenario(self) -> None:
        from mureo.demo.scenarios import SCENARIOS
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        names = {s["name"] for s in as_dict["scenarios"]}
        assert names == set(SCENARIOS)

    def test_marks_default_scenario(self) -> None:
        from mureo.demo.scenarios import DEFAULT_SCENARIO
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        default_rows = [s for s in as_dict["scenarios"] if s.get("default")]
        assert len(default_rows) == 1
        assert default_rows[0]["name"] == DEFAULT_SCENARIO

    def test_includes_title_and_blurb(self) -> None:
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        for row in as_dict["scenarios"]:
            assert row["title"]
            assert row["blurb"]

    def test_no_secret_or_path_leakage_in_listing(self) -> None:
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        blob = repr(as_dict)
        assert "/.mureo/credentials" not in blob
        assert "refresh_token" not in blob

    def test_scenarios_sorted_by_name(self) -> None:
        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        names = [s["name"] for s in as_dict["scenarios"]]
        assert names == sorted(names)

    def test_registry_failure_degrades_to_error_envelope(self) -> None:
        from mureo.web import demo_actions

        with patch.object(
            demo_actions, "SCENARIOS", new=MagicMock()
        ) as broken:
            broken.__iter__.side_effect = RuntimeError("registry boom")
            broken.items.side_effect = RuntimeError("registry boom")
            result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"


# ---------------------------------------------------------------------------
# init_demo — success paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitDemoSuccess:
    def _materialize_return(self, target: Path) -> dict[str, Any]:
        return {
            "bundle": target / "bundle.xlsx",
            "strategy": target / "STRATEGY.md",
            "state": target / "STATE.json",
            "mcp": target / ".mcp.json",
            "readme": target / "README.md",
        }

    def test_success_returns_ok_and_created_path(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "mureo-demo"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value=self._materialize_return(target),
        ) as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "ok"
        assert as_dict["created_path"] == str(target)
        mock_mat.assert_called_once()

    def test_default_imported_true_when_not_skipped(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value=self._materialize_return(target),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["imported"] is True

    def test_skip_import_passed_through_and_imported_false(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        ret = self._materialize_return(target)
        ret["state"] = None
        with patch(
            "mureo.web.demo_actions.materialize", return_value=ret
        ) as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=True,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["imported"] is False
        assert mock_mat.call_args.kwargs.get("skip_import") is True

    def test_force_flag_passed_through(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value=self._materialize_return(target),
        ) as mock_mat:
            demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=True,
                skip_import=False,
            )
        assert mock_mat.call_args.kwargs.get("force") is True

    def test_scenario_name_passed_through(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value=self._materialize_return(target),
        ) as mock_mat:
            demo_actions.init_demo(
                scenario_name="halo-effect",
                target=str(target),
                force=False,
                skip_import=False,
            )
        kwargs = mock_mat.call_args.kwargs
        assert kwargs.get("scenario_name") == "halo-effect"

    def test_never_echoes_binary_file_contents(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value=self._materialize_return(target),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert "PK\x03\x04" not in repr(as_dict)


# ---------------------------------------------------------------------------
# init_demo — error / validation paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitDemoErrors:
    def test_unknown_scenario_returns_error(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=ValueError("Unknown scenario: 'nope'"),
        ):
            result = demo_actions.init_demo(
                scenario_name="nope",
                target=str(tmp_path / "d"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"

    def test_demo_init_error_returns_error_envelope(self, tmp_path: Path) -> None:
        from mureo.demo.installer import DemoInitError
        from mureo.web import demo_actions

        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=DemoInitError("directory is not empty"),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(tmp_path / "d"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"

    def test_exists_without_force_surfaces_error(self, tmp_path: Path) -> None:
        from mureo.demo.installer import DemoInitError
        from mureo.web import demo_actions

        existing = tmp_path / "d"
        existing.mkdir()
        (existing / "unrelated.txt").write_text("x", encoding="utf-8")
        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=DemoInitError("directory is not empty"),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(existing),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"

    def test_unexpected_exception_degrades_to_error(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=RuntimeError("disk full"),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(tmp_path / "d"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"

    def test_error_envelope_does_not_leak_full_traceback(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import demo_actions

        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=RuntimeError("/Users/secret/path boom"),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(tmp_path / "d"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert "Traceback (most recent call last)" not in repr(as_dict)


# ---------------------------------------------------------------------------
# init_demo — target path validation (security)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitDemoTargetValidation:
    @pytest.mark.parametrize(
        "bad_target",
        [
            "../../etc",
            "../escape",
            "demo/../../../tmp/x",
            "./relative-but-traversal/../..",
        ],
    )
    def test_traversal_target_rejected_without_calling_materialize(
        self, bad_target: str
    ) -> None:
        from mureo.web import demo_actions

        with patch("mureo.web.demo_actions.materialize") as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=bad_target,
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"
        mock_mat.assert_not_called()

    @pytest.mark.parametrize("ctrl", ["bad\x00name", "tab\tname", "nl\nname"])
    def test_control_char_target_rejected(self, ctrl: str) -> None:
        from mureo.web import demo_actions

        with patch("mureo.web.demo_actions.materialize") as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=ctrl,
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"
        mock_mat.assert_not_called()

    def test_empty_target_rejected(self) -> None:
        from mureo.web import demo_actions

        with patch("mureo.web.demo_actions.materialize") as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target="",
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"
        mock_mat.assert_not_called()

    def test_absolute_target_under_tmp_is_accepted(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "ok-demo"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value={
                "bundle": target / "bundle.xlsx",
                "strategy": target / "STRATEGY.md",
                "state": target / "STATE.json",
                "mcp": target / ".mcp.json",
                "readme": target / "README.md",
            },
        ) as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "ok"
        mock_mat.assert_called_once()

    def test_home_relative_target_accepted(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "home" / "mureo-demo"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value={
                "bundle": target / "bundle.xlsx",
                "strategy": target / "STRATEGY.md",
                "state": target / "STATE.json",
                "mcp": target / ".mcp.json",
                "readme": target / "README.md",
            },
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "ok"

    def test_non_string_target_rejected(self) -> None:
        from mureo.web import demo_actions

        with patch("mureo.web.demo_actions.materialize") as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=12345,  # type: ignore[arg-type]
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"
        mock_mat.assert_not_called()

    def test_symlink_escape_target_rejected(self, tmp_path: Path) -> None:
        """A symlink whose realpath escapes a safe root must be refused
        before ``materialize`` runs."""
        from mureo.web import demo_actions

        outside = tmp_path / "outside"
        outside.mkdir()
        link = tmp_path / "home" / "evil-link"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        with patch("mureo.web.demo_actions.materialize") as mock_mat:
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(link / ".." / ".." / "escaped"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] == "error"
        mock_mat.assert_not_called()


# ---------------------------------------------------------------------------
# Result envelope shape contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvelopeContract:
    def test_result_is_frozen_dataclass_like(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value={
                "bundle": target / "bundle.xlsx",
                "strategy": target / "STRATEGY.md",
                "state": target / "STATE.json",
                "mcp": target / ".mcp.json",
                "readme": target / "README.md",
            },
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        assert hasattr(result, "as_dict")
        with pytest.raises(Exception):
            result.status = "tampered"  # type: ignore[misc]

    def test_as_dict_is_json_serializable(self, tmp_path: Path) -> None:
        import json

        from mureo.web import demo_actions

        target = tmp_path / "d"
        with patch(
            "mureo.web.demo_actions.materialize",
            return_value={
                "bundle": target / "bundle.xlsx",
                "strategy": target / "STRATEGY.md",
                "state": target / "STATE.json",
                "mcp": target / ".mcp.json",
                "readme": target / "README.md",
            },
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(target),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        json.dumps(as_dict)  # must not raise

    def test_list_result_json_serializable(self) -> None:
        import json

        from mureo.web import demo_actions

        result = demo_actions.list_demo_scenarios()
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        json.dumps(as_dict)

    def test_error_envelope_has_no_status_ok(self, tmp_path: Path) -> None:
        from mureo.web import demo_actions

        with patch(
            "mureo.web.demo_actions.materialize",
            side_effect=RuntimeError("x"),
        ):
            result = demo_actions.init_demo(
                scenario_name="seasonality-trap",
                target=str(tmp_path / "d"),
                force=False,
                skip_import=False,
            )
        as_dict = result.as_dict() if hasattr(result, "as_dict") else result
        assert as_dict["status"] != "ok"
