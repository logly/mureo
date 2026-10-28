// dashboard_ops_history_detail.js — the expanded row of the ops history
// section (#849): the rationale, the expected effects, the operations sent,
// the reason a change was not evaluated and the evaluation table.
//
// Lifted whole out of dashboard_ops_history_section.js when that file reached
// its 800-line budget (#851). The section draws the row and decides what the
// expanded row holds; the blocks are built here. The small helpers both
// halves use (the `ops_history_section.` wording, the element builder, the
// number formats, the verdict vocabulary) are defined here once and bound by
// the section under their original names.
//
// NOTHING HERE JUDGES: every verdict and figure is the server's. Writer text
// goes on the page through `textContent` only, with markdown emphasis
// stripped by the shared display helper.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_OPS_HISTORY_DETAIL`. Loads AFTER
// dashboard_reports_state.js, reports_display.js and outcome_text.js (whose
// bindings it reads at load) and BEFORE dashboard_ops_history_section.js,
// which binds this file at load.

(function () {
  "use strict";

  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  const DISPLAY = window.MUREO_REPORTS_DISPLAY;
  // The evaluation table's wording (#894): one place for it, outcome_text.js.
  const OUTCOME = window.MUREO_OUTCOME_TEXT;
  if (!REPORTS_SHARED || !DISPLAY || !OUTCOME) {
    throw new Error(
      "dashboard_ops_history_detail.js needs MUREO_DASHBOARD_REPORTS_STATE, " +
        "MUREO_REPORTS_DISPLAY and MUREO_OUTCOME_TEXT — load dashboard_reports_state.js, " +
        "reports_display.js and outcome_text.js BEFORE dashboard_ops_history_detail.js"
    );
  }
  const formatNumber = REPORTS_SHARED.formatNumber;
  const humanizeFlagWords = REPORTS_SHARED.humanizeFlagWords;

  const VERDICTS = ["regressed", "inconclusive", "held", "improved"];
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

  // --- shared ------------------------------------------------------------

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

  /** The first evaluation table with rows among the item's changes, or null. */
  function evaluationTable(item) {
    const acts = item && Array.isArray(item.actions) ? item.actions : [];
    for (let i = 0; i < acts.length; i++) {
      const table = acts[i] && acts[i].evaluation && acts[i].evaluation.table;
      if (table && Array.isArray(table.metrics) && table.metrics.length) return table;
    }
    return null;
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

  function verdictLabel(verdict) {
    return t("verdict_" + verdict);
  }

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

  // #854: the external approval a change carried out, exactly as it was
  // stated (mureo verified nothing about it). Not run through clean():
  // emphasis stripping would change a reference such as REQ__1__x, and the
  // line is set as text, so nothing in a value is interpreted. Drawn only
  // when it is the three strings; anything else draws no line rather than a
  // broken one.
  function stated(value) {
    return typeof value === "string" && value.trim() ? value : null;
  }

  function approvalLine(approval) {
    if (!approval || typeof approval !== "object") return null;
    const name = stated(approval.approved_by);
    const reference = stated(approval.reference);
    const at = stated(approval.approved_at);
    if (!name || !reference || !at) return null;
    const text = t("approved_by", { name: name, date: at.slice(0, 10), reference: reference });
    const line = el("p", "ops-history-op-approval", text);
    line.setAttribute("data-ops-history-approval", "");
    return line;
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
    const approval = approvalLine(act.approval);
    if (approval) li.appendChild(approval);
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
      const approval = approvalLine(item.decision && item.decision.approval);
      if (approval) wrap.appendChild(approval);
      return wrap;
    }
    const list = el("ul", "ops-history-operations");
    acts.forEach(function (act) {
      if (act && typeof act === "object") list.appendChild(operationLine(act));
    });
    wrap.appendChild(list);
    return wrap;
  }

  // A role the table does not state (written before #888) adds nothing.
  function evaluationRow(row, table) {
    const tr = el("tr");
    const role = OUTCOME.rowRole(row, table);
    if (role) tr.setAttribute("data-role", role);
    const name = el("td", null, humanizeFlagWords(String(row.metric || "")));
    const said = VERDICTS.indexOf(row.verdict) !== -1 ? verdictLabel(row.verdict) : NO_VALUE;
    const verdict = el("td", "ops-history-eval-verdict", said);
    const primary = role === "primary" ? MUREO.t("outcome.role_primary") : null;
    if (primary) name.appendChild(el("span", "ops-history-eval-role", primary));
    const reference = role === "reference" ? MUREO.t("outcome.role_reference") : null;
    if (reference) verdict.appendChild(el("span", "ops-history-eval-reference", reference));
    const delta = deltaText(row.delta_pct) || NO_VALUE;
    const note = el("td", null, OUTCOME.noteText(row.note_parts) || clean(row.note) || "");
    const cell = function (text) { return el("td", null, text); };
    [name, cell(formatValue(row.before)), cell(formatValue(row.after)), cell(delta), verdict, note]
      .forEach(function (td) { tr.appendChild(td); });
    return tr;
  }

  function buildEvaluation(item) {
    const table = evaluationTable(item);
    if (!table) return null;
    const wrap = block("eval_title");
    const parts = headedTable("ops-history-eval", EVAL_COLUMNS, false);
    parts.table.setAttribute("data-ops-history-evaluation", "");
    table.metrics.forEach(function (row) {
      if (row && typeof row === "object") parts.body.appendChild(evaluationRow(row, table));
    });
    wrap.appendChild(parts.table);
    if (typeof table.reason === "string" && table.reason) {
      const reason = el("p", "ops-history-eval-reason", OUTCOME.reasonText(table.reason));
      reason.setAttribute("data-ops-history-eval-reason", "");
      wrap.appendChild(reason);
    }
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

  const api = {
    VERDICTS: VERDICTS,
    NO_VALUE: NO_VALUE,
    ARROW: ARROW,
    t: t,
    el: el,
    clean: clean,
    isNumber: isNumber,
    formatValue: formatValue,
    deltaText: deltaText,
    verdictLabel: verdictLabel,
    evaluationTable: evaluationTable,
    headedTable: headedTable,
    buildRationale: buildRationale,
    buildExpected: buildExpected,
    buildOperations: buildOperations,
    skippedLine: skippedLine,
    buildEvaluation: buildEvaluation,
  };
  window.MUREO_DASHBOARD_OPS_HISTORY_DETAIL = api;
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
