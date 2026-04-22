# Dockerfile for mureo — AI agent framework for ad operations.
#
# Primary purpose: enable MCP introspection checks on server registries
# such as Glama (https://glama.ai/mcp/servers/logly/mureo).
#
# Secondary purpose: let users try mureo without touching their host
# Python environment. Real usage requires credentials; see README.
#
# Usage:
#   docker build -t mureo .
#   docker run --rm -v ~/.mureo:/root/.mureo mureo

FROM python:3.11-slim

WORKDIR /app

# Copy package metadata and sources
COPY pyproject.toml README.md LICENSE ./
COPY mureo/ ./mureo/

# Install mureo from source
RUN pip install --no-cache-dir .

# Introspection-only defaults. Replace with real credentials at runtime
# via `-v ~/.mureo:/root/.mureo` or `--env-file`.
ENV GOOGLE_ADS_DEVELOPER_TOKEN=introspection-only \
    GOOGLE_ADS_CLIENT_ID=introspection-only \
    GOOGLE_ADS_CLIENT_SECRET=introspection-only \
    GOOGLE_ADS_REFRESH_TOKEN=introspection-only \
    META_ADS_ACCESS_TOKEN=introspection-only

# MCP server over stdio (Claude Code / Cursor / Codex CLI / Gemini CLI)
CMD ["python", "-m", "mureo.mcp"]
