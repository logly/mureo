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

## Security Best Practices for Users

- Never commit `~/.mureo/credentials.json` to version control
- Use environment variables for CI/CD environments
- Rotate OAuth tokens periodically
- Keep mureo updated to the latest version
