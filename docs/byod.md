# BYOD: Bring Your Own Data

Run mureo against your **real** ad account in 5 minutes — without OAuth,
without a Google Ads developer token, without giving any SaaS access to
your data.

You export a CSV from Google Ads / Meta Ads Manager / Search Console,
drop it into mureo, and ask Claude Code to run `/daily-check`. mureo
analyses the file locally and produces a strategy-grounded diagnosis.
**No network calls reach Google or Meta. No real credentials are read.**

> **Phase 1a status:** Google Ads CSV is supported today. Meta Ads and
> Search Console adapters land in Phase 1b. The MCP plumbing is already
> in place — adding new platforms is a matter of writing the adapter.

---

## Why BYOD?

The biggest barrier to mureo adoption is the OAuth + Google Ads developer-
token application — the latter takes days to weeks. BYOD bypasses both:

- Try mureo against **your actual account**, not a synthetic demo.
- No data governance review needed — the CSV stays on your machine.
- Compatible with `mureo setup claude-code` you already ran (no extra
  MCP config).
- Read-only by construction: every mutation tool (`create_*`, `update_*`,
  `pause_*`, etc.) returns `{"status": "skipped_in_byod_readonly"}`.

---

## 5-minute walkthrough (Google Ads)

### Step 1 — Install mureo + register MCP

```bash
pip install mureo
mureo setup claude-code --skip-auth   # registers MCP only; no OAuth
```

### Step 2 — Export a CSV from Google Ads

1. Open Google Ads → **Reports → Report editor**.
2. Drag in **Campaign**, **Day**, **Impressions**, **Clicks**, **Cost**.
   Optionally also drag **Ad group** and **Conversions**.
3. Choose a date range (last 14–30 days is typical).
4. Click **Download → Comma-separated values (.csv)**.

### Step 3 — Import into mureo

```bash
mureo byod import --google-ads ~/Downloads/report.csv
```

Output:

```
=== mureo byod import ===

  Detected format: google_ads_report_editor_v1
  Validated 421 rows, date range 2026-04-01 to 2026-04-25
  Normalized to /Users/you/.mureo/byod/google_ads/
    - campaigns.csv
    - ad_groups.csv
    - metrics_daily.csv

Mode summary:
  google_ads      BYOD (421 rows, 2026-04-01..2026-04-25)
  meta_ads        not configured (no BYOD data, no credentials.json)
  search_console  not configured (no BYOD data, no credentials.json)

Next: ask Claude Code: 'Run /daily-check'
```

### Step 4 — Ask Claude Code

Open Claude Code in any directory that contains a `STRATEGY.md` (or
generate one with `mureo onboard` if you don't have one yet), then type:

> Run /daily-check

mureo's MCP server detects your imported CSV automatically — no flag
required — and the agent reasons over your real data.

---

## CLI reference

| Command | Description |
|---|---|
| `mureo byod import <file.csv>` | Auto-detect format; refuse if a platform is already imported |
| `mureo byod import <file.csv> --google-ads` | Force the Google Ads adapter |
| `mureo byod import <file.csv> --replace` | Overwrite an existing import |
| `mureo byod status` | Show per-platform mode (BYOD / real API / not configured) |
| `mureo byod remove --google-ads` | Remove only one platform |
| `mureo byod clear` | Wipe `~/.mureo/byod/` |
| `mureo byod clear --yes` | Skip the confirmation prompt |

There is **no `--byod` flag** anywhere. mureo decides per-platform at
each tool call by checking `~/.mureo/byod/manifest.json`. Real-API
credentials and BYOD imports coexist freely.

---

## How activation works

```
┌────────────────────┐
│ mureo byod import  │──▶ ~/.mureo/byod/manifest.json
└────────────────────┘            │
                                  ▼
                       ┌───────────────────────┐
   Claude Code ─MCP──▶│ mureo MCP server      │
                       │                       │
                       │  per-tool dispatch    │
                       │  byod_has(platform)?  │
                       └─────┬───────────────┬─┘
                       yes  │             no │
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
| google_ads imported, meta_ads + SC not | Google = CSV, Meta = real API, SC = real API |
| google_ads + meta_ads imported, SC not | Google = CSV, Meta = CSV, SC = real API |
| nothing imported | All three platforms = real API |
| `mureo byod clear` | All three = real API |

You can run a `/daily-check` that joins BYOD-Google with real-Meta in
the same call. This is useful for agencies who have API access to some
client accounts but only CSV exports for others.

---

## What BYOD blocks

mureo BYOD is **read-only by design**. The agent can analyse your data,
diagnose, and propose actions, but never writes to a real account.
Every method on the BYOD clients with one of the following name
prefixes returns `{"status": "skipped_in_byod_readonly", ...}`:

`create_`, `update_`, `delete_`, `remove_`, `add_`, `send_`, `upload_`,
`pause_`, `resume_`, `enable_`, `disable_`, `apply_`, `publish_`,
`submit_`, `attach_`, `detach_`, `approve_`, `reject_`, `cancel_`,
`set_`, `patch_`.

So if the agent calls `pause_campaign` after seeing a runaway-spend
incident in your CSV, the call **doesn't actually pause anything** —
it returns a stub response, and the agent sees that the action would
have written to a real account.

---

## Privacy guarantees

- **Local only.** mureo never uploads imported CSVs anywhere. The
  network-isolation test patches `httpx.AsyncClient.send` and
  `urllib.request.urlopen` and asserts zero outbound calls during a
  BYOD-mode tool dispatch.
- **PII column rejection.** If your CSV has a column whose name
  contains `email`, `phone`, `user_id`, `ip_address`, or
  `customer_email`, `mureo byod import` refuses the file and tells you
  to remove the column from the export.
- **Path-traversal defense.** The installer refuses to write outside
  `~/.mureo/byod/`.

---

## Supported source formats (Phase 1a)

| Platform | Source | Required columns (case-insensitive) | Optional |
|---|---|---|---|
| Google Ads | Report Editor → CSV download | Campaign, Day, Impressions, Clicks, Cost | Ad group, Conversions, Campaign state, Advertising channel type, Bid strategy type, Budget |

The adapter is tolerant of the 1–3 line preamble Google Ads adds (account
name, report title, date filter), and skips trailing `Total` / `Grand
total` / `合計` rows so they don't double-count metrics. Both
`YYYY-MM-DD` and `YYYY/MM/DD` date formats are accepted; currency
symbols (¥/$/€/£) and thousands separators are stripped automatically.

Phase 1b adds:

- Meta Ads Manager → Insights export
- Search Console → Performance report

---

## What's *not* in BYOD

- **`/daily-check`'s organic-search insights** that depend on Search
  Console data work only after the SC adapter ships in Phase 1b.
- **`/rescue` budget operations.** The agent can recommend rescues but
  cannot execute them — BYOD is read-only.
- **Live token refresh.** BYOD doesn't read or refresh OAuth tokens.

For the full live-account experience, run `mureo auth setup` (or
`mureo auth setup --web`) and `mureo byod clear` to switch back to
real-API mode.

---

## Troubleshooting

### `Error: <file>: not a Google Ads Report Editor export`

Your CSV is missing one or more of the required columns. Re-export
from Google Ads with **Campaign**, **Day**, **Impressions**, **Clicks**,
and **Cost** dragged in as report columns.

### `BYOD data for 'google_ads' already exists.`

Pass `--replace` to overwrite, or run `mureo byod remove --google-ads`
first.

### `mureo byod status` shows BYOD active but `/daily-check` returns nothing

Run `mureo byod status` and look for a "manifest references X but X is
missing on disk" warning in the MCP server logs. If the platform's
directory was deleted out of band, run `mureo byod import --replace`
or `mureo byod remove --<platform>`.

---

## Related

- CLI reference: `docs/cli.md`
- Architecture: `docs/architecture.md`
- Real-API auth: `docs/authentication.md`
