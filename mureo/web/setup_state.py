"""Which basic-setup components are installed.

Once a *record*: the configure UI wrote a flag file whenever one of its own
actions ran, and read the status back out of it. That made the flag the only
source of truth for three rows that every other row on the status snapshot
detects from disk — so an install done any other way (``mureo setup``, by
hand) read as absent, and a component deleted after a UI install read as
present. The second is the dangerous direction: the UI asserts a
guardrail-bearing component is there when it is not, and nothing prompts the
operator to look (#423).

So this is now just the shape. ``status_collector`` fills it by detecting each
part on disk — the credential-guard hook by its tag, the skills by presence in
the host's skills dir, the mureo MCP block by the same registry read that
already reports every other provider. A ``setup_state.json`` left over from an
older mureo is simply ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

PART_MCP = "mureo_mcp"
PART_HOOK = "auth_hook"
PART_SKILLS = "skills"

KNOWN_PARTS: tuple[str, ...] = (PART_MCP, PART_HOOK, PART_SKILLS)


@dataclass(frozen=True)
class SetupParts:
    """Whether each basic-setup component is installed, as found on disk."""

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
