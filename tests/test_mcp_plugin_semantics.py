"""Unit tests for #114 Phase 2: plugin tool safety semantics +
mutating-call promotion into STATE.json's action_log.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from mcp.types import Tool, ToolAnnotations

from mureo.mcp.plugin_semantics import derive_semantics, record_mutation_action_log
from mureo.throttle import ThrottleConfig

if TYPE_CHECKING:
    from pathlib import Path


def _tool(*, annotations=None, meta=None, name="acme_ads_x") -> Tool:
    return Tool(
        name=name,
        description="x",
        inputSchema={"type": "object", "properties": {}},
        annotations=annotations,
        meta=meta,
    )


@pytest.mark.unit
class TestDeriveSemantics:
    def test_undeclared_is_mutating(self) -> None:
        assert derive_semantics(_tool()).mutating is True

    def test_read_only_hint_is_non_mutating(self) -> None:
        sem = derive_semantics(_tool(annotations=ToolAnnotations(readOnlyHint=True)))
        assert sem.mutating is False

    def test_destructive_without_readonly_is_mutating(self) -> None:
        sem = derive_semantics(_tool(annotations=ToolAnnotations(destructiveHint=True)))
        assert sem.mutating is True

    def test_reversal_meta_captured_only_when_dict(self) -> None:
        ok = derive_semantics(
            _tool(meta={"mureo": {"reversal": {"operation": "acme_ads_resume"}}})
        )
        assert ok.reversal == {"operation": "acme_ads_resume"}
        bad = derive_semantics(_tool(meta={"mureo": {"reversal": "nope"}}))
        assert bad.reversal is None

    def test_throttle_meta_parsed_and_malformed_ignored(self) -> None:
        good = derive_semantics(
            _tool(meta={"mureo": {"throttle": {"rate": 2.0, "burst": 3}}})
        )
        assert good.throttle == ThrottleConfig(rate=2.0, burst=3)
        bad = derive_semantics(_tool(meta={"mureo": {"throttle": {"rate": "x"}}}))
        assert bad.throttle is None

    def test_observation_days_meta_parsed_and_malformed_ignored(self) -> None:
        assert derive_semantics(_tool()).observation_days is None
        good = derive_semantics(_tool(meta={"mureo": {"observation_days": 7}}))
        assert good.observation_days == 7
        for bad_val in ("x", 0, -3, 1.5, None, True, False):
            sem = derive_semantics(_tool(meta={"mureo": {"observation_days": bad_val}}))
            assert sem.observation_days is None

    def test_identity_meta_parsed(self) -> None:
        sem = derive_semantics(
            _tool(
                meta={
                    "mureo": {
                        "identity": {
                            "campaign_id": "campaignId",
                            "entity_type": "placement",
                            "entity_id": "placementId",
                        }
                    }
                }
            )
        )
        assert sem.identity is not None
        assert sem.identity.campaign_id_key == "campaignId"
        assert sem.identity.entity_type == "placement"
        assert sem.identity.entity_id_key == "placementId"

    @pytest.mark.parametrize(
        "identity",
        [
            {},
            {"entity_type": "placement"},
            {"entity_id": "placementId"},
            {"campaign_id": 123},
            {"unknown": "id"},
        ],
    )
    def test_malformed_identity_meta_is_ignored(self, identity: object) -> None:
        assert (
            derive_semantics(_tool(meta={"mureo": {"identity": identity}})).identity
            is None
        )


@pytest.mark.unit
class TestHintLessToolsFallBackToTheNameVocabulary:
    """#517: a bridged surface is not obliged to annotate.

    On one real Amazon manifest 83 of 85 tools declare ``readOnlyHint``;
    the two that do not are plainly ``list_`` reads, and the
    undeclared-⇒-mutating default filed them in STATE.json's action_log
    with a 14-day observation window.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "billing-list_invoice_summaries",
            "billing-list_billing_profile_usages",
        ],
    )
    def test_the_two_real_hint_less_reads_are_not_mutating(self, name: str) -> None:
        assert derive_semantics(_tool(name=name)).mutating is False

    def test_a_hint_less_mutation_shaped_name_stays_mutating(self) -> None:
        assert derive_semantics(
            _tool(name="campaign_management-create_campaign")
        ).mutating

    def test_annotations_without_the_hint_also_fall_back_to_the_name(self) -> None:
        sem = derive_semantics(
            _tool(
                name="billing-list_invoices",
                annotations=ToolAnnotations(destructiveHint=False),
            )
        )
        assert sem.mutating is False

    def test_an_explicit_hint_always_wins_over_the_name(self) -> None:
        """A plugin author saying ``readOnlyHint=False`` on a read-shaped
        name is a declaration, not an omission."""
        mutating = derive_semantics(
            _tool(
                name="billing-list_invoice_summaries",
                annotations=ToolAnnotations(readOnlyHint=False),
            )
        )
        assert mutating.mutating is True
        read = derive_semantics(
            _tool(
                name="campaign_management-create_campaign",
                annotations=ToolAnnotations(readOnlyHint=True),
            )
        )
        assert read.mutating is False

    def test_the_fallback_uses_the_shared_read_vocabulary(self) -> None:
        """Same answer as the rollback planner and the guardrail
        pattern-fallback registration — three surfaces, one list."""
        from mureo.core.tool_names import is_read_only_tool_name

        for name in ("billing-list_invoice_summaries", "acme-create_thing"):
            assert derive_semantics(_tool(name=name)).mutating is not (
                is_read_only_tool_name(name)
            )


@pytest.mark.unit
class TestRecordMutationActionLog:
    def _seed_state(self, d: Path) -> Path:
        from mureo.context.models import StateDocument
        from mureo.context.state import write_state_file

        p = d / "STATE.json"
        write_state_file(p, StateDocument())
        return p

    def test_appends_when_state_json_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_pause",
            source="acme-dist",
            reversal={"operation": "acme_ads_resume"},
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        e = doc.action_log[0]
        assert e.action == "acme_ads_pause"
        # No provider named — the legacy short key, not a fabricated one.
        assert e.platform == "plugin:acme-dist"
        assert e.reversible_params == {"operation": "acme_ads_resume"}

    def test_provider_makes_the_platform_the_canonical_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#537 — two providers of one distribution log under distinct keys.

        Without the provider half, a LINE mutation and a Yahoo mutation
        would both read as ``plugin:mureo-lineyahoo-bridge`` in the audit
        trail, i.e. one platform's action recorded as another's.
        """
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="line_ads_pause",
            source="mureo-lineyahoo-bridge",
            provider="line_ads",
            reversal=None,
        )
        record_mutation_action_log(
            tool="yahoo_ads_pause",
            source="mureo-lineyahoo-bridge",
            provider="yahoo_ads",
            reversal=None,
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert [e.platform for e in doc.action_log] == [
            "plugin:mureo-lineyahoo-bridge:line_ads",
            "plugin:mureo-lineyahoo-bridge:yahoo_ads",
        ]

    def test_single_provider_distribution_also_gets_the_two_part_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key shape does not depend on the sibling count (#537)."""
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="logly_pause",
            source="mureo-logly-bridge",
            provider="logly_ads_context",
            reversal=None,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.platform == "plugin:mureo-logly-bridge:logly_ads_context"

    def test_common_argument_names_are_recorded_as_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_ad_set",
            source="acme-dist",
            reversal=None,
            arguments={"campaign_id": "c1", "ad_set_id": "s1"},
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id == "c1"
        assert entry.entity_type == "ad_set"
        assert entry.entity_id == "s1"

    def test_ad_is_canonical_over_inferred_parent_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_pause_ad",
            source="acme-dist",
            reversal=None,
            arguments={"campaign_id": "c1", "ad_group_id": "g1", "ad_id": "a1"},
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id == "c1"
        assert entry.ad_id == "a1"
        assert entry.entity_type is None
        assert entry.entity_id is None

    def test_declared_identity_uses_provider_argument_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        sem = derive_semantics(
            _tool(
                meta={
                    "mureo": {
                        "identity": {
                            "campaign_id": "campaignRef",
                            "entity_type": "placement",
                            "entity_id": "targetRef",
                        }
                    }
                }
            )
        )
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_target",
            source="acme-dist",
            reversal=None,
            arguments={"campaignRef": 42, "targetRef": "p9"},
            identity=sem.identity,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id == "42"
        assert entry.entity_type == "placement"
        assert entry.entity_id == "p9"

    def test_declared_generic_identity_ignores_undeclared_ad_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        sem = derive_semantics(
            _tool(
                meta={
                    "mureo": {
                        "identity": {
                            "entity_type": "placement",
                            "entity_id": "placementRef",
                        }
                    }
                }
            )
        )
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_placement",
            source="acme-dist",
            reversal=None,
            arguments={"ad_id": "a1", "placementRef": "p1"},
            identity=sem.identity,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.ad_id is None
        assert entry.entity_type == "placement"
        assert entry.entity_id == "p1"

    def test_declaration_does_not_infer_undeclared_ad_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        sem = derive_semantics(
            _tool(meta={"mureo": {"identity": {"campaign_id": "campaignRef"}}})
        )
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_campaign",
            source="acme-dist",
            reversal=None,
            arguments={"campaignRef": "c1", "ad_id": "context-ad"},
            identity=sem.identity,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id == "c1"
        assert entry.ad_id is None
        assert entry.entity_type is None
        assert entry.entity_id is None

    def test_missing_declared_generic_id_does_not_infer_parent_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        sem = derive_semantics(
            _tool(
                meta={
                    "mureo": {
                        "identity": {
                            "entity_type": "placement",
                            "entity_id": "placementRef",
                        }
                    }
                }
            )
        )
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_placement",
            source="acme-dist",
            reversal=None,
            arguments={"placementRef": None, "ad_set_id": "parent-set"},
            identity=sem.identity,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id is None
        assert entry.ad_id is None
        assert entry.entity_type is None
        assert entry.entity_id is None

    def test_missing_declared_entity_does_not_drop_campaign_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        sem = derive_semantics(
            _tool(
                meta={
                    "mureo": {
                        "identity": {
                            "campaign_id": "campaignRef",
                            "entity_type": "placement",
                            "entity_id": "placementRef",
                        }
                    }
                }
            )
        )
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_update_target",
            source="acme-dist",
            reversal=None,
            arguments={"campaignRef": "c1"},
            identity=sem.identity,
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.campaign_id == "c1"
        assert entry.entity_type is None
        assert entry.entity_id is None

    def test_noop_without_state_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(tool="t", source="s", reversal=None)  # no raise
        assert not (tmp_path / "STATE.json").exists()  # never created

    def test_never_raises_on_append_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("disk gone")

        monkeypatch.setattr("mureo.context.state.append_action_log", _boom)
        record_mutation_action_log(tool="t", source="s", reversal=None)  # swallowed

    def _due_date(self, doc_path: Path) -> date:
        from mureo.context.state import read_state_file

        e = read_state_file(doc_path).action_log[0]
        assert e.observation_due is not None  # structural strategy parity
        return date.fromisoformat(e.observation_due)

    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> date:
        """Freeze the shared server clock and return its LOCAL date.

        The window is counted off ``mureo.core.clock.server_now`` (#460),
        which is host-local. Comparing against a real ``datetime.now(utc)``
        would be flaky on any positive-offset host: at 02:00 JST the local
        date is already the next UTC day, so the delta reads N+1 and the
        test fails for a reason that has nothing to do with the window.
        Freezing at exactly that hour keeps the case covered — and pinned.
        """
        import mureo.core.clock as clock

        frozen = datetime(2026, 7, 28, 2, 0, tzinfo=timezone(timedelta(hours=9)))
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        return frozen.date()

    def test_default_observation_window_when_undeclared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp.plugin_semantics import _DEFAULT_OBSERVATION_DAYS

        today = self._freeze_clock(monkeypatch)
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(tool="acme_ads_pause", source="d", reversal=None)
        assert self._due_date(tmp_path / "STATE.json") == today + timedelta(
            days=_DEFAULT_OBSERVATION_DAYS
        )

    def test_declared_observation_days_honored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        today = self._freeze_clock(monkeypatch)
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_pause", source="d", reversal=None, observation_days=3
        )
        assert self._due_date(tmp_path / "STATE.json") == today + timedelta(days=3)
