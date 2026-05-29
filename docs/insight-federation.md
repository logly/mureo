# Insight federation: serving practitioner know-how to mureo via MCP

`mureo_learning_insights_get` aggregates insights from two layers:

1. **Local** — the operator's own `/learn` history saved by
   `mureo learn add` (default location:
   `~/.claude/skills/_mureo-pro-diagnosis/SKILL.md`).
2. **External MCP servers** — third-party servers that publish
   know-how, configured in `~/.mureo/insight_sources.json`.

This guide covers the external layer.

## Why federation?

- **Consulting companies** can publish their accumulated marketing
  know-how as an MCP server; clients install once and every mureo
  diagnostic flow benefits.
- **Industry trade groups** can serve benchmark deltas (CPA,
  conversion-rate baselines per vertical) so the agent calibrates
  recommendations against the cohort.
- **OSS communities** can run a shared insights MCP that aggregates
  what operators have collectively learned.
- **Enterprise teams** can wrap an internal wiki / Notion / SharePoint
  as a small MCP server so the agent gets cross-team learnings.

The MCP server can be written in **any language** — Python,
TypeScript, Go, Rust — as long as it implements the MCP protocol.

## Config file

Path: `~/.mureo/insight_sources.json`.

Schema:

```jsonc
{
  "sources": [
    {
      "name": "acme-consulting",        // section heading in the merged output
      "transport": "stdio",              // "stdio" | "sse" | "http"
      "tool": "insights_get",            // the remote tool name to call
      "command": "acme-insights-mcp",    // stdio only: executable
      "args": ["--scope", "google-ads"], // stdio only: extra CLI args
      "env": {"ACME_API_KEY": "..."},    // stdio only: env vars merged into subprocess
      "url": "https://...",              // sse / http only
      "headers": {"Authorization": "Bearer ..."}, // sse / http only
      "timeout_sec": 10                  // optional; default 10
    }
  ]
}
```

Required fields per transport:

| transport | required fields            |
|-----------|----------------------------|
| `stdio`   | `name`, `tool`, `command`  |
| `sse`     | `name`, `tool`, `url`      |
| `http`    | `name`, `tool`, `url`      |

The MCP server should expose a tool (any name, declared via `tool`)
that takes no arguments and returns Markdown text via `TextContent`
blocks. The first text block becomes the section under
`## <name>` in the merged response; multiple text blocks are
concatenated with a single blank line between them.

## Per-source error isolation

mureo treats every external source as advisory. A failure mode in
one source NEVER blocks the diagnostic flow:

| failure                              | mureo's response                                  |
|--------------------------------------|---------------------------------------------------|
| config file missing / malformed JSON | empty config + WARNING log; local insights only   |
| one entry has wrong shape            | skip that entry + WARNING; siblings continue      |
| duplicate `name` across entries      | keep the first; skip subsequent + WARNING         |
| source exceeds `timeout_sec`         | drop the source + WARNING; siblings continue      |
| network / subprocess error           | drop the source + WARNING; siblings continue      |
| `tools/call` returns `isError`       | drop the source + WARNING; siblings continue      |
| response has no text content         | drop the source + WARNING; siblings continue      |

Operators can grep the mureo MCP server log for `insight source` to
diagnose problems.

## Performance

Sources fan out via `asyncio.gather`, so total wall-time is bounded
by the slowest source, not the sum. Default per-source timeout is
10 seconds — long enough for a slow remote MCP, short enough that a
dead server does not stall the diagnostic UX.

There is no caching in v0.9.19. Every call to
`mureo_learning_insights_get` re-fetches every external source. If
your insight set is large and stable, consider serving an HTTP MCP
with appropriate cache headers (mureo respects them).

## Writing a federation-friendly MCP server

The minimum contract:

1. Expose a single tool that takes no arguments.
2. Return `CallToolResult` with `isError = False` and at least one
   `TextContent` block whose `text` is Markdown.
3. Respond within `timeout_sec` (default 10s).

The Markdown can be anything. Convention: use `###` headings for
individual insights and a brief `**Why:**` / `**When to apply:**`
template under each, mirroring the `/learn` skill's local format
([learn skill template](../skills/learn/SKILL.md)).

Example (Python, minimal):

```python
from mcp.server.fastmcp import FastMCP

app = FastMCP("acme-insights")

@app.tool()
def insights_get() -> str:
    return """\
### Always disable underperforming RSAs after 14 days at <2 conversions
**Why:** Asset combination volume below this threshold doesn't recover.
**When to apply:** Any RSA that has accumulated 14 days at <2 conversions.

### Cap broad-match keyword bids at 70% of phrase-match bids
**Why:** Broad-match competes with phrase / exact on the same query —
keeping broad cheaper prevents cannibalisation.
**When to apply:** Any campaign mixing broad and phrase keywords.
"""

if __name__ == "__main__":
    app.run()  # stdio by default
```

Register it on the operator's machine:

```json
{
  "sources": [
    {
      "name": "acme-insights",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "acme_insights"],
      "tool": "insights_get"
    }
  ]
}
```

Next time the operator runs `/daily-check`, `/rescue`, or any other
diagnostic skill, the Acme insights appear under
`## acme-insights` in the aggregated response.

## Security model

mureo treats every external source as **untrusted advisory content**.
The text is forwarded to the agent as Markdown but never executed.
No `tools/call` from the external server reaches mureo's own tool
surface; the federation is one-way.

For stdio sources, `env` keys are passed to the subprocess (so an
`ACME_API_KEY` can be supplied without bleeding into the operator's
shell history). The subprocess's stdout/stderr is captured by the
MCP transport and not surfaced as part of the insights.

For sse / http sources, headers are forwarded as supplied; mureo does
not refresh tokens automatically. If a source needs an auth refresh
loop, wrap it in a small local MCP proxy.

**Secret hygiene**: if the config carries bearer tokens or API keys
in `headers` / `env`, `chmod 600 ~/.mureo/insight_sources.json` so
the file is not world-readable. mureo does not enforce this — it is
on the operator.

## Roadmap

- **Caching with TTL** — short-circuit identical fetches within a
  configurable window
- **Insight scoring / dedupe** — merge similar insights from
  multiple sources
- **Per-account / per-workspace filtering** — allow sources to scope
  themselves to specific platforms or accounts

None of these are blocking the v0.9.19 release; they will land as
needed based on operator feedback.
