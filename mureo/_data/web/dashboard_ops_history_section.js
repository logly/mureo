// dashboard_ops_history_section.js — the ops history on a client's detail
// view, and the one line it puts on each client card (#849).
//
// The detail section answers "what did we change, why, and how did it turn
// out" for one client: one row per change (or decision), worst outcome
// first, each row opening onto the reasoning, the expected effect, the
// operations sent and the before/after table the evaluator wrote. It is fed
// by `GET /api/reports/ops-history` and is NOT in the DOM while the
// workspace's ops history is off — no empty frame, no "turned off" notice.
//
// NOTHING HERE JUDGES. Every verdict, state and figure is the server's; this
// file only orders, filters and prints them. The one call it makes on its
// own is the "weak rationale" chip, and its threshold is the named constant
// below so the documentation can state it. The "possible duplicate" chip
// (#851) is the server's `decision.possible_duplicate_of`, only shown.
//
// Writer text (titles, rationales, reasons, notes) is untrusted: it goes on
// the page through `textContent` only, with markdown emphasis stripped by
// the shared display helper.
//
// The expanded row's blocks are built by dashboard_ops_history_detail.js
// (#851), which also defines the helpers both files use.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_OPS_HISTORY_SECTION`. Loads AFTER
// dashboard_reports_detail.js and dashboard_ops_history_detail.js and BEFORE
// dashboard_reports_cards.js and dashboard_reports.js, which resolve it per
// call.

(function () {
  "use strict";

  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  // The expanded row's builders and the helpers both files use (#851),
  // bound by their original names.
  const DETAIL = window.MUREO_DASHBOARD_OPS_HISTORY_DETAIL;
  if (!REPORTS_SHARED || !DETAIL) {
    throw new Error(
      "dashboard_ops_history_section.js needs MUREO_DASHBOARD_REPORTS_STATE and " +
        "MUREO_DASHBOARD_OPS_HISTORY_DETAIL — load dashboard_reports_state.js and " +
        "dashboard_ops_history_detail.js BEFORE dashboard_ops_history_section.js"
    );
  }
  const formatNumber = REPORTS_SHARED.formatNumber;
  const humanizeFlagWords = REPORTS_SHARED.humanizeFlagWords;
  const reportsPlatformLabels = REPORTS_SHARED.reportsPlatformLabels;
  const VERDICTS = DETAIL.VERDICTS;
  const NO_VALUE = DETAIL.NO_VALUE;
  const ARROW = DETAIL.ARROW;
  const t = DETAIL.t;
  const el = DETAIL.el;
  const clean = DETAIL.clean;
  const isNumber = DETAIL.isNumber;
  const formatValue = DETAIL.formatValue;
  const deltaText = DETAIL.deltaText;
  const verdictLabel = DETAIL.verdictLabel;
  const evaluationTable = DETAIL.evaluationTable;
  const headedTable = DETAIL.headedTable;
  const buildRationale = DETAIL.buildRationale;
  const buildExpected = DETAIL.buildExpected;
  const buildOperations = DETAIL.buildOperations;
  const skippedLine = DETAIL.skippedLine;
  const buildEvaluation = DETAIL.buildEvaluation;

  const FEED_URL = "/api/reports/ops-history";

  //: A decision whose rationale is shorter than this many characters (after
  //: markdown emphasis is stripped and whitespace trimmed) is marked "weak
  //: rationale". Twenty characters is about one short clause: enough for
  //: "CPA above target for two weeks", not for "Too high.".
  const WEAK_RATIONALE_MIN_CHARS = 20;

  //: The server's window for a possible duplicate (#851,
  //: mureo/context/ops_history_duplicates.py DUPLICATE_DECISION_WINDOW): a
  //: change on the same target recorded as its own decision within this many
  //: hours after a decision recorded on its own. Only stated, never applied.
  const DUPLICATE_DECISION_WINDOW_HOURS = 24;

  //: The period choices: that many calendar days ending on the server's
  //: today, today included (the server's own window rule).
  const PERIOD_DAYS = [7, 30, 90];
  //: The default period — the server's default window, so the first fetch
  //: carries no dates and the client card's counts cover the same days.
  const DEFAULT_PERIOD_DAYS = 30;

  const STATES = [
    "proposed",
    "adopted",
    "executed",
    "observing",
    "evaluated",
    "skipped",
    "rejected",
    "deferred",
  ];
  const COLUMNS = [
    "col_date",
    "col_title",
    "col_platform",
    "col_state",
    "col_metric",
    "col_verdict",
  ];
  const DAY_MS = 86400000;

  //: What the view holds between a fetch and a filter change. Replaced, not
  //: mutated, field by field.
  let view = {
    seq: 0,
    client: null,
    labels: {},
    period: DEFAULT_PERIOD_DAYS,
    filters: { platform: "", state: "", verdict: "" },
    today: null,
    body: null,
  };

  // --- pure ----------------------------------------------------------------

  function firstAction(item) {
    return item && Array.isArray(item.actions) && item.actions.length ? item.actions[0] : null;
  }

  function itemPlatform(item) {
    const decision = item && item.decision;
    const act = firstAction(item);
    return (decision && decision.platform) || (act && act.platform) || "";
  }

  // The item's date by the server's own rule (ops_history_view.item_timestamp):
  // the decision's first record, else the uncovered change's timestamp — so
  // the date shown is the one the period window was applied to.
  function itemStamp(item) {
    const decision = item && item.decision;
    const act = firstAction(item);
    return (decision && decision.recorded_at) || (act && act.timestamp) || "";
  }

  /** The verdict a row shows: the server's, or inconclusive once evaluated. */
  function verdictOf(item) {
    if (item && VERDICTS.indexOf(item.verdict) !== -1) return item.verdict;
    return item && item.state === "evaluated" ? "inconclusive" : null;
  }

  function groupRank(item) {
    const verdict = verdictOf(item);
    if (verdict === "regressed") return 0;
    if (item && item.state === "observing") return 1;
    return verdict === "improved" ? 3 : 2;
  }

  /** Regressed, observing, the rest, improved; newest first in each. */
  function orderItems(items) {
    const keyed = (Array.isArray(items) ? items : []).map(function (item, at) {
      const time = Date.parse(itemStamp(item));
      return { item: item, at: at, rank: groupRank(item), time: isNaN(time) ? 0 : time };
    });
    keyed.sort(function (a, b) {
      return a.rank - b.rank || b.time - a.time || a.at - b.at;
    });
    return keyed.map(function (k) {
      return k.item;
    });
  }

  function isWeakRationale(item) {
    if (!item || !item.decision) return false;
    const text = clean(item.decision.rationale) || "";
    return text.trim().length < WEAK_RATIONALE_MIN_CHARS;
  }

  /** The decision the server says this one may duplicate (#851), or null. */
  function duplicateOf(item) {
    const id = item && item.decision && item.decision.possible_duplicate_of;
    return typeof id === "string" && id ? id : null;
  }

  function filterItems(items, filters) {
    const f = filters || {};
    return (Array.isArray(items) ? items : []).filter(function (item) {
      if (f.platform && itemPlatform(item) !== f.platform) return false;
      if (f.state && item.state !== f.state) return false;
      return !f.verdict || verdictOf(item) === f.verdict;
    });
  }

  function platformsOf(items) {
    const seen = {};
    (Array.isArray(items) ? items : []).forEach(function (item) {
      const key = itemPlatform(item);
      if (key) seen[key] = true;
    });
    return Object.keys(seen).sort();
  }

  function evaluationRows(item) {
    const table = evaluationTable(item);
    return table ? table.metrics : [];
  }

  /** The row the list states: the expected metric marked primary (a legacy
   *  declaration without one: the first), else the table's primary row. */
  function primaryMetric(item) {
    const rows = evaluationRows(item);
    const expected = item && item.decision && Array.isArray(item.decision.expected)
      ? item.decision.expected
      : [];
    const declared = expected.find(function (e) { return e && e.primary === true; }) || expected[0];
    const wanted = declared ? String(declared.metric || "") : "";
    const pick =
      rows.find(function (r) {
        return wanted && r && String(r.metric).toLowerCase() === wanted.toLowerCase();
      }) ||
      rows.find(function (r) {
        return r && r.role === "primary";
      }) ||
      rows[0];
    return pick || null;
  }

  function metricText(row) {
    if (!row || !isNumber(row.before) || !isNumber(row.after)) return NO_VALUE;
    const head = humanizeFlagWords(String(row.metric || "")) + " ";
    const delta = deltaText(row.delta_pct);
    const moved = formatValue(row.before) + ARROW + formatValue(row.after);
    return head + moved + (delta ? " " + delta : "");
  }

  function shiftDay(day, days) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day || ""));
    if (!m) return null;
    const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) - days * DAY_MS;
    return new Date(ms).toISOString().slice(0, 10);
  }

  function feedUrl(client, period, today) {
    const params = [];
    if (client) params.push("client=" + encodeURIComponent(client));
    const since =
      period !== DEFAULT_PERIOD_DAYS && today ? shiftDay(today, period - 1) : null;
    if (since) params.push("since=" + since, "until=" + today);
    return FEED_URL + (params.length ? "?" + params.join("&") : "");
  }

  /** The client card's line, or null while off or when nothing changed. */
  function opsHistoryAggregateText(summary) {
    const ops = summary && summary.ops_history;
    if (!ops || ops.enabled !== true || !isNumber(ops.changes) || ops.changes < 1) return null;
    function count(key) {
      return formatNumber(isNumber(ops[key]) ? ops[key] : 0);
    }
    return MUREO.t("ops_history_section.aggregate", {
      days: count("window_days"),
      n: count("changes"),
      improved: count("improved"),
      regressed: count("regressed"),
      held: count("held"),
      inconclusive: count("inconclusive"),
      observing: count("observing"),
    });
  }

  // --- the header ----------------------------------------------------------

  function buildSelect(attr, labelKey, options, value, onChange) {
    const wrap = el("label", "ops-history-filter");
    wrap.appendChild(el("span", "ops-history-filter-label", t(labelKey)));
    const select = el("select", "reports-platform-select ops-history-select");
    select.setAttribute(attr, "");
    options.forEach(function (opt) {
      const option = el("option", null, opt.label);
      option.value = opt.value;
      select.appendChild(option);
    });
    select.value = value;
    select.addEventListener("change", function () {
      onChange(select.value);
    });
    wrap.appendChild(select);
    return wrap;
  }

  function withAll(values, label) {
    return [{ value: "", label: t("all") }].concat(
      values.map(function (v) {
        return { value: v, label: label(v) };
      })
    );
  }

  function buildFilters(items) {
    const bar = el("div", "ops-history-filters");
    const periods = PERIOD_DAYS.map(function (n) {
      return { value: String(n), label: t("period_days", { n: n }) };
    });
    bar.appendChild(
      buildSelect("data-ops-history-period", "period_label", periods, String(view.period), onPeriod)
    );
    const platformLabel = function (key) {
      return view.labels[key] || key;
    };
    const filters = [
      [
        "data-ops-history-platform",
        "platform_label",
        "platform",
        platformsOf(items),
        platformLabel,
      ],
      ["data-ops-history-state", "state_label", "state", STATES, stateLabel],
      ["data-ops-history-verdict", "verdict_label", "verdict", VERDICTS, verdictLabel],
    ];
    filters.forEach(function (f) {
      const opts = withAll(f[3], f[4]);
      bar.appendChild(buildSelect(f[0], f[1], opts, view.filters[f[2]], onFilter(f[2])));
    });
    return bar;
  }

  function stateLabel(state) {
    return t("state_" + state);
  }

  function buildHeader(items) {
    const head = el("div", "ops-history-head");
    head.appendChild(el("h3", null, t("title")));
    const note = el("p", "ops-history-note", t("note"));
    note.setAttribute("data-ops-history-note", "");
    head.appendChild(note);
    head.appendChild(buildFilters(items));
    return head;
  }

  // --- one row -------------------------------------------------------------

  // A badge only for a verdict; an item not judged yet gets a plain dash, so
  // "no verdict" never looks like a fourth verdict.
  function verdictBadge(verdict) {
    if (!verdict) return el("span", "ops-history-no-verdict", NO_VALUE);
    return el("span", "ops-history-verdict is-" + verdict, verdictLabel(verdict));
  }

  function titleCell(item) {
    const td = el("td", "ops-history-title-cell");
    const decision = item.decision;
    const title = decision ? clean(decision.title) : null;
    const span = el("span", "ops-history-title");
    span.setAttribute("data-ops-history-title", "");
    if (!decision) span.classList.add("is-muted");
    span.textContent = decision ? title || NO_VALUE : t("no_decision");
    td.appendChild(span);
    if (isWeakRationale(item)) {
      const chip = el("span", "report-chip is-warn ops-history-weak", t("weak_rationale"));
      chip.setAttribute("data-ops-history-weak-chip", "");
      td.appendChild(chip);
    }
    if (duplicateOf(item)) {
      const chip = el("span", "report-chip is-info ops-history-duplicate", t("possible_duplicate"));
      chip.setAttribute("data-ops-history-duplicate-chip", "");
      td.appendChild(chip);
    }
    return td;
  }

  function expandCell() {
    const td = el("td", "ops-history-expand-cell");
    const btn = el("button", "ops-history-expand", "▸");
    btn.type = "button";
    btn.setAttribute("data-ops-history-expand", "");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-label", t("expand"));
    td.appendChild(btn);
    return td;
  }

  function buildRow(item, at) {
    const tr = el("tr", "ops-history-row");
    tr.setAttribute("data-ops-history-row", "");
    const decision = item.decision;
    tr.setAttribute("data-decision", (decision && decision.decision_id) || "change-" + at);
    if (isWeakRationale(item)) tr.setAttribute("data-ops-history-weak", "");
    if (duplicateOf(item)) tr.setAttribute("data-ops-history-duplicate", "");
    tr.appendChild(el("td", "ops-history-date", itemStamp(item).slice(0, 10) || NO_VALUE));
    tr.appendChild(titleCell(item));
    const platform = itemPlatform(item);
    const platformText = platform ? view.labels[platform] || platform : NO_VALUE;
    tr.appendChild(el("td", "ops-history-nowrap", platformText));
    tr.appendChild(el("td", "ops-history-nowrap", item.state ? stateLabel(item.state) : NO_VALUE));
    const metric = el("td", "ops-history-metric", metricText(primaryMetric(item)));
    metric.setAttribute("data-ops-history-metric", "");
    tr.appendChild(metric);
    const verdictTd = el("td");
    verdictTd.appendChild(verdictBadge(verdictOf(item)));
    tr.appendChild(verdictTd);
    tr.appendChild(expandCell());
    return tr;
  }

  // --- the expanded detail (its blocks: dashboard_ops_history_detail.js) ---

  // #851: said, never acted on. No link to the other decision: the operator
  // reads both rows and decides.
  function duplicateNote(item) {
    const id = duplicateOf(item);
    if (!id) return null;
    const text = t("possible_duplicate_detail", { id: id, hours: DUPLICATE_DECISION_WINDOW_HOURS });
    const p = el("p", "ops-history-duplicate-note", text);
    p.setAttribute("data-ops-history-duplicate-note", "");
    return p;
  }

  function buildDetail(item) {
    const tr = el("tr", "ops-history-detail");
    tr.setAttribute("data-ops-history-detail", "");
    tr.hidden = true;
    const td = el("td", "ops-history-detail-cell");
    td.setAttribute("colspan", String(COLUMNS.length + 1));
    if (item.rolled_back) {
      const chip = el("span", "report-chip is-danger", t("rolled_back"));
      chip.setAttribute("data-ops-history-rolled-back", "");
      td.appendChild(chip);
    }
    [
      duplicateNote(item),
      buildRationale(item.decision),
      buildExpected(item.decision),
      buildOperations(item),
      skippedLine(item),
      buildEvaluation(item),
    ].forEach(function (node) {
      if (node) td.appendChild(node);
    });
    tr.appendChild(td);
    return tr;
  }

  function wireToggle(row, detail) {
    const btn = row.querySelector("[data-ops-history-expand]");
    row.addEventListener("click", function () {
      detail.hidden = !detail.hidden;
      row.classList.toggle("is-open", !detail.hidden);
      if (btn) btn.setAttribute("aria-expanded", detail.hidden ? "false" : "true");
    });
  }

  // --- the table -----------------------------------------------------------

  function buildTable(items) {
    const parts = headedTable("ops-history-table", COLUMNS, true);
    items.forEach(function (item, at) {
      const row = buildRow(item, at);
      const detail = buildDetail(item);
      wireToggle(row, detail);
      parts.body.appendChild(row);
      parts.body.appendChild(detail);
    });
    return parts.table;
  }

  function drawRows(slot) {
    slot.textContent = "";
    const all = view.body.items;
    if (!all.length) {
      const empty = el("p", "ops-history-empty", t("empty"));
      empty.setAttribute("data-ops-history-empty", "");
      slot.appendChild(empty);
      return;
    }
    const shown = orderItems(filterItems(all, view.filters));
    if (!shown.length) {
      const none = el("p", "ops-history-empty", t("no_match"));
      none.setAttribute("data-ops-history-no-match", "");
      slot.appendChild(none);
      return;
    }
    slot.appendChild(buildTable(shown));
  }

  // --- the section ---------------------------------------------------------

  function currentSection() {
    return document.querySelector("[data-ops-history-section]");
  }

  function removeSection() {
    const node = currentSection();
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  function placeSection(section) {
    const anchor = document.querySelector("[data-reports-actions]");
    if (!anchor || !anchor.parentNode) return false;
    removeSection();
    anchor.parentNode.insertBefore(section, anchor.nextSibling);
    return true;
  }

  function newSection() {
    const section = el("section", "dashboard-reports-block ops-history-section");
    section.setAttribute("data-ops-history-section", "");
    return section;
  }

  function drawSection(focusPeriod) {
    const body = view.body;
    const section = newSection();
    section.appendChild(buildHeader(body.items));
    const slot = el("div", "ops-history-rows");
    slot.setAttribute("data-ops-history-rows", "");
    section.appendChild(slot);
    drawRows(slot);
    if (!placeSection(section) || !focusPeriod) return;
    const period = section.querySelector("[data-ops-history-period]");
    if (period) period.focus();
  }

  function onFilter(name) {
    return function (value) {
      const filters = Object.assign({}, view.filters);
      filters[name] = value;
      view = Object.assign({}, view, { filters: filters });
      const slot = document.querySelector("[data-ops-history-rows]");
      if (slot && view.body) drawRows(slot);
    };
  }

  function onPeriod(value) {
    const days = Number(value);
    if (PERIOD_DAYS.indexOf(days) === -1 || days === view.period) return;
    view = Object.assign({}, view, { period: days });
    load(true);
  }

  function validBody(body) {
    if (!body || typeof body !== "object" || body.enabled !== true) return null;
    const items = Array.isArray(body.items)
      ? body.items.filter(function (item) {
          return item && typeof item === "object";
        })
      : [];
    return Object.assign({}, body, { items: items });
  }

  async function load(focusPeriod) {
    view = Object.assign({}, view, { seq: view.seq + 1 });
    const seq = view.seq;
    const url = feedUrl(view.client, view.period, view.today);
    let body;
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      body = await res.json();
    } catch (err) {
      // Whether ops history is even on is unknown here, and a workspace with
      // it off must have no section at all — so none is drawn.
      if (seq !== view.seq) return;
      view = Object.assign({}, view, { body: null });
      removeSection();
      console.warn("ops history could not be loaded", err);
      return;
    }
    if (seq !== view.seq) return;
    const usable = validBody(body);
    const today =
      usable && typeof usable.server_today === "string" ? usable.server_today : view.today;
    view = Object.assign({}, view, { body: usable, today: today });
    if (usable) drawSection(focusPeriod);
    else removeSection();
  }

  /** Draw (or remove) the section for `client`, under the recent actions. */
  function renderOpsHistorySection(client, summary) {
    const slug = client || (summary && typeof summary.client === "string" ? summary.client : null);
    if (slug !== view.client) {
      view = Object.assign({}, view, {
        client: slug,
        period: DEFAULT_PERIOD_DAYS,
        filters: { platform: "", state: "", verdict: "" },
        today: null,
      });
    }
    view = Object.assign({}, view, { labels: reportsPlatformLabels(summary) });
    return load(false);
  }

  /** Take the section off the page and drop any fetch still in flight. */
  function clearOpsHistorySection() {
    view = Object.assign({}, view, { seq: view.seq + 1, body: null });
    removeSection();
  }

  const api = {
    WEAK_RATIONALE_MIN_CHARS: WEAK_RATIONALE_MIN_CHARS,
    DUPLICATE_DECISION_WINDOW_HOURS: DUPLICATE_DECISION_WINDOW_HOURS,
    PERIOD_DAYS: PERIOD_DAYS,
    DEFAULT_PERIOD_DAYS: DEFAULT_PERIOD_DAYS,
    orderItems: orderItems,
    primaryMetric: primaryMetric,
    isWeakRationale: isWeakRationale,
    filterItems: filterItems,
    opsHistoryAggregateText: opsHistoryAggregateText,
    renderOpsHistorySection: renderOpsHistorySection,
    clearOpsHistorySection: clearOpsHistorySection,
  };
  window.MUREO_DASHBOARD_OPS_HISTORY_SECTION = api;
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
