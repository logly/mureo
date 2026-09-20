"""The Guardrails ``currency`` bullet, written from ``mureo configure`` (#786).

Three layers, in the order a change breaks them:

- the option table (what the dropdown may offer at all);
- :func:`read_currency` / :func:`write_currency` — a surgical upsert into
  ``## Guardrails`` that must leave every other line of the operator's
  STRATEGY.md exactly as it found it, and must be readable back by the
  policy gate that the bullet exists for;
- the two routes, on a real server, with the CSRF gate the rest of the
  configure UI's writes go through.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import StrategyEntry
from mureo.context.strategy import (
    mutate_strategy_file,
    parse_strategy,
    read_strategy_file,
)
from mureo.policy.strategy_gate import guardrails_from_strategy_text
from mureo.web.server import ConfigureWizard
from mureo.web.strategy_currency import (
    CURRENCY_OPTIONS,
    StrategyCurrencyError,
    read_currency,
    write_currency,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path


# ---------------------------------------------------------------------------
# The option table
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCurrencyOptions:
    def test_codes_are_sorted_and_unique(self) -> None:
        codes = [option["code"] for option in CURRENCY_OPTIONS]
        assert codes == sorted(codes)
        assert len(codes) == len(set(codes))

    def test_carries_the_meta_offset_for_each_code(self) -> None:
        by_code = {option["code"]: option["minor_units"] for option in CURRENCY_OPTIONS}
        assert by_code["EUR"] == 100
        assert by_code["JPY"] == 1

    def test_meta_credits_are_not_an_account_currency(self) -> None:
        """FBZ is Meta's internal credits unit — never an ad account's."""
        assert "FBZ" not in {option["code"] for option in CURRENCY_OPTIONS}


# ---------------------------------------------------------------------------
# read_currency
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadCurrency:
    def test_missing_file_reads_as_nothing_set(self, tmp_path: Path) -> None:
        state = read_currency(tmp_path / "STRATEGY.md")
        assert state == {
            "currency": None,
            "raw_value": None,
            "guardrails_present": False,
            "exists": False,
        }

    def test_file_without_a_guardrails_section(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text("# Strategy\n\n## Persona\n30s\n", encoding="utf-8")
        state = read_currency(path)
        assert state["exists"] is True
        assert state["guardrails_present"] is False
        assert state["currency"] is None
        assert state["raw_value"] is None

    def test_a_lower_case_code_is_normalised_and_the_raw_kept(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n- currency: eur\n", encoding="utf-8"
        )
        state = read_currency(path)
        assert state["currency"] == "EUR"
        assert state["raw_value"] == "eur"
        assert state["guardrails_present"] is True

    def test_an_unknown_code_comes_back_as_raw_only(self, tmp_path: Path) -> None:
        """The gate drops it; the dashboard has to be able to SAY so."""
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n- currency: XYZ\n", encoding="utf-8"
        )
        state = read_currency(path)
        assert state["currency"] is None
        assert state["raw_value"] == "XYZ"

    def test_a_guardrails_section_without_the_bullet(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n- max_total_daily_budget: 900\n",
            encoding="utf-8",
        )
        state = read_currency(path)
        assert state["guardrails_present"] is True
        assert state["currency"] is None
        assert state["raw_value"] is None


# ---------------------------------------------------------------------------
# write_currency
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteCurrency:
    def test_no_file_creates_one_with_just_the_bullet(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        state = write_currency(path, "EUR")
        assert path.read_text(encoding="utf-8") == (
            "# Strategy\n\n## Guardrails\n- currency: EUR\n"
        )
        assert state["currency"] == "EUR"
        assert state["exists"] is True

    def test_other_sections_survive_byte_identically(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        before = "# Strategy\n\n## Persona\n30s\n\n## USP\ncheapest\n"
        path.write_text(before, encoding="utf-8")
        write_currency(path, "EUR")
        after = path.read_text(encoding="utf-8")
        assert after.startswith(before)
        assert after == before + "\n## Guardrails\n- currency: EUR\n"

    def test_the_bullet_goes_first_and_the_caps_are_untouched(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n"
            "- max_total_daily_budget: 900\n"
            "- blocked_operations: campaign_delete\n",
            encoding="utf-8",
        )
        write_currency(path, "USD")
        assert path.read_text(encoding="utf-8") == (
            "# Strategy\n\n## Guardrails\n"
            "- currency: USD\n"
            "- max_total_daily_budget: 900\n"
            "- blocked_operations: campaign_delete\n"
        )

    def test_an_existing_bullet_is_replaced_in_place(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n"
            "- max_total_daily_budget: 900\n"
            "- currency: JPY\n"
            "- blocked_operations: campaign_delete\n",
            encoding="utf-8",
        )
        write_currency(path, "EUR")
        assert path.read_text(encoding="utf-8") == (
            "# Strategy\n\n## Guardrails\n"
            "- max_total_daily_budget: 900\n"
            "- currency: EUR\n"
            "- blocked_operations: campaign_delete\n"
        )

    def test_clearing_removes_the_bullet_and_keeps_the_caps(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n"
            "- currency: EUR\n"
            "- max_total_daily_budget: 900\n",
            encoding="utf-8",
        )
        state = write_currency(path, None)
        assert path.read_text(encoding="utf-8") == (
            "# Strategy\n\n## Guardrails\n- max_total_daily_budget: 900\n"
        )
        assert state["currency"] is None
        assert state["guardrails_present"] is True

    def test_clearing_what_is_not_there_does_not_rewrite_the_file(
        self, tmp_path: Path
    ) -> None:
        """A no-op write would churn the mtime and drop a pointless backup
        beside a file the operator did not ask us to touch."""
        path = tmp_path / "STRATEGY.md"
        before = "# Strategy\n\n## Guardrails\n- max_total_daily_budget: 900\n"
        path.write_text(before, encoding="utf-8")
        mtime = path.stat().st_mtime_ns
        write_currency(path, None)
        assert path.read_text(encoding="utf-8") == before
        assert path.stat().st_mtime_ns == mtime
        assert list(tmp_path.glob("STRATEGY.md.bak*")) == []

    def test_clearing_does_not_create_a_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        state = write_currency(path, None)
        assert not path.exists()
        assert state["exists"] is False

    def test_a_change_to_an_existing_file_is_backed_up_first(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STRATEGY.md"
        before = "# Strategy\n\n## Guardrails\n- currency: JPY\n"
        path.write_text(before, encoding="utf-8")
        write_currency(path, "EUR")
        backups = list(tmp_path.glob("STRATEGY.md.bak.*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == before

    def test_an_unknown_code_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(StrategyCurrencyError) as excinfo:
            write_currency(tmp_path / "STRATEGY.md", "XYZ")
        assert excinfo.value.code == "invalid_currency"
        assert not (tmp_path / "STRATEGY.md").exists()

    def test_the_writer_is_strict_about_case(self, tmp_path: Path) -> None:
        """The handler upper-cases at the boundary; the writer does not
        guess, so a caller that skipped the boundary fails loudly."""
        with pytest.raises(StrategyCurrencyError) as excinfo:
            write_currency(tmp_path / "STRATEGY.md", "eur")
        assert excinfo.value.code == "invalid_currency"

    def test_the_gate_reads_back_what_the_dashboard_wrote(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(
            "# Strategy\n\n## Guardrails\n- max_total_daily_budget: 900\n",
            encoding="utf-8",
        )
        write_currency(path, "EUR")
        text = path.read_text(encoding="utf-8")
        assert guardrails_from_strategy_text(text).currency == "EUR"
        assert [e.title for e in parse_strategy(text)] == ["Guardrails"]


# ---------------------------------------------------------------------------
# mutate_strategy_file — the locked read-modify-write the writer runs in
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMutateStrategyFile:
    def test_a_missing_file_reads_as_no_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "STRATEGY.md"
        seen: list[list[StrategyEntry]] = []

        def mutate(entries: list[StrategyEntry]) -> list[StrategyEntry]:
            seen.append(entries)
            return [StrategyEntry("usp", "USP", "cheapest")]

        result = mutate_strategy_file(path, mutate)
        assert seen == [[]]
        assert result == [StrategyEntry("usp", "USP", "cheapest")]
        assert read_strategy_file(path) == result

    def test_the_lock_sidecar_is_used(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        mutate_strategy_file(path, lambda entries: entries)
        assert (tmp_path / "STRATEGY.md.lock").exists()


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the one client seam at a temp workspace."""
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
    """Start a ConfigureWizard bound to 127.0.0.1:0."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
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


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _get(wiz: ConfigureWizard, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(_url(wiz, path), timeout=2.0) as res:
        body: dict[str, Any] = json.loads(res.read().decode("utf-8"))
    return body


def _post(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any],
    *,
    csrf: str | None = "use_session",
) -> HTTPResponse:
    headers = {"Content-Type": "application/json"}
    if csrf == "use_session":
        headers["X-CSRF-Token"] = wiz.session.csrf_token
    elif csrf is not None:
        headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(
        _url(wiz, path), data=json.dumps(payload).encode(), method="POST"
    )
    for key, value in headers.items():
        req.add_header(key, value)
    return urllib.request.urlopen(req, timeout=2.0)


def _post_json(
    wiz: ConfigureWizard, path: str, payload: dict[str, Any]
) -> dict[str, Any]:
    with _post(wiz, path, payload) as res:
        body: dict[str, Any] = json.loads(res.read().decode("utf-8"))
    return body


@pytest.mark.unit
class TestStrategyCurrencyRoutes:
    def test_get_reports_the_options_and_the_active_path(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _get(wizard, "/api/strategy/currency")
        assert body["status"] == "ok"
        assert body["currency"] is None
        assert body["client"] is None
        assert body["path"] == str(workspace / "STRATEGY.md")
        assert {"code": "EUR", "minor_units": 100} in body["options"]

    def test_post_upper_cases_writes_and_is_read_back(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _post_json(wizard, "/api/strategy/currency", {"currency": "eur"})
        assert body["status"] == "ok"
        assert body["currency"] == "EUR"
        text = (workspace / "STRATEGY.md").read_text(encoding="utf-8")
        assert "- currency: EUR" in text
        assert _get(wizard, "/api/strategy/currency")["currency"] == "EUR"

    def test_post_empty_clears_the_bullet(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _post_json(wizard, "/api/strategy/currency", {"currency": "EUR"})
        body = _post_json(wizard, "/api/strategy/currency", {"currency": ""})
        assert body["currency"] is None
        text = (workspace / "STRATEGY.md").read_text(encoding="utf-8")
        assert "currency" not in text

    def test_post_refuses_an_unknown_code(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, "/api/strategy/currency", {"currency": "XYZ"})
        assert excinfo.value.code == 400
        assert json.loads(excinfo.value.read())["error"] == "invalid_currency"
        assert not (workspace / "STRATEGY.md").exists()

    def test_post_refuses_a_non_string(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, "/api/strategy/currency", {"currency": 5})
        assert excinfo.value.code == 400
        assert json.loads(excinfo.value.read())["error"] == "invalid_currency"

    def test_post_needs_the_csrf_header(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, "/api/strategy/currency", {"currency": "EUR"}, csrf=None)
        assert excinfo.value.code == 403
        assert not (workspace / "STRATEGY.md").exists()

    def test_a_client_slug_is_echoed_and_ignored_on_oss(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        """OSS is one workspace; the picker exists for the Agency seam."""
        body = _post_json(
            wizard, "/api/strategy/currency", {"currency": "EUR", "client": "acme"}
        )
        assert body["client"] == "acme"
        assert body["path"] == str(workspace / "STRATEGY.md")
        assert _get(wizard, "/api/strategy/currency?client=acme")["client"] == "acme"
