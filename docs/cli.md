# CLI Guide

mureo provides a command-line interface for setup, authentication, and environment configuration. Ad platform operations are handled through MCP tools used by AI agents, not through the CLI.

## Installation

```bash
pip install mureo
```

## Command Structure

```
mureo <subcommand-group> <command> [options]
```

| Group | Description |
|-------|-------------|
| `setup` | Environment setup (Claude Code, Cursor, Codex, Gemini) |
| `auth` | Authentication management |
| `configure` | Open the local web configuration UI (credential entry + host setup) |
| `open` | Bring an already-running configure dashboard to the front |
| `service` | Install / inspect / remove the always-on configure service |
| `upgrade` | Upgrade mureo and its plugins (also re-deploys skills) |
| `byod` | Bring Your Own Data — analyse ad-account data locally, no OAuth |
| `demo` | Scaffold a self-contained demo workspace |
| `providers` | Install / list / remove official MCP providers (Google Ads, Meta, GA4) |
| `amazon` | Amazon Ads official-MCP bridge setup |
| `install-desktop` | Wire mureo into Claude Desktop chat (macOS) |
| `learn` | Append insights to the diagnostic knowledge base |
| `rollback` | Inspect reversible actions recorded in STATE.json |
| `repair` | Repair STATE.json problems mureo can fix without guessing |

Run `mureo --help` to see all available groups.

## Setup Commands

### Claude Code (recommended)

```bash
mureo setup claude-code
```

One-command setup that handles:
1. Google Ads / Meta Ads authentication (OAuth)
2. MCP server configuration (`~/.claude/settings.json`)
3. Credential guard (blocks AI agents from reading secrets)
4. Workflow commands as native slash skills (`~/.claude/skills/`)
5. Skills (`~/.claude/skills/`) — bundled operational + shared skills, plus any plugin-provided native slash skills discovered via the `mureo.native_skills` entry-point group (#439)

`mureo configure` (the browser UI) deploys the same skills — bundled and plugin native — when it runs basic setup.

Use `--skip-auth` to install commands, skills, MCP config, and credential guard without running OAuth:

```bash
mureo setup claude-code --skip-auth
```

### Cursor

```bash
mureo setup cursor
```

Sets up authentication and MCP configuration for Cursor. Cursor does not support workflow commands or skills.

### OpenAI Codex CLI

```bash
mureo setup codex
```

Full parity with Claude Code. Installs:

1. MCP server configuration as a tagged `[mcp_servers.mureo]` block in `~/.codex/config.toml` (append-only; refuses to overwrite an untagged pre-existing `[mcp_servers.mureo]`).
2. Credential guard — PreToolUse hooks in `~/.codex/hooks.json` (Read + Bash) that block any tool call that would touch `~/.mureo/credentials*`.
3. Workflow commands as **Codex skills** at `~/.codex/skills/<command>/SKILL.md` with YAML frontmatter. Users invoke them with `$daily-check`, `$onboard`, … or via the `/skills` picker. (Codex CLI 0.117.0+ no longer surfaces `~/.codex/prompts/`, per [openai/codex#15941](https://github.com/openai/codex/issues/15941); re-running `mureo setup codex` also deletes stale prompt files that mureo owns, while leaving user-authored prompts alone.)
4. Shared mureo skills at `~/.codex/skills/mureo-*/`.

`--skip-auth` is supported and is auto-implied under a non-TTY subprocess (e.g. an AI agent's Bash tool) so the command can never hang on a confirm prompt.

### Gemini CLI

```bash
mureo setup gemini
```

Registers mureo as a Gemini CLI extension at `~/.gemini/extensions/mureo/gemini-extension.json` with `mcpServers.mureo` and `contextFileName: CONTEXT.md`. Operator-added top-level keys (`excludeTools`, renamed `contextFileName`) and extra `mcpServers` entries are preserved across reinstall. Gemini CLI does not support PreToolUse hooks or the `.md` command format, so those layers are not installed.

### Per-platform flags (all `setup …` subcommands)

Every setup subcommand accepts:

- `--skip-auth` — install MCP config (+ guard / commands / skills, where supported) without running OAuth. Auto-implied under a non-TTY invocation.
- `--google-ads` / `--no-google-ads` — override the "configure Google Ads?" prompt.
- `--meta-ads` / `--no-meta-ads` — override the "configure Meta Ads?" prompt.

Passing the platform flags alongside `--skip-auth` (or under a non-TTY) emits a warning and is ignored.

## Authentication Commands

```bash
# Show authentication status for all platforms
mureo auth status

# Check Google Ads credentials (masked output)
mureo auth check-google

# Check Meta Ads credentials (masked output)
mureo auth check-meta

# Interactive authentication wizard (terminal prompts)
mureo auth setup

# Browser configuration UI (no terminal input needed) — supersedes the
# removed `mureo auth setup --web`
mureo configure
```

Credential entry has two front doors:

- **`mureo auth setup` (terminal, default)** — walks you through Google Ads / Meta Ads setup via stdin prompts. Best when you're comfortable pasting secrets into a terminal.
- **`mureo configure` (browser)** — starts a local UI on `http://127.0.0.1:<random-port>/` and opens your browser. It does the same credential entry (HTML forms + standard OAuth redirects, each field deep-linked to the right console) **and** the rest of Claude setup: pick the host, run basic setup, add official MCP providers, scaffold Demo/BYOD. Recommended when an AI agent (Claude Code, etc.) pointed you here, or you just prefer a GUI. (The old `mureo auth setup --web` was removed and folded into `mureo configure`.)

Both end at the same destination: `~/.mureo/credentials.json` is populated and Claude (or any other MCP client) picks up mureo after a restart.

See [authentication.md](authentication.md) for details on credentials.

## Amazon Ads Commands

`mureo amazon` sets up the Amazon Ads official-MCP bridge. Enter the Amazon credentials first — in the **Amazon Ads** card of the **Plugin credentials** section of `mureo configure` (recommended), via the `AMAZON_ADS_*` environment variables, or by hand in the `amazon_ads` section of `~/.mureo/credentials.json`. The card also carries the **Authorize with Amazon** flow, which obtains the tokens for you: Amazon has no loopback callback, so it is a guided paste-code flow — mureo opens Amazon's consent page and you paste the redirected address back.

```bash
# Discover Amazon's MCP tools and (re)write amazon_tools.json beside
# your credentials file (~/.mureo/amazon_tools.json by default)
mureo amazon refresh-manifest
```

`refresh-manifest` connects once, authenticated, lists the official Amazon Ads MCP's tools, and writes the local manifest the mureo MCP server reads at start. Re-run it when Amazon's tool surface changes or after you re-authorize; a routine access-token refresh is handled automatically and needs no CLI action.

See [amazon-ads.md](amazon-ads.md) for the full walkthrough.

## Configure UI & Always-On Service

`mureo configure` normally runs the browser UI on demand and stops when idle. To keep it running across reboots — so the dashboard (including the read-only **Reports** tab) is always reachable — register it as a user-level auto-start service.

```bash
# Open the configure UI (or surface the already-running one)
mureo configure
mureo open                 # bring an already-running configure UI to the front

# Run headless as a long-lived daemon (no browser, no idle timeout).
# This is what the service backend invokes; you rarely run it by hand.
mureo configure --serve --port 7613

# Auto-start service (user-level: launchd on macOS, systemd --user on
# Linux, Task Scheduler on Windows — never root/admin daemon).
mureo service install      # register + start now (runs at every login)
mureo service status       # show installed / running state + the URL
mureo service restart      # restart in place to pick up a new version
mureo service uninstall    # remove the auto-start registration
```

Notes:

- **Windows**: `mureo service install` registers an on-logon Scheduled Task. Creating it writes to the Task Scheduler root, which needs an **elevated** shell — run it from a PowerShell opened via *Run as administrator* (being in the Administrators group is not enough). The task itself then runs at logon with your normal (non-elevated) rights.
- After upgrading mureo, run `mureo service restart` so the running daemon picks up the new code (Task Scheduler and the supervisors do not relaunch a cleanly-exited process automatically on every platform).
- The configure dashboard's **About** tab also has a **Restart configure** button that does the same thing from the browser: a managed service restarts via its supervisor, while an interactive `mureo configure` restarts itself in place. The page waits for the server to come back and reloads automatically.

### Configure log

Every configure run — interactive, `--serve`, or started by the auto-start service — writes to:

```
~/.mureo/logs/configure.log        # (%USERPROFILE%\.mureo\logs\configure.log on Windows)
```

`mureo configure` prints the path on startup. The file is rotated at 1 MiB and keeps 3 older generations (`configure.log.1` … `.3`), so it is bounded at ~4 MiB no matter how long the daemon runs. It is created owner-only (`0600`) on macOS/Linux.

What goes in it: the server's own lifecycle (bound URL, single-instance reuse, shutdown), credential *operations* (which env var name was written into which file, which plugin credential keys were accepted — never a value), and the failures the UI deliberately shows only as a generic message — a Meta token refresh that failed or could not be persisted, an account listing that failed, a credential file that would not parse. Warnings and errors also still go to the terminal.

Platform failures are recorded as a status code plus the platform's own error *identifiers*, not its response body: a failed Meta token refresh, for instance, logs `HTTP 400 from Meta Graph (… | code=190 | subcode=460)` — enough to look the error up or quote it in a support ticket, without writing an unbounded, vendor-authored blob to your disk. Quote the whole line in a bug report; it carries no credential value.

Raise the level with an environment variable (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO`):

```bash
MUREO_LOG_LEVEL=DEBUG mureo configure
```

For the always-on service, add it to the unit rather than the shell: `Environment=MUREO_LOG_LEVEL=DEBUG` in `~/.config/systemd/user/mureo-configure.service`, or an `EnvironmentVariables` entry in `~/Library/LaunchAgents/io.mureo.configure.plist`, then `mureo service restart`.

`DEBUG` adds every HTTP request line the local UI served. Query strings are redacted before they are written (an OAuth callback carries an authorization code in its query), and no log line at any level contains a token, secret or credential value — but a debug log does reveal which accounts and files you touched, so read it before you attach it to a bug report.

Only mureo's own log records go to this file. Third-party libraries (the Google Ads SDK among them) keep whatever logging your environment gives them, so raising `MUREO_LOG_LEVEL` cannot make an SDK dump request payloads into it.

> **macOS only:** `~/.mureo/configure.log` and `~/.mureo/configure.err` (note: no `logs/`) are a different thing — the raw stdout/stderr of the LaunchAgent, captured by launchd itself. They hold startup lines and any traceback that escaped the server. The rotated `logs/configure.log` above is the application log and is the one to read first.

## Maintenance Commands

`mureo upgrade` upgrades mureo and its plugins inside the current (pipx) venv in one pip invocation — `pipx upgrade mureo` only touches the primary package, leaving same-venv plugins behind.

```bash
mureo upgrade              # upgrade mureo itself
mureo upgrade --all        # upgrade mureo + every installed `mureo-*` plugin
mureo upgrade --dry-run    # print the pip command without running it
mureo upgrade --no-refresh # upgrade the package(s) only; skip the post-upgrade refresh
```

After a successful upgrade, mureo runs a **post-upgrade refresh** so the new code actually takes effect: it re-deploys the bundled skills into `~/.claude/skills/` and any plugin-provided native slash skills (the `mureo.native_skills` entry-point group, #439) into both `~/.claude/skills/` and `~/.codex/skills/`, upgrades the installed credential-guard hooks, and restarts the always-on service. The refresh only touches a host that already has a skills directory, so it never force-installs skills you removed on purpose. Pass `--no-refresh` to upgrade the package(s) alone.

The configure UI's **About mureo** tab surfaces the same capability for GUI users: it shows installed versions, checks the index for newer mureo / plugin releases in the background, and offers a one-click "update all" button.

## Rollback Commands

`mureo rollback` lets an operator inspect reversible actions recorded in `STATE.json`. The commands are read-only — executing a rollback still goes through the MCP dispatcher so it re-enters the same policy gate as forward actions.

```bash
# List every state-changing action log entry with the planner's verdict.
mureo rollback list

# Limit to one platform.
mureo rollback list --platform google_ads

# Inspect a specific entry (index as shown by `list`).
mureo rollback show 3

# Point at a non-default STATE.json location.
mureo rollback list --state-file /path/to/STATE.json
```

`list` output:

```
  #  timestamp            platform    status           action
------------------------------------------------------------------------
  0  2026-04-15T10:00:00  google_ads  supported        update_budget
  2  2026-04-13T12:00:00  meta_ads    partial       *  update_status
  3  2026-04-12T08:00:00  google_ads  not_supported    update_budget
```

`*` marks entries with caveats (e.g. "spend during pause is not refundable"); run `mureo rollback show <#>` for the full detail.

`show` emits JSON for scripting:

```json
{
  "index": 0,
  "source_timestamp": "2026-04-15T10:00:00",
  "source_action": "update_budget",
  "platform": "google_ads",
  "status": "supported",
  "operation": "google_ads_budget_update",
  "params": {"budget_id": "222", "amount_micros": 10000000000},
  "caveats": [],
  "notes": ""
}
```

A rollback entry only appears when the agent wrote a `reversible_params` hint at the time of the original action. Operations outside the planner's allow-list, or hints that smuggle unexpected parameter keys, are rejected at plan time — see [architecture.md](architecture.md#defense-in-depth-for-ai-agents) for the threat model.

### Applying a rollback

Execution is not a CLI command — it is the `rollback_apply` MCP tool. The CLI is intentionally read-only; applying a rollback from the CLI would bypass the authentication, rate-limiting, and input-validation gate that every forward action passes through. To apply a rollback, ask the agent to call `rollback_apply` with the index shown by `mureo rollback list`:

```
You: "Roll back action #0."
Agent: rollback_plan_get → previews the reversal.
Agent: rollback_apply({index: 0, confirm: true}) → dispatches.
```

`confirm` must be the literal boolean `true` (truthy non-booleans are refused). On success the executor appends a new log entry tagged `rollback_of=<index>`; a second apply of the same index is refused. `state_file` resolves strictly inside the MCP server's current working directory — `..`-traversal and symlink escape are refused so an attacker-crafted `STATE.json` elsewhere on disk cannot be used as the reversal source.

### Reverting a whole bulk change

A bulk pass wrapped in a batch (`mureo_batch_begin` / `mureo_batch_end`) is planned as one unit by `rollback_plan_get` with `batch_id` instead of `index` — it reports every member, overall and per-platform coverage (`full` / `partial` / `none`), and the reason each member it cannot reverse. That surface is **MCP-only**: `mureo rollback list` / `show` still work entry by entry, and neither the batch tools nor batch planning has a CLI command today. Ask the agent for the batch plan before applying anything; a batch where only some members can be restored will say so there.

## Repair Commands

`mureo repair` fixes the STATE.json problems mureo can fix **without guessing**. Today that is one: a `platforms` entry filed under a key that names no advertising platform at all — an agent writing LOGLY snapshots under `logly_ads` when the bridge's provider is `logly_ads_context`, for instance. Both keys then carry the same ad account, and the dashboard reports the spend, conversions and CPA as double-counted.

A duplicate whose two keys **both** name real platforms is reported and handed back to you: which of two sets of partial figures is true is a question about money that only you can answer, and mureo will not answer it for you.

```bash
# Show what mureo would do. Changes nothing — this is the default.
mureo repair platform-key

# Make the change. Asks for confirmation first.
mureo repair platform-key --apply

# Skip the prompt (scripts, or when you have already read the dry run).
mureo repair platform-key --apply --yes

# Narrow it to one key, or point at another workspace's STATE.json.
mureo repair platform-key --key logly_ads
mureo repair platform-key --state-file /path/to/STATE.json

# Survey every client on this machine instead of one workspace.
mureo repair platform-key --all
mureo repair platform-key --all --apply
```

The dry run names the key, the ad account, how many campaigns the entry carries, whether it holds a `totals` rollup and which windows it covers with each window's fetch time — for the unresolvable entry **and** for the entry the same ad account is stored under — then states exactly what would change:

```
  logly_ads — mureo cannot resolve this key.
    It is not one of mureo's own platform names, no plugin installed here
    registers it, and it is not a plugin:<distribution>:<provider> key. So no
    platform's data can belong to it.

    This entry holds:
      ad account:  1234567890
      campaigns:   1
      totals:      stored, covering LAST_30_DAYS, fetched 2026-08-01T03:00:00+00:00
      periods:     LAST_30_DAYS (fetched 2026-08-01T03:00:00+00:00)

    The same ad account is also stored under a key mureo CAN resolve, which
    holds:
      logly_ads_context
        campaigns:   1
        totals:      stored, covering LAST_30_DAYS, fetched 2026-08-12T03:00:00+00:00
        periods:     none stored

    Would change: the whole logly_ads entry is removed from STATE.json.
    Would NOT change: no figures are added together, moved or edited, and every
    other platform entry is left exactly as it is.
    Afterwards: the next sync refills logly_ads_context from the platform itself.
```

Nothing is ever merged or summed: two partial entries added together over-count exactly as much as dropping one under-counts. The unresolvable entry is **removed**, and the next sync refills the key the account is really stored under.

`--apply` backs STATE.json up first, timestamped, and prints the command that restores it:

```
Backed up STATE.json to /path/to/STATE.json.bak.1786664790525084000
If this turns out wrong, put it back with:
  cp "/path/to/STATE.json.bak.1786664790525084000" "/path/to/STATE.json"
```

That backup is the undo. The repair is not recorded in `action_log`: that log records changes made to an *ad platform* and feeds the rollback planner, and a local-file edit has neither a platform operation to name nor one to reverse. With no TTY — an AI agent's shell, a CI runner — `--apply` declines rather than proceeding, so nothing destructive happens where the question could not be asked.

The same finding is flagged on the configure UI's Reports cards, which now name this command.

### Every client at once: `--all`

A bad key is rarely one directory's problem. It is written by an agent, and an agent that ran against every client on the machine wrote it into every client's STATE.json. `--all` sweeps them all and **leads with the summary**, so you can see how many of how many need work without scrolling:

```
=== mureo repair platform-key --all ===

Surveyed 6 clients.

  Need repair (2 of 6):
    acme (Acme Co) — logly_ads
    beta (Beta Ltd) — logly_ads

  Need your decision (1 of 6):
    epsilon (Epsilon GmbH) [archived] — one ad account under two real platform keys (see below)

  Clean (2 of 6):
    gamma (Gamma KK)
    zeta (Zeta SA) — no STATE.json yet

  Could not be read (1 of 6):
    delta (Delta Inc) — Failed to parse JSON in STATE.json: /clients/delta/STATE.json
```

The per-client detail follows, in the same shape as the single-workspace run, for every client that has a finding. Then:

- **Dry run is still the default.** `--all` on its own changes nothing.
- **`Need your decision` is its own group, not a footnote under `Clean`.** An ad account stored under two keys that *both* name real platforms is still double-counted; mureo simply will not choose which entry to drop, because the two usually hold different partial figures. It is not a repair this command can make, and it is not clean either — so it is counted separately rather than qualified after an em dash in a line you would skim.
- **`--all --apply` asks once**, with the whole list in view — not once per client. A prompt per client teaches you to hold down `y`, which is the opposite of what a confirmation is for. Every repaired client is still backed up individually, and the `cp` that restores it is printed per client.
- **One client failing does not stop the sweep.** An unparseable STATE.json, a lock it cannot take, a permission error — that client is named in the summary and under `Could not be read`, the rest are repaired, and the command exits non-zero so a script notices. A *finding* is not a failure: a dry run that reports work to do exits `0`.
- **`--all` and `--state-file` are refused together.** One says "every client", the other says "this one file".
- **`--all --key <key>` is allowed** and narrows the sweep to that key across every client — the reported incident used one invented key everywhere. A client that does not carry it is simply clean.

Which clients exist comes from the same optional `StateStore` capabilities the configure UI's Reports tab reads (`list_clients()` / `state_store_for_client(slug)` — see [`docs/plugin-authoring.md`](plugin-authoring.md)). A store that declares neither — every OSS install — yields exactly one client, the active workspace, and `--all` reports `Surveyed 1 client.` and repairs it. That count is worth reading: if you run twelve clients and are told one, the client registry is what is broken, not the sweep.

**Archived clients are swept too**, and labelled `[archived]`. Archiving means "stop collecting this client's figures" — a decision about what to fetch next, not a statement that what is already stored is correct. Skipping them would leave the bad key in place to reappear the day the client is restored, on a machine whose operator has no reason to run the sweep again.

## BYOD Commands (Bring Your Own Data)

Analyse your ad-account data locally without OAuth or a developer token. The importer accepts a single XLSX produced by either the mureo Google Ads Script (`scripts/sheet-template/google-ads-script.js`) or a Meta Ads Manager Saved Report. Activated automatically when `~/.mureo/byod/manifest.json` registers a platform — no `--byod` flag exists. Adapter dispatch is by workbook header signature, so no `--google-ads / --meta-ads` flags on `import` are needed. See [`docs/byod.md`](byod.md) for the full walkthrough.

| Command | Description |
|---|---|
| `mureo byod import <file>.xlsx` | Import a Sheet bundle. Aborts if any platform present in the workbook is already imported. |
| `mureo byod import <file>.xlsx --replace` | Overwrite existing BYOD data for any platform present in the bundle. |
| `mureo byod status` | Show per-platform mode (BYOD / Live API / not configured); warns about stale entries from older mureo versions. |
| `mureo byod remove --google-ads` / `--meta-ads` | Remove BYOD data for one platform. |
| `mureo byod clear` | Wipe `~/.mureo/byod/` (prompts for confirmation). |
| `mureo byod clear --yes` | Skip the confirmation prompt. |

### Per-platform routing

The MCP server checks each platform independently at every tool dispatch. With `google_ads` imported but `meta_ads` not, a single `/daily-check` call uses the BYOD CSVs for Google Ads and the live API for Meta Ads. `mureo byod status` shows the active mix.

GA4 and Search Console are **not** part of the BYOD bundle pipeline — they remain on the Live API OAuth path.

### Read-only guarantee

BYOD mode rejects every mutation tool. Methods whose name starts with `create_`, `update_`, `delete_`, `remove_`, `add_`, `send_`, `upload_`, `pause_`, `resume_`, `enable_`, `disable_`, `apply_`, `publish_`, `submit_`, `attach_`, `detach_`, `approve_`, `reject_`, `cancel_`, `set_`, or `patch_` return:

```json
{
  "status": "skipped_in_byod_readonly",
  "operation": "<name>",
  "note": "BYOD mode is analysis-only. This call would have written to a real ad account."
}
```

The agent can analyse and recommend, but never writes.

## Output Format

Authentication check commands output JSON to stdout:

```bash
mureo auth check-google | jq .
```

```json
{
  "developer_token": "***************abcd",
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "***************wxyz",
  "refresh_token": "***************efgh",
  "login_customer_id": "1234567890"
}
```

Secrets are masked, showing only the last 4 characters.

## Ad Platform Operations

Ad platform operations (listing campaigns, creating ads, analyzing performance, etc.) are available through **MCP tools**, not the CLI. AI agents (Claude Code, Cursor, Codex, Gemini) call these tools directly.

See [mcp-server.md](mcp-server.md) for the full tool reference.
