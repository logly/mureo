// dashboard_reports_cards.js — one client's card, and the report inside it.
//
// Lifted verbatim out of dashboard_reports.js (#687). Nothing here changed in
// the move beyond the bindings at the top.
//
// Everything about rendering ONE thing: the stored report's own block (its
// headline figures, secondary stats, flag chips and prose), and the client
// card that carries it in the grid — its KPI cells, freshness, conflict and
// not-collected notices, drag handle and archive control.
//
// Not one decision about which clients to show, what the roster totals, or
// which view the section is on: that is dashboard_reports.js's half. The
// three functions there that a card needs — `renderReports`,
// `showReportsClientDetail`, `buildPlatformSlice` — are resolved per call
// below, because that file's `<script>` tag comes after this one.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_CARDS`. Loads AFTER
// dashboard_reports_state.js and BEFORE dashboard_reports.js.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_cards.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_cards.js"
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
  const reportsCardFreshness = REPORTS_SHARED.reportsCardFreshness;
  const aggregateClientKpis = REPORTS_SHARED.aggregateClientKpis;
  const humanizeReportFlag = REPORTS_SHARED.humanizeReportFlag;
  const reportFlagKind = REPORTS_SHARED.reportFlagKind;
  const flagSeverityRank = REPORTS_SHARED.flagSeverityRank;
  const latestReport = REPORTS_SHARED.latestReport;
  const clientReportFlags = REPORTS_SHARED.clientReportFlags;
  const buildFlagDetail = REPORTS_SHARED.buildFlagDetail;
  const formatNumber = REPORTS_SHARED.formatNumber;
  const formatKpi = REPORTS_SHARED.formatKpi;
  const reportSummaryTotals = REPORTS_SHARED.reportSummaryTotals;
  const reportSecondaryStats = REPORTS_SHARED.reportSecondaryStats;
  const reportStatLabel = REPORTS_SHARED.reportStatLabel;
  const persistReportsOrderFromDom = REPORTS_SHARED.persistReportsOrderFromDom;
  const moveReportsCard = REPORTS_SHARED.moveReportsCard;
  const clientPlatformSplit = REPORTS_SHARED.clientPlatformSplit;
  const platformColorSlot = REPORTS_SHARED.platformColorSlot;
  const REPORTS_KPI_LABELS = REPORTS_SHARED.REPORTS_KPI_LABELS;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // Defined in dashboard_reports.js, which loads AFTER this file, so each name is
  // resolved when a card is clicked rather than at load. That is what
  // lets the call sites below read exactly as they always did.
  function cardsPeer() {
    const api = typeof window !== "undefined" ? window.MUREO_DASHBOARD_REPORTS : null;
    if (!api) {
      throw new Error(
        "MUREO_DASHBOARD_REPORTS (dashboard_reports.js) is missing — its <script> tag must come " +
          "AFTER dashboard_reports_cards.js in app.html."
      );
    }
    return api;
  }

  function buildPlatformSlice(row, className) {
    return cardsPeer().buildPlatformSlice(row, className);
  }

  function renderReports(entry) {
    return cardsPeer().renderReports(entry);
  }

  function showReportsClientDetail(slug) {
    return cardsPeer().showReportsClientDetail(slug);
  }

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
    let summary =
      (await fetchReportsJson(summaryUrl(REPORTS_VIEW_STATE.reportsPeriod))) || {};
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
      const fallback =
        periods.indexOf(REPORTS_VIEW_STATE.reportsPeriod) === -1 ? periods[0] : null;
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
    return REPORTS_VIEW_STATE.reportsClients.filter(function (c) {
      return !isArchivedClient(c);
    });
  }

  function archivedReportsClients() {
    return REPORTS_VIEW_STATE.reportsClients.filter(isArchivedClient);
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
    REPORTS_VIEW_STATE.reportsView = "index";
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
    if (REPORTS_VIEW_STATE.reportsCanArchive && slug) {
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
      REPORTS_VIEW_STATE.reportsActiveClient = slug;
      showReportsClientDetail(slug);
    });
    return card;
  }


  const api = {
    archivedReportsClients: archivedReportsClients,
    buildClientCardItem: buildClientCardItem,
    buildReportCard: buildReportCard,
    fetchClientCardSummary: fetchClientCardSummary,
    fetchReportsJson: fetchReportsJson,
    renderReportsActions: renderReportsActions,
    renderReportsLatest: renderReportsLatest,
    setReportsClientArchived: setReportsClientArchived,
    visibleReportsClients: visibleReportsClients,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_CARDS = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
