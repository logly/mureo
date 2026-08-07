"""Tracking-parameter consistency tests (issue #550).

Pure detection functions: no I/O, no mocks. The fixtures reproduce the
anonymised incident from the issue — two audience-segment Display
campaigns pointing at the same eight landing pages, distinguishable in
analytics only by a ``utm_campaign`` prefix, where sixteen ads carrying
segment A's prefix were uploaded into segment B's campaign.

The most important tests in this module are the **negative** ones: a
check that fires on legitimate per-article variation (``segb01`` vs
``segb02``) would be switched off by its first user, so the false
positives are pinned as hard as the true positives.
"""

from __future__ import annotations

import pytest

from mureo.analysis.tracking import (
    AdTrackingRecord,
    DeliveryState,
    TrackingSeverity,
    check_tracking_consistency,
    parse_tracking_convention,
    preflight_tracking_consistency,
)

# Landing pages shared by both segment campaigns — the analytics split
# between the segments exists ONLY in the utm_campaign prefix.
_ARTICLES = tuple(range(1, 9))


def _url(
    article: int, campaign_value: str, *, source: str = "google", medium: str = "cpc"
) -> str:
    return (
        f"https://example.com/article/{article}/"
        f"?utm_source={source}&utm_medium={medium}&utm_campaign={campaign_value}"
    )


def _ad(
    ad_id: str,
    campaign_id: str,
    url: str,
    *,
    platform: str = "google_ads",
    campaign_name: str = "",
    impressions: int | None = None,
) -> AdTrackingRecord:
    return AdTrackingRecord(
        ad_id=ad_id,
        campaign_id=campaign_id,
        final_urls=(url,),
        platform=platform,
        campaign_name=campaign_name,
        impressions=impressions,
    )


def _segment_a_campaign(*, impressions: int | None = None) -> list[AdTrackingRecord]:
    """Segment A's campaign: eight correctly-tagged ads, one per article."""
    return [
        _ad(
            f"a{n}",
            "campaign-a",
            _url(n, f"sega0{n}"),
            campaign_name="Display / Segment A",
            impressions=impressions,
        )
        for n in _ARTICLES
    ]


def _segment_b_campaign(*, impressions: int | None = None) -> list[AdTrackingRecord]:
    """Segment B's campaign: eight correctly-tagged ads, one per article."""
    return [
        _ad(
            f"b{n}",
            "campaign-b",
            _url(n, f"segb0{n}"),
            campaign_name="Display / Segment B",
            impressions=impressions,
        )
        for n in _ARTICLES
    ]


def _mis_tagged_into_b(*, impressions: int | None = None) -> list[AdTrackingRecord]:
    """The incident: 16 ads carrying segment A's prefix, in B's campaign."""
    return [
        _ad(
            f"x{n}-{copy}",
            "campaign-b",
            _url(n, f"sega0{n}"),
            campaign_name="Display / Segment B",
            impressions=impressions,
        )
        for n in _ARTICLES
        for copy in (1, 2)
    ]


def _codes(report) -> set[str]:  # noqa: ANN001 - report type is under test
    return {f.code for f in report.findings}


def _findings(report, code: str):  # noqa: ANN001 - report type is under test
    return [f for f in report.findings if f.code == code]


@pytest.mark.unit
class TestForeignCampaignScheme:
    """The incident: segment A's prefix inside segment B's campaign."""

    def test_detects_segment_a_prefix_inside_segment_b_campaign(self) -> None:
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign(), *_mis_tagged_into_b()]
        )

        foreign = _findings(report, "foreign_campaign_scheme")
        assert foreign, "the 16 mis-tagged ads must be reported"
        assert {f.campaign_id for f in foreign} == {"campaign-b"}
        flagged = {ad_id for f in foreign for ad_id in f.ad_ids}
        assert flagged == {f"x{n}-{c}" for n in _ARTICLES for c in (1, 2)}
        # The finding must name the campaign the scheme actually belongs to,
        # so the operator does not have to work it out during an audit.
        evidence = dict(foreign[0].evidence)
        assert evidence["owning_campaign_id"] == "campaign-a"
        # Only utm_campaign separates the two segments; utm_source and
        # utm_medium are identical across the whole account and must not
        # be reported as the thing that differs.
        assert evidence["differing_parameters"] == "utm_campaign"

    def test_does_not_flag_the_correctly_tagged_ads_in_the_same_campaign(self) -> None:
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign(), *_mis_tagged_into_b()]
        )
        flagged = {ad_id for f in report.findings for ad_id in f.ad_ids}
        assert not flagged & {f"a{n}" for n in _ARTICLES}

    def test_detects_a_third_scheme_borrowed_from_a_social_campaign(self) -> None:
        """``utm_source=sns_cp&utm_medium=cpci`` inside a Display campaign."""
        social = [
            _ad(
                f"s{n}",
                "campaign-social",
                _url(n, f"sns0{n}", source="sns_cp", medium="cpci"),
                campaign_name="Social / Retargeting",
            )
            for n in (1, 2, 3)
        ]
        display = [
            _ad(
                f"d{n}",
                "campaign-display",
                _url(n, f"disp0{n}"),
                campaign_name="Display / Prospecting",
            )
            for n in (4, 5, 6, 7)
        ]
        borrowed = [
            _ad(
                f"d{n}-bad",
                "campaign-display",
                _url(n, f"sns0{n}", source="sns_cp", medium="cpci"),
            )
            for n in (1, 2)
        ]

        report = check_tracking_consistency([*social, *display, *borrowed])

        foreign = _findings(report, "foreign_campaign_scheme")
        assert foreign
        flagged = {ad_id for f in foreign for ad_id in f.ad_ids}
        assert flagged == {"d1-bad", "d2-bad"}
        # The whole identifying signature was borrowed, so all three
        # campaign-identifying parameters are named as differing.
        differing = dict(foreign[0].evidence)["differing_parameters"]
        assert "utm_source" in differing
        assert "utm_medium" in differing

    def test_detects_a_foreign_scheme_on_a_non_google_platform(self) -> None:
        """Meta Ads records go through the same core check, unchanged."""
        brand = [
            _ad(
                f"m{n}",
                "meta-brand",
                _url(n, f"brand0{n}"),
                platform="meta_ads",
                campaign_name="Meta / Brand",
            )
            for n in (1, 2, 3)
        ]
        promo = [
            _ad(f"p{n}", "meta-promo", _url(n, f"promo0{n}"), platform="meta_ads")
            for n in (4, 5, 6)
        ]
        leaked = [
            _ad(f"p{n}-bad", "meta-promo", _url(n, f"brand0{n}"), platform="meta_ads")
            for n in (1, 2)
        ]

        report = check_tracking_consistency([*brand, *promo, *leaked])

        foreign = _findings(report, "foreign_campaign_scheme")
        assert foreign
        assert {f.platform for f in foreign} == {"meta_ads"}
        assert {ad_id for f in foreign for ad_id in f.ad_ids} == {"p1-bad", "p2-bad"}

    def test_does_not_cross_platform_boundaries(self) -> None:
        """A Google scheme and a Meta scheme are never compared."""
        google = [
            _ad(f"g{n}", "g-campaign", _url(n, f"sega0{n}"), platform="google_ads")
            for n in (1, 2, 3)
        ]
        meta = [
            _ad(f"m{n}", "m-campaign", _url(n, f"sega0{n}"), platform="meta_ads")
            for n in (1, 2, 3)
        ]
        report = check_tracking_consistency([*google, *meta])
        assert not report.findings


@pytest.mark.unit
class TestSameDestinationConflict:
    """Two ads at the same landing page carrying different schemes."""

    def test_detects_a_scheme_conflict_on_one_landing_page(self) -> None:
        """Fires without any other campaign to compare against."""
        records = [
            _ad("b1", "campaign-b", _url(1, "segb01")),
            _ad("b2", "campaign-b", _url(2, "segb02")),
            _ad("x1", "campaign-b", _url(1, "sega01")),
            _ad("x2", "campaign-b", _url(2, "sega02")),
        ]
        report = check_tracking_consistency(records)

        conflicts = _findings(report, "same_destination_scheme_conflict")
        assert conflicts
        assert {ad_id for f in conflicts for ad_id in f.ad_ids} == {
            "b1",
            "x1",
            "b2",
            "x2",
        }

    def test_same_destination_same_scheme_is_not_a_conflict(self) -> None:
        """Two ads on one LP with the same scheme and different serials."""
        records = [
            _ad("b1", "campaign-b", _url(1, "segb01")),
            _ad("b2", "campaign-b", _url(1, "segb02")),
        ]
        assert not check_tracking_consistency(records).findings


@pytest.mark.unit
class TestNoFalsePositives:
    """A check that cries wolf gets switched off. These pin that it does not."""

    def test_serial_variation_within_one_scheme_is_not_a_finding(self) -> None:
        """``segb01`` .. ``segb08``, one per article — the legitimate case."""
        report = check_tracking_consistency(_segment_b_campaign())
        assert report.findings == ()

    def test_two_campaigns_each_internally_consistent_are_not_findings(self) -> None:
        """Segment A and segment B side by side, correctly tagged."""
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign()]
        )
        assert report.findings == ()

    def test_two_campaigns_deliberately_sharing_one_scheme_is_not_a_finding(
        self,
    ) -> None:
        """Whole-campaign sharing is deliberate far more often than not."""
        shared_a = [_ad(f"a{n}", "campaign-a", _url(n, "always_on")) for n in (1, 2, 3)]
        shared_b = [_ad(f"b{n}", "campaign-b", _url(n, "always_on")) for n in (4, 5, 6)]
        assert not check_tracking_consistency([*shared_a, *shared_b]).findings

    def test_per_landing_page_word_tokens_are_not_a_finding(self) -> None:
        """utm_campaign varying by LP name, two ads each — no numeric serial."""
        pages = ("pricing", "toppage", "cases", "faq")
        records = [
            _ad(
                f"{page}-{copy}",
                "campaign-b",
                f"https://example.com/{page}/?utm_source=google&utm_medium=cpc&utm_campaign={page}",
            )
            for page in pages
            for copy in (1, 2)
        ]
        assert not check_tracking_consistency(records).findings

    def test_a_single_ad_account_produces_nothing(self) -> None:
        assert not check_tracking_consistency(
            [_ad("a1", "campaign-a", _url(1, "sega01"))]
        ).findings

    def test_untagged_account_produces_nothing(self) -> None:
        """No recognised tracking parameters anywhere = nothing to compare."""
        records = [
            _ad(f"a{n}", "campaign-a", f"https://example.com/article/{n}/")
            for n in (1, 2, 3)
        ]
        assert not check_tracking_consistency(records).findings


@pytest.mark.unit
class TestCreativeDifferentiatingParametersAreNotSchemes:
    """utm_content / utm_term vary within one campaign by design.

    Comparing on them flags ordinary creative differentiation, which is
    the single most likely way an operator ends up muting the check.
    """

    def test_utm_content_varying_per_creative_on_one_landing_page(self) -> None:
        records = [
            _ad(
                f"ad-{creative}",
                "campaign-prospecting",
                "https://example.com/lp/?utm_source=google&utm_medium=display"
                f"&utm_campaign=prospecting&utm_content={creative}",
            )
            for creative in ("hero", "video", "carousel", "static")
        ]
        assert check_tracking_consistency(records).findings == ()

    def test_utm_term_varying_per_keyword_on_one_landing_page(self) -> None:
        records = [
            _ad(
                f"ad-{term}",
                "campaign-brand",
                "https://example.com/lp/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=brand&utm_term={term}",
            )
            for term in ("shoes", "sneakers", "trainers")
        ]
        assert check_tracking_consistency(records).findings == ()

    def test_utm_content_is_not_borrowed_across_campaigns(self) -> None:
        """One campaign's creative names reused in another is not a leak."""
        a = [
            _ad(
                f"a{n}",
                "campaign-a",
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=sega&utm_content=hero",
            )
            for n in (1, 2, 3)
        ]
        b = [
            _ad(
                f"b{n}",
                "campaign-b",
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=segb&utm_content={creative}",
            )
            for n, creative in ((4, "hero"), (5, "video"), (6, "video"))
        ]
        assert check_tracking_consistency([*a, *b]).findings == ()

    def test_declared_identify_can_promote_utm_content(self) -> None:
        """An account whose segment lives in utm_content declares it."""
        convention = parse_tracking_convention(
            "## Tracking Convention\n\n- identify: utm_content\n"
        )
        a = [
            _ad(
                f"a{n}",
                "campaign-a",
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=always_on&utm_content=sega",
            )
            for n in (1, 2, 3)
        ]
        b = [
            _ad(
                f"b{n}",
                "campaign-b",
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=always_on&utm_content=segb",
            )
            for n in (4, 5, 6)
        ]
        leaked = [
            _ad(
                f"b{n}-bad",
                "campaign-b",
                f"https://example.com/lp/{n}/?utm_source=google&utm_medium=cpc"
                f"&utm_campaign=always_on&utm_content=sega",
            )
            for n in (7, 8)
        ]
        assert check_tracking_consistency([*a, *b, *leaked]).findings == ()

        report = check_tracking_consistency([*a, *b, *leaked], convention=convention)
        assert {ad for f in report.findings for ad in f.ad_ids} == {"b7-bad", "b8-bad"}


@pytest.mark.unit
class TestSharedValuesAreNotBorrowedSchemes:
    """A value two campaigns merely share is not evidence of a leak.

    Schemes are compared as whole identifying signatures for exactly
    this reason. Comparing one parameter at a time reported "these ads
    borrowed campaign Y's utm_source" for a value like ``google``, and
    below three campaigns ``google`` IS owned by exactly one other
    campaign — so the correctly-tagged majority got flagged.
    """

    # Distinct per-campaign utm_campaign tokens — every campaign shares
    # utm_source=google and utm_medium=cpc, as almost every real account
    # does.
    _TOKENS = ("spring_promo", "brand_always_on", "retargeting")

    def _account(self, campaigns: int) -> list[AdTrackingRecord]:
        records: list[AdTrackingRecord] = []
        for index in range(campaigns):
            name = f"campaign-{index}"
            records.extend(
                _ad(f"{name}-ad{n}", name, _url(n, f"{self._TOKENS[index]}0{n}"))
                for n in (1, 2, 3)
            )
        return records

    def test_two_campaign_account_with_one_off_ad_is_not_flagged(self) -> None:
        """The reviewer's repro: co-marketing one-off inside campaign X."""
        records = [
            *self._account(2),
            _ad(
                "campaign-0-oneoff",
                "campaign-0",
                _url(9, "newsletter", source="newsletter", medium="email"),
            ),
        ]
        report = check_tracking_consistency(records)
        assert _findings(report, "foreign_campaign_scheme") == []

    def test_adding_a_third_campaign_does_not_change_the_verdict(self) -> None:
        """The old mechanism made the finding vanish at three campaigns."""
        records = [
            *self._account(3),
            _ad(
                "campaign-0-oneoff",
                "campaign-0",
                _url(9, "newsletter", source="newsletter", medium="email"),
            ),
        ]
        assert (
            _findings(check_tracking_consistency(records), "foreign_campaign_scheme")
            == []
        )

    def test_shared_source_and_medium_alone_never_fire(self) -> None:
        """Every campaign in the account is google/cpc — that is normal."""
        report = check_tracking_consistency(self._account(2))
        assert report.findings == ()

    def test_the_incident_is_still_caught_in_a_two_campaign_account(self) -> None:
        """A minimum campaign count would have switched this off.

        The motivating incident happened in an account with exactly two
        Display campaigns, so requiring three campaigns before the check
        runs would have disabled it for the case it exists for.
        """
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign(), *_mis_tagged_into_b()]
        )
        assert _findings(report, "foreign_campaign_scheme")


@pytest.mark.unit
class TestMissingParameters:
    def test_missing_parameter_the_rest_of_the_campaign_carries(self) -> None:
        records = [
            *_segment_b_campaign(),
            _ad(
                "b9",
                "campaign-b",
                "https://example.com/article/9/?utm_source=google&utm_campaign=segb09",
            ),
        ]
        report = check_tracking_consistency(records)
        missing = _findings(report, "missing_tracking_parameter")
        assert missing
        assert missing[0].ad_ids == ("b9",)
        assert dict(missing[0].evidence)["parameter"] == "utm_medium"

    def test_untagged_url_inside_a_tagged_campaign(self) -> None:
        records = [
            *_segment_b_campaign(),
            _ad("b9", "campaign-b", "https://example.com/article/9/"),
        ]
        report = check_tracking_consistency(records)
        untagged = _findings(report, "untagged_final_url")
        assert untagged
        assert untagged[0].ad_ids == ("b9",)


@pytest.mark.unit
class TestSeverityReflectsDeliveryState:
    def test_a_mis_tagged_ad_that_served_is_critical(self) -> None:
        report = check_tracking_consistency(
            [
                *_segment_a_campaign(impressions=5000),
                *_segment_b_campaign(impressions=5000),
                *_mis_tagged_into_b(impressions=1200),
            ]
        )
        foreign = _findings(report, "foreign_campaign_scheme")
        assert foreign
        assert all(f.severity is TrackingSeverity.CRITICAL for f in foreign)
        assert all(f.delivery_state is DeliveryState.SERVED for f in foreign)

    def test_a_mis_tagged_ad_that_never_served_is_high(self) -> None:
        report = check_tracking_consistency(
            [
                *_segment_a_campaign(impressions=5000),
                *_segment_b_campaign(impressions=5000),
                *_mis_tagged_into_b(impressions=0),
            ]
        )
        foreign = _findings(report, "foreign_campaign_scheme")
        assert foreign
        assert all(f.severity is TrackingSeverity.HIGH for f in foreign)
        assert all(f.delivery_state is DeliveryState.NOT_SERVED for f in foreign)

    def test_delivery_state_unknown_when_impressions_were_not_supplied(self) -> None:
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign(), *_mis_tagged_into_b()]
        )
        foreign = _findings(report, "foreign_campaign_scheme")
        assert all(f.delivery_state is DeliveryState.UNKNOWN for f in foreign)
        assert any("delivery" in note for note in report.notes)


@pytest.mark.unit
class TestPreflight:
    def test_planned_ad_carrying_another_campaigns_scheme_is_blocked(self) -> None:
        existing = [*_segment_a_campaign(), *_segment_b_campaign()]
        planned = [
            AdTrackingRecord(
                ad_id="planned-1",
                campaign_id="campaign-b",
                final_urls=(_url(3, "sega03"),),
                platform="google_ads",
                planned=True,
            )
        ]
        report = preflight_tracking_consistency(planned, existing)
        assert report.findings
        assert {ad_id for f in report.findings for ad_id in f.ad_ids} == {"planned-1"}

    def test_a_correctly_tagged_planned_ad_passes(self) -> None:
        existing = [*_segment_a_campaign(), *_segment_b_campaign()]
        planned = [
            AdTrackingRecord(
                ad_id="planned-1",
                campaign_id="campaign-b",
                final_urls=(_url(9, "segb09"),),
                platform="google_ads",
                planned=True,
            )
        ]
        assert preflight_tracking_consistency(planned, existing).findings == ()

    def test_preflight_never_reports_pre_existing_problems(self) -> None:
        """The operator uploading one ad is not asked to fix the account."""
        existing = [
            *_segment_a_campaign(),
            *_segment_b_campaign(),
            *_mis_tagged_into_b(),
        ]
        planned = [
            AdTrackingRecord(
                ad_id="planned-1",
                campaign_id="campaign-b",
                final_urls=(_url(9, "segb09"),),
                platform="google_ads",
                planned=True,
            )
        ]
        assert preflight_tracking_consistency(planned, existing).findings == ()


@pytest.mark.unit
class TestConvention:
    _MARKDOWN = """
# Strategy

## Tracking Convention

- recognize: utm_*, argument
- require: utm_source, utm_medium, utm_campaign
- pattern utm_source: google, yahoo
- pattern utm_campaign: seg[ab]??

## Persona

Someone else's section.
"""

    def test_parses_the_declared_convention(self) -> None:
        convention = parse_tracking_convention(self._MARKDOWN)
        assert convention is not None
        assert convention.recognize == ("utm_*", "argument")
        assert convention.require == ("utm_source", "utm_medium", "utm_campaign")
        assert dict(convention.patterns)["utm_source"] == ("google", "yahoo")

    def test_absent_section_returns_none(self) -> None:
        assert (
            parse_tracking_convention("# Strategy\n\n## Persona\n\nNothing here.\n")
            is None
        )

    def test_value_outside_the_declared_pattern_is_flagged(self) -> None:
        convention = parse_tracking_convention(self._MARKDOWN)
        records = [
            *_segment_b_campaign(),
            _ad("b9", "campaign-b", _url(9, "spring_sale")),
        ]
        report = check_tracking_consistency(records, convention=convention)
        violations = _findings(report, "convention_violation")
        assert violations
        assert violations[0].ad_ids == ("b9",)

    def test_declared_required_parameter_is_flagged_when_absent(self) -> None:
        convention = parse_tracking_convention(self._MARKDOWN)
        records = [
            _ad(
                "b1",
                "campaign-b",
                "https://example.com/article/1/?utm_source=google&utm_campaign=segb01",
            )
        ]
        report = check_tracking_consistency(records, convention=convention)
        missing = _findings(report, "missing_required_parameter")
        assert missing
        assert dict(missing[0].evidence)["parameter"] == "utm_medium"

    def test_conforming_values_are_not_flagged(self) -> None:
        convention = parse_tracking_convention(self._MARKDOWN)
        report = check_tracking_consistency(
            _segment_b_campaign(), convention=convention
        )
        assert report.findings == ()

    def test_declared_identify_extends_the_compared_parameters(self) -> None:
        """A non-utm scheme is invisible by default and visible once declared.

        ``identify:`` implies recognition — a parameter cannot be
        compared without first being read.
        """
        convention = parse_tracking_convention(
            "## Tracking Convention\n\n- identify: argument\n"
        )
        a = [
            _ad(f"a{n}", "campaign-a", f"https://example.com/lp/{n}/?argument=sega0{n}")
            for n in (1, 2, 3)
        ]
        b = [
            _ad(f"b{n}", "campaign-b", f"https://example.com/lp/{n}/?argument=segb0{n}")
            for n in (4, 5, 6)
        ]
        leaked = [
            _ad(
                f"b{n}-bad",
                "campaign-b",
                f"https://example.com/lp/{n}/?argument=sega0{n}",
            )
            for n in (1, 2)
        ]

        assert check_tracking_consistency([*a, *b, *leaked]).findings == ()

        report = check_tracking_consistency([*a, *b, *leaked], convention=convention)
        assert {ad_id for f in report.findings for ad_id in f.ad_ids} == {
            "b1-bad",
            "b2-bad",
        }


@pytest.mark.unit
class TestReportShape:
    def test_report_counts_what_it_examined(self) -> None:
        report = check_tracking_consistency(
            [*_segment_a_campaign(), *_segment_b_campaign()]
        )
        assert report.ads_examined == 16
        assert report.campaigns_examined == 2

    def test_ads_without_a_readable_url_are_named_not_silently_skipped(self) -> None:
        records = [
            *_segment_b_campaign(),
            AdTrackingRecord(
                ad_id="b9",
                campaign_id="campaign-b",
                final_urls=(),
                platform="google_ads",
            ),
        ]
        report = check_tracking_consistency(records)
        assert report.ads_without_readable_url == ("b9",)
