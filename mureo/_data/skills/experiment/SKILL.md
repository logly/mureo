---
name: experiment
description: "Design, run, and evaluate a controlled A/B test (split test) on your ad accounts with evidence discipline — one variable, a falsifiable hypothesis, a fixed window, and a per-variant outcome verdict. Use when the user asks to run an A/B test, split test, or experiment, to 'test whether X beats Y', to validate a creative-refresh or learning hunch properly, or requests A/Bテスト / スプリットテスト設計 / 実験を回したい / どちらが勝ったか評価して / 仮説を検証したい. Forces a designed experiment instead of an ad-hoc change, records the baseline in action_log, and forbids peeking-based decisions before the window closes."
metadata:
  version: 0.10.22
---

# Experiment

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Turn an ad-hoc change into a **designed experiment**. Most "we tried X and CPA moved" claims are noise — one variable was never isolated, the window was never fixed, and the decision was made by peeking. This skill enforces the discipline: a falsifiable hypothesis, exactly **one** variable, a success metric tied to a Goal, a pre-committed duration and sample floor, no peeking, and a per-variant verdict where **inconclusive is a valid outcome**.

Read `../_mureo-learning/SKILL.md` first — its **Observation Windows** and **Minimum Sample Sizes** tables set the duration and sample floor this skill commits to, and its evidence lifecycle is the rulebook for the no-peeking rule below.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Hypothesis intake — force a falsifiable statement**. Take the hypothesis from the operator, from a `/creative-refresh` finding, or from a VALIDATED learning insight, and rewrite it into a single testable sentence with three explicit parts: **variable** (the ONE thing that differs), **expected effect** (direction + rough magnitude), and **success metric** (the number that decides it). Reject vague inputs ("make it better") — push back until it is falsifiable, e.g. *"Video creative (variable) will lower CPA by ≥15% (effect) vs the current static image, measured on cost_per_conversion (metric)."* If two things would differ, split into two experiments or drop one.

2. **Design — one variable, tied to a Goal**. Confirm **exactly one variable** changes between variants (creative, headline, audience, placement, bid — not several at once; confounded designs are unattributable). Set the **variant count** (2 is the default; more variants need proportionally more sample and duration). Bind the **success metric** to a specific STRATEGY.md Goal so the winner means something (a CTR win that doesn't move the Goal's CPA/CV is not a win). Derive the **minimum duration and sample floor** from `../_mureo-learning/SKILL.md`: creative/targeting changes need a 14-day window; the metric's sample floor (CPA: ≥30 conversions/variant; CTR: ≥1,000 impressions/variant; CVR: ≥200 clicks/variant) must be *reachable within the window at current traffic* — if it is not, say so and either extend the window or advise against running (an underpowered test wastes spend).

3. **Discover platforms**. Identify configured platforms from STATE.json `platforms`. Include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) and `mcp__mureo__<plugin>_*` plugin platforms — but note honestly that a true randomized split-test tool only exists for **Meta** below; on other platforms the experiment is a manual/approximate construction (see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms* and *Plugin platforms*). mureo BYOD data lives in the workspace `byod/` directory and is reachable only through mureo MCP tools — do not look for raw CSVs in the project directory.

4. **Setup — Meta (native split test)**. Meta has a real experiment engine. The variants are **ad sets** — the split-test tool references pre-existing ad sets and does **not** create them, so first make sure each variant exists as its own ad set (identical except for the one variable) via `meta_ads_ad_sets_list` / `meta_ads_ad_sets_create`. Then, after the approval gate (step 6), create the test with `meta_ads_split_tests_create`:
   - `cells`: one `{name, adsets:[ad_set_id]}` per variant; Meta splits traffic evenly.
   - `objectives`: `[{type: COST_PER_RESULT | CONVERSIONS | REACH | CPC | CPM}]` — pick the type matching the Goal metric from step 2.
   - `start_time` (must be in the future) and `end_time` — honor the designed window; Meta requires **≥4 days** between them.
   - `confidence_level` (80–99, default 95). Do not lower it just to force a faster verdict.
   Inspect a running test with `meta_ads_split_tests_list` / `meta_ads_split_tests_get`. If mureo's Meta tools are unavailable (`MUREO_DISABLE_META_ADS=1` after `mureo providers add meta-ads-official`), fall back to the official `meta-ads-official` hosted MCP for whatever experiment surface it exposes, and self-apply the guardrail/confirm rules yourself (mureo's PolicyGate cannot see that call).

5. **Setup — Google Ads (no split-test tool — honest manual paths)**. mureo ships **no Google Ads campaign-experiment / drafts-and-experiments tool** — there is no `google_ads_experiment*` in the tool surface, so do **not** invent one. Offer the operator the two honest alternatives and require **explicit acknowledgment of their caveats** before proceeding:
   - **(a) RSA asset A/B (in-ad, lowest-risk).** Add the challenger headline/description alongside the control in the same Responsive Search Ad and let Google's asset rotation gather per-asset data; read the split with `google_ads_rsa_assets_analyze` (per-asset `performance_label` + CTR) and `google_ads_rsa_assets_audit`. **Caveat**: this is asset-level rotation, **not** a randomized user split — Google serves assets non-uniformly (it favors likely winners), so it is directional, not a clean controlled test.
   - **(b) Duplicated-campaign split (campaign-level).** Duplicate the campaign (`google_ads_campaigns_create` + `google_ads_ads_create`), change only the one variable, split budget, and compare with `google_ads_ad_performance_report` / `google_ads_ad_performance_compare`. **Caveats**: the two campaigns compete in the same auction (they can cannibalize each other), Smart Bidding re-enters its learning phase on each, and there is no traffic-randomization guarantee — confounds are larger than a Meta split test. State these plainly and get the operator to accept them.
   If neither caveat is acceptable, recommend **not** running the Google Ads experiment rather than shipping a test the operator will over-trust.

6. **Approval gate before ANY write**. Setup steps 4–5 create/mutate platform state. Apply the *Confirm Before Write Operations* rule from `../_mureo-shared/SKILL.md`: show the full design (variants, variable, split, budget, window, success metric, sample floor) and get explicit **approval** before creating any ad set, split test, or duplicated campaign. Respect Operation Mode and `## Guardrails` (budget caps, `blocked_operations`); refuse a design that breaches them.

7. **Record the design in `action_log`**. After the test is created, append one `mureo_state_action_log_append` entry per variant (or one entry capturing all variants) with `metrics_at_action` = the **baseline per variant** (the control's current cost_per_conversion / conversions / ctr / impressions, and the challenger's starting zero/baseline), `command="/experiment"`, a `summary` naming the hypothesis, and `observation_due` = the **designed end date** (not a default 7/14). This is the commitment device that makes step 8's no-peeking rule enforceable and lets daily-check pick the evaluation up automatically.

8. **Interim rule — NO peeking-based decisions before the window closes**. While the test runs, you may *report* interim numbers if asked, but you must **refuse to call a winner or stop a variant early** on them. State why: repeatedly checking and acting on a running test inflates the false-positive rate (the sequential-testing / "peeking" problem) — a lead that looks significant mid-flight reverses far more often than the confidence level implies. If a variant is causing genuine harm (runaway spend, a policy issue), that is an *incident* to escalate, not an experiment result — handle it via `/rescue`, and mark the experiment confounded.

9. **Evaluation — only when the window has closed**. Once `observation_due` has passed:
   - **Check sample-size adequacy FIRST.** Pull per-variant results (`meta_ads_split_tests_get` for Meta; `google_ads_ad_performance_report` / `google_ads_rsa_assets_analyze` for the Google Ads paths). If any variant is below its sample floor from step 2, the result is **inconclusive-underpowered** — do not read the metric delta as signal. Say so and stop here (optionally extend the window if traffic allows).
   - **Per-variant verdict.** For each challenger, call `mureo_outcome_evaluate` with `before` = the variant baseline from step 7 and `after` = its final numbers — the deterministic verdict avoids eyeballing. Cross-read Meta's own `winner_cell_id` / `confidence_interval` from `meta_ads_split_tests_get` where present.
   - **Declare one of three outcomes**, honestly: **winner** (challenger beats control on the success metric, above noise, sample-adequate), **no-difference** (within the noise band — a real and useful result: it means the variable doesn't matter here, stop spending attention on it), or **inconclusive** (underpowered or confounded). Inconclusive is a valid outcome — never manufacture a winner to close the ticket.

10. **Close out**. Apply the outcome (**approval gate**): promote the winner (shift budget to it / adopt the winning creative or copy), and **stop the losing variant** (`meta_ads_split_tests_end` if ending a Meta study early is warranted, or pause the losing ad set / ad). Show current-vs-proposed and confirm before each mutation.

11. **Offer to save the finding via `/learn`**. A closed experiment — winner, no-difference, or inconclusive-because-underpowered — is exactly the reusable know-how the knowledge base is for. Propose the generalized lesson (e.g. *"Video beat static image by 22% CPA for this Persona — prefer video-first creative briefs"*) and, on approval, save it through the **`/learn`** flow (`mureo learn add`, per that skill's conventions — do not duplicate its steps here). Never record account IDs or personal data.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="experiment"` and a concise `summary` object so the read-only dashboard can render the experiment without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the experiment window (start_time..end_time) and its status (running / evaluated)
    - `kpis`: per-variant `{metric_at_baseline, metric_final, verdict}` and the success metric name
    - `flags`: notable items (e.g. `["underpowered_variant_B", "google_ads_manual_split_caveats_accepted"]`)
    - `narrative`: the 1-2 sentence outcome (winner / no-difference / inconclusive, with confidence)

    **Reflect the FINAL state, and persist this LAST** — after every `action_log` entry and any winner-promotion / loser-stop you applied this run. This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
