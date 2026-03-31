"""Meta Ads クリエイティブ操作Mixin

AdCreative作成・画像アップロード・ダイナミッククリエイティブ対応。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from mureo._image_validation import validate_image_file, validate_video_file

logger = logging.getLogger(__name__)

# Meta Ads 画像アップロード制限
_META_MAX_IMAGE_SIZE_BYTES = 30 * 1024 * 1024  # 30MB
_META_ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "bmp", "tiff"})

# Meta Ads 動画アップロード制限
_META_MAX_VIDEO_SIZE_BYTES = 100 * 1024 * 1024  # 100MB（実用上の制限）
_META_ALLOWED_VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "wmv", "mkv"})

# カルーセルカード枚数制限
_CAROUSEL_MIN_CARDS = 2
_CAROUSEL_MAX_CARDS = 10

# AdCreative取得用フィールド
_CREATIVE_FIELDS = (
    "id,name,status,title,body,image_url,image_hash,"
    "thumbnail_url,object_story_spec,url_tags"
)


class CreativesMixin:
    """Meta Ads クリエイティブ操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str
    _access_token: str
    BASE_URL: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_ad_creatives(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """AdCreative一覧を取得する

        Returns:
            AdCreative情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _CREATIVE_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adcreatives", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_ad_creative(
        self,
        name: str,
        page_id: str,
        link_url: str,
        *,
        image_url: str | None = None,
        image_hash: str | None = None,
        message: str | None = None,
        headline: str | None = None,
        description: str | None = None,
        call_to_action: str | None = None,
    ) -> dict[str, Any]:
        """AdCreativeを作成する（画像URL or image_hash指定）

        Args:
            name: クリエイティブ名
            page_id: FacebookページID
            link_url: リンク先URL
            image_url: 画像URL（image_hashと排他）
            image_hash: アップロード済み画像のハッシュ（image_urlと排他）
            message: 広告本文
            headline: 見出し
            description: 説明文
            call_to_action: CTAボタンタイプ（LEARN_MORE, SIGN_UP等）

        Returns:
            作成されたAdCreative情報
        """
        link_data: dict[str, Any] = {
            "link": link_url,
        }

        if image_url:
            link_data["image_url"] = image_url
        elif image_hash:
            link_data["image_hash"] = image_hash

        if message:
            link_data["message"] = message
        if headline:
            link_data["name"] = headline
        if description:
            link_data["description"] = description
        if call_to_action:
            link_data["call_to_action"] = {"type": call_to_action}

        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }

        data: dict[str, Any] = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }

        return await self._post(f"/{self._ad_account_id}/adcreatives", data)

    async def upload_ad_image(
        self,
        image_url: str,
    ) -> dict[str, Any]:
        """画像URLを指定してMeta APIにアップロードする

        Args:
            image_url: アップロード元の画像URL

        Returns:
            {"hash": "...", "url": "..."} or {"error": "..."}
        """
        data: dict[str, Any] = {
            "url": image_url,
        }

        result = await self._post(f"/{self._ad_account_id}/adimages", data)

        images = result.get("images")
        if not images or not isinstance(images, dict):
            return {"error": "画像アップロードに失敗しました"}

        # imagesは {filename: {hash, url}} の形式
        first_image = next(iter(images.values()))
        return {
            "hash": first_image.get("hash", ""),
            "url": first_image.get("url", ""),
        }

    async def upload_ad_image_file(
        self,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """ローカルファイルから画像をアップロードする。

        Args:
            file_path: ローカル画像ファイルのパス
            name: 画像名（省略時はファイル名を使用）

        Returns:
            {"hash": "...", "url": "..."} or {"error": "..."}

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: バリデーションエラー
        """
        path = validate_image_file(
            file_path,
            max_size_bytes=_META_MAX_IMAGE_SIZE_BYTES,
            max_size_label="30MB",
            allowed_extensions=_META_ALLOWED_IMAGE_EXTENSIONS,
        )

        upload_name = name or path.name
        url = f"{self.BASE_URL}/{self._ad_account_id}/adimages"

        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(path, "rb") as f:
                files = {"filename": (upload_name, f, "application/octet-stream")}
                data = {"access_token": self._access_token}
                response = await client.post(url, files=files, data=data)

        response.raise_for_status()
        result = response.json()

        images = result.get("images")
        if not images or not isinstance(images, dict):
            return {"error": "画像アップロードに失敗しました"}

        first_image = next(iter(images.values()))
        return {
            "hash": first_image.get("hash", ""),
            "url": first_image.get("url", ""),
        }

    async def create_dynamic_creative(
        self,
        name: str,
        page_id: str,
        image_hashes: list[str],
        bodies: list[str],
        titles: list[str],
        link_url: str,
        *,
        descriptions: list[str] | None = None,
        call_to_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """ダイナミッククリエイティブ用AdCreativeを作成する

        複数の画像・本文・見出しを登録し、Meta側が自動最適化する。

        Args:
            name: クリエイティブ名
            page_id: FacebookページID
            image_hashes: 画像ハッシュのリスト（2〜10枚推奨）
            bodies: 広告本文のリスト
            titles: 見出しのリスト
            link_url: リンク先URL
            descriptions: 説明文のリスト（任意）
            call_to_actions: CTAタイプのリスト（任意）

        Returns:
            作成されたAdCreative情報
        """
        object_story_spec = {
            "page_id": page_id,
            "link_data": {
                "link": link_url,
            },
        }

        asset_feed_spec: dict[str, Any] = {
            "images": [{"hash": h} for h in image_hashes],
            "bodies": [{"text": b} for b in bodies],
            "titles": [{"text": t} for t in titles],
            "link_urls": [{"website_url": link_url}],
        }

        if descriptions:
            asset_feed_spec["descriptions"] = [{"text": d} for d in descriptions]
        if call_to_actions:
            asset_feed_spec["call_to_action_types"] = call_to_actions

        data: dict[str, Any] = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
            "asset_feed_spec": json.dumps(asset_feed_spec),
        }

        return await self._post(f"/{self._ad_account_id}/adcreatives", data)

    # ------------------------------------------------------------------
    # 動画アップロード
    # ------------------------------------------------------------------

    async def upload_ad_video(
        self, video_url: str, title: str | None = None
    ) -> dict[str, Any]:
        """URL指定で動画をアップロードする

        Args:
            video_url: アップロード元の動画URL
            title: 動画タイトル（任意）

        Returns:
            {"id": "..."} 形式のレスポンス
        """
        data: dict[str, Any] = {
            "file_url": video_url,
        }
        if title:
            data["title"] = title

        return await self._post(f"/{self._ad_account_id}/advideos", data)

    async def upload_ad_video_file(
        self, file_path: str, title: str | None = None
    ) -> dict[str, Any]:
        """ローカルファイルから動画をアップロードする

        Args:
            file_path: ローカル動画ファイルのパス
            title: 動画タイトル（任意）

        Returns:
            {"id": "..."} 形式のレスポンス

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: バリデーションエラー
        """
        path = validate_video_file(
            file_path,
            max_size_bytes=_META_MAX_VIDEO_SIZE_BYTES,
            max_size_label="100MB",
            allowed_extensions=_META_ALLOWED_VIDEO_EXTENSIONS,
        )

        url = f"{self.BASE_URL}/{self._ad_account_id}/advideos"
        upload_data: dict[str, str] = {"access_token": self._access_token}
        if title:
            upload_data["title"] = title

        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(path, "rb") as f:
                files = {"source": (path.name, f, "application/octet-stream")}
                response = await client.post(url, files=files, data=upload_data)

        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # カルーセルクリエイティブ
    # ------------------------------------------------------------------

    async def create_carousel_creative(
        self,
        page_id: str,
        cards: list[dict[str, Any]],
        link: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """カルーセルクリエイティブを作成する

        Args:
            page_id: FacebookページID
            cards: カードのリスト（各要素に link, name, image_hash 等を含む）
                   2〜10枚が必須
            link: メインリンクURL
            name: クリエイティブ名（任意）

        Returns:
            作成されたAdCreative情報

        Raises:
            ValueError: カード枚数が2〜10の範囲外の場合
        """
        if not (_CAROUSEL_MIN_CARDS <= len(cards) <= _CAROUSEL_MAX_CARDS):
            raise ValueError(
                f"カルーセルのカード枚数は2〜10枚です（指定: {len(cards)}枚）"
            )

        child_attachments = []
        for card in cards:
            attachment: dict[str, Any] = {
                "link": card["link"],
            }
            if "name" in card:
                attachment["name"] = card["name"]
            if "description" in card:
                attachment["description"] = card["description"]
            if "image_hash" in card:
                attachment["image_hash"] = card["image_hash"]
            if "image_url" in card:
                attachment["image_url"] = card["image_url"]
            if "video_id" in card:
                attachment["video_id"] = card["video_id"]
            child_attachments.append(attachment)

        object_story_spec: dict[str, Any] = {
            "page_id": page_id,
            "link_data": {
                "child_attachments": child_attachments,
                "link": link,
            },
        }

        creative_data: dict[str, Any] = {
            "object_story_spec": json.dumps(object_story_spec),
        }
        if name:
            creative_data["name"] = name

        return await self._post(f"/{self._ad_account_id}/adcreatives", creative_data)

    # ------------------------------------------------------------------
    # コレクションクリエイティブ
    # ------------------------------------------------------------------

    async def create_collection_creative(
        self,
        page_id: str,
        product_ids: list[str],
        link: str,
        cover_image_hash: str | None = None,
        cover_video_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """コレクションクリエイティブを作成する

        Args:
            page_id: FacebookページID
            product_ids: 商品IDのリスト
            link: メインリンクURL
            cover_image_hash: カバー画像ハッシュ（cover_video_idと排他）
            cover_video_id: カバー動画ID（cover_image_hashと排他）
            name: クリエイティブ名（任意）

        Returns:
            作成されたAdCreative情報
        """
        template_data: dict[str, Any] = {
            "call_to_action": {
                "type": "LEARN_MORE",
                "value": {"link": link},
            },
            "retailer_item_ids": product_ids,
        }

        if cover_video_id:
            template_data["format_option"] = "collection_video"
            template_data["video_id"] = cover_video_id
        elif cover_image_hash:
            template_data["format_option"] = "collection_image"
            template_data["image_hash"] = cover_image_hash

        object_story_spec: dict[str, Any] = {
            "page_id": page_id,
            "template_data": template_data,
        }

        collection_data: dict[str, Any] = {
            "object_story_spec": json.dumps(object_story_spec),
        }
        if name:
            collection_data["name"] = name

        return await self._post(f"/{self._ad_account_id}/adcreatives", collection_data)
