"""Hermetic-credentials isolation for the built-in analytics adapter tests.

The adapter modules (:class:`GoogleAdsAnalyticsModule` /
:class:`MetaAdsAnalyticsModule`) fall back to a LIVE client whenever a test
constructs them without injecting a fetcher::

    detect_anomalies(account_id)
        -> fetch_google_ads_per_campaign_metrics(account_id)
        -> _open_google_ads_client(account_id)
        -> load_google_ads_credentials()        # <- consults AMBIENT state

That fallback is meant to raise :class:`NoCredentialsError` (rendered as an
empty result) when credentials are absent. But the lookup reads *ambient*
state -- ``~/.mureo/credentials.json``, ``GOOGLE_ADS_*`` / ``META_ADS_*``
environment variables, the BYOD manifest, and the process-wide
runtime-context cache. If any earlier test in the same ``pytest`` process, or
the CI runner's own environment, leaves credentials resolvable, the
no-fetcher tests in this package construct a real client and reach
``googleads.googleapis.com`` -- surfacing as the order/timing-dependent flaky
failure ``Invalid customer ID 'acct123'`` (the test's own ``"acct-123"`` arg
with the dash stripped by the client).

This autouse fixture pins every live-credential lookup to "absent" for the
duration of each test in this package, so the no-fetcher tests are hermetic
regardless of ambient state. Tests that exercise the live path
(``test_live_clients.py``) override these with their own narrower
``patch(...)`` blocks; those nest correctly inside the fixture's monkeypatch
(the inner patch wins for its scope, then restores to the fixture's stub).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the live-client credential lookups to resolve as "absent".

    ``_open_google_ads_client`` / ``_open_meta_ads_client`` import these names
    locally at call time, so patching the module attributes
    (``mureo.byod.runtime.byod_has`` and the two
    ``mureo.auth.load_*_credentials`` functions) is enough to make the live
    fallback raise :class:`NoCredentialsError`. The no-fetcher adapter tests
    can then never reach a real API, no matter what credentials happen to be
    present in the process environment.
    """
    monkeypatch.setattr("mureo.byod.runtime.byod_has", lambda *a, **k: False)
    monkeypatch.setattr("mureo.auth.load_google_ads_credentials", lambda *a, **k: None)
    monkeypatch.setattr("mureo.auth.load_meta_ads_credentials", lambda *a, **k: None)
