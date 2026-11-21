"""Install messages for a platform mureo has no tools of its own for.

The providers-install step of the configure wizard installs an official
MCP. For Google Ads the operator can fall back to mureo's own tools ("mureo
standard"), and the messages say so. GA4 has no such tools: the official
MCP is the only path, so a message that reaches a GA4 operator must not
offer one (#1045). The wording lives in ``i18n.json``; which key a
platform gets is pinned in ``tests/js/wizard_install_slots.test.js``.
"""

from __future__ import annotations

import pytest

from tests.test_web_i18n_keys import _load_i18n

pytestmark = pytest.mark.unit

#: Messages the wizard shows on a platform without tools of mureo's own.
_OFFICIAL_ONLY_KEYS = (
    "wizard.providers_install.needs_credentials.generic",
    "wizard.providers_install.failed_official_only",
)

#: How each locale names mureo's own tools.
_MUREO_STANDARD = {"en": "mureo standard", "ja": "mureo 標準"}


@pytest.mark.parametrize("locale", sorted(_MUREO_STANDARD))
@pytest.mark.parametrize("key", _OFFICIAL_ONLY_KEYS)
def test_official_only_messages_do_not_offer_mureo_standard(
    locale: str, key: str
) -> None:
    message = _load_i18n()[locale][key]
    assert _MUREO_STANDARD[locale] not in message, message


@pytest.mark.parametrize("locale", sorted(_MUREO_STANDARD))
def test_official_only_failure_still_names_the_cause(locale: str) -> None:
    message = _load_i18n()[locale]["wizard.providers_install.failed_official_only"]
    assert "{detail}" in message
