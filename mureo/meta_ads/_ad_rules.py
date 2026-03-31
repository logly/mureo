"""Meta Ads Ad Rules (自動ルール) 操作Mixin

Ad Rules Library API を使用した自動ルールの作成・一覧・詳細取得・更新・削除。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 自動ルール取得用フィールド
_RULE_FIELDS = (
    "id,name,status,evaluation_spec,execution_spec,"
    "schedule_spec,created_time,updated_time"
)


class AdRulesMixin:
    """Meta Ads Ad Rules (自動ルール) 操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _delete(self, path: str) -> dict[str, Any]: ...  # type: ignore[empty-body]

    async def list_ad_rules(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """自動ルール一覧を取得する

        Args:
            limit: 取得件数上限

        Returns:
            自動ルール情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _RULE_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adrules_library", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_ad_rule(self, rule_id: str) -> dict[str, Any]:
        """自動ルール詳細を取得する

        Args:
            rule_id: ルールID

        Returns:
            自動ルール詳細情報
        """
        params: dict[str, Any] = {"fields": _RULE_FIELDS}
        return await self._get(f"/{rule_id}", params)

    async def create_ad_rule(
        self,
        name: str,
        evaluation_spec: dict[str, Any],
        execution_spec: dict[str, Any],
        *,
        schedule_spec: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """自動ルールを作成する

        Args:
            name: ルール名
            evaluation_spec: 評価条件（evaluation_type, trigger, filters）
            execution_spec: 実行アクション（execution_type: NOTIFICATION, PAUSE_CAMPAIGN等）
            schedule_spec: スケジュール設定
            status: 初期ステータス

        Returns:
            作成された自動ルール情報
        """
        data: dict[str, Any] = {
            "name": name,
            "evaluation_spec": json.dumps(evaluation_spec),
            "execution_spec": json.dumps(execution_spec),
        }
        if schedule_spec is not None:
            data["schedule_spec"] = json.dumps(schedule_spec)
        if status is not None:
            data["status"] = status

        logger.info("自動ルール作成: name=%s", name)
        return await self._post(f"/{self._ad_account_id}/adrules_library", data)

    async def update_ad_rule(
        self, rule_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """自動ルールを更新する

        Args:
            rule_id: ルールID
            updates: 更新内容（name, evaluation_spec, execution_spec等）

        Returns:
            更新結果
        """
        data: dict[str, Any] = {}
        for key, value in updates.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        logger.info("自動ルール更新: rule_id=%s", rule_id)
        return await self._post(f"/{rule_id}", data)

    async def delete_ad_rule(self, rule_id: str) -> dict[str, Any]:
        """自動ルールを削除する

        Args:
            rule_id: ルールID

        Returns:
            削除結果
        """
        logger.info("自動ルール削除: rule_id=%s", rule_id)
        return await self._delete(f"/{rule_id}")
