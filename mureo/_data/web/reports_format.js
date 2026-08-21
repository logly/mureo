// reports_format.js — the Reports dashboard's display vocabulary (#556).
//
// Everything here turns a wire value into text or a CSS class: a report flag
// into a localized label and a severity chip kind, a flag's `params` into a
// drill-down line, a raw number into a thousands-separated string, a period
// token into a button label. It was MOVED here verbatim from dashboard.js —
// same reason as reports_logic.js (#540): these are decisions a substring pin
// cannot check. Whether the LONGEST flag base wins, whether an unknown code
// degrades to a humanized token instead of showing a raw i18n key, whether an
// `is-info` flag sorts below an alarm — each is a comparison that can be
// flipped silently, and `node --test tests/js/` can execute them.
//
// No node is built here: nothing calls document.createElement, and the chip
// and card elements that consume these strings stay in dashboard.js. The one
// thing that reads the document at all is pickLocalizedLabel, which takes the
// active locale off <html lang> exactly as it did before — one attribute read,
// at CALL time, not a rendering dependency.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing one
// global, `window.MUREO_REPORTS_FORMAT`, the same way amazon_oauth.js
// publishes `window.MUREO_AMAZON_OAUTH`, and it MUST load before dashboard.js.
// The `module.exports` tail at the bottom is inert in a browser (`module` is
// undefined there) and is what lets Node require the same bytes the browser
// gets — the test never sees a re-implementation.
//
// `MUREO.t` is read from the global at CALL time, not captured at load time,
// so this file has no load-order dependency on app.js and a test can supply
// its own `t`.

(function () {
  "use strict";

  // Canonical period token → i18n label key. Unknown tokens fall back to the
  // raw token (so a future window still renders a button, just unlocalized).
  const REPORTS_PERIOD_LABELS = {
    YESTERDAY: "dashboard.reports_period_yesterday",
    LAST_7_DAYS: "dashboard.reports_period_last_7_days",
    LAST_30_DAYS: "dashboard.reports_period_last_30_days",
  };

  function reportsPeriodLabel(token) {
    const key = REPORTS_PERIOD_LABELS[token];
    return key ? MUREO.t(key) : String(token);
  }

  // Is this one of the windows mureo actually reports on (#659)?
  //
  // The map above IS that vocabulary — a token missing from it has no label
  // because mureo does not define the window. Such a token can only be one an
  // agent invented before the write path refused them: real figures,
  // correctly collected, filed under a name no view expects. The toggle
  // still renders it (dropping the tab would hide numbers mureo did collect)
  // but marks it, because an operator picking between seven windows, four of
  // them one session's ad-hoc phrasings, otherwise cannot tell which one
  // their reports are keyed to.
  //
  // `hasOwnProperty` rather than a truthiness check: `reportsPeriodLabel`
  // may fall back for a token, but "has no label" and "is not a window" must
  // stay the same question asked of the same table, and a token like
  // "constructor" must not inherit an answer from Object.prototype.
  function isCanonicalReportsPeriod(token) {
    return Object.prototype.hasOwnProperty.call(REPORTS_PERIOD_LABELS, token);
  }

  // Report flags (reports.daily.flags) are free-form snake_case tags the
  // analysis skill authors (e.g. "cpa_over_target_logly"). Map the common
  // bases to friendly localized labels; anything unknown is humanized
  // generically so a raw snake_case token never reaches the operator. The
  // LONGEST matching base wins. Only the base label is shown — the trailing
  // remainder (a platform or a descriptor) is dropped: it was inconsistent
  // across flags and read as distracting, ambiguous parentheses. Detail
  // lives in the report narrative. The 3rd element is the chip severity
  // (is-warn / is-danger / is-success) so flags read as coloured tags:
  // off-target / setup gaps = warn (amber), data-integrity / runaway = danger
  // (red), on-target = success (green).
  const REPORTS_FLAG_BASES = [
    ["cpa_over_target", "dashboard.reports_flag_cpa_over_target", "is-warn"],
    ["cpa_under_target", "dashboard.reports_flag_cpa_under_target", "is-success"],
    ["cv_below_target", "dashboard.reports_flag_cv_below_target", "is-warn"],
    ["conversions_below_target", "dashboard.reports_flag_cv_below_target", "is-warn"],
    ["cv_above_target", "dashboard.reports_flag_cv_above_target", "is-success"],
    ["operation_mode_mismatch", "dashboard.reports_flag_operation_mode_mismatch", "is-warn"],
    ["low_cvr_lp_conversion", "dashboard.reports_flag_low_cvr_lp", "is-warn"],
    ["low_cvr", "dashboard.reports_flag_low_cvr", "is-warn"],
    ["sparse_conversions_tracking_suspect", "dashboard.reports_flag_tracking_suspect", "is-danger"],
    ["tracking_suspect", "dashboard.reports_flag_tracking_suspect", "is-danger"],
    ["zero_conversions", "dashboard.reports_flag_zero_conversions", "is-danger"],
    ["budget_overspend", "dashboard.reports_flag_budget_overspend", "is-danger"],
    ["spend_spike", "dashboard.reports_flag_spend_spike", "is-warn"],
    ["search_console_no", "dashboard.reports_flag_sc_no_property", "is-warn"],
    // Canonical vocabulary (PR-A) — a bare-string flag emitted as one of these
    // codes maps to the same localized label + severity as its object form.
    ["invalid_traffic_suspected", "dashboard.reports_flag_invalid_traffic_suspected", "is-danger"],
    ["cpa_spike", "dashboard.reports_flag_cpa_spike", "is-warn"],
    ["zero_cv_adspots", "dashboard.reports_flag_zero_cv_adspots", "is-warn"],
    ["budget_drift", "dashboard.reports_flag_budget_drift", "is-warn"],
    ["goals_met", "dashboard.reports_flag_goals_met", "is-success"],
    ["supply_tools_unconfigured", "dashboard.reports_flag_supply_tools_unconfigured", "is-info"],
    ["anomaly_baseline_insufficient", "dashboard.reports_flag_anomaly_baseline_insufficient", "is-info"],
    ["pending_observations", "dashboard.reports_flag_pending_observations", "is-info"],
    ["search_console_no_property", "dashboard.reports_flag_search_console_no_property", "is-info"],
    ["ga4_not_configured", "dashboard.reports_flag_ga4_not_configured", "is-info"],
  ];

  // snake_case tokens that read better upper-cased (metric acronyms).
  const REPORTS_FLAG_ACRONYMS = {
    cpa: "CPA",
    cpc: "CPC",
    cpm: "CPM",
    ctr: "CTR",
    cvr: "CVR",
    cv: "CV",
    roas: "ROAS",
    roi: "ROI",
    lp: "LP",
    ga4: "GA4",
    seo: "SEO",
    url: "URL",
  };

  function humanizeFlagWords(token) {
    const words = String(token == null ? "" : token)
      .split("_")
      .filter(Boolean)
      .map(function (w) {
        return REPORTS_FLAG_ACRONYMS[w] || w;
      });
    if (!words.length) return "";
    const s = words.join(" ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // The longest base entry that a bare-string flag matches (or null).
  function matchReportFlagBase(raw) {
    let best = null;
    for (let i = 0; i < REPORTS_FLAG_BASES.length; i++) {
      const base = REPORTS_FLAG_BASES[i][0];
      if (
        (raw === base || raw.indexOf(base + "_") === 0) &&
        (!best || base.length > best[0].length)
      ) {
        best = REPORTS_FLAG_BASES[i];
      }
    }
    return best;
  }

  function humanizeReportFlag(flag) {
    // Structured object flag: localize by its canonical code, or use the
    // author-written label for a `custom` flag. Detail never appears here —
    // it lives in `params` (rendered on drill-down) and the narrative.
    if (flag && typeof flag === "object") {
      if (flag.code === "custom") return pickLocalizedLabel(flag.label);
      if (typeof flag.code === "string" && flag.code) {
        const key = "dashboard.reports_flag_" + flag.code;
        const label = MUREO.t(key);
        return label !== key ? label : humanizeFlagWords(flag.code);
      }
      // Legacy object without a code: fall back to any author text it carries
      // (label / message / level / kind), matching the pre-vocabulary render.
      return String(flag.label || flag.message || flag.level || flag.kind || "");
    }
    const raw = String(flag == null ? "" : flag);
    const best = matchReportFlagBase(raw);
    // A matched base shows only its localized label (no trailing context).
    return best ? MUREO.t(best[1]) : humanizeFlagWords(raw);
  }

  // A `custom` flag's label is either a plain string or a {locale: text} map.
  // Pick the active configure-UI locale (mirrored onto <html lang>), falling
  // back to English, then to any provided string.
  function pickLocalizedLabel(label) {
    if (typeof label === "string") return label;
    if (label && typeof label === "object") {
      const loc = document.documentElement.lang || "en";
      if (typeof label[loc] === "string") return label[loc];
      if (typeof label.en === "string") return label.en;
      const first = Object.keys(label)
        .map(function (k) {
          return label[k];
        })
        .filter(function (v) {
          return typeof v === "string" && v;
        })[0];
      return first || "";
    }
    return "";
  }

  // Canonical severity (action/watch/info/positive) → chip CSS class. Kept
  // separate from the legacy keyword inference in flagChipKind so a positive
  // ("goals met") or informational ("baseline not yet established") flag is
  // never coloured like an alarm.
  const SEVERITY_CHIP = {
    action: "is-danger",
    watch: "is-warn",
    info: "is-info",
    positive: "is-success",
  };

  // Severity class for a flag's coloured chip. An object flag carries an
  // explicit canonical severity; a bare string uses its base entry's curated
  // severity, falling back to keyword inference (flagChipKind) for unmapped
  // flags.
  function reportFlagKind(flag) {
    if (flag && typeof flag === "object") {
      const sev = flag.severity || flag.level || flag.kind;
      return SEVERITY_CHIP[sev] || flagChipKind(sev);
    }
    const best = matchReportFlagBase(String(flag == null ? "" : flag));
    return (best && best[2]) || flagChipKind(flag);
  }

  // Build the drill-down detail string for a structured flag from its
  // `params` (adspot ids, yen, ctr, …). Returns "" when there is nothing to
  // show — the chip then renders as a plain, non-interactive tag.
  function buildFlagDetail(flag) {
    if (!flag || typeof flag !== "object") return "";
    const params = flag.params;
    if (!params || typeof params !== "object") return "";
    const parts = [];
    Object.keys(params).forEach(function (key) {
      const value = formatFlagParam(key, params[key]);
      if (value === "") return;
      parts.push(flagParamLabel(key) + ": " + value);
    });
    return parts.join(" · ");
  }

  // Localized label for a param key (dashboard.reports_param_<key>), humanized
  // as a fallback so an unlocalized key never shows a raw i18n token.
  function flagParamLabel(key) {
    const k = "dashboard.reports_param_" + key;
    const label = MUREO.t(k);
    return label !== k ? label : humanizeFlagWords(key);
  }

  // Format a single param value: arrays join with commas, ctr renders as a
  // percentage, other numbers get thousands separators (no currency symbol —
  // the value may be any platform's spend), everything else is stringified.
  function formatFlagParam(key, value) {
    if (Array.isArray(value)) {
      return value
        .map(function (v) {
          return formatFlagParam(key, v);
        })
        .filter(Boolean)
        .join(", ");
    }
    if (typeof value === "boolean") {
      return MUREO.t(
        value ? "dashboard.reports_param_yes" : "dashboard.reports_param_no"
      );
    }
    if (key === "ctr" && typeof value === "number" && Number.isFinite(value)) {
      return formatKpi("ctr", value);
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return formatNumber(value);
    }
    return value == null ? "" : String(value);
  }

  // Format a raw number with thousands separators (no currency symbol —
  // the API returns raw numbers and we must not assume a currency). Non-
  // numbers pass through as plain text.
  function formatNumber(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value.toLocaleString();
    }
    return value == null ? "" : String(value);
  }

  // CTR is a ratio/percentage — render with up to 2 decimals + "%".
  function formatKpi(key, value) {
    if (key === "ctr" && typeof value === "number" && Number.isFinite(value)) {
      // Heuristic: a value <= 1 is a fraction (0.034 → 3.4%); otherwise it
      // is already a percentage figure from the platform. NOTE: totals are
      // platform-agnostic (built-in + arbitrary plugin:<dist> bridges) with no
      // guaranteed CTR-unit convention, so a bridge reporting "0.8" meaning
      // 0.8% would render as 80%. The real fix is normalizing CTR units in the
      // backend (PR-1) so the frontend doesn't guess; tracked as a follow-up.
      const pct = value <= 1 ? value * 100 : value;
      return pct.toLocaleString(undefined, { maximumFractionDigits: 2 }) + "%";
    }
    return formatNumber(value);
  }

  // The canonical headline metrics a stored report may state, in the order
  // the detail view renders them. Same vocabulary the platform cards use —
  // a report is not a place to invent a metric name.
  const REPORTS_SUMMARY_TOTAL_KEYS = [
    "spend",
    "conversions",
    "cpa",
    "ctr",
    "clicks",
    "impressions",
  ];

  /**
   * A stored report's headline figures as [{key, value}] (#662).
   *
   * The report summary is a free-form object written by an agent, and what
   * this returns is rendered AS FIGURES — so it is deliberately narrow:
   * only the canonical vocabulary above, only finite numbers. Anything else
   * (a formatted string, a per-platform breakdown, a metric mureo has no
   * label for) is not a headline figure — `reportSecondaryStats` below
   * shows it as what it is instead (#670). Reports already on disk state no
   * structure at all and get an empty list — they stay readable as the
   * prose they are, rather than being reformatted by guesswork.
   *
   * Two field names are read because the product uses two for the same
   * thing: `mureo_state_report_set` documents `kpis (per-platform / totals
   * headline numbers)`, and #662 calls it `totals`. `totals` wins where a
   * report carries both, and a payload keyed by platform is unwrapped
   * through its own `totals` — the per-platform half is not headline
   * figures.
   */
  function reportSummaryTotals(report) {
    let source = reportTotalsBlock(report);
    if (!source) return [];
    if (isPlainObject(source.totals)) source = source.totals;
    const out = [];
    REPORTS_SUMMARY_TOTAL_KEYS.forEach(function (key) {
      const value = source[key];
      if (isHeadlineFigure(key, value)) out.push({ key: key, value: value });
    });
    return out;
  }

  function isPlainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  // The block the view reads a report's headline figures FROM, or null.
  // Both spellings the schema uses are read, `totals` wins where a report
  // carries both. Factored out of reportSummaryTotals so the secondary row
  // below cannot drift from what the headline row looked at — "what the
  // headline row did NOT render" is only a true description while both
  // start from the same object.
  function reportTotalsBlock(report) {
    return reportTotalsBlocks(report).winner;
  }

  // Both blocks, as `{winner, loser}`: the one the headline row reads, and
  // the other spelling where a report carried both.
  //
  // The headline row only ever looks at the winner — that is #662's rule and
  // it does not change here. But a key that exists ONLY on the losing block
  // is then written, refused by nothing, and rendered nowhere, which is
  // exactly the failure #670 is about. So the loser is kept, and the
  // secondary row reads what the winner does not already carry.
  //
  // `loser` is null when a report states one block, or states the same
  // object under both names.
  function reportTotalsBlocks(report) {
    const obj = report && typeof report === "object" ? report : null;
    const out = { winner: null, loser: null };
    if (!obj) return out;
    [obj.kpis, obj.totals].forEach(function (candidate) {
      if (!isPlainObject(candidate)) return;
      if (out.winner) out.loser = out.winner;
      out.winner = candidate;
    });
    if (out.loser === out.winner) out.loser = null;
    return out;
  }

  // Did the headline row render this pair? (Canonical name, real number.)
  function isHeadlineFigure(key, value) {
    return (
      REPORTS_SUMMARY_TOTAL_KEYS.indexOf(key) !== -1 &&
      typeof value === "number" &&
      isFinite(value)
    );
  }

  // A value the secondary row can print as it stands. Strings, finite
  // numbers and booleans stringify losslessly; anything else does not have
  // a one-line rendering that is still the author's own.
  function isPrintableStat(value) {
    if (typeof value === "string" || typeof value === "boolean") return true;
    return typeof value === "number" && isFinite(value);
  }

  /**
   * What a report stated that the headline row did not render (#670).
   *
   * Returns `{entries: [{path, value}], hidden}`. #662 chose to STORE keys
   * outside the canonical six rather than refuse them — a goal review
   * carries a CVR, a per-goal target, a per-platform split, and refusing
   * those sends exactly that content back into the paragraph the length
   * bound exists to empty. Nothing read them back, so they were accepted on
   * write and invisible for good. This is the read half of that choice.
   *
   * Two rules make it safe to show content mureo has no vocabulary for:
   *
   *   • the value is returned UNTOUCHED. The caller prints it as written —
   *     "0.21%" is the author's own rendering of a ratio and 30000 is a
   *     target in the account's currency, and a separator, a unit or a
   *     percentage heuristic applied to either states a number the report
   *     never wrote.
   *   • what cannot be shown flat is COUNTED in `hidden`, never dropped. A
   *     per-platform split is flattened one level (`google_ads · spend`) —
   *     which is also where a string figure the write guard never reached
   *     becomes visible — and anything deeper, or a list, is reported as
   *     existing so the operator knows to open the report itself.
   *
   * Both blocks are read, not just the winning one. `totals` wins the
   * headline row where a report carries both spellings, and a key that
   * exists only on the losing block would otherwise be stored, refused by
   * nothing and rendered nowhere — the very failure this function exists to
   * end. A key the winner already carries is read from the WINNER and shown
   * once: the headline block is the one the report meant, and printing two
   * values under one name states a disagreement the report never wrote.
   *
   * A key with no value (`null` / absent) is not an entry: nothing was
   * written there to be hidden.
   */
  function reportSecondaryStats(report) {
    const out = { entries: [], hidden: 0 };
    const blocks = reportTotalsBlocks(report);
    const winner = blocks.winner;
    if (!winner) return out;
    const headline = isPlainObject(winner.totals) ? winner.totals : winner;
    collectReportStats(winner, winner === headline, headline, null, out);
    // The other spelling, minus everything the winner already answered for.
    // Nothing here was a headline figure — the headline row never looked at
    // this block — so a canonical name on it is a stat like any other.
    if (blocks.loser) {
      collectReportStats(blocks.loser, false, headline, winner, out);
    }
    return out;
  }

  // One totals block. Keys keep the author's order — a report's own stats
  // have no canonical order to sort them into. `alreadyRead`, when given, is
  // the block whose keys have been read already (see reportSecondaryStats).
  function collectReportStats(block, isHeadline, headline, alreadyRead, out) {
    Object.keys(block).forEach(function (key) {
      if (alreadyRead && Object.prototype.hasOwnProperty.call(alreadyRead, key)) {
        return;
      }
      const value = block[key];
      if (value == null) return;
      if (isHeadline && isHeadlineFigure(key, value)) return;
      if (isPrintableStat(value)) {
        out.entries.push({ path: [key], value: value });
        return;
      }
      if (isPlainObject(value)) {
        // The unwrapped headline block, reached from the outer one: its
        // own non-figure entries belong at the same level as the report's.
        if (value === headline) {
          collectReportStats(value, true, headline, null, out);
        } else {
          collectReportStatChildren(key, value, out);
        }
        return;
      }
      out.hidden += 1;
    });
  }

  // One level down: a per-platform block's own values. Deeper than this is
  // a tree, and a tree is read in the report, not in a row of chips.
  function collectReportStatChildren(parent, block, out) {
    Object.keys(block).forEach(function (key) {
      const value = block[key];
      if (value == null) return;
      if (isPrintableStat(value)) {
        out.entries.push({ path: [parent, key], value: value });
        return;
      }
      out.hidden += 1;
    });
  }

  // The label for a stat's path. No new vocabulary is invented for a key
  // mureo has no label for: the same snake_case humanizer the flag params
  // use, one segment at a time.
  function reportStatLabel(path) {
    if (!Array.isArray(path)) return "";
    return path
      .map(function (segment) {
        return humanizeFlagWords(segment);
      })
      .join(" · ");
  }

  // Map a free-form flag (string) to a chip kind. Defensive: any field may
  // be absent and the value may be an object with {level, label}.
  function flagChipKind(level) {
    const l = String(level || "").toLowerCase();
    if (l.indexOf("danger") >= 0 || l.indexOf("critical") >= 0 || l.indexOf("error") >= 0)
      return "is-danger";
    if (l.indexOf("warn") >= 0 || l.indexOf("watch") >= 0) return "is-warn";
    if (l.indexOf("ok") >= 0 || l.indexOf("good") >= 0 || l.indexOf("healthy") >= 0)
      return "is-success";
    return "";
  }

  // The report kinds mureo writes, mirrored from mureo/core/report_kinds.py
  // and pinned to it by tests/test_report_kind_vocabulary.py (#671). Nine
  // skills write nine kinds; this view used to know three of them.
  //
  // The order is the TIE-BREAK, not a preference — see latestReport.
  const REPORT_KINDS = [
    "daily",
    "weekly",
    "monthly",
    "goal",
    "audience",
    "experiment",
    "fatigue",
    "pacing",
    "tracking",
  ];

  /**
   * The most recently generated of a client's stored reports, or null.
   *
   * "Latest" is by `generated_at`, and that is the whole point (#671): the
   * pick used to be a fixed `daily || weekly || goal`, so once six more
   * kinds could be written, a monthly report filed this morning would sit
   * behind a daily one and never appear. A kind that can be written and
   * cannot be seen is the same failure as one the schema refuses, reached
   * from the other side.
   *
   * Defensive by construction — every field of a stored report is
   * agent-written and any of it may be absent or the wrong type:
   *
   *   • a missing or unparseable `generated_at` does not disqualify a
   *     report; it ranks below every dated one, and among the undated the
   *     REPORT_KINDS order decides. That order — not the JSON's key order —
   *     so the pick cannot change with how a document was serialized.
   *   • a key outside REPORT_KINDS is ignored. Strict on write (the tool's
   *     enum), tolerant on read (it stays in the document and reads back
   *     verbatim), but it does not compete for this block.
   */
  function latestReport(reports) {
    const obj = reports && typeof reports === "object" ? reports : null;
    if (!obj) return null;
    let best = null;
    let bestTime = -Infinity;
    REPORT_KINDS.forEach(function (kind) {
      const report = obj[kind];
      if (!report || typeof report !== "object" || Array.isArray(report)) return;
      const parsed =
        typeof report.generated_at === "string"
          ? Date.parse(report.generated_at)
          : NaN;
      const time = isNaN(parsed) ? -Infinity : parsed;
      // Strictly greater: iteration is in REPORT_KINDS order, so a tie keeps
      // the earlier kind and the fallback order is the one stated above.
      if (best === null || time > bestTime) {
        best = report;
        bestTime = time;
      }
    });
    return best;
  }

  // Flags from a client's latest report.
  function clientReportFlags(summary) {
    const r = latestReport(summary && summary.reports);
    return r && Array.isArray(r.flags) ? r.flags : [];
  }

  // Sort flags danger → warn → success → info → neutral (most urgent first).
  const REPORTS_FLAG_SEVERITY_ORDER = ["is-danger", "is-warn", "is-success", "is-info", ""];
  function flagSeverityRank(flag) {
    const idx = REPORTS_FLAG_SEVERITY_ORDER.indexOf(reportFlagKind(flag));
    return idx === -1 ? REPORTS_FLAG_SEVERITY_ORDER.length : idx;
  }

  const api = {
    // Exported for the invariant test in tests/js/reports_format.test.js,
    // which derives its cases FROM this table rather than restating them:
    // every base that is a `_`-boundary prefix of a longer one must lose to
    // it, whatever order they are registered in. Read-only by convention —
    // nothing in the browser build touches it.
    REPORTS_FLAG_BASES: REPORTS_FLAG_BASES,
    reportsPeriodLabel: reportsPeriodLabel,
    isCanonicalReportsPeriod: isCanonicalReportsPeriod,
    humanizeFlagWords: humanizeFlagWords,
    matchReportFlagBase: matchReportFlagBase,
    humanizeReportFlag: humanizeReportFlag,
    pickLocalizedLabel: pickLocalizedLabel,
    flagChipKind: flagChipKind,
    reportFlagKind: reportFlagKind,
    flagSeverityRank: flagSeverityRank,
    // The write side's vocabulary, mirrored (#671). Exported so the JS suite
    // can drive every kind through latestReport rather than restating the
    // list, and so the Python pin has one place to compare against.
    REPORT_KINDS: REPORT_KINDS,
    latestReport: latestReport,
    clientReportFlags: clientReportFlags,
    buildFlagDetail: buildFlagDetail,
    flagParamLabel: flagParamLabel,
    formatFlagParam: formatFlagParam,
    formatNumber: formatNumber,
    formatKpi: formatKpi,
    REPORTS_SUMMARY_TOTAL_KEYS: REPORTS_SUMMARY_TOTAL_KEYS,
    reportSummaryTotals: reportSummaryTotals,
    reportSecondaryStats: reportSecondaryStats,
    reportStatLabel: reportStatLabel,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_FORMAT = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
