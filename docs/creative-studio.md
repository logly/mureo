# Creative Studio

> [日本語版](creative-studio.ja.md)

Generate **creator-quality ad creatives** — text-free key visuals plus fully
composed banners — from a strategy-grounded brief, without leaving your ad-ops
workflow. Creative Studio is built into mureo (not a paid add-on), works across
any genre, and lets you bring your own image-generation API key.

---

## What it is

The naive "prompt → image API → done" pipeline produces unmistakably-AI banners:
garbled Japanese text, broken typography, off-brand colours. Creative Studio wins
on quality by **separating three layers** and giving each to the tool that is
actually good at it:

1. **Visual layer** — an image model generates the **background / key visual
   only** (photo, illustration, product scene, texture). A hard *no-text*
   constraint is appended to every prompt, because image models render text —
   especially Japanese — badly.

2. **Typography & layout layer** — headline, body, CTA, badge, and logo are laid
   out in **HTML/CSS and rendered by headless Chromium (Playwright)**, so Japanese
   is pixel-perfect and you get web fonts, flexbox, gradients, and shadows — the
   same tools a designer uses.

3. **Art-direction layer** — the agent becomes the art director: it generates N
   candidates, **actually looks at each PNG**, scores it against the 7-dimension
   creative-refresh rubric, keeps the best, refines weaknesses through the
   provider's edit path, and re-scores until the quality bar is met. This loop is
   what separates a shippable creative from a plausible-looking one. The whole
   flow is encoded in the [`/creative-generate`](#the-creative-generate-workflow)
   skill.

---

## Install

Visual **generation** (steps 1-4 of the workflow) works with the core install.
**Composition** — the HTML/CSS + Chromium typography layer — needs the optional
`creative` extra and a Chromium browser:

```bash
pip install 'mureo[creative]'     # adds jinja2, playwright
playwright install chromium       # one-time browser download for Playwright
```

The composition dependencies are lazily imported, so a core install stays lean;
`creative_studio_compose` returns a clear `pip install 'mureo[creative]'` hint if
the extra is missing.

---

## Provider keys (bring your own)

Creative Studio is **BYO-API-key**: you choose the image provider and pay the
provider directly. Only providers with a configured key are selectable; the agent
lists them with `creative_studio_providers_list` and you pick one (or fan out
across all of them). mureo ships three built-ins and third parties can register
more under the `mureo.image_providers` entry-point group.

| Provider | Key (credential field) | Env-var fallback | Edit path |
|---|---|---|---|
| OpenAI (gpt-image) | `creative_studio.openai_api_key` | `OPENAI_API_KEY` | yes |
| Google (Gemini image / Imagen) | `creative_studio.gemini_api_key` | `GEMINI_API_KEY` | yes |
| fal.ai (FLUX / Recraft …) | `creative_studio.fal_key` | `FAL_KEY` | no |

The recommended way to add keys is the `mureo configure` dashboard: open the
**Setup** tab and use the **Creative Studio (image generation)** section, which
gives each provider a labelled, masked input, shows a ✓/✗ configured indicator,
and saves straight into the `creative_studio` credentials section (leave a field
blank to keep its stored key; a **Remove** button clears the whole section once
a key is stored). Exporting the env-var fallbacks above still works for
headless / CI setups. Keys are never logged and provider error messages are
redacted.

> **Rough cost pointer.** Each provider bills you per generated image (typically a
> few US cents up to ~10¢ per image at current list prices, varying by model and
> resolution). The art-direction loop deliberately generates several candidates
> (`n >= 4`) and may edit the top ones, so budget a handful of image calls per
> finished creative. Check your provider's current pricing page for exact rates.

---

## BRAND_KIT / kit.yml

A lightweight brand kit makes generated banners look like they belong to a
specific brand rather than a generic template. It is read from
`./BRAND_KIT/kit.yml` in the workspace and surfaced by
`creative_studio_brand_kit_get`. **Every field is optional** and degrades
field-by-field to a tasteful neutral default — a missing, empty, or malformed kit
never fails a compose, it only emits a warning for the field it could not use.

```yaml
# ./BRAND_KIT/kit.yml
colors:
  primary:    "#1a1d29"   # #rgb or #rrggbb (case-insensitive)
  secondary:  "#6b7280"
  accent:     "#4f46e5"
  text:       "#111827"
  background: "#ffffff"
fonts:
  heading: "Noto Sans JP"  # safe font-family name only ([A-Za-z0-9 -_+.], <= 64 chars)
  body:    "Noto Sans JP"
logo: "logo.png"           # path relative to BRAND_KIT/ (png/jpg/jpeg/webp, <= 10MB)
logo_min_clear_px: 24      # non-negative integer: clear-space padding around the logo
```

| Key | Roles / type | Default |
|---|---|---|
| `colors` | `primary` / `secondary` / `accent` / `text` / `background` (hex) | near-black / grey / indigo / near-black / white |
| `fonts` | `heading` / `body` (font-family name) | `Noto Sans JP` |
| `logo` | path relative to `BRAND_KIT/` | none |
| `logo_min_clear_px` | integer px | `24` |

Unknown keys and invalid values are ignored (with a `BrandKitWarning`); a bad hex
colour or an unreadable logo falls back only for that one field.

---

## Format matrix

`creative_studio_compose` renders any subset of these formats in one call. Each
carries per-format **safe areas** (keep-out margins) so copy and logo stay clear
of the format edges and platform UI chrome.

| Format id | Size (px) | Aspect | Surface |
|---|---|---|---|
| `meta_feed_1x1` | 1080 × 1080 | square | Meta feed |
| `meta_feed_4x5` | 1080 × 1350 | portrait | Meta feed |
| `story_9x16` | 1080 × 1920 | vertical | Meta stories (14% top / 20% bottom reserved for UI chrome) |
| `gdn_300x250` | 300 × 250 | landscape | Google Display (medium rectangle) |
| `gdn_336x280` | 336 × 280 | landscape | Google Display (large rectangle) |
| `gdn_728x90` | 728 × 90 | landscape | Google Display (leaderboard — tight 2% margin) |
| `gdn_160x600` | 160 × 600 | vertical | Google Display (skyscraper — tight 2% margin) |
| `rda_landscape` | 1200 × 628 | landscape | Responsive display asset |
| `rda_square` | 1200 × 1200 | square | Responsive display asset |

Three layout templates position the copy: `hero_overlay` (headline band over the
lower third), `split` (copy panel beside the subject), and `minimal_badge`
(centered copy + small badge chip over an even-textured subject).

### Japanese fonts

The composer bundles a two-face Japanese pipeline — **Noto Sans JP** (body) and
**Zen Kaku Gothic New** Bold (display) — downloaded once into `~/.mureo/fonts`
with checksum-locked provenance. When a download is unavailable (offline), it
falls back to the system Japanese stack (Hiragino / Yu Gothic / Meiryo), so
composition still renders real glyphs, not tofu boxes.

---

## The `/creative-generate` workflow

The `creative-generate` skill drives the whole thing in six steps:

1. **Brief** — read STRATEGY.md (Persona / USP / Brand Voice); when an LP URL is
   given, run `google_ads_landing_page_analyze` / `google_ads_creative_research`;
   confirm genre, offer, tone, and target formats with the operator.
2. **Copy** — the agent writes 2-3 headline/body/CTA sets grounded in Brand
   Voice. Copy is passed to composition only — **never** into the image prompt.
3. **Visuals** — `creative_studio_providers_list`, then
   `creative_studio_generate_visual` with a visual-only prompt and negative-space
   guidance matching the template's copy zone (`n >= 4`).
4. **Art-direction loop** — `Read` each PNG, score it on the 7-dimension rubric,
   keep the top 1-2, refine with `creative_studio_edit_visual`, re-score. Pass bar:
   no dimension `<= 3` and total `>= 28/35`, max 3 edit rounds per visual.
5. **Compose** — `creative_studio_compose` renders the chosen visual + winning
   copy + template into the target formats; the agent re-reads the banners to
   re-verify legibility, CTA visibility, and safe-area respect per format.
6. **Deliver** — a gallery table (paths, format, template, scores) + the run
   manifest, then hand approved banners to the existing upload tools
   (`meta_ads_images_upload_file` / `google_ads_assets_upload_image`).

Run it in Claude Code with `/creative-generate`, or describe the goal in natural
language on Desktop / Cowork ("make three banner variations for this campaign").

---

## Visual prompt engineering

Prompt quality is the ceiling on visual quality, so the `creative-generate` skill
ships a **prompt-engineering framework** the agent fills for every generation: a
scaffold (`[subject & action] + [environment] + [style discipline] + [lighting] +
[color & mood] + [composition & negative space] + [quality descriptors]`), a
style-discipline menu (commercial photography, illustration, 3D render,
collage/editorial), per-genre presets (beauty, B2B SaaS, real estate, food/EC,
recruiting), provider-dialect notes (FLUX / gpt-image / Gemini image), and an
anti-patterns list. See the skill's *Visual prompt engineering* section for the
worked examples.

To make negative space mechanical rather than a matter of prompt wording,
`creative_studio_generate_visual` takes an optional **`template`** argument
(`hero_overlay` / `split` / `minimal_badge`). When set, the tool appends that
template's negative-space sentence to the prompt automatically, so the generated
subject leaves the calm zone the matching layout overlays copy into. Pass the
template you intend to compose with, then still restate the composition intent in
the prompt body — the two reinforce each other.

---

## Safety notes

- **Throttle.** Every provider call passes through a shared rate limiter
  (`CREATIVE_STUDIO_THROTTLE`) so a fan-out run cannot hammer a provider API.
- **Audit-only action log.** Each generate / compose / edit run is recorded as an
  audit-only `action_log` entry (with the provenance manifest path) when a
  STATE.json exists — `reversible_params=None`, because these write local files
  only and are not platform mutations to reverse. The *reversible* record is made
  later, by the existing upload / creative-create tools.
- **No-text constraint.** The image prompt is always wrapped with a hard no-text
  rule. This is deliberate: image models are unreliable at rendering text (Latin,
  and catastrophic at Japanese). Keeping text out of the model and in the HTML/CSS
  layer is *why* the output looks professional — do not try to route copy through
  the image prompt.
- **Input validation.** Generated, edited, and brand-logo images are validated
  before any downstream use; provider endpoints are fixed vendor hosts (no
  user-supplied URLs, so no new SSRF surface).
- **Guardrails.** Listing `creative_studio_generate_visual` under STRATEGY.md
  `## Guardrails` → `blocked_operations` makes mureo's policy gate refuse the tool
  (name-match, no extra config).
- **Meta dev-mode publishing caveat.** Uploading the image asset may succeed, but
  publishing a **new** creative to Meta requires a **Live app** — a development-mode
  app is blocked (error subcode **1885183**).

---

## Troubleshooting

**`Creative Studio composition requires the 'creative' extra: pip install 'mureo[creative]'`**
Install the extra and the browser: `pip install 'mureo[creative]'` then
`playwright install chromium`. Generation (steps 1-4) works without it; only
composition needs it.

**`No image provider is configured…`**
No provider key is set. Add one in the `mureo configure` dashboard's
`creative_studio` section, or export `OPENAI_API_KEY` / `GEMINI_API_KEY` /
`FAL_KEY`, then re-run `creative_studio_providers_list` to confirm it shows as
configured.

**`provider '<name>' does not support image editing`**
Not every provider has an edit path (fal.ai does not). Use OpenAI or Google for
the art-direction edit loop, or omit `provider` so the tool auto-picks the first
edit-capable configured provider.

**Composed Japanese text looks like boxes (tofu), or fonts look wrong offline**
The bundled font download failed and the system fallback stack is missing a
Japanese face. Install a Japanese system font (Noto Sans JP / Hiragino / Yu
Gothic / Meiryo), or reconnect so `~/.mureo/fonts` can populate on the next
compose.

**`creative_studio_*` tools are missing entirely**
The family is disabled via `MUREO_DISABLE_CREATIVE_STUDIO=1`. Unset it and restart
the MCP server.

---

## Related

- Workflow skill: `mureo/_data/skills/creative-generate/SKILL.md`
- Scoring existing banners: `mureo/_data/skills/creative-refresh/SKILL.md` → *Visual creative evaluation*
- Getting started: [docs/getting-started.md](getting-started.md)
- Architecture: [docs/architecture.md](architecture.md)
