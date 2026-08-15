"""Performance Max asset-group assets — read + text swap (#590, #626).

Covers ``_AssetGroupsMixin``: the read of the assets linked to a
Performance Max asset group — the HEADLINE / LONG_HEADLINE / DESCRIPTION
text of #590 and the five image field types of #626, in one query — and
the swap that replaces one text asset. The image swap has its own module,
``tests/test_google_ads_asset_group_images.py``.

**Real SDK messages, faked transport.** A ``GoogleAdsClient`` built with
mock credentials opens no channel until a call is actually issued, so the
tests below run the production code against the real v23 protos: the
operations the swap builds, the enums it sets and the resource-name paths
it derives are the ones the API would receive. Only ``_search`` and the
outbound ``GoogleAdsService.mutate`` are replaced. A ``MagicMock`` client
would have accepted any misspelt field name, which is the failure mode
``tests/test_gaql_field_names.py`` exists to prevent one layer up.

What is NOT covered here, and is only reasoned about from the API
reference: whether Google's asset-count validation runs on the request's
final state (the premise behind sending create-link + remove-link as one
atomic mutate). No live P-MAX account is available to this suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.ads.googleads import util
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v23.services.types.asset_group_asset_service import (
    MutateAssetGroupAssetResult,
)
from google.ads.googleads.v23.services.types.asset_service import MutateAssetResult
from google.ads.googleads.v23.services.types.google_ads_service import (
    GoogleAdsRow,
    MutateGoogleAdsResponse,
    MutateOperationResponse,
)

from mureo.google_ads._asset_groups import (
    PMAX_IMAGE_FIELD_TYPES,
    PMAX_TEXT_FIELD_TYPES,
)
from mureo.google_ads.client import GoogleAdsApiClient

CUSTOMER_ID = "1234567890"

# AssetFieldTypeEnum values, spelled out so the fixtures do not depend on
# the same lookup the production mapper uses.
HEADLINE = 2
DESCRIPTION = 3
LONG_HEADLINE = 17
MARKETING_IMAGE = 5
SQUARE_MARKETING_IMAGE = 19
LOGO = 21
_FIELD_TYPE_NAMES = {
    HEADLINE: "HEADLINE",
    DESCRIPTION: "DESCRIPTION",
    LONG_HEADLINE: "LONG_HEADLINE",
    MARKETING_IMAGE: "MARKETING_IMAGE",
    SQUARE_MARKETING_IMAGE: "SQUARE_MARKETING_IMAGE",
    LOGO: "LOGO",
}


def _make_client() -> GoogleAdsApiClient:
    """A client whose SDK layer is real and whose transport is not."""
    return GoogleAdsApiClient(
        credentials=MagicMock(),
        customer_id=CUSTOMER_ID,
        developer_token="test-token",
    )


def _row(
    *,
    asset_id: int = 111,
    text: str = "Old headline",
    field_type: int = HEADLINE,
    status: int = 2,  # AssetLinkStatusEnum.ENABLED
    asset_group_id: int = 4242,
    asset_group_name: str = "PMax JP",
    campaign_id: int = 900,
) -> Any:
    """One ``asset_group_asset`` row, in the raw-protobuf shape the client
    receives in production (``use_proto_plus=False``)."""
    row = GoogleAdsRow()
    link = row.asset_group_asset
    link.resource_name = (
        f"customers/{CUSTOMER_ID}/assetGroupAssets/"
        f"{asset_group_id}~{asset_id}~{_FIELD_TYPE_NAMES[field_type]}"
    )
    link.field_type = field_type
    link.status = status
    row.asset.id = asset_id
    row.asset.text_asset.text = text
    row.asset_group.id = asset_group_id
    row.asset_group.name = asset_group_name
    row.asset_group.campaign = f"customers/{CUSTOMER_ID}/campaigns/{campaign_id}"
    return util.convert_proto_plus_to_protobuf(row)


def _image_row(
    *,
    asset_id: int = 555,
    asset_name: str = "Spring hero",
    field_type: int = MARKETING_IMAGE,
    url: str = "https://tpc.googlesyndication.com/simgad/555",
    width: int = 1200,
    height: int = 628,
    status: int = 2,  # AssetLinkStatusEnum.ENABLED
    asset_group_id: int = 4242,
    asset_group_name: str = "PMax JP",
    campaign_id: int = 900,
) -> Any:
    """One image ``asset_group_asset`` row, raw-protobuf shaped."""
    row = GoogleAdsRow()
    link = row.asset_group_asset
    link.resource_name = (
        f"customers/{CUSTOMER_ID}/assetGroupAssets/"
        f"{asset_group_id}~{asset_id}~{_FIELD_TYPE_NAMES[field_type]}"
    )
    link.field_type = field_type
    link.status = status
    row.asset.id = asset_id
    row.asset.name = asset_name
    row.asset.image_asset.full_size.url = url
    row.asset.image_asset.full_size.width_pixels = width
    row.asset.image_asset.full_size.height_pixels = height
    row.asset_group.id = asset_group_id
    row.asset_group.name = asset_group_name
    row.asset_group.campaign = f"customers/{CUSTOMER_ID}/campaigns/{campaign_id}"
    return util.convert_proto_plus_to_protobuf(row)


def _mutate_response() -> Any:
    """The three-result response the atomic swap produces."""
    response = MutateGoogleAdsResponse(
        mutate_operation_responses=[
            MutateOperationResponse(
                asset_result=MutateAssetResult(
                    resource_name=f"customers/{CUSTOMER_ID}/assets/777"
                )
            ),
            MutateOperationResponse(
                asset_group_asset_result=MutateAssetGroupAssetResult(
                    resource_name=(
                        f"customers/{CUSTOMER_ID}/assetGroupAssets/4242~777~HEADLINE"
                    )
                )
            ),
            MutateOperationResponse(
                asset_group_asset_result=MutateAssetGroupAssetResult(
                    resource_name=(
                        f"customers/{CUSTOMER_ID}/assetGroupAssets/4242~111~HEADLINE"
                    )
                )
            ),
        ]
    )
    return util.convert_proto_plus_to_protobuf(response)


def _google_ads_exception(*error_names: str) -> GoogleAdsException:
    """A ``GoogleAdsException`` carrying ``asset_group_error`` codes.

    ``_has_error_code`` reads ``error.error_code.<attr>.name``, so the
    stand-in only needs that shape.

    Built through ``__new__`` rather than the real constructor, and it
    installs the ``failure`` property itself: ``tests/test_google_ads_ads.py``
    replaces ``GoogleAdsException.failure`` with a read-only property at class
    level and never restores it, so the constructor's ``self.failure = ...``
    raises for every module collected after it. Mirroring that helper's idiom
    makes this one independent of collection order.
    """
    errors = []
    for name in error_names:
        error = MagicMock()
        error.message = f"server said: {name}"
        error.error_code.asset_group_error.name = name
        errors.append(error)
    failure = MagicMock()
    failure.errors = errors
    exc = GoogleAdsException.__new__(GoogleAdsException)
    # Assign on the INSTANCE. `type(exc)` is GoogleAdsException itself, so a
    # class-level property here would edit the class for the rest of the
    # session and make the real __init__ (`self.failure = failure`) raise
    # AttributeError in every module collected afterwards. `failure` is a
    # plain instance attribute, so the property was never needed.
    exc.failure = failure
    exc._call = MagicMock()
    exc._request_id = "req-1"
    return exc


def _install_fake_mutate(client: GoogleAdsApiClient, response: Any) -> list[Any]:
    """Capture the operations the client sends; return the capture list."""
    captured: list[Any] = []
    service = MagicMock()

    def _mutate(
        *, customer_id: str, mutate_operations: list[Any], **kwargs: Any
    ) -> Any:
        captured.append((customer_id, list(mutate_operations), kwargs))
        if isinstance(response, Exception):
            raise response
        return response

    service.mutate.side_effect = _mutate
    real_get_service = client._get_service

    def _get_service(name: str) -> Any:
        if name == "GoogleAdsService":
            return service
        return real_get_service(name)

    client._get_service = _get_service  # type: ignore[method-assign]
    return captured


# ---------------------------------------------------------------------------
# list_asset_group_assets
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAssetGroupTextAssets:
    async def test_query_targets_asset_group_asset_and_the_three_text_types(
        self,
    ) -> None:
        """The read that #590 says returns nothing today: P-MAX text lives on
        ``asset_group_asset``, not on ``ad_group_ad``."""
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_asset_group_assets()

        assert len(queries) == 1
        assert "FROM asset_group_asset" in queries[0]
        assert "asset.text_asset.text" in queries[0]
        for field_type in PMAX_TEXT_FIELD_TYPES:
            assert f"'{field_type}'" in queries[0]

    async def test_one_query_covers_the_images_too(self) -> None:
        """#626: "show me this asset group's creative" must not need two
        calls, and a text-only read is how #591's field report concluded a
        P-MAX account had no creative at all."""
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_asset_group_assets()

        assert len(queries) == 1, "text and images come back in one round trip"
        for field_type in PMAX_IMAGE_FIELD_TYPES:
            assert f"'{field_type}'" in queries[0]
        for column in (
            "asset.name",
            "asset.image_asset.full_size.url",
            "asset.image_asset.full_size.width_pixels",
            "asset.image_asset.full_size.height_pixels",
        ):
            assert column in queries[0]

    async def test_video_field_types_are_not_selected(self) -> None:
        """Out of scope by design: a video asset references a YouTube id
        rather than uploaded bytes, so it is a different entry shape."""
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_asset_group_assets()

        for field_type in ("YOUTUBE_VIDEO", "VIDEO", "RELATED_YOUTUBE_VIDEOS"):
            assert f"'{field_type}'" not in queries[0]

    async def test_image_rows_carry_the_picture_and_its_dimensions(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_image_row()]

        client._search = _search  # type: ignore[method-assign]
        (entry,) = await client.list_asset_group_assets()

        assert entry["field_type"] == "MARKETING_IMAGE"
        assert entry["asset_id"] == "555"
        assert entry["asset_name"] == "Spring hero"
        assert entry["url"] == "https://tpc.googlesyndication.com/simgad/555"
        assert entry["width_pixels"] == 1200
        assert entry["height_pixels"] == 628
        assert entry["status"] == "ENABLED"
        assert entry["asset_group_id"] == "4242"
        assert entry["campaign_id"] == "900"
        assert "text" not in entry, "an image link has no text to report"

    async def test_text_rows_are_unchanged_by_the_image_half(self) -> None:
        """#590's row shape is a contract: the image half added no key to a
        text row and removed none."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_row(asset_id=111, text="Old headline"), _image_row()]

        client._search = _search  # type: ignore[method-assign]
        text_entry, image_entry = await client.list_asset_group_assets()

        assert set(text_entry) == {
            "resource_name",
            "field_type",
            "status",
            "asset_id",
            "text",
            "asset_group_id",
            "asset_group_name",
            "campaign_id",
            "campaign_resource_name",
        }
        assert set(image_entry) - set(text_entry) == {
            "asset_name",
            "url",
            "width_pixels",
            "height_pixels",
        }
        assert set(text_entry) - set(image_entry) == {"text"}

    async def test_both_kinds_come_back_from_one_call_in_api_order(self) -> None:
        client = _make_client()
        rows = [
            _image_row(asset_id=555, field_type=MARKETING_IMAGE),
            _row(asset_id=111, text="A headline"),
            _image_row(
                asset_id=556,
                field_type=LOGO,
                width=1200,
                height=1200,
                asset_name="Logo",
            ),
        ]

        async def _search(query: str) -> list[Any]:
            return rows

        client._search = _search  # type: ignore[method-assign]
        result = await client.list_asset_group_assets()

        assert [r["asset_id"] for r in result] == ["555", "111", "556"]
        assert [r["field_type"] for r in result] == [
            "MARKETING_IMAGE",
            "HEADLINE",
            "LOGO",
        ]

    async def test_returns_every_row_the_api_returned_in_order(self) -> None:
        """No summing, no dedupe, no reordering — three identical texts under
        the same field type are three rows, because that is what is linked."""
        client = _make_client()
        rows = [
            _row(asset_id=1, text="Same", field_type=HEADLINE),
            _row(asset_id=2, text="Same", field_type=HEADLINE),
            _row(asset_id=3, text="Long one", field_type=LONG_HEADLINE),
        ]

        async def _search(query: str) -> list[Any]:
            return rows

        client._search = _search  # type: ignore[method-assign]
        result = await client.list_asset_group_assets()

        assert [r["asset_id"] for r in result] == ["1", "2", "3"]
        assert [r["text"] for r in result] == ["Same", "Same", "Long one"]
        assert [r["field_type"] for r in result] == [
            "HEADLINE",
            "HEADLINE",
            "LONG_HEADLINE",
        ]

    async def test_row_carries_the_removal_handle_and_its_parents(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_row(asset_id=111, text="Old headline")]

        client._search = _search  # type: ignore[method-assign]
        (entry,) = await client.list_asset_group_assets()

        assert entry["resource_name"].startswith(
            f"customers/{CUSTOMER_ID}/assetGroupAssets/"
        )
        assert entry["asset_id"] == "111"
        assert entry["status"] == "ENABLED"
        assert entry["asset_group_id"] == "4242"
        assert entry["asset_group_name"] == "PMax JP"
        assert entry["campaign_id"] == "900"
        assert (
            entry["campaign_resource_name"] == f"customers/{CUSTOMER_ID}/campaigns/900"
        )

    async def test_filters_by_asset_group_and_campaign(self) -> None:
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_asset_group_assets(asset_group_id="4242", campaign_id="900")

        assert "asset_group.id = 4242" in queries[0]
        assert (
            f"asset_group.campaign = 'customers/{CUSTOMER_ID}/campaigns/900'"
            in queries[0]
        )

    @pytest.mark.parametrize("bad", ["4242; DROP", "４２４２", "abc"])
    async def test_rejects_non_numeric_asset_group_id(self, bad: str) -> None:
        """Full-width digits included — the ASCII-only ID whitelist (#441)."""
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await client.list_asset_group_assets(asset_group_id=bad)

    async def test_an_empty_filter_is_no_filter_not_an_error(self) -> None:
        """Matches ``list_ads``: a falsy filter means "whole account"."""
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_asset_group_assets(asset_group_id="", campaign_id="")

        # Not a bare "AND": LANDSCAPE_LOGO in the IN clause contains one.
        assert "AND asset_group." not in queries[0]


# ---------------------------------------------------------------------------
# replace_asset_group_text_asset
# ---------------------------------------------------------------------------


def _current_rows() -> list[Any]:
    return [
        _row(asset_id=111, text="Old headline", field_type=HEADLINE),
        _row(asset_id=112, text="Kept headline", field_type=HEADLINE),
        _row(asset_id=113, text="Third headline", field_type=HEADLINE),
        _row(asset_id=222, text="A description", field_type=DESCRIPTION),
    ]


def _swap_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "asset_group_id": "4242",
        "field_type": "HEADLINE",
        "old_asset_id": "111",
        "new_text": "Brand new headline",
    }
    params.update(overrides)
    return params


@pytest.mark.unit
class TestReplaceAssetGroupTextAsset:
    async def test_sends_one_atomic_mutate_with_create_link_then_unlink(
        self,
    ) -> None:
        """The whole point of #590's write half: a text ``Asset`` is immutable,
        so the swap is create + link + unlink — and all three go in ONE request
        so the asset group never dips below the P-MAX minimum."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_text_asset(_swap_params())

        assert len(captured) == 1, "the swap must be a single request"
        customer_id, operations, kwargs = captured[0]
        assert customer_id == CUSTOMER_ID
        assert len(operations) == 3
        # Order: the replacement exists before the old link is dropped.
        assert operations[0].WhichOneof("operation") == "asset_operation"
        assert operations[1].WhichOneof("operation") == "asset_group_asset_operation"
        assert operations[1].asset_group_asset_operation.WhichOneof("operation") == (
            "create"
        )
        assert operations[2].asset_group_asset_operation.WhichOneof("operation") == (
            "remove"
        )
        # Atomicity is the guard against the count floor: partial_failure would
        # let the remove land on its own.
        assert kwargs.get("partial_failure") in (None, False)

    async def test_new_asset_is_created_and_referenced_by_temp_resource_name(
        self,
    ) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_text_asset(_swap_params())

        _, operations, _ = captured[0]
        created_asset = operations[0].asset_operation.create
        assert created_asset.text_asset.text == "Brand new headline"
        temp_name = created_asset.resource_name
        assert temp_name == f"customers/{CUSTOMER_ID}/assets/-1"

        link = operations[1].asset_group_asset_operation.create
        assert link.asset == temp_name
        assert link.asset_group == f"customers/{CUSTOMER_ID}/assetGroups/4242"
        assert link.field_type == HEADLINE

    async def test_removes_the_link_of_the_named_old_asset(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_text_asset(_swap_params())

        _, operations, _ = captured[0]
        assert operations[2].asset_group_asset_operation.remove == (
            f"customers/{CUSTOMER_ID}/assetGroupAssets/4242~111~HEADLINE"
        )

    async def test_result_reports_both_sides_of_the_swap(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        _install_fake_mutate(client, _mutate_response())

        result = await client.replace_asset_group_text_asset(_swap_params())

        assert result["asset_group_id"] == "4242"
        assert result["field_type"] == "HEADLINE"
        assert result["removed"]["asset_id"] == "111"
        assert result["removed"]["text"] == "Old headline"
        assert result["added"]["text"] == "Brand new headline"
        assert result["added"]["asset_id"] == "777"
        assert result["added"]["asset_resource_name"] == (
            f"customers/{CUSTOMER_ID}/assets/777"
        )

    async def test_long_headline_uses_its_own_field_type_and_limit(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_row(asset_id=333, text="Old long", field_type=LONG_HEADLINE)]

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_text_asset(
            _swap_params(
                field_type="LONG_HEADLINE",
                old_asset_id="333",
                new_text="x" * 90,
            )
        )

        _, operations, _ = captured[0]
        assert operations[1].asset_group_asset_operation.create.field_type == (
            LONG_HEADLINE
        )
        assert operations[2].asset_group_asset_operation.remove.endswith(
            "~333~LONG_HEADLINE"
        )

    async def test_refuses_an_asset_id_that_is_not_linked_under_that_field_type(
        self,
    ) -> None:
        """The description asset 222 exists, but not as a HEADLINE."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="222"):
            await client.replace_asset_group_text_asset(
                _swap_params(old_asset_id="222")
            )
        assert not captured, "no mutate may be sent when the target is unknown"

    async def test_refuses_text_already_linked_under_the_same_field_type(
        self,
    ) -> None:
        """Google rejects a duplicate link; say so before spending the call."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="already"):
            await client.replace_asset_group_text_asset(
                _swap_params(new_text="Kept headline")
            )
        assert not captured

    @pytest.mark.parametrize(
        "field_type,text",
        [
            ("HEADLINE", "x" * 31),
            ("LONG_HEADLINE", "x" * 91),
            ("DESCRIPTION", "x" * 91),
            ("HEADLINE", "あ" * 16),  # display width 32
        ],
    )
    async def test_refuses_text_over_the_field_type_limit(
        self, field_type: str, text: str
    ) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="width"):
            await client.replace_asset_group_text_asset(
                _swap_params(field_type=field_type, new_text=text)
            )

    @pytest.mark.parametrize("text", ["", "   "])
    async def test_refuses_blank_text(self, text: str) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await client.replace_asset_group_text_asset(_swap_params(new_text=text))

    @pytest.mark.parametrize("field_type", ["SITELINK", "MARKETING_IMAGE", "headline "])
    async def test_refuses_a_field_type_outside_the_three_text_types(
        self, field_type: str
    ) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="field_type"):
            await client.replace_asset_group_text_asset(
                _swap_params(field_type=field_type)
            )

    @pytest.mark.parametrize("key", ["asset_group_id", "old_asset_id"])
    async def test_refuses_non_numeric_ids(self, key: str) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match=key):
            await client.replace_asset_group_text_asset(_swap_params(**{key: "4242'"}))

    async def test_not_enough_asset_error_becomes_an_actionable_message(
        self,
    ) -> None:
        """``AssetGroupError.NOT_ENOUGH_HEADLINE_ASSET`` is the floor refusal the
        issue names; it must not reach the agent as a raw API error."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        _install_fake_mutate(client, _google_ads_exception("NOT_ENOUGH_HEADLINE_ASSET"))

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_text_asset(_swap_params())

        message = str(excinfo.value)
        assert "NOT_ENOUGH_HEADLINE_ASSET" in message
        assert "minimum" in message.lower()

    async def test_other_api_errors_keep_the_curated_server_detail(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return _current_rows()

        client._search = _search  # type: ignore[method-assign]
        _install_fake_mutate(client, _google_ads_exception("DUPLICATE_NAME"))

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_text_asset(_swap_params())

        assert "server said: DUPLICATE_NAME" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFieldTypeConstants:
    def test_the_query_and_the_two_tables_name_the_same_field_types(self) -> None:
        """The GAQL ``IN`` clause is a static literal (so it can carry the
        ``validate_static_query`` marker); this stops it drifting from the
        two tables the write halves validate against."""
        from mureo.google_ads._asset_groups import _ASSET_QUERY

        expected = set(PMAX_TEXT_FIELD_TYPES) | set(PMAX_IMAGE_FIELD_TYPES)
        for field_type in expected:
            assert f"'{field_type}'" in _ASSET_QUERY
        quoted = _ASSET_QUERY.split("IN (")[1].split(")")[0]
        assert quoted.count("'") == 2 * len(expected)

    def test_the_two_tables_do_not_overlap(self) -> None:
        """Parallel, not shared: a text field type carries a width limit and
        an image field type carries a shape."""
        assert not set(PMAX_TEXT_FIELD_TYPES) & set(PMAX_IMAGE_FIELD_TYPES)

    def test_every_field_type_is_a_real_asset_field_type_enum_member(self) -> None:
        from google.ads.googleads.v23.enums.types.asset_field_type import (
            AssetFieldTypeEnum,
        )

        names = {member.name for member in AssetFieldTypeEnum.AssetFieldType}
        assert set(PMAX_TEXT_FIELD_TYPES) <= names
        assert set(PMAX_IMAGE_FIELD_TYPES) <= names

    def test_the_image_table_excludes_the_non_asset_group_image_types(self) -> None:
        """``AssetFieldTypeEnum`` has eight image field types; three of them
        are not Performance Max asset-group slots. Pinned so a later "the
        enum has more, add them" edit has to argue with this."""
        excluded = {"TALL_PORTRAIT_MARKETING_IMAGE", "BUSINESS_LOGO", "AD_IMAGE"}
        assert not excluded & set(PMAX_IMAGE_FIELD_TYPES)

    def test_every_required_image_type_has_an_asset_count_floor(self) -> None:
        """The SDK's own corroboration that these are asset-group slots:
        ``AssetGroupErrorEnum`` defines ``NOT_ENOUGH_*`` for exactly the
        three required image field types and for no other."""
        from google.ads.googleads.v23.errors.types.asset_group_error import (
            AssetGroupErrorEnum,
        )

        from mureo.google_ads._asset_groups_images import (
            _NOT_ENOUGH_IMAGE_ASSET_ERRORS,
        )

        codes = {m.name for m in AssetGroupErrorEnum.AssetGroupError}
        assert set(_NOT_ENOUGH_IMAGE_ASSET_ERRORS) <= codes
        floors = {c for c in codes if c.startswith("NOT_ENOUGH_")}
        image_floors = {
            c
            for c in floors
            if any(f"NOT_ENOUGH_{ft}_ASSET" == c for ft in PMAX_IMAGE_FIELD_TYPES)
        }
        assert image_floors == set(_NOT_ENOUGH_IMAGE_ASSET_ERRORS)

    def test_the_dimension_rules_are_self_consistent(self) -> None:
        """Each spec's own minimum has to satisfy the ratio it declares —
        otherwise the smallest allowed image would be refused by the very
        check the same table drives."""
        from mureo.google_ads._asset_groups import _validate_image_dimensions

        for field_type, spec in PMAX_IMAGE_FIELD_TYPES.items():
            _validate_image_dimensions(field_type, spec.min_width, spec.min_height)
            width, height = (int(part) for part in spec.recommended.split("x"))
            _validate_image_dimensions(field_type, width, height)


@pytest.mark.unit
def test_mixin_is_composed_into_the_client() -> None:
    with patch("mureo.google_ads.client.GoogleAdsClient"):
        client = GoogleAdsApiClient(
            credentials=MagicMock(),
            customer_id=CUSTOMER_ID,
            developer_token="t",
        )
    assert hasattr(client, "list_asset_group_assets")
    assert hasattr(client, "replace_asset_group_text_asset")
    assert hasattr(client, "replace_asset_group_image_asset")
