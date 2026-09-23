"""How an Amazon failure body is PRESENTED to the agent (#113 Phase 1).

Everything here runs strictly AFTER
:func:`mureo.amazon_ads.bridge._normalize_failure` has established that a
call failed, so nothing in this module can make something a failure or stop
it being one — ``CallToolResult.isError`` settles that, over there. What is
left is presentation: redact Amazon's own body, reshape it into a line the
agent can act on, and bound it so a runaway body cannot flood the model's
context.

The scrub-before-flatten ordering this module hosts is a SECURITY property,
not a style choice. The shared redactor keys on the literal ``"code":``
anchor, so flattening first would delete that anchor and hand what may be an
LwA authorization code to the agent — and to ``plugin_audit.jsonl`` — in
cleartext. :func:`_flatten_for_display` records the full reasoning and the
legibility cost accepted with it; do not reorder the two calls in
:func:`_display_text` without reading it.

Failure DETECTION deliberately stayed in :mod:`mureo.amazon_ads.bridge`
(``_VALIDATION_FAILURE_PREFIX`` / ``_is_validation_failure``). Those decide
WHETHER a result is a failure, which is ``_normalize_failure``'s question
and is answered from ``isError`` with that prefix as a belt-and-braces
second signal; they read the raw content before anything here touches it,
and they never render. The cut is between "is this a failure" (bridge) and
"what does the agent read" (here), so moving them would split one decision
across two modules.
"""

from __future__ import annotations

import json
from typing import Any

from mureo.amazon_ads.session_auth import scrub_secrets

#: Stand-in when a failure arrives with no text at all — the envelope must
#: still be produced (a failure with an empty body is still a failure), and it
#: must still say something.
_NO_FAILURE_TEXT = "Amazon reported a tool error with no message"

#: Prefix for a body that carries no usable ``message``. Since the redactor
#: masks most ``code`` values, such a body would otherwise reach the agent as
#: an opaque ``{"code":"***"}`` with nothing to act on. Saying so plainly is
#: the only honest option, and it tells the agent what to report.
_NO_MESSAGE_TEXT = "Amazon returned no error message; raw body:"

#: Hard cap on the failure text handed to the agent, with an explicit marker
#: so a truncated diagnostic can never be mistaken for a complete one.
#:
#: 4000 characters. The longest failure observed live is ~150 characters, and
#: a ``Validation errors: [...]`` list with a dozen entries still lands well
#: under 1000, so every plausible real diagnostic survives whole (>25x the
#: observed maximum). Past that it is a runaway or adversarial body, and an
#: unbounded one would dump megabytes into the agent's context — the audit
#: line has always been capped (``plugin_audit._MAX_STR``); this is the same
#: protection for the side that reaches the model.
_MAX_FAILURE_TEXT = 4000
_TRUNCATION_MARKER = "…<truncated>"

#: Cap on the RAW body handed to the redactor, ahead of flattening (#791).
#:
#: Deliberately NOT :data:`_MAX_FAILURE_TEXT`. Scrubbing runs BEFORE
#: :func:`_flatten_for_display` — the ordering is a security property, see
#: there — so this caps the JSON while 4000 caps the text flattening
#: renders out of it, and flattening only ever shortens what it parses: the
#: ``{"code":…,"message":…}`` scaffolding becomes ``code: message`` and a
#: JSON escape collapses to the single character it names (6:1 for
#: ``\uXXXX``). Capping the input at the output budget would therefore cut
#: bodies that had room to spare. 4x is that headroom with margin: the
#: longest failure observed live is ~150 characters, so 16000 is >100x it,
#: and the regex work it buys is ~4 ms where a 2 MB body cost ~480 ms.
#:
#: No cap can be exact — JSON permits unbounded whitespace between tokens,
#: so an arbitrarily long body can render into four characters — which is
#: why the over-cap path announces itself (:data:`_OVERSIZE_BODY_TEXT`)
#: instead of pretending the number was always enough.
_SCRUB_INPUT_HEADROOM = 4
_MAX_SCRUB_INPUT = _MAX_FAILURE_TEXT * _SCRUB_INPUT_HEADROOM

#: Prefix for a body that was cut at :data:`_MAX_SCRUB_INPUT` and no longer
#: parses. See :func:`_display_text` for why that combination has to speak.
_OVERSIZE_BODY_TEXT = "Amazon returned an oversized error body; scrubbed prefix:"


def _flatten_for_display(scrubbed: str) -> str:
    """PRESENTATION ONLY: ``{"code": X, "message": Y, …}`` ⇒ ``X: Y (…)``.

    Runs strictly AFTER a failure has been established by
    :func:`mureo.amazon_ads.bridge._normalize_failure`, so it CANNOT influence
    whether something is a failure — that is ``CallToolResult.isError``'s job
    alone.

    **The input must already be scrubbed**, and the ordering is a security
    property, not a style choice. The shared redactor keys on the literal
    ``"code":`` anchor to mask what may be an LwA authorization code
    (:func:`mureo.core.scrub.scrub_text`). Flattening first would delete that
    anchor and hand a credential to the agent AND to ``plugin_audit.jsonl`` in
    cleartext. Scrub, then reshape what the redactor has already cleared.

    The consequence is accepted deliberately: the redactor cannot tell an
    Amazon error code from an OAuth code — and must not guess, since a wrong
    guess here leaks a credential — so a ``code`` long enough to trip the rule
    renders as ``***``. ``FIELD_VALUE_IS_INVALID`` is one of those, verified:
    the live failure reads ``API error: ***: Multi marketplace query requests
    only support query by primary resource id``. The message carries the
    actionable content, which is what the agent needs to correct its call.

    Every key that is not rendered into the summary is appended verbatim
    rather than dropped, so a future Amazon shape does not lose information
    silently. A body with NO usable ``message`` (absent, empty, ``null``, or
    not a string) is prefixed with :data:`_NO_MESSAGE_TEXT`: with the code
    masked there is nothing left to read, and an opaque ``{"code":"***"}``
    would leave the agent guessing. A ``message`` with no usable ``code``
    renders as the message alone — it is a perfectly good diagnosis.

    Anything that does not parse is returned untouched — including a body deep
    enough to exhaust the parser's stack (``RecursionError`` is a
    ``RuntimeError``, so it needs naming explicitly beside ``ValueError``).
    """
    try:
        payload = json.loads(scrubbed)
        if not isinstance(payload, dict):
            return scrubbed
        raw_message = payload.get("message")
        message = raw_message.strip() if isinstance(raw_message, str) else ""
        if not message:
            return f"{_NO_MESSAGE_TEXT} {scrubbed}"
        rendered = message
        rendered_keys = {"message"}
        code = payload.get("code")
        if not isinstance(code, bool) and isinstance(code, (str, int)):
            rendered = f"{code}: {message}"
            rendered_keys.add("code")
        extras = {k: v for k, v in payload.items() if k not in rendered_keys}
        if extras:
            rendered = f"{rendered} ({json.dumps(extras, ensure_ascii=False)})"
        return rendered
    except (ValueError, RecursionError):
        return scrubbed


def _failure_text(content: list[Any]) -> str:
    """Amazon's own failure text — scrubbed, reshaped and bounded.

    Scrubbing happens HERE, at the point the string is taken out of the
    response and before anything reshapes it, so every caller gets a redacted
    string and the redactor still sees the payload in its original form
    (see :func:`_display_text`). The result is capped last, so the bound
    holds for every path through this function.
    """
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return _bounded(_display_text(text.strip()))
    return _NO_FAILURE_TEXT


def _display_text(raw: str) -> str:
    """Amazon's body, scrubbed inside a bounded window, then reshaped.

    Scrub first, flatten second, for the reason :func:`_flatten_for_display`
    records. What #791 added is the WINDOW: ``scrub_secrets`` slices to
    :data:`_MAX_SCRUB_INPUT` plus the straddle margin before it scrubs, so a
    runaway body costs a constant instead of ~480 ms per 2 MB on the MCP
    dispatch path. A body under the cap comes back exactly as before.

    Over the cap the body is CUT, and a cut JSON body normally stops
    parsing — which leaves :func:`_flatten_for_display` handing the text
    straight back. Passing that fragment off as Amazon's own diagnostic is
    the failure mode this guard exists for, so it is labelled instead. Not
    every over-cap body is affected: trailing filler cuts away without
    touching the object, and then the agent gets the flattened form as
    usual. The test is the SCRUBBED length rather than ``len(raw)`` because
    redaction can itself push a body over the cap (``pwd=a`` ⇒ ``pwd=***``).
    """
    scrubbed = scrub_secrets(raw, cap=_MAX_SCRUB_INPUT)
    flattened = _flatten_for_display(scrubbed)
    if flattened != scrubbed or len(scrubbed) < _MAX_SCRUB_INPUT:
        return flattened
    return f"{_OVERSIZE_BODY_TEXT} {scrubbed}"


def _bounded(text: str) -> str:
    """Cap ``text`` at :data:`_MAX_FAILURE_TEXT`, marking any truncation."""
    if len(text) <= _MAX_FAILURE_TEXT:
        return text
    return text[:_MAX_FAILURE_TEXT] + _TRUNCATION_MARKER
