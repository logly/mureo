# Insight federation — `mureo_consult_advisor`

> 日本語版: [insight-federation.ja.md](insight-federation.ja.md)

mureo's `mureo_consult_advisor` MCP tool lets diagnostic agents query
external **advisor servers** for practitioner know-how during a
workflow. The advisor side runs a vector search over its own corpus
and returns the top-k matching snippets; the operator-side Claude
reasons over them. No LLM lives on the advisor server — it is a
retrieval endpoint, not a generation endpoint.

## Why this design

Returning the full corpus per call (the v0.9.18-era "text-return"
proposal in [#163](https://github.com/logly/mureo/issues/163)) leaked
the advisor's know-how on every consultation. The retrieval pattern
adopted in v0.9.19 keeps the corpus private and only surfaces the
fragments the query matches.

- The advisor server holds the corpus, embedder, and vector store.
- mureo sends a query text built from the operator's question plus
  local campaign context.
- The server embeds the query, searches its vector store, and
  returns the top-k fragments with similarity scores.
- The operator-side Claude weighs and applies the fragments.

## Operator setup

Create `~/.mureo/insight_sources.json`:

```json
{
  "sources": [
    {
      "name": "acme",
      "transport": "stdio",
      "command": "acme-advisor-mcp",
      "tool": "vector_search",
      "top_k": 5
    },
    {
      "name": "benchmarks",
      "transport": "http",
      "url": "https://benchmarks.example/mcp",
      "headers": {"Authorization": "Bearer PASTE_TOKEN_LITERAL_HERE"},
      "tool": "vector_search",
      "top_k": 3,
      "timeout_sec": 8
    }
  ]
}
```

Supported transports:

| transport | mureo helper                    | required fields            |
|-----------|---------------------------------|----------------------------|
| `stdio`   | `mcp.client.stdio.stdio_client` | `command` (+ optional `args`, `env`) |
| `sse`     | `mcp.client.sse.sse_client`     | `url` (+ optional `headers`)         |
| `http`    | `mcp.client.streamable_http.streamablehttp_client` | `url` (+ optional `headers`) |

Per-source isolation: a slow / crashed / malformed advisor never
blocks the others. `timeout_sec` (default 10s) caps each call;
failures collapse to "no fragments from that source".

**Secrets are passed verbatim** — mureo does NOT expand `${VAR}`-style
environment-variable references inside `env` or `headers`. Paste the
literal value, and `chmod 600 ~/.mureo/insight_sources.json` if the
file carries credentials.

**Empty `env: {}` means a sealed subprocess**, not "inherit parent
env". An advisor configured with `"env": {}` will NOT see your
operator's `OPENAI_API_KEY` / cloud credentials / shell history; the
parent environment leaks only when `env` is omitted entirely. This
matches the principle of least privilege but may surprise operators
who expect shell-script-style inheritance.

## Calling the tool

`mureo_consult_advisor` takes two arguments:

- `question` (required) — the specific question to research. Concrete
  beats generic: "why is CPA up 30% on Brand-Search this week?" works
  much better than "tips for Google Ads".
- `campaign_id` (optional) — when provided, mureo attaches the
  campaign's name / status / daily budget plus the most recent
  action-log entries to the query, so the advisor's vector search
  can match against richer context.

The response is a single Markdown block, one section per advisor
that returned hits:

```
## acme
- (similarity 0.92) Use micro-conversions when CV volume is sparse...
- (similarity 0.81) Brand search CPA inflation typically tracks...

---

## benchmarks
- (similarity 0.78) Median CPA for B2B Search in JP is ~4,200 JPY...
```

If no sources are configured, the tool returns a guidance string
pointing the operator at this doc. If every source returned nothing,
the tool says so explicitly so the agent does not silently fall back.

## Writing an advisor server

Your server only needs to expose **one** tool that takes
`{query, top_k}` and returns a JSON list of `{text, similarity, ...}`
fragments. Extra fields (`tags`, `case_id`, source URLs, …) are
forwarded verbatim to the agent.

A 30-line example using FastMCP + sentence-transformers + ChromaDB:

```python
import json
from fastmcp import FastMCP
from sentence_transformers import SentenceTransformer
import chromadb

embedder = SentenceTransformer("intfloat/multilingual-e5-base")
collection = chromadb.PersistentClient(path="./vectors").get_or_create_collection("kb")

server = FastMCP("acme-advisor")

@server.tool()
def vector_search(query: str, top_k: int = 5) -> str:
    query_vec = embedder.encode([f"query: {query}"]).tolist()[0]
    hits = collection.query(query_embeddings=[query_vec], n_results=top_k)
    fragments = [
        {
            "text": doc,
            "similarity": float(1 - dist),
            **(meta or {}),
        }
        for doc, dist, meta in zip(
            hits["documents"][0],
            hits["distances"][0],
            hits["metadatas"][0] or [{}] * len(hits["documents"][0]),
        )
    ]
    return json.dumps(fragments)

if __name__ == "__main__":
    server.run()
```

The server does not need an LLM. Embedder + vector store + a single
tool is the whole contract.

## Server-side security and abuse-control spec

mureo is a **canonical, well-behaved client**: it caps `top_k` at 50,
truncates each response at 1 MiB, drops fragment text past 4 KiB, and
fans calls out concurrently per advisor. Those caps protect the
**operator's** machine. They do NOT protect **your corpus**. mureo
runs on the operator's machine — a determined operator (or an agent
compromised by prompt injection on that machine) can bypass any
client-side limit. **All abuse control belongs on the server.**

If your corpus has any value, treat every `vector_search` call as
untrusted and implement the controls below.

### Authentication (REQUIRED if the corpus is non-public)

mureo forwards the `env` / `headers` fields verbatim, so any
bearer-token / API-key / mTLS scheme works:

- **stdio**: read a credential from the subprocess env on startup.
  Operators put their key in `~/.mureo/insight_sources.json` under
  `"env": {"ACME_API_KEY": "..."}`.
- **sse / http**: read `Authorization` from request headers.
  Operators put `"headers": {"Authorization": "Bearer ..."}` in the
  same file. mureo does NOT expand `${VAR}` — operators paste literal
  tokens.

Reject unauthenticated calls with an MCP `isError` response. Rotate
keys on a documented cadence. Bind keys to a single tenant / quota
bucket so a leaked key affects exactly one client.

### Per-key rate limiting (REQUIRED)

The retrieval pattern returns N fragments per call. An attacker can
issue many calls with different queries to map your corpus over
time. Enforce a sliding-window rate limit per API key:

- A defensible default: **60 calls / minute, 1,000 calls / day** per
  key. Tune to your corpus value.
- Return HTTP 429 (or MCP `isError` with a clear message) when
  exceeded — mureo will treat that source as empty for the call and
  log a WARNING.

### Per-key fragment quota (RECOMMENDED)

A higher-fidelity defence than call-count limiting: track the number
of **unique fragment IDs** a key has been shown over a rolling
window. Once a key has seen, say, 5–10% of your corpus, throttle or
require manual review. This blunts the "scan with many slightly
different queries" attack the call-rate limit alone misses.

### Query logging and anomaly detection (RECOMMENDED)

Log every call with: timestamp, API key, query text length (or a
salted hash of the query), top_k requested, fragment IDs returned,
client IP for HTTP / SSE. Watch for:

- Queries that are very short or very generic (`"a"`, `"the"`,
  empty embeddings) — likely corpus-scanning probes.
- A single key hitting different cohorts of the corpus rapidly.
- Concurrent requests across many sessions tied to one key.

A simple cron over the log catches most abuse without ML.

### Response shaping (RECOMMENDED)

- **Cap `top_k` server-side too.** mureo enforces `top_k <= 50` but a
  hand-written or malicious MCP client will not. Clamp on the server.
- **Sanitise text on the way out.** Strip credentials, PII, internal
  URLs, and section markers an LLM might mis-attribute. mureo
  defangs `##` / `---` at render time but a server that re-uses your
  corpus elsewhere should also sanitise at the source.
- **Truncate per-fragment text** so a single fragment cannot leak a
  full document.
- **Round similarity scores** (e.g. to 2 decimals). Raw distances can
  fingerprint your embedding model and ANN parameters.

### Corpus partitioning (RECOMMENDED for multi-tenant servers)

If your server backs multiple tenants, partition the vector store by
tenant and bind each API key to exactly one partition. A single
search must not be able to reach across partitions. This is the
single most effective defence against compromise-of-one-key →
disclosure-of-all-tenants.

### Operational hygiene

- Run the server in a sandbox / container with the minimum env it
  needs — operators can pass an explicit `"env": {}` to seal your
  subprocess of their secrets, but you should still treat the
  process as untrusted.
- Pin the MCP SDK + vector-store client versions.
- Update embedder weights via a controlled rollout — flipping the
  embedder mid-flight breaks similarity semantics for clients that
  cache.

### What mureo guarantees

| concern                                  | mureo guarantee                                |
|------------------------------------------|------------------------------------------------|
| Forwards `env` / `headers` verbatim      | Yes (no `${VAR}` expansion)                    |
| Caps per-call `top_k`                    | `<= 50` (validated at config load)             |
| Caps per-call response bytes             | `1 MiB` raw JSON                               |
| Caps per-fragment text                   | `4 KiB`                                        |
| Caps total fragments parsed              | `50`                                           |
| Per-source timeout                       | `timeout_sec` (`<= 120s`, default `10s`)       |
| Concurrent fan-out across advisors       | Yes (`asyncio.gather`)                         |
| Server-side rate limiting                | **No** — your responsibility                   |
| Server-side authentication               | **No** — your responsibility                   |
| Server-side audit logging                | **No** — your responsibility                   |

## Compared with the local `/learn` tool

| use case | tool |
|---|---|
| Surface the operator's own `/learn` history | `mureo_learning_insights_get` |
| Consult shared external know-how | `mureo_consult_advisor` |

Both tools coexist. v0.9.18's `mureo_learning_insights_get` is
unchanged; v0.9.19's `mureo_consult_advisor` adds the external
surface alongside it.
