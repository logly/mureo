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
#   docker run --rm -v ~/.mureo:/home/mureo/.mureo mureo

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/logly/mureo" \
      org.opencontainers.image.description="AI agent framework for autonomous ad operations across Google Ads, Meta Ads, and Search Console" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Logly, Inc." \
      org.opencontainers.image.documentation="https://mureo.io" \
      org.opencontainers.image.url="https://github.com/logly/mureo"

# Non-root user for runtime
RUN groupadd --system mureo && useradd --system --gid mureo --create-home mureo

WORKDIR /app

# Install dependencies first in a cacheable layer.
# We create an empty package stub so `pip install .` resolves deps
# without needing the full source tree; sources are copied next.
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p mureo && touch mureo/__init__.py \
 && pip install --no-cache-dir . \
 && rm -rf mureo

# Copy real sources. Edits here do not invalidate the deps layer above.
COPY mureo/ ./mureo/
RUN pip install --no-cache-dir --no-deps .

# Drop privileges
RUN chown -R mureo:mureo /app
USER mureo

# Introspection-only defaults for server registries. Replace at runtime
# via `-v ~/.mureo:/home/mureo/.mureo` or `--env-file`.
ENV GOOGLE_ADS_DEVELOPER_TOKEN=introspection-only \
    GOOGLE_ADS_CLIENT_ID=introspection-only \
    GOOGLE_ADS_CLIENT_SECRET=introspection-only \
    GOOGLE_ADS_REFRESH_TOKEN=introspection-only \
    META_ADS_ACCESS_TOKEN=introspection-only

# MCP server over stdio (Claude Code / Cursor / Codex CLI / Gemini CLI)
CMD ["python", "-m", "mureo.mcp"]
