---
name: creative-refresh
description: "Refresh ad copy and creative assets based on performance signals and brand voice. Use when the user asks to refresh creative, propose new ad copy, A/B test creatives, update RSA assets, rotate underperformers, or visually evaluate / compare banner (image) creatives."
metadata:
  version: 0.10.23
---

# Creative Refresh

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Refresh ad creatives based on strategy context and performance data across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


1. **Load context**: Read STRATEGY.md (Persona, USP, Brand Voice, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) — drive it via its own tools and skip mureo-only value-adds; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **Audit current creatives**: For each ad platform:
   - **Google Ads**: prefer mureo native — call `google_ads_ad_performance_report` per campaign, plus `google_ads_rsa_assets_audit` (per-asset CTR/CVR ratings) and `google_ads_rsa_assets_analyze` (LOW/POOR detection). In BYOD mode, the Apps Script bundle does not include per-asset ratings — these tools return `[]`; fall back to `google_ads_ads_list` for headline/description text and use `ad_performance.report` for ad-level CTR/conv only. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for ad-level performance and ad listing, then **skip the mureo-only RSA asset audit tools** (`google_ads_rsa_assets_audit`, `google_ads_rsa_assets_analyze`) and note: "per-asset LOW/POOR detection and the RSA asset audit are mureo-specific value-add features — install or re-enable via `mureo setup claude-code` for the full creative audit."
   - **Meta Ads**: prefer mureo native — call `meta_ads_creatives_list`, `meta_ads_analysis_compare_ads`, and `meta_ads_analysis_suggest_creative`. In BYOD mode, creative URLs / headlines / body / CTA may be present in `~/.mureo/byod/meta_ads/creatives.csv` (best-effort, populated only when those columns were in the export). If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the creative list and ad-level insights only, then **skip the mureo-only analysis tools** (`meta_ads_analysis_compare_ads`, `meta_ads_analysis_suggest_creative`); perform the ad-comparison and creative-suggestion logic yourself using the rules in step 6 and note to the user that mureo's automated creative-suggestion engine requires the native MCP.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.
   - Identify underperforming assets (LOW/POOR ratings for search ads, low CTR/engagement for social ads).
   - **Image / banner creatives**: the text-and-metrics audit above does not look at the picture itself. When a creative carries an image (`image_url` / `thumbnail_url` from `meta_ads_creatives_list`, or a Google image/Display/PMax asset), also run the **Visual creative evaluation** section below to score the banner's design, not just its copy and CTR.

4. **Analyze landing pages**: For each campaign's final URL, analyze the landing page to extract key selling points, CTAs, and features. If GA4 is available, pull engagement metrics (time on page, scroll depth, bounce rate) to inform creative direction.

5. **Organic keyword insights** (if Search Console is available): Incorporate top-performing organic search queries into ad copy. Terms that drive organic clicks likely resonate with users.

6. **Generate platform-appropriate creative recommendations**:
   Using Persona pain points + USP + LP selling points + Brand Voice rules, draft:
   - **Search ads**: Headlines and descriptions aligned with character limits and ad format requirements
   - **Social ads**: Primary text, headline, description, CTA suggestions
   - Consider platform-specific best practices and format requirements

   Each creative must:
   - Address a specific Persona pain point OR highlight a USP
   - Match the Brand Voice guidelines
   - Include keywords from top-performing search terms (paid and organic)

7. **Validate**: Run each through the relevant platform's ad validation rules (character limits, prohibited expressions, no duplicates).

8. **Present recommendations** with rationale for each. Group by platform.

9. **Ask for approval** before creating/updating any ads.

10. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous creative change is still within its observation window, warn about stacking changes.

11. **Execute approved changes**: Use each platform's ad creation/update tools to apply changes.

12. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CTR, CPA, conversions, impressions, clicks) and `observation_due` (14 days from today).

13. **Update STATE.json** with notes.

## Visual creative evaluation (image / banner ads)

Scores the **picture itself** — composition, legibility, brand fit — which the
copy-and-metrics audit in step 3 does not cover. Use it to grade a single
banner or to rank several competing ones before recommending a refresh.

> **Generating new creatives?** This section *scores existing* banners. To
> *create* fresh ad creatives (text-free key visuals + composed banners) from a
> brief, use the **creative-generate** skill — it drives the image providers and
> the HTML/CSS composer, and reuses this exact 7-dimension rubric in its
> art-direction loop.

**Applies only to creatives that have an image.** A text-only search ad
(Google RSA / ETA, or any ad with no `image_url` / `thumbnail_url`) has nothing
to view — skip this entire section for it and evaluate it with the copy +
RSA-asset ratings + performance audit from step 3 alone. Do not emit a visual
score, an empty rubric, or an "image not found" finding for a text ad.

### Getting the image in front of you (surface-dependent)

1. Collect each creative's image reference: `image_url` (or `thumbnail_url` for
   video — you evaluate the still frame only, not motion) from
   `meta_ads_creatives_list`; for Google, the image/Display/PMax asset URL. In
   BYOD mode use the URL column from `creatives.csv` when present.
2. **On Claude Code (has Read/Bash):** download the image to the scratch
   directory (`curl -sL "<image_url>" -o <scratch>/creative_<id>.jpg`) and
   `Read` that file — the Read tool renders the pixels so you can actually see
   the banner. Only fetch URLs on the ad platform's own CDN
   (`*.fbcdn.net` / `*.cdninstagram.com` / `googleusercontent.com` /
   `gstatic.com` etc.); refuse arbitrary hosts (SSRF hygiene). Delete the temp
   files when done.
3. **On Desktop / Cowork (MCP-only, no Read/Bash):** you generally cannot fetch
   and view an arbitrary URL yourself. Present the `image_url` to the operator
   and ask them to paste/drop the image into chat so you can see it; if they
   can't, do the copy/metrics audit only and tell them the pixel-level score
   needs the Code surface (or the future ImageContent tool). **Never invent a
   visual score for an image you have not actually seen.**

### Scoring rubric

Once you can see the banner, score each dimension **1–5** (5 = excellent):

| Dimension | What to judge |
|---|---|
| Legibility | Is overlaid text readable at feed/thumbnail size? Contrast, font size, not cramped. |
| Composition & hierarchy | Clear focal point, uncluttered, the eye lands on the offer/CTA. |
| Brand fit | Matches STRATEGY.md Brand Voice — palette, tone, logo usage, style. |
| Message clarity | Is the value prop / offer graspable in under ~2 seconds? |
| CTA visibility | Is there a visible, prominent call to action? |
| Copy/LP consistency | Does the image match the ad copy and the landing-page promise? |
| Policy / text density | Excessive text overlay (heavy-text creatives underdeliver on Meta), or any prohibited/misleading visual. |

- **Overall** = the simple average, but any dimension scoring **≤ 2 is a
  must-fix** and caps the verdict at "Needs work" regardless of the average.
- Output a per-creative table of the 7 scores + overall + the **top 3 concrete
  fixes** (specific and actionable, e.g. "increase headline contrast; the white
  text on a light-sky background fails legibility at feed size").

### Comparison mode (2+ banners)

Score each banner with the same rubric, then produce a **ranking** with a
one-line justification per rank. Name the winner, and for the runners-up call
out the single strongest element worth borrowing into the winner. Tie the
recommendation back to Persona / USP / performance data from step 3 — a
visually strong banner that already has low CTR still loses.

Fold the visual verdict into the step 6 recommendations and the step 8
presentation (a low visual score is itself a reason to refresh).

IMPORTANT: Every headline/description must have a clear rationale tied to Persona, USP, or LP content. Never generate generic ad copy. Consult past action_log — if previous creative refreshes have evaluated outcomes, reference what worked.
