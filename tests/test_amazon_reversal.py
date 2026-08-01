"""Automatic before-state capture for Amazon Ads mutations (TDD, #121).

Amazon writes used to land in ``action_log`` with ``reversible_params=None``,
so ``rollback_apply`` answered NOT_SUPPORTED. The bridge now implements the
``MCPReversibleToolProvider`` hook: before a reversible mutation it reads the
entity's current state through its OWN dispatch (inheriting auth/refresh) and
records a reversal that the rollback planner can execute verbatim.

Everything Amazon-side is faked here. The envelope keys ``{"campaigns": [...]}``
and ``{"ads": [...]}`` are the live-verified ones; the per-item field names
(``campaignId``/``state``/``budgets``/``name``/``bid``) come from the write-side
inputSchemas of the real 85-tool manifest, so the fakes mirror what the code is
allowed to assume — no more.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from mureo.amazon_ads import reversal as rev

_ACCOUNT = {"profileId": "1234567890"}


def _content(payload: Any) -> list[Any]:
    from mcp.types import TextContent

    return [TextContent(type="text", text=json.dumps(payload))]


class _FakeDispatch:
    """Stands in for ``AmazonAdsBridge.handle_mcp_tool``.

    ``payloads`` is a queue of responses consumed in call order; a payload may
    be a dict (JSON-encoded into a TextContent), a raw string, or an exception
    to raise. A missing entry yields an empty envelope.
    """

    def __init__(
        self, payloads: list[Any] | None = None, *, delay: float = 0.0
    ) -> None:
        self._payloads = list(payloads or [])
        self._delay = delay
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        self.calls.append((name, copy.deepcopy(arguments)))
        if self._delay:
            await asyncio.sleep(self._delay)
        payload = self._payloads.pop(0) if self._payloads else {}
        if isinstance(payload, BaseException):
            raise payload
        if isinstance(payload, str):
            from mcp.types import TextContent

            return [TextContent(type="text", text=payload)]
        return _content(payload)


class _FakeClock:
    """Deterministic stand-in for ``reversal._monotonic``.

    Advances by ``step`` on every read, so the capture deadline can be driven
    to expiry without any wall-clock sleeping (and without flakiness).
    """

    def __init__(self, *, step: float) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._now
        self._now += self._step
        return value


def _mutation(collection: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"body": {"accessRequestedAccount": dict(_ACCOUNT), collection: items}}


@pytest.fixture(autouse=True)
def _no_learned_ad_products():
    """The id → ad-product cache is process-local; isolate every test from it."""
    rev.clear_ad_product_cache()
    yield
    rev.clear_ad_product_cache()


# ---------------------------------------------------------------------------
# The declarative pair table — one capture per reversible mutation.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerPairCapture:
    async def test_update_campaign_state_restores_the_prior_state(self) -> None:
        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out == {
            "operation": "campaign_management-update_campaign_state",
            "params": {
                "body": {
                    "accessRequestedAccount": {"profileId": "1234567890"},
                    "campaigns": [{"campaignId": "C1", "state": "ENABLED"}],
                }
            },
        }
        # The read went through the bridge's own dispatch, to the query tool,
        # filtered by the same id the mutation targets.
        tool, args = d.calls[0]
        assert tool == "campaign_management-query_campaign"
        assert args["body"]["accessRequestedAccount"] == _ACCOUNT
        assert args["body"]["campaignIdFilter"] == {"include": ["C1"]}

    async def test_update_campaign_budget_restores_the_prior_budgets(self) -> None:
        prior = [
            {
                "budgetType": "MONETARY",
                "recurrenceTimePeriod": "DAILY",
                "budgetValue": {
                    "monetaryBudgetValue": {"monetaryBudget": {"value": 10.0}}
                },
            }
        ]
        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1", "budgets": prior}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_budget",
            _mutation(
                "campaigns",
                [{"campaignId": "C1", "budgets": [{"budgetType": "MONETARY"}]}],
            ),
        )
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "budgets": prior}
        ]

    async def test_update_campaign_restores_only_the_fields_it_changes(self) -> None:
        d = _FakeDispatch(
            [{"campaigns": [{"campaignId": "C1", "state": "ENABLED", "name": "old"}]}]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign",
            _mutation("campaigns", [{"campaignId": "C1", "name": "new"}]),
        )
        assert out is not None
        # ``state`` was not part of the mutation, so it is not "restored".
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "name": "old"}
        ]

    async def test_update_ad_restores_state_and_name(self) -> None:
        d = _FakeDispatch(
            [{"ads": [{"adId": "A1", "state": "ENABLED", "name": "old ad"}]}]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_ad",
            _mutation("ads", [{"adId": "A1", "state": "PAUSED", "name": "new ad"}]),
        )
        assert out is not None
        assert d.calls[0][0] == "campaign_management-query_ad"
        assert d.calls[0][1]["body"]["adIdFilter"] == {"include": ["A1"]}
        assert out["params"]["body"]["ads"] == [
            {"adId": "A1", "state": "ENABLED", "name": "old ad"}
        ]

    async def test_update_ad_group_restores_bid_state_and_name(self) -> None:
        d = _FakeDispatch(
            [
                {
                    "adGroups": [
                        {
                            "adGroupId": "G1",
                            "state": "ENABLED",
                            "bid": {"defaultBid": 1.5},
                        }
                    ]
                }
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_ad_group",
            _mutation(
                "adGroups",
                [{"adGroupId": "G1", "bid": {"defaultBid": 2.5}}],
            ),
        )
        assert out is not None
        assert d.calls[0][0] == "campaign_management-query_ad_group"
        assert out["params"]["body"]["adGroups"] == [
            {"adGroupId": "G1", "bid": {"defaultBid": 1.5}}
        ]

    async def test_update_target_bid_restores_the_prior_bid(self) -> None:
        d = _FakeDispatch([{"targets": [{"targetId": "T1", "bid": {"bid": 0.75}}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_target_bid",
            _mutation("targets", [{"targetId": "T1", "bid": {"bid": 1.25}}]),
        )
        assert out is not None
        assert d.calls[0][0] == "campaign_management-query_target"
        assert d.calls[0][1]["body"]["targetIdFilter"] == {"include": ["T1"]}
        assert out["params"]["body"]["targets"] == [
            {"targetId": "T1", "bid": {"bid": 0.75}}
        ]

    async def test_update_target_restores_bid_and_state(self) -> None:
        d = _FakeDispatch(
            [{"targets": [{"targetId": "T1", "state": "ENABLED", "bid": {"bid": 0.5}}]}]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_target",
            _mutation("targets", [{"targetId": "T1", "state": "PAUSED"}]),
        )
        assert out is not None
        assert out["params"]["body"]["targets"] == [
            {"targetId": "T1", "state": "ENABLED"}
        ]

    async def test_update_portfolio_needs_no_ad_product_filter(self) -> None:
        d = _FakeDispatch([{"portfolios": [{"portfolioId": "P1", "state": "ENABLED"}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_portfolio",
            _mutation("portfolios", [{"portfolioId": "P1", "state": "PAUSED"}]),
        )
        assert out is not None
        assert len(d.calls) == 1
        tool, args = d.calls[0]
        assert tool == "campaign_management-query_portfolio"
        # query_portfolio's inputSchema does not declare adProductFilter.
        assert "adProductFilter" not in args["body"]
        assert args["body"]["portfolioIdFilter"] == {"include": ["P1"]}
        assert out["params"]["body"]["portfolios"] == [
            {"portfolioId": "P1", "state": "ENABLED"}
        ]


# ---------------------------------------------------------------------------
# adProductFilter — required by four of the five query tools, absent from every
# mutation payload.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdProductFilter:
    async def test_probes_one_ad_product_per_call_until_the_id_is_found(self) -> None:
        d = _FakeDispatch(
            [
                {"campaigns": []},
                {"campaigns": []},
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is not None
        assert len(d.calls) == 3  # stops as soon as the id is resolved
        products = [c[1]["body"]["adProductFilter"]["include"] for c in d.calls]
        assert products == [
            ["SPONSORED_PRODUCTS"],  # commonality heuristic — probed first
            ["AMAZON_DSP"],
            ["SPONSORED_BRANDS"],
        ]

    async def test_probe_order_covers_the_whole_enum_exactly_once(self) -> None:
        d = _FakeDispatch([{"campaigns": []}] * 5)
        await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        probed = [c[1]["body"]["adProductFilter"]["include"][0] for c in d.calls]
        assert sorted(probed) == sorted(rev.AD_PRODUCTS)

    async def test_probing_is_bounded_by_the_ad_product_enum(self) -> None:
        d = _FakeDispatch([{"campaigns": []}] * 10)
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None  # never found ⇒ no reversal, not a guess
        assert len(d.calls) == len(rev.AD_PRODUCTS) == 5

    async def test_ad_product_declared_by_the_mutation_is_used_verbatim(self) -> None:
        d = _FakeDispatch(
            [{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}],
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign",
            _mutation(
                "campaigns",
                [
                    {
                        "campaignId": "C1",
                        "state": "PAUSED",
                        "adProduct": "SPONSORED_PRODUCTS",
                    }
                ],
            ),
        )
        assert out is not None
        assert len(d.calls) == 1
        assert d.calls[0][1]["body"]["adProductFilter"] == {
            "include": ["SPONSORED_PRODUCTS"]
        }

    async def test_a_declared_product_never_strands_the_rest_of_a_batch(self) -> None:
        # One item declares its ad product, the other does not: the declared
        # one is probed first, then the remaining products are still walked
        # for the id it did not resolve.
        d = _FakeDispatch(
            [
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
                {"campaigns": [{"campaignId": "C2", "state": "PAUSED"}]},
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign",
            _mutation(
                "campaigns",
                [
                    {
                        "campaignId": "C1",
                        "state": "PAUSED",
                        "adProduct": "SPONSORED_TELEVISION",
                    },
                    {"campaignId": "C2", "state": "ENABLED"},
                ],
            ),
        )
        assert len(d.calls) == 2
        assert d.calls[0][1]["body"]["adProductFilter"]["include"] == [
            "SPONSORED_TELEVISION"
        ]
        assert d.calls[1][1]["body"]["adProductFilter"]["include"] == [
            "SPONSORED_PRODUCTS"
        ]
        # The second round asks only for what is still unresolved.
        assert d.calls[1][1]["body"]["campaignIdFilter"] == {"include": ["C2"]}
        assert out is not None
        assert [c["campaignId"] for c in out["params"]["body"]["campaigns"]] == [
            "C1",
            "C2",
        ]

    async def test_a_learned_ad_product_is_probed_first_next_time(self) -> None:
        args = _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}])
        first = _FakeDispatch(
            [
                {"campaigns": []},  # SPONSORED_PRODUCTS
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},  # DSP
            ]
        )
        assert (
            await rev.capture_reversal(
                first, "campaign_management-update_campaign_state", args
            )
            is not None
        )
        assert len(first.calls) == 2

        second = _FakeDispatch(
            [{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}]
        )
        assert (
            await rev.capture_reversal(
                second, "campaign_management-update_campaign_state", args
            )
            is not None
        )
        assert len(second.calls) == 1  # no probing: the id's product is known
        assert second.calls[0][1]["body"]["adProductFilter"]["include"] == [
            "AMAZON_DSP"
        ]

    async def test_a_stale_cache_entry_falls_through_to_a_fresh_probe(self) -> None:
        rev._remember_ad_products(
            rev._REVERSIBLE["campaign_management-update_campaign_state"],
            {"C1": {}},
            "SPONSORED_TELEVISION",
        )
        d = _FakeDispatch(
            [
                {"campaigns": []},  # the cached product no longer has it
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is not None
        probed = [c[1]["body"]["adProductFilter"]["include"][0] for c in d.calls]
        assert probed == ["SPONSORED_TELEVISION", "SPONSORED_PRODUCTS"]

    def test_the_ad_product_cache_is_bounded(self) -> None:
        pair = rev._REVERSIBLE["campaign_management-update_campaign_state"]
        for i in range(rev._AD_PRODUCT_CACHE_MAX + 50):
            rev._remember_ad_products(pair, {f"C{i}": {}}, "AMAZON_DSP")
        assert len(rev._AD_PRODUCT_CACHE) == rev._AD_PRODUCT_CACHE_MAX
        assert ("campaignId", "C0") not in rev._AD_PRODUCT_CACHE  # oldest evicted
        assert ("campaignId", f"C{rev._AD_PRODUCT_CACHE_MAX + 49}") in (
            rev._AD_PRODUCT_CACHE
        )

    async def test_slow_reads_stop_at_the_capture_deadline(self, monkeypatch) -> None:
        """Each read returns just inside its own timeout, so only the OUTER
        deadline can stop the probe walk. Time is faked so the assertion is on
        read count, not on wall clock."""
        monkeypatch.setattr(rev, "READ_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(rev, "CAPTURE_DEADLINE_SECONDS", 15.0)
        clock = _FakeClock(step=6.0)  # 0.0 (deadline set), 6.0, 12.0, 18.0 …
        monkeypatch.setattr(rev, "_monotonic", clock)

        d = _FakeDispatch(
            [
                {"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]},
                {"campaigns": []},
                {"campaigns": [{"campaignId": "C2", "state": "ENABLED"}]},
            ],
            delay=0.02,  # just under the per-read timeout: never times out
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation(
                "campaigns",
                [
                    {"campaignId": "C1", "state": "PAUSED"},
                    {"campaignId": "C2", "state": "PAUSED"},
                ],
            ),
        )
        # Two reads fit inside the 15s budget; the third would start past it,
        # so the walk stops there instead of running the whole enum.
        assert len(d.calls) == 2
        # What WAS captured is kept; the entity that ran out of time is a
        # caveat, not a guess.
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("C2" in c for c in out["caveats"])

    async def test_the_deadline_yields_no_reversal_when_nothing_was_captured(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(rev, "CAPTURE_DEADLINE_SECONDS", 15.0)
        monkeypatch.setattr(rev, "_monotonic", _FakeClock(step=20.0))
        d = _FakeDispatch([{"campaigns": []}] * 5)
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None
        assert d.calls == []  # the deadline was already spent before read one

    async def test_a_read_that_hangs_times_out_instead_of_stalling_the_write(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(rev, "READ_TIMEOUT_SECONDS", 0.01)
        attempts: list[str] = []

        async def _hang(name: str, arguments: dict[str, Any]) -> list[Any]:
            attempts.append(name)
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        out = await rev.capture_reversal(
            _hang,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None  # nothing captured ⇒ nothing recorded
        assert len(attempts) == 1  # the walk ends at the first hung read

    async def test_a_failed_probe_keeps_what_earlier_rounds_captured(
        self, monkeypatch
    ) -> None:
        """A read that overruns its (shrunk) budget must not discard the
        before-states already resolved in earlier rounds."""
        monkeypatch.setattr(rev, "CAPTURE_DEADLINE_SECONDS", 12.02)
        # 0.0 sets the deadline, 6.0 leaves 6.02s for round one, 12.0 leaves
        # 0.02s for round two — which the slow read below cannot meet.
        monkeypatch.setattr(rev, "_monotonic", _FakeClock(step=6.0))

        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}])
        attempts: list[str] = []

        async def _slow_after_the_first(
            name: str, arguments: dict[str, Any]
        ) -> list[Any]:
            attempts.append(name)
            if len(attempts) > 1:
                await asyncio.sleep(0.2)  # 10x the remaining budget
            return await d(name, arguments)

        out = await rev.capture_reversal(
            _slow_after_the_first,
            "campaign_management-update_campaign_state",
            _mutation(
                "campaigns",
                [
                    {"campaignId": "C1", "state": "PAUSED"},
                    {"campaignId": "C2", "state": "PAUSED"},
                ],
            ),
        )
        assert len(attempts) == 2  # the failure ends the walk
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("C2" in c for c in out["caveats"])


# ---------------------------------------------------------------------------
# Defensive parsing — a wrong reversal is worse than none.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefensiveParsing:
    async def test_absent_field_is_not_reversed_and_is_flagged_as_a_caveat(
        self,
    ) -> None:
        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign",
            _mutation(
                "campaigns", [{"campaignId": "C1", "state": "PAUSED", "name": "n"}]
            ),
        )
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("name" in c for c in out["caveats"])

    async def test_no_reversible_field_in_the_response_means_no_reversal(self) -> None:
        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1"}]}])
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None

    async def test_a_different_id_in_the_response_is_never_used(self) -> None:
        d = _FakeDispatch(
            [{"campaigns": [{"campaignId": "OTHER", "state": "ENABLED"}]}] * 5
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None

    async def test_a_sibling_resource_is_never_read_as_the_entity(self) -> None:
        # The reason the "scan any list" fallback is gone. A recommendations
        # list carries the SAME id and a same-named `bid` field, so every
        # structural check a scanner can apply passes — and the capture would
        # have recorded a confident, uncaveated reversal to a suggested bid
        # the entity never had.
        d = _FakeDispatch(
            [{"bidRecommendations": [{"targetId": "T1", "bid": {"suggested": 0.02}}]}]
            * 5
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_target_bid",
            _mutation("targets", [{"targetId": "T1", "bid": {"bid": 1.25}}]),
        )
        assert out is None
        assert ("targetId", "T1") not in rev._AD_PRODUCT_CACHE

    async def test_an_unexpected_envelope_key_records_nothing(self) -> None:
        # The ad-group envelope key is inferred, not live-verified. If the
        # inference is wrong, the honest outcome is NO reversal — not a guess
        # assembled from whatever else the payload happens to contain.
        d = _FakeDispatch([{"results": [{"adGroupId": "G1", "state": "ENABLED"}]}] * 5)
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_ad_group",
            _mutation("adGroups", [{"adGroupId": "G1", "state": "PAUSED"}]),
        )
        assert out is None
        assert ("adGroupId", "G1") not in rev._AD_PRODUCT_CACHE

    async def test_a_lookalike_object_under_an_unknown_key_is_rejected(self) -> None:
        # A foreign-key reference list sitting where the envelope key is not:
        # only the declared key is ever read, so this is invisible to the
        # parser no matter how entity-shaped it looks.
        d = _FakeDispatch(
            [
                {
                    "adGroupAssociations": [
                        {"adGroupId": "G1", "associationId": "X1", "weight": 3}
                    ]
                }
            ]
            * 5
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_ad_group",
            _mutation("adGroups", [{"adGroupId": "G1", "state": "PAUSED"}]),
        )
        assert out is None
        # …and the id is not remembered as belonging to any ad product.
        assert ("adGroupId", "G1") not in rev._AD_PRODUCT_CACHE

    async def test_a_lookalike_does_not_mask_the_real_entity(self) -> None:
        # A lookalike must not end the probe walk. Here it even carries a
        # valid-looking `state`, so anything that read lists other than the
        # declared envelope key would return ENABLED from round one and never
        # reach the real ad group (PAUSED) in the next ad product.
        d = _FakeDispatch(
            [
                {"adGroupAssociations": [{"adGroupId": "G1", "state": "ENABLED"}]},
                {"adGroups": [{"adGroupId": "G1", "state": "PAUSED"}]},
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_ad_group",
            _mutation("adGroups", [{"adGroupId": "G1", "state": "ARCHIVED"}]),
        )
        assert len(d.calls) == 2
        assert out is not None
        assert out["params"]["body"]["adGroups"] == [
            {"adGroupId": "G1", "state": "PAUSED"}
        ]

    async def test_non_json_response_yields_no_reversal(self) -> None:
        d = _FakeDispatch(["not json at all"] * 5)
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None

    async def test_unresolved_entity_of_a_batch_is_reported_not_guessed(self) -> None:
        d = _FakeDispatch(
            [{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}] * 5
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation(
                "campaigns",
                [
                    {"campaignId": "C1", "state": "PAUSED"},
                    {"campaignId": "C2", "state": "PAUSED"},
                ],
            ),
        )
        assert out is not None
        assert out["params"]["body"]["campaigns"] == [
            {"campaignId": "C1", "state": "ENABLED"}
        ]
        assert any("C2" in c for c in out["caveats"])

    async def test_batch_ids_are_queried_in_one_call(self) -> None:
        d = _FakeDispatch(
            [
                {
                    "campaigns": [
                        {"campaignId": "C1", "state": "ENABLED"},
                        {"campaignId": "C2", "state": "PAUSED"},
                    ]
                }
            ]
        )
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation(
                "campaigns",
                [
                    {"campaignId": "C1", "state": "ARCHIVED"},
                    {"campaignId": "C2", "state": "ARCHIVED"},
                ],
            ),
        )
        assert len(d.calls) == 1
        assert d.calls[0][1]["body"]["campaignIdFilter"] == {"include": ["C1", "C2"]}
        assert out is not None
        assert out.get("caveats") is None


@pytest.mark.unit
class TestNotCaptured:
    @pytest.mark.parametrize(
        "tool",
        [
            "campaign_management-create_campaign",
            "campaign_management-delete_campaign",
            "campaign_management-add_country_campaign",
            "account_management-update_account_name",
            "reporting-create_report",
        ],
    )
    async def test_unpaired_mutation_is_not_captured(self, tool: str) -> None:
        d = _FakeDispatch()
        assert await rev.capture_reversal(d, tool, _mutation("campaigns", [])) is None
        assert d.calls == []

    async def test_missing_access_requested_account_skips_the_read(self) -> None:
        d = _FakeDispatch()
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            {"body": {"campaigns": [{"campaignId": "C1", "state": "PAUSED"}]}},
        )
        assert out is None
        assert d.calls == []

    async def test_missing_id_skips_the_read(self) -> None:
        d = _FakeDispatch()
        out = await rev.capture_reversal(
            d,
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"state": "PAUSED"}]),
        )
        assert out is None
        assert d.calls == []

    async def test_malformed_arguments_are_survived(self) -> None:
        d = _FakeDispatch()
        for args in ({}, {"body": None}, {"body": {"accessRequestedAccount": "x"}}):
            assert (
                await rev.capture_reversal(
                    d, "campaign_management-update_campaign_state", args
                )
                is None
            )
        assert d.calls == []


# ---------------------------------------------------------------------------
# The bridge method — best effort, scrubbed, never raises.
# ---------------------------------------------------------------------------


def _bridge(tmp_path: Path, dispatch: Any) -> Any:
    from mureo.amazon_ads.bridge import AmazonAdsBridge

    mp = tmp_path / "amazon_tools.json"
    mp.write_text(json.dumps({"tools": []}))
    bridge = AmazonAdsBridge(manifest_path=mp, creds_loader=lambda: None)
    # Capture must ride the bridge's own dispatch (auth/refresh); the fake
    # stands in for exactly that method.
    bridge.handle_mcp_tool = dispatch  # type: ignore[method-assign]
    return bridge


@pytest.mark.unit
class TestBridgeCaptureHook:
    async def test_bridge_capture_uses_its_own_dispatch(self, tmp_path) -> None:
        d = _FakeDispatch([{"campaigns": [{"campaignId": "C1", "state": "ENABLED"}]}])
        out = await _bridge(tmp_path, d).capture_reversal(
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is not None
        assert d.calls[0][0] == "campaign_management-query_campaign"

    async def test_bridge_satisfies_the_reversible_provider_protocol(
        self, tmp_path
    ) -> None:
        from mureo.mcp.tool_provider import MCPReversibleToolProvider

        assert isinstance(_bridge(tmp_path, _FakeDispatch()), MCPReversibleToolProvider)

    async def test_an_unpaired_tool_never_reaches_the_dispatch(self, tmp_path) -> None:
        d = _FakeDispatch()
        out = await _bridge(tmp_path, d).capture_reversal(
            "campaign_management-create_campaign",
            _mutation("campaigns", [{"campaignId": "C1"}]),
        )
        assert out is None
        assert d.calls == []

    async def test_a_timed_out_read_is_swallowed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(rev, "READ_TIMEOUT_SECONDS", 0.01)

        async def _hang(name: str, arguments: dict[str, Any]) -> list[Any]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        out = await _bridge(tmp_path, _hang).capture_reversal(
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None

    async def test_read_failure_is_swallowed(self, tmp_path) -> None:
        d = _FakeDispatch([RuntimeError("boom")])
        out = await _bridge(tmp_path, d).capture_reversal(
            "campaign_management-update_campaign_state",
            _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
        )
        assert out is None

    async def test_a_failed_probe_logs_its_type_and_never_its_text(
        self, tmp_path, caplog
    ) -> None:
        """The failure MESSAGE never reaches the log — not "the message with
        secrets masked", the message at all. Stronger than redaction, which
        can only remove what it recognises."""
        token = "Atza|SUPERSECRETTOKENVALUE"
        # The marker is deliberately NOT secret-shaped: a redactor would have
        # let it through, so its absence proves the whole text is dropped.
        d = _FakeDispatch([RuntimeError(f"401 rejected {token} marker-9f3a2c")])
        with caplog.at_level(logging.DEBUG):
            out = await _bridge(tmp_path, d).capture_reversal(
                "campaign_management-update_campaign_state",
                _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
            )
        assert out is None
        assert token not in caplog.text
        assert "SUPERSECRETTOKENVALUE" not in caplog.text
        assert "marker-9f3a2c" not in caplog.text
        # …while the diagnosis survives: what failed, and how.
        assert "RuntimeError" in caplog.text
        assert "campaign_management-query_campaign" in caplog.text

    async def test_a_failure_outside_the_probe_loop_logs_only_its_type(
        self, tmp_path, caplog, monkeypatch
    ) -> None:
        from mureo.amazon_ads import bridge as bmod

        async def _explode(*_a: Any, **_kw: Any) -> None:
            raise ValueError("Atza|SUPERSECRETTOKENVALUE marker-7b1e4d")

        monkeypatch.setattr(bmod, "_capture_reversal", _explode)
        with caplog.at_level(logging.DEBUG):
            out = await _bridge(tmp_path, _FakeDispatch()).capture_reversal(
                "campaign_management-update_campaign_state",
                _mutation("campaigns", [{"campaignId": "C1", "state": "PAUSED"}]),
            )
        assert out is None
        assert "SUPERSECRETTOKENVALUE" not in caplog.text
        assert "marker-7b1e4d" not in caplog.text
        assert "ValueError" in caplog.text
        assert "campaign_management-update_campaign_state" in caplog.text


# ---------------------------------------------------------------------------
# End to end through the MCP server: capture → action_log → plan_rollback.
# ---------------------------------------------------------------------------

_UPDATE_STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "body": {
            "type": "object",
            "properties": {
                "accessRequestedAccount": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {"advertiserAccountId": {"type": "string"}},
                            "required": ["advertiserAccountId"],
                        },
                        {
                            "type": "object",
                            "properties": {"profileId": {"type": "string"}},
                            "required": ["profileId"],
                        },
                    ]
                },
                "campaigns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "state": {
                                "type": "string",
                                "enum": ["ARCHIVED", "ENABLED", "PAUSED"],
                            },
                            "campaignId": {"type": "string"},
                        },
                        "required": ["campaignId", "state"],
                    },
                },
            },
            "required": ["accessRequestedAccount"],
        }
    },
}

_QUERY_CAMPAIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "body": {
            "type": "object",
            "properties": {
                "accessRequestedAccount": _UPDATE_STATE_SCHEMA["properties"]["body"][
                    "properties"
                ]["accessRequestedAccount"],
                "adProductFilter": {
                    "type": "object",
                    "properties": {
                        "include": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["include"],
                },
                "campaignIdFilter": {
                    "type": "object",
                    "properties": {
                        "include": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["include"],
                },
            },
            "required": ["accessRequestedAccount", "adProductFilter"],
        }
    },
    "required": ["body"],
}

_E2E_MANIFEST = {
    "generated_at": "2026-08-01T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [
        {
            "name": "campaign_management-update_campaign_state",
            "description": "Update campaign state.",
            "inputSchema": _UPDATE_STATE_SCHEMA,
        },
        {
            "name": "campaign_management-query_campaign",
            "description": "Query campaigns.",
            "inputSchema": _QUERY_CAMPAIGN_SCHEMA,
            "annotations": {"readOnlyHint": True},
        },
    ],
}


class _E2ESession:
    """Amazon side: answers the query with a realistic envelope, the mutation
    with an opaque ok. ``fail_query`` makes every read blow up."""

    def __init__(self, calls: list[Any], *, fail_query: bool) -> None:
        self._calls = calls
        self._fail_query = fail_query

    async def initialize(self) -> None: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        from mcp.types import TextContent

        self._calls.append((name, arguments))
        if name == "campaign_management-query_campaign":
            if self._fail_query:
                raise RuntimeError("Amazon read failed (Atza|SECRET)")
            payload: Any = {
                "campaigns": [{"campaignId": "C1", "state": "ENABLED"}],
            }
        else:
            payload = {"success": True}
        return type(
            "R", (), {"content": [TextContent(type="text", text=json.dumps(payload))]}
        )()


def _reload_server(monkeypatch, tmp_path: Path, calls: list, *, fail_query: bool):
    from mureo.amazon_ads import bridge as bmod
    from mureo.auth import AmazonAdsCredentials
    from mureo.mcp import plugin_audit

    mp = tmp_path / "amazon_tools.json"
    mp.write_text(json.dumps(_E2E_MANIFEST))

    def _connect(url, headers):
        class _CM:
            async def __aenter__(self):
                return _E2ESession(calls, fail_query=fail_query)

            async def __aexit__(self, *e):
                return False

        return _CM()

    monkeypatch.setattr(
        "mureo.core.providers.registry.discover_providers", lambda **_kw: ()
    )
    monkeypatch.setattr(bmod, "manifest_path", lambda: mp)
    monkeypatch.setattr(
        bmod,
        "load_amazon_ads_credentials",
        lambda *a, **k: AmazonAdsCredentials(
            client_id="cid", access_token="Atza|SECRET"
        ),
    )
    monkeypatch.setattr(bmod, "_default_connect", _connect)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    from mureo.mcp import server as mod

    return importlib.reload(mod)


def _seed_state(d: Path) -> None:
    from mureo.context.models import StateDocument
    from mureo.context.state import write_state_file

    write_state_file(d / "STATE.json", StateDocument())


_E2E_ARGS = {
    "body": {
        "accessRequestedAccount": {"profileId": "1234567890"},
        "campaigns": [{"campaignId": "C1", "state": "PAUSED"}],
    }
}


@pytest.mark.integration
class TestEndToEndRollbackPlan:
    async def test_capture_makes_the_mutation_executably_reversible(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file
        from mureo.rollback.models import RollbackStatus
        from mureo.rollback.planner import plan_rollback

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        calls: list[Any] = []
        mod = _reload_server(monkeypatch, tmp_path, calls, fail_query=False)
        try:
            out = await mod.handle_call_tool(
                "campaign_management-update_campaign_state", copy.deepcopy(_E2E_ARGS)
            )
            assert out
            # The read happened BEFORE the write.
            assert [c[0] for c in calls][:2] == [
                "campaign_management-query_campaign",
                "campaign_management-update_campaign_state",
            ]
            entry = read_state_file(tmp_path / "STATE.json").action_log[0]
            assert entry.reversible_params is not None
            plan = plan_rollback(entry)
            assert plan is not None
            assert plan.status is not RollbackStatus.NOT_SUPPORTED
            assert plan.operation == "campaign_management-update_campaign_state"
            # The planned call carries the OLD value.
            assert plan.params is not None
            assert plan.params["body"]["campaigns"] == [
                {"campaignId": "C1", "state": "ENABLED"}
            ]
        finally:
            importlib.reload(mod)

    async def test_the_capture_read_is_inside_the_mutation_throttle_slot(
        self, monkeypatch, tmp_path
    ) -> None:
        """The capture issues real platform reads, so it must not run before
        the mutation's rate-limit slot is acquired."""
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        calls: list[Any] = []
        mod = _reload_server(monkeypatch, tmp_path, calls, fail_query=False)
        try:
            real_throttle = mod._acquire_plugin_throttle

            async def _recording_throttle(name: str) -> None:
                calls.append(("throttle", name))
                await real_throttle(name)

            monkeypatch.setattr(mod, "_acquire_plugin_throttle", _recording_throttle)
            await mod.handle_call_tool(
                "campaign_management-update_campaign_state", copy.deepcopy(_E2E_ARGS)
            )
            assert [c[0] for c in calls] == [
                "throttle",
                "campaign_management-query_campaign",
                "campaign_management-update_campaign_state",
            ]
        finally:
            importlib.reload(mod)

    async def test_capture_failure_never_blocks_the_write(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        calls: list[Any] = []
        mod = _reload_server(monkeypatch, tmp_path, calls, fail_query=True)
        try:
            out = await mod.handle_call_tool(
                "campaign_management-update_campaign_state", copy.deepcopy(_E2E_ARGS)
            )
            assert out  # the mutation still ran and returned Amazon's content
            assert "campaign_management-update_campaign_state" in [c[0] for c in calls]
            entry = read_state_file(tmp_path / "STATE.json").action_log[0]
            assert entry.action == "campaign_management-update_campaign_state"
            assert entry.reversible_params is None  # audit-only, not a guess
        finally:
            importlib.reload(mod)
