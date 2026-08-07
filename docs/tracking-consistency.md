# Tracking-parameter consistency

An ad's final-URL tracking parameters decide which row of everyone's analytics its clicks land in. When an ad is uploaded into the wrong campaign carrying another campaign's tags, nothing looks broken: delivery is healthy, spend is healthy, and the reporting the whole team trusts is quietly wrong. Nobody investigates, because nothing appears to be wrong.

mureo checks for that class of defect in two places:

- **Account audit** — `/tracking-health` runs it across every configured platform.
- **Pre-flight** — before ads are created, the same detector runs over the account *plus* the ads about to be uploaded, and reports only what the new ads are responsible for.

Both go through one platform-neutral core (`mureo/analysis/tracking/`) and one MCP tool, `analysis_tracking_consistency_check`. The tool is read-only and reaches no platform API: the caller passes in ad records, so a platform mureo cannot fetch ads for is still auditable whenever the agent can list them.

### How strongly the pre-flight is enforced, per platform

This distinction matters: a check the agent can skip is not the same as a check it cannot.

| Path | Enforcement |
| --- | --- |
| `google_ads_ads_create`, `google_ads_ads_create_display` | **Enforced in the handler.** The check runs before the mutation; a finding refuses the create and the ad is not uploaded. Override per call with `acknowledge_tracking_findings=true`, or globally with `MUREO_DISABLE_TRACKING_PREFLIGHT=1`. |
| Meta Ads, plugin, bridged and hosted creates | **Routing only.** `_mureo-shared/SKILL.md` instructs the agent to run `analysis_tracking_consistency_check` before creating ads, but nothing stops it from skipping the step. |

The Meta gap is not an oversight to read past: on Meta the destination link lives on the **creative**, which is created by a separate earlier call (`meta_ads_creatives_create`), so the ad-create arguments carry a `creative_id` and no URL. Enforcing there means fetching the creative inside the create path; it is tracked as follow-up work rather than shipped half-done here. Plugin and bridged platforms stay best-effort for the same reason other guardrails do — mureo does not own their tool schemas.

**Why this is not a `PolicyGate`.** `mureo/core/policy.py` is the dispatch-level hook for write tools and would be the obvious home, but its v1 ABI rules it out on its own terms: the Protocol is *synchronous by design* ("gates that need to await network I/O are out of scope"), and gates "MUST be pure and fast" because they run on every tool call. This check can only compare the planned ad against the ads already in the account — one platform read, necessarily awaited. A gate also never sees the campaign: `google_ads_ads_create` takes `ad_group_id`, not `campaign_id`, and no siblings, so a pure gate would have nothing to compare and would enforce nothing. The handler is the first point that has both a client and an `await`.

**The pre-flight fails open.** Any error reading the account is logged and the create proceeds. A tracking check that cannot see the account must not stop an operator shipping an ad; the only thing that blocks is a positive finding.

## The design decision: where "inconsistent" comes from

mureo does **not** know what a correct `utm_campaign` looks like for your account. A prefix that identifies an audience segment in one account is a campaign month in the next. A check that guessed the convention and then judged ads against the guess would produce false positives, and a check that produces false positives gets muted — at which point it detects nothing at all.

So the zero-configuration checks derive their verdict entirely from **evidence already in the account**, and the one thing evidence cannot supply — operator intent — is **declared, never inferred**.

Four fixed, documented rules carry the whole false-positive story. None of them is an inference:

1. **Which parameters are read at all.** Only `utm_*` by default. A product id or a variant flag in the URL never contributes, so an account that carries content parameters in its final URLs is never compared on them. An account whose tracking uses other names declares them (`recognize:`, below).
2. **Which parameters identify a campaign.** Only `utm_source`, `utm_medium` and `utm_campaign` take part in the scheme comparison. `utm_content` and `utm_term` exist precisely so one campaign can tell its creatives and keywords apart on a single landing page — comparing on them would flag `utm_content=hero` vs `utm_content=video` as an inconsistency, which is the fastest way to have this check muted. They are still read (the presence checks and any declared value patterns see them); they just never make two ads "disagree". Move a parameter in or out of this set with `identify:` / `differentiate:`.
3. **Schemes are compared whole, never one parameter at a time.** A finding requires the *entire* campaign-identifying signature to match another campaign's. Per-parameter comparison reported "these ads borrowed campaign Y's `utm_source`" for a value like `google` that Y merely happens to share — and below three campaigns, or in any account where one campaign carries a single legitimate one-off ad, `google` **is** owned by exactly one other campaign, so the correctly-tagged majority got flagged. A whole-signature match says something true instead: these ads carry another campaign's entire tracking identity, so reporting cannot tell them apart.
4. **What counts as the same value.** A maximal run of digits is collapsed to `#` when values are compared. `segb01` and `segb02` are therefore the *same* scheme (`segb#`) while `sega01` is a different one (`sega#`). This is the single rule that distinguishes "article 2 instead of article 1" (legitimate) from "segment A instead of segment B" (a defect), and it errs toward treating values as the same — toward **fewer** findings.

## What it detects

| Code | Fires when | Configuration |
| --- | --- | --- |
| `foreign_campaign_scheme` | Some ads of campaign X carry a whole campaign-identifying signature that is the **sole** signature of **exactly one** other campaign Y on the same platform (Y having at least two ads carrying it), while campaign X also contains a different signature. | none |
| `same_destination_scheme_conflict` | Two ads in one campaign send clicks to the **same** landing page (scheme + host + path) under different campaign-identifying signatures. | none |
| `missing_tracking_parameter` | An ad lacks a parameter that **every** other tagged ad in its own campaign carries (minimum two siblings). | none |
| `untagged_final_url` | An ad's final URL carries no recognized tracking parameter at all, inside a campaign where at least two ads are tagged. | none |
| `missing_required_parameter` | A tagged ad lacks a parameter listed under `require:` in STRATEGY.md. | opt-in |
| `convention_violation` | A parameter value matches none of the patterns declared for it in STRATEGY.md. | opt-in |

`foreign_campaign_scheme` is the check that would have caught the incident behind [#550](https://github.com/logly/mureo/issues/550) at upload time: sixteen ads carrying segment A's `utm_campaign` prefix, uploaded into segment B's campaign. Comparing **whole signatures** is what stops a shared `utm_source=google` from firing — a value two campaigns merely have in common never matches a whole identity. Requiring **exactly one** owner campaign on top of that keeps a house style used by three or more campaigns out of the results.

Note that the motivating incident happened in an account with exactly **two** Display campaigns. A minimum-campaign-count guard would have switched the check off for the case it exists for, which is why the fix for shared values is the signature comparison, not a floor on how many campaigns an account has.

Neither scheme check declares which group is correct. mureo does not know that; it reports both groups, names the campaign the borrowed scheme belongs to, and leaves the decision with the operator.

## Severity reflects delivery state

A mis-tagged ad that has already served is a data-integrity incident that needs a reporting caveat. One that has never served is a cheap fix. Every finding carries both a `severity` and a `delivery_state`:

| `delivery_state` | Meaning | `severity` |
| --- | --- | --- |
| `served` | at least one ad in the finding has impressions > 0 | `critical` |
| `not_served` | every ad in the finding has impressions == 0 | `high` |
| `unknown` | per-ad delivery data was not supplied | `high` |

`unknown` is reported honestly rather than assumed: it means the severity **may be understated**, and the report says so in `notes`. Supply `impressions` per ad (omitted is *not* the same as `0`) to get the distinction.

## Declaring a convention (opt-in)

Add a `## Tracking Convention` section to `STRATEGY.md`:

```markdown
## Tracking Convention

- recognize: utm_*, argument
- identify: argument
- differentiate: utm_medium
- require: utm_source, utm_medium, utm_campaign
- pattern utm_source: google, yahoo
- pattern utm_campaign: seg[ab]??
```

- `recognize:` **adds** parameter-name globs to the default `utm_*` — declaring `argument` does not switch off `utm_*` detection.
- `identify:` **adds** parameters to the campaign-identifying set (the only ones schemes are compared on). An account that carries its audience segment in `utm_content` declares `identify: utm_content`. Anything declared here is recognized automatically — a parameter cannot be compared without first being read.
- `differentiate:` **removes** a default parameter from that set. An account whose `utm_medium` varies per creative declares `differentiate: utm_medium`.
- `require:` names parameters every tagged final URL must carry.
- `pattern <name>:` lists the value patterns allowed for one parameter; a value matching **any** of them conforms.

Patterns are `fnmatch` globs (`*`, `?`, `[seq]`), not regular expressions — an operator-authored regex in an agent-writable file is both harder to write and a denial-of-service surface, while a glob matches the shape these values actually have.

The section is parsed by mureo, not interpreted by the agent. An LLM deciding on the fly what "consistent" means is exactly the failure this check exists to replace. Accounts that declare nothing still get every zero-configuration check.

## Platform coverage

The core check only ever sees `AdTrackingRecord` (ad id, campaign id, destination URLs, platform, optional delivery). Each platform gets one thin accessor in `mureo/analysis/tracking/sources.py` that answers "give me this ad's destination URLs". Where the URL lives differs per platform, and on some platforms mureo cannot read it at all with the tools available:

| Platform | Where the URL lives | Read by mureo | Notes |
| --- | --- | --- | --- |
| Google Ads (native) | `final_urls` on the `google_ads_ads_list` row | yes | `records_from_google_ads_ads` |
| Meta Ads (native) | creative `object_story_spec` (`link_data.link`, or a call-to-action link on `video_data` / `photo_data` / `template_data`) plus creative-level `url_tags`, which Meta appends at delivery time | yes | `records_from_meta_ads_ads`. `url_tags` is read because `meta_ads_ads_list` now requests it |
| Plugin platforms via the provider ABI (Yahoo, LINE, SmartNews, LOGLY, …) | `Ad.final_url` | yes, one URL per ad — all the ABI models | `records_from_provider_ads`; pass the canonical `plugin:<distribution>:<provider>` key |
| Amazon Ads (bridged official MCP) | not exposed by the bridged tool surface mureo carries today | **no** | ads come back with no URL and are listed in `ads_without_readable_url` |
| Hosted connectors (e.g. TikTok's own MCP) | whatever that connector's own list tool returns | best-effort | `records_from_mappings` with an explicit field map |

`records_from_mappings` requires the caller to state which field holds the URL rather than sniffing for one. A guessed field name that silently resolves to nothing would turn "not checked" into a clean bill of health.

**"No finding" is not the same as "clean."** An ad whose destination URL could not be read is never silently dropped: it is counted and named in `ads_without_readable_url`, and the report carries a note saying so.

## Limits

Both lists below are meant to be complete. A check whose limits are undocumented gets trusted past them — and one whose false positives are undocumented gets muted the first time it cries wolf, which is worse.

### What it does NOT detect (false negatives)

- **A whole campaign mis-tagged.** If *every* ad in a campaign carries another campaign's scheme, there is no internal disagreement and no minority group. Deliberate sharing of one scheme by two campaigns is common enough that flagging this would be a false-positive machine.
- **A scheme shared by three or more campaigns.** `foreign_campaign_scheme` requires the shape to be traceable to exactly one owner. A shape used by three campaigns is a house style, not a leak.
- **The campaign it was copied from being outside the record set.** Pass the whole account. When the source campaign is absent, only `same_destination_scheme_conflict` can still fire — and only if the ads share a landing page with correctly-tagged ones.
- **Tracking that does not use `utm_*` names, undeclared.** Invisible until the names are declared under `recognize:` / `identify:`.
- **A wrong `utm_content` or `utm_term`.** These are excluded from the scheme comparison by design (they vary per creative and per keyword), so an ad that carries the wrong creative token is not flagged. Accounts that encode something campaign-identifying in `utm_content` declare `identify: utm_content` and get it back.
- **Non-numeric variation that is genuinely per-ad.** Two ads whose `utm_campaign` values differ in a non-digit way are two schemes as far as mureo is concerned. They only produce a finding under one of the rules above (same landing page, or a shape owned by exactly one other campaign), so per-landing-page word tokens do not fire — but a genuinely mis-tagged ad on a landing page nothing else points at, in an account with no comparable campaign, is not detected either.
- **`tracking_url_template` / `final_url_suffix` (Google Ads) set at campaign or account level.** mureo does not read those fields, so a scheme injected there is invisible.
- **Meta creative shapes that carry the destination elsewhere** — dynamic `asset_feed_spec` link sets, catalog-driven ads. These come back with no URL rather than a guess.
- **Whether the tags are *correct* in absolute terms.** mureo compares ads against each other and against what the operator declared. It cannot tell that the whole account's `utm_medium` should have been `cpc` rather than `ppc`.
- **Redirects.** The URL on the ad is what is compared; where it lands after a redirect chain is not fetched.
- **Duplicate query keys.** When one URL carries the same parameter twice, the first occurrence is used — delivery-time precedence is platform-specific and mureo does not guess it.
- **Anything on a create path that is not native Google Ads.** Meta, plugin, bridged and hosted ad creation is routing only — see the enforcement table above.

### What it may flag that you meant (false positives)

- **Two campaigns deliberately reporting under one identity.** If some — not all — of campaign X's ads carry exactly the same `utm_source` + `utm_medium` + `utm_campaign` as every ad of campaign Y, that fires. It is a real reporting collision (those ads are indistinguishable from Y's in analytics), but it can be intentional, e.g. a shared always-on line item split across two campaigns. Declare the distinguishing parameter with `identify:` so the two stop looking identical.
- **Campaign tokens that differ only in digits.** `promo001` and `promo101` collapse to the same shape `promo#`, so two campaigns using that pattern read as one scheme. This is the digit-collapsing rule doing what it is for; the same rule is what stops `segb01` vs `segb02` from firing. Use tokens that differ by more than a digit, or declare patterns.
- **An A/B test of the tracking itself.** Two ads pointing at one landing page under two deliberately different schemes is exactly what `same_destination_scheme_conflict` reports. That is usually what you want to know, but if you are running such a test it is noise — acknowledge it per call, or park the check with `MUREO_DISABLE_TRACKING_PREFLIGHT=1`.

Two earlier false positives are fixed rather than documented, and are pinned by tests so they stay fixed: `utm_content` / `utm_term` varying per creative on one landing page (rule 2 above), and a value like `utm_source=google` that two campaigns merely share (rule 3).

## Using it

```jsonc
// audit
{
  "ads": [
    {"ad_id": "111", "campaign_id": "c1", "campaign_name": "Display / Segment B",
     "platform": "google_ads", "impressions": 0,
     "final_urls": ["https://example.com/article/1/?utm_source=google&utm_medium=cpc&utm_campaign=sega01"]}
  ],
  "convention_markdown": "## Tracking Convention\n\n- pattern utm_campaign: seg[ab]??\n"
}

// pre-flight — only the planned ads are reported on
{
  "ads": [ /* the campaign as it exists today */ ],
  "planned_ads": [
    {"ad_id": "new-1", "campaign_id": "c1", "platform": "google_ads",
     "final_urls": ["https://example.com/article/9/?utm_source=google&utm_medium=cpc&utm_campaign=segb09"]}
  ]
}
```

The response carries `mode` (`audit` / `preflight`), `findings`, `ads_examined`, `campaigns_examined`, `ads_without_readable_url` and `notes`.
