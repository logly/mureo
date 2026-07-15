---
name: lead-form-create
description: "Create a Meta Instant Form (Lead Ad form) through a one-question-at-a-time interview. Use when the user asks to create a lead form, Instant Form, CV form, or similar. The agent collects required parameters via a guided dialogue, confirms, then calls meta_ads_lead_forms_create. Also use when the user asks in Japanese (リードフォームを作成 / インスタントフォームを作って / CVフォーム作成)."
metadata:
  version: 0.10.26
---

# Lead Form Create

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection**.

Drive an interactive interview that produces a Meta Instant Form (Lead Ad form) on the user's Facebook Page. The skill is for the first-time creation flow — lifecycle operations (update / archive / duplicate) live in their own paths.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)
- Meta Ads platform must be configured in STATE.json `platforms`
- The user can supply a Facebook Page ID (mureo does not currently ship a Page-listing helper)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


### How to drive the interview

This skill is a **dialogue**, not a form-fill. Ask the user **one question at a time** and wait for an answer before moving on. Do **not** dump every parameter at once. The user-facing experience the operator asked for is "answer a few questions and the form appears" — pacing matters.

For every step below:

1. State what you're about to ask in one sentence.
2. Offer a sensible default (drawn from STRATEGY.md / Persona / Brand Voice / prior `meta_ads_lead_forms_list` results) so the user can answer with "use the default" instead of typing.
3. After they answer, repeat their answer back in one sentence and move on.

Skip a step only when the answer is unambiguous from STATE.json / STRATEGY.md (e.g. only one Facebook Page on the account → still confirm in one line, do not silently assume).

1. **Identify the Facebook Page**: Ask the user for the Page ID that will own the form (e.g. "Which Facebook Page should host this form? Paste the Page ID."). mureo does not currently ship a Page-listing helper, so do not pretend to enumerate Pages — if the user does not know their Page ID, point them at **Meta Business Suite → Page Settings → Page Info**, or `https://www.facebook.com/<page-name>/about`. Capture the supplied `page_id` for the create call.

2. **Form name**: Ask for the form name shown in Ads Manager + Page Lead Center. Default suggestion uses the current campaign / Persona context — e.g. "2026 Q2 — `<Persona>` lead form". Confirm the picked name with the user before moving on.

3. **Lead questions to collect**: Ask "What information do you need from each lead?" with a one-sentence default (e.g. "Most B2B advertisers ask for name + email + phone — use that default?"). Build the `questions` list:
   - Standard types: `FULL_NAME`, `EMAIL`, `PHONE_NUMBER`, `COMPANY_NAME`, `JOB_TITLE`, `CITY`, `STATE`, `ZIP_CODE`, `COUNTRY`, `DATE_OF_BIRTH`.
   - Custom questions (advertiser-defined) — only when the user asks for one. Each custom question needs `type: CUSTOM`, a stable `key` (used as the CRM field name; suggest a snake_case key based on the label), a `label`, and `options` if it is a dropdown. Walk the user through each custom question one at a time.

   Adding more than ~3 standard questions noticeably reduces submission rate — warn the user when the list grows beyond that.

4. **Privacy policy URL**: Ask the user for the advertiser's privacy policy URL. Meta requires `https://` and will reject the form otherwise — validate the prefix and re-prompt if the input does not start with `https://`. Suggest pulling the URL from STRATEGY.md when possible.

5. **Intro card (`context_card`)?**: Ask "Do you want an intro / welcome screen before the form questions? It typically lifts CVR." If yes, collect — one question per step:
   - **title** — short headline.
   - **content** — body text. Default style is `PARAGRAPH_STYLE`; offer `LIST_STYLE` if the body is naturally bulletable.
   - **cover image** — explicitly ask "Do you want a cover image on the intro screen?" The operator's feedback flagged this as the kind of question users want surfaced.
     - **IMPORTANT — `cover_photo_id` needs a PAGE photo id, not an ad-account `image_hash`.** Do **not** use `meta_ads_images_upload_file` / `meta_ads_creatives_upload_image` here — those upload to the ad account and return an `image_hash`, which Meta rejects for a form cover photo (this previously failed silently).
     - If the user wants a cover image: call **`meta_ads_pages_upload_photo`** with the form's `page_id` and either a `file_path` (local image) or `image_url`. Capture the returned **`photo_id`** and pass it as `context_card.cover_photo_id`.
       - This needs the `pages_manage_posts` permission. If the call fails with a permissions error (e.g. `(#200)` / `pages_manage_posts`), tell the user to re-run Meta auth (`mureo` Meta login) so the access token picks up the scope, then retry. As a fallback they can upload the cover manually in **Ads Manager → form builder → intro screen**.
     - If the user does not want a cover image, omit `cover_photo_id` entirely.

6. **Post-submission behaviour**: Ask which of three options the user wants — (a) Meta's default confirmation (no extra config), (b) a simple redirect to a URL after submission (the lightweight `follow_up_action_url` field, common case for "send them to my thank-you page"), or (c) a full custom completion screen with title / body / CTA button. If (b), capture the URL. If (c), collect — one question per step: `title`, `body`, `button_type` (`VIEW_WEBSITE` / `CALL_BUSINESS` / `MESSAGE_BUSINESS` / `DOWNLOAD` / `DOWNLOAD_APP`), `website_url`, `button_text`. Note: `thank_you_page` supersedes `follow_up_action_url` when both are set, so do not collect both — pick one based on the user's choice.

7. **Higher-intent (3-step) mode?**: Explain the trade-off in one sentence: "Higher-intent mode adds a review step before submit. It improves lead quality and trims junk submissions, but it costs total volume." Then ask yes/no. Default is `false` (single-step) unless the operator's STRATEGY.md flags quality over volume.

8. **Locale**: Ask whether to use the Page's primary locale or override (e.g. `ja_JP` for a Japanese form on a multilingual Page). Default = Page primary locale.

### Confirm before mutating

Once every answer is collected, summarise the full payload in a short bulleted list (form name, questions, privacy URL, intro card on/off, thank-you on/off, higher-intent on/off, locale) and **ask the user to confirm** before calling the tool. Do not call `meta_ads_lead_forms_create` until the user gives an explicit go-ahead.

### Create the form

Call `meta_ads_lead_forms_create` with the collected parameters. On success, report the new `form_id` back to the user. On failure, surface the platform error verbatim and offer to retry with adjusted parameters (do not silently retry with different values).

### Suggest the natural next step

After the form is created, suggest using it in a Lead Ad creative: "To wire this form into an ad, run `meta_ads_creatives_create_lead` with `form_id=<new_id>`, `page_id=<page_id>`, and either an `image_hash` or a `video_id`." Stop there — building the creative belongs to a separate flow; this skill's job is the form.

### Edge cases

- **No Meta Ads access**: If the Meta Ads provider is not configured (or `MUREO_DISABLE_META_ADS=1` is set), explain to the user that mureo's Meta Ads tools are unavailable and point them at `mureo setup claude-code` / `mureo providers add meta-ads-official`. Do not attempt the create call.
- **Privacy URL is `http://`**: Re-prompt; do not pass a non-HTTPS URL into `meta_ads_lead_forms_create`.
- **User wants to revisit an earlier answer**: Honour it. Edit the in-progress payload and re-summarise before the confirm step.
- **The form should reuse an existing form's structure**: Suggest `meta_ads_lead_forms_duplicate` instead of this skill — that is a different starting point and outside this skill's scope.
- **The user asks for branching logic (`conditional_questions_choices`)**: The tool supports it (e.g. "if industry = retail, ask about store count next") but this skill does not interview for it in v1 — the interview would balloon into a question-graph editor. Explain the trade-off and offer to call `meta_ads_lead_forms_create` directly with a hand-written `conditional_questions_choices` payload if the user supplies one, or suggest creating the form linearly first via this skill and following up with `meta_ads_lead_forms_update`.
