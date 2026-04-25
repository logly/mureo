"""Generate static demo CSV/MD files into mureo/_data/demo/.

Run once at dev time. Outputs are committed to the repo as package data.

The data carries an embedded narrative (see spec §4.1):
  - Brand Search campaign CPA spikes ~45% from day -7 onward
  - Search Console brand keyword position drops from #1 to #5 on day -7
  - Meta Ads CTR is stable (false-positive creative-fatigue distractor)

Dates are stored as relative `day_offset` integers; mureo demo init
resolves them to today-anchored absolute dates at install time.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

SEED = 42
DATA_ROOT = Path(__file__).parent.parent / "mureo" / "_data" / "demo"
SCHEMA_VERSION = 1

INCIDENT_DAY = -7


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_google_ads(rng: random.Random) -> None:
    out = DATA_ROOT / "google_ads"

    campaigns = [
        {
            "campaign_id": "12345001",
            "name": "[DEMO] Brand Search",
            "status": "ENABLED",
            "channel_type": "SEARCH",
            "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
            "daily_budget_jpy": 5000,
            "start_offset": -30,
            "end_offset": "",
        },
        {
            "campaign_id": "12345002",
            "name": "[DEMO] Generic Search",
            "status": "ENABLED",
            "channel_type": "SEARCH",
            "bidding_strategy_type": "TARGET_CPA",
            "daily_budget_jpy": 8000,
            "start_offset": -60,
            "end_offset": "",
        },
        {
            "campaign_id": "12345003",
            "name": "[DEMO] Display Retargeting",
            "status": "ENABLED",
            "channel_type": "DISPLAY",
            "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
            "daily_budget_jpy": 3000,
            "start_offset": -45,
            "end_offset": "",
        },
    ]
    _write_csv(
        out / "campaigns.csv",
        [
            "campaign_id",
            "name",
            "status",
            "channel_type",
            "bidding_strategy_type",
            "daily_budget_jpy",
            "start_offset",
            "end_offset",
        ],
        campaigns,
    )

    ad_groups = [
        {
            "ad_group_id": "67890001",
            "campaign_id": "12345001",
            "name": "[DEMO] Brand - Exact",
            "status": "ENABLED",
        },
        {
            "ad_group_id": "67890002",
            "campaign_id": "12345001",
            "name": "[DEMO] Brand - Phrase",
            "status": "ENABLED",
        },
        {
            "ad_group_id": "67890003",
            "campaign_id": "12345002",
            "name": "[DEMO] Generic - Demo Software",
            "status": "ENABLED",
        },
        {
            "ad_group_id": "67890004",
            "campaign_id": "12345002",
            "name": "[DEMO] Generic - SaaS Trial",
            "status": "ENABLED",
        },
        {
            "ad_group_id": "67890005",
            "campaign_id": "12345003",
            "name": "[DEMO] Retargeting - 30d",
            "status": "ENABLED",
        },
    ]
    _write_csv(
        out / "ad_groups.csv",
        ["ad_group_id", "campaign_id", "name", "status"],
        ad_groups,
    )

    ads = []
    for i, ag in enumerate(ad_groups):
        for j in range(2 if i < 4 else 4):
            ads.append(
                {
                    "ad_id": f"99000{i:02d}{j}",
                    "ad_group_id": ag["ad_group_id"],
                    "headline_1": f"[DEMO] Headline {i}-{j}",
                    "headline_2": "[DEMO] B2B SaaS for Growth Teams",
                    "description": "[DEMO] Start your free trial today.",
                    "final_url": "https://example.com/demo",
                    "status": "ENABLED",
                }
            )
    _write_csv(
        out / "ads.csv",
        [
            "ad_id",
            "ad_group_id",
            "headline_1",
            "headline_2",
            "description",
            "final_url",
            "status",
        ],
        ads,
    )

    keywords = []
    brand_kws = ["[DEMO] mureo", "[DEMO] mureo software", "[DEMO] mureo demo"]
    generic_kws = [
        "[DEMO] ad ops automation",
        "[DEMO] ai marketing ops",
        "[DEMO] saas marketing tool",
        "[DEMO] google ads automation",
        "[DEMO] meta ads ai",
    ]
    for i, text in enumerate(brand_kws):
        keywords.append(
            {
                "keyword_id": f"kw{i:04d}",
                "ad_group_id": "67890001" if i % 2 == 0 else "67890002",
                "text": text,
                "match_type": "EXACT",
                "status": "ENABLED",
            }
        )
    for i, text in enumerate(generic_kws):
        keywords.append(
            {
                "keyword_id": f"kw{100 + i:04d}",
                "ad_group_id": "67890003" if i % 2 == 0 else "67890004",
                "text": text,
                "match_type": "PHRASE",
                "status": "ENABLED",
            }
        )
    base_count = len(keywords)
    for i in range(30 - base_count):
        keywords.append(
            {
                "keyword_id": f"kw{200 + i:04d}",
                "ad_group_id": rng.choice(["67890003", "67890004"]),
                "text": f"[DEMO] keyword variant {i}",
                "match_type": rng.choice(["BROAD", "PHRASE"]),
                "status": "ENABLED",
            }
        )
    _write_csv(
        out / "keywords.csv",
        ["keyword_id", "ad_group_id", "text", "match_type", "status"],
        keywords,
    )

    metrics = []
    for day in range(-13, 1):
        for ag in ad_groups:
            campaign_id = ag["campaign_id"]
            ad_group_id = ag["ad_group_id"]
            is_incident = day >= INCIDENT_DAY

            base_imp = {
                "12345001": 4500,
                "12345002": 8200,
                "12345003": 12000,
            }[campaign_id]
            imp_per_ag = base_imp // sum(
                1 for x in ad_groups if x["campaign_id"] == campaign_id
            )
            imp = int(imp_per_ag * rng.uniform(0.85, 1.15))

            ctr = {"12345001": 0.08, "12345002": 0.03, "12345003": 0.004}[campaign_id]
            clicks = int(imp * ctr * rng.uniform(0.9, 1.1))

            if campaign_id == "12345001":
                cpc = 400 if is_incident else 250
            elif campaign_id == "12345002":
                cpc = 180
            else:
                cpc = 80
            cpc = int(cpc * rng.uniform(0.95, 1.05))
            cost = clicks * cpc

            cvr = {"12345001": 0.12, "12345002": 0.04, "12345003": 0.005}[campaign_id]
            convs = round(clicks * cvr * rng.uniform(0.85, 1.15), 1)

            metrics.append(
                {
                    "day_offset": day,
                    "campaign_id": campaign_id,
                    "ad_group_id": ad_group_id,
                    "impressions": imp,
                    "clicks": clicks,
                    "cost_jpy": cost,
                    "conversions": convs,
                }
            )
    _write_csv(
        out / "metrics_daily.csv",
        [
            "day_offset",
            "campaign_id",
            "ad_group_id",
            "impressions",
            "clicks",
            "cost_jpy",
            "conversions",
        ],
        metrics,
    )


def generate_meta_ads(rng: random.Random) -> None:
    out = DATA_ROOT / "meta_ads"

    campaigns = [
        {
            "campaign_id": "120330001",
            "name": "[DEMO] Awareness - Lookalike",
            "status": "ACTIVE",
            "objective": "OUTCOME_AWARENESS",
            "daily_budget_jpy": 4000,
            "start_offset": -30,
        },
        {
            "campaign_id": "120330002",
            "name": "[DEMO] Conversion - Demo Request",
            "status": "ACTIVE",
            "objective": "OUTCOME_LEADS",
            "daily_budget_jpy": 6000,
            "start_offset": -45,
        },
        {
            "campaign_id": "120330003",
            "name": "[DEMO] Retargeting - 7d",
            "status": "ACTIVE",
            "objective": "OUTCOME_LEADS",
            "daily_budget_jpy": 2500,
            "start_offset": -20,
        },
    ]
    _write_csv(
        out / "campaigns.csv",
        [
            "campaign_id",
            "name",
            "status",
            "objective",
            "daily_budget_jpy",
            "start_offset",
        ],
        campaigns,
    )

    ad_sets = [
        {
            "ad_set_id": "120440001",
            "campaign_id": "120330001",
            "name": "[DEMO] LAL 1% - JP",
            "status": "ACTIVE",
        },
        {
            "ad_set_id": "120440002",
            "campaign_id": "120330001",
            "name": "[DEMO] LAL 3% - JP",
            "status": "ACTIVE",
        },
        {
            "ad_set_id": "120440003",
            "campaign_id": "120330002",
            "name": "[DEMO] Interest - SaaS Decision Makers",
            "status": "ACTIVE",
        },
        {
            "ad_set_id": "120440004",
            "campaign_id": "120330002",
            "name": "[DEMO] Interest - Marketing Ops",
            "status": "ACTIVE",
        },
        {
            "ad_set_id": "120440005",
            "campaign_id": "120330003",
            "name": "[DEMO] Website 7d",
            "status": "ACTIVE",
        },
    ]
    _write_csv(
        out / "ad_sets.csv",
        ["ad_set_id", "campaign_id", "name", "status"],
        ad_sets,
    )

    ads = []
    for i, ag in enumerate(ad_sets):
        for j in range(2 if i < 3 else 1):
            ads.append(
                {
                    "ad_id": f"120550{i:02d}{j}",
                    "ad_set_id": ag["ad_set_id"],
                    "name": f"[DEMO] Creative {i}-{j}",
                    "status": "ACTIVE",
                }
            )
    while len(ads) < 8:
        ads.append(
            {
                "ad_id": f"120550{len(ads):02d}9",
                "ad_set_id": "120440005",
                "name": f"[DEMO] Creative variant {len(ads)}",
                "status": "ACTIVE",
            }
        )
    _write_csv(
        out / "ads.csv",
        ["ad_id", "ad_set_id", "name", "status"],
        ads,
    )

    metrics = []
    for day in range(-13, 1):
        for ad_set in ad_sets:
            campaign_id = ad_set["campaign_id"]
            base_imp = {"120330001": 22000, "120330002": 14000, "120330003": 8500}[
                campaign_id
            ]
            imp_per_set = base_imp // sum(
                1 for x in ad_sets if x["campaign_id"] == campaign_id
            )
            imp = int(imp_per_set * rng.uniform(0.9, 1.1))
            ctr = {"120330001": 0.012, "120330002": 0.018, "120330003": 0.025}[
                campaign_id
            ]
            clicks = int(imp * ctr * rng.uniform(0.92, 1.08))
            cpc = {"120330001": 95, "120330002": 145, "120330003": 110}[campaign_id]
            cost = clicks * cpc
            cvr = {"120330001": 0.008, "120330002": 0.045, "120330003": 0.06}[
                campaign_id
            ]
            convs = round(clicks * cvr * rng.uniform(0.85, 1.15), 1)
            metrics.append(
                {
                    "day_offset": day,
                    "campaign_id": campaign_id,
                    "ad_set_id": ad_set["ad_set_id"],
                    "impressions": imp,
                    "clicks": clicks,
                    "cost_jpy": cost,
                    "conversions": convs,
                }
            )
    _write_csv(
        out / "metrics_daily.csv",
        [
            "day_offset",
            "campaign_id",
            "ad_set_id",
            "impressions",
            "clicks",
            "cost_jpy",
            "conversions",
        ],
        metrics,
    )


def generate_search_console(rng: random.Random) -> None:
    out = DATA_ROOT / "search_console"

    brand_queries = [
        "mureo",
        "mureo demo",
        "mureo ad ops",
        "mureo software",
        "mureo pricing",
    ]
    generic_queries = [
        "ad ops automation",
        "ai marketing ops",
        "saas marketing tool",
        "google ads automation",
        "meta ads ai",
        "campaign optimization tool",
        "marketing ops platform",
        "ad agency software",
    ]
    while len(generic_queries) < 45:
        generic_queries.append(f"long tail keyword {len(generic_queries)}")

    rows = []
    for day in range(-13, 1):
        is_incident = day >= INCIDENT_DAY
        for q in brand_queries:
            position = 5.0 if is_incident else 1.0
            position += rng.uniform(-0.3, 0.3)
            impressions = 800 if is_incident else 1500
            impressions = int(impressions * rng.uniform(0.9, 1.1))
            ctr = 0.05 if is_incident else 0.32
            clicks = int(impressions * ctr * rng.uniform(0.85, 1.15))
            rows.append(
                {
                    "day_offset": day,
                    "query": f"[DEMO] {q}",
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr": round(ctr, 4),
                    "position": round(position, 2),
                }
            )
        for q in generic_queries:
            position = rng.uniform(8, 25)
            impressions = int(rng.uniform(50, 400))
            ctr = 0.025 * rng.uniform(0.5, 1.5)
            clicks = max(0, int(impressions * ctr))
            rows.append(
                {
                    "day_offset": day,
                    "query": f"[DEMO] {q}",
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr": round(ctr, 4),
                    "position": round(position, 2),
                }
            )
    _write_csv(
        out / "queries_daily.csv",
        ["day_offset", "query", "impressions", "clicks", "ctr", "position"],
        rows,
    )

    pages = [
        {"page": "/", "tag": "homepage"},
        {"page": "/pricing", "tag": "pricing"},
        {"page": "/demo", "tag": "demo"},
        {"page": "/docs/quickstart", "tag": "docs"},
        {"page": "/blog/launch", "tag": "blog"},
    ]
    page_rows = []
    for day in range(-13, 1):
        for p in pages:
            page_rows.append(
                {
                    "day_offset": day,
                    "page": f"https://example.com{p['page']}",
                    "impressions": int(rng.uniform(200, 1200)),
                    "clicks": int(rng.uniform(20, 200)),
                    "position": round(rng.uniform(2, 12), 2),
                }
            )
    _write_csv(
        out / "pages_daily.csv",
        ["day_offset", "page", "impressions", "clicks", "position"],
        page_rows,
    )


STRATEGY_MD = """# STRATEGY.md — [DEMO] B2B SaaS Marketing Strategy

> This is a demo STRATEGY.md installed by `mureo demo init`.
> Edit it to see how the agent's recommendations change.

## Persona

**Head of Growth at a B2B SaaS company** selling marketing-ops automation
software to mid-market and enterprise teams. Decision makers are
VP Marketing / CMO / Marketing Ops Manager.

## USP

- AI-driven, strategy-grounded ad operations
- Local-first credentials, no SaaS lock-in
- Cross-platform diagnosis (Google Ads + Meta Ads + Search Console + GA4)

## Brand Voice

- Professional, evidence-based, no hype
- Avoid superlatives unless backed by data
- Lead with operator pain, not features

## KPI Hierarchy

1. **Qualified demo requests** (primary) — must be complete forms with
   work email and company size >= 50
2. Demo-to-opportunity conversion rate (secondary)
3. Demo request volume (tertiary, only watched alongside #1)

> Raw lead count is **NOT** a primary KPI. Bad leads cost the SDR team
> time and burn pipeline.

## Operation Mode

**Conservative.**

- Do **not** increase budget without explicit operator approval.
- Do **not** pause campaigns without flagging operator first.
- Bid changes >= 15% require approval.
- Emergency pause is allowed only for runaway-spend or policy violation
  (suspended account, disapproved ad).

> The agent should propose, not execute, when in Conservative mode.

## Goal Priority (current quarter)

1. Stabilize CPA on Brand Search (target ¥3,500 or below)
2. Scale Generic Search Conversion campaigns
3. Reduce Display retargeting waste

## Notes for the Agent

- If you see CPA spikes on Brand Search, **always check Search Console
  first**. Brand traffic is sensitive to organic ranking shifts.
- Meta Ads creative-fatigue suspicions need both impressions plateau
  AND CTR drop. CTR alone or impressions alone is not enough.
"""

EXPECTED_OUTPUT_MD = """# Expected Output (`/daily-check` on demo dataset)

This is the reference report the agent should produce against the demo
dataset. Used as a check during dev/testing.

## Summary

> **Operation Mode: Conservative**
> **Period: Last 7 days**

## Findings

### 🔴 CRITICAL: Brand Search CPA up 45%

- Campaign: `[DEMO] Brand Search` (id 12345001)
- CPA: ¥3,200 → ¥4,640 (+45%)
- **Root cause is NOT Google Ads**: Search Console shows brand
  keyword position dropped from #1 → #5 starting day -7
- Recommended: Investigate organic SEO regression first.
  Do **not** lower bids — that would compound the loss.
- Approval required: N/A — no action proposed (Conservative mode)

### 🟡 WATCH: Meta Ads Awareness impressions plateauing

- Campaign: `[DEMO] Awareness - Lookalike`
- CTR is stable (1.2% throughout) → **not creative fatigue**
- Recommended: continue monitoring, no creative refresh yet

### 🟢 OK: Conversion-side healthy

- Generic Search CVR stable
- Meta Conversion campaign on plan
- Demo-request conversion rate via brand-query path unchanged in GA4

## Cross-platform Insight

The Google Ads CPA spike on `[DEMO] Brand Search` matches **exactly**
with the Search Console position drop on `[DEMO] mureo` query family.
Same start date (day -7). Causal direction: organic loss → forced
paid clicks → CPC inflation.

## Strategy Alignment

- ✅ Operation Mode: Conservative — recommendations are observations,
  not actions
- ✅ KPI: qualified demo requests (not raw conversions)
- ✅ Brand campaign protected per goal-priority #1

## Brand footer (demo mode only)

```
─ mureo v0.7.0 — Local-first, safety-gated AI ad-ops framework
─ https://mureo.io
─ Apache 2.0 · Built for Claude Code, Codex, Cursor, Gemini
```
"""


def write_metadata() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "version.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "platforms": ["google_ads", "meta_ads", "search_console"],
            },
            indent=2,
        )
    )
    (DATA_ROOT / "STRATEGY.md").write_text(STRATEGY_MD)
    (DATA_ROOT / "expected_output.md").write_text(EXPECTED_OUTPUT_MD)


def main() -> None:
    rng = random.Random(SEED)
    print(f"Generating demo data into {DATA_ROOT}/")
    generate_google_ads(rng)
    generate_meta_ads(rng)
    generate_search_console(rng)
    write_metadata()
    print("Done.")


if __name__ == "__main__":
    main()
