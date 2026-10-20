"""The ops history feed for the dashboard section, and the client-list
aggregate on the summary (#849).

- ``GET /api/reports/ops-history`` relays ``build_ops_history`` for one
  client and a date window: the last 30 days by default, a bad date refused
  with a 400 and a plain message, the client resolved the way
  ``/api/reports/summary`` resolves it.
- Under the client-registry seam, the summary that feeds each client card
  carries ``ops_history`` — the counts for the last 30 days — read off the
  document the summary already parsed.
"""

from __future__ import annotations

import dataclasses
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.state_store import FilesystemStateStore
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

ENDPOINT = "/api/reports/ops-history"
NOW = datetime(2026, 10, 14, 12, 0).astimezone()


def _entry(day: str, **extra: Any) -> dict[str, Any]:
    return {
        "timestamp": f"{day}T10:00:00+09:00",
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "c1",
        **extra,
    }


def _evaluation(index: int, overall: str) -> dict[str, Any]:
    return _entry(
        "2026-10-12",
        action="outcome_evaluated",
        evaluation_of=index,
        evaluation={"overall": overall, "basis": "default", "metrics": []},
    )


def _document(*, enabled: bool) -> dict[str, Any]:
    return {
        "version": "2",
        "settings": {"ops_history": {"enabled": enabled}},
        "action_log": [
            _entry("2026-10-01", observation_due="2026-10-08"),  # 0
            _entry("2026-10-03", observation_due="2026-10-08"),  # 1
            _entry("2026-10-10", observation_due="2026-10-30"),  # 2 observing
            _entry("2026-09-01"),  # 3, outside the default window
            _evaluation(0, "regressed"),
            _evaluation(1, "improved"),
        ],
    }


def _write(workspace: Path, document: dict[str, Any]) -> None:
    (workspace / "STATE.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.core import clock

    monkeypatch.setattr(clock, "server_now", lambda: NOW)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from mureo.core.runtime_context import (
        default_runtime_context,
        reset_runtime_context,
    )

    reset_runtime_context()
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    yield tmp_path
    reset_runtime_context()


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _get(wiz: ConfigureWizard, path: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:{wiz.port}{path}"
    with urllib.request.urlopen(url, timeout=2.0) as res:
        body: dict[str, Any] = json.loads(res.read().decode("utf-8"))
    return body


def _get_error(wiz: ConfigureWizard, path: str) -> tuple[int, dict[str, Any]]:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(wiz, path)
    return excinfo.value.code, json.loads(excinfo.value.read())


def _days(body: dict[str, Any]) -> list[str]:
    return [item["actions"][0]["timestamp"][:10] for item in body["items"]]


class TestEndpoint:
    def test_the_default_window_is_the_last_thirty_days(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _write(workspace, _document(enabled=True))
        body = _get(wizard, ENDPOINT)
        # Thirty calendar days ending today, both ends included.
        assert body["since"] == "2026-09-15"
        assert body["until"] == "2026-10-14"
        assert body["server_today"] == "2026-10-14"
        assert body["enabled"] is True
        assert _days(body) == ["2026-10-10", "2026-10-03", "2026-10-01"]

    def test_an_explicit_window(self, wizard: ConfigureWizard, workspace: Path) -> None:
        _write(workspace, _document(enabled=True))
        body = _get(wizard, ENDPOINT + "?since=2026-08-01&until=2026-10-02")
        assert (body["since"], body["until"]) == ("2026-08-01", "2026-10-02")
        assert _days(body) == ["2026-10-01", "2026-09-01"]

    def test_one_bound_keeps_the_other_default(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _write(workspace, _document(enabled=True))
        body = _get(wizard, ENDPOINT + "?since=2026-10-05")
        assert (body["since"], body["until"]) == ("2026-10-05", "2026-10-14")

    @pytest.mark.parametrize(
        ("query", "named"),
        [
            ("since=yesterday", "since"),
            ("until=2026-13-01", "until"),
            ("since=2026-10-05&until=2026-10-01", "before"),
            # Forms date.fromisoformat accepts on 3.11+ but the API does not.
            ("since=20261005", "since"),
            ("until=2026-W41-1", "until"),
        ],
    )
    def test_a_bad_date_is_a_400_with_a_plain_message(
        self, wizard: ConfigureWizard, workspace: Path, query: str, named: str
    ) -> None:
        _write(workspace, _document(enabled=True))
        status, body = _get_error(wizard, f"{ENDPOINT}?{query}")
        assert status == 400
        assert named in body["error"]
        assert "yesterday" not in body["error"]

    def test_disabled_still_answers_with_enabled_false(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _write(workspace, _document(enabled=False))
        body = _get(wizard, ENDPOINT)
        assert body["enabled"] is False

    def test_a_missing_document_is_empty_and_disabled(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _get(wizard, ENDPOINT)
        assert body["enabled"] is False
        assert body["items"] == []

    def test_the_client_is_echoed(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _write(workspace, _document(enabled=True))
        assert _get(wizard, ENDPOINT + "?client=acme")["client"] == "acme"


class _Roster(FilesystemStateStore):
    """A store with a client registry, each client in its own folder."""

    def __init__(self, workspace: Path, clients: dict[str, Path]) -> None:
        super().__init__(workspace)
        self.clients = clients

    def list_clients(self) -> list[dict[str, Any]]:
        return [{"slug": s, "name": s, "active": True} for s in self.clients]

    def state_store_for_client(self, slug: str) -> FilesystemStateStore:
        return FilesystemStateStore(self.clients[slug])


@pytest.fixture
def roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Path]]:
    from mureo.core.runtime_context import (
        default_runtime_context,
        reset_runtime_context,
    )

    clients = {"acme": tmp_path / "acme", "globex": tmp_path / "globex"}
    for folder in clients.values():
        folder.mkdir()
    reset_runtime_context()
    ctx = dataclasses.replace(
        default_runtime_context(workspace=tmp_path),
        state_store=_Roster(tmp_path, clients),
    )
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    yield clients
    reset_runtime_context()


class TestClientResolution:
    def test_each_client_reads_its_own_file(
        self, wizard: ConfigureWizard, roster: dict[str, Path]
    ) -> None:
        _write(roster["acme"], _document(enabled=True))
        _write(roster["globex"], _document(enabled=False))
        acme = _get(wizard, ENDPOINT + "?client=acme")
        globex = _get(wizard, ENDPOINT + "?client=globex")
        assert (acme["client"], acme["enabled"]) == ("acme", True)
        assert (globex["client"], globex["enabled"]) == ("globex", False)
        assert len(acme["items"]) == 3


_ZERO_COUNTS = {
    "changes": 0,
    "improved": 0,
    "regressed": 0,
    "regressed_open": 0,
    "inconclusive": 0,
    "observing": 0,
}


class TestSummaryAggregate:
    def test_each_client_row_carries_the_counts(self, roster: dict[str, Path]) -> None:
        from mureo.web.reports import build_report_summary

        _write(roster["acme"], _document(enabled=True))
        summary = build_report_summary(client="acme")
        assert summary["ops_history"] == {
            "enabled": True,
            "window_days": 30,
            "changes": 3,
            "improved": 1,
            "regressed": 1,
            "regressed_open": 1,
            "inconclusive": 0,
            "observing": 1,
        }

    def test_a_disabled_client_carries_zero(self, roster: dict[str, Path]) -> None:
        from mureo.web.reports import build_report_summary

        _write(roster["globex"], _document(enabled=False))
        assert build_report_summary(client="globex")["ops_history"] == {
            "enabled": False,
            "window_days": 30,
            **_ZERO_COUNTS,
        }

    def test_a_single_workspace_summary_has_no_aggregate(self, workspace: Path) -> None:
        from mureo.web.reports import build_report_summary

        _write(workspace, _document(enabled=True))
        assert "ops_history" not in build_report_summary()

    def test_the_document_is_read_once(
        self, roster: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mureo.web.reports as reports

        _write(roster["acme"], _document(enabled=True))
        calls: list[object] = []
        real = reports._read_state_safe

        def counting(store: Any) -> Any:
            calls.append(store)
            return real(store)

        monkeypatch.setattr(reports, "_read_state_safe", counting)
        reports.build_report_summary(client="acme")
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# The section's assets
# ---------------------------------------------------------------------------

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"
_MODULE = "dashboard_ops_history_section.js"
_SECTION_KEY = re.compile(r"(?<![a-z_])ops_history_section\.[a-z_]+")
# The module's own `t("key")` helper prefixes `ops_history_section.`.
_T_CALL = re.compile(r'\bt\("([a-z_]*[a-z])"')
# Keys the module builds from a value rather than spells out.
_FAMILIES = {
    "state_": (
        "proposed",
        "adopted",
        "executed",
        "observing",
        "evaluated",
        "skipped",
        "rejected",
        "deferred",
    ),
    "verdict_": ("improved", "regressed", "inconclusive"),
    "direction_": ("up", "down", "hold"),
}


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


class TestAssets:
    def test_the_module_is_served_and_loaded_before_the_reports_view(self) -> None:
        from mureo.web.handlers import _STATIC_ALLOWLIST

        assert _MODULE in _STATIC_ALLOWLIST
        html = _read("app.html")
        script = f"/static/{_MODULE}"
        assert html.index("/static/dashboard_reports_detail.js") < html.index(script)
        assert html.index(script) < html.index("/static/dashboard_reports.js")
        harness = (Path(__file__).parent / "js" / "dom_harness.js").read_text(
            encoding="utf-8"
        )
        assert harness.index(f'"{_MODULE}"') < harness.index('"dashboard_reports.js"')

    def test_the_section_is_not_in_the_static_page(self) -> None:
        """It is built by the module, so a disabled workspace has none."""
        assert "data-ops-history-section" not in _read("app.html")

    @pytest.mark.parametrize("sink", ["innerHTML", "outerHTML", "insertAdjacentHTML"])
    def test_free_text_never_goes_through_an_html_sink(self, sink: str) -> None:
        assert sink not in _read(_MODULE)

    def test_the_weak_rationale_threshold_is_one_documented_constant(self) -> None:
        assert "WEAK_RATIONALE_MIN_CHARS = 20" in _read(_MODULE)
        docs = Path(__file__).resolve().parent.parent / "docs" / "ops-history.md"
        assert "WEAK_RATIONALE_MIN_CHARS" in docs.read_text(encoding="utf-8")

    def test_every_key_is_translated_in_both_locales(self) -> None:
        used: set[str] = set()
        for name in (_MODULE, "dashboard_reports_cards.js", "reports_triage.js"):
            used |= set(_SECTION_KEY.findall(_read(name)))
        used |= {f"ops_history_section.{k}" for k in _T_CALL.findall(_read(_MODULE))}
        for prefix, values in _FAMILIES.items():
            used |= {f"ops_history_section.{prefix}{v}" for v in values}
        assert len(used) >= 20
        i18n = json.loads(_read("i18n.json"))
        for locale in ("en", "ja"):
            for key in sorted(used):
                assert key in i18n[locale], f"{key} missing from {locale!r}"
                assert str(i18n[locale][key]).strip() != ""
        en = {k for k in i18n["en"] if k.startswith("ops_history_section.")}
        ja = {k for k in i18n["ja"] if k.startswith("ops_history_section.")}
        assert en == ja
        assert i18n["ja"]["ops_history_section.title"] == "運用履歴"
        assert i18n["ja"]["ops_history_section.note"] == (
            "前後の比較は参考値です。市況・季節の影響を含みます。"
        )
        assert i18n["en"]["ops_history_section.note"] == (
            "Before/after comparison is indicative; market and seasonal "
            "effects are included."
        )
