---
name: learn
description: "Save a marketing diagnosis insight to the pro-diagnosis knowledge base so it is applied in future operations across all platforms. Use when the user runs /learn, explicitly teaches the agent a marketing insight, corrects the agent's analysis, or asks to remember/record an operational learning for next time. Also use when the user asks in Japanese (この学びを記録して / 次回から反映して / 運用の気づきを覚えておいて)."
metadata:
  version: 0.10.32
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

The knowledge base has two tiers — an **operator** tier shared across
every workspace, and an optional **workspace** tier scoped to the
current one. Use `mureo learn tiers` to find out which are available
before deciding where an insight belongs (step 4).

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

4. **Choose the scope.** Before saving, detect which knowledge tiers
   this installation exposes. The command is read-only — it creates
   and modifies nothing:

   ```bash
   mureo learn tiers
   ```

   It prints one line per tier, e.g.:

   ```
   operator: configured
   workspace: configured
   ```

   - **`workspace: configured`** — ask the user which tier to save to,
     and present **workspace as the recommended default**. Most
     insights worth recording are account-specific: product quirks,
     measurement and conversion-tracking quirks, seasonality, campaign
     history, what has already been tried on this account. Those are
     true here and often false elsewhere, so writing them to the
     operator tier makes every other account inherit them and the
     agent will confidently misapply them. Reserve the operator tier
     for genuinely generalizable cross-account know-how — platform
     mechanics, statistical reasoning, structural rules of thumb.
   - **`workspace: absent`** — no workspace tier is installed on this
     machine. Save to the operator tier without asking the user.

5. **Save by invoking the CLI.** Pass the approved insight verbatim
   (including its leading blank line and trailing newline), with the
   scope from step 4 stated explicitly:

   ```bash
   # Run ONE of these — the scope you settled on in step 4.
   mureo learn add "$INSIGHT_MARKDOWN" --scope workspace
   mureo learn add "$INSIGHT_MARKDOWN" --scope operator
   ```

   - `--scope operator` writes the cross-workspace tier read by every
     diagnostic skill.
   - `--scope workspace` writes the workspace-scoped tier, so the
     insight stays with the active account and never leaks to other
     workspaces. The command exits with a helpful message when no
     workspace tier is configured — step 4 rules that case out.

   Both tiers are handed to diagnostic workflows by
   `mureo_learning_insights_get`; when the two conflict, workspace-tier
   insights take precedence over operator-tier insights.

6. **Confirm.** Tell the user the insight was saved, which tier it went
   to, and that it will be applied in future `/daily-check`,
   `/rescue`, `/budget-rebalance`, and other diagnostic workflows.

IMPORTANT: Always save through `mureo learn add`, never by writing the
file path manually. Going through the CLI keeps the skill compatible
with alternate KnowledgeStore backends and avoids the agent having to
know about the scaffold/file layout. Never save to Claude Code memory;
the on-disk knowledge base persists across sessions, Claude memory
does not.
