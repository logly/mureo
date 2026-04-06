# Contributing Guide

Thank you for your interest in contributing to mureo. This guide covers the development setup, coding standards, and PR workflow.

## Development Setup

### Prerequisites

- Python 3.10 or later
- Git

### Clone and Install

```bash
git clone https://github.com/yourorg/mureo-core.git
cd mureo-core

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

### With Coverage

```bash
pytest --cov=mureo --cov-report=term-missing
```

**Minimum coverage: 80%.** The CI pipeline will fail if coverage drops below this threshold (configured in `pyproject.toml`). The current test suite has 1165 tests with 95% coverage.

### Test Markers

Tests are categorized with pytest markers:

```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration
```

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

## Pull Request Guidelines

### Before Submitting

1. **Tests pass**: `pytest tests/ -v`
2. **Coverage >= 80%**: `pytest --cov=mureo --cov-report=term-missing`
3. **Types pass**: `mypy mureo/`
4. **Lint passes**: `ruff check mureo/`
5. **Formatted**: `black --check mureo/ tests/`

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
mureo-core/
├── mureo/               # Source package
│   ├── __init__.py
│   ├── auth.py
│   ├── google_ads/
│   ├── meta_ads/
│   ├── analysis/
│   ├── context/
│   ├── cli/
│   └── mcp/
├── tests/               # Test suite
├── docs/                # Documentation
├── pyproject.toml       # Project configuration
└── README.md
```

## Questions?

Open an issue on GitHub for questions, bug reports, or feature requests.
