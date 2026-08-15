"""Performance Max asset-group image swap (#626).

Covers ``_AssetGroupImagesMixin``: replacing one image or logo of a
Performance Max asset group, from either entry point — an image asset the
account already holds, or a local file that has to be uploaded first.

**Real SDK messages, faked transport.** As in
``tests/test_google_ads_asset_groups.py``: a ``GoogleAdsClient`` built with
mock credentials opens no channel until a call is issued, so the production
code below runs against the real v23 protos — the operations it builds, the
enums it sets and the resource-name paths it derives are the ones the API
would receive. Only ``_search``, ``upload_image_asset`` and the outbound
``GoogleAdsService.mutate`` are replaced. A ``MagicMock`` client would have
accepted any misspelt field name.

What is NOT covered here and is only reasoned about from the API reference:

- whether Google's asset-count validation runs on the request's final state
  (the premise behind sending link + unlink as one atomic mutate);
- the exact dimension and aspect-ratio figures per field type — they come
  from Google's Performance Max asset-requirements page, not from anything
  the SDK declares. What IS pinned here is that mureo applies them
  consistently, never resizes, and translates the server's refusal when it
  could not check for itself.

No live P-MAX account is available to this suite.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.ads.googleads import util
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v23.services.types.asset_group_asset_service import (
    MutateAssetGroupAssetResult,
)
from google.ads.googleads.v23.services.types.google_ads_service import (
    GoogleAdsRow,
    MutateGoogleAdsResponse,
    MutateOperationResponse,
)

from mureo.google_ads._asset_groups import PMAX_IMAGE_FIELD_TYPES
from mureo.google_ads.client import GoogleAdsApiClient

CUSTOMER_ID = "1234567890"

# AssetFieldTypeEnum / AssetTypeEnum values, spelled out so the fixtures do
# not depend on the same lookup the production mappers use.
MARKETING_IMAGE = 5
SQUARE_MARKETING_IMAGE = 19
LOGO = 21
LANDSCAPE_LOGO = 22
HEADLINE = 2
ASSET_TYPE_IMAGE = 4
ASSET_TYPE_TEXT = 5

_FIELD_TYPE_NAMES = {
    MARKETING_IMAGE: "MARKETING_IMAGE",
    SQUARE_MARKETING_IMAGE: "SQUARE_MARKETING_IMAGE",
    LOGO: "LOGO",
    LANDSCAPE_LOGO: "LANDSCAPE_LOGO",
    HEADLINE: "HEADLINE",
}


def _make_client() -> GoogleAdsApiClient:
    """A client whose SDK layer is real and whose transport is not."""
    return GoogleAdsApiClient(
        credentials=MagicMock(),
        customer_id=CUSTOMER_ID,
        developer_token="test-token",
    )


def _link_row(
    *,
    asset_id: int = 555,
    asset_name: str = "Spring hero",
    field_type: int = MARKETING_IMAGE,
    url: str = "https://tpc.googlesyndication.com/simgad/555",
    width: int = 1200,
    height: int = 628,
    asset_group_id: int = 4242,
) -> Any:
    """One ``asset_group_asset`` row for the group's current images."""
    row = GoogleAdsRow()
    link = row.asset_group_asset
    link.resource_name = (
        f"customers/{CUSTOMER_ID}/assetGroupAssets/"
        f"{asset_group_id}~{asset_id}~{_FIELD_TYPE_NAMES[field_type]}"
    )
    link.field_type = field_type
    link.status = 2  # ENABLED
    row.asset.id = asset_id
    row.asset.name = asset_name
    row.asset.image_asset.full_size.url = url
    row.asset.image_asset.full_size.width_pixels = width
    row.asset.image_asset.full_size.height_pixels = height
    row.asset_group.id = asset_group_id
    row.asset_group.name = "PMax JP"
    row.asset_group.campaign = f"customers/{CUSTOMER_ID}/campaigns/900"
    return util.convert_proto_plus_to_protobuf(row)


def _asset_row(
    *,
    asset_id: int = 777,
    name: str = "New hero",
    asset_type: int = ASSET_TYPE_IMAGE,
    width: int = 1200,
    height: int = 628,
) -> Any:
    """One ``asset`` row, as the new-asset lookup receives it."""
    row = GoogleAdsRow()
    row.asset.id = asset_id
    row.asset.name = name
    row.asset.type_ = asset_type
    row.asset.image_asset.full_size.url = (
        f"https://tpc.googlesyndication.com/simgad/{asset_id}"
    )
    row.asset.image_asset.full_size.width_pixels = width
    row.asset.image_asset.full_size.height_pixels = height
    return util.convert_proto_plus_to_protobuf(row)


def _current_links() -> list[Any]:
    return [
        _link_row(asset_id=555, asset_name="Spring hero", field_type=MARKETING_IMAGE),
        _link_row(asset_id=556, asset_name="Kept hero", field_type=MARKETING_IMAGE),
        _link_row(
            asset_id=557,
            asset_name="Square one",
            field_type=SQUARE_MARKETING_IMAGE,
            width=1200,
            height=1200,
        ),
    ]


def _install_search(
    client: GoogleAdsApiClient,
    *,
    links: list[Any] | None = None,
    assets: list[Any] | None = None,
) -> list[str]:
    """Route the two reads the swap makes; return the captured queries."""
    queries: list[str] = []

    async def _search(query: str) -> list[Any]:
        queries.append(query)
        if "FROM asset_group_asset" in query:
            return _current_links() if links is None else links
        return [_asset_row()] if assets is None else assets

    client._search = _search  # type: ignore[method-assign]
    return queries


def _mutate_response() -> Any:
    """The two-result response the atomic image swap produces."""
    response = MutateGoogleAdsResponse(
        mutate_operation_responses=[
            MutateOperationResponse(
                asset_group_asset_result=MutateAssetGroupAssetResult(
                    resource_name=(
                        f"customers/{CUSTOMER_ID}/assetGroupAssets/"
                        "4242~777~MARKETING_IMAGE"
                    )
                )
            ),
            MutateOperationResponse(
                asset_group_asset_result=MutateAssetGroupAssetResult(
                    resource_name=(
                        f"customers/{CUSTOMER_ID}/assetGroupAssets/"
                        "4242~555~MARKETING_IMAGE"
                    )
                )
            ),
        ]
    )
    return util.convert_proto_plus_to_protobuf(response)


def _google_ads_exception(attr_name: str, *error_names: str) -> GoogleAdsException:
    """A ``GoogleAdsException`` carrying error codes under ``attr_name``.

    ``_has_error_code`` reads ``error.error_code.<attr>.name``, so the
    stand-in only needs that shape. Built through ``__new__``, with
    ``failure`` assigned on the INSTANCE — assigning through ``type(exc)``
    would edit ``GoogleAdsException`` for the rest of the session and break
    every module collected afterwards (#624).

    ``error_code`` is a ``MagicMock``, which answers every attribute, so the
    codes are also set to a non-matching name on the sibling attribute this
    module's production code queries. Without that, a lookup against the
    wrong attribute would match anyway and the test would prove nothing.
    """
    other = "asset_group_error" if attr_name == "image_error" else "image_error"
    errors = []
    for name in error_names:
        error = MagicMock()
        error.message = f"server said: {name}"
        getattr(error.error_code, attr_name).name = name
        getattr(error.error_code, other).name = "UNSPECIFIED"
        errors.append(error)
    failure = MagicMock()
    failure.errors = errors
    exc = GoogleAdsException.__new__(GoogleAdsException)
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


def _install_fake_upload(client: GoogleAdsApiClient) -> list[Any]:
    """Replace the upload; return the capture list."""
    captured: list[Any] = []

    async def _upload(file_path: str, name: str | None = None) -> dict[str, Any]:
        captured.append((file_path, name))
        return {
            "resource_name": f"customers/{CUSTOMER_ID}/assets/888",
            "id": "888",
            "name": name or Path(file_path).name,
        }

    client.upload_image_asset = _upload  # type: ignore[method-assign]
    return captured


def _write_png(path: Path, width: int, height: int) -> Path:
    """A real PNG header the std-lib prober can measure."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    chunk += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)
    return path


def _swap_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "asset_group_id": "4242",
        "field_type": "MARKETING_IMAGE",
        "old_asset_id": "555",
        "new_asset_id": "777",
    }
    params.update(overrides)
    return params


# ---------------------------------------------------------------------------
# The swap itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReplaceAssetGroupImageAsset:
    async def test_sends_one_atomic_mutate_with_the_link_before_the_unlink(
        self,
    ) -> None:
        """Two operations, not three: an image Asset exists before the asset
        group can point at it. Both go in ONE request so the asset group
        never dips below the P-MAX minimum for the field type."""
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_image_asset(_swap_params())

        assert len(captured) == 1, "the swap must be a single request"
        customer_id, operations, kwargs = captured[0]
        assert customer_id == CUSTOMER_ID
        assert len(operations) == 2
        assert operations[0].asset_group_asset_operation.WhichOneof("operation") == (
            "create"
        )
        assert operations[1].asset_group_asset_operation.WhichOneof("operation") == (
            "remove"
        )
        # Atomicity is the guard against the count floor: partial_failure
        # would let the remove land on its own.
        assert kwargs.get("partial_failure") in (None, False)

    async def test_links_the_named_asset_under_the_named_field_type(self) -> None:
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_image_asset(_swap_params())

        _, operations, _ = captured[0]
        link = operations[0].asset_group_asset_operation.create
        assert link.asset == f"customers/{CUSTOMER_ID}/assets/777"
        assert link.asset_group == f"customers/{CUSTOMER_ID}/assetGroups/4242"
        assert link.field_type == MARKETING_IMAGE
        assert operations[1].asset_group_asset_operation.remove == (
            f"customers/{CUSTOMER_ID}/assetGroupAssets/4242~555~MARKETING_IMAGE"
        )

    async def test_no_asset_is_created_inside_the_mutate(self) -> None:
        """The text swap creates its Asset in-request because a text Asset is
        immutable. An image asset already exists — creating a second copy of
        the same bytes would be pure account clutter."""
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_image_asset(_swap_params())

        _, operations, _ = captured[0]
        assert all(
            op.WhichOneof("operation") == "asset_group_asset_operation"
            for op in operations
        )

    async def test_result_reports_both_sides_of_the_swap(self) -> None:
        client = _make_client()
        _install_search(client)
        _install_fake_mutate(client, _mutate_response())

        result = await client.replace_asset_group_image_asset(_swap_params())

        assert result["asset_group_id"] == "4242"
        assert result["field_type"] == "MARKETING_IMAGE"
        assert result["added"]["asset_id"] == "777"
        assert result["added"]["asset_name"] == "New hero"
        assert result["added"]["width_pixels"] == 1200
        assert result["added"]["height_pixels"] == 628
        assert result["added"]["source"] == "existing_asset"
        assert result["added"]["asset_group_asset"].endswith("4242~777~MARKETING_IMAGE")
        assert result["removed"]["asset_id"] == "555"
        assert result["removed"]["asset_name"] == "Spring hero"
        assert result["removed"]["url"].endswith("/555")
        assert result["removed"]["asset_group_asset"].endswith(
            "4242~555~MARKETING_IMAGE"
        )

    async def test_a_logo_uses_its_own_field_type_and_shape(self) -> None:
        client = _make_client()
        _install_search(
            client,
            links=[
                _link_row(
                    asset_id=600,
                    asset_name="Old logo",
                    field_type=LOGO,
                    width=1200,
                    height=1200,
                )
            ],
            assets=[_asset_row(asset_id=601, width=512, height=512)],
        )
        captured = _install_fake_mutate(client, _mutate_response())

        await client.replace_asset_group_image_asset(
            _swap_params(field_type="LOGO", old_asset_id="600", new_asset_id="601")
        )

        _, operations, _ = captured[0]
        assert operations[0].asset_group_asset_operation.create.field_type == LOGO
        assert operations[1].asset_group_asset_operation.remove.endswith("~600~LOGO")


# ---------------------------------------------------------------------------
# The two entry points
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNewImageSource:
    async def test_a_local_path_is_uploaded_then_linked(self, tmp_path: Any) -> None:
        """The second situation, reached by the same tool: bytes on disk
        become an asset id and then the identical swap."""
        client = _make_client()
        _install_search(client)
        uploads = _install_fake_upload(client)
        captured = _install_fake_mutate(client, _mutate_response())
        image = _write_png(tmp_path / "hero.png", 1200, 628)

        result = await client.replace_asset_group_image_asset(
            _swap_params(new_asset_id=None, new_image_path=str(image))
        )

        assert len(uploads) == 1
        assert uploads[0][0].endswith("hero.png")
        _, operations, _ = captured[0]
        assert operations[0].asset_group_asset_operation.create.asset == (
            f"customers/{CUSTOMER_ID}/assets/888"
        )
        assert result["added"]["asset_id"] == "888"
        assert result["added"]["source"] == "uploaded"

    async def test_the_upload_takes_the_supplied_asset_name(
        self, tmp_path: Any
    ) -> None:
        client = _make_client()
        _install_search(client)
        uploads = _install_fake_upload(client)
        _install_fake_mutate(client, _mutate_response())
        image = _write_png(tmp_path / "hero.png", 1200, 628)

        await client.replace_asset_group_image_asset(
            _swap_params(
                new_asset_id=None,
                new_image_path=str(image),
                new_image_name="Autumn hero",
            )
        )

        assert uploads[0][1] == "Autumn hero"

    @pytest.mark.parametrize(
        "params",
        [
            {"new_asset_id": None},
            {"new_asset_id": "777", "new_image_path": "/tmp/hero.png"},
            {"new_asset_id": "", "new_image_path": "   "},
        ],
    )
    async def test_refuses_anything_but_exactly_one_source(
        self, params: dict[str, Any]
    ) -> None:
        """Accepting both would silently ignore one, and the asset group
        would end up carrying an image the operator did not choose."""
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="exactly one"):
            await client.replace_asset_group_image_asset(_swap_params(**params))
        assert not captured

    async def test_refuses_an_asset_id_that_is_not_an_image(self) -> None:
        client = _make_client()
        _install_search(client, assets=[_asset_row(asset_type=ASSET_TYPE_TEXT)])
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="not an image"):
            await client.replace_asset_group_image_asset(_swap_params())
        assert not captured

    async def test_refuses_an_asset_id_the_account_does_not_hold(self) -> None:
        client = _make_client()
        _install_search(client, assets=[])
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="not found"):
            await client.replace_asset_group_image_asset(_swap_params())
        assert not captured

    async def test_refuses_an_image_already_linked_under_the_field_type(self) -> None:
        """Google rejects a duplicate link; say so before spending the call."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(asset_id=556)])
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="already linked"):
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id="556")
            )
        assert not captured

    async def test_refuses_swapping_an_image_for_itself(self) -> None:
        """The old asset is linked by definition, so it is a duplicate link
        — and a swap that changes nothing should not spend a mutate."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(asset_id=555)])
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="already linked"):
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id="555")
            )
        assert not captured


# ---------------------------------------------------------------------------
# Dimension rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDimensionRules:
    @pytest.mark.parametrize(
        "field_type,width,height,expected",
        [
            ("MARKETING_IMAGE", 1200, 1200, "1.91:1"),
            ("SQUARE_MARKETING_IMAGE", 1200, 628, "1:1"),
            ("PORTRAIT_MARKETING_IMAGE", 1200, 1200, "4:5"),
            ("LANDSCAPE_LOGO", 1200, 1200, "4:1"),
        ],
    )
    async def test_refuses_an_existing_asset_of_the_wrong_shape(
        self, field_type: str, width: int, height: int, expected: str
    ) -> None:
        """Every slot has its own shape: a square image is not a landscape
        one, and the refusal has to say which rule it broke."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(width=width, height=height)])

        with pytest.raises(ValueError) as excinfo:
            await client._existing_image_asset("777", field_type)

        message = str(excinfo.value)
        assert expected in message
        assert f"{width}x{height}" in message
        assert "resize" in message

    async def test_a_wrong_shape_asset_blocks_the_whole_swap(self) -> None:
        """End to end: the shape check sits before the mutate, not beside
        it."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(width=1200, height=1200)])
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="1.91:1"):
            await client.replace_asset_group_image_asset(_swap_params())

        assert not captured

    @pytest.mark.parametrize(
        "field_type,width,height",
        [
            ("MARKETING_IMAGE", 382, 200),
            ("SQUARE_MARKETING_IMAGE", 200, 200),
            ("LOGO", 64, 64),
            ("LANDSCAPE_LOGO", 400, 100),
        ],
    )
    async def test_refuses_an_image_below_the_field_type_minimum(
        self, field_type: str, width: int, height: int
    ) -> None:
        """Right shape, too few pixels."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(width=width, height=height)])

        with pytest.raises(ValueError, match="at least"):
            await client._existing_image_asset("777", field_type)

    async def test_a_local_file_is_measured_before_it_is_uploaded(
        self, tmp_path: Any
    ) -> None:
        """A wrongly proportioned file must cost no API call and leave no
        unlinked asset behind in the account."""
        client = _make_client()
        _install_search(client)
        uploads = _install_fake_upload(client)
        captured = _install_fake_mutate(client, _mutate_response())
        image = _write_png(tmp_path / "square.png", 1200, 1200)

        with pytest.raises(ValueError, match="1.91:1"):
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id=None, new_image_path=str(image))
            )

        assert not uploads, "nothing may be uploaded before the shape is checked"
        assert not captured

    async def test_an_unmeasurable_file_is_not_refused_on_a_guess(
        self, tmp_path: Any
    ) -> None:
        """A GIF has no std-lib prober here. mureo does not know its shape,
        so it does not pretend to: the file goes to Google and the refusal,
        if any, comes back translated."""
        client = _make_client()
        _install_search(client)
        uploads = _install_fake_upload(client)
        _install_fake_mutate(client, _mutate_response())
        image = tmp_path / "animated.gif"
        image.write_bytes(b"GIF89a" + b"\x00" * 32)

        result = await client.replace_asset_group_image_asset(
            _swap_params(new_asset_id=None, new_image_path=str(image))
        )

        assert len(uploads) == 1
        assert result["added"]["source"] == "uploaded"

    @pytest.mark.parametrize(
        "width,height",
        [(1200, 628), (600, 314), (1200, 630)],
    )
    async def test_accepts_the_sizes_google_itself_publishes(
        self, width: int, height: int
    ) -> None:
        """1200x628 is 1.911:1, not 1.910:1 — a tolerance-free ratio check
        would refuse Google's own recommended size."""
        client = _make_client()
        _install_search(client, assets=[_asset_row(width=width, height=height)])

        resolved = await client._existing_image_asset("777", "MARKETING_IMAGE")

        assert resolved["asset_id"] == "777"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInputValidation:
    async def test_refuses_an_asset_id_not_linked_under_that_field_type(self) -> None:
        """557 is linked, but as a SQUARE_MARKETING_IMAGE."""
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="557"):
            await client.replace_asset_group_image_asset(
                _swap_params(old_asset_id="557")
            )
        assert not captured

    @pytest.mark.parametrize(
        "field_type", ["HEADLINE", "YOUTUBE_VIDEO", "AD_IMAGE", "marketing_image"]
    )
    async def test_refuses_a_field_type_outside_the_five_image_types(
        self, field_type: str
    ) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="field_type"):
            await client.replace_asset_group_image_asset(
                _swap_params(field_type=field_type)
            )

    @pytest.mark.parametrize("key", ["asset_group_id", "old_asset_id"])
    async def test_refuses_non_numeric_ids(self, key: str) -> None:
        client = _make_client()
        client._search = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match=key):
            await client.replace_asset_group_image_asset(_swap_params(**{key: "4242'"}))

    async def test_refuses_a_non_numeric_new_asset_id(self) -> None:
        client = _make_client()
        _install_search(client)
        captured = _install_fake_mutate(client, _mutate_response())

        with pytest.raises(ValueError, match="new_asset_id"):
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id="７７７")
            )
        assert not captured

    async def test_refuses_a_traversing_image_path(self, tmp_path: Any) -> None:
        client = _make_client()
        _install_search(client)
        uploads = _install_fake_upload(client)

        with pytest.raises(ValueError):
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id=None, new_image_path="../../etc/passwd.png")
            )
        assert not uploads


# ---------------------------------------------------------------------------
# API refusals worth translating
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslatedRefusals:
    @pytest.mark.parametrize(
        "code",
        [
            "NOT_ENOUGH_MARKETING_IMAGE_ASSET",
            "NOT_ENOUGH_SQUARE_MARKETING_IMAGE_ASSET",
            "NOT_ENOUGH_LOGO_ASSET",
        ],
    )
    async def test_asset_count_floor_becomes_an_actionable_message(
        self, code: str
    ) -> None:
        """The image twins of #590's ``NOT_ENOUGH_HEADLINE_ASSET``. They must
        not reach the agent as a raw API error."""
        client = _make_client()
        _install_search(client)
        _install_fake_mutate(client, _google_ads_exception("asset_group_error", code))

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_image_asset(_swap_params())

        message = str(excinfo.value)
        assert code in message
        assert "minimum" in message.lower()

    @pytest.mark.parametrize(
        "code",
        [
            "ASPECT_RATIO_NOT_ALLOWED",
            "IMAGE_TOO_SMALL",
            "IMAGE_CONSTRAINTS_VIOLATED",
            "UNEXPECTED_SIZE",
        ],
    )
    async def test_image_constraint_refusal_names_the_rule_for_the_slot(
        self, code: str
    ) -> None:
        """The backstop for what mureo could not measure itself: the message
        has to say what shape the slot takes, not just echo an enum name."""
        client = _make_client()
        _install_search(client)
        _install_fake_mutate(client, _google_ads_exception("image_error", code))

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_image_asset(_swap_params())

        message = str(excinfo.value)
        assert code in message
        assert "1.91:1" in message
        assert "600x314" in message
        assert "resize" in message

    async def test_a_failed_swap_after_an_upload_says_the_asset_is_orphaned(
        self, tmp_path: Any
    ) -> None:
        """The upload is a separate request, so a refusal afterwards leaves
        an unlinked asset in the account. Say so rather than let the
        operator find it."""
        client = _make_client()
        _install_search(client)
        _install_fake_upload(client)
        _install_fake_mutate(
            client, _google_ads_exception("image_error", "ASPECT_RATIO_NOT_ALLOWED")
        )
        image = tmp_path / "animated.gif"
        image.write_bytes(b"GIF89a" + b"\x00" * 32)

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_image_asset(
                _swap_params(new_asset_id=None, new_image_path=str(image))
            )

        assert "unlinked" in str(excinfo.value)

    async def test_other_api_errors_keep_the_curated_server_detail(self) -> None:
        client = _make_client()
        _install_search(client)
        _install_fake_mutate(
            client, _google_ads_exception("asset_group_error", "DUPLICATE_NAME")
        )

        with pytest.raises(RuntimeError) as excinfo:
            await client.replace_asset_group_image_asset(_swap_params())

        assert "server said: DUPLICATE_NAME" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestImageErrorConstants:
    def test_every_translated_code_is_a_real_enum_member(self) -> None:
        """A misspelt code silently never matches, and the refusal it exists
        to explain reaches the agent raw."""
        from google.ads.googleads.v23.errors.types.asset_group_error import (
            AssetGroupErrorEnum,
        )
        from google.ads.googleads.v23.errors.types.image_error import ImageErrorEnum

        from mureo.google_ads._asset_groups_images import (
            _IMAGE_CONSTRAINT_ERRORS,
            _NOT_ENOUGH_IMAGE_ASSET_ERRORS,
        )

        group_codes = {m.name for m in AssetGroupErrorEnum.AssetGroupError}
        image_codes = {m.name for m in ImageErrorEnum.ImageError}
        assert set(_NOT_ENOUGH_IMAGE_ASSET_ERRORS) <= group_codes
        assert set(_IMAGE_CONSTRAINT_ERRORS) <= image_codes

    def test_the_mixin_shadows_no_sibling_implementation(self) -> None:
        """The image mixin needs ``upload_image_asset`` and
        ``list_asset_group_assets``, both owned by other mixins. A plain
        ``...`` stub for either would win the MRO — ``_MediaMixin`` is
        composed after this one — and every upload would silently return
        ``None``, which is exactly what happened before this was pinned.
        """
        from mureo.google_ads._asset_groups import _AssetGroupsMixin
        from mureo.google_ads._asset_groups_images import _AssetGroupImagesMixin
        from mureo.google_ads._media import _MediaMixin

        for name, owner in (
            ("upload_image_asset", _MediaMixin),
            ("list_asset_group_assets", _AssetGroupsMixin),
        ):
            assert not hasattr(
                _AssetGroupImagesMixin, name
            ), f"{name} must be declared under TYPE_CHECKING only"
            assert getattr(GoogleAdsApiClient, name) is getattr(owner, name)

    def test_every_field_type_has_a_dimension_rule(self) -> None:
        for field_type, spec in PMAX_IMAGE_FIELD_TYPES.items():
            assert spec.aspect_ratio > 0, field_type
            assert spec.min_width > 0 and spec.min_height > 0, field_type
            assert spec.ratio_label and spec.recommended, field_type
