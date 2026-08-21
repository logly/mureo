// dashboard_reports.js — the Reports section's rendering layer.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move: same functions, same bodies, same order, same module-level state.
//
// This is the DOM half. The decisions it renders live in the five DOM-free
// modules loaded ahead of it — reports_logic.js, reports_format.js,
// reports_order.js, reports_triage.js and reports_overview.js — and are bound
// by their original names in the block below so every call site downstream
// reads exactly as before. That binding block, and the guard that fails loudly
// when one of those modules is missing, moved here with the code that needs
// them: it is this file, not dashboard.js, that holds `undefined` if a
// `<script>` tag is dropped.
//
// It did not split further, and the reason is worth stating so the next
// reader does not try. Six `let`s — `reportsPeriod`, `reportsActiveClient`,
// `reportsView`, `reportsClients`, `reportsCanArchive`, `reportsRenderSeq` —
// are written on one side of every candidate seam and read on the other. Two
// `<script>` IIFEs cannot share a `let`, so cutting here would mean promoting
// that state onto an object and rewriting every read and write of it. That is
// a redesign, not a move, and it is not what #678 asked for.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS`. Must load AFTER the five reports_*.js
// modules and BEFORE dashboard.js.

(function () {
  "use strict";

  // ----------------------------------------------------------------------
  // Reports dashboard (read-only, STATE.json-sourced via /api/reports/*).
  //
  // Platform-agnostic: a KPI card is rendered for EVERY platform the API
  // returns — built-in google_ads/meta_ads AND plugin:<dist> bridges. A
  // platform with no synced metrics (totals null/empty) still gets a card
  // labelled "no synced metrics yet" instead of a broken/empty one.
  //
  // Period toggle (YESTERDAY default / LAST_30_DAYS): the summary carries a
  // `periods` union of the windows that have data; the toggle is rendered
  // ONLY for those, and only when there is a real choice (>= 2). Each call
  // requests `?period=`, and the cards show that window's totals.
  //
  // Freshness (#535) is PER PLATFORM, from each row's own `freshness` block
  // ({fetched_at, stale, stale_after_days}, resolved server-side against the
  // window the figure covers). The document-level `last_synced_at` is
  // re-stamped on ANY platform write, so it cannot stand in for it — it
  // still shows in the detail view, labelled as the document sync it is.
  //
  // Conflicts (#533): `platform_conflicts` says when these rows must NOT be
  // added together. The grouping is done server-side because the rows carry
  // no account id (and must not start carrying one), so the browser only
  // renders what it is told.
  // ----------------------------------------------------------------------

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

  // Build one flag chip element. A flag with drill-down detail becomes an
  // interactive <button> that toggles a detail line (an ARIA disclosure);
  // a flag without detail is a plain, non-interactive <span> tag.
  let reportFlagDetailSeq = 0;
  function buildFlagChipElement(flag) {
    const label = String(humanizeReportFlag(flag));
    const kind = reportFlagKind(flag);
    const detail = buildFlagDetail(flag);
    if (!detail) {
      const chip = document.createElement("span");
      chip.className = "report-chip " + kind;
      chip.textContent = label;
      return chip;
    }
    // Detail present → the chip stays coarse and the adspot / yen / ctr detail
    // is one click away (and also visible in the narrative below).
    const wrap = document.createElement("span");
    wrap.className = "report-chip-wrap";
    const detailId = "report-flag-detail-" + ++reportFlagDetailSeq;
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "report-chip is-interactive " + kind;
    chip.textContent = label;
    chip.setAttribute("aria-expanded", "false");
    chip.setAttribute("aria-controls", detailId);
    const det = document.createElement("span");
    det.className = "report-flag-detail";
    det.id = detailId;
    det.hidden = true;
    det.textContent = detail;
    chip.addEventListener("click", function () {
      const show = det.hidden;
      det.hidden = !show;
      chip.setAttribute("aria-expanded", show ? "true" : "false");
    });
    wrap.appendChild(chip);
    wrap.appendChild(det);
    return wrap;
  }

  // The selected window. Default = YESTERDAY (daily-check runs every day, so
  // the prior day is what an operator checks first). Reconciled against the
  // summary's `periods` union on each render — falls back to the first
  // available window when YESTERDAY has no data yet.
  let reportsPeriod = "YESTERDAY";

  // The client whose detail is on screen — so the period toggle re-fetches
  // the SAME client.
  let reportsActiveClient = null;

  // Reports navigation: "index" (the client overview grid) or "detail" (one
  // client's full report). A single-client (OSS) install has no index and
  // stays on "detail". The last-fetched client list is cached so a back /
  // period re-render does not need to re-resolve it.
  let reportsView = "index";
  // EVERY client the registry returned, archived ones included. The index
  // renders only the visible ones, but the routing decision counts them all
  // — see renderReports().
  let reportsClients = [];

  // Whether the backing client registry can record an archive decision
  // (`can_archive` off /api/reports/clients). False on an OSS-only install:
  // there is no registry there, so the control is not rendered AT ALL rather
  // than rendered and inert.
  let reportsCanArchive = false;

  // Monotonic render generation (mirrors renderPluginCredentials #223):
  // the section clears then awaits a fetch, so an interleaved re-render
  // (locale change, client switch, period switch) must not let a stale
  // result append.
  let reportsRenderSeq = 0;

  // What separates the restated stale figures from one another. One place,
  // because both the client card and the platform card render the line.
  const STALE_FIGURE_SEPARATOR = " · ";

  // The withheld figures restated as what they ARE — numbers collected at
  // `fetchedAt`, not the selected window's answer (#638). Nothing is hidden;
  // only the claim changes. An age mureo cannot quote is said to be unknown
  // rather than guessed at.
  function buildStaleFiguresElement(className, fetchedAt, figuresText) {
    const el = document.createElement("p");
    el.className = className;
    const age = fetchedAt ? relativeAge(fetchedAt) : null;
    el.textContent = MUREO.t(
      age
        ? "dashboard.reports_stale_last_collected"
        : "dashboard.reports_stale_last_collected_unknown",
      { ago: age, figures: figuresText }
    );
    return el;
  }

  // One platform's own rollup as a single labelled line, in the same order
  // and the same vocabulary its KPI grid would have used.
  function staleTotalsFiguresText(totals) {
    const parts = [];
    if (totals.spend != null) {
      parts.push(
        MUREO.t("dashboard.reports_kpi_spend") + " " + formatNumber(totals.spend)
      );
    }
    Object.keys(REPORTS_KPI_LABELS).forEach(function (key) {
      if (totals[key] == null) return;
      parts.push(MUREO.t(REPORTS_KPI_LABELS[key]) + " " + formatKpi(key, totals[key]));
    });
    return parts.join(STALE_FIGURE_SEPARATOR);
  }

  // The same line for a client card's aggregate (spend / conversions / CPA).
  function staleAggregateFiguresText(figures) {
    const parts = [];
    if (figures.spend != null) {
      parts.push(
        MUREO.t("dashboard.reports_kpi_spend") + " " + formatNumber(figures.spend)
      );
    }
    if (figures.conversions != null) {
      parts.push(
        MUREO.t("dashboard.reports_kpi_conversions") +
          " " +
          formatNumber(figures.conversions)
      );
    }
    if (figures.cpa != null) {
      parts.push(
        MUREO.t("dashboard.reports_kpi_cpa") +
          " " +
          formatNumber(Math.round(figures.cpa))
      );
    }
    return parts.join(STALE_FIGURE_SEPARATOR);
  }

  // Build one KPI card for a single platform entry. `summary` is optional and
  // supplies the conflict context (the platform row itself carries none).
  function buildReportCard(platform, summary) {
    const card = document.createElement("article");
    card.className = "report-card";
    // Defensive: a null/non-object element in the platforms array must not
    // throw and break the whole render (Array.isArray guards the list, not
    // its elements).
    if (!platform || typeof platform !== "object") return card;

    const head = document.createElement("header");
    head.className = "report-card-head";
    const name = document.createElement("h3");
    name.className = "report-card-name";
    name.textContent = platform.display_name || platform.key || "";
    head.appendChild(name);
    const period = platform.metrics_period;
    if (period) {
      const periodEl = document.createElement("span");
      periodEl.className = "report-card-period";
      periodEl.textContent = String(period);
      head.appendChild(periodEl);
    }
    card.appendChild(head);

    // Any conflict naming this key, before the numbers — the index card only
    // renders for multi-client installs, so on a single-client (OSS) setup
    // this platform card is the ONLY place the finding can surface.
    const conflicts = reportsConflictsForKey(summary, platform.key);
    if (conflicts.length) {
      card.classList.add("is-conflicted");
      const labels = reportsPlatformLabels(summary);
      conflicts.forEach(function (row) {
        const note = document.createElement("p");
        note.className = "report-card-conflict";
        note.textContent = reportsConflictText(row, labels);
        card.appendChild(note);
      });
      // Where the way out lives (#610/#636). The repair is NOT offered as a
      // button here. Since #631 this signal does agree with mureo's
      // write-time answer — the CORRECT key in the reported incident
      // (`logly_ads_context`) no longer fires it — but agreeing about the
      // key is not deciding the repair: removal needs the DOCUMENT to show
      // the entry wrong (a resolvable sibling on the same ad account, or an
      // entry storing nothing) and is refused for one carrying
      // `conversion_action_types` (#616/#617). None of that evidence is on
      // the wire. This is a pointer, not an action — but since #636 it
      // points at the command that actually ends THIS finding, which
      // `reportsRepairHint` chooses from the kinds on the card.
      const hint = document.createElement("p");
      hint.className = "report-card-conflict-hint";
      hint.textContent = reportsRepairHint(conflicts);
      card.appendChild(hint);
    }

    // Why this platform's figures did not move (#638), above the numbers it
    // explains — and above BOTH early returns below, because the platform
    // this is most true of is the one with no figures to show at all. On a
    // single-client (OSS) install the client index never renders, so this
    // card is the only place the note can surface.
    const notCollected = reportsNotCollectedNote(platform);
    if (notCollected) {
      const why = document.createElement("p");
      why.className = "report-card-not-collected";
      why.textContent = reportsNotCollectedText(notCollected);
      card.appendChild(why);
    }

    const totals =
      platform.totals && typeof platform.totals === "object"
        ? platform.totals
        : null;
    const hasMetrics = totals && Object.keys(totals).length > 0;

    if (!hasMetrics) {
      // Advisory bridge / not-yet-synced platform: a deliberate, complete
      // card (display name + status + campaign count), never empty.
      const empty = document.createElement("p");
      empty.className = "report-card-empty";
      empty.textContent = MUREO.t("dashboard.reports_no_metrics");
      card.appendChild(empty);
      card.appendChild(buildReportCardFoot(platform));
      return card;
    }

    // A rollup older than the window it summarises is not that window's
    // answer, so it is not rendered as one (#638). The card's head states
    // the selected period right above these numbers — putting a stale figure
    // there asserts something mureo cannot back, exactly as a double-counted
    // total does, and it gets the same treatment: withheld here, restated
    // below with its age. `stale` unknown (#637) keeps its old rendering.
    const rowStale = reportsRowIsStale(platform);

    // Headline number: spend, large, mono so digits align.
    const headline = document.createElement("div");
    headline.className = "report-card-headline";
    const headlineValue = document.createElement("span");
    headlineValue.className = "report-card-headline-value";
    // "—", never a 0: a figure mureo will not state is not a figure of zero.
    headlineValue.textContent = rowStale
      ? "—"
      : formatNumber(totals.spend != null ? totals.spend : 0);
    const headlineLabel = document.createElement("span");
    headlineLabel.className = "report-card-headline-label";
    headlineLabel.textContent = MUREO.t("dashboard.reports_kpi_spend");
    headline.appendChild(headlineValue);
    headline.appendChild(headlineLabel);
    card.appendChild(headline);

    if (rowStale) {
      const note = document.createElement("p");
      note.className = "report-card-stale";
      note.textContent = MUREO.t("dashboard.reports_stale_kpis_withheld");
      card.appendChild(note);
      card.appendChild(
        buildStaleFiguresElement(
          "report-card-stale-figures",
          platform.freshness.fetched_at,
          staleTotalsFiguresText(totals)
        )
      );
      card.appendChild(buildReportCardFoot(platform));
      return card;
    }

    // Secondary KPIs in a tidy 2-col grid — only those present in totals.
    const grid = document.createElement("dl");
    grid.className = "report-card-kpis";
    Object.keys(REPORTS_KPI_LABELS).forEach(function (key) {
      if (totals[key] == null) return;
      const term = document.createElement("dt");
      term.textContent = MUREO.t(REPORTS_KPI_LABELS[key]);
      const def = document.createElement("dd");
      def.textContent = formatKpi(key, totals[key]);
      grid.appendChild(term);
      grid.appendChild(def);
    });
    if (grid.childNodes.length > 0) card.appendChild(grid);

    card.appendChild(buildReportCardFoot(platform));
    return card;
  }

  // Card footer: campaign count + THIS platform's own freshness (#535).
  function buildReportCardFoot(platform) {
    const foot = document.createElement("footer");
    foot.className = "report-card-foot";
    const count = document.createElement("span");
    count.className = "report-card-count";
    const n = typeof platform.campaign_count === "number" ? platform.campaign_count : 0;
    count.textContent = MUREO.t("dashboard.reports_campaign_count", { n: n });
    foot.appendChild(count);
    // Per-platform, never the document-level last_synced_at: that is
    // re-stamped on any platform write, so it would report this platform's
    // months-old numbers as just-synced.
    const fresh = reportsFreshnessLabel(platform.freshness);
    const freshEl = document.createElement("span");
    freshEl.className = "report-card-fresh" + (fresh.stale ? " is-stale" : "");
    freshEl.textContent = fresh.text;
    foot.appendChild(freshEl);
    return foot;
  }

  // One statistic the report stated outside the canonical vocabulary (#670),
  // as a small "key value" chip.
  //
  // The value is NOT put through formatKpi / formatNumber. Those answer a
  // question about a metric mureo knows — its unit, whether it is a ratio,
  // whether a separator belongs in it — and this chip exists precisely for
  // the ones it does not know. "0.21%" is the author's own rendering of a
  // ratio and 30000 is a target in the account's currency; a heuristic
  // applied to either prints a number the report never wrote.
  function buildReportStatElement(entry) {
    const el = document.createElement("span");
    el.className = "report-stat";
    const key = document.createElement("span");
    key.className = "report-stat-key";
    key.textContent = reportStatLabel(entry.path);
    const value = document.createElement("span");
    value.className = "report-stat-value";
    value.textContent = String(entry.value);
    el.appendChild(key);
    el.appendChild(value);
    return el;
  }

  // The row those chips sit in, titled so it is never read as the headline
  // figures above it.
  function buildReportStatsRow(stats) {
    const row = document.createElement("div");
    row.className = "report-latest-stats";
    const title = document.createElement("span");
    title.className = "report-stats-title";
    title.textContent = MUREO.t("dashboard.reports_stats_title");
    row.appendChild(title);
    stats.entries.forEach(function (entry) {
      row.appendChild(buildReportStatElement(entry));
    });
    // Fields with no flat rendering (a deeper tree, a list) are stated as
    // existing rather than dropped — being silently discarded is the whole
    // of what #670 is about. The count is of FIELDS, which is what the
    // string says: a fifty-element list is one of them. The stored report
    // is where they are read.
    if (stats.hidden > 0) {
      const more = document.createElement("span");
      more.className = "report-stat-more";
      more.textContent = MUREO.t("dashboard.reports_stats_more", { n: stats.hidden });
      row.appendChild(more);
    }
    return row;
  }

  // Render the "latest report" block from STATE.json's `reports` section.
  // The object is free-form; render defensively (any field may be absent).
  function renderReportsLatest(reports) {
    const block = document.querySelector("[data-reports-latest]");
    const body = document.querySelector("[data-reports-latest-body]");
    if (!block || !body) return;
    body.textContent = "";
    // WHICH of the stored kinds is "the latest" is decided in
    // reports_format.js, where the JS suite can execute it (#671) — nine
    // skills write nine kinds, and this block used to know three.
    const report = latestReport(reports);
    if (!report) {
      block.hidden = true;
      return;
    }
    block.hidden = false;

    if (report.period) {
      const period = document.createElement("p");
      period.className = "report-latest-period";
      period.textContent = String(report.period);
      body.appendChild(period);
    }
    // The headline figures the report stated, AS FIGURES (#662). The schema
    // has always defined `totals` / `kpis` next to `flags` and `narrative`;
    // what it had no way to do was make anything render them, so a report
    // that put its numbers where they belong looked exactly like one that
    // folded them into the paragraph. Only the canonical vocabulary and only
    // real numbers reach this row — reports_format.js decides that — so a
    // report already on disk states nothing here and stays readable below,
    // as the prose it is.
    const totals = reportSummaryTotals(report);
    if (totals.length > 0) {
      const row = document.createElement("div");
      row.className = "report-latest-kpis";
      totals.forEach(function (cell) {
        row.appendChild(
          clientKpiCell(
            cell.key === "spend"
              ? "dashboard.reports_kpi_spend"
              : REPORTS_KPI_LABELS[cell.key],
            formatKpi(cell.key, cell.key === "cpa" ? Math.round(cell.value) : cell.value)
          )
        );
      });
      body.appendChild(row);
    }
    // What the report stated that is NOT one of the six canonical figures
    // (#670). The writer accepts those keys deliberately (#662): a goal
    // review carries a CVR, a per-goal target, a per-platform split, and
    // refusing them sends that content straight back into the paragraph the
    // length bound exists to empty. Nothing rendered them, so they were
    // written successfully and then invisible for good.
    //
    // Below the headline row and shaped nothing like it: the row above
    // states mureo's own metrics for the window, these are the report's own
    // words for something mureo has no label for, printed as written.
    const stats = reportSecondaryStats(report);
    if (stats.entries.length > 0 || stats.hidden > 0) {
      body.appendChild(buildReportStatsRow(stats));
    }
    // Flags as small tinted chips (warn/danger/success).
    const flags = Array.isArray(report.flags) ? report.flags : [];
    if (flags.length > 0) {
      const chips = document.createElement("div");
      chips.className = "report-flags";
      flags.forEach(function (flag) {
        chips.appendChild(buildFlagChipElement(flag));
      });
      body.appendChild(chips);
    }
    if (report.narrative) {
      const narrative = document.createElement("p");
      narrative.className = "report-latest-narrative";
      narrative.textContent = String(report.narrative);
      body.appendChild(narrative);
    }
    if (report.generated_at) {
      const gen = document.createElement("p");
      gen.className = "report-latest-generated";
      gen.textContent = MUREO.t("dashboard.reports_generated", {
        ago: relativeAge(report.generated_at),
      });
      body.appendChild(gen);
    }
  }

  // Render the recent-actions list from the action log.
  function renderReportsActions(actions) {
    const block = document.querySelector("[data-reports-actions]");
    const list = document.querySelector("[data-reports-actions-list]");
    if (!block || !list) return;
    list.textContent = "";
    const rows = Array.isArray(actions) ? actions : [];
    if (rows.length === 0) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    rows.forEach(function (a) {
      const li = document.createElement("li");
      li.className = "report-action";
      const top = document.createElement("div");
      top.className = "report-action-top";
      const action = document.createElement("span");
      action.className = "report-action-name";
      action.textContent = a.action || "";
      const platform = document.createElement("span");
      platform.className = "report-action-platform";
      platform.textContent = a.platform || "";
      top.appendChild(action);
      top.appendChild(platform);
      li.appendChild(top);
      if (a.summary) {
        const summary = document.createElement("p");
        summary.className = "report-action-summary";
        summary.textContent = String(a.summary);
        li.appendChild(summary);
      }
      const meta = document.createElement("div");
      meta.className = "report-action-meta";
      if (a.timestamp) {
        const ts = document.createElement("span");
        ts.textContent = relativeAge(a.timestamp);
        meta.appendChild(ts);
      }
      if (a.observation_due) {
        const due = document.createElement("span");
        due.textContent = MUREO.t("dashboard.reports_observation_due", {
          date: String(a.observation_due),
        });
        meta.appendChild(due);
      }
      if (meta.childNodes.length > 0) li.appendChild(meta);
      list.appendChild(li);
    });
  }

  // ----------------------------------------------------------------------
  // Multi-client overview (#307): a card grid (one per client) replaces the
  // old single-select dropdown. Each card shows that client's headline KPIs
  // + latest report flags; clicking it loads the existing per-client detail.
  // ----------------------------------------------------------------------

  const REPORTS_CLIENT_FLAG_CAP = 3; // chips per card before collapsing to +N

  // Fetch JSON defensively — null on any failure / non-object body.
  async function fetchReportsJson(url) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return null;
      const body = await res.json();
      return body && typeof body === "object" ? body : null;
    } catch (_err) {
      return null;
    }
  }

  // Fetch a client's summary for its overview card. Honours the period toggle,
  // and when the selected window has no totals (a period-bucketed client whose
  // passthrough rollup is blank) falls back to the first window with data.
  async function fetchClientCardSummary(slug) {
    function summaryUrl(period) {
      const params = [];
      if (slug) params.push("client=" + encodeURIComponent(slug));
      if (period) params.push("period=" + encodeURIComponent(period));
      return (
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "")
      );
    }
    let summary = (await fetchReportsJson(summaryUrl(reportsPeriod))) || {};
    const kpis = aggregateClientKpis(summary);
    const periods = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    // `hasFigures`, not the rendered values: a conflicted client HAS data,
    // it is just withheld, and re-fetching another window would not fix that
    // (the conflict is a property of the document, not of the window).
    if (!kpis.hasFigures && periods.length) {
      const fallback = periods.indexOf(reportsPeriod) === -1 ? periods[0] : null;
      if (fallback) {
        const alt = await fetchReportsJson(summaryUrl(fallback));
        if (alt) summary = alt;
      }
    }
    return summary;
  }

  function clientKpiCell(labelKey, value) {
    const cell = document.createElement("div");
    cell.className = "reports-client-kpi";
    const v = document.createElement("span");
    v.className = "reports-client-kpi-value";
    v.textContent = value;
    const l = document.createElement("span");
    l.className = "reports-client-kpi-label";
    l.textContent = MUREO.t(labelKey);
    cell.appendChild(v);
    cell.appendChild(l);
    return cell;
  }

  // The card being dragged, held as the NODE (never as a slug fed back into
  // a selector — a client slug is registry-controlled text).
  let reportsDragNode = null;

  function wireReportsCardDrag(item, wrap) {
    item.draggable = true;
    item.addEventListener("dragstart", function (ev) {
      reportsDragNode = item;
      item.classList.add("is-dragging");
      if (ev.dataTransfer) {
        ev.dataTransfer.effectAllowed = "move";
        // Some browsers cancel a drag that carries no payload.
        try {
          const slug = item.getAttribute("data-client") || "";
          ev.dataTransfer.setData("text/plain", slug);
        } catch (_e) {
          /* payload optional */
        }
      }
    });
    item.addEventListener("dragend", function () {
      reportsDragNode = null;
      item.classList.remove("is-dragging");
    });
    item.addEventListener("dragover", function (ev) {
      if (!reportsDragNode || reportsDragNode === item) return;
      ev.preventDefault();
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
    });
    item.addEventListener("drop", function (ev) {
      if (!reportsDragNode || reportsDragNode === item) return;
      ev.preventDefault();
      const items = Array.prototype.slice.call(wrap.children);
      const from = items.indexOf(reportsDragNode);
      const to = items.indexOf(item);
      if (from === -1 || to === -1) return;
      if (from < to) wrap.insertBefore(reportsDragNode, item.nextSibling);
      else wrap.insertBefore(reportsDragNode, item);
      persistReportsOrderFromDom(wrap);
    });
  }

  // The drag handle. It is a real button so it is reachable by keyboard, and
  // the arrow keys move the card — a reorder control that only a mouse can
  // work excludes operators who do not use one. Both paths end in
  // moveReportsCard, so mouse and keyboard can never drift apart.
  function buildReportsDragHandle(item, name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reports-client-drag";
    btn.setAttribute("data-reports-drag-handle", "");
    btn.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_reorder_handle", { name: name })
    );
    btn.title = MUREO.t("dashboard.reports_reorder_hint");
    btn.textContent = "⠿";
    btn.addEventListener("keydown", function (ev) {
      let delta = 0;
      if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") delta = -1;
      else if (ev.key === "ArrowDown" || ev.key === "ArrowRight") delta = 1;
      if (!delta) return;
      ev.preventDefault();
      moveReportsCard(item, delta);
      btn.focus();
    });
    return btn;
  }

  // --------------------------------------------------------------------
  // Archiving (server-side — see mureo/web/reports.py)
  // --------------------------------------------------------------------
  function isArchivedClient(c) {
    return !!(c && c.archived);
  }

  function visibleReportsClients() {
    return reportsClients.filter(function (c) {
      return !isArchivedClient(c);
    });
  }

  function archivedReportsClients() {
    return reportsClients.filter(isArchivedClient);
  }

  // Relay the decision to the client registry. Archiving is NOT a view
  // preference: while it is set, that client's figures are never collected,
  // so a browser-local flag could not reach the process that does the
  // collecting. On success the whole view is re-rendered from the server's
  // answer rather than from an optimistic local edit.
  async function setReportsClientArchived(slug, archived) {
    let res = null;
    try {
      res = await MUREO.postJson("/api/reports/clients/archive", {
        slug: slug,
        archived: archived,
      });
    } catch (_err) {
      res = null;
    }
    if (!res || !res.ok || !res.body || res.body.status === "error") {
      MUREO.toast(MUREO.t("dashboard.reports_archive_failed"), "error");
      return;
    }
    reportsView = "index";
    renderReports();
  }

  function buildReportsArchiveButton(slug, name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reports-client-archive";
    btn.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_archive_label", { name: name })
    );
    btn.textContent = MUREO.t("dashboard.reports_archive_action");
    btn.addEventListener("click", async function () {
      // The confirmation states the real consequence — figures stop being
      // collected and the gap is never backfilled — not "hide from view".
      const ok = await MUREO.confirmAction(
        MUREO.t("dashboard.reports_archive_confirm", { name: name })
      );
      if (!ok) return;
      await setReportsClientArchived(slug, true);
    });
    return btn;
  }

  // One grid cell: the card button plus its controls. The controls live
  // OUTSIDE the card because the card IS a button, and a button may not nest
  // interactive children.
  function buildClientCardItem(client, summary, wrap, triaged, health, badges) {
    const slug = client && client.slug ? client.slug : "";
    const name = (client && (client.name || client.slug)) || "";
    const item = document.createElement("div");
    item.className =
      "reports-client-card-item" + (triaged ? " is-triaged" : "");
    item.setAttribute("role", "listitem");
    item.setAttribute("data-client", slug);
    // The health the filter chips above the grid select on. It comes from
    // the triage layer's own findings, so a card the alerts call urgent can
    // never be filtered away as a healthy one.
    item.setAttribute("data-health", health || "ok");
    // The other half of the triage layer above the grid (#651): if the layer
    // says three clients need attention, exactly three cards are marked.
    // Both read the same list, so they cannot drift. A class alone would be
    // colour-only, and the grid is a list of buttons an operator may reach
    // by keyboard, so the mark carries text too.
    if (triaged) {
      const mark = document.createElement("span");
      mark.className = "reports-client-card-mark";
      mark.textContent = MUREO.t("dashboard.reports_triage_card_marker");
      item.appendChild(mark);
    }
    item.appendChild(buildClientCard(client, summary, health, badges));

    const tools = document.createElement("div");
    tools.className = "reports-client-tools";
    tools.appendChild(buildReportsDragHandle(item, name));
    // No registry, no archive control: an OSS-only single-workspace install
    // has nowhere to record the decision, and must be completely unaffected.
    if (reportsCanArchive && slug) {
      tools.appendChild(buildReportsArchiveButton(slug, name));
    }
    item.appendChild(tools);

    wireReportsCardDrag(item, wrap);
    return item;
  }

  // One card: who the client is, what state mureo is in about them, and the
  // window's headline figures. A SUMMARY — deliberately not an explanation.
  //
  // It used to carry the full sentences too: which platform key could not be
  // resolved, why a collection failed, and the repair command to run. On a
  // twenty-seven-client grid that put three red paragraphs inside a 230px
  // card, and every one of them was already on screen in the alert list
  // directly above it. Two renderings of one finding is not twice the
  // signal; it is a wall with the summary buried in it.
  //
  // What did NOT move is the state. A card whose figures mureo will not
  // state still says so — the "—" and a short badge next to it ("Figures 29
  // days old"), because a bare dash reads as zero and #638 is the incident
  // where exactly that happened. The explanation and the way out live in the
  // alert row above (grouped, one per kind) and on the client's own detail
  // view, which is where the per-platform conflict note and its repair hint
  // have always been rendered.
  function buildClientCard(client, summary, health, badges) {
    const slug = client && client.slug ? client.slug : "";
    const card = document.createElement("button");
    card.type = "button";
    // The health is a class AND the status tag below, never colour alone:
    // the grid is a list of buttons an operator may reach by keyboard.
    card.className = "reports-client-card is-health-" + (health || "ok");
    card.setAttribute("data-client", slug);

    const head = document.createElement("div");
    head.className = "reports-client-card-head";
    const name = document.createElement("span");
    name.className = "reports-client-card-name";
    name.textContent = (client && (client.name || client.slug)) || "";
    head.appendChild(name);
    const status = document.createElement("span");
    status.className = "reports-client-card-status is-" + (health || "ok");
    status.textContent = MUREO.t("dashboard.reports_health_" + (health || "ok"));
    head.appendChild(status);
    // Per-platform freshness, NOT the document-level last_synced_at (#535):
    // that is re-stamped on any platform write, so a card whose numbers are
    // months old read as just-synced whenever a sibling platform synced.
    const cardFresh = reportsCardFreshness(summary);
    const fresh = document.createElement("span");
    fresh.className =
      "reports-client-card-fresh" + (cardFresh.stale ? " is-stale" : "");
    fresh.textContent = cardFresh.text;
    card.appendChild(head);
    // Freshness on its own line, under the name: in the head it competed
    // with the name and the status pill for a 230px row, and the casualty
    // was the name — a five-character Japanese client name was being broken
    // across two lines.
    card.appendChild(fresh);

    const badgeRow = document.createElement("div");
    badgeRow.className = "reports-client-card-badges";

    // A conflicted card still carries its modifier class, so it can never be
    // skimmed as an ordinary one — but the sentence explaining the conflict
    // is the alert row's job now, and the repair command is the detail
    // view's. Both are one click from here and neither is duplicated.
    const conflicts =
      summary && Array.isArray(summary.platform_conflicts)
        ? summary.platform_conflicts
        : [];
    if (conflicts.length) card.classList.add("is-conflicted");

    // The state, as badges: one per kind, short, no command and no prose.
    // These are what keeps the "—" below from reading as zero.
    (Array.isArray(badges) ? badges : []).forEach(function (badge) {
      const el = document.createElement("span");
      el.className = "reports-client-card-badge is-" + badge.severity;
      el.textContent = badge.text;
      badgeRow.appendChild(el);
    });
    if (badgeRow.childNodes.length) card.appendChild(badgeRow);

    const kpis = aggregateClientKpis(summary);
    const krow = document.createElement("div");
    krow.className = "reports-client-card-kpis";
    krow.appendChild(
      clientKpiCell(
        "dashboard.reports_kpi_spend",
        // "—" (not 0) when absent — a no-data client must not read as zero
        // spend in this at-a-glance triage view.
        kpis.spend != null ? formatNumber(kpis.spend) : "—"
      )
    );
    if (kpis.conversions != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_conversions",
          formatNumber(kpis.conversions)
        )
      );
    }
    if (kpis.cpa != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_cpa",
          formatNumber(Math.round(kpis.cpa))
        )
      );
    }
    card.appendChild(krow);
    // …and the withheld figures restated below the cells, so the operator
    // keeps every number they had before, correctly labelled.
    if (kpis.staleFigures) {
      card.appendChild(
        buildStaleFiguresElement(
          "reports-client-card-stale-figures",
          kpis.staleFigures.fetched_at,
          staleAggregateFiguresText(kpis.staleFigures)
        )
      );
    }

    // Where this client's spend went, as one bar. It is drawn only from the
    // rows mureo is willing to state (reports_overview.js returns nothing
    // for a withheld or stale client): the bar is the same claim as the
    // number above it, and drawing shares of figures the card refuses to
    // print would restate them in a shape that looks like a picture.
    const split = clientPlatformSplit(summary);
    if (split.length) {
      const bar = document.createElement("div");
      bar.className = "reports-client-split";
      split.forEach(function (row) {
        bar.appendChild(buildPlatformSlice(row, "reports-client-split-slice"));
      });
      card.appendChild(bar);
      const legend = document.createElement("div");
      legend.className = "reports-client-split-legend";
      split.forEach(function (row) {
        const entry = document.createElement("span");
        entry.className = "reports-client-split-entry";
        const dot = document.createElement("i");
        dot.className = "reports-client-split-dot is-platform-" + platformColorSlot(row.key);
        entry.appendChild(dot);
        const label = document.createElement("span");
        // Registry / plugin-controlled display name — text, never markup.
        label.textContent = row.label;
        entry.appendChild(label);
        legend.appendChild(entry);
      });
      card.appendChild(legend);
    }

    const flags = clientReportFlags(summary)
      .slice()
      .sort(function (a, b) {
        return flagSeverityRank(a) - flagSeverityRank(b);
      });
    if (flags.length) {
      const chips = document.createElement("div");
      chips.className = "reports-client-card-flags";
      flags.slice(0, REPORTS_CLIENT_FLAG_CAP).forEach(function (flag) {
        const chip = document.createElement("span");
        chip.className = "report-chip " + reportFlagKind(flag);
        chip.textContent = humanizeReportFlag(flag);
        chips.appendChild(chip);
      });
      const overflow = flags.length - REPORTS_CLIENT_FLAG_CAP;
      if (overflow > 0) {
        const more = document.createElement("span");
        more.className = "report-chip reports-client-flag-more";
        more.textContent = "+" + overflow;
        chips.appendChild(more);
      }
      card.appendChild(chips);
    }

    card.addEventListener("click", function () {
      reportsActiveClient = slug;
      showReportsClientDetail(slug);
    });
    return card;
  }

  // Default slug for a client list: the first active client, else the first.
  function defaultClientSlug(rows) {
    if (!rows.length) return null;
    const active = rows.find(function (c) {
      return c && c.active;
    });
    return ((active || rows[0]) || {}).slug || null;
  }

  // Toggle the index (client grid) vs detail (one client) views, and the
  // detail's back bar (only meaningful when there is an index to return to).
  function setReportsView(view) {
    reportsView = view;
    const index = document.querySelector("[data-reports-clients]");
    const detail = document.querySelector("[data-reports-detail]");
    const back = document.querySelector("[data-reports-back]");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (index) index.hidden = view !== "index";
    if (detail) detail.hidden = view !== "detail";
    // The two-column index shell (client portfolio + spend by platform).
    const shell = document.querySelector("[data-reports-index-grid]");
    if (shell) shell.hidden = view !== "index";
    // The archived list belongs to the index; renderReportsIndex un-hides it
    // again when there is something to list.
    const archived = document.querySelector("[data-reports-archived]");
    if (archived && view !== "index") archived.hidden = true;
    // So does the triage layer, and for a stronger reason: it states
    // findings ABOUT the grid, so left behind over a detail view it would be
    // describing clients that are no longer on screen. The portfolio strip
    // is the same claim in numbers — a roster total sitting above one
    // client's report reads as that client's.
    const triageBox = document.querySelector("[data-reports-triage]");
    if (triageBox && view !== "index") triageBox.hidden = true;
    const kpiStrip = document.querySelector("[data-reports-kpis]");
    if (kpiStrip && view !== "index") kpiStrip.hidden = true;
    // …and the rail's "what mureo did today", which is the roster's day and
    // not the day of whichever client a detail view is showing.
    const feed = document.querySelector("[data-reports-feed]");
    if (feed && view !== "index") feed.hidden = true;
    // The back link (under the "Reports" heading) and the client-name heading
    // appear only in a multi-client detail view — an OSS single client has no
    // index to go back to and no sibling to disambiguate.
    const showClientChrome = view === "detail" && reportsClients.length > 1;
    if (back) back.hidden = !showClientChrome;
    if (nameEl) nameEl.hidden = !showClientChrome;
  }

  // ------------------------------------------------------------------
  // Triage layer (#651) — the index view's "what do I touch today?"
  // ------------------------------------------------------------------

  // Render the ranked findings above the client grid.
  //
  // Silence when there is nothing: no "0 alerts" banner competing for
  // attention with the cards it sits above. The list is emptied BEFORE the
  // early return so a row from a previous render cannot survive one that
  // found nothing.
  //
  // Nothing here ranks, sorts or trims: the order and the membership are
  // decided in reports_triage.js, where a test runner can execute them.
  // Defensive about its argument for the usual reason — this runs
  // mid-render, and a throw blanks the whole Reports view.
  function renderReportsTriage(built) {
    const box = document.querySelector("[data-reports-triage]");
    const list = document.querySelector("[data-reports-triage-list]");
    const heading = document.querySelector("[data-reports-triage-title]");
    if (!box || !list) return;
    const items = built && Array.isArray(built.items) ? built.items : [];
    // The count is of CLIENTS, and it is the same array the grid marks from
    // — one client raising four findings is still one card.
    const marked = built && Array.isArray(built.clients) ? built.clients : [];
    list.textContent = "";
    box.hidden = !items.length;
    if (!items.length) return;
    if (heading) {
      heading.textContent = MUREO.t("dashboard.reports_triage_title", {
        n: marked.length,
      });
    }
    // The same count again, as the panel's badge. It reads the same array as
    // the heading and the grid's marks, so there is still exactly one list.
    const badge = document.querySelector("[data-reports-triage-count]");
    if (badge) {
      badge.textContent = MUREO.t("dashboard.reports_triage_count", {
        n: marked.length,
      });
    }
    // One row per KIND, each naming the clients it covers — the grouping
    // and the dismissal filter are both the module's (reports_triage.js).
    // Neither changes `built.clients`, so the heading above and the marks
    // below still count every client that raised anything.
    reportsTriageBuilt = built;
    const split = partitionTriageGroups(groupReportsTriage(built));
    // …and only the top few of those, unless the operator asked for the
    // rest. Which rows survive the collapse is the module's decision, for
    // the same reason the ranking is: "the top four" is only defensible
    // while it means the four mureo can do most about.
    const shown = collapseTriageGroups(split.visible, reportsTriageShowAll);
    shown.rows.forEach(function (group) {
      list.appendChild(buildTriageRow(group));
    });
    renderTriageMore(shown);
    renderTriageDismissed(split.hiddenCount);
  }

  // Which rows are expanded, by kind. Dismissing one message re-renders the
  // list, and a row that snapped shut after every ✕ would make closing six
  // findings six trips through the disclosure. Reset with the list itself on
  // every index render.
  let reportsTriageOpenKinds = {};

  // Whether the alert list is showing every row it has. Reset on every index
  // render — the list opens short each time the operator arrives, which is
  // the whole point of opening short.
  let reportsTriageShowAll = false;

  // "Show all (N)". Absent when the list already fits: there is no
  // "show all (0)", the same way there is no "0 alerts" banner.
  function renderTriageMore(shown) {
    const more = document.querySelector("[data-reports-triage-more]");
    if (!more) return;
    more.hidden = !shown.collapsed;
    if (!shown.collapsed) return;
    more.textContent = MUREO.t("dashboard.reports_triage_show_all", {
      n: shown.remaining,
    });
    more.onclick = function () {
      reportsTriageShowAll = true;
      renderReportsTriage(reportsTriageBuilt);
    };
  }

  // The layer as it was last built, so closing or restoring a row can redraw
  // it without re-fetching every client's summary.
  let reportsTriageBuilt = null;

  // "N alerts hidden", with the way back.
  //
  // This is the price of the ✗ and it is not optional. Closing a row hides
  // it; it does not resolve anything, and a finding that left NO trace when
  // it was closed would be the failure mode this entire layer was built
  // against (#636, #638: the condition was true, and nothing said so). So
  // the count is always on screen while anything is hidden, it says in words
  // that hiding resolved nothing, and one button brings them all back.
  function renderTriageDismissed(hiddenCount) {
    const box = document.querySelector("[data-reports-triage-hidden]");
    if (!box) return;
    box.textContent = "";
    box.hidden = !hiddenCount;
    if (!hiddenCount) return;
    const title = document.createElement("span");
    title.className = "reports-triage-hidden-title";
    // MESSAGES, not rows. Counting rows would report "1" for six findings
    // nobody can see, which is the silence this line exists to prevent.
    title.textContent = MUREO.t("dashboard.reports_triage_hidden_title", {
      n: hiddenCount,
    });
    box.appendChild(title);
    const note = document.createElement("span");
    note.className = "reports-triage-hidden-note";
    note.textContent = MUREO.t("dashboard.reports_triage_hidden_note");
    box.appendChild(note);
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "reports-triage-restore";
    restore.textContent = MUREO.t("dashboard.reports_triage_restore");
    restore.addEventListener("click", function () {
      restoreTriageDismissals();
      renderReportsTriage(reportsTriageBuilt);
    });
    box.appendChild(restore);
  }

  // One row: one KIND of finding, the clients it covers, and — one click
  // away — what each of them says and what to run about it.
  //
  // Per kind, not per client. On the twenty-seven-client install this layer
  // was built for it rendered sixteen rows, six of them the same sentence
  // about the same unresolvable platform key under six different names. The
  // grouping is reports_triage.js's; nothing here re-orders or re-groups.
  //
  // The detail is one click away rather than always open, like the flag
  // chips' disclosure above: a list where every row states its remedy inline
  // is a wall again, and the whole point of the layer is that it can be
  // skimmed. It is never absent — an item with no next step is a bug in the
  // item, which is why the module refuses to produce one.
  //
  // The severity dot and the tag come from the module's own kind table, so
  // the colour of a row and the colour of that client's card cannot
  // disagree.
  let triageRowSeq = 0;
  function buildTriageRow(group) {
    const item = group.items[0];
    const row = document.createElement("li");
    row.className = "reports-triage-row";
    row.setAttribute("data-triage-kind", group.kind);
    row.setAttribute("data-severity", group.severity);

    const detailId = "reports-triage-detail-" + ++triageRowSeq;
    const head = document.createElement("div");
    head.className = "reports-triage-row-head";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "reports-triage-toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", detailId);

    const sig = document.createElement("span");
    sig.className = "reports-triage-sig is-" + group.severity;
    toggle.appendChild(sig);

    const tag = triageItemTag(item);
    if (tag) {
      const chip = document.createElement("span");
      chip.className = "reports-triage-tag is-" + group.severity;
      chip.textContent = tag;
      toggle.appendChild(chip);
    }

    // Who it covers, named. Registry-controlled text — textContent, never
    // markup (#533).
    const who = document.createElement("span");
    who.className = "reports-triage-client";
    who.textContent = group.clients
      .map(function (c) {
        return c.name || c.slug;
      })
      .join(MUREO.t("dashboard.reports_triage_client_separator"));
    toggle.appendChild(who);

    if (group.clients.length > 1) {
      const count = document.createElement("span");
      count.className = "reports-count-badge";
      count.textContent = MUREO.t("dashboard.reports_triage_count", {
        n: group.clients.length,
      });
      toggle.appendChild(count);
    }

    // What it says, on ONE line, clipped by the stylesheet. A row is a thing
    // to skim; the sentence wrapping to three lines was most of the height
    // an operator complained about. The full text of every item on the row
    // is in the disclosure below, and the `title` puts this one a hover
    // away — the clip never has to be the only copy.
    const summary = document.createElement("span");
    summary.className = "reports-triage-summary";
    // Writer-supplied text (a collection-failure reason out of STATE.json, a
    // registry-controlled platform key) — text, never markup.
    summary.textContent = triageItemText(item);
    summary.title = summary.textContent;
    toggle.appendChild(summary);
    head.appendChild(toggle);

    // Closing a row is every message on it — the message-level control
    // below applied to each, which is the only reading that keeps the two
    // consistent. It is a VIEW operation and says so: the count above does
    // not move, the clients' cards stay marked, and "N hidden" appears
    // under the list with the way back. See renderTriageDismissed.
    const close = document.createElement("button");
    close.type = "button";
    close.className = "reports-triage-dismiss";
    close.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_triage_dismiss_group", {
        what: tag,
        n: group.items.length,
      })
    );
    close.textContent = "✕";
    close.addEventListener("click", function () {
      dismissTriageGroup(group);
      renderReportsTriage(reportsTriageBuilt);
    });
    head.appendChild(close);
    row.appendChild(head);

    const detail = document.createElement("div");
    detail.className = "reports-triage-detail";
    detail.id = detailId;
    const open = !!reportsTriageOpenKinds[group.kind];
    detail.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    const list = document.createElement("ul");
    list.className = "reports-triage-detail-list";
    group.items.forEach(function (item) {
      const line = document.createElement("li");
      line.className = "reports-triage-detail-row";
      const name = document.createElement("span");
      name.className = "reports-triage-client";
      name.textContent = item.name || item.slug;
      line.appendChild(name);
      const what = document.createElement("span");
      what.className = "reports-triage-what";
      // Writer-supplied text (a collection-failure reason out of STATE.json,
      // a registry-controlled platform key) is interpolated into this
      // sentence, so it is set as text and never as markup.
      what.textContent = triageItemText(item);
      line.appendChild(what);
      // …and its own ✕. A row can cover six clients, and closing the KIND
      // would take five findings the operator never read with it. The row's
      // count and the clients it names shrink as these go; the row goes
      // when the last of them does.
      const drop = document.createElement("button");
      drop.type = "button";
      drop.className = "reports-triage-dismiss";
      drop.setAttribute(
        "aria-label",
        MUREO.t("dashboard.reports_triage_dismiss", {
          client: item.name || item.slug,
          what: tag,
        })
      );
      drop.textContent = "✕";
      drop.addEventListener("click", function () {
        dismissTriageItem(item);
        renderReportsTriage(reportsTriageBuilt);
      });
      line.appendChild(drop);
      list.appendChild(line);
    });
    detail.appendChild(list);

    // What to run. One per row because every item on it is the same kind,
    // and the kind is what decides the next step.
    const next = triageItemNextStep(item);
    if (next) {
      const step = document.createElement("p");
      step.className = "reports-triage-next";
      step.textContent = next;
      detail.appendChild(step);
    }
    row.appendChild(detail);
    toggle.addEventListener("click", function () {
      const show = detail.hidden;
      detail.hidden = !show;
      reportsTriageOpenKinds[group.kind] = show;
      toggle.setAttribute("aria-expanded", show ? "true" : "false");
    });
    return row;
  }

  // ------------------------------------------------------------------
  // The portfolio strip, the health filter and the platform split
  // ------------------------------------------------------------------

  // One cell of the strip: a label, a figure, and the coverage under it.
  //
  // A figure the module could state over NO client renders as "—" with the
  // reason spelled out, never as a bare dash and never as 0. That is the
  // rule the whole Reports view is built on (#638), and a roster total is
  // the easiest place to break it: every client whose totals are withheld
  // would otherwise be summed in as nothing.
  function buildPortfolioCell(labelKey, text, note, full) {
    const cell = document.createElement("div");
    cell.className = "reports-kpi";
    const label = document.createElement("span");
    label.className = "reports-kpi-label";
    label.textContent = MUREO.t(labelKey);
    cell.appendChild(label);
    const value = document.createElement("span");
    value.className = "reports-kpi-value";
    value.textContent = text;
    cell.appendChild(value);
    // The note is ONE clipped line: four cells each carrying a wrapped
    // sentence is a strip taller than the alerts under it. The whole
    // sentence stays reachable on the cell as a title — it is the half of
    // the figure that says whose numbers are in it, so it is shortened,
    // never dropped.
    const foot = document.createElement("span");
    foot.className = "reports-kpi-note";
    foot.textContent = note;
    if (full) cell.title = full;
    cell.appendChild(foot);
    return cell;
  }

  // A money cell: the figure when at least one client stated it, and how
  // many clients that was whenever it was not all of them.
  function buildPortfolioFigureCell(labelKey, figure, total, format) {
    const stated = figure && typeof figure.stated === "number" ? figure.stated : 0;
    const value = figure ? figure.value : null;
    const params = { stated: stated, total: total };
    const short =
      value == null
        ? "dashboard.reports_portfolio_unstated_short"
        : stated < total
          ? "dashboard.reports_portfolio_coverage_short"
          : "";
    const full =
      value == null
        ? "dashboard.reports_portfolio_unstated"
        : stated < total
          ? "dashboard.reports_portfolio_coverage"
          : "";
    return buildPortfolioCell(
      labelKey,
      value != null ? format(value) : "—",
      short ? MUREO.t(short, params) : "",
      full ? MUREO.t(full, params) : ""
    );
  }

  // The strip above the alerts: what the roster spent and converted, what it
  // paid per conversion, and how many of its clients need attention.
  //
  // Rendered only for the index — a roster total sitting above one client's
  // report reads as that client's — and only when there is a roster: an
  // empty grid gets no strip rather than four dashes.
  function renderReportsPortfolio(portfolio, triage) {
    const strip = document.querySelector("[data-reports-kpis]");
    if (!strip) return;
    strip.textContent = "";
    strip.hidden = !portfolio.total;
    if (!portfolio.total) return;
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_spend",
        portfolio.spend,
        portfolio.total,
        formatNumber
      )
    );
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_conversions",
        portfolio.conversions,
        portfolio.total,
        formatNumber
      )
    );
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_cpa",
        portfolio.cpa,
        portfolio.total,
        function (value) {
          return formatNumber(Math.round(value));
        }
      )
    );
    // The one cell that is never withheld: it counts findings mureo raised
    // itself, not figures it collected. It reads the same array as the alert
    // list's heading and the grid's marks.
    const marked = triage && Array.isArray(triage.clients) ? triage.clients : [];
    const counts = triageHealthCounts(triage, portfolio.total);
    strip.appendChild(
      buildPortfolioCell(
        "dashboard.reports_portfolio_attention",
        formatNumber(marked.length),
        MUREO.t("dashboard.reports_portfolio_health_note", {
          attention: counts.attention,
          watch: counts.watch,
        })
      )
    );
  }

  // Which health the grid is filtered to. "all" until the operator says
  // otherwise, and reset on every index render: a filter that survived a
  // re-render would leave cards missing with no visible reason.
  let reportsHealthFilter = "all";

  // Show only the cards at the selected health. The cards are hidden, never
  // removed: the grid is also the operator's own card order (#556), and
  // rebuilding it from a filtered list would reorder it.
  function applyReportsHealthFilter() {
    const wrap = document.querySelector("[data-reports-clients]");
    if (!wrap) return;
    Array.prototype.forEach.call(wrap.children, function (item) {
      const health = item.getAttribute("data-health");
      if (!health) return;
      item.hidden = reportsHealthFilter !== "all" && health !== reportsHealthFilter;
    });
    const chips = document.querySelectorAll("[data-reports-filter]");
    Array.prototype.forEach.call(chips, function (chip) {
      const active = chip.getAttribute("data-reports-filter") === reportsHealthFilter;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  // The health chips over the grid. Each carries its own count, so the
  // operator can see there are three clients needing attention without
  // clicking, and a chip whose count is zero is still rendered — a filter
  // that appears and disappears is harder to use than one that says "0".
  const REPORTS_HEALTH_FILTERS = [
    ["all", "dashboard.reports_filter_all"],
    ["attention", "dashboard.reports_health_attention"],
    ["watch", "dashboard.reports_health_watch"],
    ["ok", "dashboard.reports_health_ok"],
  ];

  function renderReportsFilters(counts) {
    const wrap = document.querySelector("[data-reports-filters]");
    if (!wrap) return;
    wrap.textContent = "";
    // Nothing to filter with one card, and nothing to filter with none.
    wrap.hidden = counts.all < 2;
    if (wrap.hidden) return;
    REPORTS_HEALTH_FILTERS.forEach(function (row) {
      const key = row[0];
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "reports-filter-chip";
      chip.setAttribute("data-reports-filter", key);
      if (key !== "all") {
        const dot = document.createElement("span");
        dot.className = "reports-filter-dot is-" + key;
        chip.appendChild(dot);
      }
      const label = document.createElement("span");
      label.textContent = MUREO.t(row[1]);
      chip.appendChild(label);
      const count = document.createElement("span");
      count.className = "reports-filter-count";
      count.textContent = formatNumber(counts[key]);
      chip.appendChild(count);
      chip.addEventListener("click", function () {
        reportsHealthFilter = key;
        applyReportsHealthFilter();
      });
      wrap.appendChild(chip);
    });
    applyReportsHealthFilter();
  }

  // One bar of a platform split: the coloured slice, sized by its share.
  //
  // The colour is chosen from the platform KEY (reports_overview.js), so the
  // same platform is the same colour on every card and in the panel — the
  // split is ranked by spend, and a colour that followed the ranking would
  // change from card to card.
  function buildPlatformSlice(row, className) {
    const slice = document.createElement("span");
    slice.className = className + " is-platform-" + platformColorSlot(row.key);
    slice.style.width = (row.share * 100).toFixed(2) + "%";
    return slice;
  }

  // The roster's spend by platform, beside the grid. Hidden entirely when no
  // client's totals could be stated — an empty panel of zero-width bars says
  // nothing, and a panel of bars drawn from withheld figures says something
  // false.
  function renderReportsPlatforms(portfolio) {
    const panel = document.querySelector("[data-reports-platforms]");
    const rows = document.querySelector("[data-reports-platform-rows]");
    const note = document.querySelector("[data-reports-platform-note]");
    if (!panel || !rows) return;
    rows.textContent = "";
    panel.hidden = !portfolio.platforms.length;
    if (panel.hidden) return;
    portfolio.platforms.forEach(function (row) {
      const line = document.createElement("div");
      line.className = "reports-platform-row";
      const name = document.createElement("span");
      name.className = "reports-platform-name";
      // Registry / plugin-controlled display name — text, never markup.
      name.textContent = row.label;
      line.appendChild(name);
      const track = document.createElement("span");
      track.className = "reports-platform-track";
      track.appendChild(buildPlatformSlice(row, "reports-platform-bar"));
      line.appendChild(track);
      const value = document.createElement("span");
      value.className = "reports-platform-value";
      value.textContent = formatNumber(Math.round(row.spend));
      line.appendChild(value);
      rows.appendChild(line);
    });
    // The panel is a sum over other people's numbers, so it says whose.
    if (note) {
      const stated = portfolio.spend.stated;
      note.textContent =
        stated < portfolio.total
          ? MUREO.t("dashboard.reports_portfolio_coverage", {
              stated: stated,
              total: portfolio.total,
            })
          : "";
      note.hidden = !note.textContent;
    }
  }

  // What mureo did today, across the roster — the rail's top panel.
  //
  // A day with nothing logged renders NO panel: the same default silence the
  // alert layer keeps, and for the same reason. "0 actions today" is a frame
  // competing for attention with the sections that do have something in it,
  // and on a rail it would push the platform split below the fold to say so.
  //
  // Nothing here decides what "today" is — reports_overview.js does, from the
  // date the SERVER stated, which a static pin could never check.
  function renderReportsActionFeed(feed) {
    const panel = document.querySelector("[data-reports-feed]");
    const list = document.querySelector("[data-reports-feed-list]");
    const count = document.querySelector("[data-reports-feed-count]");
    const more = document.querySelector("[data-reports-feed-more]");
    if (!panel || !list) return;
    list.textContent = "";
    panel.hidden = !feed.items.length;
    if (!feed.items.length) return;
    if (count) {
      count.textContent = MUREO.t("dashboard.reports_feed_count", { n: feed.total });
    }
    feed.items.forEach(function (item) {
      list.appendChild(buildReportsFeedRow(item));
    });
    if (more) {
      more.textContent = feed.remaining
        ? MUREO.t("dashboard.reports_feed_more", { n: feed.remaining })
        : "";
      more.hidden = !feed.remaining;
    }
  }

  // One line of the feed: when, for whom, what.
  //
  // The client name is a button that opens that client's report — the feed
  // says a thing happened to somebody, and "show me" is the only follow-up
  // it can offer. It is a real button so the keyboard reaches it, and it
  // sits OUTSIDE nothing: the row itself is not interactive.
  function buildReportsFeedRow(item) {
    const row = document.createElement("li");
    row.className = "reports-feed-row";

    const time = document.createElement("span");
    time.className = "reports-feed-time";
    // Sliced out of the server's own timestamp by reports_overview.js — not
    // reformatted here, which would render it in the browser's timezone.
    time.textContent = item.time;
    row.appendChild(time);

    const dot = document.createElement("span");
    dot.className = "reports-feed-dot";
    row.appendChild(dot);

    const body = document.createElement("span");
    body.className = "reports-feed-body";
    const who = document.createElement("button");
    who.type = "button";
    who.className = "reports-feed-client";
    // Registry-controlled text — textContent, never markup (#533).
    who.textContent = item.name;
    who.addEventListener("click", function () {
      reportsActiveClient = item.slug;
      showReportsClientDetail(item.slug);
    });
    body.appendChild(who);
    const what = document.createElement("span");
    what.className = "reports-feed-text";
    // Writer-supplied text out of STATE.json's action log — text, not markup.
    what.textContent = item.text;
    body.appendChild(what);
    // …and clamped to two lines by the stylesheet, with the whole sentence
    // here. A real `summary` runs to several hundred characters, and one of
    // them turned this rail back into the wall of prose the index was
    // redesigned to end. Nothing is lost by it: the string is unaltered, it
    // is complete on this attribute, and the action log is rendered in full
    // on the client's own detail view. mureo's "never truncate silently"
    // rule is about a stored VALUE it would be changing; how many lines of
    // an unchanged string a 340px rail shows is a display decision, and the
    // alert rows above make the same one at one line.
    body.title = item.text;
    row.appendChild(body);
    return row;
  }

  // INDEX view: a card per client (KPIs + flags for the selected window).
  // Fetches each client's summary in parallel; a period toggle built from the
  // union of windows lets the operator triage by Yesterday / Last 30 days.
  async function renderReportsIndex(seq) {
    const wrap = document.querySelector("[data-reports-clients]");
    if (!wrap) return;
    // Archived clients are off the grid entirely (and no summary is fetched
    // for them), then the operator's own order is applied.
    const rows = orderReportsClients(visibleReportsClients());
    const summaries = await Promise.all(
      rows.map(function (c) {
        return fetchClientCardSummary(c && c.slug ? c.slug : "");
      })
    );
    if (seq !== reportsRenderSeq) return; // superseded by a newer render
    // Commit the view switch only once the data is ready — switching before
    // the await would expose an empty index grid if this render is superseded.
    setReportsView("index");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (freshness) freshness.textContent = "";
    // Triage before the cards (#651): which of these clients needs attention
    // today, ranked, with what to run about each. Built ONCE and handed to
    // both the layer and the grid, so the count above and the marks below
    // are the same list. This is the multi-client view, which is the only
    // place the Agency seam produces — a single workspace opens the detail
    // view directly and never reaches this function.
    const triage = buildReportsTriage(rows, summaries);
    // The roster's own figures, above the alerts — built from the same
    // summaries the cards below are built from, and stating over how many
    // clients each of them holds.
    const portfolio = buildReportsPortfolio(rows, summaries);
    renderReportsPortfolio(portfolio, triage);
    renderReportsTriage(triage);
    // The rail: what mureo did today, then where the money went. Both are
    // built from the summaries already in hand — no extra request.
    renderReportsActionFeed(buildReportsActionFeed(rows, summaries));
    renderReportsPlatforms(portfolio);
    wrap.textContent = "";
    // A filter left over from a previous render would hide cards with no
    // visible reason, so every index render starts on "all" — and the alert
    // list starts short again for the same reason it opens short at all.
    reportsHealthFilter = "all";
    reportsTriageShowAll = false;
    reportsTriageOpenKinds = {};
    rows.forEach(function (c, i) {
      wrap.appendChild(
        buildClientCardItem(
          c,
          summaries[i],
          wrap,
          triageMarksClient(triage, i),
          triageClientHealth(triage, i),
          triageClientBadges(triage, i)
        )
      );
    });
    const countBadge = document.querySelector("[data-reports-clients-count]");
    if (countBadge) {
      countBadge.textContent = MUREO.t("dashboard.reports_clients_count", {
        n: rows.length,
      });
    }
    renderReportsFilters(triageHealthCounts(triage, rows.length));
    if (!rows.length) {
      // Every client archived: say so, and leave the disclosure below as the
      // way back — an empty grid with no explanation reads as a broken view.
      const note = document.createElement("p");
      note.className = "reports-clients-empty";
      // The grid is role="list"; keep its children listitems so the message
      // is announced rather than dropped as an out-of-structure child.
      note.setAttribute("role", "listitem");
      note.textContent = MUREO.t("dashboard.reports_all_archived");
      wrap.appendChild(note);
    }
    renderReportsArchived();
    // Period toggle from the union of windows any client advertises.
    const union = [];
    summaries.forEach(function (s) {
      (s && Array.isArray(s.periods) ? s.periods : []).forEach(function (p) {
        if (typeof p === "string" && p && union.indexOf(p) === -1) union.push(p);
      });
    });
    renderReportsPeriodToggle(union);
  }

  // The archived-clients disclosure under the index. Un-archiving has to be
  // reachable from THIS screen: if the only way back were editing the client
  // registry by hand, archiving would be a trap. It does not need to be
  // prominent, so it is a collapsed <details> that appears only when there is
  // something in it.
  function renderReportsArchived() {
    const box = document.querySelector("[data-reports-archived]");
    const list = document.querySelector("[data-reports-archived-list]");
    const summary = document.querySelector("[data-reports-archived-summary]");
    if (!box || !list) return;
    const rows = archivedReportsClients();
    box.hidden = !rows.length;
    list.textContent = "";
    if (!rows.length) return;
    if (summary) {
      summary.textContent = MUREO.t("dashboard.reports_archived_title", {
        n: rows.length,
      });
    }
    rows.forEach(function (c) {
      const slug = c && c.slug ? c.slug : "";
      const name = (c && (c.name || c.slug)) || "";
      const row = document.createElement("li");
      row.className = "reports-archived-row";
      const label = document.createElement("span");
      label.className = "reports-archived-name";
      // Registry-controlled text — textContent, never innerHTML (#533).
      label.textContent = name;
      row.appendChild(label);
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "reports-archived-restore";
      restore.setAttribute(
        "aria-label",
        MUREO.t("dashboard.reports_archive_restore_label", { name: name })
      );
      restore.textContent = MUREO.t("dashboard.reports_archive_restore");
      // No confirmation: restoring resumes collection, which is the safe
      // direction. It still cannot recover the period that was missed.
      restore.addEventListener("click", function () {
        setReportsClientArchived(slug, false);
      });
      row.appendChild(restore);
      list.appendChild(row);
    });
  }

  // DETAIL view: one client's full report (per-platform KPIs, latest report,
  // recent activity, period toggle). Sets the back bar + client name.
  function showReportsClientDetail(slug) {
    setReportsView("detail");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (nameEl) {
      const c = reportsClients.find(function (r) {
        return r && r.slug === slug;
      });
      nameEl.textContent = c ? c.name || c.slug || "" : "";
    }
    // Bump the generation so any in-flight render is dropped, then load.
    reportsRenderSeq++;
    renderReportsSummary(slug || null);
  }

  // Render the period toggle from the summary's `periods` union. Shown only
  // when there is a real choice (>= 2 windows); a single-window account has
  // nothing to switch, so the toggle stays hidden. Buttons are recreated on
  // every render, so their click handlers never accumulate.
  //
  // A window mureo does not define still gets a button — those are figures
  // an agent really collected, under a name no view expects (#659) — but it
  // is marked `is-adhoc` and carries the explanation, so the tab an agent
  // invented is not mistaken for one mureo keeps up to date.
  function renderReportsPeriodToggle(periods) {
    const wrap = document.querySelector("[data-reports-period]");
    if (!wrap) return;
    const list = Array.isArray(periods)
      ? periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    wrap.textContent = "";
    if (list.length < 2) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    list.forEach(function (token) {
      const active = token === reportsPeriod;
      const adhoc = !isCanonicalReportsPeriod(token);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "reports-period-btn" +
        (active ? " is-active" : "") +
        (adhoc ? " is-adhoc" : "");
      btn.setAttribute("data-period", token);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.textContent = reportsPeriodLabel(token);
      if (adhoc) {
        // Named, not hidden and not silently kept: the operator is told what
        // this tab is so they can decide what to do with it.
        const hint = MUREO.t("dashboard.reports_period_adhoc");
        btn.title = hint;
        btn.setAttribute("aria-label", token + " — " + hint);
      }
      btn.addEventListener("click", function () {
        if (token === reportsPeriod) return;
        reportsPeriod = token;
        // Re-render the CURRENT view for the new window: the index re-fetches
        // every client's card, the detail re-fetches the selected client.
        // renderReports() preserves the active view + client via state.
        renderReports();
      });
      wrap.appendChild(btn);
    });
  }

  // Fetch + render the summary for a given client (or the default one).
  async function renderReportsSummary(client) {
    const seq = reportsRenderSeq;
    // NB: reportsActiveClient is set only after the stale-render guards below,
    // so a superseded call can never reset it to a no-longer-shown client
    // (which would make the period toggle re-fetch the wrong one).
    const cards = document.querySelector("[data-reports-cards]");
    const empty = document.querySelector("[data-reports-empty]");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (!cards) return;

    let summary;
    try {
      const params = [];
      if (client) params.push("client=" + encodeURIComponent(client));
      if (reportsPeriod) params.push("period=" + encodeURIComponent(reportsPeriod));
      const url =
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "");
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      summary = await res.json();
    } catch (_err) {
      // Fetch/parse failed. Clear any prior render so a failed client switch
      // never leaves a different client's numbers on screen — degrade to the
      // empty state rather than stale data.
      if (seq !== reportsRenderSeq) return;
      reportsActiveClient = client || null;
      cards.textContent = "";
      if (freshness) freshness.textContent = "";
      renderReportsPeriodToggle([]);
      renderReportsLatest(null);
      renderReportsActions(null);
      if (empty) empty.hidden = false;
      return;
    }
    if (seq !== reportsRenderSeq) return; // Superseded by a newer render.
    reportsActiveClient = client || null;
    // A 200 whose body is not a JSON object (null / string / number from a
    // misbehaving backend or proxy) must not crash the render — coerce to an
    // empty summary so the guarded accessors below fall back to the empty state.
    if (!summary || typeof summary !== "object") summary = {};

    // Reconcile the selected window against the windows that actually carry
    // data. When the preferred window (YESTERDAY) has nothing yet, fall back
    // to the first available and re-fetch ONCE — the corrected period is
    // guaranteed to be in `available`, so the re-entry can't loop.
    const available = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    if (available.length && available.indexOf(reportsPeriod) === -1) {
      reportsPeriod =
        available.indexOf("YESTERDAY") !== -1 ? "YESTERDAY" : available[0];
      return renderReportsSummary(client);
    }
    renderReportsPeriodToggle(available);

    cards.textContent = "";

    const platforms = Array.isArray(summary.platforms) ? summary.platforms : [];
    if (freshness) {
      // Document-level, and labelled as such ("Synced N ago"). Per-platform
      // freshness lives on each card's footer — see buildReportCardFoot.
      freshness.textContent = summary.last_synced_at
        ? MUREO.t("dashboard.reports_synced", {
            ago: relativeAge(summary.last_synced_at),
          })
        : "";
    }

    if (platforms.length === 0) {
      if (empty) empty.hidden = false;
    } else {
      if (empty) empty.hidden = true;
      platforms.forEach(function (p) {
        cards.appendChild(buildReportCard(p, summary));
      });
    }

    renderReportsLatest(summary.reports);
    renderReportsActions(summary.recent_actions);
  }

  // Entry point: fetch the client list, then show the right view. Re-runnable
  // (tab open, locale / period change, navigation).
  //
  // `entry` says WHY this render is happening, and it is the whole routing
  // input the state cannot supply: the left menu asking for the section is a
  // request for the client list, while a period switch or a status refresh
  // is a redraw of whatever the operator is already reading. Both arrive
  // here, and before this argument existed the second's rule ("keep the
  // detail while its client is alive") also governed the first — so the menu
  // could not get back to the list at all. The rule itself lives in
  // reports_overview.js, where the JS suite executes it.
  //
  // The routing decision counts the WHOLE registry, archived rows included.
  // Counting only the visible ones would drop an operator who archived down
  // to one client into that client's detail view — and the index is the only
  // place an archived client can be restored from, so the feature would trap
  // them. A registry that has ever held more than one client keeps its index.
  async function renderReports(entry) {
    const cards = document.querySelector("[data-reports-cards]");
    if (!cards) return;
    const seq = ++reportsRenderSeq;
    const body = await fetchReportsJson("/api/reports/clients");
    if (seq !== reportsRenderSeq) return;
    reportsClients = body && Array.isArray(body.clients) ? body.clients : [];
    reportsCanArchive = !!(body && body.can_archive);

    // An archived client is not a live selection: archiving the one on screen
    // returns the operator to the index rather than leaving them on a detail
    // view for a client that is no longer being collected.
    const hasIndex =
      reportsClients.length > 1 || archivedReportsClients().length > 0;
    const view = reportsViewToShow({
      entry: entry,
      currentView: reportsView,
      hasIndex: hasIndex,
      selectionAlive:
        reportsActiveClient &&
        visibleReportsClients().some(function (c) {
          return c && c.slug === reportsActiveClient;
        }),
    });
    if (view === "index") {
      await renderReportsIndex(seq);
      return;
    }
    // OSS single workspace: no index page — the detail IS the section, so
    // the client is resolved here rather than carried across renders.
    if (!hasIndex) {
      reportsActiveClient = defaultClientSlug(reportsClients);
    }
    // showReportsClientDetail() sets the view + syncs the DOM.
    showReportsClientDetail(reportsActiveClient);
  }

  // Entering the Reports section from the left menu. Always the client list
  // — see renderReports() above. Exported to selectNavGroup(), the one place
  // that knows the operator clicked the menu item.
  function enterReportsSection() {
    renderReports(REPORTS_OVERVIEW.REPORTS_ENTRY_MENU);
  }

  // Wire the back-to-index button once. Re-fetches the client list (a fresh
  // sync may have changed it) and shows the index.
  function wireReportsBackButton() {
    const back = document.querySelector("[data-reports-back]");
    if (!back) return;
    back.addEventListener("click", function () {
      reportsView = "index";
      renderReports();
    });
  }

  const api = {
    renderReports: renderReports,
    enterReportsSection: enterReportsSection,
    wireReportsBackButton: wireReportsBackButton,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
