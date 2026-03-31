"""Meta Ads Ad Rules (automated rules) operations mixin.

Automated rule creation, listing, details retrieval, updating, and deletion via Ad Rules Library API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Automated rule retrieval fields
_RULE_FIELDS = (
    "id,name,status,evaluation_spec,execution_spec,"
    "schedule_spec,created_time,updated_time"
)


class AdRulesMixin:
    """Meta Ads Ad Rules (automated rules) operations mixin.

    Used via multiple inheritance with MetaAdsApiClient.
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
        """List automated rules.

        Args:
            limit: Maximum number of results

        Returns:
            List of automated rule information
        """
        params: dict[str, Any] = {
            "fields": _RULE_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adrules_library", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_ad_rule(self, rule_id: str) -> dict[str, Any]:
        """Get automated rule details.

        Args:
            rule_id: Rule ID

        Returns:
            Automated rule detail information
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
        """Create an automated rule.

        Args:
            name: Rule name
            evaluation_spec: Evaluation conditions (evaluation_type, trigger, filters)
            execution_spec: Execution action (execution_type: NOTIFICATION, PAUSE_CAMPAIGN, etc.)
            schedule_spec: Schedule settings
            status: Initial status

        Returns:
            Created automated rule information
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

        logger.info("Automated rule creation: name=%s", name)
        return await self._post(f"/{self._ad_account_id}/adrules_library", data)

    async def update_ad_rule(
        self, rule_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an automated rule.

        Args:
            rule_id: Rule ID
            updates: Update contents (name, evaluation_spec, execution_spec, etc.)

        Returns:
            Update result
        """
        data: dict[str, Any] = {}
        for key, value in updates.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        logger.info("Automated rule update: rule_id=%s", rule_id)
        return await self._post(f"/{rule_id}", data)

    async def delete_ad_rule(self, rule_id: str) -> dict[str, Any]:
        """Delete an automated rule.

        Args:
            rule_id: Rule ID

        Returns:
            Deletion result
        """
        logger.info("Automated rule deletion: rule_id=%s", rule_id)
        return await self._delete(f"/{rule_id}")
