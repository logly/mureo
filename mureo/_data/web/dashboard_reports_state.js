// dashboard_reports_state.js — what every module of the Reports view shares.
//
// Split out of dashboard_reports.js (#687), which was 2,139 lines. Three
// things live here, and the third is the one that made the split possible:
//
//   1. The load-order guard for the five DOM-free reports_*.js modules, and
//      the bindings that give their functions back their original names, so
//      every call site downstream reads exactly as it did.
//   2. `REPORTS_KPI_LABELS`, the secondary-KPI display vocabulary.
//   3. `REPORTS_VIEW_STATE` — the ten values the view mutates as an operator
//      moves through it: the selected window, the client on screen, which of
//      index/detail is showing, the cached roster, whether the registry can
//      archive, the monotonic render generation, and the four the alert list
//      and the health filter keep between renders (which rows are open,
//      whether the list is showing everything, the layer as it was last
//      built, and the health the grid is filtered to).
//
// Those ten used to be `let`s in one closure, and they are why this file was
// not splittable: each is written on one side of some seam in this layer and
// read on the other, and two `<script>` IIFEs cannot share a `let`. They can
// share an OBJECT, because every module holds the same reference. That is the
// entire change — same ten values, same defaults, same prose.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_STATE`. Must load AFTER the five
// reports_*.js modules and BEFORE the five dashboard_reports*.js files that
// bind from it — dashboard_reports_report.js is the first of them.

(function () {
  "use strict";

  // The parts of this section that need no DOM live in their own plain
  // `<script>` modules, loaded ahead of this file (see app.html):
  //
  //   reports_logic.js  (#540) — the KPI-withholding condition, the
  //     freshness aggregation and the conflict-kind routing.
  //   reports_format.js (#556) — the display vocabulary: a flag's label and
  //     severity, a param's detail line, a number's and a period's text.
  //   reports_order.js  (#556) — the operator's card order: where it is
  //     stored, how it is applied, and the two ways it changes.
  //   reports_triage.js (#651) — which clients need attention today, in
  //     what order, and what to run about each.
  //   reports_overview.js — the index view's own decisions: which view the
  //     Reports section shows, and the portfolio-level figures above the grid.
  //
  // Everything below still needs a DOM. The modules are bound here by their
  // original names so every call site downstream reads exactly as before.
  //
  // Failing at load is deliberate — the alternative is a conflicted client's
  // double-counted totals rendering because the withholding helper quietly
  // became `undefined`. Everything above this point is declarations, so
  // nothing observable has happened yet when this throws: no listener is
  // registered, no fetch is issued, no node reaches the DOM. But it does
  // take the whole configure UI with it, so it names WHICH modules are
  // missing and what fixes it rather than leaving whoever hits it to
  // reverse-engineer a bare "cannot read properties of undefined".
  //
  // ALL of them, not the first: a deployment that dropped the whole block of
  // <script> tags would otherwise be diagnosed one reload at a time.
  const missingReportsModules = [
    ["MUREO_REPORTS_LOGIC", "reports_logic.js"],
    ["MUREO_REPORTS_FORMAT", "reports_format.js"],
    ["MUREO_REPORTS_ORDER", "reports_order.js"],
    ["MUREO_REPORTS_TRIAGE", "reports_triage.js"],
    ["MUREO_REPORTS_OVERVIEW", "reports_overview.js"],
  ].filter(function (mod) {
    return !window[mod[0]];
  });
  if (missingReportsModules.length) {
    throw new Error(
      "dashboard.js: " +
        missingReportsModules
          .map(function (mod) {
            return "window." + mod[0] + " (" + mod[1] + ")";
          })
          .join(", ") +
        " is missing. Each must be served (see _STATIC_ALLOWLIST in " +
        "mureo/web/handlers.py) and its <script> tag must come BEFORE " +
        "dashboard.js in app.html."
    );
  }

  const REPORTS_LOGIC = window.MUREO_REPORTS_LOGIC;
  const relativeAge = REPORTS_LOGIC.relativeAge;
  const reportsPlatformLabels = REPORTS_LOGIC.reportsPlatformLabels;
  const reportsConflictText = REPORTS_LOGIC.reportsConflictText;
  const reportsRepairHint = REPORTS_LOGIC.reportsRepairHint;
  const reportsConflictsForKey = REPORTS_LOGIC.reportsConflictsForKey;
  const reportsFreshnessLabel = REPORTS_LOGIC.reportsFreshnessLabel;
  const reportsRowIsStale = REPORTS_LOGIC.reportsRowIsStale;
  const reportsNotCollectedNote = REPORTS_LOGIC.reportsNotCollectedNote;
  const reportsNotCollectedNotes = REPORTS_LOGIC.reportsNotCollectedNotes;
  const reportsNotCollectedText = REPORTS_LOGIC.reportsNotCollectedText;
  const reportsCardFreshness = REPORTS_LOGIC.reportsCardFreshness;
  const aggregateClientKpis = REPORTS_LOGIC.aggregateClientKpis;

  const REPORTS_FORMAT = window.MUREO_REPORTS_FORMAT;
  const reportsPeriodLabel = REPORTS_FORMAT.reportsPeriodLabel;
  const isCanonicalReportsPeriod = REPORTS_FORMAT.isCanonicalReportsPeriod;
  const humanizeReportFlag = REPORTS_FORMAT.humanizeReportFlag;
  const humanizeFlagWords = REPORTS_FORMAT.humanizeFlagWords;
  const reportFlagKind = REPORTS_FORMAT.reportFlagKind;
  const flagSeverityRank = REPORTS_FORMAT.flagSeverityRank;
  const latestReport = REPORTS_FORMAT.latestReport;
  const clientReportFlags = REPORTS_FORMAT.clientReportFlags;
  const buildFlagDetail = REPORTS_FORMAT.buildFlagDetail;
  const formatNumber = REPORTS_FORMAT.formatNumber;
  const formatKpi = REPORTS_FORMAT.formatKpi;
  const reportSummaryTotals = REPORTS_FORMAT.reportSummaryTotals;
  const reportSecondaryStats = REPORTS_FORMAT.reportSecondaryStats;
  const reportStatLabel = REPORTS_FORMAT.reportStatLabel;

  const REPORTS_ORDER = window.MUREO_REPORTS_ORDER;
  const orderReportsClients = REPORTS_ORDER.orderReportsClients;
  const persistReportsOrderFromDom = REPORTS_ORDER.persistReportsOrderFromDom;
  const moveReportsCard = REPORTS_ORDER.moveReportsCard;

  const REPORTS_TRIAGE = window.MUREO_REPORTS_TRIAGE;
  const buildReportsTriage = REPORTS_TRIAGE.buildReportsTriage;
  const triageMarksClient = REPORTS_TRIAGE.triageMarksClient;
  const triageItemText = REPORTS_TRIAGE.triageItemText;
  const triageItemNextStep = REPORTS_TRIAGE.triageItemNextStep;
  const triageItemSeverity = REPORTS_TRIAGE.triageItemSeverity;
  const triageItemTag = REPORTS_TRIAGE.triageItemTag;
  const triageClientHealth = REPORTS_TRIAGE.triageClientHealth;
  const triageHealthCounts = REPORTS_TRIAGE.triageHealthCounts;
  const triageClientBadges = REPORTS_TRIAGE.triageClientBadges;
  const groupReportsTriage = REPORTS_TRIAGE.groupReportsTriage;
  const partitionTriageGroups = REPORTS_TRIAGE.partitionTriageGroups;
  const dismissTriageGroup = REPORTS_TRIAGE.dismissTriageGroup;
  const dismissTriageItem = REPORTS_TRIAGE.dismissTriageItem;
  const restoreTriageDismissals = REPORTS_TRIAGE.restoreTriageDismissals;
  const collapseTriageGroups = REPORTS_TRIAGE.collapseTriageGroups;

  const REPORTS_OVERVIEW = window.MUREO_REPORTS_OVERVIEW;
  const reportsViewToShow = REPORTS_OVERVIEW.reportsViewToShow;
  const buildReportsPortfolio = REPORTS_OVERVIEW.buildReportsPortfolio;
  const clientPlatformSplit = REPORTS_OVERVIEW.clientPlatformSplit;
  const platformColorSlot = REPORTS_OVERVIEW.platformColorSlot;
  const buildReportsActionFeed = REPORTS_OVERVIEW.buildReportsActionFeed;

  // Canonical secondary KPI vocabulary → i18n label key. Headline (spend)
  // is rendered separately. Order here is the on-card display order.
  const REPORTS_KPI_LABELS = {
    conversions: "dashboard.reports_kpi_conversions",
    cpa: "dashboard.reports_kpi_cpa",
    ctr: "dashboard.reports_kpi_ctr",
    clicks: "dashboard.reports_kpi_clicks",
    impressions: "dashboard.reports_kpi_impressions",
  };

  // The Reports view's own state, on ONE object rather than ten `let`s.
  //
  // Ten variables, and every one of them is written on one side of some
  // seam in this layer and read on the other. Two `<script>` IIFEs cannot
  // share a `let`, so a file this size could not be cut while they were
  // bindings; an object CAN be shared, because every module holds the same
  // reference. That is the whole reason this exists — the fields below are
  // the same ten values, with the same defaults and the same prose.
  //
  // `const`, and never reassigned: `reportsRenderSeq` is the #223 generation
  // guard, and both `++state.reportsRenderSeq` and the `seq !== ...` compare
  // that follows must reach the same object. One `const` binding is what
  // guarantees they do.
  const REPORTS_VIEW_STATE = {
    // The selected window. Default = YESTERDAY (daily-check runs every day, so
    // the prior day is what an operator checks first). Reconciled against the
    // summary's `periods` union on each render — falls back to the first
    // available window when YESTERDAY has no data yet.
    reportsPeriod: "YESTERDAY",

    // The client whose detail is on screen — so the period toggle re-fetches
    // the SAME client.
    reportsActiveClient: null,

    // Reports navigation: "index" (the client overview grid) or "detail" (one
    // client's full report). A single-client (OSS) install has no index and
    // stays on "detail". The last-fetched client list is cached so a back /
    // period re-render does not need to re-resolve it.
    reportsView: "index",
    // EVERY client the registry returned, archived ones included. The index
    // renders only the visible ones, but the routing decision counts them all
    // — see renderReports().
    reportsClients: [],

    // Whether the backing client registry can record an archive decision
    // (`can_archive` off /api/reports/clients). False on an OSS-only install:
    // there is no registry there, so the control is not rendered AT ALL rather
    // than rendered and inert.
    reportsCanArchive: false,

    // Monotonic render generation (mirrors renderPluginCredentials #223):
    // the section clears then awaits a fetch, so an interleaved re-render
    // (locale change, client switch, period switch) must not let a stale
    // result append.
    reportsRenderSeq: 0,

    // Which rows are expanded, by kind. Dismissing one message re-renders the
    // list, and a row that snapped shut after every ✕ would make closing six
    // findings six trips through the disclosure. Reset with the list itself on
    // every index render.
    reportsTriageOpenKinds: {},
    // Whether the alert list is showing every row it has. Reset on every index
    // render — the list opens short each time the operator arrives, which is
    // the whole point of opening short.
    reportsTriageShowAll: false,
    // The layer as it was last built, so closing or restoring a row can redraw
    // it without re-fetching every client's summary.
    reportsTriageBuilt: null,
    // Which health the grid is filtered to. "all" until the operator says
    // otherwise, and reset on every index render: a filter that survived a
    // re-render would leave cards missing with no visible reason.
    reportsHealthFilter: "all",
  };


  const api = {
    REPORTS_LOGIC: REPORTS_LOGIC,
    relativeAge: relativeAge,
    reportsPlatformLabels: reportsPlatformLabels,
    reportsConflictText: reportsConflictText,
    reportsRepairHint: reportsRepairHint,
    reportsConflictsForKey: reportsConflictsForKey,
    reportsFreshnessLabel: reportsFreshnessLabel,
    reportsRowIsStale: reportsRowIsStale,
    reportsNotCollectedNote: reportsNotCollectedNote,
    reportsNotCollectedNotes: reportsNotCollectedNotes,
    reportsNotCollectedText: reportsNotCollectedText,
    reportsCardFreshness: reportsCardFreshness,
    aggregateClientKpis: aggregateClientKpis,
    REPORTS_FORMAT: REPORTS_FORMAT,
    reportsPeriodLabel: reportsPeriodLabel,
    isCanonicalReportsPeriod: isCanonicalReportsPeriod,
    humanizeReportFlag: humanizeReportFlag,
    humanizeFlagWords: humanizeFlagWords,
    reportFlagKind: reportFlagKind,
    flagSeverityRank: flagSeverityRank,
    latestReport: latestReport,
    clientReportFlags: clientReportFlags,
    buildFlagDetail: buildFlagDetail,
    formatNumber: formatNumber,
    formatKpi: formatKpi,
    reportSummaryTotals: reportSummaryTotals,
    reportSecondaryStats: reportSecondaryStats,
    reportStatLabel: reportStatLabel,
    REPORTS_ORDER: REPORTS_ORDER,
    orderReportsClients: orderReportsClients,
    persistReportsOrderFromDom: persistReportsOrderFromDom,
    moveReportsCard: moveReportsCard,
    REPORTS_TRIAGE: REPORTS_TRIAGE,
    buildReportsTriage: buildReportsTriage,
    triageMarksClient: triageMarksClient,
    triageItemText: triageItemText,
    triageItemNextStep: triageItemNextStep,
    triageItemSeverity: triageItemSeverity,
    triageItemTag: triageItemTag,
    triageClientHealth: triageClientHealth,
    triageHealthCounts: triageHealthCounts,
    triageClientBadges: triageClientBadges,
    groupReportsTriage: groupReportsTriage,
    partitionTriageGroups: partitionTriageGroups,
    dismissTriageGroup: dismissTriageGroup,
    dismissTriageItem: dismissTriageItem,
    restoreTriageDismissals: restoreTriageDismissals,
    collapseTriageGroups: collapseTriageGroups,
    REPORTS_OVERVIEW: REPORTS_OVERVIEW,
    reportsViewToShow: reportsViewToShow,
    buildReportsPortfolio: buildReportsPortfolio,
    clientPlatformSplit: clientPlatformSplit,
    platformColorSlot: platformColorSlot,
    buildReportsActionFeed: buildReportsActionFeed,
    REPORTS_KPI_LABELS: REPORTS_KPI_LABELS,
    REPORTS_VIEW_STATE: REPORTS_VIEW_STATE,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_STATE = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
