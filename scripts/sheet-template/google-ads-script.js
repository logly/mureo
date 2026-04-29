/**
 * mureo Google Ads Script — pulls last-N-day data into the mureo Sheet.
 *
 * Setup (5 minutes, one time per Google Ads account):
 *   1. Open Google Ads → Tools → Bulk actions → Scripts → +
 *   2. Paste this entire file into the editor.
 *   3. Set TARGET_SHEET_URL below to the URL of the mureo Sheet you
 *      copied from the published template.
 *   4. Click "Authorize", grant the read-only Google Ads + Sheets
 *      permissions, and click "Run".
 *   5. (Optional) Schedule daily/hourly runs from the same UI to keep
 *      the Sheet fresh.
 *
 * The script writes to four tabs in the target Sheet:
 *   - campaigns
 *   - ad_groups
 *   - search_terms
 *   - keywords
 *
 * Auction insights are intentionally excluded from this BYOD path:
 * Google Ads Scripts does not expose `auction_insight_domain` (GAQL)
 * and the legacy AWQL `AUCTION_INSIGHT_PERFORMANCE_REPORT` returns
 * "Report not mapped" — neither surface works from inside Ads Scripts.
 * Use the existing real-API path (mureo auth setup) for `/competitive-scan`
 * if you need competitor share data.
 *
 * The user then exports the Sheet as XLSX and feeds it to mureo via:
 *   mureo byod import --bundle <file>.xlsx
 *
 * mureo never sees the Google Ads credentials — Apps Script runs under
 * the user's own Google account on Google's infrastructure, and the
 * Sheet is in the user's own Drive. There is no mureo-managed OAuth
 * client, no developer token to apply for.
 */

// ===========================================================================
// USER CONFIGURATION
// ===========================================================================

// Paste the URL of your mureo Sheet copy here.
// Example: 'https://docs.google.com/spreadsheets/d/<sheet_id>/edit'
const TARGET_SHEET_URL = '';

// Lookback window (days). 14–30 is typical.
const DAYS_LOOKBACK = 30;


// ===========================================================================
// Constants
// ===========================================================================

const TAB_CAMPAIGNS = 'campaigns';
const TAB_AD_GROUPS = 'ad_groups';
const TAB_SEARCH_TERMS = 'search_terms';
const TAB_KEYWORDS = 'keywords';

const COST_DIVISOR = 1000000; // Google Ads returns cost in micros.


// ===========================================================================
// Entry point
// ===========================================================================

function main() {
  if (!TARGET_SHEET_URL) {
    throw new Error(
      'TARGET_SHEET_URL is empty. Paste your mureo Sheet URL at the top ' +
        'of this script and re-run.'
    );
  }

  const ss = SpreadsheetApp.openByUrl(TARGET_SHEET_URL);

  const dateRange = lastNDayRange_(DAYS_LOOKBACK);

  writeCampaigns_(ss, dateRange);
  writeAdGroups_(ss, dateRange);
  writeSearchTerms_(ss, dateRange);
  writeKeywords_(ss, dateRange);

  Logger.log(
    'mureo: wrote 4 tabs to ' + TARGET_SHEET_URL +
      ' (date range ' + dateRange.start + ' .. ' + dateRange.end + ')'
  );
}


// ===========================================================================
// Date helpers
// ===========================================================================

function lastNDayRange_(days) {
  const today = new Date();
  const start = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
  return {
    start: ymd_(start),
    end: ymd_(today),
    gaqlStart: gaqlYmd_(start),
    gaqlEnd: gaqlYmd_(today),
  };
}

function ymd_(date) {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  const d = String(date.getUTCDate()).padStart(2, '0');
  return y + '-' + m + '-' + d;
}

function gaqlYmd_(date) {
  // GAQL accepts YYYY-MM-DD with quotes when used as a string literal.
  return ymd_(date);
}


// ===========================================================================
// GAQL query runners
// ===========================================================================

function writeCampaigns_(ss, dateRange) {
  const query =
    "SELECT segments.date, campaign.name, " +
    "metrics.impressions, metrics.clicks, metrics.cost_micros, " +
    "metrics.conversions " +
    "FROM campaign " +
    "WHERE segments.date BETWEEN '" + dateRange.gaqlStart + "' AND '" +
    dateRange.gaqlEnd + "' " +
    "ORDER BY segments.date";

  const header = ['day', 'campaign', 'impressions', 'clicks', 'cost', 'conversions'];
  const rows = [];
  const it = AdsApp.search(query);
  while (it.hasNext()) {
    const r = it.next();
    rows.push([
      r.segments.date,
      r.campaign.name,
      Number(r.metrics.impressions || 0),
      Number(r.metrics.clicks || 0),
      Number(r.metrics.costMicros || 0) / COST_DIVISOR,
      Number(r.metrics.conversions || 0),
    ]);
  }
  writeTab_(ss, TAB_CAMPAIGNS, header, rows);
}

function writeAdGroups_(ss, dateRange) {
  const query =
    "SELECT segments.date, campaign.name, ad_group.name, " +
    "metrics.impressions, metrics.clicks, metrics.cost_micros, " +
    "metrics.conversions " +
    "FROM ad_group " +
    "WHERE segments.date BETWEEN '" + dateRange.gaqlStart + "' AND '" +
    dateRange.gaqlEnd + "' " +
    "ORDER BY segments.date";

  const header = [
    'day', 'campaign', 'ad_group',
    'impressions', 'clicks', 'cost', 'conversions',
  ];
  const rows = [];
  const it = AdsApp.search(query);
  while (it.hasNext()) {
    const r = it.next();
    rows.push([
      r.segments.date,
      r.campaign.name,
      r.adGroup.name,
      Number(r.metrics.impressions || 0),
      Number(r.metrics.clicks || 0),
      Number(r.metrics.costMicros || 0) / COST_DIVISOR,
      Number(r.metrics.conversions || 0),
    ]);
  }
  writeTab_(ss, TAB_AD_GROUPS, header, rows);
}

function writeSearchTerms_(ss, dateRange) {
  const query =
    "SELECT search_term_view.search_term, " +
    "campaign.name, ad_group.name, " +
    "metrics.impressions, metrics.clicks, metrics.cost_micros, " +
    "metrics.conversions " +
    "FROM search_term_view " +
    "WHERE segments.date BETWEEN '" + dateRange.gaqlStart + "' AND '" +
    dateRange.gaqlEnd + "'";

  const header = [
    'search_term', 'campaign', 'ad_group',
    'impressions', 'clicks', 'cost', 'conversions',
  ];
  const rows = [];
  const it = AdsApp.search(query);
  while (it.hasNext()) {
    const r = it.next();
    rows.push([
      r.searchTermView.searchTerm,
      r.campaign.name,
      r.adGroup.name,
      Number(r.metrics.impressions || 0),
      Number(r.metrics.clicks || 0),
      Number(r.metrics.costMicros || 0) / COST_DIVISOR,
      Number(r.metrics.conversions || 0),
    ]);
  }
  writeTab_(ss, TAB_SEARCH_TERMS, header, rows);
}

function writeKeywords_(ss, dateRange) {
  const query =
    "SELECT ad_group_criterion.keyword.text, " +
    "ad_group_criterion.keyword.match_type, " +
    "ad_group_criterion.quality_info.quality_score, " +
    "campaign.name, ad_group.name, " +
    "metrics.impressions, metrics.clicks, metrics.cost_micros, " +
    "metrics.conversions " +
    "FROM keyword_view " +
    "WHERE segments.date BETWEEN '" + dateRange.gaqlStart + "' AND '" +
    dateRange.gaqlEnd + "'";

  const header = [
    'keyword', 'match_type', 'quality_score',
    'campaign', 'ad_group',
    'impressions', 'clicks', 'cost', 'conversions',
  ];
  const rows = [];
  const it = AdsApp.search(query);
  while (it.hasNext()) {
    const r = it.next();
    const kw = r.adGroupCriterion.keyword;
    const qInfo = r.adGroupCriterion.qualityInfo || {};
    rows.push([
      kw ? kw.text : '',
      kw ? kw.matchType : '',
      Number(qInfo.qualityScore || 0),
      r.campaign.name,
      r.adGroup.name,
      Number(r.metrics.impressions || 0),
      Number(r.metrics.clicks || 0),
      Number(r.metrics.costMicros || 0) / COST_DIVISOR,
      Number(r.metrics.conversions || 0),
    ]);
  }
  writeTab_(ss, TAB_KEYWORDS, header, rows);
}

// ===========================================================================
// Sheet writer
// ===========================================================================

function writeTab_(ss, name, header, rows) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  sheet.clear();
  sheet.getRange(1, 1, 1, header.length)
    .setValues([header])
    .setFontWeight('bold');
  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, header.length).setValues(rows);
  }
  sheet.setFrozenRows(1);
}
