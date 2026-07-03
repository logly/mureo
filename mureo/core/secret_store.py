"""``SecretStore`` Protocol and default in-process implementation.

The Protocol abstracts the read/write of ad-platform credentials and
other secret material so callers (tests, alternate backends such as OS
keychains, HashiCorp Vault, GCP Secret Manager, AWS Secrets Manager)
can swap the underlying storage without touching the rest of mureo.

``FilesystemSecretStore`` is the default implementation. It is
behaviourally equivalent to the legacy ``~/.mureo/credentials.json``
flow read by :func:`mureo.auth.load_credentials`: on READS, missing or
corrupt files yield an empty result rather than raising. On WRITES,
however, an existing-but-corrupt file is backed up and the save is
refused (:class:`SecretStoreError`) rather than silently reset to ``{}``
— otherwise saving one provider would drop every other provider's
credentials. The on-disk root must be a JSON object keyed by platform
name; saves preserve unrelated platform keys; saves land at ``0o600`` on
POSIX so credential files stay owner-readable (via
:func:`mureo.fsutil.secure_fchmod`, the cross-platform helper used
elsewhere in the repo).

This default is **single-writer**. Concurrent writes from different
processes can lose updates because the read-modify-write inside
``save`` / ``delete`` is not file-locked. The legacy
``mureo.auth._save_meta_token`` has the same property; cross-process
locking is out of scope for the in-memory default and belongs in an
alternate backend if a deployment needs it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mureo.fsutil import backup_file, secure_fchmod

logger = logging.getLogger(__name__)


class SecretStoreError(Exception):
    """Raised when a write would clobber an existing but unreadable/malformed
    credentials file.

    Reads stay tolerant (missing/corrupt → empty), but a *save* or *delete*
    must not silently reset a corrupt file to ``{}`` and drop every other
    provider's credentials — the same data-loss class fixed for the env-var and
    Meta-token writers (#276). The corrupt file is backed up before the error is
    raised so the operator can recover it.
    """


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

    Optional capability (read defensively via :func:`getattr`, so existing
    stores need no change):

    - ``credentials_write_path: Path`` — the single filesystem path the
      store's writes actually land in. A filesystem-backed store that is
      not a :class:`FilesystemSecretStore` instance (e.g. a composite that
      layers an override file over a shared base) declares this so the
      configure-UI write path
      (:func:`mureo.core.runtime_context.runtime_credentials_path`) can
      target the same file the runtime reads from — closing the #194
      split-brain for non-default backends without coupling the resolver
      to a concrete class (#196). Omit it (or return ``None``) for
      non-filesystem backends; the path-based write helpers then stay on
      the host default.

    - ``multi_account_auth: bool`` — set ``True`` to mark the store as a
      multi-account backend whose OAuth credentials are operator-shared
      across many client accounts (e.g. an agency plugin: one Google
      ``developer_token`` + OAuth client, one Meta app, serving N
      clients whose ``customer_id`` / ``account_id`` are supplied
      per-request out of band). The ``mureo configure`` OAuth flow then
      persists only the shared credentials and skips the per-account
      picker, redirecting straight to ``/done`` (#198). Honored only
      when exactly ``True`` (see
      :func:`mureo.core.runtime_context.runtime_multi_account_auth`);
      omit it for single-account stores so the picker is shown as today.

    - ``ui_plugin_credential_fields: Mapping[str, Collection[str]]`` —
      a per-provider allow-list of the credential-field keys the
      configure dashboard's "Plugin credentials" section should render
      (e.g. ``{"yahoo_ads": {"client_id", "client_secret",
      "refresh_token"}}``). A multi-account backend uses it to surface
      only operator-shared auth fields and hide per-account ids that
      belong on its own per-client form (#207). Providers absent from
      the mapping keep all their fields. Read defensively (only a
      ``Mapping`` is honored) via
      :func:`mureo.core.runtime_context.runtime_ui_plugin_credential_fields`;
      omit it for single-account stores so every declared field renders
      as today.
    """

    def load(self, key: str) -> dict[str, Any]: ...

    def save(self, key: str, value: dict[str, Any]) -> None: ...

    def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Default implementation — JSON file under ``~/.mureo/``
# ---------------------------------------------------------------------------


class FilesystemSecretStore:
    """Persist credentials in a single JSON file (default
    ``~/.mureo/credentials.json``).

    The file root is a ``dict[str, dict[str, Any]]`` keyed by platform
    name (``"google_ads"``, ``"meta_ads"``, ``"search_console"``, …).
    Reads tolerate missing files, OS errors, JSON decode errors, and
    non-object roots — all collapse to an empty result so the MCP
    server can still start when credentials have not yet been
    configured. Writes are atomic (tempfile + ``os.replace``) and land
    at ``0o600`` on POSIX.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = (
            path if path is not None else Path.home() / ".mureo" / "credentials.json"
        )

    def load(self, key: str) -> dict[str, Any]:
        data = self._read_root()
        value = data.get(key, {})
        # Defensive copy so callers cannot mutate our cached return.
        return dict(value) if isinstance(value, dict) else {}

    def save(self, key: str, value: dict[str, Any]) -> None:
        # Strict read: refuse to overwrite a corrupt file (which would drop
        # every other provider's credentials); back it up + raise instead.
        data = self._read_root(strict=True)
        data[key] = dict(value)  # defensive copy of caller's input
        self._write_root(data)

    def delete(self, key: str) -> None:
        data = self._read_root(strict=True)
        if key in data:
            del data[key]
            self._write_root(data)

    def ensure_exists(self) -> bool:
        """Materialize an empty credentials file (``{}``) if absent.

        Uses the same atomic-write + ``0o600`` machinery as :meth:`save`.
        Returns ``True`` when a file was created, ``False`` when one
        already existed (its contents are never touched).

        Lets a caller record "setup completed" on disk even when no
        credentials were registered — distinguishing "configured nothing
        yet" (``{}``) from "setup never ran" (no file) for diagnostic
        tooling that keys off file presence (#210). The
        missing-equals-empty load contract means ``{}`` is
        runtime-indistinguishable from no file, so this changes the
        diagnostic signal only, not behaviour.
        """
        if self.path.exists():
            return False
        self._write_root({})
        return True

    # ------------------------------------------------------------------

    def _read_root(self, *, strict: bool = False) -> dict[str, Any]:
        """Return the file's root object.

        Non-strict (reads): tolerate every reasonable failure mode (missing,
        unreadable, malformed, wrong type) by returning ``{}``.

        Strict (writes): a genuinely absent file is still ``{}`` (a first
        write), but an existing-yet-unreadable/malformed/non-object file backs
        itself up and raises :class:`SecretStoreError` — overwriting it would
        silently drop every other provider's credentials.
        """
        if not self.path.exists():
            logger.debug("credentials file not found: %s", self.path)
            return {}
        try:
            text = self.path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            if strict:
                self._backup_corrupt("unreadable or malformed JSON")
                raise SecretStoreError(
                    f"refusing to overwrite unreadable credentials file "
                    f"{self.path} ({exc}); a .bak copy was kept"
                ) from exc
            logger.warning("failed to read credentials file: %s", exc)
            return {}
        if not isinstance(data, dict):
            # A valid-JSON but non-object root (e.g. a stray list) holds no
            # provider entries, so replacing it loses nothing — stay tolerant
            # even on writes. Only genuinely unreadable/malformed files (the
            # branch above, which may have held real credentials) are refused.
            logger.warning("credentials file root is not an object: %s", self.path)
            return {}
        return data

    def _backup_corrupt(self, reason: str) -> None:
        """Best-effort backup of a corrupt file before a refused overwrite."""
        try:
            backup = backup_file(self.path)
        except OSError:
            logger.warning("could not back up corrupt credentials file %s", self.path)
            return
        logger.warning(
            "credentials file %s is corrupt (%s); backed up to %s",
            self.path,
            reason,
            backup,
        )

    def _write_root(self, data: dict[str, Any]) -> None:
        """Atomically write the root object and apply secure permissions.

        Matches :func:`mureo.auth._save_meta_token` byte-for-byte:
        ``ensure_ascii=False`` so on-disk JSON keeps UTF-8 (operators
        editing the file by hand see real characters, not ``\\uXXXX``
        escapes), ``secure_fchmod`` applied to the temp fd before
        ``os.replace`` so the destination inherits ``0o600`` atomically
        on POSIX, and best-effort no-op on Windows (see
        :mod:`mureo.fsutil`).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            secure_fchmod(fd)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
