"""The tracking pre-flight that runs whether the agent asks for it or not.

`analysis_tracking_consistency_check` is opt-in — the agent has to choose
to call it. These tests cover the enforced path: the native Google Ads
ad-create handlers run the check before the mutation and refuse the
create when the planned ad carries another campaign's tracking identity.

The failure policy is pinned here too: a pre-flight that cannot read the
account must never block an operator from shipping an ad.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.mcp._tracking_preflight import (
    DISABLE_ENV,
    google_ads_create_preflight,
    reset_preflight_cache,
)


@pytest.fixture(autouse=True)
def _clear_preflight_state():
    """The account snapshot is cached across creates; isolate each test."""
    from mureo.core.runtime_context import reset_runtime_context

    reset_preflight_cache()
    reset_runtime_context()
    yield
    reset_preflight_cache()
    reset_runtime_context()


def _url(article: int, campaign_value: str) -> str:
    return (
        f"https://example.com/article/{article}/"
        f"?utm_source=google&utm_medium=cpc&utm_campaign={campaign_value}"
    )


def _row(ad_id: str, campaign_id: str, ad_group_id: str, value: str, n: int) -> dict:
    return {
        "id": ad_id,
        "campaign_id": campaign_id,
        "campaign_name": f"Display / {campaign_id}",
        "ad_group_id": ad_group_id,
        "status": "ENABLED",
        "final_urls": [_url(n, value)],
    }


def _account_rows() -> list[dict]:
    """Segment A and segment B campaigns, each correctly tagged."""
    return [
        *[_row(f"a{n}", "campaign-a", "ag-a", f"sega0{n}", n) for n in (1, 2, 3)],
        *[_row(f"b{n}", "campaign-b", "ag-b", f"segb0{n}", n) for n in (4, 5, 6)],
    ]


def _client(rows: list[dict] | None = None, **overrides: Any) -> Any:
    client = AsyncMock()
    client.list_ads = AsyncMock(
        return_value=rows if rows is not None else _account_rows()
    )
    client.list_ad_groups = AsyncMock(
        return_value=[
            {"id": "ag-a", "campaign_id": "campaign-a"},
            {"id": "ag-b", "campaign_id": "campaign-b"},
            {"id": "ag-new", "campaign_id": "campaign-b"},
        ]
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def _payload(result: list) -> dict:
    return json.loads(result[0].text)


@pytest.mark.unit
class TestRefusal:
    async def test_refuses_an_ad_carrying_another_campaigns_scheme(self) -> None:
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert outcome.refused
        payload = _payload(outcome.refusal)
        assert payload["error"] == "tracking_preflight_failed"
        assert payload["findings"]
        assert payload["findings"][0]["code"] == "foreign_campaign_scheme"
        assert payload["findings"][0]["evidence"]["owning_campaign_id"] == "campaign-a"

    async def test_allows_a_correctly_tagged_ad(self) -> None:
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(7, "segb07"),
            acknowledged=False,
        )
        assert not outcome.refused
        assert outcome.note is None

    async def test_resolves_the_campaign_for_a_brand_new_ad_group(self) -> None:
        """An ad group with no ads yet joins through list_ad_groups."""
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-new",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert outcome.refused


@pytest.mark.unit
class TestOverrides:
    async def test_acknowledged_call_proceeds(self) -> None:
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=True,
        )
        assert not outcome.refused

    async def test_env_kill_switch_disables_the_preflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DISABLE_ENV, "1")
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert not outcome.refused

    async def test_an_ad_without_a_final_url_is_not_blocked(self) -> None:
        outcome = await google_ads_create_preflight(
            _client(), ad_group_id="ag-b", final_url=None, acknowledged=False
        )
        assert not outcome.refused


@pytest.mark.unit
class TestFailsOpen:
    """A check that cannot read the account must not block a create."""

    async def test_a_read_failure_lets_the_create_proceed(self) -> None:
        client = _client()
        client.list_ads = AsyncMock(side_effect=RuntimeError("API unavailable"))
        outcome = await google_ads_create_preflight(
            client,
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert not outcome.refused
        # Fail-open, but never silently: the create says it was unchecked.
        assert outcome.note is not None
        assert "NOT CHECKED" in outcome.note
        assert "RuntimeError" in outcome.note

    async def test_an_unresolvable_campaign_lets_the_create_proceed(self) -> None:
        client = _client()
        client.list_ad_groups = AsyncMock(return_value=[])
        outcome = await google_ads_create_preflight(
            client,
            ad_group_id="ag-unknown",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert not outcome.refused
        assert outcome.note is not None

    async def test_an_empty_account_lets_the_create_proceed(self) -> None:
        client = _client(rows=[])
        client.list_ad_groups = AsyncMock(
            return_value=[{"id": "ag-b", "campaign_id": "campaign-b"}]
        )
        outcome = await google_ads_create_preflight(
            client,
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert not outcome.refused


@pytest.mark.unit
class TestHandlerWiring:
    """The refusal actually stops the platform mutation."""

    async def _handler_client(
        self, monkeypatch: pytest.MonkeyPatch, client: Any
    ) -> Any:
        from mureo.mcp import _handlers_google_ads as handlers

        monkeypatch.setattr(handlers, "_get_client", lambda args: client)
        return handlers

    async def test_ads_create_refuses_and_does_not_mutate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(
            return_value={"resource_name": "should-not-happen"}
        )
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(1, "sega01"),
            }
        )

        assert _payload(result)["error"] == "tracking_preflight_failed"
        client.create_ad.assert_not_awaited()

    async def test_ads_create_proceeds_when_acknowledged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(return_value={"resource_name": "created"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(1, "sega01"),
                "acknowledge_tracking_findings": True,
            }
        )

        assert _payload(result)["resource_name"] == "created"
        client.create_ad.assert_awaited_once()

    async def test_ads_create_display_refuses_and_does_not_mutate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_display_ad = AsyncMock(return_value={"resource_name": "nope"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create_display(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "long_headline": "long",
                "descriptions": ["d1"],
                "business_name": "Acme",
                "marketing_image_paths": ["/tmp/a.png"],
                "square_marketing_image_paths": ["/tmp/b.png"],
                "final_url": _url(1, "sega01"),
            }
        )

        assert _payload(result)["error"] == "tracking_preflight_failed"
        client.create_display_ad.assert_not_awaited()

    async def test_a_correctly_tagged_create_still_reaches_the_platform(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(return_value={"resource_name": "created"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(7, "segb07"),
            }
        )

        assert _payload(result)["resource_name"] == "created"
        client.create_ad.assert_awaited_once()


@pytest.mark.unit
class TestToolSchema:
    def test_both_create_tools_expose_the_acknowledgement(self) -> None:
        from mureo.mcp.tools_google_ads import TOOLS

        for name in ("google_ads_ads_create", "google_ads_ads_create_display"):
            (tool,) = [t for t in TOOLS if t.name == name]
            assert "acknowledge_tracking_findings" in tool.inputSchema["properties"]


@pytest.mark.unit
class TestDeclaredConventionReachesEnforcement:
    """The enforcing path must honour STRATEGY.md, not just the advisory one.

    Enforcement running on defaults while the advisory tool honours
    ``identify:`` / ``differentiate:`` breaks the promise the feature is
    built on in both directions: the account that declared its way out
    of a false positive is still blocked (and learns to acknowledge
    reflexively), and the account that declared ``identify:`` because
    its segment marker lives elsewhere gets no enforcement on a real
    leak. Coverage could never have shown this — the code was absent,
    and absent code has no uncovered lines.
    """

    @pytest.fixture
    def workspace(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def _declare(self, workspace, body: str) -> None:
        (workspace / "STRATEGY.md").write_text(
            f"# Strategy\n\n## Tracking Convention\n\n{body}\n\n## Persona\n\nSomeone.\n",
            encoding="utf-8",
        )

    async def test_differentiate_stops_enforcement_blocking_it(self, workspace) -> None:
        """The declared escape hatch must work on create, not only in the audit.

        Without this the only way through is acknowledging every time,
        which is exactly how an override stops meaning anything.
        """
        rows = [
            *[_row(f"a{n}", "campaign-a", "ag-a", f"sega0{n}", n) for n in (1, 2, 3)],
            *[_row(f"b{n}", "campaign-b", "ag-b", f"segb0{n}", n) for n in (4, 5, 6)],
        ]
        # utm_campaign is the ONLY parameter separating segment A from
        # segment B here (source and medium are google/cpc throughout).
        # Declaring it creative-differentiating empties the identifying
        # signature, so the borrowed URL stops being a foreign scheme.
        self._declare(workspace, "- differentiate: utm_campaign")

        outcome = await google_ads_create_preflight(
            _client(rows),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert not outcome.refused, "a declared convention must reach enforcement"

    async def test_the_same_url_is_still_refused_without_the_declaration(
        self, workspace
    ) -> None:
        """Control: the fixture above only passes because of STRATEGY.md."""
        outcome = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert outcome.refused

    async def test_identify_extends_enforcement_to_a_custom_marker(
        self, workspace
    ) -> None:
        """An account whose segment lives in utm_content gets enforced too."""

        def url(n: int, content: str) -> str:
            return (
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=always_on&utm_content={content}"
            )

        rows = [
            *[
                {
                    "id": f"a{n}",
                    "campaign_id": "campaign-a",
                    "ad_group_id": "ag-a",
                    "final_urls": [url(n, "sega")],
                }
                for n in (1, 2, 3)
            ],
            *[
                {
                    "id": f"b{n}",
                    "campaign_id": "campaign-b",
                    "ad_group_id": "ag-b",
                    "final_urls": [url(n, "segb")],
                }
                for n in (4, 5, 6)
            ],
        ]
        client = _client(rows)

        # Default parameter sets: utm_content is creative-differentiating,
        # so nothing fires.
        assert not (
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=url(7, "sega"),
                acknowledged=False,
            )
        ).refused

        reset_preflight_cache()
        self._declare(workspace, "- identify: utm_content")
        outcome = await google_ads_create_preflight(
            client,
            ad_group_id="ag-b",
            final_url=url(7, "sega"),
            acknowledged=False,
        )
        assert outcome.refused
        payload = _payload(outcome.refusal)
        assert payload["findings"][0]["evidence"]["owning_campaign_id"] == "campaign-a"

    async def test_absent_strategy_file_falls_back_to_defaults(self, workspace) -> None:
        assert (
            await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
        ).refused

    async def test_a_strategy_file_without_the_section_falls_back(
        self, workspace
    ) -> None:
        (workspace / "STRATEGY.md").write_text(
            "# Strategy\n\n## Persona\n\nNo convention here.\n", encoding="utf-8"
        )
        assert (
            await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
        ).refused


@pytest.mark.unit
class TestAccountSnapshotIsReusedAcrossABulkUpload:
    """One account-wide read per burst, not one per ad.

    The read cannot be narrowed to the target campaign — finding the
    campaign a scheme was copied FROM is the whole point — so the cost
    is managed by reuse instead.
    """

    async def test_second_create_reuses_the_snapshot(self) -> None:
        client = _client()
        for _ in range(4):
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=_url(7, "segb07"),
                acknowledged=False,
            )
        assert client.list_ads.await_count == 1

    async def test_the_cache_is_per_account(self) -> None:
        first = _client()
        first._customer_id = "111"
        second = _client()
        second._customer_id = "222"
        for client in (first, second):
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=_url(7, "segb07"),
                acknowledged=False,
            )
        assert first.list_ads.await_count == 1
        assert second.list_ads.await_count == 1


_PREFLIGHT_LOGGER = "mureo.mcp._tracking_preflight"


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Only this module's records.

    ``caplog`` collects from the root handler, so anything else
    installed in the environment (an agency plugin, a vendored client)
    would otherwise be counted as a pre-flight failure.
    """
    return [r for r in caplog.records if r.name == _PREFLIGHT_LOGGER]


@pytest.mark.unit
class TestFailureEscalation:
    """A permanently broken guardrail must not look like a quiet one.

    These pin the two headline behaviours of the fail-open path: the
    counter escalates to ERROR, and a success resets it. Without them a
    refactor could move the threshold or drop the reset and nothing
    would go red — the reviewer confirmed both work by executing them,
    which is exactly the evidence a test is supposed to make permanent.
    """

    def _broken(self) -> Any:
        client = _client()
        client.list_ads = AsyncMock(side_effect=RuntimeError("API unavailable"))
        return client

    def _blind(self) -> Any:
        """An integration that returns empty data instead of raising."""
        client = _client(rows=[])
        client.list_ad_groups = AsyncMock(return_value=[])
        return client

    async def _run(self, client: Any):
        return await google_ads_create_preflight(
            client,
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )

    async def test_repeated_failures_escalate_to_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = self._broken()
        with caplog.at_level(logging.WARNING, logger="mureo.mcp._tracking_preflight"):
            for _ in range(3):
                assert not (await self._run(client)).refused
        levels = [r.levelno for r in _records(caplog)]
        assert levels == [logging.WARNING, logging.WARNING, logging.ERROR]
        assert "guardrail is effectively OFF" in _records(caplog)[2].getMessage()

    async def test_an_unresolvable_campaign_counts_towards_escalation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The branch that raises nothing must still be visible.

        It returns NOT CHECKED without an exception, so if it bypassed
        the counter a broken integration could stay silent forever.
        """
        client = self._blind()
        with caplog.at_level(logging.WARNING, logger="mureo.mcp._tracking_preflight"):
            for _ in range(3):
                outcome = await self._run(client)
                assert not outcome.refused
                assert outcome.note is not None
        assert [r.levelno for r in _records(caplog)] == [
            logging.WARNING,
            logging.WARNING,
            logging.ERROR,
        ]

    async def test_every_not_run_emits_a_log_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression: the unresolved-campaign branch once logged nothing."""
        with caplog.at_level(logging.WARNING, logger="mureo.mcp._tracking_preflight"):
            outcome = await self._run(self._blind())
        assert outcome.note is not None
        assert len(_records(caplog)) == 1
        assert "did not run" in _records(caplog)[0].getMessage()

    async def test_a_success_resets_the_counter(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two failures, a clean run, two more failures: still no alarm."""
        broken = self._broken()
        with caplog.at_level(logging.WARNING, logger="mureo.mcp._tracking_preflight"):
            for _ in range(2):
                await self._run(broken)
            healthy = _client()
            healthy._customer_id = "healthy"
            assert not (
                await google_ads_create_preflight(
                    healthy,
                    ad_group_id="ag-b",
                    final_url=_url(7, "segb07"),
                    acknowledged=False,
                )
            ).refused
            for _ in range(2):
                await self._run(broken)
        assert [r.levelno for r in _records(caplog)] == [logging.WARNING] * 4


@pytest.mark.unit
class TestConventionReadFailures:
    """An unreadable STRATEGY.md falls back to defaults, not to nothing."""

    async def test_a_read_error_still_enforces_on_defaults(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        strategy = tmp_path / "STRATEGY.md"
        strategy.write_text("## Tracking Convention\n\n- differentiate: utm_campaign\n")

        import mureo.mcp._tracking_preflight as preflight

        def _boom(*_args: Any, **_kwargs: Any) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _boom)

        with caplog.at_level(logging.WARNING, logger="mureo.mcp._tracking_preflight"):
            assert preflight.load_workspace_convention() is None
            outcome = await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )

        # The declared `differentiate:` never loaded, so the DEFAULT
        # identifying set applies and the ad is still refused.
        assert outcome.refused
        assert any("could not read" in r.getMessage() for r in _records(caplog))

    def test_the_strategy_path_comes_from_the_state_store(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Taken from the store, not rebuilt, so the two cannot drift."""
        import mureo.mcp._tracking_preflight as preflight
        from mureo.core.state_store import FilesystemStateStore

        store = FilesystemStateStore(workspace=tmp_path)
        moved = tmp_path / "elsewhere" / "STRATEGY.md"
        store.strategy_path = moved

        class _Ctx:
            state_store = store

        import mureo.core.runtime_context as rc

        monkeypatch.setattr(rc, "get_runtime_context", lambda: _Ctx())
        assert preflight._strategy_path() == moved
