// dashboard_reports_report.js — the stored report, rendered.
//
// Split out of dashboard_reports_cards.js (#687). Nothing here changed in the
// move beyond the bindings at the top.
//
// One agent-written report summary, turned into a block an operator can read:
// its headline figures first, then the secondary stats, then the flag chips,
// then the prose. The order is the argument — a figure buried under 700
// characters of paragraph is a figure nobody sees (#662).
//
// Two things it will not do. It does not decide WHICH fields are figures —
// a report summary is agent-written, and everything that reaches the headline
// row is presented as a number, with reports_format.js holding the
// vocabulary. And it never prints a figure mureo cannot vouch for: a withheld
// or stale total is restated below the cells as its own line, never as a dash
// inside them, which is the one thing #638 established this view must not do.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_REPORT`. Loads AFTER
// dashboard_reports_state.js and BEFORE dashboard_reports_cards.js.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_report.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_report.js"
    );
  }
  const relativeAge = REPORTS_SHARED.relativeAge;
  const reportsPlatformLabels = REPORTS_SHARED.reportsPlatformLabels;
  const reportsConflictText = REPORTS_SHARED.reportsConflictText;
  const reportsRepairHint = REPORTS_SHARED.reportsRepairHint;
  const reportsConflictsForKey = REPORTS_SHARED.reportsConflictsForKey;
  const reportsFreshnessLabel = REPORTS_SHARED.reportsFreshnessLabel;
  const reportsRowIsStale = REPORTS_SHARED.reportsRowIsStale;
  const reportsNotCollectedNote = REPORTS_SHARED.reportsNotCollectedNote;
  const reportsNotCollectedText = REPORTS_SHARED.reportsNotCollectedText;
  const humanizeReportFlag = REPORTS_SHARED.humanizeReportFlag;
  const reportFlagKind = REPORTS_SHARED.reportFlagKind;
  const latestReport = REPORTS_SHARED.latestReport;
  const buildFlagDetail = REPORTS_SHARED.buildFlagDetail;
  const formatNumber = REPORTS_SHARED.formatNumber;
  const formatKpi = REPORTS_SHARED.formatKpi;
  const reportSummaryTotals = REPORTS_SHARED.reportSummaryTotals;
  const reportSecondaryStats = REPORTS_SHARED.reportSecondaryStats;
  const reportStatLabel = REPORTS_SHARED.reportStatLabel;
  const REPORTS_KPI_LABELS = REPORTS_SHARED.REPORTS_KPI_LABELS;

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

  // Label first, then the figure — the same anatomy the portfolio strip's
  // cells already had (#691). This one was built the other way round, so the
  // two KPI families on the index read in opposite orders; a reader scanning
  // a column of figures had to work out which caption belonged to which
  // number in each. Same two nodes, same parent, same classes: only the
  // order they are appended in.
  function clientKpiCell(labelKey, value) {
    const cell = document.createElement("div");
    cell.className = "reports-client-kpi";
    const l = document.createElement("span");
    l.className = "reports-client-kpi-label";
    l.textContent = MUREO.t(labelKey);
    const v = document.createElement("span");
    v.className = "reports-client-kpi-value";
    v.textContent = value;
    cell.appendChild(l);
    cell.appendChild(v);
    return cell;
  }


  const api = {
    buildStaleFiguresElement: buildStaleFiguresElement,
    staleAggregateFiguresText: staleAggregateFiguresText,
    clientKpiCell: clientKpiCell,
    buildReportCard: buildReportCard,
    renderReportsLatest: renderReportsLatest,
    renderReportsActions: renderReportsActions,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_REPORT = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
