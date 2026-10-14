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
// below so the documentation can state it.
//
// Writer text (titles, rationales, reasons, notes) is untrusted: it goes on
// the page through `textContent` only, with markdown emphasis stripped by
// the shared display helper.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_OPS_HISTORY_SECTION`. Loads AFTER
// dashboard_reports_detail.js and BEFORE dashboard_reports_cards.js and
// dashboard_reports.js, which resolve it per call.

(function () {
  "use strict";

  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  const DISPLAY = window.MUREO_REPORTS_DISPLAY;
  if (!REPORTS_SHARED || !DISPLAY) {
    throw new Error(
      "dashboard_ops_history_section.js needs MUREO_DASHBOARD_REPORTS_STATE " +
        "and MUREO_REPORTS_DISPLAY — load dashboard_reports_state.js and " +
        "reports_display.js BEFORE dashboard_ops_history_section.js"
    );
  }
  const formatNumber = REPORTS_SHARED.formatNumber;
  const humanizeFlagWords = REPORTS_SHARED.humanizeFlagWords;
  const reportsPlatformLabels = REPORTS_SHARED.reportsPlatformLabels;

  const FEED_URL = "/api/reports/ops-history";

  //: A decision whose rationale is shorter than this many characters (after
  //: markdown emphasis is stripped and whitespace trimmed) is marked "weak
  //: rationale". Twenty characters is about one short clause: enough for
  //: "CPA above target for two weeks", not for "Too high.".
  const WEAK_RATIONALE_MIN_CHARS = 20;

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
  const VERDICTS = ["regressed", "inconclusive", "improved"];
  const COLUMNS = [
    "col_date",
    "col_title",
    "col_platform",
    "col_state",
    "col_metric",
    "col_verdict",
  ];
  const EVAL_COLUMNS = [
    "eval_metric",
    "eval_before",
    "eval_after",
    "eval_delta",
    "eval_verdict",
    "eval_note",
  ];
  const NO_VALUE = "—";
  //: The longest a single before / after value is printed. A nested value is
  //: shown as JSON and cut here, so one deep parameter cannot fill the row.
  const VALUE_TEXT_MAX_CHARS = 80;
  const ARROW = " → ";
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

  function t(key, params) {
    return MUREO.t("ops_history_section." + key, params);
  }

  function el(tag, className, textContent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textContent != null) node.textContent = textContent;
    return node;
  }

  function clean(value) {
    return typeof value === "string" ? DISPLAY.stripEmphasis(value) : null;
  }

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
    const acts = item && Array.isArray(item.actions) ? item.actions : [];
    for (let i = 0; i < acts.length; i++) {
      const table = acts[i] && acts[i].evaluation && acts[i].evaluation.table;
      if (table && Array.isArray(table.metrics) && table.metrics.length) return table.metrics;
    }
    return [];
  }

  /** The row the list states: the first expected metric, else the primary. */
  function primaryMetric(item) {
    const rows = evaluationRows(item);
    const expected = item && item.decision && Array.isArray(item.decision.expected)
      ? item.decision.expected
      : [];
    const wanted = expected.length && expected[0] ? String(expected[0].metric || "") : "";
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

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function formatValue(value) {
    if (!isNumber(value)) return NO_VALUE;
    if (Math.abs(value) >= 100) return formatNumber(Math.round(value));
    return formatNumber(Math.round(value * 100) / 100);
  }

  function deltaText(pct) {
    if (!isNumber(pct)) return "";
    const rounded = Math.round(Math.abs(pct));
    if (rounded === 0) return "±0%";
    return (pct > 0 ? "▲" : "▼") + rounded + "%";
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

  function verdictLabel(verdict) {
    return t("verdict_" + verdict);
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

  // --- the expanded detail -------------------------------------------------

  function block(titleKey, attr) {
    const wrap = el("div", "ops-history-detail-block");
    if (attr) wrap.setAttribute(attr, "");
    wrap.appendChild(el("h4", null, t(titleKey)));
    return wrap;
  }

  function buildRationale(decision) {
    const wrap = block("rationale");
    const text = decision ? clean(decision.rationale) : null;
    const p = el("p", text ? null : "is-muted", text || t("rationale_missing"));
    p.setAttribute("data-ops-history-rationale", "");
    wrap.appendChild(p);
    return wrap;
  }

  function expectedText(entry) {
    const parts = [humanizeFlagWords(String(entry.metric || ""))];
    if (entry.direction) parts.push(t("direction_" + entry.direction));
    if (isNumber(entry.target)) {
      parts.push(t("expected_target", { value: formatValue(entry.target) }));
    }
    if (isNumber(entry.horizon_days)) parts.push(t("expected_horizon", { n: entry.horizon_days }));
    return parts.join(" · ");
  }

  function buildExpected(decision) {
    const wrap = block("expected", "data-ops-history-expected");
    const entries = decision && Array.isArray(decision.expected) ? decision.expected : [];
    if (!entries.length) {
      wrap.appendChild(el("p", "is-muted", t("expected_none")));
      return wrap;
    }
    const list = el("ul", "ops-history-expected");
    entries.forEach(function (entry) {
      if (entry && typeof entry === "object") list.appendChild(el("li", null, expectedText(entry)));
    });
    wrap.appendChild(list);
    return wrap;
  }

  function bounded(text) {
    if (text.length <= VALUE_TEXT_MAX_CHARS) return text;
    return text.slice(0, VALUE_TEXT_MAX_CHARS - 1) + "…";
  }

  function valueText(v) {
    if (isNumber(v)) return formatNumber(v);
    if (v && typeof v === "object") return bounded(JSON.stringify(v));
    return bounded(String(v));
  }

  function valuesText(values) {
    if (!values || typeof values !== "object") return NO_VALUE;
    const pairs = Object.keys(values).map(function (key) {
      return key + ": " + valueText(values[key]);
    });
    return pairs.length ? pairs.join(", ") : NO_VALUE;
  }

  function operationLine(act) {
    const li = el("li", "ops-history-operation");
    const name = clean(act.display_title) || humanizeFlagWords(String(act.action || ""));
    const target = [act.entity_type, act.entity_id || act.campaign_id].filter(Boolean).join(" ");
    li.appendChild(el("span", "ops-history-op-name", name + (target ? " (" + target + ")" : "")));
    const moved = valuesText(act.before) + ARROW + valuesText(act.after);
    li.appendChild(el("span", "ops-history-op-values", " " + moved));
    const reason = clean(act.reason);
    if (reason) li.appendChild(el("p", "ops-history-op-reason", reason));
    if (act.observation_due) {
      const due = t("observation_due", { date: act.observation_due });
      li.appendChild(el("p", "ops-history-op-due", due));
    }
    return li;
  }

  function buildOperations(item) {
    const wrap = block("operations", "data-ops-history-operations");
    const acts = Array.isArray(item.actions) ? item.actions : [];
    if (!acts.length) {
      const params = item.decision && item.decision.applied_params;
      const text = params ? t("params_sent") + " " + valuesText(params) : t("operations_none");
      wrap.appendChild(el("p", "is-muted", text));
      return wrap;
    }
    const list = el("ul", "ops-history-operations");
    acts.forEach(function (act) {
      if (act && typeof act === "object") list.appendChild(operationLine(act));
    });
    wrap.appendChild(list);
    return wrap;
  }

  function evaluationRow(row) {
    const tr = el("tr");
    const verdict = VERDICTS.indexOf(row.verdict) !== -1 ? verdictLabel(row.verdict) : NO_VALUE;
    [
      humanizeFlagWords(String(row.metric || "")),
      formatValue(row.before),
      formatValue(row.after),
      deltaText(row.delta_pct) || NO_VALUE,
      verdict,
      clean(row.note) || "",
    ].forEach(function (text) {
      tr.appendChild(el("td", null, text));
    });
    return tr;
  }

  function buildEvaluation(item) {
    const rows = evaluationRows(item);
    if (!rows.length) return null;
    const wrap = block("eval_title");
    const parts = headedTable("ops-history-eval", EVAL_COLUMNS, false);
    parts.table.setAttribute("data-ops-history-evaluation", "");
    rows.forEach(function (row) {
      if (row && typeof row === "object") parts.body.appendChild(evaluationRow(row));
    });
    wrap.appendChild(parts.table);
    return wrap;
  }

  function skippedLine(item) {
    const act = (item.actions || []).find(function (a) {
      return a && a.skipped_reason;
    });
    if (!act) return null;
    const reason = humanizeFlagWords(String(act.skipped_reason));
    const p = el("p", "ops-history-skipped", t("skipped", { reason: reason }));
    p.setAttribute("data-ops-history-skipped", "");
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

  /** A table with its header row in a thead, and the tbody to fill. */
  function headedTable(className, keys, expandColumn) {
    const table = el("table", "reports-breakdown-table " + className);
    const thead = el("thead");
    const head = el("tr");
    keys.forEach(function (key) {
      head.appendChild(el("th", null, t(key)));
    });
    if (expandColumn) head.appendChild(el("th", "ops-history-expand-cell"));
    thead.appendChild(head);
    table.appendChild(thead);
    const body = el("tbody");
    table.appendChild(body);
    return { table: table, body: body };
  }

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
