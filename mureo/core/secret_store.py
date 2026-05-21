"""``SecretStore`` Protocol — pluggable credential persistence.

Abstracts the read/write of ad-platform credentials and other secret
material. The OSS default implementation (added in a follow-up commit)
wraps the existing ``~/.mureo/credentials.json`` flow in ``mureo.auth``,
behaviourally equivalent to today's behaviour for callers that do not
inject a custom store.

Designed so callers (tests, alternate backends such as OS keychains,
HashiCorp Vault, GCP Secret Manager, AWS Secrets Manager) can swap the
underlying storage without touching the rest of mureo.

The Protocol is intentionally minimal — three opaque dict round-trip
operations keyed by a string — so concrete backends can map ``key``
onto whatever namespace they natively use.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecretStore(Protocol):
    """Pluggable persistence for credential dicts.

    Contract:
    - ``load(key)`` returns the stored dict, or an empty dict if the key
      is unknown. It must not raise on missing keys. The "empty stored
      value is indistinguishable from missing" semantic is intentional
      and matches the legacy ``mureo.auth.load_credentials`` behaviour
      that callers already depend on; do not change it without auditing
      every credential-load site.
    - ``save(key, value)`` persists ``value`` under ``key``. Implementations
      should overwrite existing entries.
    - ``delete(key)`` removes ``key`` from the store. It must be idempotent
      and not raise on missing keys.
    """

    def load(self, key: str) -> dict[str, Any]: ...

    def save(self, key: str, value: dict[str, Any]) -> None: ...

    def delete(self, key: str) -> None: ...
