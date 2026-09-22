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

One pattern set, two modes. Free text and a tool argument need different
separator rules — ``"The secret: better ROAS"`` is a headline, not a
credential dump — but they must not become two answers to "what is a
secret". So the ROOTS are declared once and the MODE picks how strictly a
key has to be punctuated to count. See :func:`scrub_text`.
"""

from __future__ import annotations

import re
from typing import Literal

#: What the text being scrubbed IS. Not a style preference — the two kinds
#: leak differently and read differently, and :func:`scrub_text` refuses to
#: guess which one a call site holds.
ScrubMode = Literal["prose", "argument"]

PROSE: ScrubMode = "prose"
ARGUMENT: ScrubMode = "argument"

__all__ = ["ARGUMENT", "PROSE", "ScrubMode", "scrub_text"]

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
# A COMPOUND root cannot occur in an English sentence. Nobody writes
# "client_secret:" or "developer-token:" in a headline, so these keep the
# permissive separator: an equals sign, a colon, with or without spaces and
# quotes, whichever shape the leaking surface happened to use.
#
# ``client[_-]?secret`` is listed even though the bare ``secret`` root
# already covers it: without it the compound would inherit the AMBIGUOUS
# separator and ``client_secret: amzn1.oa2-cs.v1.…`` — the LwA form-body
# echo this scrubber was originally written for — would stop matching in
# ``argument`` mode.
_UNAMBIGUOUS_KEY_ROOTS = (
    "client[_-]?secret",
    "secret[_-]?key",
    "private[_-]?key",
    "access[_-]?key",
    "api[_-]?key",
    "access[_-]?token",
    "refresh[_-]?token",
    "developer[_-]?token",
)

# A BARE root is also an ordinary English word, and ``Password:`` starts a
# novel's title as readily as a credential dump. In an error string that is
# a legibility cost worth paying; in a tool ARGUMENT it destroys the record,
# because ``headline`` / ``description`` / ``primary_text`` / campaign
# ``name`` are the most-written arguments in this product and a colon is how
# a sentence is punctuated. See :data:`_ARGUMENT_SEPARATOR`.
_AMBIGUOUS_KEY_ROOTS = (
    "secret",
    "password",
    "passwd",
    "pwd",
    "credentials?",
    "authorization",
    "bearer",
    "cookie",
    "signature",
)

# ``token`` is ambiguous AND names a quantity ("token limit: 128000",
# "token: 5"), so it is the one root that also carries a minimum value
# length, exactly as ``_CODE_KEY_VALUE`` does and for the same reason: a
# real token is a long opaque string, a count is short. ``max_tokens=4096``
# never matches at all — a root has to sit at the END of the key, and there
# the ``s`` is in the way. The three ``…_token`` compounds above keep their
# unrestricted match, so this narrows nothing #528 and #758 covered: the
# leftmost match wins and theirs starts earlier.
_MIN_TOKEN_VALUE_LEN = 8

# Everything up to the first character that cannot be part of a credential.
_VALUE_CHAR = r"[^\s,;&'\"}\])]"

#: Prose separator: ``k=v``, ``k = v``, ``k: v``, ``'k': 'v'``. The optional
#: quotes catch the dict/JSON rendering an exception ``repr`` produces as
#: well as the bare form-encoded one.
_PROSE_SEPARATOR = r"['\"]?\s*[:=]\s*['\"]?"

#: Argument separator for an ambiguous root: the shape ``_CODE_KEY_VALUE``
#: already established — an ``=`` with NO space before it (the query-string
#: and form-body shape a credential actually leaks in), or the QUOTED
#: dict-key form. A space-padded colon is English punctuation, so it is
#: excluded. Every machine-generated leak still matches; a sentence does
#: not.
_ARGUMENT_SEPARATOR = r"(?:=['\"]?|['\"]\s*:\s*['\"])"


def _key_value_rule(
    roots: tuple[str, ...], separator: str, min_value_len: int = 1
) -> re.Pattern[str]:
    """Compile one ``key<separator>value`` redaction rule.

    The KEY and separator are kept (group 1) so the diagnostic still reads
    ``client_secret=***`` rather than losing what failed. A root matches the
    END of the key and the prefix is never consumed, which is what makes
    ``app_secret`` and ``appSecret`` fall out of a root spelled ``secret``
    — and why no ``[\\w-]*secret`` prefix wildcard is needed. That form
    backtracks quadratically on a long non-matching string, and this
    scrubber runs on attacker-influenceable text.
    """
    quantifier = "+" if min_value_len <= 1 else f"{{{min_value_len},}}"
    return re.compile(
        "((?:" + "|".join(roots) + ")" + separator + ")" + _VALUE_CHAR + quantifier,
        re.IGNORECASE,
    )


_ALL_KEY_ROOTS = _UNAMBIGUOUS_KEY_ROOTS + _AMBIGUOUS_KEY_ROOTS

_PROSE_KEY_VALUE = _key_value_rule(_ALL_KEY_ROOTS, _PROSE_SEPARATOR)
_PROSE_TOKEN_KEY_VALUE = _key_value_rule(
    ("token",), _PROSE_SEPARATOR, _MIN_TOKEN_VALUE_LEN
)

_ARGUMENT_KEY_VALUE = _key_value_rule(_UNAMBIGUOUS_KEY_ROOTS, _PROSE_SEPARATOR)
_ARGUMENT_AMBIGUOUS_KEY_VALUE = _key_value_rule(
    _AMBIGUOUS_KEY_ROOTS, _ARGUMENT_SEPARATOR
)
_ARGUMENT_TOKEN_KEY_VALUE = _key_value_rule(
    ("token",), _ARGUMENT_SEPARATOR, _MIN_TOKEN_VALUE_LEN
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
# PROSE ONLY — this rule does not run in ``argument`` mode. It was written
# for ERROR PROSE, where ``code=`` with no space before the ``=`` really is
# the query-string shape an authorization code leaks in. In a TOOL ARGUMENT
# that same shape is overwhelmingly an ordinary URL parameter: ``final_url``
# is a real argument of ad creation and of sitelinks, and
# ``…?promo_code=SUMMER2026`` is a landing page, not a credential. This
# comment already records that ``code`` is "far too common in ordinary error
# prose"; inside a query string it is commoner still, so dropping the rule
# where the text is known to be a URL-bearing argument is the rule's own
# intent applied one step further — not a relaxation of it.
_MIN_CODE_VALUE_LEN = 8
_CODE_KEY_VALUE = re.compile(
    r"((?:code=['\"]?|code['\"]\s*:\s*['\"]))[^\s,;&'\"}\])]{"
    + str(_MIN_CODE_VALUE_LEN)
    + r",}",
    re.IGNORECASE,
)


def scrub_text(text: str, *, mode: ScrubMode = PROSE) -> str:
    """Redact secret-shaped substrings from a string.

    All passes are value-only: an HTTP status, an exception type and the
    failing operation survive, so a scrubbed message is still a usable
    diagnostic. Applied at ONE boundary per trail, so no two of them can
    redact differently.

    ``mode`` says what the text IS, because the two kinds need different
    rules and guessing per call site is how they drift apart:

    ``PROSE`` (the default)
        An error message, a ``reason``, a ``rationale``, a platform's
        error body. Four passes: token prefixes (``Bearer …``, ``Atza|…``,
        ``Atzr|…``), ``key: value`` credential pairs on every root, the
        same for a ``token`` key with a long enough value, and the
        narrowly-anchored ``code=<authorization code>``. This is the mode
        ``normalize_reason`` uses, so an ``action_log`` reason is scrubbed
        identically on its way to STATE.json and to the journal.

    ``ARGUMENT``
        The value of a tool argument. Two differences, both because the
        text is a parameter rather than a sentence. The ``code=`` pass
        does not run — ``…?promo_code=…`` in a ``final_url`` is a landing
        page, and a journal that rewrites the URL an agent submitted
        cannot answer the question it exists for. And an AMBIGUOUS root
        (``secret``, ``password``, ``cookie``, ``signature``, bare
        ``token``, …) needs an ``=`` or a quoted dict key rather than a
        space-padded colon, because ``"The secret: better ROAS"`` is a
        headline. Compound roots (``client_secret``, ``developer-token``)
        keep the permissive separator in both modes; they do not occur in
        an English sentence.

    An unrecognised ``mode`` is treated as ``PROSE``. Prose is the wider
    of the two, so the fail-safe direction is to over-mask.
    """
    scrubbed = _SECRET_VALUE.sub("***", text)
    if mode == ARGUMENT:
        scrubbed = _ARGUMENT_KEY_VALUE.sub(r"\1***", scrubbed)
        scrubbed = _ARGUMENT_AMBIGUOUS_KEY_VALUE.sub(r"\1***", scrubbed)
        return _ARGUMENT_TOKEN_KEY_VALUE.sub(r"\1***", scrubbed)
    scrubbed = _PROSE_KEY_VALUE.sub(r"\1***", scrubbed)
    scrubbed = _PROSE_TOKEN_KEY_VALUE.sub(r"\1***", scrubbed)
    return _CODE_KEY_VALUE.sub(r"\1***", scrubbed)
