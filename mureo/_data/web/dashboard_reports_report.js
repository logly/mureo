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
  const humanizeFlagWords = REPORTS_SHARED.humanizeFlagWords;
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

  // ------------------------------------------------------------------
  // Day-over-day movement (#691 phase 4)
  // ------------------------------------------------------------------

  /**
   * Which direction of a metric is worth colouring, and how.
   *
   * Spend, clicks and impressions are absent on purpose: they are volume,
   * and volume going up is neither good nor bad without a target nobody has
   * put on the wire. Colouring them was the #694 capture's finding — every
   * delta arrived red, including a spend rise, which trains an operator to
   * ignore the colour entirely. CTR rising is "is-flat" for the narrower
   * version of the same reason: a small rise is not an achievement worth
   * announcing, while a fall is worth a look.
   *
   * Lives here rather than in dashboard_reports.js because BOTH tiers draw
   * deltas now — the change cards in (2) and the platform cards in (3) — and
   * a second copy is how two rows describing the same movement start
   * disagreeing about whether it was good news.
   */
  const REPORTS_CHANGE_TONE = {
    cpa: { up: "is-bad", down: "is-good" },
    conversions: { up: "is-good", down: "is-bad" },
    ctr: { up: "is-flat", down: "is-bad" },
  };

  function changeTone(key, diff) {
    const axis = REPORTS_CHANGE_TONE[key];
    if (!axis) return "is-flat";
    return diff > 0 ? axis.up : axis.down;
  }

  /** CPA is carried to the yen; the rest keep whatever precision they have. */
  function roundedFor(key, value) {
    return key === "cpa" ? Math.round(value) : value;
  }

  /**
   * "↑ 1,200  from 4,200" for one metric, or `null`.
   *
   * `null` whenever #690 declined to state the movement — fewer than two
   * days, a calendar gap between the last two, or a metric only one of them
   * carries. All three mean the comparison cannot honestly be made, and a
   * caller that appends whatever it gets then shows nothing rather than a
   * fabricated zero.
   *
   * Absolute difference only. A percentage needs a rule for a zero baseline
   * and #690 does not carry one, so inventing it here would be this layer
   * making up the very thing the server refused to.
   */
  function buildDeltaElement(delta, key, current) {
    const metrics = delta && typeof delta === "object" ? delta.metrics : null;
    const diff = metrics && typeof metrics === "object" ? metrics[key] : undefined;
    if (typeof diff !== "number" || !isFinite(diff)) return null;

    const el = document.createElement("span");
    el.className = "report-delta " + changeTone(key, diff);
    const arrow = document.createElement("b");
    // The direction is a character before it is a colour, so the row still
    // reads for anyone the colour does not reach.
    arrow.className = "report-delta-move";
    arrow.textContent =
      (diff > 0 ? "↑ " : diff < 0 ? "↓ " : "± ") +
      formatKpi(key, roundedFor(key, Math.abs(diff)));
    el.appendChild(arrow);
    if (typeof current === "number" && isFinite(current)) {
      const prev = document.createElement("span");
      prev.className = "report-delta-prev";
      prev.textContent = MUREO.t("dashboard.reports_delta_prev", {
        value: formatKpi(key, roundedFor(key, current - diff)),
      });
      el.appendChild(prev);
    }
    return el;
  }

  /**
   * The sparkline for one metric of one platform, or `null`.
   *
   * Resolved at call time: reports_sparkline.js publishes its global the same
   * way every module in this family does, and a missing one is a load-order
   * bug rather than something to paper over.
   */
  function buildMetricSparkline(platform, key) {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_SPARKLINE : null;
    if (!api) {
      throw new Error(
        "MUREO_REPORTS_SPARKLINE (reports_sparkline.js) is missing — its " +
          "<script> tag must come BEFORE dashboard_reports_report.js."
      );
    }
    return api.buildSparkline(platform && platform.daily, key);
  }

  /**
   * Append the delta and the sparkline for `key` to a KPI cell, if any.
   *
   * Both are optional and independent: an install with two days has a delta
   * and a two-point line, one with a gap before yesterday has a line and no
   * delta, and a fresh install has neither and gets neither — no empty
   * frame, no dash, no reserved space. That is the DEFAULT state of this
   * feature until daily-check has run for a while, so it is the one the
   * layout has to look right in.
   */
  function appendTrend(cell, platform, key, current) {
    const delta = buildDeltaElement(platform && platform.daily_delta, key, current);
    if (delta) cell.appendChild(delta);
    const spark = buildMetricSparkline(platform, key);
    if (spark) cell.appendChild(spark);
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

    // Headline number: spend, large, tabular so digits align.
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
    // Label, then figure — the anatomy every other cell on these screens
    // uses (#691). This one was built the other way round, so the single card
    // carrying both spend and CPA read in two directions at once.
    headline.appendChild(headlineLabel);
    headline.appendChild(headlineValue);
    // The two slots phase 1 reserved in the card anatomy (label → value →
    // delta → sparkline), filled. Below the withholding branch it would be
    // unreachable for a stale row, which is right: see the note there.
    if (!rowStale) appendTrend(headline, platform, "spend", totals.spend);
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

    // CPA joins spend at the top (#691). They are the two an operator is
    // judged on — what was consumed and what it cost per result — and CPA was
    // previously the same size as impressions, four rows down. Everything
    // else stays small: they explain these two rather than compete with them.
    if (totals.cpa != null) {
      const second = document.createElement("div");
      second.className = "report-card-second";
      const value = document.createElement("span");
      value.className = "report-card-second-value";
      value.textContent = formatKpi("cpa", totals.cpa);
      const label = document.createElement("span");
      label.className = "report-card-second-label";
      label.textContent = MUREO.t(REPORTS_KPI_LABELS.cpa);
      second.appendChild(label);
      second.appendChild(value);
      appendTrend(second, platform, "cpa", totals.cpa);
      card.appendChild(second);
    }

    // The rest of the canonical vocabulary, in a tidy 2-col grid — only those
    // present in totals, and no longer CPA, which is above.
    const grid = document.createElement("dl");
    grid.className = "report-card-kpis";
    Object.keys(REPORTS_KPI_LABELS).forEach(function (key) {
      if (key === "cpa" || totals[key] == null) return;
      const term = document.createElement("dt");
      term.textContent = MUREO.t(REPORTS_KPI_LABELS[key]);
      const def = document.createElement("dd");
      def.textContent = formatKpi(key, totals[key]);
      grid.appendChild(term);
      grid.appendChild(def);
    });
    if (grid.childNodes.length > 0) card.appendChild(grid);

    // Anything the platform stated that the canonical vocabulary has no slot
    // for, behind a disclosure. Rendered only when there IS something: a
    // "Show all metrics" control that opens onto nothing is worse than no
    // control. `period` and `fetched_at` are excluded — they are the window
    // and the timestamp, both already on the card, and neither is a metric.
    const extra = document.createElement("dl");
    extra.className = "report-card-kpis";
    Object.keys(totals).forEach(function (key) {
      if (key === "spend" || key === "period" || key === "fetched_at") return;
      if (REPORTS_KPI_LABELS[key] || totals[key] == null) return;
      const term = document.createElement("dt");
      term.textContent = key;
      const def = document.createElement("dd");
      def.textContent = formatKpi(key, totals[key]);
      extra.appendChild(term);
      extra.appendChild(def);
    });
    if (extra.childNodes.length > 0) {
      const more = document.createElement("details");
      more.className = "report-card-more";
      const summaryEl = document.createElement("summary");
      const summaryText = document.createElement("span");
      summaryText.textContent = MUREO.t("dashboard.reports_all_metrics");
      const summaryCount = document.createElement("span");
      summaryCount.className = "report-card-more-count";
      summaryCount.textContent = MUREO.t("dashboard.reports_metric_count", {
        n: extra.childNodes.length / 2,
      });
      summaryEl.appendChild(summaryText);
      summaryEl.appendChild(summaryCount);
      more.appendChild(summaryEl);
      more.appendChild(extra);
      card.appendChild(more);
    }

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
    const el = document.createElement("tr");
    el.className = "report-stat";
    const key = document.createElement("th");
    key.scope = "row";
    key.className = "report-stat-key";
    key.textContent = reportStatLabel(entry.path);
    const value = document.createElement("td");
    value.className = "report-stat-value";
    value.textContent = String(entry.value);
    el.appendChild(key);
    el.appendChild(value);
    return el;
  }

  // The table those values sit in, captioned so it is never read as the
  // headline figures above it.
  //
  // A table rather than the chip row it was (#691): these are label/value
  // pairs, and a chip row makes the reader re-parse where each label ends and
  // its figure begins on every line. Left-aligned label, right-aligned
  // tabular figure, one per row — the shape the eye can scan down. The
  // DATA is untouched: reportSecondaryStats still decides which fields are
  // here and which are counted as hidden.
  function buildReportStatsRow(stats) {
    const row = document.createElement("table");
    row.className = "report-latest-stats";
    const title = document.createElement("caption");
    title.className = "report-stats-title";
    title.textContent = MUREO.t("dashboard.reports_stats_title");
    row.appendChild(title);
    const tbody = document.createElement("tbody");
    stats.entries.forEach(function (entry) {
      tbody.appendChild(buildReportStatElement(entry));
    });
    row.appendChild(tbody);
    // Fields with no flat rendering (a deeper tree, a list) are stated as
    // existing rather than dropped — being silently discarded is the whole
    // of what #670 is about. The count is of FIELDS, which is what the
    // string says: a fifty-element list is one of them. The stored report
    // is where they are read.
    if (stats.hidden > 0) {
      const foot = document.createElement("tfoot");
      const tr = document.createElement("tr");
      const more = document.createElement("td");
      more.className = "report-stat-more";
      more.colSpan = 2;
      more.textContent = MUREO.t("dashboard.reports_stats_more", { n: stats.hidden });
      tr.appendChild(more);
      foot.appendChild(tr);
      row.appendChild(foot);
    }
    return row;
  }

  /**
   * A narrative, with its opening sentence emphasised.
   *
   * The opening sentence is the CONCLUSION — the report writer is instructed
   * to lead with it — and it is the thing an operator opened the page for. It
   * used to be the last paragraph on the screen, under two rows of chips.
   *
   * The split rule is deliberately dumb: whichever comes FIRST of `。` and
   * `". "` — a full stop followed by a space. Both locales write reports, and
   * a rule that only knew `。` left every English narrative unemphasised,
   * which is what the capture review caught.
   *
   * `". "` and not `"."`: a bare period is not a sentence end in a text
   * carrying figures like `3.42%` or `v0.13.1`, and requiring the space is
   * what keeps those intact. No tokeniser, no abbreviation table — when
   * neither stop is present nothing is emphasised and the narrative renders
   * whole and plain, which is the honest outcome for a text this cannot
   * parse: bolding half a sentence is worse than bolding none of it.
   */
  function buildNarrativeElement(text) {
    const el = document.createElement("p");
    el.className = "report-latest-narrative";
    const whole = String(text);
    // Both candidates, and the earlier one wins. `。` carries its own break,
    // `". "` needs the period kept and the space dropped from the lead.
    const ja = whole.indexOf("。");
    const en = whole.indexOf(". ");
    let cut = -1;
    if (ja !== -1 && (en === -1 || ja < en)) cut = ja + 1;
    else if (en !== -1) cut = en + 1;
    if (cut === -1) {
      el.textContent = whole;
      return el;
    }
    const lead = document.createElement("b");
    lead.className = "report-latest-lead";
    lead.textContent = whole.slice(0, cut);
    el.appendChild(lead);
    const rest = whole.slice(cut);
    if (rest) el.appendChild(document.createTextNode(rest));
    return el;
  }

  // How many flag chips the detail view shows before collapsing to a count.
  // Four, matching the mockup; the client card caps at three because its
  // track is narrower (REPORTS_CLIENT_FLAG_CAP).
  //
  // Note this is a DISPLAY cap and nothing else: every flag the report stated
  // is still counted, and "+N more" says how many are not drawn. It is not
  // related to the alert list's per-message dismissal, which is a different
  // surface with its own persisted state (reports_triage.js) — a report flag
  // has no dismiss and is not filtered by one.
  const REPORT_FLAG_CAP = 4;

  /** The flag row for one report: up to four chips, then "+N more". */
  function buildReportFlagRow(report) {
    const flags = Array.isArray(report && report.flags) ? report.flags : [];
    if (flags.length === 0) return null;
    const chips = document.createElement("div");
    chips.className = "report-flags";
    flags.slice(0, REPORT_FLAG_CAP).forEach(function (flag) {
      chips.appendChild(buildFlagChipElement(flag));
    });
    if (flags.length > REPORT_FLAG_CAP) {
      const more = document.createElement("span");
      more.className = "report-flag-more";
      more.textContent = MUREO.t("dashboard.reports_flags_more", {
        n: flags.length - REPORT_FLAG_CAP,
      });
      chips.appendChild(more);
    }
    return chips;
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
      const emptySlot = document.querySelector("[data-reports-latest-period]");
      if (emptySlot) emptySlot.textContent = "";
      return;
    }
    block.hidden = false;

    // The window the report covers belongs in the tier's heading, beside the
    // number, not as a line of its own above the prose.
    const periodSlot = document.querySelector("[data-reports-latest-period]");
    if (periodSlot) {
      periodSlot.textContent = report.period ? String(report.period) : "";
    }
    // The headline figures the report stated, AS FIGURES (#662). The schema
    // has always defined `totals` / `kpis` next to `flags` and `narrative`;
    // what it had no way to do was make anything render them, so a report
    // that put its numbers where they belong looked exactly like one that
    // folded them into the paragraph. Only the canonical vocabulary and only
    // real numbers reach this row — reports_format.js decides that — so a
    // report already on disk states nothing here and stays readable below,
    // as the prose it is.
    // The conclusion, first. Everything below it is support.
    if (report.narrative) {
      body.appendChild(buildNarrativeElement(report.narrative));
    }
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
    // The flag row is tier (2)'s — it is a list of what is WRONG, which is
    // what that tier is for. renderReportsChanges appends it.
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
      // WHEN and WHAT KIND, on one quiet line above the sentence — the shape
      // the mockup draws. This was three stacked blocks with the sentence in
      // the middle, which reads as a loose column of text rather than as a
      // log with a time axis.
      const top = document.createElement("div");
      top.className = "report-action-top";
      if (a.timestamp) {
        const ts = document.createElement("span");
        ts.className = "report-action-time";
        ts.textContent = relativeAge(a.timestamp);
        top.appendChild(ts);
      }
      const action = document.createElement("span");
      action.className = "report-action-name";
      // `budget_update` reaches the operator as "Budget update". The same
      // helper the flag chips use, so a wire token is spelled one way on this
      // page — and it is the ONLY transformation: an action mureo has no
      // words for keeps its own, rather than being renamed by guesswork.
      action.textContent = humanizeFlagWords(a.action || "");
      top.appendChild(action);
      if (a.platform) {
        const platform = document.createElement("span");
        platform.className = "report-action-platform";
        platform.textContent = a.platform;
        top.appendChild(platform);
      }
      li.appendChild(top);
      if (a.summary) {
        const summary = document.createElement("p");
        summary.className = "report-action-summary";
        summary.textContent = String(a.summary);
        li.appendChild(summary);
      }
      // What is still OWED about this change, under the sentence it is about.
      const meta = document.createElement("div");
      meta.className = "report-action-meta";
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
    // Shared with dashboard_reports.js so tier (2)'s change cards and tier
    // (3)'s platform cards colour one movement one way (#691 phase 4).
    REPORTS_CHANGE_TONE: REPORTS_CHANGE_TONE,
    changeTone: changeTone,
    buildDeltaElement: buildDeltaElement,
    buildMetricSparkline: buildMetricSparkline,
    appendTrend: appendTrend,
    buildStaleFiguresElement: buildStaleFiguresElement,
    staleAggregateFiguresText: staleAggregateFiguresText,
    clientKpiCell: clientKpiCell,
    buildReportCard: buildReportCard,
    buildReportFlagRow: buildReportFlagRow,
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
