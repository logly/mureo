"""BYOD read-only guard regression tests for Meta mutation methods.

``ByodMetaAdsClient`` blocks writes via ``__getattr__``: any method name
whose prefix is in ``_MUTATION_PREFIXES`` returns
``{"status": "skipped_in_byod_readonly", ...}`` instead of silently
no-op'ing as an empty list. Four real POST/mutation methods
(``boost_post``, ``boost_instagram_post``, ``end_split_test``,
``duplicate_lead_form``) plus the local-file writer
``export_leads_to_csv`` did not match any prefix and previously fell
through to ``_async_empty_list`` — an empty list that masks a would-be
write. This test pins the fix.

The BYOD client has no network layer, so calling a mutation on it can
never reach a real ad account; asserting the skip payload also proves
the call is inert.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from mureo.byod.clients import ByodMetaAdsClient

if TYPE_CHECKING:
    from pathlib import Path

_MUTATION_METHODS = (
    "boost_post",
    "boost_instagram_post",
    "end_split_test",
    "duplicate_lead_form",
    "export_leads_to_csv",
)


def _client(tmp_path: Path) -> ByodMetaAdsClient:
    # Point at an empty (non-existent) data dir — reads return []; the
    # methods under test never touch it anyway.
    return ByodMetaAdsClient(data_dir=tmp_path / "meta_ads")


@pytest.mark.unit
@pytest.mark.parametrize("method_name", _MUTATION_METHODS)
def test_mutation_method_is_skipped_in_byod(tmp_path: Path, method_name: str) -> None:
    client = _client(tmp_path)
    method = getattr(client, method_name)
    result = asyncio.run(method(some="arg", another=1))
    assert isinstance(result, dict)
    assert result["status"] == "skipped_in_byod_readonly"
    assert result["operation"] == method_name


@pytest.mark.unit
def test_read_methods_still_return_data_not_skipped(tmp_path: Path) -> None:
    """The new prefixes must not accidentally flip read methods into the
    skip path. A ``get_``/``list_`` call still returns a data shape."""
    client = _client(tmp_path)
    campaigns = asyncio.run(client.list_campaigns())
    assert isinstance(campaigns, list)
    # An undefined read-style name falls through to the empty-list stub,
    # NOT the mutation-skip stub.
    end_of_nothing = asyncio.run(client.get_something_readonly())
    assert end_of_nothing == []
