# Contributing Guide

Thank you for your interest in contributing to mureo. This guide covers the development setup, coding standards, and PR workflow.

## Development Setup

### Prerequisites

- Python 3.10 or later
- Git
- Node.js 20 or later (`node:test` was experimental before 20) — **only**
  to run the browser-asset tests
  (`node --test tests/js/*.test.js`). mureo ships no JavaScript
  dependencies, there is no `package.json` and no build step; Node is used
  purely as a test runner for the DOM-free logic in
  `mureo/_data/web/reports_*.js`. Skip it if you are not touching the
  configure UI — CI runs it either way.

### Clone and Install

```bash
git clone https://github.com/logly/mureo.git
cd mureo

# Install with dev tools
pip install -e ".[dev]"
```

### Verify Installation

```bash
# Run the test suite
pytest tests/ -v

# Check types
mypy mureo/

# Check linting
ruff check mureo/
```

## Running Tests

### Full Test Suite

```bash
pytest tests/ -v
```

Run the suite in a clean virtualenv that has mureo and its `[dev]` extra and
nothing else. The root `tests/conftest.py` points the home directory at a
throwaway temp dir and hides any installed `mureo.runtime_context_factory`
entry point for the duration of every test, so a test that exercises a
credentials writer can never reach your real `~/.mureo/credentials.json` — nor
a plugin's shared credential store, which the write-path resolver would
otherwise prefer (#739). Keeping the venv clean keeps whatever else is
installed out of the results as well.

### With Coverage

```bash
pytest --cov=mureo --cov-report=term-missing
```

**Minimum coverage: 80%.** The CI pipeline will fail if coverage drops below this threshold (configured in `pyproject.toml`). Coverage must stay at or above 80%.

### Test Markers

Tests are categorized with pytest markers:

```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration
```

### MCP Server Startup Budget

`tests/test_mcp_startup_budget.py` pins what `import mureo.mcp.server` costs,
because an MCP client gives the server a fixed window to answer `initialize`
(30,000 ms by default in Claude Code) and a server that misses it contributes
no tools at all (#807). Two kinds of check live there:

- **Deterministic**, and the one that matters: no platform SDK, API client or
  transport stack may be asked for on mureo's own import path. It does not
  depend on how fast the machine is. A `sys.meta_path` finder records which
  module first asked for each forbidden module, and the test fails if any of
  them is mureo's — so what a third-party plugin imports for itself is charged
  to the plugin, and the check keeps its teeth in an environment that has
  plugins installed. One case is set up rather than waited for: a synthetic
  `mureo.runtime_context_factory` plugin, which is the configuration #807 was
  reported from and which CI would otherwise never exercise.
- A **CPU backstop**, for a new heavy dependency the module-name check cannot
  name. The child reports `time.process_time` and the parent compares it to a
  6 s ceiling, against an achieved cost of roughly 1.1 s. Not wall clock: the
  same import measured 7–9 s warm and 19 s cold on a loaded machine while its
  CPU time stayed inside a tenth of a second, which made the old wall-clock
  version a load meter.

```bash
# Raise the CPU ceiling for a slow machine or a loaded CI runner.
MUREO_MCP_IMPORT_BUDGET_SECONDS=20 pytest tests/test_mcp_startup_budget.py
```

Raise it for a slow machine, never to accept a regression: if the import got
slower, `python -X importtime -c 'import mureo.mcp.server'` names what was
added.

`tests/test_mcp_tool_validators.py` is the other half of #807: each tool's
`inputSchema` validator is compiled on that tool's first call, and these tests
hold the guarantee that deferring it does not weaken — a tool is still
validated on the call that compiles it, and an unusable schema still costs one
tool its validation and nothing else.

`tests/test_platform_submodule_imports.py` imports each submodule of
`mureo.google_ads` / `mureo.meta_ads` **first**, in a child interpreter of its
own, so the lazy `__init__` cannot hide an import cycle that only a single-file
`pytest` run would hit.

### Exhaustive (`slow`) lanes

A few checks are real but cost minutes of child interpreters: the exhaustive
submodule sweep above, the whole-product credential-guard enumeration, the
plugin strict-mode startup, and the per-package submodule-attribute sweep. They
are marked `slow` AND gated on an environment variable, so a plain `pytest`
skips them visibly (as skips in the summary, not as a silent deselect) and
running them has to be asked for by name:

```bash
MUREO_RUN_EXHAUSTIVE_TESTS=1 pytest -m slow
```

The `test-slow` CI job runs exactly that on one Python version. `pytest -m slow`
without the variable is a no-op by design — the marker alone says which tests
they are, the variable says you meant it.

One of them is left out of that job: `tests/test_credential_guard_product.py`,
the whole-product credential-guard enumeration, measured 1 h 56 m on a developer
machine (against 77 s for all the others together), which no per-PR job can
carry. The `credential-guard-sweep.yml` workflow runs it nightly instead, and can
be started by hand from the Actions tab (`workflow_dispatch`) — do that after
changing the guard rather than waiting for the night. A sweep that fails, times
out or is cancelled opens an issue labelled `guard-sweep`, or comments on the one
already open, with the job status (`failure` or `cancelled`) and a link to the
run; the run's `sweep.log` artifact holds the full output. To run it locally:

```bash
MUREO_RUN_EXHAUSTIVE_TESTS=1 pytest tests/test_credential_guard_product.py -m slow
```

### Browser Assets

The configure UI in `mureo/_data/web/` ships as plain `<script>`-loaded
files — no bundler, no module system, no build step. Most of it is guarded
by the `tests/test_web_assets_*.py` pins, which grep the shipped asset for
the names, strings and selectors a feature depends on.

Grepping cannot catch an inverted condition, so the DOM-free parts of the
Reports dashboard live in their own assets and are executed by Node's
built-in test runner:

```bash
node --test tests/js/*.test.js
```

| Asset | Global | What is in it |
| --- | --- | --- |
| `reports_logic.js` | `MUREO_REPORTS_LOGIC` | KPI withholding, freshness aggregation, conflict routing |
| `reports_format.js` | `MUREO_REPORTS_FORMAT` | Flag labels and severities, param detail, numbers, period labels |
| `reports_order.js` | `MUREO_REPORTS_ORDER` | The Reports index card order and how it is persisted |

No install step: no `package.json`, no dependencies, no lockfile. Each
module publishes exactly one global for the browser and carries an inert
`module.exports` tail so Node can require the exact bytes the browser is
served. A new module needs three things: an entry in `_STATIC_ALLOWLIST`
(`mureo/web/handlers.py`), a `<script>` tag ahead of `dashboard.js` in
`app.html`, and a row in the table at the top of
`tests/js/browser_contract.test.js` — which then asserts the same shipping
contract for it as for every other module.

When you add DOM-free logic to the configure UI, put it in one of these and
test it; rendering stays in `dashboard.js` and stays pinned statically.

### Test Framework

- **pytest** with **pytest-asyncio** (async tests auto-detected)
- **pytest-mock** for mocking
- All API calls must be mocked in tests -- no live API calls in CI

### Writing Tests

Place tests in `tests/` mirroring the source structure:

```
mureo/google_ads/client.py  →  tests/test_google_ads/test_client.py
mureo/context/strategy.py   →  tests/test_context/test_strategy.py
```

Example test:

```python
import pytest
from mureo.context import parse_strategy, StrategyEntry

@pytest.mark.unit
def test_parse_strategy_persona():
    text = "# Strategy\n\n## Persona\nB2B SaaS buyers.\n"
    entries = parse_strategy(text)
    assert len(entries) == 1
    assert entries[0].context_type == "persona"
    assert "B2B" in entries[0].content
```

## Coding Standards

### PEP 8

Follow [PEP 8](https://peps.python.org/pep-0008/) conventions. Formatting is enforced automatically.

### Type Annotations

**Required on all function signatures.** mureo uses `mypy --strict`.

```python
# Good
def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    ...

# Bad (missing annotations)
def get_campaign(doc, campaign_id):
    ...
```

Use `from __future__ import annotations` at the top of every module for PEP 604 union syntax (`X | Y`).

### Frozen Dataclasses

All data models must use `frozen=True`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MyModel:
    name: str
    value: int
```

For fields containing mutable types (`dict`, `list`), use defensive copies in `__post_init__` or convert to immutable types (`tuple` instead of `list`).

### Immutability

Never mutate existing objects. Create new instances instead:

```python
# Good
new_entries = [*entries, new_entry]

# Bad
entries.append(new_entry)
```

### File Size

- Target: 200-400 lines per file
- Maximum: 800 lines
- If a file grows beyond this, extract logic into separate modules (see the Mixin pattern used in `google_ads/` and `meta_ads/`)

### Formatting and Linting

```bash
# Format code
black mureo/ tests/

# Fix auto-fixable lint issues
ruff check --fix mureo/ tests/

# Type check
mypy mureo/
```

Configuration is in `pyproject.toml`:

- **black**: line-length 88, target Python 3.10
- **ruff**: select rules E, F, I, N, W, UP, B, A, SIM, TCH
- **mypy**: strict mode

### Error Handling

- Handle errors explicitly. Never silently swallow exceptions.
- API client methods should raise `RuntimeError` with user-facing messages.
- Log technical details with the `logging` module, not `print()`.

### No Hardcoded Secrets

Never commit credentials, API keys, or tokens. Use environment variables or `~/.mureo/credentials.json`.

### Repository Language

The repository is English: code comments, docstrings, docs, skills, tests, commit messages, issues and PRs. Japanese belongs in two places only — the `*.ja.md` translations (`README.ja.md`, `docs/*.ja.md`) and string literals that are Japanese data, such as ad-text samples, the Japanese column headers a report parser matches on, a validator's character classes, or the `ja` entries of a per-locale label table. When a markdown line outside a code fence has to carry Japanese on purpose (a language-switch link, a literal UI string, an example of operator input), end that line with `<!-- ja-literal -->` and give the English meaning beside it. The checker does not look at identifiers, and Japanese test function names remain (about 350 in 8 test files; tracked separately). The one exemption is the `description:` key in a `SKILL.md` frontmatter: it carries the Japanese trigger phrases a skill fires on when an operator asks in Japanese, and `tests/test_skill_ja_triggers.py` requires them (#396). `python scripts/check_english_only.py` enforces this in CI (Python comments and docstrings, markdown prose, CSS/HTML comments under `mureo/`, and JavaScript comments under `mureo/` and `tests/js/` — `/* */` blocks and `//` comments that start a line; a `//` comment after code on the same line is not checked, so keep those English yourself); `--list` prints the files it scans.

## Pull Request Guidelines

### Before Submitting

1. **Tests pass**: `pytest tests/ -v`
2. **Coverage >= 80%**: `pytest --cov=mureo --cov-report=term-missing`
3. **Types pass**: `mypy mureo/`
4. **Lint passes**: `ruff check mureo/`
5. **Formatted**: `black --check mureo/ tests/`
6. **Browser assets pass** (only if you touched `mureo/_data/web/`):
   `node --test tests/js/*.test.js`

### PR Structure

- **Title**: concise summary under 70 characters
- **Description**: explain *what* and *why*, not just *how*
- **Test plan**: describe how the change was tested

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add device performance analysis tool
fix: handle empty campaign list in state parser
refactor: extract keyword validation to shared helper
test: add coverage for Meta Ads rate limit retry
docs: update MCP server setup instructions
```

### Adding a New Tool

When adding a new MCP tool:

1. **Client method**: Add the async method to the appropriate Mixin in `mureo/google_ads/` or `mureo/meta_ads/`.
2. **Tool definition**: Add a `Tool` object to `mureo/mcp/tools_google_ads.py` or `tools_meta_ads.py`.
3. **Handler**: Add a handler function and register it in the `_HANDLERS` dict.
4. **Tests**: Add unit tests for both the client method and the handler.
5. **Documentation**: Update `docs/mcp-server.md` with the new tool.

### Adding a New CLI Command

1. Add the command function to `mureo/cli/google_ads.py` or `mureo/cli/meta_ads.py`.
2. Follow the existing pattern: `_require_creds()` -> create client -> `asyncio.run()` -> `_output()`.
3. Add tests.
4. Update `docs/cli.md`.

## Project Structure

```
mureo/
├── mureo/               # Source package
│   ├── __init__.py
│   ├── auth.py
│   ├── google_ads/
│   ├── meta_ads/
│   ├── analysis/
│   ├── context/
│   ├── cli/
│   └── mcp/
├── tests/               # Test suite (pytest)
│   └── js/              # Browser-asset tests (node --test, no deps)
├── docs/                # Documentation
├── pyproject.toml       # Project configuration
└── README.md
```

## Questions?

Open an issue on GitHub for questions, bug reports, or feature requests.
