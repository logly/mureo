---
name: tracking-health
description: "Preventive audit of conversion tracking across all configured ad platforms — Meta pixels + CAPI, Google Ads conversion actions — with a GA4 cross-check. Use when the user asks to check tracking, audit conversion measurement, verify pixels / tags, diagnose why conversions stopped or look wrong, sanity-check CV counting, or requests a 計測ヘルスチェック / タグ・計測監査 / 計測が壊れていないか確認. Reads STRATEGY.md and STATE.json, produces a per-platform tracking scorecard (OK / Watch / Broken per check) and a fix list ranked by revenue risk."
metadata:
  version: 0.10.26
---

# Tracking Health

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Preventively audit conversion tracking across every configured platform. Measurement breakage is the costliest **silent** failure in ad ops — spend keeps flowing while the signal the algorithm optimizes toward is wrong or absent — so this skill hunts for it *before* it shows up as a mysterious CPA spike.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run the `onboard` skill first if not)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Load context**: Read STRATEGY.md (especially each Goal's declared conversion definition, Persona, and Operation Mode) and STATE.json. Note **what the operator considers a real conversion** for each platform (a lead form submit, a purchase, a phone call) — the audit below is only meaningful relative to that intent.

2. **Discover available platforms**: Identify all configured platforms from STATE.json `platforms` and which data sources (GA4, Search Console) are accessible. Also enumerate installed **plugin** platforms (`mcp__mureo__<plugin>_*` tools) and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, STATE.json key `tiktok_ads`); include them best-effort — see `../_mureo-shared/SKILL.md` → *Plugin platforms* and *Hosted-connector platforms*.

3. **Meta Ads — pixel inventory + health** (prefer mureo native):
   - **Inventory**: call `meta_ads_pixels_list` to enumerate every pixel in the account (id, name, `last_fired_time`). Zero pixels on an account running conversion campaigns is a **Broken** finding on its own.
   - **Per-pixel health**: for each pixel call `meta_ads_pixels_get` and check `last_fired_time` is recent (a pixel that stopped firing = **Broken**). Call `meta_ads_pixels_stats` (window `last_30d`, widen to `last_90d` to catch slow degradations) and look for a sudden drop or a flatline in PageView / Lead / Purchase volume — a step-down that lines up with a site deploy is the classic pixel break.
   - **Event coverage**: call `meta_ads_pixels_events` to list the distinct standard + custom events the pixel actually receives, with sample parameters. Flag when the event the operator's Goal depends on (e.g. `Lead`, `Purchase`) is **absent** or firing with missing parameters (no `value` / `currency` on a Purchase).
   - **Per-campaign `result_indicator` audit**: call `meta_ads_insights_report` (level `campaign`) and inspect each campaign's `result_indicator`. Flag any campaign optimized for `actions:link_click` where the operator expects real leads / purchases (`actions:offsite_conversion.fb_pixel_lead`) — that campaign is buying clicks, not conversions, and its "results" number is not comparable to a lead-optimized campaign's. This CV-definition-mismatch detection is a mureo value-add; see daily-check step 4.
   - **CAPI presence check**: mureo ships **no dedicated tool** that reports a browser-vs-server event split, so treat this as best-effort. Use `meta_ads_pixels_events` to see whether server-originated (Conversions API) events appear alongside browser events, and note in the scorecard when a high-value account is relying on the browser pixel alone (no CAPI) — a resilience risk as browser signal degrades. mureo *can send* server events (`meta_ads_conversions_send` / `meta_ads_conversions_send_lead` / `meta_ads_conversions_send_purchase`), but a definitive server/browser coverage split still requires Events Manager; say so rather than guessing.
   - If mureo's Meta Ads tools are unavailable (i.e. `MUREO_DISABLE_META_ADS=1` after `mureo providers add meta-ads-official`), fall back to the official `meta-ads-official` hosted MCP for whatever pixel / insights surface it exposes, and note that the `result_indicator` CV-mismatch analysis is a mureo-specific value-add absent from the official MCP.

4. **Google Ads — conversion actions + status** (prefer mureo native):
   - **Inventory + status**: call `google_ads_conversions_list` to list every conversion action with its `status` (`ENABLED` / `HIDDEN` / `REMOVED`) and `category` (`PURCHASE`, `SIGNUP`, …). For any action whose configuration you need to inspect further, call `google_ads_conversions_get`. A campaign optimizing toward a `REMOVED` / `HIDDEN` action, or an account with **no** ENABLED conversion action, is a **Broken** finding.
   - **Recent-data check**: call `google_ads_conversions_performance` (period `LAST_30_DAYS`) — only rows with conversions > 0 are returned, so an ENABLED action that is **absent** from the report has recorded **no recent conversions**. Cross-reference its `first_date` / `last_date`: an action that used to fire and went silent is a likely tag break; a brand-new action with no data yet is expected. Flag silent actions as **Watch** (or **Broken** if it is the primary action a live campaign depends on).
   - **Primary / secondary counting sanity**: Google Ads counts only *primary* actions into the "Conversions" column that bidding optimizes toward; *secondary* actions are observational. mureo's read tools do not expose the primary/secondary flag directly, so verify it in the Google Ads UI and flag the common misconfigurations: (a) a micro-conversion (e.g. `PageView`) set as primary — inflates Conversions and misleads Smart Bidding; (b) the true macro-conversion set as secondary — starves bidding of the signal. Also flag **double-counting** risk when two actions plausibly fire on the same event.
   - If mureo's Google Ads tools are unavailable (`MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for the conversion-action listing / performance surface it exposes, and note that the recency and counting-sanity heuristics still apply.

5. **Cross-check with GA4** (when available): mureo ships **no native GA4 tools** — GA4 is reached as a configured data source, so pull the site's conversion count from that source (do not reference a `ga4_*` tool that does not exist). Compare each platform's *ads-reported* conversions against GA4's conversions for the same event and window. A divergence **> 20 %** is a **flag** — report the likely causes so the operator can triage:
   - **Attribution window / model** differences (platform click-through + view-through vs GA4 last-click).
   - **Consent Mode / cookie loss** suppressing GA4 (or platform) tags for a slice of users.
   - **Tag coverage gaps** — the pixel/tag missing on some conversion pages, or duplicated on others.
   - **Cross-device / logged-in attribution** the platform can resolve but GA4 cannot.
   Present the discrepancy as a *signal to investigate*, not proof one number is wrong — the platforms genuinely count differently.

6. **Search Console**: N/A for conversion tracking — Search Console has no conversion signal. Skip it here (organic conversion behavior belongs in daily-check / weekly-report).

7. **Plugin & hosted-connector platforms** (best-effort): for a plugin platform (`plugin:<dist>`) or a hosted connector (`tiktok_ads`), report only the basic tracking status its own tools expose and emit `analytics_not_available_for_<platform>` for the mureo-only deep checks (pixel health, `result_indicator`, conversion-action recency) — do **not** fabricate a tracking verdict from an integration's tool schemas. See `../_mureo-shared/SKILL.md` → *analytics-module parity* and *Hosted-connector platforms*.

8. **Scorecard**: present a per-platform **tracking scorecard**, one row per check, each rated **OK** / **Watch** / **Broken**:
   ```
   Platform    Check                              Status   Evidence
   Meta Ads    Pixel firing (last_fired_time)     OK       fired 2h ago
   Meta Ads    Lead event present                 Broken   no Lead events in 30d
   Meta Ads    result_indicator vs Goal           Watch    2 campaigns on link_click
   Meta Ads    CAPI present                        Watch    browser pixel only
   Google Ads  Primary conversion action ENABLED  OK       "Purchase" ENABLED
   Google Ads  Recent conversion data             Broken   0 conv in 30d for "Lead"
   Google Ads  Primary/secondary counting         Watch    verify PageView not primary
   Google Ads  Ads CV vs GA4 CV (±20%)            Watch    Ads 120 / GA4 78 (+54%)
   ```

9. **Fix list — ranked by revenue risk**: turn every **Broken** / **Watch** into a concrete fix, ordered by how much spend is riding on the broken signal (a broken primary action on the highest-spend campaign is #1; a missing secondary action on a paused campaign is last). For each fix state: what is wrong, the concrete remediation, and the platform/UI or tool that performs it.

10. **Approval gate for any state-mutating fix**: most remediations here are **operator actions** (re-add a tag on the site, flip an action to primary in the Google Ads UI, install CAPI). Where a fix *does* mutate platform state through a mureo tool (e.g. `google_ads_conversions_update` to re-enable an action, `google_ads_conversions_create` to add one, sending backfill events via `meta_ads_conversions_send`), apply the *Confirm Before Write Operations* rule from `../_mureo-shared/SKILL.md` — show the current value and the proposed change and get explicit **approval** before the call. For an official/hosted-MCP or plugin write, also self-apply the STRATEGY.md `## Guardrails` rules yourself (mureo's PolicyGate cannot see that call) — see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

11. **Record any change to `action_log`**: for each approved state-mutating fix, log to `action_log` (via `mureo_state_action_log_append`) with `metrics_at_action` (the pre-fix conversion counts / firing state you could read) and an `observation_due` **7 days** out, so daily-check's evidence step confirms the fix actually restored the signal. A pure audit with no changes still logs a summary entry (findings + scorecard verdict), with no `observation_due`.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="tracking"` and a concise `summary` object so the read-only dashboard can render this audit without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the window audited (e.g. `"LAST_30_DAYS"`)
    - `kpis`: per-platform tracking health counts (e.g. `{"meta_ads": {"pixels_ok": 1, "broken": 1}}`) and any ads-vs-GA4 divergence
    - `flags`: notable items (e.g. `["meta_lead_event_missing", "google_primary_action_zero_conv"]`)
    - `narrative`: the 1-2 sentence overall verdict (OK / Watch / Broken)

    **Reflect the FINAL state, and persist this LAST** — after every `action_log` entry and any fix you applied this run. This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
