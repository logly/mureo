"""Redact secret-shaped substrings from free text.

Below :mod:`mureo.mcp` on purpose (#758 phase 2). Three trails now share
these passes — the plugin audit log, the dispatcher journal, and the
``reason`` stamped onto an ``action_log`` entry — and the last of those
is written from :mod:`mureo.context.state`, which must not import the MCP
layer. A second copy of the patterns would be a second answer to "what
is a secret", and the trails would drift apart on the day one of them is
updated.

The rules stay value-only: an HTTP status, an exception type and the
failing operation all survive, so a scrubbed message is still a usable
diagnostic.
"""

from __future__ import annotations

import re

__all__ = ["scrub_text"]

# Secret-shaped *values* that can appear in a free-text error string
# (``error`` is not key/value-masked like ``args``). Covers HTTP bearer
# headers and Amazon LwA access/refresh tokens (Atza|… / Atzr|…). The
# Amazon bridge is the first credentialed plugin path, so this is
# defense-in-depth for every plugin's recorded exception text.
#
# Every alternative stops at whitespace OR a quote. ``Bearer\s+\S+`` used to
# run past the closing quote of a JSON string and swallow the rest of the
# document, leaving structurally broken text for whoever reads the record.
# A bearer token cannot contain a quote, so stopping there cannot leak.
#
# ``Basic`` is an ordinary English word ("Basic plan"), so its alternative
# is deliberately narrower: only a base64-shaped value of 16+ characters
# counts, which is what an ``Authorization: Basic`` header actually carries.
_SECRET_VALUE = re.compile(
    r"(Bearer\s+[^\s'\"]+|Basic\s+[A-Za-z0-9+/=]{16,}"
    r"|Atza\|[^\s'\"]+|Atzr\|[^\s'\"]+)",
    re.IGNORECASE,
)

# Second shape: ``key=value`` / ``key: value`` credential leaks. An HTTP
# client that echoes the form body it POSTed spills the client secret in
# plain text, which the token-prefix patterns above do not match (an LwA
# client secret has no distinguishing prefix). The KEY and separator are
# kept so the diagnostic still reads "client_secret=***" rather than
# losing the context of what failed.
#
# The value stops at the first separator that cannot be part of a token
# (whitespace, quote, comma, ``&``, or a closing bracket), so only the
# credential — not the rest of the sentence — is redacted.
# The optional quotes around the separator catch the dict/JSON rendering
# an exception's ``repr`` produces (``{'client_secret': 'shh'}``) as well
# as the bare form-encoded one.
#
# EVERY key word separator is optional (``[_-]?``), so ``client_secret``,
# ``client-secret`` and ``clientSecret`` are all masked. Three of the five
# alternatives once required a literal underscore, which meant the camelCase
# spelling leaked in cleartext (#528) — and camelCase is not exotic here:
# Amazon's own surface is camelCase throughout (``advertiserAccountId``,
# ``adProductFilter``, ``authorizationCode``), and this scrubber's whole job
# is redacting error bodies from surfaces like it. Matches ``_SENSITIVE_KEY``
# above, which was already spelled this way.
#
# ``developer[_-]?token`` and ``authorization`` joined the list for #758: the
# journal routes every platform family's error text through this scrubber, and
# Google's request metadata — which a gRPC debug string prints verbatim —
# spells the credential ``developer-token`` and the header ``authorization``.
# ``authorization`` carries no separator of its own, so it is listed bare.
#
# The roots below are the ones ``mureo.mcp.plugin_audit._SENSITIVE_KEY``
# already masks an argument KEY for (#779). Until then this pattern knew
# seven EXACT spellings while the key path matched those words as a
# SUBSTRING, so the identical credential was redacted when it arrived as an
# argument key and written in cleartext when it arrived inside a string —
# ``app_secret`` most of all, which is mureo's own Meta credential field
# (``mureo/auth.py``).
#
# A root matches the END of the key, not the whole of it; the prefix is
# never part of the match, so ``app_secret=…`` becomes ``app_secret=***``
# and ``appSecret`` / ``authToken`` / ``privateKey`` are caught by the same
# ``[_-]?`` treatment every root already had. This is the technique
# ``_CODE_KEY_VALUE`` below documents, and it is chosen over a
# ``[\w-]*secret`` prefix wildcard for the reason recorded there: the
# wildcard backtracks quadratically over a long non-matching string.
#
# ``key`` is deliberately NOT a root — it would eat ``monkey=``,
# ``turkey=`` and ``keyword=`` — so each credential-bearing ``…key`` tail
# is spelled out instead (``aws_secret_access_key`` lands on
# ``access[_-]?key``). ``sig`` is not a root either: it would eat
# ``design=``. ``signature`` is safe and is listed in full.
_SECRET_KEY_VALUE = re.compile(
    r"((?:secret[_-]?key|private[_-]?key|access[_-]?key|api[_-]?key"
    r"|access[_-]?token|refresh[_-]?token|developer[_-]?token"
    r"|secret|password|passwd|pwd|credentials?"
    r"|authorization|bearer|cookie|signature)"
    r"['\"]?\s*[:=]\s*['\"]?)[^\s,;&'\"}\])]+",
    re.IGNORECASE,
)

# ``token`` is the one root that cannot go in the list above. In ordinary
# prose it names a UNIT, not a credential ("token limit: 128000",
# "token: 5"), so it takes the same minimum-value-length rule
# ``_CODE_KEY_VALUE`` uses, for the same reason: a real token is a long
# opaque string, a count is short. ``max_tokens=4096`` never matches at all
# — the root has to sit at the END of the key, and there the ``s`` is in
# the way.
#
# The three unambiguous ``…_token`` spellings stay in ``_SECRET_KEY_VALUE``
# with no length rule, so this does not narrow what #528 and #758 already
# covered: the leftmost match wins, and theirs starts earlier.
_MIN_TOKEN_VALUE_LEN = 8
_TOKEN_KEY_VALUE = re.compile(
    r"(token['\"]?\s*[:=]\s*['\"]?)[^\s,;&'\"}\])]{"
    + str(_MIN_TOKEN_VALUE_LEN)
    + r",}",
    re.IGNORECASE,
)

# ``code`` on its own is far too common in ordinary error prose ("status
# code = 400", "error code: 17"), so it gets a deliberately narrow rule.
# Only two shapes count:
#   - ``code=…`` with NO space before the ``=`` (the query-string /
#     form-body shape an authorization code actually leaks in), and
#   - the QUOTED dict-key shape ``'code': '…'`` that an exception repr
#     produces.
# Bare ``code: 12345678`` prose is deliberately NOT matched. The value
# must also be at least _MIN_CODE_VALUE_LEN token characters — Amazon's
# authorization codes are long alphanumerics; status codes and errnos
# are not.
#
# The key may END in ``code`` rather than BE it (``authorizationCode``,
# ``authCode``, ``oauth_code``): the same credential lands in whatever field
# name a platform picked, and the original word-boundary lookbehind let those
# through in full (#528). Dropping the lookbehind is all that takes — the
# pattern simply matches the ``code`` at the END of the key and leaves the
# prefix untouched, so ``authorizationCode": "…"`` becomes
# ``authorizationCode": "***"``. Broadening the KEY is the safe direction: the
# length rule still keeps ``status_code=400`` and friends readable, and
# over-masking costs legibility while under-masking costs a credential.
#
# Deliberately NOT written as a ``[\w-]*code`` prefix: that form backtracks
# quadratically on a long non-matching string (a 2 MB error body hung the
# test suite), and this scrubber runs on attacker-influenceable text.
#
# Not covered, deliberately: a bare NUMERIC code is never masked (an LwA
# authorization code is a long alphanumeric string, never an integer), so the
# asymmetry with string codes is a legibility quirk, not a leak.
#
# EXEMPTIBLE, and only this rule is (``mask_code_key_value=False``). The rule
# was written for ERROR PROSE, where ``code=`` with no space before the ``=``
# really is the query-string shape an authorization code leaks in. In a TOOL
# ARGUMENT that same shape is overwhelmingly an ordinary URL parameter:
# ``final_url`` is a real argument of ad creation and of sitelinks, and
# ``…?promo_code=SUMMER2026`` is a landing page, not a credential. This
# comment already records that ``code`` is "far too common in ordinary error
# prose"; inside a query string it is commoner still, so dropping the rule
# where the text is known to be a URL-bearing argument is the rule's own
# intent applied one step further — not a relaxation of it. The exemption is
# a FLAG on this one implementation rather than a second pattern set: two
# pattern sets would be two answers to "what is a secret", which is exactly
# what this module exists to prevent.
_MIN_CODE_VALUE_LEN = 8
_CODE_KEY_VALUE = re.compile(
    r"((?:code=['\"]?|code['\"]\s*:\s*['\"]))[^\s,;&'\"}\])]{"
    + str(_MIN_CODE_VALUE_LEN)
    + r",}",
    re.IGNORECASE,
)


def scrub_text(text: str, *, mask_code_key_value: bool = True) -> str:
    """Redact secret-shaped substrings from a free-text error string.

    Four passes, all value-only: token prefixes (``Bearer …``,
    ``Atza|…``, ``Atzr|…``), ``key=value`` credential pairs, the same for
    a ``token`` key with a long enough value, and the narrowly-anchored
    ``code=<authorization code>``. Everything else — HTTP status,
    exception type, the failing operation — survives, so a scrubbed
    message is still a usable diagnostic.

    Applied at ONE boundary per trail, so no two of them can redact
    differently: the plugin audit record, the journal line, and — since
    #758 phase 2 — ``normalize_reason``, which every ``action_log``
    rationale passes through before it reaches STATE.json.

    ``mask_code_key_value=False`` drops the third pass, and nothing else.
    One caller passes it: :func:`~mureo.mcp.plugin_audit.mask_arguments`,
    which scrubs tool ARGUMENTS rather than prose. ``…?promo_code=…`` in a
    ``final_url`` is a landing page, not an authorization code, and a
    journal that rewrites the URL an agent submitted cannot answer the
    question it exists for. Every ``reason`` / ``rationale`` path calls
    this function directly and therefore keeps the pass — those really are
    free text, which is what the rule was written for. See the
    ``_CODE_KEY_VALUE`` comment above for why the exemption is a flag on
    one pattern set rather than a second one.
    """
    scrubbed = _SECRET_VALUE.sub("***", text)
    scrubbed = _SECRET_KEY_VALUE.sub(r"\1***", scrubbed)
    scrubbed = _TOKEN_KEY_VALUE.sub(r"\1***", scrubbed)
    if not mask_code_key_value:
        return scrubbed
    return _CODE_KEY_VALUE.sub(r"\1***", scrubbed)
