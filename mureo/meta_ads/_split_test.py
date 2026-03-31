"""Meta Ads Split Test (A/B test) operations mixin.

Split test creation, listing, details retrieval, and termination via Ad Studies API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Split test retrieval fields
_STUDY_FIELDS = (
    "id,name,description,type,start_time,end_time,"
    "cells,objectives,confidence_level,results"
)

_VALID_CONFIDENCE_LEVELS = frozenset({80, 90, 95})


class SplitTestMixin:
    """Meta Ads Split Test (A/B test) operations mixin.

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_split_tests(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """List split tests.

        Args:
            limit: Maximum number of results

        Returns:
            List of split test information
        """
        params: dict[str, Any] = {
            "fields": _STUDY_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adstudies", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_split_test(self, study_id: str) -> dict[str, Any]:
        """Get split test details and results.

        Args:
            study_id: Study ID

        Returns:
            Split test detail information
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
        """Create a split test.

        Args:
            name: Test name
            cells: Cell definitions (each cell includes name and adsets)
            objectives: Objectives (e.g. [{"type": "COST_PER_RESULT"}])
            start_time: Start time (ISO 8601 format)
            end_time: End time (ISO 8601 format)
            confidence_level: Confidence level (default: 95)
            description: Test description

        Returns:
            Created split test information
        """
        if confidence_level not in _VALID_CONFIDENCE_LEVELS:
            raise ValueError(
                f"confidence_level must be one of {sorted(_VALID_CONFIDENCE_LEVELS)}: "
                f"{confidence_level}"
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
            "Split test creation: name=%s, cells=%d, confidence=%d%%",
            name,
            len(cells),
            confidence_level,
        )
        return await self._post(f"/{self._ad_account_id}/adstudies", data)

    async def end_split_test(self, study_id: str) -> dict[str, Any]:
        """End a split test.

        Args:
            study_id: Study ID

        Returns:
            Termination result
        """
        logger.info("Split test ended: study_id=%s", study_id)
        return await self._post(f"/{study_id}", {"status": "COMPLETED"})
