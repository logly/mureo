"""Meta Ads Split Test (A/Bテスト) 操作Mixin

Ad Studies API を使用したスプリットテストの作成・一覧・詳細取得・終了。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# スプリットテスト取得用フィールド
_STUDY_FIELDS = (
    "id,name,description,type,start_time,end_time,"
    "cells,objectives,confidence_level,results"
)

_VALID_CONFIDENCE_LEVELS = frozenset({80, 90, 95})


class SplitTestMixin:
    """Meta Ads Split Test (A/Bテスト) 操作Mixin

    MetaAdsApiClientに多重継承して使用する。
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_split_tests(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """スプリットテスト一覧を取得する

        Args:
            limit: 取得件数上限

        Returns:
            スプリットテスト情報のリスト
        """
        params: dict[str, Any] = {
            "fields": _STUDY_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adstudies", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_split_test(self, study_id: str) -> dict[str, Any]:
        """スプリットテスト詳細・結果を取得する

        Args:
            study_id: スタディID

        Returns:
            スプリットテスト詳細情報
        """
        params: dict[str, Any] = {"fields": _STUDY_FIELDS}
        return await self._get(f"/{study_id}", params)

    async def create_split_test(
        self,
        name: str,
        cells: list[dict[str, Any]],
        objectives: list[dict[str, Any]],
        start_time: str,
        end_time: str,
        *,
        confidence_level: int = 95,
        description: str | None = None,
    ) -> dict[str, Any]:
        """スプリットテストを作成する

        Args:
            name: テスト名
            cells: セル定義（各セルにname, adsetsを含む）
            objectives: 目的（例: [{"type": "COST_PER_RESULT"}]）
            start_time: 開始日時（ISO 8601形式）
            end_time: 終了日時（ISO 8601形式）
            confidence_level: 信頼度（デフォルト: 95）
            description: テスト説明

        Returns:
            作成されたスプリットテスト情報
        """
        if confidence_level not in _VALID_CONFIDENCE_LEVELS:
            raise ValueError(
                f"confidence_levelは {sorted(_VALID_CONFIDENCE_LEVELS)} "
                f"のいずれかを指定してください: {confidence_level}"
            )

        data: dict[str, Any] = {
            "name": name,
            "type": "SPLIT_TEST",
            "cells": json.dumps(cells),
            "objectives": json.dumps(objectives),
            "start_time": start_time,
            "end_time": end_time,
            "confidence_level": confidence_level,
        }
        if description is not None:
            data["description"] = description

        logger.info(
            "スプリットテスト作成: name=%s, cells=%d, confidence=%d%%",
            name,
            len(cells),
            confidence_level,
        )
        return await self._post(f"/{self._ad_account_id}/adstudies", data)

    async def end_split_test(self, study_id: str) -> dict[str, Any]:
        """スプリットテストを終了する

        Args:
            study_id: スタディID

        Returns:
            終了結果
        """
        logger.info("スプリットテスト終了: study_id=%s", study_id)
        return await self._post(f"/{study_id}", {"status": "COMPLETED"})
