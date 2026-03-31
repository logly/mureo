"""Meta Ads Lead Ads (リード広告) 操作Mixin

リードフォーム管理・リードデータ取得。
Lead FormsはPageに紐づくため、page_idが必要。
リードデータには個人情報が含まれるためログに出力しない。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# リードフォーム取得用フィールド
_LEAD_FORM_FIELDS = (
    "id,name,status,locale,questions,privacy_policy,"
    "follow_up_action_url,created_time,expired_leads_count,"
    "leads_count,organic_leads_count"
)

# リードデータ取得用フィールド
_LEAD_FIELDS = "id,created_time,field_data,ad_id,ad_name,form_id"


class LeadsMixin:
    """Meta Ads Lead Ads (リード広告) 操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    Lead FormsはFacebook Pageに紐づくため、操作にはpage_idが必要。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_lead_forms(
        self,
        page_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """リードフォーム一覧を取得する

        Args:
            page_id: Facebook ページID
            limit: 取得件数上限

        Returns:
            リードフォーム情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FORM_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{page_id}/leadgen_forms", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_lead_form(self, form_id: str) -> dict[str, Any]:
        """リードフォーム詳細を取得する

        Args:
            form_id: リードフォームID

        Returns:
            リードフォーム詳細情報
        """
        params: dict[str, Any] = {"fields": _LEAD_FORM_FIELDS}
        return await self._get(f"/{form_id}", params)

    async def create_lead_form(
        self,
        page_id: str,
        name: str,
        questions: list[dict[str, Any]],
        privacy_policy_url: str,
        *,
        follow_up_action_url: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """リードフォームを作成する

        Args:
            page_id: Facebook ページID
            name: フォーム名
            questions: 質問リスト（FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, CUSTOM等）
            privacy_policy_url: プライバシーポリシーURL
            follow_up_action_url: フォーム送信後のリダイレクトURL
            locale: ロケール

        Returns:
            作成されたリードフォーム情報
        """
        data: dict[str, Any] = {
            "name": name,
            "questions": json.dumps(questions),
            "privacy_policy": json.dumps({"url": privacy_policy_url}),
        }

        if follow_up_action_url is not None:
            data["follow_up_action_url"] = follow_up_action_url
        if locale is not None:
            data["locale"] = locale

        logger.info(
            "リードフォーム作成: page_id=%s, name=%s",
            page_id,
            name,
        )
        return await self._post(f"/{page_id}/leadgen_forms", data)

    async def get_leads(
        self,
        form_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """フォームに送信されたリードデータを取得する

        リードデータには個人情報（名前・メール・電話番号等）が含まれるため、
        ログには出力しない。

        Args:
            form_id: リードフォームID
            limit: 取得件数上限

        Returns:
            リードデータのリスト
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{form_id}/leads", params)
        # 個人情報を含むためログ出力しない
        leads = result.get("data", [])
        logger.info("リードデータ取得: form_id=%s, 件数=%d", form_id, len(leads))
        return leads  # type: ignore[no-any-return]

    async def get_ad_leads(
        self,
        ad_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """広告経由のリードデータを取得する

        リードデータには個人情報（名前・メール・電話番号等）が含まれるため、
        ログには出力しない。

        Args:
            ad_id: 広告ID
            limit: 取得件数上限

        Returns:
            リードデータのリスト
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{ad_id}/leads", params)
        # 個人情報を含むためログ出力しない
        leads = result.get("data", [])
        logger.info("広告別リードデータ取得: ad_id=%s, 件数=%d", ad_id, len(leads))
        return leads  # type: ignore[no-any-return]
