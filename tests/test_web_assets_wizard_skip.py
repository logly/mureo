"""Static-content guard: the "Pick your platforms" wizard step is skippable.

The configure wizard gates the Next button on the platforms step until
at least one platform is selected (`isNextEnabled` → `platforms` branch).
An operator who wants to defer platform setup and go straight to the
dashboard would otherwise be stranded on a disabled Next with no way
out. The shared Skip button (footer, `data-wizard-action="skip"`, wired
to `gotoNext`) surfaces on any step NOT listed in `STEPS_WITHOUT_SKIP`,
so the fix is to drop `"platforms"` from that set.

These tests pin that behaviour so a future refactor of the step list
cannot silently re-strand the operator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _steps_without_skip_block() -> str:
    """Return the source slice of the ``STEPS_WITHOUT_SKIP`` Set literal.

    Extracts everything between ``new Set([`` and the closing ``])`` so
    membership assertions are scoped to that declaration and cannot be
    fooled by the step keys appearing elsewhere in the file.
    """
    js = (_WEB / "wizard.js").read_text(encoding="utf-8")
    marker = "STEPS_WITHOUT_SKIP = new Set(["
    start = js.index(marker) + len(marker)
    end = js.index("])", start)
    return js[start:end]


@pytest.mark.unit
def test_platforms_step_is_skippable() -> None:
    """``"platforms"`` must NOT be in ``STEPS_WITHOUT_SKIP`` so the Skip
    button surfaces on the platform-selection step."""
    assert '"platforms"' not in _steps_without_skip_block()


@pytest.mark.unit
def test_gateway_steps_stay_non_skippable() -> None:
    """The terminal / prerequisite steps must keep their no-skip status:
    `host` (a host must be chosen), `basic` (has its own advanced-skip
    affordance), and `completed` (terminal — nothing to skip to)."""
    block = _steps_without_skip_block()
    assert '"host"' in block
    assert '"basic"' in block
    assert '"completed"' in block
