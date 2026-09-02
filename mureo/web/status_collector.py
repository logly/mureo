"""Collect installation status across hosts, providers, and basic parts.

Pure read-only — nothing in this module mutates settings files or
credentials. The configure UI surfaces this snapshot on every
``GET /api/status`` poll and uses it to render ✓/✗ pills.

Security boundary: ``credentials.json`` is inspected both for the
**presence** of platform sections and, for the credentials panel,
for individual field values. Values are surfaced either fully masked
(for secret-named vars) or in full (for path-shaped vars such as
``GOOGLE_APPLICATION_CREDENTIALS``). The masked preview only ever
leaks the last 4 characters of a secret, matching the convention
used by AWS / Stripe surface UIs.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mureo import __version__
from mureo.core import clock
from mureo.web._helpers import read_json_safe
from mureo.web.env_var_writer import allowed_env_var_names, get_env_var_target
from mureo.web.host_paths import HostPaths, get_host_paths
from mureo.web.setup_state import SetupParts

_HOST_DESKTOP = "claude-desktop"
_HOST_CODEX = "codex"

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

OFFICIAL_PROVIDER_IDS: tuple[str, ...] = (
    "google-ads-official",
    "meta-ads-official",
    "ga4-official",
    "tiktok-ads-official",
)

MUREO_NATIVE_ID = "mureo"

# Env var names matching this pattern get masked previews — only the
# last 4 chars survive, prefixed with bullets. Non-matching names
# (e.g. GOOGLE_APPLICATION_CREDENTIALS, META_ADS_ACCOUNT_ID) expose
# their full value because they are either filesystem paths or
# non-secret identifiers the operator may want to copy verbatim.
_SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD)", re.IGNORECASE)

# Minimum value length below which we mask the entire value to avoid
# leaking a short secret whose last-4-chars effectively *is* the
# secret. Mirrors AWS console's "shorter than threshold → all bullets".
_MASK_MIN_LENGTH = 8

# Amazon's stated lifetime for refresh tokens issued on/after 2026-07-30,
# counted from advertiser consent. Tokens issued earlier have no fixed
# expiry, which is why an unknown issue date is never warned about.
AMAZON_REFRESH_TOKEN_LIFETIME_DAYS = 365

# Warn once a refresh token is older than this — 30 days of headroom to
# re-authorize before Amazon revokes it mid-operation.
AMAZON_REFRESH_TOKEN_WARN_DAYS = 335

# Meta's long-lived user tokens live ~60 days from issue. mureo exchanges
# them for a fresh one at 53 days, so a token still older than that on
# disk is one the automatic refresh has NOT renewed — which is the only
# state worth warning about, and it leaves a week of headroom. Kept in
# lockstep with ``mureo.auth._TOKEN_REFRESH_THRESHOLD_DAYS`` (asserted by
# ``tests/test_web_status_meta_token.py``) rather than imported: this
# module is a pure filesystem read and must not pull in the auth stack.
META_ACCESS_TOKEN_WARN_DAYS = 53

# Warn once a token with a KNOWN expiry has fewer than this many days left
# (#726). Two weeks is deliberately more headroom than the 7-day automatic
# exchange (``auth._TOKEN_EXPIRY_REFRESH_LEAD_DAYS``): the warning also has
# to serve the install that CANNOT auto-extend — no app_id/app_secret stored
# — where the fix is a human generating a new system-user token in Business
# settings, and a week's notice for that is not a week's notice at all.
META_ACCESS_TOKEN_EXPIRY_WARN_DAYS = 14

# The three states a deployed workflow-skill set can be in (#728). Surfaced
# verbatim on the status payload as ``setup_parts.skills_state``, so the
# strings are part of the JSON contract the dashboard reads.
SKILLS_MISSING = "missing"
SKILLS_STALE = "stale"
SKILLS_CURRENT = "current"

# Frontmatter is delimited by lines containing exactly ``---``, the opener on
# line 1 — the same rule ``mureo.core.skills.parser`` enforces.
_SKILL_FRONTMATTER_DELIM = "---"

# ``version:`` anywhere inside the frontmatter block. Deliberately indifferent
# to the indentation that puts it under ``metadata:``, and unanchored at the
# end so a trailing ``# comment`` does not hide the pin: the shipped files are
# the only writers of the key, and a stricter parse would answer "unknown"
# (i.e. stale) for a file whose block was merely reordered or annotated.
_SKILL_VERSION_RE = re.compile(r"^\s*version:\s*(\S+)")

# Bytes of a SKILL.md read to find its frontmatter. Comfortably past the
# longest block mureo ships (~2 KB of description) and far short of the 64 KiB
# a whole file may be: none of the body answers "which version is this", and
# this runs once per shipped skill on every status poll.
_SKILL_HEAD_BYTES = 8192


@dataclass(frozen=True)
class SkillsStatus:
    """What a host's deployed workflow-skill set is, version included (#728).

    ``state`` is one of :data:`SKILLS_MISSING` / :data:`SKILLS_STALE` /
    :data:`SKILLS_CURRENT`. ``installed_versions`` maps each shipped skill name
    to the version its deployed copy records — ``None`` for a copy too old to
    record one — and omits the ones that are not deployed at all.
    """

    state: str
    expected_version: str
    installed_versions: dict[str, str | None] = field(default_factory=dict)

    @property
    def is_current(self) -> bool:
        return self.state == SKILLS_CURRENT

    @property
    def installed_version(self) -> str | None:
        """The single version to name in a one-line report, or ``None``."""
        return _dominant_version(self.installed_versions.values())


@dataclass(frozen=True)
class StatusSnapshot:
    """Aggregated configure-UI status payload."""

    host: str
    setup_parts: SetupParts
    providers_installed: dict[str, bool]
    credentials_present: dict[str, bool]
    credentials_oauth: dict[str, bool]
    env_vars: dict[str, dict[str, Any]]
    legacy_commands_present: bool
    # Per-platform: True ⇔ mcpServers.mureo.env.MUREO_DISABLE_<P> == "1"
    # (mureo-native tools for that platform are stepped aside so the
    # official MCP is the single source). Drives the dashboard toggle.
    mureo_disable: dict[str, bool]
    # #222: True ⇔ the active store declares ``multi_account_auth`` (a
    # multi-account backend). The configure UI uses it to suppress the
    # bare-``mureo`` MCP registration (the backend writes per-client
    # ``mureo-<slug>`` entries instead). Computed by the handler behind the
    # ``home is None`` gate and relayed through here; defaults False so
    # standalone OSS and direct callers are unchanged.
    multi_account_auth: bool = False
    # Audit #47: the Amazon tool manifest's freshness —
    # ``{"present": bool, "stale": bool, "age_days": float | None}``. The
    # manifest is a snapshot of a tool surface mureo does not own, so an old
    # one means the exposed tool list has quietly drifted from reality.
    # ``age_days`` is ``None`` when it cannot be determined (absent manifest,
    # or an unusable ``generated_at``), and an unknown age is never reported
    # as stale. Defaults to an empty dict so direct constructions of this
    # snapshot (tests, alternate callers) keep working.
    amazon_manifest: dict[str, Any] = field(default_factory=dict)
    # #121: the Amazon refresh token's re-authorization clock —
    # ``{"refresh_token_age_days": int | None, "refresh_token_expiring":
    # bool}``. Amazon expires refresh tokens issued on/after 2026-07-30 a
    # year after consent, so the dashboard nudges before that lands. An
    # unknown age (legacy setup, or a token mureo did not obtain itself)
    # is never reported as expiring — older tokens have no fixed expiry.
    # Defaults to an empty dict so direct constructions keep working.
    amazon_token: dict[str, Any] = field(default_factory=dict)
    # #579/#726: the Meta access token's two clocks —
    # ``{"access_token_age_days", "access_token_expiring",
    # "access_token_expires_at", "access_token_expires_in_days",
    # "access_token_expiry_warning"}``. The first pair is the
    # re-authentication nudge (only a token stored WITH
    # ``app_id``/``app_secret`` can be exchanged, so the flag is False
    # without them); the rest is the token's own expiry as Meta reported
    # it, which needs no app pair. See :func:`_detect_meta_token`.
    # Defaults to an empty dict so direct constructions keep working.
    meta_token: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "setup_parts": self.setup_parts.as_dict(),
            "providers_installed": dict(self.providers_installed),
            "credentials_present": dict(self.credentials_present),
            "credentials_oauth": dict(self.credentials_oauth),
            "env_vars": {k: dict(v) for k, v in self.env_vars.items()},
            "legacy_commands_present": self.legacy_commands_present,
            "mureo_disable": dict(self.mureo_disable),
            "multi_account_auth": self.multi_account_auth,
            "amazon_manifest": dict(self.amazon_manifest),
            "amazon_token": dict(self.amazon_token),
            "meta_token": dict(self.meta_token),
        }


def _detect_installed_providers(mcp_registry_path: Path) -> dict[str, bool]:
    """Report which official providers + the mureo native block are
    registered.

    Reads the file the host actually discovers MCP servers from
    (``~/.claude.json`` for Claude Code — NOT ``settings.json`` —;
    ``claude_desktop_config.json`` for Desktop; ``config.toml`` for Codex).
    A read-only parse is deterministic and race-safe for status display.
    """
    if mcp_registry_path.suffix == ".toml":
        from mureo.web.codex_mcp import installed_codex_server_ids

        ids = installed_codex_server_ids(mcp_registry_path)
        installed = {pid: pid in ids for pid in OFFICIAL_PROVIDER_IDS}
        installed[MUREO_NATIVE_ID] = MUREO_NATIVE_ID in ids
        return installed
    payload = read_json_safe(mcp_registry_path)
    raw = payload.get("mcpServers")
    mcp_servers: dict[str, Any] = raw if isinstance(raw, dict) else {}
    installed = {pid: pid in mcp_servers for pid in OFFICIAL_PROVIDER_IDS}
    installed[MUREO_NATIVE_ID] = MUREO_NATIVE_ID in mcp_servers
    return installed


# Platforms that have a MUREO_DISABLE_<P> toggle (mirror
# mureo.providers.mureo_env._PLATFORM_TO_ENV_VAR — Search Console is
# intentionally absent: mureo is always canonical for it).
_DISABLE_PLATFORMS: tuple[str, ...] = ("google_ads", "meta_ads", "ga4")


def _detect_mureo_disable(mcp_registry_path: Path) -> dict[str, bool]:
    """Per-platform: is ``mcpServers.mureo.env.MUREO_DISABLE_<P>`` ``"1"``.

    Read-only parse of the file the host actually reads MCP from. A
    missing/corrupt file or absent mureo block means nothing is
    disabled (all ``False``) — never raises.
    """
    if mcp_registry_path.suffix == ".toml":
        from mureo.web.codex_mcp import read_codex_server_env

        codex_env = read_codex_server_env(mcp_registry_path, MUREO_NATIVE_ID)
        return {
            p: codex_env.get("MUREO_DISABLE_" + p.upper()) == "1"
            for p in _DISABLE_PLATFORMS
        }
    payload = read_json_safe(mcp_registry_path)
    servers = payload.get("mcpServers")
    mureo = servers.get("mureo") if isinstance(servers, dict) else None
    env = mureo.get("env") if isinstance(mureo, dict) else None
    env = env if isinstance(env, dict) else {}
    return {p: env.get("MUREO_DISABLE_" + p.upper()) == "1" for p in _DISABLE_PLATFORMS}


def _detect_credentials_present(credentials_path: Path) -> dict[str, bool]:
    """Inspect credentials.json for presence of platform sections."""
    payload = read_json_safe(credentials_path)
    sections = ("google_ads", "meta_ads", "ga4")
    out: dict[str, bool] = {}
    for section in sections:
        value = payload.get(section)
        out[section] = isinstance(value, dict) and bool(value)
    out["amazon_ads"] = _amazon_credentials_usable(payload.get("amazon_ads"))
    return out


def _amazon_credentials_usable(section: Any) -> bool:
    """Amazon needs more than a non-empty section to be configured (#121).

    A half-filled ``amazon_ads`` block (say a ``region`` and nothing
    else) would light up the dashboard pill while every Amazon call
    still fails, so presence mirrors
    :func:`mureo.auth.load_amazon_ads_credentials`: a ``client_id`` plus
    either a stored ``access_token`` or the ``refresh_token`` +
    ``client_secret`` pair mureo mints one from.
    """
    if not isinstance(section, dict):
        return False
    if not section.get("client_id"):
        return False
    return bool(
        section.get("access_token")
        or (section.get("refresh_token") and section.get("client_secret"))
    )


def _detect_amazon_manifest(credentials_path: Path) -> dict[str, Any]:
    """Freshness of the Amazon tool manifest (audit #47).

    The manifest lives beside ``credentials.json``, and
    :func:`mureo.amazon_ads.manifest.manifest_path_for` is the one place
    that says so (#516). Resolving from the handed-in ``credentials_path``
    rather than from ``Path.home()`` is what keeps a test (or a non-default
    home) from being answered with the operator's real manifest.

    Read-only and never raises, like every other detector here: an unreadable
    or timestamp-less manifest reports ``present`` with an unknown age, and an
    unknown age is never called stale.
    """
    from mureo.amazon_ads.manifest import (
        is_stale,
        manifest_age_days,
        manifest_path_for,
    )

    path = manifest_path_for(credentials_path)
    present = path.exists()
    age = manifest_age_days(path) if present else None
    return {
        "present": present,
        "stale": is_stale(age),
        # Rounded for display: the dashboard shows "N days old", and a raw
        # float carries a precision this figure does not have.
        "age_days": None if age is None else round(age, 1),
    }


def _detect_amazon_token(credentials_path: Path) -> dict[str, Any]:
    """Amazon refresh-token age + expiry warning (#121).

    Amazon expires refresh tokens issued **on/after 2026-07-30** exactly
    :data:`AMAZON_REFRESH_TOKEN_LIFETIME_DAYS` days after the advertiser
    consented, and never tells the client when that was. The only issue
    date mureo can trust is the one the authorization wizard recorded
    itself (``amazon_ads.refresh_token_obtained_at``), so an absent or
    unparseable stamp reports an unknown age — and an unknown age is
    never warned about, because a pre-2026-07-30 token has no fixed
    expiry and nagging its owner annually would be false.

    Read-only and never raises, like every other detector here.
    """
    payload = read_json_safe(credentials_path)
    section = payload.get("amazon_ads")
    raw = (
        section.get("refresh_token_obtained_at") if isinstance(section, dict) else None
    )
    age = _refresh_token_age_days(raw)
    return {
        "refresh_token_age_days": age,
        "refresh_token_expiring": age is not None
        and age > AMAZON_REFRESH_TOKEN_WARN_DAYS,
    }


def _detect_meta_token(credentials_path: Path) -> dict[str, Any]:
    """Meta access-token age + expiry warning (#579).

    Two Meta tokens live in the same field and only one of them expires:

    - a **long-lived user token**, stored together with ``app_id`` and
      ``app_secret``, lives ~60 days. mureo exchanges it for a fresh one
      at :data:`META_ACCESS_TOKEN_WARN_DAYS`
      (:func:`mureo.auth._should_refresh`), so finding one still older
      than that on disk means the refresh is not happening — a browser
      OAuth that has not run in months, or an exchange Graph keeps
      rejecting. That is the state worth a nudge;
    - a **Business Manager system-user token** may be stored without the
      app pair, in which case mureo cannot exchange it at all. It is still
      stamped with an obtained-at date, so age alone would grow into a
      warning about a token no exchange is going to renew. The app pair —
      the same condition ``_should_refresh`` short-circuits on — is what
      separates the two.

    An absent or unparseable stamp reports an unknown age and never
    warns: a hand-entered token clears the stamp on purpose (#578), so
    "no stamp" means "off the clock", not "infinitely old".

    **The second, independent signal (#726): the token's own expiry.** A
    system-user token does not live forever — Business Manager mints it
    with a 60-day life — so the paste route asks Graph ``debug_token``
    when it dies and stores the answer as ``token_expires_at``. When that
    date is present it yields ``access_token_expires_in_days`` (negative
    once the token is dead) and, inside
    :data:`META_ACCESS_TOKEN_EXPIRY_WARN_DAYS`,
    ``access_token_expiry_warning``.

    That warning deliberately does NOT require the app pair. The age
    warning above means "an exchange that should have happened did not",
    which is meaningless without an exchange to make; this one means "this
    credential dies on Tuesday", which is worth saying loudest to exactly
    the operator mureo cannot help automatically.

    Read-only and never raises, like every other detector here.
    """
    payload = read_json_safe(credentials_path)
    section = payload.get("meta_ads")
    section = section if isinstance(section, dict) else {}
    age = _refresh_token_age_days(section.get("token_obtained_at"))
    refreshable = bool(section.get("app_id")) and bool(section.get("app_secret"))
    raw_expiry = section.get("token_expires_at")
    days_left = _days_until(raw_expiry)
    return {
        "access_token_age_days": age,
        "access_token_expiring": refreshable
        and age is not None
        and age > META_ACCESS_TOKEN_WARN_DAYS,
        # Echoed only when it parsed, so the UI never renders a date it
        # could not interpret.
        "access_token_expires_at": str(raw_expiry) if days_left is not None else None,
        "access_token_expires_in_days": days_left,
        "access_token_expiry_warning": days_left is not None
        and days_left < META_ACCESS_TOKEN_EXPIRY_WARN_DAYS,
    }


def _refresh_token_age_days(raw: Any) -> int | None:
    """Whole days since ``raw`` (ISO 8601), or ``None`` when unknowable.

    Accepts what the wizard writes (an explicit UTC offset) plus the two
    shapes a hand-edited file may carry: a ``Z`` suffix (rejected by
    ``datetime.fromisoformat`` before 3.11) and a naive timestamp, read
    as host-local — the same tolerance
    :mod:`mureo.amazon_ads.manifest` applies to ``generated_at``. A
    future stamp (clock skew) clamps to ``0`` rather than going negative.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        obtained = datetime.fromisoformat(text)
    except ValueError:
        return None
    if obtained.tzinfo is None:
        obtained = obtained.astimezone()
    delta = clock.server_now() - obtained
    return max(0, int(delta.total_seconds() // 86_400))


def _days_until(raw: Any) -> int | None:
    """Whole days from now until ``raw`` (ISO 8601), or ``None``.

    Same parsing tolerance as :func:`_refresh_token_age_days` — and the
    same helper would do, but for the sign: an age clamps at zero because a
    stamp in the future is clock skew, while a countdown that has run out is
    a real and important state. A token that died a week ago reports ``-7``,
    not ``0``; "expires in 0 days" would read as "today", which is the one
    thing it is not.
    """

    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        expires = datetime.fromisoformat(text)
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.astimezone()
    delta = expires - clock.server_now()
    return int(delta.total_seconds() // 86_400)


def _detect_credentials_oauth(credentials_path: Path) -> dict[str, bool]:
    """Report whether an OAuth refresh/access token has been saved.

    For Google the *adwords* and *webmasters* scopes share a single
    OAuth dance (see ``mureo.auth_setup._GOOGLE_SCOPES``), so this flag
    governs both Google Ads and Search Console re-auth UX.
    """
    payload = read_json_safe(credentials_path)
    google_section = payload.get("google_ads")
    meta_section = payload.get("meta_ads")
    return {
        "google": isinstance(google_section, dict)
        and bool(google_section.get("refresh_token")),
        "meta": isinstance(meta_section, dict)
        and bool(meta_section.get("access_token")),
    }


def _detect_legacy_commands(commands_dir: Path) -> bool:
    """Return True iff any known-legacy slash command file exists."""
    from mureo.web.legacy_commands import detect_legacy_commands

    return bool(detect_legacy_commands(commands_dir))


def _read_skill_version(skill_md: Path) -> str | None:
    """Return the mureo version a ``SKILL.md`` records about itself.

    Every shipped skill pins ``metadata.version`` to the mureo that shipped it
    (CI asserts the pin across all shipped files), and ``install_skills``
    copies the file verbatim — so the deployed copy carries the version of the
    mureo that deployed it, and that is the only thing on disk that can date it.

    Parsed line-wise instead of through :mod:`mureo.core.skills.parser`: that
    parser is the right one for loading a skill (YAML, capabilities,
    validation), and this module is a pure filesystem read on the status-poll
    path that must not pull the skills stack in behind it. Only the frontmatter
    block is looked at, so a ``version:`` line in the body cannot answer for
    the file.

    ``None`` when the file is unreadable, has no leading ``---`` block, or that
    block records no version. An unknown version is never treated as a match:
    a copy that cannot say where it came from predates the pin, which makes it
    older than every copy that can.
    """
    try:
        with skill_md.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_SKILL_HEAD_BYTES)
    except OSError:
        return None
    lines = head.splitlines()
    if not lines or lines[0].lstrip("\ufeff").rstrip() != _SKILL_FRONTMATTER_DELIM:
        return None
    for line in lines[1:]:
        if line.rstrip() == _SKILL_FRONTMATTER_DELIM:
            return None
        match = _SKILL_VERSION_RE.match(line)
        if match is not None:
            return match.group(1).strip("\"'")
    return None


def _shipped_skill_versions() -> dict[str, str | None]:
    """The skills this mureo would install, each with its recorded version.

    Read from ``mureo/_data/skills`` on disk rather than assumed to be
    :data:`mureo.__version__`. The two agree in any released install (CI pins
    them), but they disagree for exactly one process: the one running
    ``mureo upgrade``, which holds the OLD ``__version__`` in memory while the
    NEW package data is already on disk. Comparing deployed copies against the
    source files they were copied from is right in both cases.
    """
    from mureo.cli.setup_cmd import _get_data_path

    try:
        src = _get_data_path("skills")
        return {
            d.name: _read_skill_version(d / "SKILL.md")
            for d in sorted(src.iterdir())
            if d.is_dir() and (d / "SKILL.md").exists()
        }
    except OSError:  # unreadable package data — cannot claim anything is installed
        return {}


def _shipped_skill_names() -> frozenset[str]:
    """The names of the skills this mureo would install."""
    return frozenset(_shipped_skill_versions())


def _dominant_version(versions: Iterable[str | None]) -> str | None:
    """The one version worth naming in a one-line report.

    A skill set is normally all of one version, so this is that version. When
    it is not (a half-finished copy, a hand-edited file), the most common one
    describes the set better than an arbitrary member does; ties break on the
    lowest string so the answer never depends on iteration order.
    """
    counts = Counter(v for v in versions if v)
    if not counts:
        return None
    top = max(counts.values())
    return min(v for v, count in counts.items() if count == top)


def _detect_workflow_skills(skills_dir: Path) -> SkillsStatus:
    """Report whether ``skills_dir`` holds a current, stale or absent skill set.

    Detected, never recalled (#423). The old status came from a flag file that
    only the configure UI's own actions wrote, so a ``mureo setup`` install read
    ✗ while present, and a hand-deleted skill read ✓ while absent — the UI
    asserting a component is there when it is not.

    Presence alone was still not the question (#728). ``pip install -U mureo``
    never rewrites the deployed copies, so a skill from 0.10.39 sat in
    ``~/.claude/skills`` of a 0.17 install for months reading ✓ — running
    workflows written against tools that had moved on. So a set that is all
    there but not all CURRENT is its own state.

    A *missing* skill still outranks a stale one: the remedy is the same either
    way (re-run the install, which overwrites), and a half-installed set
    reported as ✓ is how an operator ends up without the workflow they think
    they have — the more urgent half of the fact leads.

    A skill whose SHIPPED copy records no version is not judged: mureo cannot
    date it, and inventing staleness out of package data it failed to read
    would make the check cry wolf on the install that is actually fine.
    """
    shipped = _shipped_skill_versions()
    expected = _dominant_version(shipped.values()) or __version__
    if not shipped:
        return SkillsStatus(state=SKILLS_MISSING, expected_version=expected)
    installed: dict[str, str | None] = {}
    absent = False
    for name in shipped:
        skill_md = skills_dir / name / "SKILL.md"
        if not skill_md.exists():
            absent = True
            continue
        installed[name] = _read_skill_version(skill_md)
    if absent:
        return SkillsStatus(SKILLS_MISSING, expected, installed)
    stale = any(
        installed[name] != shipped_version
        for name, shipped_version in shipped.items()
        if shipped_version is not None
    )
    return SkillsStatus(SKILLS_STALE if stale else SKILLS_CURRENT, expected, installed)


def _detect_auth_hook(host: str, settings_path: Path) -> bool:
    """Return True iff mureo's credential-guard PreToolUse hook is installed.

    Identified with :func:`mureo.credential_guard.is_guard_entry` — the same
    predicate the installer and the remover use. It is scoped to the entry's
    inner ``command`` field, so a user's own hook is never claimed as ours, and
    there is only ever one definition of "is this our guard" to keep correct.

    The path comes from ``settings_path``, never from a separately-threaded
    home: Codex keeps its hooks in ``hooks.json`` beside its config rather than
    inside it, and deriving that from the resolved :class:`HostPaths` keeps this
    reading the *same* tree the rest of the snapshot reads. (Taking a ``home``
    of its own would let a caller that passes only ``paths`` — as the handler
    does — silently read the operator's real ``~/.codex`` instead.)

    Claude Desktop has no ``PreToolUse`` surface, so the installer no-ops there
    and this is always False. A guard stranded in the *legacy* top-level
    ``PreToolUse`` list by a much older mureo reads as absent; re-running the
    install rewrites it into the nested shape, which is the safe direction.
    """
    if host == _HOST_DESKTOP:
        return False
    from mureo.credential_guard import is_guard_entry

    path = settings_path.parent / "hooks.json" if host == _HOST_CODEX else settings_path
    hooks = read_json_safe(path).get("hooks")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get("PreToolUse")
    return isinstance(entries, list) and any(is_guard_entry(e) for e in entries)


def _mask_value(name: str, value: str) -> str:
    """Return a UI-safe preview for an env var value.

    Secret-named vars get bullets + last 4 chars (or full bullets for
    very short values). Non-secret vars surface the full value so the
    operator can verify a file path or non-sensitive identifier.
    """
    if not value:
        return ""
    if _SECRET_NAME_RE.search(name) is None:
        return value
    if len(value) < _MASK_MIN_LENGTH:
        return "•" * 8
    return "••••" + value[-4:]


def _collect_env_vars(credentials_path: Path) -> dict[str, dict[str, Any]]:
    """Snapshot the configure-UI's known credential fields.

    Despite the historical ``env_vars`` field name (kept stable so the
    JSON contract does not break), values are sourced from
    ``credentials.json`` — not from ``os.environ``. The wizard and the
    "Set environment variable" dashboard form both persist into that
    file, so this is the only source of truth the UI should read.

    Returns ``{name: {"set": bool, "value_preview": str | None}}``. The
    value preview is masked for secret-named vars; the full value is
    *never* placed in a log line by this function.
    """
    payload = read_json_safe(credentials_path)
    out: dict[str, dict[str, Any]] = {}
    for name in allowed_env_var_names():
        target = get_env_var_target(name)
        if target is None:
            out[name] = {"set": False, "value_preview": None}
            continue
        section = payload.get(target.section)
        raw: Any = section.get(target.field) if isinstance(section, dict) else None
        if not isinstance(raw, str) or raw == "":
            out[name] = {"set": False, "value_preview": None}
            continue
        out[name] = {"set": True, "value_preview": _mask_value(name, raw)}
    return out


def collect_status(
    host: str,
    *,
    home: Path | None = None,
    paths: HostPaths | None = None,
    multi_account_auth: bool = False,
) -> StatusSnapshot:
    """Build a status snapshot for ``host``.

    ``multi_account_auth`` (#222) is relayed verbatim onto the snapshot —
    the caller (the handler) computes it behind the ``home is None`` gate,
    so this stays a pure filesystem read with no runtime-context coupling.
    """
    resolved = paths if paths is not None else get_host_paths(host, home)
    providers = _detect_installed_providers(resolved.mcp_registry_path)
    # Detected from disk, like every other row here — never recalled from a
    # flag file (#423). ``mureo_mcp`` reuses the provider detection above
    # rather than keeping a second source of truth for the same fact.
    skills = _detect_workflow_skills(resolved.skills_dir)
    setup_parts = SetupParts(
        mureo_mcp=providers[MUREO_NATIVE_ID],
        auth_hook=_detect_auth_hook(resolved.host, resolved.settings_path),
        # ``skills`` answers "is this a working set", which a set left behind
        # by an older mureo is not (#728) — the three fields below say which
        # way it fails, so a surface can tell "never installed" from "old".
        skills=skills.is_current,
        skills_state=skills.state,
        skills_expected_version=skills.expected_version,
        skills_installed_version=skills.installed_version,
    )
    creds = _detect_credentials_present(resolved.credentials_path)
    creds_oauth = _detect_credentials_oauth(resolved.credentials_path)
    env_vars = _collect_env_vars(resolved.credentials_path)
    legacy = _detect_legacy_commands(resolved.commands_dir)
    mureo_disable = _detect_mureo_disable(resolved.mcp_registry_path)
    amazon_manifest = _detect_amazon_manifest(resolved.credentials_path)
    amazon_token = _detect_amazon_token(resolved.credentials_path)
    meta_token = _detect_meta_token(resolved.credentials_path)
    return StatusSnapshot(
        host=resolved.host,
        setup_parts=setup_parts,
        providers_installed=providers,
        credentials_present=creds,
        credentials_oauth=creds_oauth,
        env_vars=env_vars,
        legacy_commands_present=legacy,
        mureo_disable=mureo_disable,
        multi_account_auth=multi_account_auth,
        amazon_manifest=amazon_manifest,
        amazon_token=amazon_token,
        meta_token=meta_token,
    )
