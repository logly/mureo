# BYOD: Bring Your Own Data

> [日本語版](byod.ja.md)

Run mureo against your **real Google Ads / Meta Ads account** in 5
minutes — no OAuth Client ID to register, no Google Ads developer
token to apply for, no SaaS connection of any kind. You run a Google
Ads Script (or export from Meta Ads Manager), download the resulting
Sheet/Excel as XLSX, drop it into mureo, and ask Claude Code to run
`/daily-check`.

**No network calls reach Google or Meta from mureo. No mureo-managed
credentials are involved. The Sheet lives in your own Drive; mureo
only ever reads the local XLSX file.**

> **Status (Phase 2):** Google Ads (via the mureo Google Ads Script)
> and Meta Ads (via the Ads Manager Excel export) are both supported
> through the Sheet bundle pipeline. GA4 and Search Console remain on
> the existing real-API OAuth path (see `docs/authentication.md`) —
> they are **not** part of the BYOD bundle.

---

## Why BYOD?

The biggest barriers to local-first ad analysis are OAuth client
registration and Google Ads developer-token approval (days to weeks).
BYOD avoids both:

- Try mureo against **your actual account**, not a synthetic demo.
- No data governance review needed — the XLSX stays on your machine.
- Compatible with the `mureo setup claude-code` you already ran (no
  extra MCP config).
- Works on Google Workspace **organization** accounts where
  Apps Script is blocked from auto-creating a personal GCP project
  (Google Ads Scripts run inside the Ads UI, not Apps Script).
- **Read-only by construction**: every mutation tool (`create_*`,
  `update_*`, `pause_*`, etc.) returns
  `{"status": "skipped_in_byod_readonly"}`.

---

## 5-minute walkthrough

### Step 1 — Install mureo

```bash
pip install mureo
mureo setup claude-code --skip-auth   # registers MCP only; no OAuth
```

### Step 2a — Run the Google Ads Script (optional)

Open Google Ads → **Tools → Bulk actions → Scripts → +**.

Paste the contents of `scripts/sheet-template/google-ads-script.js`.
At the top, set `TARGET_SHEET_URL` to the URL of any Google Sheet you
own (create a fresh one if you don't have one yet). Click
**Authorize** and **Run**.

Four tabs populate in the Sheet: `campaigns`, `ad_groups`,
`search_terms`, `keywords`. Auction insights are intentionally
excluded — Google Ads Scripts cannot reach them. Use
`mureo auth setup` if you need `/competitive-scan` data.

### Step 2b — Export from Meta Ads Manager (optional)

In Ads Manager: **Reports → Customize → Export**.

Configure the report once with these columns (one row per
day × ad-set × ad):

- **Breakdowns:** *By Time → Day*
- **Level:** *Ad* (gives the full Campaign / Ad set / Ad hierarchy)
- **Metrics:** Day, Campaign name, Ad set name, Ad name,
  Impressions, Clicks (all), Amount spent (JPY), Results
- **Account language:** English (other locales aren't recognized in
  v1 — switch under *Reports → Account language*)

Click **Export → Excel (.xlsx)**. Save the file alongside the Google
Ads Sheet's XLSX export.

### Step 3 — Download as XLSX, import to mureo

In the Google Sheet, **File → Download → Microsoft Excel (.xlsx)**.
Then run mureo byod import once per file:

```bash
# Google Ads bundle
mureo byod import ~/Downloads/<google-ads-bundle>.xlsx

# Meta Ads export (separate file from Ads Manager → Reports → Export)
mureo byod import ~/Downloads/<meta-ads-export>.xlsx
```

Sample output:

```
=== mureo byod import ===

  [google_ads] format: mureo_sheet_bundle_google_ads_v1
    421 rows, date range 2026-04-01..2026-04-30
    written to /Users/you/.mureo/byod/google_ads/
      - campaigns.csv
      - metrics_daily.csv
      - ad_groups.csv
      - keywords.csv
      - search_terms.csv

Mode summary:
  google_ads        BYOD (421 rows, 2026-04-01..2026-04-30)
  meta_ads          not configured (no BYOD data, no credentials.json)

Next: ask Claude Code: 'Run /daily-check'
```

### Step 4 — Ask Claude Code

Open Claude Code in any directory that contains a `STRATEGY.md` (or
generate one with `mureo onboard` if you don't have one yet), then
type:

> Run /daily-check

mureo's MCP server detects your imported bundle automatically — no
flag required — and the agent reasons over your real Google Ads data:
search-term gaps, keyword quality scores, etc.

---

## CLI reference

| Command | Description |
|---|---|
| `mureo byod import <file.xlsx>` | Import a Sheet bundle. Aborts if the target platform already has BYOD data. |
| `mureo byod import <file.xlsx> --replace` | Overwrite existing BYOD data for the platform present in the bundle. |
| `mureo byod status` | Show per-platform mode (BYOD / real API / not configured). |
| `mureo byod remove --<platform>` | Remove BYOD data for one platform (`--google-ads` / `--meta-ads`). |
| `mureo byod clear` | Wipe `~/.mureo/byod/` entirely. |
| `mureo byod clear --yes` | Skip the confirmation prompt. |

There is **no `--byod` flag** anywhere. mureo decides per-platform at
each tool call by checking `~/.mureo/byod/manifest.json`. Real-API
credentials and BYOD imports coexist freely — see the next section.

---

## How activation works

```
┌──────────────────────────────┐
│ mureo byod import bundle.xlsx│──▶ ~/.mureo/byod/manifest.json
└──────────────────────────────┘                │
                                                ▼
                                  ┌───────────────────────┐
   Claude Code ─────MCP──────────▶│ mureo MCP server      │
                                  │                       │
                                  │  per-tool dispatch    │
                                  │  byod_has(platform)?  │
                                  └─────┬───────────────┬─┘
                                  yes   │             no │
                                        ▼                ▼
                              ┌────────────────┐  ┌─────────────────┐
                              │ Byod*Client    │  │ create_*_client │
                              │ (reads CSV)    │  │ (live API)      │
                              └────────────────┘  └─────────────────┘
```

`byod_has(platform)` returns True only when:

1. `~/.mureo/byod/manifest.json` exists and is parseable
2. Its `schema_version` is supported (currently `1`)
3. The platform is registered under `platforms`
4. `~/.mureo/byod/<platform>/` actually exists on disk

If you remove `~/.mureo/byod/google_ads/` out of band but leave the
manifest, mureo logs a warning and falls back to real-API mode for
that platform.

---

## Mixing BYOD and real API

| Setup | Result |
|---|---|
| Bundle imported for Google Ads; meta_ads not configured | Google Ads = bundle, Meta = real API |
| Bundle imported for Meta Ads; google_ads not configured | Meta = bundle, Google Ads = real API |
| Bundles imported for both | Both = bundle |
| Nothing imported | All platforms = real API |
| `mureo byod clear` | All platforms = real API |

GA4 and Search Console always go through the real-API OAuth path —
the bundle pipeline does not cover them.

---

## What BYOD blocks

mureo BYOD is **read-only by design**. The agent can analyse your
data, diagnose, and propose actions, but never writes to a real
account. Every method on the BYOD clients with one of the following
name prefixes returns `{"status": "skipped_in_byod_readonly", ...}`:

`create_`, `update_`, `delete_`, `remove_`, `add_`, `send_`,
`upload_`, `pause_`, `resume_`, `enable_`, `disable_`, `apply_`,
`publish_`, `submit_`, `attach_`, `detach_`, `approve_`, `reject_`,
`cancel_`, `set_`, `patch_`.

---

## Switching back to the real API

```bash
mureo byod remove --google-ads          # remove just one platform
# or
mureo byod clear                         # remove all BYOD data
```

`mureo byod clear` does **not** touch `~/.mureo/credentials.json`,
so your real-API OAuth tokens survive a BYOD reset. After removal,
restart Claude Code; the MCP server detects the missing manifest at
startup and falls back to credentials.json automatically.

If you see `not configured` for the platform you removed,
run `mureo auth setup` (or `mureo auth setup --web`) to populate
`~/.mureo/credentials.json`.

---

## Privacy guarantees

- **Local only.** mureo never uploads imported data anywhere. The
  network-isolation tests patch `httpx.AsyncClient.send` and
  `urllib.request.urlopen` and assert zero outbound calls during a
  BYOD-mode tool dispatch and during the bundle import itself.
- **No mureo-managed OAuth.** The Google Ads Script runs under your
  Google Ads account. mureo has no GCP project and no OAuth client
  for the BYOD path.
- **Path-traversal defense.** The bundle importer refuses to write
  outside `~/.mureo/byod/`.

---

## Tabs the bundle importer recognizes

| Source | Tab signal | → mureo CSV(s) |
|---|---|---|
| Google Ads Script | `campaigns` (required) | `campaigns.csv` + `metrics_daily.csv` |
| Google Ads Script | `ad_groups` | `ad_groups.csv` |
| Google Ads Script | `keywords` | `keywords.csv` |
| Google Ads Script | `search_terms` | `search_terms.csv` |
| Meta Ads Export | Any sheet whose header contains a Day column + `Campaign name` + `Impressions` | `meta_ads/{campaigns,ad_sets,ads,metrics_daily}.csv` |

The bundle importer dispatches the Google Ads adapter when at least
one of those tabs is present, and the Meta Ads adapter when it
detects a Meta Ads Manager export-style header. The two adapters are
disjoint — Google Ads tabs use `campaign` (short form) while Meta
uses `Campaign name` (long form), so a workbook can carry only one
adapter's data.

---

## What's *not* in BYOD

- **GA4 / Search Console.** Use the real-API OAuth path
  (`mureo auth setup`); they are not part of the bundle pipeline.
- **`/rescue` budget operations.** The agent can recommend rescues
  but cannot execute them — BYOD is read-only.
- **Live token refresh.** BYOD doesn't read or refresh OAuth tokens.

The Meta export adapter recognizes column headers in English /
日本語 / Español / Português / 한국어 / 繁體中文 / 简体中文 /
Français / Deutsch — exporting from Ads Manager in any of these
languages works without changing Account language.

For the full live-account experience, run `mureo auth setup` (or
`mureo auth setup --web`) and `mureo byod clear` to switch back to
real-API mode.

---

## Google Ads richer BYOD tools

The Sheet bundle's `search_terms` tab is exposed through the existing
Google Ads MCP surface:

| Tool | Returns |
|---|---|
| `google_ads.search_terms.report` | One row per search term: campaign_name, ad_group_name, impressions, clicks, cost, conversions, ctr, average_cpc |

`google_ads.auction_insights.get` / `analyze` return empty under BYOD
(the data isn't available from Google Ads Scripts). Use
`mureo auth setup` for the real-API path if competitor share data is
required.

---

## Troubleshooting

### `Error: <file>: failed to open as XLSX`

Verify the file is the **Microsoft Excel (.xlsx)** download from
*File → Download → Microsoft Excel*. Other formats (Google Sheets
native, ODS, CSV) won't work.

### `Error: <file>: no recognized tabs found`

The bundle importer expects at least one of the Google Ads tabs
listed above. Verify the Google Ads Script actually populated data —
check the Sheet tabs by hand.

### `BYOD data for 'google_ads' already exists.`

Pass `--replace` to overwrite, or run
`mureo byod remove --google-ads` first.

### `mureo byod status` shows BYOD active but `/daily-check` returns nothing

Run `mureo byod status` and look for a "manifest references X but X
is missing on disk" warning in the MCP server logs. If the platform's
directory was deleted out of band, run
`mureo byod import --replace` or `mureo byod remove --<platform>`.

---

## Related

- Sheet template scripts: `scripts/sheet-template/README.md`
- CLI reference: `docs/cli.md`
- Architecture: `docs/architecture.md`
- Real-API auth: `docs/authentication.md`
