---
name: creative-refresh
description: "Refresh ad copy and creative assets based on performance signals and brand voice. Use when the user asks to refresh creative, propose new ad copy, A/B test creatives, update RSA assets, swap Performance Max asset-group headlines, descriptions, images or logos, rotate underperformers, or visually evaluate / compare banner (image) creatives. Also use when the user asks in Japanese (クリエイティブを刷新して / 広告文の改善案がほしい / RSAアセットの入れ替え / P-MAXの見出しを差し替えて / P-MAXの画像を差し替えて / バナーを比較評価して)."
metadata:
  version: 0.10.48
---

# Creative Refresh

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Refresh ad creatives based on strategy context and performance data across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: the `observation_due` you write in step 12, and every "is a previous creative change still inside its observation window?" check in step 10, are measured from it. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (Persona, USP, Brand Voice, Data Sources) and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts).

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) — drive it via its own tools and skip mureo-only value-adds; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **Audit current creatives**: For each ad platform:
   - **Google Ads**: prefer mureo native — call `google_ads_ad_performance_report` per campaign, plus `google_ads_rsa_assets_audit` (per-asset CTR/CVR ratings) and `google_ads_rsa_assets_analyze` (LOW/POOR detection). A **Performance Max** campaign has no `ad_group_ad`, so `google_ads_ads_list` and the RSA asset tools return nothing for it — an audit that stops there reports a P-MAX account as having no creative at all. Read its creative with `google_ads_asset_group_assets_list` (pass `campaign_id` when you have no `asset_group_id`); one call returns **both** the HEADLINE / LONG_HEADLINE / DESCRIPTION text (each entry with `text`) and the MARKETING_IMAGE / SQUARE_MARKETING_IMAGE / PORTRAIT_MARKETING_IMAGE / LOGO / LANDSCAPE_LOGO images (each entry with `asset_name`, a full-size serving `url`, `width_pixels`, `height_pixels`). `field_type` says which. Every entry carries the `asset_id` you will need to change it. Video and business-name assets are not returned. In BYOD mode, the Apps Script bundle does not include per-asset ratings — these tools return `[]`; fall back to `google_ads_ads_list` for headline/description text and use `ad_performance.report` for ad-level CTR/conv only. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for ad-level performance and ad listing, then **skip the mureo-only RSA asset audit tools** (`google_ads_rsa_assets_audit`, `google_ads_rsa_assets_analyze`) and note: "per-asset LOW/POOR detection and the RSA asset audit are mureo-specific value-add features — install or re-enable via `mureo setup claude-code` for the full creative audit."
   - **Meta Ads**: prefer mureo native — call `meta_ads_creatives_list`, `meta_ads_analysis_compare_ads`, and `meta_ads_analysis_suggest_creative`. In BYOD mode, creative URLs / headlines / body / CTA may be present in `~/.mureo/byod/meta_ads/creatives.csv` (best-effort, populated only when those columns were in the export). If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the creative list and ad-level insights only, then **skip the mureo-only analysis tools** (`meta_ads_analysis_compare_ads`, `meta_ads_analysis_suggest_creative`); perform the ad-comparison and creative-suggestion logic yourself using the rules in step 6 and note to the user that mureo's automated creative-suggestion engine requires the native MCP.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.
   - Identify underperforming assets (LOW/POOR ratings for search ads, low CTR/engagement for social ads).
   - **Image / banner creatives**: the text-and-metrics audit above does not look at the picture itself. When a creative carries an image you can actually reach — `image_url` / `thumbnail_url` from `meta_ads_creatives_list`, a P-MAX asset group's images from `google_ads_asset_group_assets_list` (which says *which* asset group serves each one), or a Google image asset from `google_ads_image_assets_list` (account-level: name, dimensions and a full-size serving `url`) — also run the **Visual creative evaluation** section below to score the banner's design, not just its copy and CTR.

4. **Analyze landing pages**: For each campaign's final URL, analyze the landing page to extract key selling points, CTAs, and features. If GA4 is available, pull engagement metrics (time on page, scroll depth, bounce rate) to inform creative direction.

5. **Organic keyword insights** (if Search Console is available): Incorporate top-performing organic search queries into ad copy. Terms that drive organic clicks likely resonate with users.

6. **Generate platform-appropriate creative recommendations**:
   **First run the *Apply or draft* check below** for every surface you are about to write copy for, and carry its verdict into the draft itself — a draft mureo cannot apply is labelled that way in the same message that presents it, not after the operator agrees.
   Using Persona pain points + USP + LP selling points + Brand Voice rules, draft:
   - **Search ads**: Headlines and descriptions aligned with character limits and ad format requirements
   - **Social ads**: Primary text, headline, description, CTA suggestions
   - Consider platform-specific best practices and format requirements

   Each creative must:
   - Address a specific Persona pain point OR highlight a USP
   - Match the Brand Voice guidelines
   - Include keywords from top-performing search terms (paid and organic)

7. **Validate**: Run each through the relevant platform's ad validation rules (character limits, prohibited expressions, no duplicates).

8. **Present recommendations** with rationale for each. Group by platform, and inside each group keep the *Apply or draft* verdict visible per item — "mureo will apply" and "paste this in yourself" are different offers and must not be presented as one list.

9. **Ask for approval** before creating/updating any ads — only for the items the *Apply or draft* check marked applicable. Never ask for approval to apply a draft-only item; hand that draft over as paste-in copy and move on.

10. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous creative change is still within its observation window, warn about stacking changes.

11. **Execute approved changes**: Use each platform's ad creation/update tools to apply changes. For Google Performance Max copy that is `google_ads_asset_group_assets_replace` — one call per asset, taking `asset_group_id` + `field_type` + `old_asset_id` (from `google_ads_asset_group_assets_list`) + `new_text` — not `google_ads_ads_update`, which cannot see a P-MAX campaign. For a P-MAX **image or logo** it is `google_ads_asset_group_images_replace`, same targeting arguments plus either `new_asset_id` (an image the account already holds) or `new_image_path` (a local file to upload) — exactly one, and you do not need to know which situation you are in to pick the tool. A draft-only item produces **no tool call at all**.

12. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CTR, CPA, conversions, impressions, clicks) and `observation_due` (14 days from `server_now`'s date). Log only what mureo actually wrote: a draft the operator was asked to paste in by hand is not a mureo change and gets no `action_log` entry (log it, and `/ad-fatigue-check` and the outcome evaluator will later measure a change that may never have been made).

13. **Update STATE.json** with notes.

## Apply or draft (decide before you draft, not after approval)

Some ad copy mureo can write for the operator; some it can only hand over as
text to paste into the platform's own UI. Both are useful outcomes. What is
never useful is finding out which one applies *after* the operator has said
yes — that spends a round trip on an offer that was never executable.

**The rule**: before you draft anything, name the mureo write tool that would
apply it for that exact surface (platform + campaign type + asset kind), and
scope the offer by **whether that tool is in this session's tool list** —
never by campaign type as a category.

- **A write tool exists** → offer to apply it, under the step 9 approval gate.
- **No write tool exists** → say so in the same message that carries the
  draft, before asking for anything: "mureo cannot apply this one — here is
  copy to paste into <platform> yourself." Never offer to apply it, never ask
  for approval to apply it, and never log it as a mureo change (step 12).

What Google Ads copy mureo can write **today**:

| Surface | Read | Write |
|---|---|---|
| Search RSA headlines / descriptions | `google_ads_ads_list`, `google_ads_rsa_assets_audit` | `google_ads_ads_create`, `google_ads_ads_update` |
| Performance Max asset-group text — HEADLINE / LONG_HEADLINE / DESCRIPTION | `google_ads_asset_group_assets_list` (the `text` of each entry) | `google_ads_asset_group_assets_replace` — one asset per call, by `asset_group_id` + `field_type` + `old_asset_id` |
| Performance Max asset-group images — MARKETING_IMAGE / SQUARE_MARKETING_IMAGE / PORTRAIT_MARKETING_IMAGE / LOGO / LANDSCAPE_LOGO | `google_ads_asset_group_assets_list` (the `url` + dimensions of each entry) | `google_ads_asset_group_images_replace` — one image per call, by `asset_group_id` + `field_type` + `old_asset_id` + either `new_asset_id` or `new_image_path` |
| Responsive Display Ad text | `google_ads_ads_list` | create only (`google_ads_ads_create_display`); no text update — **draft-only** for an edit |
| A Responsive Display Ad's images | `google_ads_ads_list` returns asset resource names; join by id to `google_ads_image_assets_list` for a URL | none — **draft-only** |
| Video, business name, and every other non-text non-image field type of a P-MAX asset group | not returned by `google_ads_asset_group_assets_list` | none — **draft-only** |
| Any image outside the surfaces above | `google_ads_image_assets_list` lists account-level images with a serving URL, but does not report which ad uses one | none — **draft-only** |

That table is a **snapshot of the tool layer, not** the boundary. The boundary
is the tool list you can actually see in this session, and it moves in both
directions: mureo gains tools, so a surface that was draft-only last release
may have a write tool now — offer it even though the table does not name it.
And a tool the table names can be **absent** here (BYOD, a plugin-only or
hosted-connector-only session, `MUREO_DISABLE_GOOGLE_ADS=1`); when it is,
that surface is draft-only for this run. Check, do not assume in either
direction.

The same rule governs the platforms this table does not cover: if you cannot
name the write tool, the answer is a draft, said up front.

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
   `meta_ads_creatives_list`; for a **Performance Max** asset group, the
   `url` of each image entry from `google_ads_asset_group_assets_list` — that
   is the one Google read that says *which* asset group serves an image, so
   "the images of this asset group" is directly enumerable (pass
   `campaign_id` when you have no `asset_group_id`); for any other Google
   image, the full-size serving `url` from `google_ads_image_assets_list`. In
   BYOD mode use the URL column from `creatives.csv` when present.
   **What Google will not give you**: `google_ads_image_assets_list` is
   account-wide — outside a P-MAX asset group it does not say which ad serves
   an asset. A Responsive Display Ad is the one other case with a link:
   `google_ads_ads_list` returns its `marketing_images` /
   `square_marketing_images` / `logo_images` as asset **resource names**,
   which you match by id against `google_ads_image_assets_list` to get a URL.
   And no Google read returns video assets at all.
   For any image you cannot reach, score the copy and metrics, say plainly
   that the picture could not be retrieved, and ask the operator to paste it
   into chat if they want it graded — never a guessed visual score, and never
   an offer to change an asset mureo has no write tool for (see *Apply or
   draft*).
2. **On Claude Code (has Read/Bash):** download the image to the scratch
   directory (`curl -sL "<image_url>" -o <scratch>/creative_<id>.jpg`) and
   `Read` that file — the Read tool renders the pixels so you can actually see
   the banner. Only fetch URLs on the ad platform's own CDN
   (`*.fbcdn.net` / `*.cdninstagram.com` / `googleusercontent.com` /
   `gstatic.com` / `googlesyndication.com` — the last is where a P-MAX asset
   group's image `url` points); refuse arbitrary hosts (SSRF hygiene). Delete
   the temp files when done.
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
