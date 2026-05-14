"""Persistent record of which basic-setup steps have been run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.web._helpers import atomic_write_json, read_json_safe

SETUP_STATE_FILENAME = "setup_state.json"

PART_MCP = "mureo_mcp"
PART_HOOK = "auth_hook"
PART_SKILLS = "skills"

KNOWN_PARTS: tuple[str, ...] = (PART_MCP, PART_HOOK, PART_SKILLS)


@dataclass(frozen=True)
class SetupParts:
    """Whether each basic-setup component has been installed."""

    mureo_mcp: bool = False
    auth_hook: bool = False
    skills: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            PART_MCP: self.mureo_mcp,
            PART_HOOK: self.auth_hook,
            PART_SKILLS: self.skills,
        }

    def all_installed(self) -> bool:
        return self.mureo_mcp and self.auth_hook and self.skills


def state_file_path(home: Path | None = None) -> Path:
    """Return the canonical setup_state.json location."""
    base = home if home is not None else Path.home()
    return base / ".mureo" / SETUP_STATE_FILENAME


def read_setup_state(home: Path | None = None) -> SetupParts:
    """Load the persisted setup-parts record."""
    payload = read_json_safe(state_file_path(home))
    return SetupParts(
        mureo_mcp=bool(payload.get(PART_MCP, False)),
        auth_hook=bool(payload.get(PART_HOOK, False)),
        skills=bool(payload.get(PART_SKILLS, False)),
    )


def write_setup_state(parts: SetupParts, home: Path | None = None) -> None:
    """Persist ``parts`` to ``setup_state.json`` (atomic + 0o600)."""
    payload: dict[str, Any] = parts.as_dict()
    atomic_write_json(state_file_path(home), payload)


def mark_part_installed(part: str, home: Path | None = None) -> SetupParts:
    """Flip one part to True and persist."""
    if part not in KNOWN_PARTS:
        raise ValueError(f"unknown setup part: {part!r}")
    current = read_setup_state(home)
    updated = SetupParts(
        mureo_mcp=current.mureo_mcp or part == PART_MCP,
        auth_hook=current.auth_hook or part == PART_HOOK,
        skills=current.skills or part == PART_SKILLS,
    )
    write_setup_state(updated, home)
    return updated


def clear_part(part: str, home: Path | None = None) -> SetupParts:
    """Reset one part to False (used by uninstall flows)."""
    if part not in KNOWN_PARTS:
        raise ValueError(f"unknown setup part: {part!r}")
    current = read_setup_state(home)
    updated = SetupParts(
        mureo_mcp=current.mureo_mcp and part != PART_MCP,
        auth_hook=current.auth_hook and part != PART_HOOK,
        skills=current.skills and part != PART_SKILLS,
    )
    write_setup_state(updated, home)
    return updated
