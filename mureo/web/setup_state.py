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
from typing import Any

PART_MCP = "mureo_mcp"
PART_HOOK = "auth_hook"
PART_SKILLS = "skills"

KNOWN_PARTS: tuple[str, ...] = (PART_MCP, PART_HOOK, PART_SKILLS)

# #728 — the skills row carries three extra facts beyond its boolean: which
# of the three states it is in, which mureo this package ships skills for,
# and which mureo the deployed copies actually came from. Not parts: nothing
# installs or removes them, and ``KNOWN_PARTS`` stays the installable three.
FIELD_SKILLS_STATE = "skills_state"
FIELD_SKILLS_EXPECTED_VERSION = "skills_expected_version"
FIELD_SKILLS_INSTALLED_VERSION = "skills_installed_version"


@dataclass(frozen=True)
class SetupParts:
    """Whether each basic-setup component is installed, as found on disk."""

    mureo_mcp: bool = False
    auth_hook: bool = False
    skills: bool = False
    # #728: ``skills`` is True only for a CURRENT set — a set left behind by
    # an older mureo is not a working set, and every existing consumer (the
    # dashboard row, the wizard's completion gate, the landing page) already
    # reads that boolean as "is this usable". The three fields below say WHY
    # it is False so a surface can tell "never installed" from "installed
    # months ago", which is the whole point of the issue.
    skills_state: str = "missing"
    skills_expected_version: str = ""
    skills_installed_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            PART_MCP: self.mureo_mcp,
            PART_HOOK: self.auth_hook,
            PART_SKILLS: self.skills,
            FIELD_SKILLS_STATE: self.skills_state,
            FIELD_SKILLS_EXPECTED_VERSION: self.skills_expected_version,
            FIELD_SKILLS_INSTALLED_VERSION: self.skills_installed_version,
        }

    def all_installed(self) -> bool:
        return self.mureo_mcp and self.auth_hook and self.skills
