Synchronize STATE.json with the current state of all advertising accounts.

## Prerequisites
- STRATEGY.md and STATE.json should exist in the current directory (run `/onboard` first if not)

## Steps

1. **Read current STATE.json** (if exists) to track changes.

2. **Fetch Google Ads data**:
   - `google_ads.campaigns.list` with status details
   - For each campaign: budget, bidding strategy, status

3. **Fetch Meta Ads data**:
   - `meta_ads.campaigns.list` with status details

4. **Update STATE.json** with all campaign snapshots.

5. **Show diff**: Compare old vs new state and highlight changes:
   - New campaigns added
   - Campaigns removed/paused
   - Budget changes
   - Status changes
   - Bidding strategy changes

6. **Update `last_synced_at`** timestamp.

If STATE.json doesn't exist yet, suggest running `/onboard` first.
