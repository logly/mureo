# Getting Started

This guide walks you through running mureo end-to-end. mureo is your local-first AI ad ops crew — pick a **mode** (what data to use) and a **host** (where the agent runs), then follow the matching walkthrough.

For a 30-second overview of which combination to pick, jump to [Choosing the right combination](#choosing-the-right-combination) at the bottom.

> **Two ways to set up mureo — pick one.**
>
> - **Easiest — do it all from a browser (recommended):** `pip install mureo` then `mureo configure`. A local web UI (bound to `127.0.0.1`) lets you do **everything on this page by point-and-click** — host selection, basic setup, OAuth/credentials, official MCP providers, Demo/BYOD. No terminal commands needed.
> - **Manual — run the commands yourself:** everything below walks you through it **one command at a time**. Use this for scripting/CI or fine-grained control.
>
> Both reach the same result. If you're not sure, use `mureo configure`.

---

## Modes × Hosts at a glance

| | Claude Code | Claude Desktop chat | Cowork (Desktop) |
|---|---|---|---|
| **Demo** (synthetic data) | `mureo setup claude-code --skip-auth` + `mureo demo init --scenario seasonality-trap` | `mureo install-desktop --with-demo seasonality-trap` | Same as Desktop chat + connect the workspace folder in Cowork |
| **BYOD** (your XLSX bundle) | `mureo setup claude-code --skip-auth` + `mureo byod import bundle.xlsx` | `mureo install-desktop` + `mureo byod import bundle.xlsx` | Same as Desktop chat + connect the workspace folder |
| **Auth** (Live API) | `mureo setup claude-code` (interactive OAuth) | `mureo install-desktop` + `mureo configure` | Same as Desktop chat + connect the workspace folder |

**Host quick reference:**

- **Claude Code** — full skill suite via `/<name>`, supports `Read` / `Write` / `Bash` / MCP, runs locally in your terminal/IDE.
- **Claude Desktop chat** — natural-language only; **no** `Read` / `Write` / `Bash` tools, only MCP. Skills are invoked by describing the goal ("run a daily check"), not by typing `/<name>`.
- **Cowork** (Desktop) — same MCP entry as the chat tab, **plus** sandboxed filesystem access to a folder you connect. Best for non-engineers who want the agent to read and write files visually.

---

# Demo (synthetic scenarios)

mureo ships with four scenarios so you can try the agent end-to-end without any real account: `seasonality-trap`, `halo-effect`, `hidden-champion`, `strategy-drift`. Each generates `STRATEGY.md`, `STATE.json`, and a synthetic ad bundle.

## A. Demo in Claude Code (5 min)

```bash
pip install mureo
mureo setup claude-code --skip-auth      # MCP + skills + credential guard, no OAuth
mureo demo init --scenario seasonality-trap
```

Then in Claude Code, in the demo workspace directory:

```
/daily-check
```

What you should see: a multi-platform health report based on the scenario's synthetic data, a Goal-progress summary, and (depending on the scenario) flagged anomalies with proposed actions.

To switch scenarios: `mureo demo init --scenario halo-effect --force`.

## B. Demo in Claude Desktop chat (10 min)

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo --with-demo seasonality-trap
```

What this does:
1. Creates `~/mureo/` and seeds it with the scenario (`STRATEGY.md`, `STATE.json`, synthetic XLSX bundle).
2. Generates a wrapper script at `~/.local/bin/mureo-mcp-wrapper.sh` that anchors the MCP server to the workspace.
3. Registers `mureo` in `~/Library/Application Support/Claude/claude_desktop_config.json`.

Then **quit Claude Desktop completely** (`⌘Q`) and re-open it.

In a chat tab:

```
Run a daily check on my campaigns
```

Claude picks up the skill from natural language and invokes the `mureo_*` MCP tools to read STRATEGY/STATE and the demo data.

> **Skills not appearing in the picker?** The slash-command picker only shows skills registered in claude.ai. Until [Anthropic Skills marketplace](https://github.com/anthropics/claude-plugins-official) accepts mureo, you can either (a) describe goals in natural language as above, or (b) [upload each `mureo/_data/skills/<name>/SKILL.md` manually via the claude.ai web UI](#manual-skill-upload-claudeai).

## C. Demo in Cowork (10 min)

Cowork is Claude Desktop's "agentic" tab — same MCP server as the chat tab, plus filesystem access to a folder you connect.

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo-demo --with-demo seasonality-trap
```

Then **restart Claude Desktop** and switch to the **Cowork** tab.

1. Open the **Connectors** / folder picker in Cowork.
2. **Connect** the `~/mureo-demo` folder.
3. Ask in Cowork:
   ```
   Run a daily check
   ```

Cowork can both call MCP tools (via the wrapper) AND read/write files inside `~/mureo-demo` directly, giving the agent the richest possible view of the workspace.

> **Why connect the folder?** The `mureo_strategy_get` / `mureo_state_*` MCP tools work without it, but Cowork's Read/Write tools let the agent inspect raw bundle files, write rollback plans, and so on. Both paths use the same workspace cwd, so updates from either tool are immediately visible to the other.

---

# BYOD — Bring Your Own Data (your XLSX bundles)

BYOD lets you run mureo against a **read-only export** of your real Google Ads / Meta Ads data without any OAuth flow. Every mutation tool refuses to write, so you cannot accidentally damage a live account.

## Step 1 — Get your data file

| Platform | How to export | Time |
|---|---|---|
| **Google Ads** | Google Sheet template (Apps Script) → populate Sheet → download `.xlsx` | ~5 min one-time per account |
| **Meta Ads** | Ads Manager → Reports → Saved Report (mureo template) → 2-click XLSX export | ~2 min |

Detailed step-by-step:
- [`docs/byod.md#google-ads-setup`](byod.md#google-ads-setup) — Google Ads template + filling instructions
- [`docs/byod.md#meta-ads-setup`](byod.md#meta-ads-setup) — Meta Ads Saved Report (recognized in 9 languages: English / 日本語 / 简体中文 / 繁體中文 / 한국어 / Español / Português / Deutsch / Français)

The exports are independent — you can start with one platform and add the other later. Search Console and GA4 are not part of BYOD; they require the Live API path.

## Step 2 — Where to put the file

The XLSX itself is just a temporary input — once imported, the data lives under `<workspace>/byod/<platform>/` (or the global `~/.mureo/byod/<platform>/` if you are running CLI without `install-desktop`).

| Setup | Recommended location for the XLSX |
|---|---|
| **Code** (CLI direct) | Anywhere — e.g. `~/Downloads/mureo-google-ads.xlsx` |
| **Desktop chat** | Anywhere — but inside `~/mureo/` is convenient because that is the MCP server's workspace |
| **Cowork** | **Inside the connected workspace folder** (`~/mureo/`) so the Cowork sandbox can see it |

The filename is arbitrary; you pass the path on import.

## Step 3 — Import the file

> **Today**: BYOD import runs from your terminal (Phase 4 of the roadmap will add a `mureo_byod_import` MCP tool so you can do this from chat). Until then, run the command below in any shell.

```bash
mureo byod import ~/Downloads/mureo-google-ads.xlsx
mureo byod import ~/Downloads/mureo-meta-ads.xlsx     # add Meta later if you skipped it
```

Where the data lands depends on whether you previously ran `mureo install-desktop`:

- **Wrapper present** (you ran `install-desktop`): the wrapper exports `MUREO_BYOD_DIR=<workspace>/byod` at chat time, but the CLI itself uses the legacy default. To target the workspace explicitly when importing:
  ```bash
  MUREO_BYOD_DIR=$HOME/mureo/byod mureo byod import ~/Downloads/mureo-google-ads.xlsx
  ```
- **Wrapper absent** (CLI direct, no `install-desktop`): writes to `~/.mureo/byod/<platform>/` (legacy default).

> **Switching from demo data to your own data**: per-workspace BYOD prevents collisions. `mureo install-desktop --workspace ~/mureo-demo --with-demo ...` and `mureo install-desktop --workspace ~/mureo-real --force` give you two independent BYOD stores. See [docs/byod.md](byod.md) for migration recipes.

## Step 4 — Try a workflow

### In Claude Code
```
/daily-check
```

### In Claude Desktop chat
```
Run a daily check on my marketing accounts
```

### In Cowork
Same as chat. If you connected the workspace folder, Cowork can also open `<workspace>/byod/google_ads/manifest.json` to show you what data is loaded.

## What works in BYOD

- Read-only analysis: `daily-check`, `weekly-report`, `goal-review`, `search-term-cleanup` (analysis), `competitive-scan` (limited — auction insights are not in the bundle), `creative-refresh` (suggestions only).
- Mutation tools (`rescue`, `budget-rebalance`, `creative-refresh` execute, search-term apply) return `{"status": "skipped_in_byod_readonly"}`. Upgrade to Live API to actually push changes.

---

# Auth (Live API)

Connect mureo directly to Google Ads / Meta Ads APIs. Required for actually executing changes (`/rescue`, `/budget-rebalance`, `/creative-refresh`, `mureo rollback apply`) and for GA4 / Search Console support.

## Step 1 — Get credentials

| Platform | What you need |
|---|---|
| **Google Ads** | [Developer Token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) + OAuth Client ID + Client Secret |
| **Meta Ads** | [Meta for Developers](https://developers.facebook.com/) App ID + App Secret (development mode is fine) |
| **GA4 / Search Console** | OAuth login (no developer token); the wizard handles this |

> **Approval timing**: Google Ads developer-token approval can take 1–3 weeks. Use BYOD in the meantime — switch to Auth once approved.

Credentials land in `~/.mureo/credentials.json` (permission `0600`). You never need to edit that file by hand — the wizard handles it.

## Step 2 — Run the OAuth wizard

Pick the host that matches where you want to run mureo.

### A. Auth in Claude Code

```bash
pip install mureo
mureo setup claude-code             # interactive OAuth wizard runs as part of setup
```

The setup command opens a local web wizard at `http://127.0.0.1:<random-port>/`, where you paste each token / secret in the appropriate field and complete the OAuth flow in the same browser. Skip individual platforms with `--no-google-ads` / `--no-meta-ads` if you only want one of them.

### B. Auth in Claude Desktop chat

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo
mureo configure                     # browser UI: OAuth + host setup + providers
```

Restart Claude Desktop. In a chat tab:

```
Run a daily check
```

The MCP server picks up the credentials from `~/.mureo/credentials.json` automatically.

### C. Auth in Cowork

Same as Desktop chat — Cowork uses the same MCP entry. After `install-desktop` + `auth setup`, **connect the workspace folder** in Cowork (`~/mureo`) so the agent can also see local files when needed.

> **Phase 4 preview**: a `mureo_auth_setup` MCP tool will let you start the OAuth wizard from chat directly. Until then, run `mureo configure` once (it opens the browser UI).

## Step 3 — Verify

```bash
mureo auth status
mureo auth check-google             # masked-output verification
mureo auth check-meta
```

Then run a workflow as in BYOD Step 4 above.

---

## Choosing the right combination

A 30-second decision tree:

1. **Just looking?** → Demo in Code or Desktop chat. 5–10 min. Fully reversible (delete the workspace dir).
2. **Have your real account, no developer token?** → BYOD. 10–15 min including the export. Read-only, safe.
3. **Have approved developer-token + want execution?** → Auth (Live API). 30–60 min first time. Required for `/rescue`, `/budget-rebalance` to actually push.

| If you... | Pick |
|---|---|
| Want to evaluate mureo on synthetic data | **Demo + Code** |
| Want to demo to a non-engineer | **Demo + Desktop chat** (no terminal needed after install) |
| Want richest agent experience for ops | **Demo + Cowork** (folder access) |
| Have your own account, want analysis only | **BYOD + Code** (or Desktop chat / Cowork) |
| Need executable mutations | **Auth + Code** (Code is the only host that can run `/rescue` end-to-end today) |

Skill availability by host:

| Host | Skill triggering | Notes |
|---|---|---|
| Claude Code | `/daily-check`, `/budget-rebalance`, … | All 10 operational skills + 6 foundation skills available locally |
| Claude Desktop chat | natural language ("run a daily check") | Skills must be registered to claude.ai (manual upload or marketplace) |
| Cowork | natural language | Same registration story as chat |

---

## Manual skill upload (claude.ai)

> Until [Anthropic Skills marketplace](https://github.com/anthropics/claude-plugins-official) lists mureo, Desktop / Cowork users can register skills manually:

1. Open claude.ai → **Skills** management page.
2. For each operational skill, upload the SKILL.md file from `mureo/_data/skills/<name>/SKILL.md` (10 files: `daily-check`, `budget-rebalance`, `search-term-cleanup`, `creative-refresh`, `rescue`, `goal-review`, `weekly-report`, `competitive-scan`, `onboard`, `sync-state`).
3. Foundation skills (the `_mureo-*` ones) are referenced via PREREQUISITE — uploading them is optional but recommended; they reduce the chance the agent misroutes a tool call.
4. Restart Claude Desktop.

---

## Troubleshooting

**"Workspace not found" / `[Errno 30] Read-only file system`**
You probably ran `mureo install-desktop` without `--workspace`, or Claude Desktop did not pick up your `cwd` setting. Re-run with an explicit workspace: `mureo install-desktop --workspace ~/mureo --force`. The wrapper script forces cwd, sidestepping a known Desktop bug.

**`mureo` MCP not appearing in Desktop's Connectors UI**
Quit Claude Desktop completely (`⌘Q`) and re-open. The config is only re-read on a full launch.

**Demo BYOD data persisting after switching to your real bundle**
You probably installed both into the same workspace, or both targeted the legacy global `~/.mureo/byod/`. Use a separate `--workspace` for each (e.g. `~/mureo-demo` and `~/mureo-real`) or `mureo byod clear` to reset.

**`/daily-check` (or other slash command) does not appear in Code**
Check `ls ~/.claude/skills/` — `daily-check` should be a directory. If not, re-run `mureo setup claude-code`. If it appears but the slash picker still shows nothing, restart Claude Code.

For more, see [docs/byod.md](byod.md), [docs/authentication.md](authentication.md), and [docs/cli.md](cli.md).
