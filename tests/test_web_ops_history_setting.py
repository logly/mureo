"""The ops history switch, toggled from ``mureo configure`` (#848).

Three layers:

- :func:`read_setting` / :func:`write_setting` against a STATE.json on
  disk, including that a no-op never creates or rewrites the file;
- the two routes on a real server, behind the CSRF gate every configure
  write goes through, with the ``client`` seam the currency routes have;
- the card's markup, script wiring and EN/JA strings, and that it is cut
  out of the page with the Guardrails card on a multi-client backend,
  because it writes the ACTIVE workspace's STATE.json.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.settings import ops_history_enabled
from mureo.context.state import read_state_file
from mureo.context.state_store import FilesystemStateStore
from mureo.web.ops_history_setting import (
    OpsHistorySettingError,
    read_setting,
    state_path_for_client,
    write_setting,
)
from mureo.web.server import ConfigureWizard
from tests.web_support import get_ok, get_text, post, post_ok

if TYPE_CHECKING:
    from collections.abc import Iterator

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"
ENDPOINT = "/api/settings/ops_history"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
class TestReadWrite:
    def test_a_missing_file_reads_as_off(self, tmp_path: Path) -> None:
        state = read_setting(tmp_path / "STATE.json")
        assert state == {"enabled": False, "exists": False}

    def test_switching_on_is_stored_and_read_back(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        assert write_setting(path, True) == {"enabled": True, "exists": True}
        assert ops_history_enabled(read_state_file(path)) is True
        assert write_setting(path, False)["enabled"] is False
        assert ops_history_enabled(read_state_file(path)) is False

    def test_other_sections_survive(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "campaigns": [
                        {
                            "campaign_id": "c1",
                            "campaign_name": "One",
                            "status": "ENABLED",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        write_setting(path, True)
        doc = read_state_file(path)
        assert [c.campaign_id for c in doc.campaigns] == ["c1"]

    def test_switching_off_what_is_off_creates_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        assert write_setting(path, False) == {"enabled": False, "exists": False}
        assert not path.exists()

    def test_a_no_op_does_not_rewrite_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_setting(path, True)
        before = path.stat().st_mtime_ns
        write_setting(path, True)
        assert path.stat().st_mtime_ns == before

    def test_a_non_boolean_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(OpsHistorySettingError) as excinfo:
            write_setting(tmp_path / "STATE.json", "yes")  # type: ignore[arg-type]
        assert excinfo.value.code == "invalid_value"
        assert not (tmp_path / "STATE.json").exists()

    def test_an_unreadable_file_is_one_code(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(OpsHistorySettingError) as excinfo:
            read_setting(path)
        assert excinfo.value.code == "read_failed"


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


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


class _RosterStore(FilesystemStateStore):
    """A store that declares a client roster (the multi-client opt-in)."""

    def list_clients(self) -> list[dict[str, Any]]:
        return [{"slug": "acme", "name": "Acme", "active": True}]


@pytest.fixture
def roster_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from mureo.core.runtime_context import (
        default_runtime_context,
        reset_runtime_context,
    )

    reset_runtime_context()
    ctx = dataclasses.replace(
        default_runtime_context(workspace=tmp_path),
        state_store=_RosterStore(tmp_path),
    )
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    yield tmp_path
    reset_runtime_context()


@pytest.mark.unit
class TestRoutes:
    def test_get_reports_off_and_the_active_path(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = get_ok(wizard, ENDPOINT)
        assert body == {
            "status": "ok",
            "client": None,
            "path": str(workspace / "STATE.json"),
            "enabled": False,
            "exists": False,
        }

    def test_post_switches_on_and_is_read_back(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = post_ok(wizard, ENDPOINT, {"enabled": True})
        assert body["status"] == "ok"
        assert body["enabled"] is True
        assert ops_history_enabled(read_state_file(workspace / "STATE.json"))
        assert get_ok(wizard, ENDPOINT)["enabled"] is True

    @pytest.mark.parametrize("value", ["true", 1, None])
    def test_post_refuses_anything_but_a_boolean(
        self, wizard: ConfigureWizard, workspace: Path, value: Any
    ) -> None:
        status, body = post(wizard, ENDPOINT, {"enabled": value})
        assert status == 400
        assert body["error"] == "invalid_value"
        assert not (workspace / "STATE.json").exists()

    def test_post_needs_the_csrf_header(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        status, _ = post(wizard, ENDPOINT, {"enabled": True}, csrf=None)
        assert status == 403
        assert not (workspace / "STATE.json").exists()

    def test_a_client_slug_is_echoed_and_ignored_on_a_single_workspace(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = post_ok(wizard, ENDPOINT, {"enabled": True, "client": "acme"})
        assert body["client"] == "acme"
        assert body["path"] == str(workspace / "STATE.json")
        assert get_ok(wizard, ENDPOINT + "?client=acme")["enabled"] is True

    def test_a_client_slug_resolves_that_client_s_own_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core.runtime_context import default_runtime_context

        own = tmp_path / "acme"
        own.mkdir()

        class _Resolving(_RosterStore):
            def state_store_for_client(self, slug: str) -> FilesystemStateStore:
                assert slug == "acme"
                return FilesystemStateStore(own)

        ctx = dataclasses.replace(
            default_runtime_context(workspace=tmp_path),
            state_store=_Resolving(tmp_path),
        )
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
        assert state_path_for_client("acme") == own / "STATE.json"


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"dashboard\.ops_history_[a-z_]+")
_ATTRIBUTES = (
    "data-dashboard-ops-history",
    "data-ops-history-enabled",
    "data-ops-history-save",
    "data-ops-history-result",
    "data-ops-history-path",
)


@pytest.mark.unit
class TestCard:
    def test_the_card_sits_in_advanced_inside_the_cut_markers(self) -> None:
        from mureo.web.app_html import GUARDRAILS_CARD_END, GUARDRAILS_CARD_START

        html = _read("app.html")
        start = html.index(GUARDRAILS_CARD_START)
        end = html.index(GUARDRAILS_CARD_END)
        for attribute in _ATTRIBUTES:
            assert start < html.index(attribute) < end, attribute
        assert html.index("data-dashboard-advanced") < start

    def test_stripping_takes_the_card(self) -> None:
        from mureo.web.app_html import strip_guardrails_card

        stripped = strip_guardrails_card(_read("app.html"))
        for attribute in _ATTRIBUTES:
            assert attribute not in stripped, attribute

    def test_the_script_is_served_and_loaded_in_order(self) -> None:
        from mureo.web.handlers import _STATIC_ALLOWLIST

        assert "dashboard_ops_history.js" in _STATIC_ALLOWLIST
        html = _read("app.html")
        assert html.index("/static/dashboard_ops_history.js") < html.index(
            "/static/dashboard.js"
        )
        harness = (Path(__file__).parent / "js" / "dom_harness.js").read_text(
            encoding="utf-8"
        )
        assert harness.index('"dashboard_ops_history.js"') < harness.index(
            '"dashboard.js"'
        )

    def test_dashboard_js_binds_both_entry_points(self) -> None:
        js = _read("dashboard.js")
        assert "MUREO_DASHBOARD_OPS_HISTORY" in js
        assert "renderOpsHistory()" in js
        assert "wireOpsHistory()" in js

    def test_the_module_sends_no_client(self) -> None:
        js = _read("dashboard_ops_history.js")
        assert f'"{ENDPOINT}"' in js
        assert "client" not in js

    def test_every_key_is_translated_in_both_locales(self) -> None:
        used = set(_KEY_RE.findall(_read("app.html")))
        used |= set(_KEY_RE.findall(_read("dashboard_ops_history.js")))
        assert len(used) >= 6
        i18n = json.loads(_read("i18n.json"))
        for locale in ("en", "ja"):
            for key in sorted(used):
                assert key in i18n[locale], f"{key} missing from {locale!r}"
                assert str(i18n[locale][key]).strip() != ""
        assert (
            i18n["en"]["dashboard.ops_history_title"]
            != i18n["ja"]["dashboard.ops_history_title"]
        )


@pytest.mark.unit
class TestServedPage:
    def test_a_single_workspace_is_served_the_card(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        status, html = get_text(wizard, "/")
        assert status == 200
        assert "data-dashboard-ops-history" in html

    def test_a_client_roster_is_served_a_page_without_it(
        self, wizard: ConfigureWizard, roster_workspace: Path
    ) -> None:
        """The card writes the active workspace's STATE.json, which on a
        backend with a client roster is no client's file."""
        status, html = get_text(wizard, "/")
        assert status == 200
        assert "data-dashboard-ops-history" not in html
        assert "data-dashboard-advisors" in html
