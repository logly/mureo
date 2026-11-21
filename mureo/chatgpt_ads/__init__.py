"""ChatGPT Ads: OpenAI's Advertiser API as a bundled provider (#992, #993).

mureo talks to the Advertiser API directly over HTTPS, the way it talks to the
Meta Graph API: the operator's Ads API key lives in mureo's credential store,
the agent never sees it, and every call rides the plugin safety layer (audit,
throttle) through :mod:`mureo.bundled_providers`.

Read-only today: account, campaigns, ad groups, ads, insights and the change
history. Nothing in this package imports :mod:`mureo.mcp` or :mod:`mureo.web`;
the HTTP client is imported on the first tool call, not at server start.
"""
