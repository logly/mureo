"""ChatGPT Ads change feed: the Advertiser API audit log as external changes (#994).

Reads ``GET /audit_logs`` for the import window and maps each row onto
:class:`~mureo.change_import.models.ExternalChange`, so
``mureo_external_changes_import`` records changes made on the account outside
mureo. Read-only. It shares the client and its ``list_all`` cursor walk with
the ``chatgpt_ads_change_history_list`` tool, not that tool's output.

**What this feed cannot see.** Stated on every result
(:data:`_COVERAGE_NOTE`), because an operator reading an empty import needs
it: the platform publishes neither how long it keeps audit-log entries nor
which changes it records, so an empty window is not evidence that the
account was static.

**Which account.** One API key reads exactly one ad account and the key is
machine-wide, while STATE.json is per workspace. When the workspace names an
account id, the feed reads ``GET /ad_account`` first and imports nothing for a
key that reads another account; otherwise another client's changes would land
in this workspace's ``action_log`` for good.

**A capped pass.** At most :data:`CHANGE_FEED_ROW_CAP` rows are imported per
pass, read oldest first, and the truncation note names the point the pass read
through. The next pass continues from the newest change mureo imported; rows
mureo made are never stored and do not move that point, so when a pass stops
at the same place the note's ``since`` is what continues it.

Rows name ONE canonical target each, at the specificity mureo's change tools
record (``identity`` in :mod:`mureo.chatgpt_ads.tools_mutations`): a campaign
by ``campaign_id``, an ad group by ``entity_type="ad_group"`` +
``entity_id``, an ad by ``ad_id``. A row on any other resource carries no
identity, so it can never be attributed to a mureo change and is imported as
external.

Every string taken from a row passes :func:`_token` (field names the tighter
:data:`_FIELD_NAME`, at most :data:`MAX_CHANGED_FIELDS` of them): these values
are written into STATE.json and read back by an agent, so anything outside an
identifier alphabet is dropped rather than carried. The free-text
``item_name`` is not read, and neither is ``actor_type``: it names the kind of
actor, not the client that made the change, so ``client_type`` stays empty.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from itertools import islice
from typing import TYPE_CHECKING, Any

from mureo.change_import.models import ChangeFeedResult, ExternalChange
from mureo.chatgpt_ads._api import (
    AD_ACCOUNT_PATH,
    CHANGE_FEED_ROW_CAP,
    CHATGPT_ADS_PROVIDER_NAME,
    MAX_CHANGED_FIELDS,
    PAGE_MAX_AUDIT_LOGS,
    TOOL_DEADLINE_SECONDS,
)
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads.credentials import (
    NO_CREDENTIALS_DETAIL,
    load_chatgpt_ads_credentials,
)
from mureo.chatgpt_ads.handlers import run_with_client
from mureo.core.auth_failure import AUTH_CAUSE_NO_CREDENTIALS, PlatformAuthError

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient

_TOKEN = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")
#: A changed-field name. The importer joins the names into the entry's
#: summary, so they get a narrower alphabet and length than ids do.
_FIELD_NAME = re.compile(r"[A-Za-z0-9_.]{1,64}")
#: A lower-case letter or digit followed by an upper-case one: where
#: ``AdGroup`` becomes ``Ad_Group`` on the way to ``AD_GROUP``.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_UNKNOWN = "UNKNOWN"

_COVERAGE_NOTE = (
    "The ChatGPT Ads audit log has no published retention period and no "
    "published list of the change types it records, so an empty window is "
    "not evidence that the account was static."
)

_NO_ACCOUNT_NOTE = (
    "This workspace names no ChatGPT Ads account id, so the import could not "
    "check that the API key reads the same account."
)

# Neither id is quoted: the reason is shown to an agent and written into the
# outcome, and the account id is all it would add.
_ACCOUNT_MISMATCH = (
    "The configured ChatGPT Ads API key reads a different ad account than the "
    "one this workspace names; nothing was imported. Check the key on the "
    "ChatGPT Ads card of `mureo configure`, or the account id in STATE.json."
)


def _truncation_note(read_through: str) -> str:
    return (
        f"The import stopped at {CHANGE_FEED_ROW_CAP} audit-log entries, read "
        f"oldest first, through {read_through}; newer changes in this window "
        "were not read. Run the import again. The next pass starts from the "
        "newest change mureo imported, so if it stops at the same point (every "
        "entry it read was mureo's own or already imported), pass "
        f"since={read_through} to continue."
    )


def _skipped_note(count: int) -> str:
    return (
        f"{count} audit-log entries had no usable timestamp inside the window "
        "and were skipped; they are not in action_log."
    )


def _capped_pass_error(problem: str) -> ChatGPTAdsAPIError:
    return ChatGPTAdsAPIError(
        f"{problem}; nothing was imported. Pass an explicit since that leaves "
        f"at most {CHANGE_FEED_ROW_CAP} audit-log entries in the window.",
        status=0,
    )


def _token(value: object, default: str = "") -> str:
    """``value`` when it is an identifier-alphabet string, else ``default``."""
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return default


def _resource_type(value: object) -> str:
    """``obj_type`` in upper snake case (``AdGroup`` → ``AD_GROUP``)."""
    return _CAMEL_BOUNDARY.sub("_", _token(value, _UNKNOWN)).upper()


def _operation(value: object) -> str:
    """The verb of ``audit_log_type`` (``update_campaign`` → ``UPDATE``)."""
    return _token(value).split("_", 1)[0].upper() or _UNKNOWN


def _changed_fields(changes: object) -> tuple[str, ...]:
    """The first :data:`MAX_CHANGED_FIELDS` usable keys of ``changes``.

    ``obj_type`` names the resource, not a field, and is not counted. The
    scan stops at the bound, so a huge object costs no more than a small one.
    """
    if not isinstance(changes, dict):
        return ()
    names = (
        key
        for key in changes
        if isinstance(key, str) and key != "obj_type" and _FIELD_NAME.fullmatch(key)
    )
    return tuple(islice(names, MAX_CHANGED_FIELDS))


def _identity(row: dict[str, Any], resource_type: str) -> dict[str, str]:
    """The ONE canonical target of a row, plus its campaign for an ad group
    or an ad.

    A row whose target id is unusable names nothing, rather than falling back
    to its campaign: the campaign alone would let a change below it match a
    mureo change to the whole campaign.
    """
    target = _token(row.get("obj_id"))
    if not target:
        return {}
    parent = {"campaign_id": c} if (c := _token(row.get("campaign_id"))) else {}
    if resource_type == "CAMPAIGN":
        return {"campaign_id": target}
    if resource_type == "AD_GROUP":
        return {**parent, "entity_type": "ad_group", "entity_id": target}
    if resource_type == "AD":
        # The ad is the target; its ad group is parent context and is not
        # promoted, the same rule mureo's own record of an ad change follows.
        return {**parent, "ad_id": target}
    return {}


def _ts(row: object, start: int, end: int) -> int | None:
    """The row's ``ts`` when it is an integer inside ``[start, end]``.

    The window the request sent is the bound: the importer's watermark is the
    newest change it stored, and one row dated in the future would move it
    past now, so every later pass would ask for an empty window.
    """
    ts = row.get("ts") if isinstance(row, dict) else None
    return ts if type(ts) is int and start <= ts <= end else None


def _row_to_change(row: object, start: int, end: int) -> ExternalChange | None:
    """Normalise one audit-log row, or ``None`` when it cannot be dated.

    The observation window and the watermark both anchor on ``ts``, so a row
    without a usable one is skipped rather than dated "now".
    """
    ts = _ts(row, start, end)
    if ts is None or not isinstance(row, dict):
        return None
    resource_type = _resource_type(row.get("obj_type"))
    return ExternalChange(
        platform=CHATGPT_ADS_PROVIDER_NAME,
        occurred_at=datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        resource_type=resource_type,
        operation=_operation(row.get("audit_log_type")),
        change_id=_token(row.get("id")),
        changed_fields=_changed_fields(row.get("changes")),
        actor=_token(row.get("actor_id")),
        **_identity(row, resource_type),
    )


def _check_oldest_first(rows: list[Any], start: int, end: int) -> None:
    """Refuse a capped pass whose datable rows go back in time.

    A capped pass imports its first rows and leaves the rest for the next
    pass, which starts from the newest change imported. Rows read newest
    first would put that point past the older rows left unread, and they
    would never be imported.
    """
    stamps = [ts for row in rows if (ts := _ts(row, start, end)) is not None]
    if stamps != sorted(stamps):
        raise _capped_pass_error(
            "the audit log did not come back oldest first, so a capped pass "
            "cannot tell which changes it left unread"
        )


def _result(rows: list[Any], start: int, end: int) -> ChangeFeedResult:
    """The feed's answer for the rows read, capped and annotated."""
    truncated = len(rows) > CHANGE_FEED_ROW_CAP
    if truncated:
        _check_oldest_first(rows, start, end)
    mapped = [_row_to_change(row, start, end) for row in rows[:CHANGE_FEED_ROW_CAP]]
    changes = tuple(change for change in mapped if change is not None)
    if truncated and not changes:
        raise _capped_pass_error(
            f"none of the first {CHANGE_FEED_ROW_CAP} audit-log entries has a "
            "usable timestamp, so the capped pass could not be dated and cannot "
            "say how far it read"
        )
    skipped = len(mapped) - len(changes)
    notes = (
        _COVERAGE_NOTE,
        *((_truncation_note(changes[-1].occurred_at),) if truncated else ()),
        *((_skipped_note(skipped),) if skipped else ()),
    )
    return ChangeFeedResult(changes=changes, truncated=truncated, notes=notes)


def _reads_account(answer: object, account_id: str) -> bool:
    """Whether the ``GET /ad_account`` answer names ``account_id``."""
    found = answer.get("id") if isinstance(answer, dict) else None
    if not isinstance(found, str) or not found:
        raise ChatGPTAdsAPIError(
            "the ad-account answer carries no usable id; nothing was imported",
            status=0,
        )
    return found == account_id


class ChatGPTAdsChangeFeed:
    """:class:`~mureo.change_import.protocol.ChangeFeedProvider` for ChatGPT Ads."""

    platform = CHATGPT_ADS_PROVIDER_NAME

    async def fetch_change_events(
        self,
        account_id: str,
        *,
        since: datetime,
        until: datetime,
    ) -> ChangeFeedResult:
        """Read the audit log for ``[since, until]``.

        A non-empty ``account_id`` must be the account the key reads, or the
        result is unavailable and the audit log is not read. A missing key
        raises the ``no_credentials`` auth error, and every client error
        propagates: the importer reports either as an ``ERROR`` outcome,
        because the window was not checked.
        """
        if since.utcoffset() is None or until.utcoffset() is None:
            # ``timestamp()`` would read a naive value as local time.
            raise ValueError("since and until must be timezone-aware")
        credentials = load_chatgpt_ads_credentials()
        if credentials is None:
            raise PlatformAuthError(
                NO_CREDENTIALS_DETAIL, cause=AUTH_CAUSE_NO_CREDENTIALS
            )
        start, end = int(since.timestamp()), int(until.timestamp())
        # Oldest first on purpose: see "A capped pass" in the module docstring.
        params = [("start_time", str(start)), ("end_time", str(end)), ("order", "asc")]

        async def _read(client: ChatGPTAdsClient) -> ChangeFeedResult:
            if account_id and not _reads_account(
                await client.get(AD_ACCOUNT_PATH), account_id
            ):
                return ChangeFeedResult(
                    unavailable_reason=_ACCOUNT_MISMATCH, notes=(_COVERAGE_NOTE,)
                )
            # One row past the cap tells a full window from a capped one.
            rows = await client.list_all(
                "/audit_logs",
                params,
                limit=CHANGE_FEED_ROW_CAP + 1,
                page_max=PAGE_MAX_AUDIT_LOGS,
            )
            return _result(rows, start, end)

        # Named here rather than left to the default so a test can shorten it.
        result = await run_with_client(
            _read, credentials.api_key, deadline=TOOL_DEADLINE_SECONDS
        )
        if account_id:
            return result
        return replace(result, notes=(*result.notes, _NO_ACCOUNT_NOTE))


__all__ = ["ChatGPTAdsChangeFeed"]
