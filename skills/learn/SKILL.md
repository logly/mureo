---
name: learn
description: "Save a marketing diagnosis insight to the pro-diagnosis knowledge base so it is applied in future operations across all platforms. Use when the user runs /learn, explicitly teaches the agent a marketing insight, corrects the agent's analysis, or asks to remember/record an operational learning for next time. Also use when the user asks in Japanese (この学びを記録して / 次回から反映して / 運用の気づきを覚えておいて)."
metadata:
  version: 0.10.24
---

# Learn

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Save a marketing diagnosis insight to the pro-diagnosis knowledge base.
Saved insights are loaded at the start of future sessions and applied
across `/daily-check`, `/rescue`, `/budget-rebalance`, and the other
diagnostic workflows.

The skill persists insights by shelling out to `mureo learn add`,
which routes the write through the KnowledgeStore Protocol. The
default backend writes to
`~/.claude/skills/_mureo-pro-diagnosis/SKILL.md` (preserving the
prior file layout); an alternate backend registered via the
`mureo.runtime_context_factory` entry-point group can redirect or
split the write without changing this skill.

## When to use

- The user runs `/learn` followed by an insight, e.g.:
  - `/learn CV少ないサイトではマイクロCVを活用すべき`
  - `/learn 予算5000円/日で広告グループ8個は多すぎる`
  - `/learn Target CPA を下げすぎると逆に CV が減る`
- The user runs `/learn` with no argument — review the current
  conversation for corrections or marketing expertise the user shared
  and propose those as insights.

## Steps

1. **Identify the insight.** If the user passed an insight as the
   argument, use it. Otherwise review the current conversation for
   moments where the user corrected the agent's analysis or supplied
   marketing expertise, and select the most reusable one(s).

2. **Structure the insight** using this template:

   ```markdown
   ### [Short descriptive title]

   **Situation:** [When this insight applies]
   **Wrong assumption:** [What an inexperienced agent might think]
   **Correct approach:** [The right way to handle this situation]
   **Why:** [The reasoning behind the correct approach]

   Date learned: YYYY-MM-DD
   ```

3. **Present for approval.** Show the formatted insight to the user
   and ask for explicit confirmation before saving. Capture the
   generalized lesson only — never record account IDs, credentials,
   access tokens, or personal data in the knowledge base.

4. **Save by invoking the CLI.** Pass the approved insight verbatim
   (including its leading blank line and trailing newline) to:

   ```bash
   mureo learn add "$INSIGHT_MARKDOWN"
   ```

   - The default `--scope operator` writes the cross-workspace tier
     read by every diagnostic skill. Use this for general practitioner
     know-how that applies to every account the operator runs.
   - Pass `--scope workspace` when the insight is specific to the
     active account and should not leak to other workspaces (only
     meaningful when a workspace-aware KnowledgeStore backend is
     installed; the command exits with a helpful message otherwise).

5. **Confirm.** Tell the user the insight was saved and that it will
   be applied in future `/daily-check`, `/rescue`, `/budget-rebalance`,
   and other diagnostic workflows.

IMPORTANT: Always save through `mureo learn add`, never by writing the
file path manually. Going through the CLI keeps the skill compatible
with alternate KnowledgeStore backends and avoids the agent having to
know about the scaffold/file layout. Never save to Claude Code memory;
the on-disk knowledge base persists across sessions, Claude memory
does not.
