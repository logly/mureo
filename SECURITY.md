# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.3.x   | :white_check_mark: |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in mureo, please report it responsibly.

**Do NOT open a public GitHub issue.**

Instead, please use [GitHub's private vulnerability reporting](https://github.com/logly/mureo/security/advisories/new) to submit your report.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 5 business days
- **Fix release**: depends on severity, but we aim for:
  - Critical: within 7 days
  - High: within 14 days
  - Medium/Low: next scheduled release

### Scope

The following are in scope:

- `mureo` Python package (PyPI)
- MCP server implementation
- CLI tool
- Credential storage and handling
- OAuth flow implementation

### Out of scope

- Vulnerabilities in upstream dependencies (please report those to the respective maintainers)
- Issues in the managed/SaaS components (not part of this OSS project)

## Built-in Security Controls

mureo ships several layers of defense-in-depth designed for the
reality that AI agents drive marketing operations. Each layer
addresses a concrete class of attack that has been observed in the
wild against AI-assisted ad management.

### Credential guard (PreToolUse hook)

`mureo setup claude-code` writes a PreToolUse hook into
`~/.claude/settings.json` that blocks AI agents from reading
`~/.mureo/credentials.json`, `.env`, and similar secret files. This
prevents a prompt-injection payload from tricking the agent into
exfiltrating OAuth tokens or developer tokens via the file-system
tools.

### GAQL input validation

Every string that enters a Google Ads Query Language (GAQL) query
flows through a single whitelist-based validator
(`mureo/google_ads/_gaql_validator.py`). IDs must be numeric and
≤ 20 characters, dates must match `YYYY-MM-DD`, date-range
constants must be one of the 12 known Google values (`ALL_TIME` is
deliberately excluded to preserve the period-days guard), and
free-text literals are escape-sanitized with backslashes processed
before quotes. `_period_to_date_clause`'s `BETWEEN` branch
pattern-matches and revalidates both dates, so a caller passing
`BETWEEN '2024-01-01' AND '2024-01-31' OR 1=1` is rejected.

### Anomaly detection

`mureo/analysis/anomaly_detector.py` compares a live
`CampaignMetrics` snapshot against a median-based baseline built
from historical `action_log` entries and emits prioritized anomalies
for three high-signal failure modes:

- Zero spend on a previously-spending campaign (CRITICAL) — catches
  account lockouts, policy suspensions, and stopped campaigns.
- CPA spike ≥ 1.5× baseline (critical at 2×) — catches rogue
  bidding, broken landing pages, and unintended mass-negative-keyword
  removals.
- CTR drop ≤ 0.5× baseline (critical at 0.3×) — catches creative
  rotation failures and audience drift.

Sample-size gates (30+ conversions for CPA, 1000+ impressions for
CTR) follow the `mureo-learning` skill's statistical-thinking rules
to suppress single-day noise.

### Immutable data models

All dataclasses that represent campaign state, action log entries,
strategy context, and anomalies use `frozen=True`. Mutation attempts
fail fast with `FrozenInstanceError`, preventing an agent from
silently altering its own record of what happened or what was
decided.

### Local-only credential storage

Credentials are loaded from `~/.mureo/credentials.json` or
environment variables and never transmitted anywhere except the
official Google Ads, Meta Ads, and Search Console APIs. mureo itself
has no telemetry or phone-home behavior.

## Security Best Practices for Users

- Never commit `~/.mureo/credentials.json` to version control
- Use environment variables for CI/CD environments
- Rotate OAuth tokens periodically
- Keep mureo updated to the latest version
- Run `mureo setup claude-code` (not a bare `mureo auth setup`) so
  the credential guard hook is installed alongside your MCP config
