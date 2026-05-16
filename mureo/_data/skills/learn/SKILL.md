---
name: learn
description: "Save a marketing diagnosis insight to the pro-diagnosis knowledge base so it is applied in future operations across all platforms. Use when the user runs /learn, explicitly teaches the agent a marketing insight, corrects the agent's analysis, or asks to remember/record an operational learning for next time."
metadata:
  version: 0.7.1
---

# Learn

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Save a marketing diagnosis insight to the pro-diagnosis knowledge base
(`../_mureo-pro-diagnosis/SKILL.md`). Saved insights are loaded at the
start of future sessions and applied across `/daily-check`, `/rescue`,
`/budget-rebalance`, and the other diagnostic workflows.

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

2. **Locate the knowledge base.** The target is the sibling skill file
   `../_mureo-pro-diagnosis/SKILL.md` (relative to this skill, i.e.
   `~/.claude/skills/_mureo-pro-diagnosis/SKILL.md` for an installed
   user). If it already exists, read it first to avoid duplicate or
   conflicting entries. If it does **not** exist (it is not shipped — it
   grows per account), create the directory and seed the file with this
   minimal scaffold before appending:

   ```markdown
   ---
   name: _mureo-pro-diagnosis
   description: "Professional marketing diagnostic frameworks: expert-level campaign analysis that grows with your experience."
   metadata:
     version: 0.1.0
   ---

   # Pro Diagnosis — Account Knowledge Base

   Insights learned from operating this account, applied by every mureo
   diagnostic workflow.

   ## Learned Insights
   ```

3. **Structure the insight** using this template:

   ```markdown
   ### [Short descriptive title]

   **Situation:** [When this insight applies]
   **Wrong assumption:** [What an inexperienced agent might think]
   **Correct approach:** [The right way to handle this situation]
   **Why:** [The reasoning behind the correct approach]

   Date learned: YYYY-MM-DD
   ```

4. **Present for approval.** Show the formatted insight to the user and
   ask for explicit confirmation before writing anything. Capture the
   generalized lesson only — never record account IDs, credentials,
   access tokens, or personal data in the knowledge base.

5. **Save.** Append the approved insight under the `## Learned Insights`
   section of `../_mureo-pro-diagnosis/SKILL.md` (creating the file from
   the scaffold in step 2 first if it was absent). Append only — never
   rewrite or reorder existing entries.

6. **Confirm.** Tell the user the insight was saved and that it will be
   applied in future `/daily-check`, `/rescue`, `/budget-rebalance`, and
   other diagnostic workflows.

IMPORTANT: Always save to `../_mureo-pro-diagnosis/SKILL.md`, never to
Claude Code memory. The skill file persists across sessions and is read
by all mureo diagnostic workflows; Claude memory is not.
