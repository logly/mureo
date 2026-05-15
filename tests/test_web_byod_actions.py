"""RED tests for ``mureo.web.byod_actions`` (does not exist yet).

Mirrors the wrapper / frozen-result-envelope pattern of
``mureo.web.setup_actions``. The module is expected to expose:

- ``byod_status() -> ...`` — per-platform mode (byod | live) with
  rows / date_range, sourced from ``mureo.byod.runtime``.
- ``byod_import(file_path, replace) -> ...`` — strict path validation
  then ``mureo.byod.bundle.import_bundle``; degrades to error envelope.
- ``byod_remove(google_ads, meta_ads) -> ...`` — wraps
  ``mureo.byod.installer.remove_platform``.
- ``byod_clear() -> ...`` — wraps ``mureo.byod.installer.clear_all``.
- ``_validate_xlsx_path(...)`` — absolute + ``.xlsx``/``.xlsm`` only +
  realpath + isfile + reject NUL/control chars.

``import_bundle`` / ``remove_platform`` / ``clear_all`` / manifest reads
are mocked. No real XLSX parsing, no real ``~/.mureo`` writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _d(result: Any) -> dict[str, Any]:
    return result.as_dict() if hasattr(result, "as_dict") else result


# ---------------------------------------------------------------------------
# _validate_xlsx_path — path-validation helper (security core)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateXlsxPath:
    def test_accepts_existing_absolute_xlsx(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        resolved = byod_actions._validate_xlsx_path(str(f))
        assert Path(resolved).name == "bundle.xlsx"

    def test_accepts_xlsm_extension(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsm"
        f.write_bytes(b"PK\x03\x04stub")
        byod_actions._validate_xlsx_path(str(f))

    def test_rejects_non_absolute_path(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        (tmp_path / "bundle.xlsx").write_bytes(b"x")
        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path("bundle.xlsx")

    @pytest.mark.parametrize("ext", [".csv", ".txt", ".json", ".xls", ""])
    def test_rejects_non_xlsx_extension(
        self, tmp_path: Path, ext: str
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / f"bundle{ext}"
        f.write_bytes(b"x")
        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path(str(f))

    @pytest.mark.parametrize(
        "payload",
        ["/tmp/bundle\x00.xlsx", "/tmp/ev\til.xlsx", "/tmp/a\nb.xlsx"],
    )
    def test_rejects_nul_and_control_chars(self, payload: str) -> None:
        from mureo.web import byod_actions

        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path(payload)

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        with pytest.raises((ValueError, FileNotFoundError, Exception)):
            byod_actions._validate_xlsx_path(str(tmp_path / "nope.xlsx"))

    def test_rejects_directory(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        d = tmp_path / "dir.xlsx"
        d.mkdir()
        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path(str(d))

    def test_rejects_traversal_even_with_xlsx_suffix(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path("/tmp/../../etc/passwd.xlsx")

    def test_rejects_empty_string(self) -> None:
        from mureo.web import byod_actions

        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path("")

    def test_rejects_non_string(self) -> None:
        from mureo.web import byod_actions

        with pytest.raises((ValueError, TypeError, Exception)):
            byod_actions._validate_xlsx_path(123)  # type: ignore[arg-type]

    def test_symlink_to_non_xlsx_target_rejected(self, tmp_path: Path) -> None:
        """Realpath resolution must defeat a ``.xlsx`` symlink that
        points at a non-xlsx (or out-of-tree) target."""
        from mureo.web import byod_actions

        secret = tmp_path / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")
        link = tmp_path / "innocent.xlsx"
        link.symlink_to(secret)
        with pytest.raises((ValueError, Exception)):
            byod_actions._validate_xlsx_path(str(link))


# ---------------------------------------------------------------------------
# byod_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestByodStatus:
    def test_no_manifest_all_platforms_live_or_unconfigured(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.read_manifest", return_value=None
        ):
            result = byod_actions.byod_status()
        as_dict = _d(result)
        assert as_dict["status"] == "ok"
        modes = {p["platform"]: p["mode"] for p in as_dict["platforms"]}
        assert set(modes) == {"google_ads", "meta_ads"}
        assert all(m in {"live", "not_configured"} for m in modes.values())

    def test_imported_platform_reports_byod_with_rows(self) -> None:
        from mureo.web import byod_actions

        manifest = {
            "schema_version": 1,
            "platforms": {
                "google_ads": {
                    "rows": 1234,
                    "date_range": {"start": "2026-01-01", "end": "2026-01-31"},
                }
            },
        }
        with patch(
            "mureo.web.byod_actions.read_manifest", return_value=manifest
        ), patch("mureo.web.byod_actions.byod_has", return_value=True):
            result = byod_actions.byod_status()
        as_dict = _d(result)
        ga = next(
            p for p in as_dict["platforms"] if p["platform"] == "google_ads"
        )
        assert ga["mode"] == "byod"
        assert ga["rows"] == 1234
        assert ga["date_range"] == {"start": "2026-01-01", "end": "2026-01-31"}

    def test_mixed_byod_and_live(self) -> None:
        from mureo.web import byod_actions

        manifest = {
            "schema_version": 1,
            "platforms": {"google_ads": {"rows": 10, "date_range": {}}},
        }

        def _has(platform: str) -> bool:
            return platform == "google_ads"

        with patch(
            "mureo.web.byod_actions.read_manifest", return_value=manifest
        ), patch("mureo.web.byod_actions.byod_has", side_effect=_has):
            result = byod_actions.byod_status()
        modes = {p["platform"]: p["mode"] for p in _d(result)["platforms"]}
        assert modes["google_ads"] == "byod"
        assert modes["meta_ads"] in {"live", "not_configured"}

    def test_status_never_leaks_credentials(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.read_manifest", return_value=None
        ):
            result = byod_actions.byod_status()
        blob = repr(_d(result))
        assert "refresh_token" not in blob
        assert "access_token" not in blob
        assert "client_secret" not in blob

    def test_status_json_serializable(self) -> None:
        import json

        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.read_manifest", return_value=None
        ):
            result = byod_actions.byod_status()
        json.dumps(_d(result))

    def test_manifest_read_error_degrades_to_error_envelope(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.read_manifest",
            side_effect=RuntimeError("boom"),
        ):
            result = byod_actions.byod_status()
        assert _d(result)["status"] == "error"


# ---------------------------------------------------------------------------
# byod_import — success
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestByodImportSuccess:
    def _bundle_result(self) -> dict[str, Any]:
        return {
            "google_ads": {
                "source_format": "google_ads_script",
                "rows": 42,
                "date_range": {"start": "2026-01-01", "end": "2026-01-31"},
                "files": ["campaigns.csv", "ad_groups.csv"],
            }
        }

    def test_success_calls_import_bundle_and_returns_summary(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            return_value=self._bundle_result(),
        ) as mock_imp:
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        as_dict = _d(result)
        assert as_dict["status"] == "ok"
        assert "google_ads" in repr(as_dict)
        mock_imp.assert_called_once()

    def test_replace_flag_forwarded(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            return_value=self._bundle_result(),
        ) as mock_imp:
            byod_actions.byod_import(file_path=str(f), replace=True)
        assert mock_imp.call_args.kwargs.get("replace") is True

    def test_per_platform_summary_includes_rows(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            return_value=self._bundle_result(),
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert "42" in repr(_d(result))

    def test_import_does_not_echo_raw_file_bytes(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04SENSITIVE-RAW-BYTES")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            return_value=self._bundle_result(),
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert "SENSITIVE-RAW-BYTES" not in repr(_d(result))


# ---------------------------------------------------------------------------
# byod_import — validation / error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestByodImportValidation:
    def test_non_xlsx_rejected_without_calling_import_bundle(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "data.csv"
        f.write_text("a,b", encoding="utf-8")
        with patch("mureo.web.byod_actions.import_bundle") as mock_imp:
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert _d(result)["status"] == "error"
        mock_imp.assert_not_called()

    def test_non_absolute_path_rejected(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        (tmp_path / "bundle.xlsx").write_bytes(b"x")
        with patch("mureo.web.byod_actions.import_bundle") as mock_imp:
            result = byod_actions.byod_import(
                file_path="bundle.xlsx", replace=False
            )
        assert _d(result)["status"] == "error"
        mock_imp.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        ["/tmp/../../etc/passwd.xlsx", "/tmp/x/../../../root/secret.xlsx"],
    )
    def test_traversal_rejected(self, payload: str) -> None:
        from mureo.web import byod_actions

        with patch("mureo.web.byod_actions.import_bundle") as mock_imp:
            result = byod_actions.byod_import(
                file_path=payload, replace=False
            )
        assert _d(result)["status"] == "error"
        mock_imp.assert_not_called()

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        from mureo.web import byod_actions

        with patch("mureo.web.byod_actions.import_bundle") as mock_imp:
            result = byod_actions.byod_import(
                file_path=str(tmp_path / "missing.xlsx"), replace=False
            )
        assert _d(result)["status"] == "error"
        mock_imp.assert_not_called()

    @pytest.mark.parametrize(
        "payload", ["/tmp/x\x00.xlsx", "/tmp/x\ty.xlsx", "/tmp/x\ny.xlsx"]
    )
    def test_control_char_path_rejected(self, payload: str) -> None:
        from mureo.web import byod_actions

        with patch("mureo.web.byod_actions.import_bundle") as mock_imp:
            result = byod_actions.byod_import(
                file_path=payload, replace=False
            )
        assert _d(result)["status"] == "error"
        mock_imp.assert_not_called()

    def test_bundle_import_error_degrades_to_error_envelope(
        self, tmp_path: Path
    ) -> None:
        from mureo.byod.bundle import BundleImportError
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            side_effect=BundleImportError("no recognized tabs"),
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        as_dict = _d(result)
        assert as_dict["status"] == "error"

    def test_unexpected_exception_degrades_to_error(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            side_effect=RuntimeError("openpyxl exploded"),
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert _d(result)["status"] == "error"

    def test_error_envelope_does_not_leak_traceback(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            side_effect=RuntimeError("/Users/secret boom"),
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert "Traceback (most recent call last)" not in repr(_d(result))


# ---------------------------------------------------------------------------
# byod_remove
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestByodRemove:
    def test_remove_google_ads_only(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.remove_platform", return_value=True
        ) as mock_rm:
            result = byod_actions.byod_remove(
                google_ads=True, meta_ads=False
            )
        assert _d(result)["status"] == "ok"
        mock_rm.assert_called_once_with("google_ads")

    def test_remove_meta_ads_only(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.remove_platform", return_value=True
        ) as mock_rm:
            result = byod_actions.byod_remove(
                google_ads=False, meta_ads=True
            )
        assert _d(result)["status"] == "ok"
        mock_rm.assert_called_once_with("meta_ads")

    def test_nothing_to_remove_is_noop(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.remove_platform", return_value=False
        ):
            result = byod_actions.byod_remove(
                google_ads=True, meta_ads=False
            )
        assert _d(result)["status"] in {"noop", "ok"}

    def test_zero_platforms_selected_rejected(self) -> None:
        from mureo.web import byod_actions

        with patch("mureo.web.byod_actions.remove_platform") as mock_rm:
            result = byod_actions.byod_remove(
                google_ads=False, meta_ads=False
            )
        assert _d(result)["status"] == "error"
        mock_rm.assert_not_called()

    def test_both_platforms_selected_rejected(self) -> None:
        from mureo.web import byod_actions

        with patch("mureo.web.byod_actions.remove_platform") as mock_rm:
            result = byod_actions.byod_remove(
                google_ads=True, meta_ads=True
            )
        assert _d(result)["status"] == "error"
        mock_rm.assert_not_called()

    def test_remove_platform_error_degrades_to_error(self) -> None:
        from mureo.byod.installer import BYODImportError
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.remove_platform",
            side_effect=BYODImportError("unknown platform"),
        ):
            result = byod_actions.byod_remove(
                google_ads=True, meta_ads=False
            )
        assert _d(result)["status"] == "error"

    def test_remove_idempotent_second_call_noop(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.remove_platform",
            side_effect=[True, False],
        ):
            first = byod_actions.byod_remove(google_ads=True, meta_ads=False)
            second = byod_actions.byod_remove(google_ads=True, meta_ads=False)
        assert _d(first)["status"] == "ok"
        assert _d(second)["status"] in {"noop", "ok"}


# ---------------------------------------------------------------------------
# byod_clear
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestByodClear:
    def test_clear_removes_all_returns_ok(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.clear_all", return_value=True
        ) as mock_clear:
            result = byod_actions.byod_clear()
        assert _d(result)["status"] == "ok"
        mock_clear.assert_called_once()

    def test_clear_when_nothing_present_is_noop(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.clear_all", return_value=False
        ):
            result = byod_actions.byod_clear()
        assert _d(result)["status"] in {"noop", "ok"}

    def test_clear_error_degrades_to_error_envelope(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.clear_all",
            side_effect=OSError("permission denied"),
        ):
            result = byod_actions.byod_clear()
        assert _d(result)["status"] == "error"

    def test_clear_idempotent_second_call_noop(self) -> None:
        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.clear_all", side_effect=[True, False]
        ):
            first = byod_actions.byod_clear()
            second = byod_actions.byod_clear()
        assert _d(first)["status"] == "ok"
        assert _d(second)["status"] in {"noop", "ok"}

    def test_clear_result_json_serializable(self) -> None:
        import json

        from mureo.web import byod_actions

        with patch(
            "mureo.web.byod_actions.clear_all", return_value=True
        ):
            result = byod_actions.byod_clear()
        json.dumps(_d(result))


# ---------------------------------------------------------------------------
# Envelope contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvelopeContract:
    def test_import_result_is_frozen_dataclass_like(
        self, tmp_path: Path
    ) -> None:
        from mureo.web import byod_actions

        f = tmp_path / "bundle.xlsx"
        f.write_bytes(b"PK\x03\x04stub")
        with patch(
            "mureo.web.byod_actions.import_bundle",
            return_value={"google_ads": {"rows": 1}},
        ):
            result = byod_actions.byod_import(
                file_path=str(f), replace=False
            )
        assert hasattr(result, "as_dict")
        with pytest.raises(Exception):
            result.status = "tampered"  # type: ignore[misc]
