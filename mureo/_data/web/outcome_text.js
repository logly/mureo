// outcome_text.js — an outcome evaluation, in the operator's words (#894).
//
// The server stores the evaluation table as data plus English working notes:
// a reason CODE (`insufficient_volume`), a one-line English summary, and a
// row `note` such as `insufficient_volume; lower_is_better; -20%`. That is
// right for the agent that reads it next and wrong for a person. This file is
// the ONE place the screen turns those into sentences, so the evaluation
// table and the action rows cannot say the same verdict two ways.
//
// NOTHING HERE JUDGES. The verdict, the reason and the parts of a note are
// the server's: `note_parts` is read on the server from the very templates
// the evaluator writes with (mureo/analysis/outcome_note.py). A note the
// server could not read arrives with `note_parts: null`, and `noteText`
// answers `null` so the caller shows the stored string instead.
//
// Pure: no DOM, nothing stored. Keys are spelled out where they are fixed;
// the ones built from a value (`outcome.reason_<code>`,
// `outcome.note_<direction>`, the reused `ops_history_section.verdict_<v>`
// and `ops_history_section.direction_<d>`) are each picked from the closed
// lists below, and the Python suite checks every such key is translated.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_OUTCOME_TEXT`. Loads AFTER reports_format.js and BEFORE
// reports_display.js and dashboard_ops_history_section.js; reads
// `MUREO_REPORTS_FORMAT` at call time and holds no copy of it.

(function () {
  "use strict";

  //: The verdicts the evaluator writes (`Verdict` in outcome_eval.py).
  const VERDICTS = ["improved", "regressed", "held", "inconclusive"];

  //: Why a result is inconclusive (`OUTCOME_REASONS` in outcome_eval.py).
  const REASONS = [
    "no_primary_metric",
    "insufficient_volume",
    "volume_unknown",
    "period_unknown",
    "zero_baseline",
    "target_not_reached",
    "no_change",
  ];
  const NO_PRIMARY_METRIC = "no_primary_metric";

  //: The words a directional row's note names (`NOTE_DIRECTION_WORDS`).
  const SIDES = ["lower_is_better", "higher_is_better"];

  //: A declared effect's directions (`EXPECTED_DIRECTIONS` in expected.py).
  const DIRECTIONS = ["up", "down", "hold"];

  // reports_format.js's number and metric-name vocabulary, read off the page
  // at CALL time, the way reports_display.js reads it: the page's <script>
  // order is the only thing that guarantees the other module is there.
  function format() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_FORMAT : null;
    if (!api) {
      throw new Error(
        "outcome_text.js needs MUREO_REPORTS_FORMAT — load " +
          "reports_format.js BEFORE outcome_text.js"
      );
    }
    return api;
  }

  // Same names, same meaning as reports_display.js: each file is a private
  // IIFE and there is no shared module to import them from.
  function text(value) {
    return typeof value === "string" && value.trim() ? value : null;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  /** A reason code as one sentence; an unknown code comes back as it is. */
  function reasonText(code) {
    return REASONS.indexOf(code) !== -1 ? MUREO.t("outcome.reason_" + code) : code;
  }

  /**
   * The verdict of an evaluation as one sentence, or `null`.
   *
   * `{overall, primary, reason}` is what the table states. With a primary the
   * sentence names it; without one it says no primary metric could be judged
   * (the evaluator's own rule, `outcome_summary`). A reason follows the
   * verdict, after `outcome.summary_sep` (a space in English, nothing in
   * Japanese). `null` for a verdict this screen does not know: the caller
   * keeps what it showed before.
   */
  function summaryText(evaluation) {
    const e = evaluation && typeof evaluation === "object" ? evaluation : {};
    if (VERDICTS.indexOf(e.overall) === -1) return null;
    const verdict = MUREO.t("ops_history_section.verdict_" + e.overall);
    const primary = text(e.primary);
    const head = primary
      ? MUREO.t("outcome.summary", {
          metric: format().humanizeFlagWords(primary),
          verdict: verdict,
        })
      : MUREO.t("outcome.summary_no_primary", { verdict: verdict });
    const reason = text(e.reason) || (primary ? null : NO_PRIMARY_METRIC);
    return reason ? head + MUREO.t("outcome.summary_sep") + reasonText(reason) : head;
  }

  function bandText(key, pct) {
    return MUREO.t(key, { pct: format().formatNumber(pct) });
  }

  /** What the note's `kind` says, or `null` for a kind this file does not know. */
  function kindText(parts) {
    if (parts.kind === "band") {
      return isNumber(parts.noise_pct) ? bandText("outcome.note_band", parts.noise_pct) : null;
    }
    if (parts.kind === "direction") {
      const known = SIDES.indexOf(parts.direction) !== -1;
      return known ? MUREO.t("outcome.note_" + parts.direction) : null;
    }
    if (parts.kind === "neutral") return MUREO.t("outcome.note_neutral");
    if (parts.kind === "zero_baseline") return MUREO.t("outcome.note_zero_baseline");
    if (parts.kind !== "expected" || DIRECTIONS.indexOf(parts.direction) === -1) return null;
    const direction = MUREO.t("ops_history_section.direction_" + parts.direction);
    return MUREO.t("outcome.note_expected", { direction: direction });
  }

  function periodText(perDay, rawTotals) {
    if (perDay && isNumber(perDay.before_days) && isNumber(perDay.after_days)) {
      return MUREO.t("outcome.note_per_day", {
        before: format().formatNumber(perDay.before_days),
        after: format().formatNumber(perDay.after_days),
      });
    }
    return rawTotals === true ? MUREO.t("outcome.note_raw_totals") : null;
  }

  function targetTexts(target) {
    if (!target || !isNumber(target.value)) return [];
    const value = format().formatNumber(target.value);
    const said = [
      target.reached === true
        ? MUREO.t("outcome.note_target_reached", { value: value })
        : MUREO.t("outcome.note_target_missed", { value: value }),
    ];
    if (isNumber(target.window_total)) {
      const total = format().formatNumber(target.window_total);
      said.push(MUREO.t("outcome.note_window_total", { value: total }));
    }
    return said;
  }

  /**
   * What an expected row adds after its direction: the band its verdict was
   * judged with (NOT that the move stayed inside it — an expected row can
   * move +30% against a ±10% band), or that its baseline was zero.
   */
  function expectedTexts(parts) {
    if (parts.kind !== "expected") return [];
    if (parts.zero_baseline === true) return [MUREO.t("outcome.note_zero_baseline")];
    if (!isNumber(parts.noise_pct)) return [];
    return [bandText("outcome.note_noise_band_used", parts.noise_pct)];
  }

  /**
   * A row's note from the parts the server read, or `null`.
   *
   * In this order: held back, what the kind says, the band an expected row
   * was judged with (or its zero baseline), per day or as totals, the
   * target, the window total. `null` when there are no parts or their kind
   * is one this file does not know.
   */
  function noteText(parts) {
    if (!parts || typeof parts !== "object") return null;
    const kind = kindText(parts);
    if (kind === null) return null;
    const said = [];
    if (parts.held_back) said.push(MUREO.t("outcome.note_held_back"));
    said.push(kind);
    said.push.apply(said, expectedTexts(parts));
    const period = periodText(parts.per_day, parts.raw_totals);
    if (period) said.push(period);
    return said.concat(targetTexts(parts.target)).join(MUREO.t("outcome.note_join"));
  }

  /**
   * `primary` / `reference` for one row of `table`, or `null` when unknown.
   *
   * The row's own `role` first. A table that predates the role reads it off
   * its `primary`; a table with neither (written before #888) has no roles.
   */
  function rowRole(row, table) {
    if (row && text(row.role)) return row.role;
    const primary = table && typeof table === "object" ? text(table.primary) : null;
    if (!primary) return null;
    return row && row.metric === primary ? "primary" : "reference";
  }

  const api = {
    reasonText: reasonText,
    summaryText: summaryText,
    noteText: noteText,
    rowRole: rowRole,
  };

  if (typeof window !== "undefined") window.MUREO_OUTCOME_TEXT = api;
  // Node (test runner only): `module` does not exist in a browser.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
