// dashboard_reports_changes.js — tier (2) of the detail view: what moved
// since yesterday, and what is wrong (#715).
//
// Lifted whole out of dashboard_reports.js, which is the INDEX file: it
// decides which clients an operator is looking at and what the roster says
// about them. This tier is about ONE client's platforms over two adjacent
// days, so it was the block in that file that answered a different question
// from everything around it.
//
// Nothing here decides anything new about an ad account. Which way is bad
// (`changeTone`), where a movement moved FROM (`deltaEndpoints`) and the week
// behind it (`buildMetricSparkline`) are all dashboard_reports_report.js's
// answers, bound below by their original names so a movement is never good
// news on one tier and bad on another (#691 phase 4).
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_CHANGES`. Loads AFTER
// dashboard_reports_state.js and dashboard_reports_report.js (whose bindings
// it reads at load) and BEFORE dashboard_reports.js, which calls it
// mid-render.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names —
  // the same block every dashboard_reports_*.js module opens with.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_changes.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_changes.js"
    );
  }
  const formatKpi = REPORTS_SHARED.formatKpi;
  const REPORTS_KPI_LABELS = REPORTS_SHARED.REPORTS_KPI_LABELS;

  // dashboard_reports_report.js's exports, likewise by their original names.
  const R_REPORT = window.MUREO_DASHBOARD_REPORTS_REPORT;
  if (!R_REPORT) {
    throw new Error(
      "dashboard_reports_changes.js needs MUREO_DASHBOARD_REPORTS_REPORT — load " +
        "dashboard_reports_report.js BEFORE dashboard_reports_changes.js"
    );
  }
  const buildReportFlagRow = R_REPORT.buildReportFlagRow;
  const changeTone = R_REPORT.changeTone;
  const deltaEndpoints = R_REPORT.deltaEndpoints;
  const buildMetricSparkline = R_REPORT.buildMetricSparkline;

  // ------------------------------------------------------------------
  // (2) Today's changes
  // ------------------------------------------------------------------

  // Which metrics a change card may be about, most consequential first.
  //
  // FIXED ORDER, and not "the largest movement". #690 gives absolute
  // differences only — `after - before`, per metric — because a percentage
  // needs a rule for a zero baseline that nobody has agreed. Absolute
  // differences in different UNITS cannot be ranked against each other: a
  // spend that moved by 6,500 yen and a CTR that moved by 0.4 points are not
  // 16,000x apart, they are incomparable, and sorting them would be this
  // file inventing a comparison and presenting it as a measurement.
  //
  // So the ranking is stated instead, and it is an argument about money: CPA
  // is what an operator is judged on, spend is what is being consumed,
  // conversions are what it bought. The three delivery metrics below them
  // explain those three but are not themselves the news.
  const REPORTS_CHANGE_PRIORITY = [
    "cpa",
    "spend",
    "conversions",
    "ctr",
    "clicks",
    "impressions",
  ];

  // How many change cards the tier shows. Three, because the tier is the
  // answer to "what should I look at first" and a list of nine is not one.
  const REPORTS_CHANGE_CAP = 3;

  /**
   * The change cards to render, or [] when none can be honestly made.
   *
   * A metric qualifies when its platform states a `daily_delta` (#690 —
   * present only when two CALENDAR-adjacent days are stored, so a gap is
   * never rendered as a day-over-day move) and its difference is non-zero.
   * Zero is not a change; a card saying "0" would be noise with the same
   * weight as the ones that matter.
   */
  function changeHighlights(platforms) {
    const rows = [];
    (Array.isArray(platforms) ? platforms : []).forEach(function (p) {
      const delta = p && p.daily_delta;
      const metrics = delta && delta.metrics;
      if (!metrics || typeof metrics !== "object") return;
      REPORTS_CHANGE_PRIORITY.forEach(function (key) {
        const diff = metrics[key];
        if (typeof diff !== "number" || !isFinite(diff) || diff === 0) return;
        const now = p.totals && p.totals[key];
        const value = typeof now === "number" && isFinite(now) ? now : null;
        // Both figures on this card have to come from `daily` — the movement
        // AND the day it moved from. deltaEndpoints reads them out of the
        // series by date and refuses when the series and the window rollup
        // disagree about the same day, which is the mixture that put a
        // "from 1,712" under a card whose stored days said 2,992 → 3,855.
        // A card that cannot state where it moved from is not drawn.
        const ends = deltaEndpoints(p, key, value);
        if (!ends) return;
        rows.push({
          platform: p,
          key: key,
          diff: diff,
          value: value,
          previous: ends.previous,
          rank: REPORTS_CHANGE_PRIORITY.indexOf(key),
        });
      });
    });
    // Priority first; platform order (the order the API returned) breaks a
    // tie, so two platforms moving the same metric read in a stable order.
    rows.sort(function (a, b) {
      return a.rank - b.rank;
    });
    return rows.slice(0, REPORTS_CHANGE_CAP);
  }

  // Which way is bad, per metric — and for most of them the answer is
  // "neither", which is the point of writing it down.
  //
  // Colour is a VERDICT, so it is spent only where mureo can actually reach
  // one from the number alone:
  //
  //   cpa         — up is worse, down is better. The one unambiguous axis.
  //   conversions — down is worse, up is better.
  //   ctr         — down is worse. Up is NOT called good: a CTR that rose a
  //                 tenth of a point is noise, and calling it a win teaches
  //                 an operator to read the colour instead of the number.
  //   spend       — neutral in BOTH directions. Spending more is not a
  //   clicks        failure; it is usually the plan. Painting a spend rise
  //   impressions   red is the single most misleading thing this card could
  //                 do, and it is what the first cut of it did.
  //
  // A metric absent from this table is neutral. Direction still reaches the
  // reader — the card prints an arrow — so nothing is lost by not colouring.
  // One change card: label, figure, and what it moved from.
  function buildChangeCard(row) {
    const card = document.createElement("div");
    card.className = "reports-change";

    const label = document.createElement("span");
    label.className = "reports-change-label";
    const name = row.platform && row.platform.display_name;
    const metric =
      row.key === "spend"
        ? MUREO.t("dashboard.reports_kpi_spend")
        : MUREO.t(REPORTS_KPI_LABELS[row.key] || row.key);
    label.textContent = name ? name + " ・ " + metric : metric;
    card.appendChild(label);

    const value = document.createElement("span");
    value.className = "reports-change-value";
    value.textContent =
      row.value === null
        ? MUREO.t("dashboard.reports_no_metrics")
        : formatKpi(row.key, row.key === "cpa" ? Math.round(row.value) : row.value);
    card.appendChild(value);

    const delta = document.createElement("span");
    delta.className = "reports-change-delta " + changeTone(row.key, row.diff);
    const arrow = document.createElement("b");
    // The arrow is the direction, and it is a character rather than colour
    // alone so the card still reads for anyone the colour does not.
    arrow.textContent =
      (row.diff > 0 ? "↑ " : "↓ ") +
      formatKpi(row.key, row.key === "cpa" ? Math.round(row.diff) : Math.abs(row.diff));
    delta.appendChild(arrow);
    // The stored figure for the day it moved from, never `value - diff`:
    // those two come from different places on the wire and subtracting one
    // from the other printed a number that was in neither.
    const prev = document.createElement("span");
    prev.className = "reports-change-prev";
    prev.textContent = MUREO.t("dashboard.reports_delta_prev", {
      value: formatKpi(
        row.key,
        row.key === "cpa" ? Math.round(row.previous) : row.previous
      ),
    });
    delta.appendChild(prev);
    card.appendChild(delta);
    // The week behind the one-day move (#691 phase 4). A row only reaches
    // this function when `daily_delta` gave it a movement, so there are at
    // least two adjacent days — but not necessarily two PLOTTABLE ones for
    // this metric, so the result is still optional and simply absent when
    // there is no line to draw.
    const spark = buildMetricSparkline(row.platform, row.key);
    if (spark) card.appendChild(spark);
    return card;
  }

  /**
   * Render tier (2): what moved, and what is wrong.
   *
   * Two independent contents, and the tier appears when EITHER has something
   * to say. The change cards need #690's `daily_delta`, which is `null` for a
   * first day, for a gap between the last two stored days, and for a metric
   * only one side carries — all three mean the comparison cannot honestly be
   * made, so no card is drawn rather than a fabricated zero. The flag row
   * comes from the report and needs no history at all, so an install with one
   * day of data still gets its findings here.
   *
   * The heading's note is about the change cards specifically, so it is
   * hidden when there are none: "the metrics that moved most" over a row of
   * flags would describe something that is not on screen.
   */
  function renderReportsChanges(platforms, report) {
    const block = document.querySelector("[data-reports-changes]");
    const body = document.querySelector("[data-reports-changes-body]");
    const note = document.querySelector("[data-reports-changes-note]");
    if (!block || !body) return;
    body.textContent = "";
    const rows = changeHighlights(platforms);
    rows.forEach(function (row) {
      body.appendChild(buildChangeCard(row));
    });
    const flagRow = buildReportFlagRow(report);
    if (flagRow) body.appendChild(flagRow);
    if (note) note.hidden = rows.length === 0;
    block.hidden = rows.length === 0 && !flagRow;
  }

  const api = {
    renderReportsChanges: renderReportsChanges,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_CHANGES = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
