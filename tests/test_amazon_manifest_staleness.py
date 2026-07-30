"""Amazon tool-manifest staleness (audit #47).

``generate_manifest`` has always written ``generated_at``; nothing ever read
it. A manifest is a snapshot of someone else's tool surface, so an old one
means mureo is exposing tools that may no longer exist (or hiding ones that
now do) with no signal anywhere. These tests pin the age helpers and the three
surfaces that report them: the configure-UI status row, the CLI refresh
command, and a one-shot bridge warning.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from mureo.amazon_ads import manifest as manifest_mod
from mureo.amazon_ads.manifest import (
    DEFAULT_MANIFEST_MAX_AGE_DAYS,
    MANIFEST_MAX_AGE_ENV,
    is_manifest_stale,
    manifest_age_days,
    manifest_max_age_days,
)


def _write(path: Path, generated_at: Any) -> Path:
    doc: dict[str, Any] = {"region": "na", "tools": []}
    if generated_at is not None:
        doc["generated_at"] = generated_at
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _iso(days_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.isoformat(timespec="seconds")


@pytest.mark.unit
class TestManifestMaxAgeDays:
    def test_defaults_to_30(self, monkeypatch: Any) -> None:
        monkeypatch.delenv(MANIFEST_MAX_AGE_ENV, raising=False)
        assert manifest_max_age_days() == DEFAULT_MANIFEST_MAX_AGE_DAYS
        assert DEFAULT_MANIFEST_MAX_AGE_DAYS == 30

    def test_env_override(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(MANIFEST_MAX_AGE_ENV, "7")
        assert manifest_max_age_days() == 7.0

    @pytest.mark.parametrize("raw", ["", "  ", "soon", "-3", "0"])
    def test_unusable_override_falls_back_to_the_default(
        self, monkeypatch: Any, raw: str
    ) -> None:
        monkeypatch.setenv(MANIFEST_MAX_AGE_ENV, raw)
        assert manifest_max_age_days() == DEFAULT_MANIFEST_MAX_AGE_DAYS


@pytest.mark.unit
class TestManifestAgeDays:
    def test_missing_file_is_none(self, tmp_path: Path) -> None:
        assert manifest_age_days(tmp_path / "nope.json") is None

    @pytest.mark.parametrize("generated_at", [None, "", "not-a-date", 12345, {"a": 1}])
    def test_unusable_timestamp_is_none(
        self, tmp_path: Path, generated_at: Any
    ) -> None:
        path = _write(tmp_path / "m.json", generated_at)
        assert manifest_age_days(path) is None

    def test_malformed_json_is_none(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text("{not json", encoding="utf-8")
        assert manifest_age_days(path) is None

    def test_reads_the_age_in_days(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "m.json", _iso(3))
        age = manifest_age_days(path)
        assert age is not None
        assert 2.9 < age < 3.1

    def test_a_z_suffixed_timestamp_is_understood(self, tmp_path: Path) -> None:
        moment = datetime.now(timezone.utc) - timedelta(days=2)
        path = _write(
            tmp_path / "m.json",
            moment.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        )
        age = manifest_age_days(path)
        assert age is not None
        assert 1.9 < age < 2.1

    def test_a_naive_timestamp_is_read_as_local(self, tmp_path: Path) -> None:
        moment = datetime.now().astimezone() - timedelta(days=5)
        path = _write(tmp_path / "m.json", moment.replace(tzinfo=None).isoformat())
        age = manifest_age_days(path)
        assert age is not None
        assert 4.9 < age < 5.1

    def test_a_future_timestamp_clamps_to_zero(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "m.json", _iso(-10))
        assert manifest_age_days(path) == 0.0

    def test_it_uses_the_injectable_clock(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from mureo.core import clock

        written = datetime.now(timezone.utc)
        path = _write(tmp_path / "m.json", written.isoformat(timespec="seconds"))
        monkeypatch.setattr(
            clock, "server_now", lambda: (written + timedelta(days=42)).astimezone()
        )
        age = manifest_age_days(path)
        assert age is not None
        assert 41.9 < age < 42.1


@pytest.mark.unit
class TestIsManifestStale:
    def test_fresh_is_not_stale(self, tmp_path: Path) -> None:
        assert is_manifest_stale(_write(tmp_path / "m.json", _iso(1))) is False

    def test_old_is_stale(self, tmp_path: Path) -> None:
        assert is_manifest_stale(_write(tmp_path / "m.json", _iso(45))) is True

    def test_unknown_age_is_not_stale(self, tmp_path: Path) -> None:
        """Never claim staleness we cannot prove — an absent manifest is
        reported as absent, not as stale."""
        assert is_manifest_stale(tmp_path / "nope.json") is False

    def test_the_threshold_is_overridable(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        path = _write(tmp_path / "m.json", _iso(10))
        assert is_manifest_stale(path) is False
        monkeypatch.setenv(MANIFEST_MAX_AGE_ENV, "7")
        assert is_manifest_stale(path) is True

    def test_default_path_is_the_manifest_path(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        path = _write(tmp_path / "amazon_tools.json", _iso(45))
        monkeypatch.setattr(manifest_mod, "manifest_path", lambda: path)
        assert is_manifest_stale() is True


@pytest.mark.unit
class TestBridgeStaleWarning:
    """The bridge warns ONCE per process when it serves a stale manifest.

    ``mcp_tools()`` runs at mureo server start and on every tool-list refresh,
    so a per-call warning would be log spam; silence would be worse — the
    operator would never learn the tool list is months old. And it stays a
    warning: an old manifest still serves its tools, because refusing to would
    break a working setup over a heuristic.
    """

    def _bridge(self, tmp_path: Path, days_old: float) -> Any:
        from mureo.amazon_ads.bridge import AmazonAdsBridge

        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "amazon_tools.json"
        path.write_text(
            json.dumps(
                {
                    "generated_at": _iso(days_old),
                    "tools": [
                        {
                            "name": "campaign_management-list_campaigns",
                            "description": "x",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return AmazonAdsBridge(manifest_path=path)

    @pytest.fixture(autouse=True)
    def _reset_flag(self) -> Any:
        from mureo.amazon_ads import bridge as bridge_mod

        bridge_mod._stale_manifest_warned = False
        yield
        bridge_mod._stale_manifest_warned = False

    def test_a_stale_manifest_warns_once(self, tmp_path: Path, caplog: Any) -> None:
        bridge = self._bridge(tmp_path, 90)
        with caplog.at_level("WARNING", logger="mureo.amazon_ads.bridge"):
            assert len(bridge.mcp_tools()) == 1
            assert len(bridge.mcp_tools()) == 1
        warnings = [r for r in caplog.records if "manifest is stale" in r.getMessage()]
        assert len(warnings) == 1
        assert "refresh-manifest" in warnings[0].getMessage()

    def test_a_fresh_manifest_does_not_warn(self, tmp_path: Path, caplog: Any) -> None:
        bridge = self._bridge(tmp_path, 1)
        with caplog.at_level("WARNING", logger="mureo.amazon_ads.bridge"):
            assert len(bridge.mcp_tools()) == 1
        assert [
            r for r in caplog.records if "manifest is stale" in r.getMessage()
        ] == []

    def test_an_absent_manifest_does_not_warn(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        from mureo.amazon_ads.bridge import AmazonAdsBridge

        bridge = AmazonAdsBridge(manifest_path=tmp_path / "nope.json")
        with caplog.at_level("WARNING", logger="mureo.amazon_ads.bridge"):
            assert bridge.mcp_tools() == ()
        assert caplog.records == []

    def test_a_fresh_read_does_not_suppress_a_later_warning(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        """The one-shot latch arms on an actual warning, not on any read."""
        fresh = self._bridge(tmp_path, 1)
        fresh.mcp_tools()
        stale = self._bridge(tmp_path / "old", 90)
        with caplog.at_level("WARNING", logger="mureo.amazon_ads.bridge"):
            stale.mcp_tools()
        assert (
            len([r for r in caplog.records if "manifest is stale" in r.getMessage()])
            == 1
        )
