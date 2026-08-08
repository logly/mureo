"""Does an exclusion target cover a delivery row? Pure, per entity kind.

Every rule here errs toward **fewer** attributed impressions, because the
estimate feeds a threshold that can refuse a write: over-attributing turns
an ordinary hygiene pass into a refusal the operator learns to switch off.

The documented limits:

- **Websites** match on host, after dropping scheme, ``www.``, port, path
  and query. Excluding ``example.com`` covers ``news.example.com`` (Google
  excludes the site, not the one hostname) but excluding
  ``news.example.com`` never claims ``example.com``. The label-boundary
  check is what stops ``example.com`` from swallowing
  ``notexample.com``.
- **Mobile applications** match on the store-qualified app id, with the
  report's ``mobileapp::`` prefix dropped from either side.
- **Negative keywords** are matched by token sequence per match type.
  Google does **not** apply close variants to negative keywords, so no
  stemming, pluralisation or accent folding is applied here either — which
  means a term that only differs by a plural is NOT counted, and the
  estimate is a lower bound.
- Any other entity kind matches on the exact string, case-folded and
  stripped. A plugin surface that needs richer matching normalizes its own
  values before handing them over.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from mureo.analysis.exclusion_impact.models import (
    ENTITY_MOBILE_APPLICATION,
    ENTITY_SEARCH_TERM,
    ENTITY_WEBSITE,
    DeliveryRecord,
    ExclusionTarget,
)

#: Google Ads placement reports prefix a mobile app id with this.
_MOBILE_APP_PREFIX = "mobileapp::"

#: Everything that is not a word character or a space becomes a separator
#: when a search term is tokenized. Unicode-aware so Japanese terms survive.
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)

_EXACT = "EXACT"
_PHRASE = "PHRASE"
_BROAD = "BROAD"


def normalize_website(value: str) -> str:
    """``https://WWW.Example.com/a?b=1`` → ``example.com``."""
    text = str(value or "").strip().lower().rstrip(".")
    if not text:
        return ""
    if "//" not in text:
        # urlsplit only fills ``netloc`` when a scheme separator is present.
        text = f"//{text}"
    host = urlsplit(text).netloc or ""
    host = host.rsplit("@", 1)[-1]
    if host.startswith("["):  # IPv6 literal — keep the brackets, drop the port
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip(".")


def normalize_app(value: str) -> str:
    """Drop the report's ``mobileapp::`` prefix and case-fold."""
    text = str(value or "").strip().lower()
    if text.startswith(_MOBILE_APP_PREFIX):
        text = text[len(_MOBILE_APP_PREFIX) :]
    return text


def tokenize(value: str) -> tuple[str, ...]:
    """Split a search term / keyword into comparable tokens."""
    return tuple(t for t in _TOKEN_SPLIT.split(str(value or "").casefold()) if t)


def _covers_host(excluded: str, served: str) -> bool:
    """True when ``served`` is ``excluded`` or a subdomain of it."""
    if not excluded or not served:
        return False
    return served == excluded or served.endswith(f".{excluded}")


def _contains_subsequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    limit = len(haystack) - len(needle)
    return any(haystack[i : i + len(needle)] == needle for i in range(limit + 1))


def _keyword_matches(target: ExclusionTarget, record: DeliveryRecord) -> bool:
    term = tokenize(record.entity)
    keyword = tokenize(target.value)
    if not keyword:
        return False
    match_type = (target.match_type or _BROAD).strip().upper()
    if match_type == _EXACT:
        return term == keyword
    if match_type == _PHRASE:
        return _contains_subsequence(term, keyword)
    # BROAD (and anything unrecognized, handled as the widest documented
    # form): every token present, order-free.
    return set(keyword).issubset(set(term))


def target_matches(target: ExclusionTarget, record: DeliveryRecord) -> bool:
    """True when excluding ``target`` stops ``record`` from delivering."""
    if target.entity_type != record.entity_type:
        return False
    if target.entity_type == ENTITY_WEBSITE:
        return _covers_host(
            normalize_website(target.value), normalize_website(record.entity)
        )
    if target.entity_type == ENTITY_MOBILE_APPLICATION:
        return normalize_app(target.value) == normalize_app(record.entity)
    if target.entity_type == ENTITY_SEARCH_TERM:
        return _keyword_matches(target, record)
    return (
        str(target.value or "").strip().casefold()
        == str(record.entity or "").strip().casefold()
    )


__all__ = [
    "normalize_app",
    "normalize_website",
    "target_matches",
    "tokenize",
]
