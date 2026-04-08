Save a marketing diagnosis insight to the pro-diagnosis skill file.

Use this command when you want to explicitly teach the agent a marketing insight, correction, or diagnostic pattern. The insight will be saved to `skills/mureo-pro-diagnosis/SKILL.md` and applied in future operations across all platforms.

## How to use

Run `/learn` followed by your insight. Examples:
- `/learn CV少ないサイトではマイクロCVを活用すべき`
- `/learn 予算5000円/日で広告グループ8個は多すぎる`
- `/learn Target CPAを下げすぎると逆にCV減る`

You can also run `/learn` without arguments — the agent will review the current conversation for corrections and insights to save.

## Steps

1. **Identify the insight**: If the user provided a specific insight as an argument, use that. If no argument is given, review the current conversation for moments where the user corrected the agent's analysis or provided marketing expertise.

2. **Read current skill**: Read `skills/mureo-pro-diagnosis/SKILL.md` to check for duplicate or conflicting insights.

3. **Structure the insight**: Format the insight using the template below:

   ```markdown
   ### [Short descriptive title]

   **Situation:** [When this insight applies]
   **Wrong assumption:** [What an inexperienced agent might think]
   **Correct approach:** [The right way to handle this situation]
   **Why:** [The reasoning behind the correct approach]

   Date learned: YYYY-MM-DD
   ```

4. **Present for approval**: Show the formatted insight to the user and ask for confirmation before saving.

5. **Save to skill file**: Append the approved insight to the "Learned Insights" section of `skills/mureo-pro-diagnosis/SKILL.md`. Do NOT save to memory — save to the skill file.

6. **Confirm**: Tell the user the insight has been saved and will be applied in future `/daily-check`, `/rescue`, `/budget-rebalance`, and other diagnostic workflows.

IMPORTANT: Always save to `skills/mureo-pro-diagnosis/SKILL.md`, never to Claude Code memory. The skill file persists across sessions and is read by all mureo commands.
