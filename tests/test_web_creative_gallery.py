"""Data layer behind the Creative Studio gallery tab (#409).

``mureo.web.creative_gallery`` enumerates the ``creative_studio/<run>/``
directories of a workspace (resolved through the same multi-account
StateStore seams the reports dashboard established) and resolves gallery
image paths with strict containment so the image route can never serve a
file outside the gallery tree.

The runtime context is reset around every test so an injected store never
leaks into another test (mirrors test_web_reports.py).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)
from mureo.core.state_store import FilesystemStateStore
from mureo.web.creative_gallery import list_creative_runs, resolve_gallery_image

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Point the active runtime context at ``workspace``.

    The gallery resolves its store through the reports module's seam
    helpers, so the patch target is ``mureo.web.reports``.
    """
    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.reports.get_runtime_context", lambda: ctx)


def _make_run(
    workspace: Path,
    run_id: str,
    images: tuple[str, ...] = ("openai_00.png",),
    manifest: dict[str, Any] | None = None,
) -> Path:
    run_dir = workspace / "creative_studio" / run_id
    run_dir.mkdir(parents=True)
    for name in images:
        (run_dir / name).write_bytes(b"\x89PNG fake")
    if manifest is not None:
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    return run_dir


# ---------------------------------------------------------------------------
# list_creative_runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListCreativeRuns:
    def test_lists_runs_newest_first_with_images_and_manifest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _make_run(
            tmp_path,
            "20260101T000000Z_aaaaaa",
            images=("openai_00.png", "google_00.png"),
            manifest={
                "provider": "openai",
                "prompt": "sunny lifestyle hero",
                "template": "hero_overlay",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        _make_run(tmp_path, "20260202T000000Z_bbbbbb")  # no manifest
        _use_workspace(monkeypatch, tmp_path)

        payload = list_creative_runs()

        runs = payload["runs"]
        assert [r["run_id"] for r in runs] == [
            "20260202T000000Z_bbbbbb",
            "20260101T000000Z_aaaaaa",
        ]
        newest, oldest = runs
        # Missing manifest is tolerated — empty summary, never an error.
        assert newest["images"] == ["openai_00.png"]
        assert newest["prompt"] == ""
        # Manifest summary is surfaced, images sorted.
        assert oldest["images"] == ["google_00.png", "openai_00.png"]
        assert oldest["prompt"] == "sunny lifestyle hero"
        assert oldest["provider"] == "openai"
        assert oldest["template"] == "hero_overlay"
        assert oldest["created_at"] == "2026-01-01T00:00:00+00:00"

    def test_ignores_non_png_and_unsafe_entries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run_dir = _make_run(tmp_path, "20260101T000000Z_cccccc")
        (run_dir / "note.txt").write_text("x")
        (run_dir / "manifest.json").write_text("{}")
        (run_dir / "nested").mkdir()
        _use_workspace(monkeypatch, tmp_path)

        runs = list_creative_runs()["runs"]
        assert runs[0]["images"] == ["openai_00.png"]

    def test_caps_run_count(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for index in range(3):
            _make_run(tmp_path, f"2026010{index + 1}T000000Z_{index:06d}")
        _use_workspace(monkeypatch, tmp_path)

        runs = list_creative_runs(limit=2)["runs"]
        assert len(runs) == 2
        assert runs[0]["run_id"].startswith("20260103")

    def test_missing_gallery_dir_is_empty_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _use_workspace(monkeypatch, tmp_path)
        assert list_creative_runs()["runs"] == []

    def test_multi_account_seam_resolves_per_client_workspace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A store advertising ``state_store_for_client`` scopes the gallery
        to that client's workspace — the multi-account requirement."""
        acme_ws = tmp_path / "acme"
        _make_run(acme_ws, "20260101T000000Z_acme00")

        class _MultiStore(FilesystemStateStore):
            def state_store_for_client(self, slug: str) -> FilesystemStateStore:
                assert slug == "acme"
                return FilesystemStateStore(workspace=acme_ws)

        ctx = dataclasses.replace(
            default_runtime_context(workspace=tmp_path),
            state_store=_MultiStore(workspace=tmp_path),
        )
        monkeypatch.setattr("mureo.web.reports.get_runtime_context", lambda: ctx)

        runs = list_creative_runs("acme")["runs"]
        assert [r["run_id"] for r in runs] == ["20260101T000000Z_acme00"]
        # And the active (no-client) view stays on the operator workspace.
        assert list_creative_runs()["runs"] == []


# ---------------------------------------------------------------------------
# resolve_gallery_image — strict containment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveGalleryImage:
    def test_resolves_existing_image(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run_dir = _make_run(tmp_path, "20260101T000000Z_dddddd")
        _use_workspace(monkeypatch, tmp_path)

        resolved = resolve_gallery_image(
            None, "20260101T000000Z_dddddd", "openai_00.png"
        )
        assert resolved == (run_dir / "openai_00.png").resolve()

    @pytest.mark.parametrize(
        ("run_id", "filename"),
        [
            ("..", "x.png"),
            ("20260101T000000Z_dddddd", "../../STATE.json"),
            ("20260101T000000Z_dddddd", "/etc/passwd"),
            ("20260101T000000Z_dddddd", "a/b.png"),
            ("20260101T000000Z_dddddd", "manifest.json"),
            ("20260101T000000Z_dddddd", "missing.png"),
            ("nosuchrun", "openai_00.png"),
        ],
    )
    def test_refuses_unsafe_or_missing_components(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        run_id: str,
        filename: str,
    ) -> None:
        _make_run(tmp_path, "20260101T000000Z_dddddd")
        _use_workspace(monkeypatch, tmp_path)
        assert resolve_gallery_image(None, run_id, filename) is None

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation needs privileges"
    )
    def test_refuses_symlink_escape(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run_dir = _make_run(tmp_path, "20260101T000000Z_eeeeee")
        secret = tmp_path / "outside.png"
        secret.write_bytes(b"\x89PNG secret")
        (run_dir / "link.png").symlink_to(secret)
        _use_workspace(monkeypatch, tmp_path)

        assert (
            resolve_gallery_image(None, "20260101T000000Z_eeeeee", "link.png") is None
        )


# ---------------------------------------------------------------------------
# list_creative_runs — the LISTING must enforce the same symlink containment
# as the image route: a symlink planted under creative_studio/ must not leak
# outside directory listings or manifest content (cross-client scenario).
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs privileges"
)
class TestListingSymlinkContainment:
    def test_symlinked_run_dir_is_excluded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A run-dir symlink pointing outside the gallery must not have its
        target's filenames or manifest content enumerated."""
        outside = tmp_path / "sensitive_outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(b"\x89PNG secret")
        (outside / "manifest.json").write_text(
            json.dumps({"prompt": "SECRET internal prompt"}), encoding="utf-8"
        )
        _make_run(tmp_path, "20260101T000000Z_ffffff")
        base = tmp_path / "creative_studio"
        (base / "20260102T000000Z_symrun").symlink_to(outside)
        _use_workspace(monkeypatch, tmp_path)

        runs = list_creative_runs()["runs"]
        assert [r["run_id"] for r in runs] == ["20260101T000000Z_ffffff"]
        assert "SECRET" not in json.dumps(runs)

    def test_symlinked_image_and_manifest_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Inside a REAL run dir, symlinked entries (an image or the
        manifest itself) must be ignored rather than followed."""
        run_dir = _make_run(tmp_path, "20260101T000000Z_gggggg")
        secret_png = tmp_path / "outside.png"
        secret_png.write_bytes(b"\x89PNG secret")
        (run_dir / "leak.png").symlink_to(secret_png)
        secret_manifest = tmp_path / "outside_manifest.json"
        secret_manifest.write_text(
            json.dumps({"prompt": "SECRET manifest"}), encoding="utf-8"
        )
        (run_dir / "manifest.json").symlink_to(secret_manifest)
        _use_workspace(monkeypatch, tmp_path)

        runs = list_creative_runs()["runs"]
        assert runs[0]["images"] == ["openai_00.png"]
        assert runs[0]["prompt"] == ""


@pytest.mark.unit
class TestListingFaultIsolation:
    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX permission semantics"
    )
    def test_one_unreadable_run_does_not_blank_the_gallery(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A single unreadable run directory (race with a live generation,
        permissions hiccup) must be skipped — not erase the whole history."""
        import os

        _make_run(tmp_path, "20260101T000000Z_okokok")
        bad = _make_run(tmp_path, "20260102T000000Z_broken")
        os.chmod(bad, 0)
        try:
            _use_workspace(monkeypatch, tmp_path)
            runs = list_creative_runs()["runs"]
        finally:
            os.chmod(bad, 0o700)
        assert [r["run_id"] for r in runs] == ["20260101T000000Z_okokok"]
