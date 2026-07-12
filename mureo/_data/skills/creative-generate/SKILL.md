---
name: creative-generate
description: "Generate creator-quality ad creatives — text-free key visuals plus composed banners — from a strategy-grounded brief. Use when the user asks to create ad creatives, generate ad images or banners, make banner variations, design display / social ad creatives, or asks in Japanese (クリエイティブ作成 / バナー作成 / 広告画像を生成 / バナーのバリエーションを作って). Runs a 6-step workflow (brief → copy → visuals → art-direction scoring loop → HTML/CSS composition → delivery) via the creative_studio_* MCP tools, then hands approved banners to the existing upload tools."
metadata:
  version: 0.10.20
---

# Creative Generate

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Produce professional, on-brand ad creatives — a text-free **key visual** plus
**composed banners** in the operator's target formats — from a strategy-grounded
brief. Quality comes from separating three layers and giving each to the right
tool: image models make the **picture** (they are terrible at text, especially
Japanese), an HTML/CSS + headless-Chromium composer lays down **pixel-perfect
typography**, and you are the **art director** who scores every candidate before
anything ships. See `docs/creative-studio.md` for the architecture and provider
setup.

## Prerequisites

- STRATEGY.md must exist (run the `onboard` skill first). Persona / USP / Brand
  Voice are the grounding for both copy and visuals.
- At least one image provider key configured — `creative_studio` credentials
  section, or the `OPENAI_API_KEY` / `GEMINI_API_KEY` / `FAL_KEY` env vars.
  Call `creative_studio_providers_list` to see what is available.
- **Composition** (step 5) requires the optional extra:
  `pip install 'mureo[creative]'` then `playwright install chromium`. Without it
  `creative_studio_compose` returns a clear pip-hint error — you can still run
  steps 1-4 (brief, copy, visuals, scoring) and hand off the raw key visual.

**Before you start**: Call `mureo_learning_insights_get` (no arguments) and treat
the returned Markdown as authoritative practitioner know-how — the operator saved
those via `/learn` precisely because they should inform your creative direction.
When the response is the "no insights saved yet" guidance, proceed without it.

## The 6-step workflow

### 1. Brief

- **Read STRATEGY.md** for Persona (pain points, desires), USP, and **Brand
  Voice** (tone, palette cues, do/don't). On Code use `Read`; on Desktop / Cowork
  use `mureo_strategy_get`. This is the strategy *file* — there is no separate
  "brief" tool.
- When the operator gives a **landing-page URL**, ground the brief in it:
  `google_ads_landing_page_analyze` (selling points, price, CTA, industry) and
  optionally `google_ads_creative_research` for angle inspiration. Skip these
  when no URL is available — do not invent an LP.
- **Confirm with the operator BEFORE generating**: genre / product, the offer,
  the desired tone, and the **target formats** (which of the format matrix — feed
  1:1, 4:5, story 9:16, the GDN sizes, RDA — they actually need). One
  confirmation round, then proceed; do not loop endlessly asking questions.

### 2. Copy

- **You write the copy** — 2-3 sets of {headline, body, CTA} grounded in the
  brief and Brand Voice. Each set must address a specific Persona pain point OR a
  USP; never generic filler. Respect the copy character-budget of the target
  formats (a leaderboard headline must be short).
- **Japanese (or any) copy goes to the COMPOSE step only (step 5).** NEVER put
  copy text into the image-generation prompt — image models mangle text and
  Japanese becomes garbled tofu. The visual layer is text-free by construction.

### 3. Visuals

- Call `creative_studio_providers_list` **first** and pick a configured provider
  (or pass `provider="all"` to fan out one candidate per provider when several
  keys are set).
- Call `creative_studio_generate_visual` with a **visual-only** prompt: describe
  scene / subject / style / mood, plus **explicit negative-space guidance that
  matches the copy zone of the template you intend to compose with**:
  - `hero_overlay` → keep the **lower third** clean and uncluttered for the
    headline/CTA band.
  - `split` → keep **one half** (left or right) clear as a solid-ish panel for
    copy; put the subject on the other half.
  - `minimal_badge` → a **center-weighted subject with even surrounding texture**
    so a small badge chip and centered copy read cleanly.
- Use `n >= 4` candidates (`aspect` picks the master generation size — `square` /
  `portrait` / `landscape` / `vertical`). The tool appends the hard no-text
  constraint for you and writes every PNG to a run directory with a provenance
  `manifest.json`.

### 4. Art-direction loop

This is where creator-quality is won. **Score the pixels, not the prompt.**

- **Read every candidate PNG** (the `Read` tool renders the image so you actually
  see it) and score it with the **7-dimension rubric from the creative-refresh
  skill** — Legibility, Composition & hierarchy, Brand fit, Message clarity, CTA
  visibility, Copy/LP consistency, Policy / text density — each 1-5. See
  `../creative-refresh/SKILL.md` → *Visual creative evaluation* → *Scoring rubric*
  for what each dimension judges. (At the visual-only stage judge the copy-related
  dimensions against the **negative space you left** and the copy you drafted in
  step 2 — you re-verify them for real after composition in step 5.)
- **IRON RULE: NEVER score an image you have not actually seen.** No invented
  scores, no scoring from the prompt, no "assuming it looks like…".
- Keep the **top 1-2** visuals. Improve each weak one with
  `creative_studio_edit_visual` using a **concrete, single-change instruction**
  (e.g. "brighten the sky and remove the clutter on the left third" — one lever
  at a time, imagery only, no text). Re-Read and re-score after each edit.
- **Pass bar**: no single dimension `<= 3` **and** total `>= 28/35`. Allow at most
  **3 edit rounds per visual**; if it still misses the bar, pick the best
  available candidate and note the compromise (which dimension fell short and
  why) rather than looping forever. Record scores in your delivery table so the
  run manifest + gallery show the art-direction actually happened.

### 5. Compose

- Call `creative_studio_compose` with the chosen visual (`visual_path`), the
  winning copy set (`headline`, `cta`, optional `body` / `badge`), the chosen
  `template` (`hero_overlay` / `split` / `minimal_badge`), and the operator's
  target `formats`. The brand kit is applied automatically (see the quick
  reference below). Headline/body/CTA/logo are laid out in HTML/CSS and
  rasterised by headless Chromium, so Japanese typography is pixel-perfect.
- **Read the composed banners** and re-verify per format: **Legibility**, **CTA
  visibility**, and **safe-area respect** (copy clear of platform UI chrome and
  the format edges). The extreme aspect ratios deserve explicit re-checks — the
  **leaderboard `gdn_728x90`** (very wide/short) and the **skyscraper
  `gdn_160x600`** (very tall/narrow) are where legibility and cropping break
  first. If a format fails, either adjust copy length / template and re-compose,
  or drop that format and say so.

### 6. Deliver

- Present a **gallery summary table**: file path, format, template, and the
  7-dimension scores (+ total) for the chosen visual. Include the run **manifest
  path** and provenance (provider, model, prompt, seed where recorded).
- **On operator approval**, hand off to the **existing upload tools** — do not
  reinvent upload:
  - Meta: `meta_ads_images_upload_file` (returns an `image_hash`).
  - Google Ads: `google_ads_assets_upload_image`.
- **Caveats to surface**:
  - Publishing a **new** creative to Meta requires a **Live app** — dev-mode apps
    are blocked (error subcode **1885183**). Uploading the image asset may
    succeed; wiring it into a live ad is what dev mode blocks.
  - Composition requires `pip install 'mureo[creative]'` (+ `playwright install
    chromium`).
  - These are mutating platform operations — apply the *Security Rules → Confirm
    Before Write Operations* gate from `_mureo-shared` before any upload.

## Hosts without file access (Desktop / Cowork)

Claude Desktop chat and Cowork are MCP-only — they **cannot `Read` a local PNG**,
so you cannot see the pixels yourself. Same convention as creative-refresh's
visual evaluation:

- Run steps 1-3 and 5 normally (the `creative_studio_*` tools work everywhere and
  return file paths).
- For step 4, **do NOT self-score** — present the returned file paths (and run
  directory) to the operator and ask them to open the images and judge, or to
  paste one back into chat so you can see it. **Never invent a visual score for an
  image you have not actually seen.**
- State plainly that the pixel-level art-direction loop needs the Code surface
  (or a future ImageContent tool). Everything else (brief, copy, composition,
  provenance) still works.

## BRAND_KIT / kit.yml quick reference

`creative_studio_compose` reads `./BRAND_KIT/kit.yml` automatically; call
`creative_studio_brand_kit_get` to inspect the resolved kit (colours / fonts /
logo / clear-space) before composing so you can judge brand fit. A missing or
malformed kit never fails — every field degrades to a tasteful neutral default.

```yaml
# ./BRAND_KIT/kit.yml  (all keys optional; unknown keys ignored)
colors:
  primary:    "#1a1d29"   # #rgb or #rrggbb
  secondary:  "#6b7280"
  accent:     "#4f46e5"
  text:       "#111827"
  background: "#ffffff"
fonts:
  heading: "Noto Sans JP"  # safe font-family name only
  body:    "Noto Sans JP"
logo: "logo.png"           # path relative to the BRAND_KIT/ dir (png/jpg/jpeg/webp)
logo_min_clear_px: 24      # non-negative integer; clear-space padding around the logo
```

## Guardrails

Creative generation is a normal tool call, so the operator can block it
deterministically: listing `creative_studio_generate_visual` under STRATEGY.md
`## Guardrails` → `blocked_operations` makes `StrategyPolicyGate` refuse the tool
(name-match, no extra config). If generation is blocked, say so and stop — do not
route around it. See `../_mureo-strategy/SKILL.md` → *Guardrails*.

IMPORTANT: Every visual and every line of copy must trace back to Persona, USP,
Brand Voice, or the landing page — never generic. Score the pixels you actually
see, never the prompt. When you compromise (a format dropped, a dimension below
bar), say so explicitly in the delivery.
