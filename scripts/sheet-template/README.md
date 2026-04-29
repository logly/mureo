# mureo Sheet template scripts

A Google Ads Script that pulls Google Ads data into a Google Sheet
that the user then exports as XLSX and feeds to mureo via
`mureo byod import <file>.xlsx`.

```
┌───────────────────────────────────┐    ┌──────────────────────────┐
│ Google Ads (Tools → Scripts)      │    │ Google Sheet (user)       │
│ google-ads-script.js              │───▶│ tabs: campaigns,          │
│ paste & Run (one click)           │    │   ad_groups, search_terms,│
└───────────────────────────────────┘    │   keywords                │
                                          │                          │
                                          │ File → Download → .xlsx  │
                                          └────────────┬─────────────┘
                                                       │
                                                       ▼
                                          mureo byod import <file>.xlsx
```

No mureo-managed credentials, no GCP Console setup, no OAuth Client
Secret. The script runs under the user's own Google Ads / Google
account on Google's infrastructure.

## Scope

This BYOD path covers **Google Ads only**. GA4 and Search Console are
reached via the existing real-API OAuth credentials (see
`docs/authentication.md`); attempting to feed those datasets through
the Sheet bundle is not supported. Meta Ads BYOD ships in a follow-up
PR.

## Files

| File | Where to paste | Purpose |
|---|---|---|
| `google-ads-script.js` | Google Ads → Tools → Bulk actions → Scripts | Google Ads data fetch via GAQL — populates the destination Sheet |

## Per-user setup

1. Create a fresh Google Sheet (or reuse one). Copy its URL.
2. Open Google Ads → **Tools → Bulk actions → Scripts → +**.
3. Paste `google-ads-script.js`.
4. Set `TARGET_SHEET_URL` at the top of the script to the Sheet URL.
5. Click **Authorize** (Google Ads grants Sheets write).
6. Click **Run**. Data populates `campaigns`, `ad_groups`,
   `search_terms`, `keywords` tabs. (Auction insights are not part
   of the BYOD path — Google Ads Scripts cannot reach them; use
   `mureo auth setup` for `/competitive-scan` if needed.)
7. **Export**: File → Download → Microsoft Excel (.xlsx).
8. **Import into mureo**:

   ```bash
   mureo byod import ~/Downloads/<file>.xlsx
   ```

## Why this design?

mureo's design contract — local-only, no SaaS dependency — rules out
bundling a mureo-managed OAuth Client / Developer Token. See
`docs/byod.md` for the full rationale. Google Ads Script is the path
that:

- Requires no OAuth Client ID / Secret from the user
- Requires no GCP Console step from the user (Ads Scripts run inside
  the Ads UI, not Apps Script — no per-user GCP project auto-creation)
- Works on Google Workspace organization accounts where Apps Script
  is blocked from auto-creating a personal GCP project
- Keeps mureo zero-infrastructure (the Sheet lives in the user's Drive,
  the script runs on Google's servers, and the data flows local to
  local via the XLSX export)
- Survives mureo team disappearance — users can fork the script
  themselves at any time

## Versioning

The script file is versioned in this repo. When the team updates it,
the user re-pastes the new contents into their Google Ads Scripts
panel.

## Tested with

- Google Ads Scripts (current as of 2026)
