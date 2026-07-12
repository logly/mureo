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
- **Write the prompt with the scaffold**, never off the top of your head — see
  **Visual prompt engineering** below for the full framework, the style-discipline
  menu, per-genre presets, and provider dialects. Quality is won here.
- **Pass the `template` arg** to `creative_studio_generate_visual`, set to the
  layout you intend to compose with (`hero_overlay` / `split` / `minimal_badge`).
  The tool then appends that template's negative-space sentence automatically, so
  the calm copy zone is **enforced mechanically** instead of left to memory.
  **Then still restate the composition intent in the prompt body** — passing the
  arg and writing it into the prompt reinforce each other, and the model listens
  harder when it hears the constraint twice:
  - `hero_overlay` → subject in the upper two thirds; keep the **lower third**
    clean and uncluttered for the headline/CTA band.
  - `split` → keep **one half** (left or right) clear as a solid-ish panel for
    copy; put the subject on the other half.
  - `minimal_badge` → a **center-weighted subject with even surrounding texture**
    so a small badge chip and centered copy read cleanly.
- Call `creative_studio_generate_visual` with the **visual-only** prompt (scene /
  subject / style / lighting / mood + the restated negative space). Use `n >= 4`
  candidates (`aspect` picks the master generation size — `square` / `portrait` /
  `landscape` / `vertical`). The tool appends the hard no-text constraint for you
  and writes every PNG to a run directory with a provenance `manifest.json`.

### Visual prompt engineering

The `template` arg and the no-text constraint are handled for you — **this
section is how you raise the ceiling of the picture itself.** The scoring loop
(step 4) can only pick from what you generate; a lazy prompt caps the whole run.
Skip to *4. Art-direction loop* for the scoring checklist and come back here
whenever you are actually writing a prompt.

#### The prompt framework

Never free-associate a prompt. Fill this scaffold, in this order, every time:

```
[subject & action]
  + [environment / setting]
  + [style discipline]
  + [lighting]
  + [color & mood — tie to Brand Voice / BRAND_KIT palette]
  + [composition & negative space — auto-handled when the `template` arg is
     passed; restate it here for reinforcement]
  + [quality descriptors]
```

Each slot is a lever. Leaving one vague hands that decision to the model's
default — usually a generic, over-lit stock look. Fill the slots that matter for
the genre; do not pad the ones that don't. Tie **color & mood** to the Brand
Voice and the `BRAND_KIT` palette so the visual and the composed typography read
as one brand, not two.

**Worked example — photographic (beauty product):**

> A single frosted-glass serum bottle on wet river stone, water droplets
> catching the light + minimal spa setting, eucalyptus leaves soft out of focus
> + editorial commercial product photography, 100mm macro lens, shallow depth of
> field + soft diffused morning light from the left with one gentle rim
> highlight + cool sage-green and cream palette, calm clinical-premium mood +
> center-weighted subject with even, low-contrast surrounding texture for a
> centered card overlay + crisp focus on the label area, natural water
> refraction, high detail.

**Worked example — illustration (B2B SaaS hero):**

> A stylized isometric dashboard floating above a laptop, small abstract data
> nodes connecting outward + clean off-white studio backdrop with a faint grid +
> flat vector illustration with soft grain, geometric shapes, consistent thick
> line weight + flat even lighting with gentle long shadows + indigo and
> slate-blue accents on a near-white ground, confident and trustworthy mood +
> main object in the upper two thirds, lower third calm for a headline band +
> clean edges, balanced negative space.

#### Style disciplines menu

Pick ONE discipline per generation — mixing them muddies the model.

| Discipline | Vocabulary that works | When to use (ad genre) |
|---|---|---|
| **Commercial photography** | lens (35mm environmental, 50mm natural, 100mm macro), aperture look (shallow depth of field / deep focus), lighting rig (softbox, high-key, golden-hour, rim light) | product, food, real estate, beauty — anything that must feel real and premium |
| **Flat & textured illustration** | flat vector, geometric shapes, grain / paper texture, limited palette, consistent line weight | SaaS, fintech, abstract services, explainer creatives |
| **3D render** | soft studio render, subsurface scattering, matte clay look, soft contact shadows | app UI heroes, product concepts, playful DTC |
| **Collage / editorial** | cut-paper collage, magazine editorial layout, bold color blocking, mixed media | recruiting, culture, bold brand campaigns |

#### Genre presets

Five starting points. Each is a scaffold-filled prompt (English — image models
respond best to English) plus one line on why it converts for that genre.

**美容 / コスメ (beauty):**
> Close-up of a dewy skincare cream swatch on smooth skin, a soft highlight
> gliding across it + minimal pastel studio surface + macro commercial
> photography, 100mm, shallow depth of field + soft high-key light, no harsh
> shadows + blush-pink and pearl-white palette, fresh gentle mood +
> center-weighted subject with even surrounding texture + natural skin texture,
> high detail, no plastic sheen.
> *Why it converts:* texture and softness signal efficacy and gentleness; the
> calm center leaves room for a JP product name and price without fighting the
> visual.

**B2B SaaS:**
> An abstract network of glowing connected nodes over a clean desk with a laptop
> + bright uncluttered workspace + flat isometric vector illustration with subtle
> grain + even studio lighting + indigo and slate accents on off-white, competent
> calm mood + subject in the upper two thirds, lower third clear for a headline +
> balanced, uncluttered composition.
> *Why it converts:* trust and clarity beat spectacle for B2B; an uncluttered
> frame reads as "this tool is simple," and the clear band carries a value-prop
> headline.

**不動産 (real estate):**
> A sunlit modern living room with large windows and warm wood floors, a soft
> linen sofa + bright airy interior with plants near the window + interior
> architectural photography, 24mm wide, deep focus + warm golden-hour daylight
> flooding in + warm neutral palette with soft green accents, aspirational homey
> mood + composed to read when cropped to one half of the frame, clean edges +
> realistic materials, crisp detail, no fisheye distortion.
> *Why it converts:* light and space sell the lifestyle; the half-frame
> composition suits a split layout carrying price / access / area copy in JP.

**EC・食品 (food / ecommerce):**
> A stack of fresh handmade dorayaki with red-bean filling on a rustic ceramic
> plate, faint steam rising + warm cafe tabletop with a soft blurred background +
> macro food photography, 60mm, shallow depth of field + warm directional window
> light with appetizing highlights + warm amber and cream palette, cozy
> craving-inducing mood + center-weighted subject with even background texture +
> glossy natural food sheen, rich detail, no artificial-coloring look.
> *Why it converts:* appetite appeal is visual first; the warm center-weighted
> shot leaves clean space for a centered badge (期間限定 / 送料無料) and the price.

**採用 (recruiting):**
> Three diverse colleagues collaborating around a bright table, candid natural
> laughter mid-action + modern open office with plants and warm wood + candid
> editorial lifestyle photography, 35mm, natural depth + soft daylight from large
> windows + warm optimistic palette with the brand accent, welcoming energetic
> mood + subjects in the upper two thirds, lower third calm for a headline band +
> authentic detail, natural skin tones, no stiff posed-stock look.
> *Why it converts:* candid warmth signals culture better than posed stock; JP
> candidates respond to genuine atmosphere, and the calm band carries the role
> and message.

#### Provider dialect notes

Different backends reward slightly different prompt styles:

| Provider | Dialect | Lean on it for |
|---|---|---|
| **FLUX** (fal.ai) | Concrete photographic vocabulary — exact lens (85mm), aperture, and named lighting rigs land precisely | crisp product and photoreal shots where you can name the optics |
| **gpt-image** (OpenAI) | Understands natural-language intent and complex scene logic; be explicit about mood and relationships | multi-element scenes, conceptual / abstract briefs, "the feeling of…" |
| **Gemini image** (Google) | Strong at photoreal product / scene consistency; iterate via the edit path | consistent product renders you refine with `creative_studio_edit_visual` |

When unsure which will land, **fan out with `provider="all"`** (one candidate per
configured provider) and let the step-4 scoring loop pick the winner — do not
agonize over provider choice up front.

#### Anti-patterns

- **Never put copy / text in the prompt.** No headline, no CTA, no Japanese — the
  model garbles it and the typography layer owns text. (It is stripped by the
  no-text constraint anyway; do not fight it.)
- **No brand names, celebrities, or logos** — a policy and IP hazard, and the
  model's rendition is off-brand regardless. Describe the *look*, then apply the
  real logo in compose.
- **Skip "4k, 8k, masterpiece, trending on artstation" token spam.** Modern
  models ignore it; describe the light and the material instead ("soft rim light,
  matte ceramic surface").
- **Don't over-constrain.** Nail subject, style, lighting, and negative space;
  leave secondary details (exact background props, minor colors) to the model so
  it composes naturally.
- **One concept per generation.** Variations come from `n` (and `provider="all"`),
  never from cramming two ideas into one prompt — two subjects fighting for the
  frame is the fastest route to a weak, cluttered candidate.

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
