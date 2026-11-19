"""The Advertiser API contract mureo's ChatGPT Ads tools are written against.

Every path, query-parameter name and limit below was checked against the
published OpenAPI document (:data:`OPENAPI_VERSION`, read on
:data:`OPENAPI_READ_ON`) and the API reference. The API is in beta and adds
fields often, so responses are passed through untouched rather than modelled;
what is pinned here is only what mureo sends.
"""

from __future__ import annotations

from typing import Final

#: Registry key, credential-store section and provider half of the platform
#: key (``plugin:mureo-chatgpt-ads:chatgpt_ads``). Defined here, below every
#: module of the package, so the credential loader and the provider read one
#: spelling; renaming it would orphan ``action_log`` history.
CHATGPT_ADS_PROVIDER_NAME: Final = "chatgpt_ads"

BASE_URL: Final = "https://api.ads.openai.com/v1"

#: ``info.version`` of the OpenAPI document the contract fixture
#: (``tests/fixtures/chatgpt_ads_openapi_subset.json``) was cut from.
OPENAPI_VERSION: Final = "2.3.0"
OPENAPI_READ_ON: Final = "2026-11-19"

#: Per-request timeout, the same as the Meta client's.
REQUEST_TIMEOUT_SECONDS: Final = 30.0

#: Attempts for one request that keeps answering a retryable status (429, and
#: 5xx for a GET). Counted the way
#: ``mureo.meta_ads.client._MAX_RETRIES`` counts: attempts, not extra tries.
MAX_ATTEMPTS: Final = 3
INITIAL_BACKOFF_SECONDS: Final = 1.0
#: Ceiling on a server-sent ``Retry-After``: a tool call is interactive, so a
#: longer wait is reported as the 429 it is rather than slept through.
MAX_RETRY_AFTER_SECONDS: Final = 30.0

#: Overall budget for one tool call: every request, retry and backoff of a
#: paginated read together. Each request has its own timeout, but a long list
#: of slow pages would otherwise hold the call open for many minutes.
TOOL_DEADLINE_SECONDS: Final = 120.0

#: Bound on the one read a mutation's before-state capture makes. The capture
#: runs before the write, so a slow read must not hold the write back for long:
#: on expiry the write proceeds without a reversal. The same value as the
#: Amazon Ads capture deadline.
REVERSAL_READ_DEADLINE_SECONDS: Final = 15.0

#: Largest page each list endpoint accepts (OpenAPI ``limit`` maximum).
PAGE_MAX_ENTITIES: Final = 500
PAGE_MAX_AUDIT_LOGS: Final = 100
PAGE_MAX_INSIGHTS: Final = 2000

#: Pages one list call may request. The tool ``limit`` needs at most 10 pages
#: at the smallest page maximum, so reaching this means the platform is
#: returning tiny pages, and the call stops instead of walking on.
MAX_PAGES_PER_CALL: Final = 50

#: Longest reporting window. Conversion metrics refuse more than 365 days, and
#: non-hourly delivery reporting keeps the most recent 365 days.
MAX_WINDOW_DAYS: Final = 365

#: Per-tool throttle. The API allows 600 requests per minute per endpoint
#: (10/s) and 1,200 overall. The throttle counts tool calls, and one call can
#: issue several sequential requests (pages, the time-zone lookup, retries)
#: under one slot, so 8/s with a burst of 5 keeps typical use under the
#: platform limit rather than guaranteeing it; a 429 is still retried.
THROTTLE_RATE: Final = 8.0
THROTTLE_BURST: Final = 5
