"""Meta Ads MCP tool handler implementation -- Page posts, Instagram, Split Test, Ad Rules

Separated from _handlers_meta_ads.py to maintain the 800-line limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.mcp._handlers_meta_ads import _get_client, _no_meta_creds
from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    api_error_handler,
)

# ---------------------------------------------------------------------------
# Page post handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_page_posts_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    result = await client.list_page_posts(page_id, limit=_opt(args, "limit", 25))
    return _json_result(result)


@api_error_handler
async def handle_page_posts_boost(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    post_id = _require(args, "post_id")
    ad_set_id = _require(args, "ad_set_id")
    name = _opt(args, "name")
    result = await client.boost_post(
        page_id=page_id, post_id=post_id, ad_set_id=ad_set_id, name=name
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Instagram handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_instagram_accounts(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_instagram_accounts()
    return _json_result(result)


@api_error_handler
async def handle_instagram_media(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ig_user_id = _require(args, "ig_user_id")
    result = await client.list_instagram_media(
        ig_user_id, limit=_opt(args, "limit", 25)
    )
    return _json_result(result)


@api_error_handler
async def handle_instagram_boost(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ig_user_id = _require(args, "ig_user_id")
    media_id = _require(args, "media_id")
    ad_set_id = _require(args, "ad_set_id")
    name = _opt(args, "name")
    result = await client.boost_instagram_post(
        ig_user_id=ig_user_id, media_id=media_id, ad_set_id=ad_set_id, name=name
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Split Test (A/B test) handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_split_tests_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_split_tests(limit=_opt(args, "limit", 50))
    return _json_result(result)


@api_error_handler
async def handle_split_tests_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    study_id = _require(args, "study_id")
    result = await client.get_split_test(study_id)
    return _json_result(result)


@api_error_handler
async def handle_split_tests_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "cells": _require(args, "cells"),
        "objectives": _require(args, "objectives"),
        "start_time": _require(args, "start_time"),
        "end_time": _require(args, "end_time"),
    }
    confidence = _opt(args, "confidence_level")
    if confidence is not None:
        kwargs["confidence_level"] = confidence
    description = _opt(args, "description")
    if description is not None:
        kwargs["description"] = description
    result = await client.create_split_test(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_split_tests_end(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    study_id = _require(args, "study_id")
    result = await client.end_split_test(study_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad Rules (automated rules) handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_rules_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_rules(limit=_opt(args, "limit", 50))
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    result = await client.get_ad_rule(rule_id)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "evaluation_spec": _require(args, "evaluation_spec"),
        "execution_spec": _require(args, "execution_spec"),
    }
    schedule_spec = _opt(args, "schedule_spec")
    if schedule_spec is not None:
        kwargs["schedule_spec"] = schedule_spec
    status = _opt(args, "status")
    if status is not None:
        kwargs["status"] = status
    result = await client.create_ad_rule(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    updates: dict[str, Any] = {}
    for key in ("name", "evaluation_spec", "execution_spec", "schedule_spec", "status"):
        val = _opt(args, key)
        if val is not None:
            updates[key] = val
    result = await client.update_ad_rule(rule_id, updates)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_delete(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    result = await client.delete_ad_rule(rule_id)
    return _json_result(result)
