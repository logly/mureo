Synchronize STATE.json with the current state of all marketing platforms.

## Prerequisites
- STRATEGY.md and STATE.json should exist in the current directory (run `/onboard` first if not)

## Steps

1. **Read current STATE.json** (if exists) to track changes.

2. **Discover platforms**: Identify all platforms registered in STATE.json `platforms`.

3. **Fetch platform data**: For each registered platform, fetch current campaign data using the platform's campaign listing tools.

4. **Check data sources**: If Search Console is configured, verify site access is still valid. If GA4 is available, verify connectivity.

5. **Detect new platforms**: If new platform credentials exist but have no entry in `platforms`, prompt the user to run `/onboard` to add them.

6. **Verify STRATEGY.md Data Sources**: If STRATEGY.md is missing a `## Data Sources` section (older setup), prompt the user to add it listing all configured platforms.

7. **Update STATE.json** with all campaign snapshots.

8. **Show diff**: Compare old vs new state and highlight changes:
   - New campaigns added
   - Campaigns removed/paused
   - Budget changes
   - Status changes
   - Bidding strategy changes

9. **Update `last_synced_at`** timestamp.

If STATE.json doesn't exist yet, suggest running `/onboard` first.
