// Behavioural tests for mureo/_data/web/reports_format.js (#556).
//
// Run with:  node --test tests/js/
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/reports_format.js, no build step and no copy.
//
// Everything here was previously guarded only by the substring pins in
// tests/test_web_assets_report_flags_vocab.py, which can see that a name, a
// string or an i18n key is present and nothing more. The decisions below are
// exactly what a substring pin cannot read:
//
//   • the LONGEST flag base wins, so "sparse_conversions_tracking_suspect"
//     is a tracking-integrity danger and not whatever a shorter prefix says.
//   • an unknown code degrades to a humanized token, so a raw i18n key
//     ("dashboard.reports_flag_…") never reaches an operator's screen.
//   • a canonical severity beats the legacy keyword inference, so an
//     `info` or `positive` flag is never coloured like an alarm — and
//     ranks BELOW the alarms when the card sorts its chips.
//   • CTR's fraction-vs-percentage heuristic scales 0.034 and 3.4 to the
//     same figure. Flip that and a card reads 0.03% instead of 3.4%.
//
// i18n: MUREO.t returns the key it was handed unless TRANSLATED names it, so
// assertions are on WHICH string was chosen and on which fallback branch was
// taken, not on English wording.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

/** Keys the stub "has a translation for"; everything else echoes the key. */
const TRANSLATED = {
  "dashboard.reports_flag_cpa_over_target": "CPA over target",
  "dashboard.reports_flag_tracking_suspect": "Tracking suspect",
  "dashboard.reports_flag_low_cvr": "Low CVR",
  "dashboard.reports_flag_low_cvr_lp": "Low CVR on the LP",
  "dashboard.reports_flag_goals_met": "Goals met",
  "dashboard.reports_period_yesterday": "Yesterday",
  "dashboard.reports_param_adspot": "Ad spot",
  "dashboard.reports_param_yes": "yes",
  "dashboard.reports_param_no": "no",
};

globalThis.MUREO = {
  t: function (key) {
    return Object.prototype.hasOwnProperty.call(TRANSLATED, key)
      ? TRANSLATED[key]
      : key;
  },
};

// pickLocalizedLabel reads the active locale off <html lang> — one attribute,
// at call time. Nothing else in the module touches the document.
globalThis.document = { documentElement: { lang: "en" } };

const fmt = require(path.join(WEB, "reports_format.js"));

test.beforeEach(function () {
  globalThis.document.documentElement.lang = "en";
});

// ---------------------------------------------------------------------------
// Period labels
// ---------------------------------------------------------------------------

test.describe("reportsPeriodLabel", function () {
  test.it("localizes a known window", function () {
    assert.equal(fmt.reportsPeriodLabel("YESTERDAY"), "Yesterday");
  });

  test.it("renders an unknown window as its raw token", function () {
    // A future window still gets a button, just unlocalized — never a blank
    // one and never a raw i18n key.
    assert.equal(fmt.reportsPeriodLabel("LAST_90_DAYS"), "LAST_90_DAYS");
    assert.equal(fmt.reportsPeriodLabel(null), "null");
  });
});

test.describe("isCanonicalReportsPeriod", function () {
  test.it("knows the three windows mureo reports on", function () {
    assert.equal(fmt.isCanonicalReportsPeriod("YESTERDAY"), true);
    assert.equal(fmt.isCanonicalReportsPeriod("LAST_7_DAYS"), true);
    assert.equal(fmt.isCanonicalReportsPeriod("LAST_30_DAYS"), true);
  });

  test.it("marks a window an agent invented (#659)", function () {
    // These four are from the reported install. The toggle still renders
    // them — the figures under them are real — but they are not windows
    // mureo keeps up to date, and an operator has to be able to tell.
    ["SINCE_LAUNCH_17D", "LAST_8_DAYS", "TO_DATE_1", "THIS_QUARTER"].forEach(
      function (token) {
        assert.equal(fmt.isCanonicalReportsPeriod(token), false, token);
      }
    );
  });

  test.it("does not inherit an answer from Object.prototype", function () {
    // A truthiness check on the label map would call these windows.
    assert.equal(fmt.isCanonicalReportsPeriod("constructor"), false);
    assert.equal(fmt.isCanonicalReportsPeriod("toString"), false);
    assert.equal(fmt.isCanonicalReportsPeriod(null), false);
    assert.equal(fmt.isCanonicalReportsPeriod(undefined), false);
  });
});

// ---------------------------------------------------------------------------
// Humanizing
// ---------------------------------------------------------------------------

test.describe("humanizeFlagWords", function () {
  test.it("upper-cases metric acronyms and sentence-cases the rest", function () {
    assert.equal(fmt.humanizeFlagWords("cpa_over_target"), "CPA over target");
    assert.equal(fmt.humanizeFlagWords("low_cvr_lp"), "Low CVR LP");
  });

  test.it("capitalizes a leading non-acronym word", function () {
    assert.equal(fmt.humanizeFlagWords("budget_drift"), "Budget drift");
  });

  test.it("survives empty and null input", function () {
    assert.equal(fmt.humanizeFlagWords(""), "");
    assert.equal(fmt.humanizeFlagWords(null), "");
    assert.equal(fmt.humanizeFlagWords("___"), "");
  });
});

test.describe("matchReportFlagBase", function () {
  test.it("prefers the LONGEST matching base", function () {
    const best = fmt.matchReportFlagBase("sparse_conversions_tracking_suspect");
    assert.equal(best[0], "sparse_conversions_tracking_suspect");

    const lp = fmt.matchReportFlagBase("low_cvr_lp_conversion");
    assert.equal(lp[0], "low_cvr_lp_conversion");
    assert.equal(fmt.matchReportFlagBase("low_cvr")[0], "low_cvr");
  });

  test.it("prefers the longest even when the SHORTER base is registered first", function () {
    // The case that matters, and the only pair in the shipped table where
    // registration order and match length disagree: "search_console_no" is
    // listed BEFORE "search_console_no_property". A first-registered-wins
    // implementation passes every other test in this file and puts an
    // amber "is-warn" chip with the wrong label in front of an operator
    // where an informational "is-info" one belongs.
    const best = fmt.matchReportFlagBase("search_console_no_property");
    assert.equal(best[0], "search_console_no_property");
    assert.equal(best[1], "dashboard.reports_flag_search_console_no_property");
    assert.equal(best[2], "is-info");
    assert.equal(fmt.reportFlagKind("search_console_no_property"), "is-info");
    // …and the shorter base still resolves to its own entry.
    assert.equal(fmt.matchReportFlagBase("search_console_no")[0], "search_console_no");
    assert.equal(fmt.reportFlagKind("search_console_no"), "is-warn");
  });

  test.it("resolves EVERY prefix pair in the shipped table to the longer one", function () {
    // Derived from the table rather than restated: a base added anywhere in
    // REPORTS_FLAG_BASES that shadows or is shadowed by another is covered
    // the moment it ships, without anyone remembering to add a case here.
    // This is what makes longest-wins a property of the module rather than
    // of where entries happen to sit in the array.
    const bases = fmt.REPORTS_FLAG_BASES.map(function (entry) {
      return entry[0];
    });
    const pairs = [];
    for (const long of bases) {
      for (const short of bases) {
        if (short !== long && long.indexOf(short + "_") === 0) {
          pairs.push([short, long]);
        }
      }
    }
    assert.ok(pairs.length > 0, "no prefix pairs found — did the table change shape?");
    for (const [short, long] of pairs) {
      const best = fmt.matchReportFlagBase(long);
      assert.equal(
        best && best[0],
        long,
        `"${long}" resolved to "${best && best[0]}"; "${short}" shadowed it`
      );
    }
  });

  test.it("gives every registered base a label key and a known severity", function () {
    // (best && best[2]) is the whole severity for a bare-string flag: an
    // entry with an empty third slot would silently fall through to the
    // legacy keyword inference, which returns "" for every base we ship.
    const KINDS = ["is-danger", "is-warn", "is-success", "is-info"];
    for (const entry of fmt.REPORTS_FLAG_BASES) {
      assert.equal(entry.length, 3, `${entry[0]} is not [base, labelKey, kind]`);
      assert.ok(entry[1].startsWith("dashboard.reports_flag_"), entry[0]);
      assert.ok(KINDS.includes(entry[2]), `${entry[0]} has severity "${entry[2]}"`);
    }
  });

  test.it("matches a base followed by a descriptor, not a bare prefix", function () {
    // "cpa_over_target_logly" is the base plus a client name…
    assert.equal(fmt.matchReportFlagBase("cpa_over_target_logly")[0], "cpa_over_target");
    // …but "cpa_over_targeting" only SHARES a prefix and must not match.
    assert.equal(fmt.matchReportFlagBase("cpa_over_targeting"), null);
  });

  test.it("returns null for an unregistered flag", function () {
    assert.equal(fmt.matchReportFlagBase("something_nobody_registered"), null);
  });
});

test.describe("humanizeReportFlag", function () {
  test.it("localizes a structured flag by its canonical code", function () {
    assert.equal(fmt.humanizeReportFlag({ code: "goals_met" }), "Goals met");
  });

  test.it("never shows a raw i18n key for an unlocalized code", function () {
    // The regression this exists to catch: MUREO.t echoes the key when there
    // is no translation, and echoing THAT onto a chip is unreadable.
    const label = fmt.humanizeReportFlag({ code: "brand_new_finding" });
    assert.equal(label, "Brand new finding");
    assert.ok(!label.includes("dashboard."));
  });

  test.it("uses the author's own label for a custom flag", function () {
    assert.equal(
      fmt.humanizeReportFlag({ code: "custom", label: "Budget parked" }),
      "Budget parked"
    );
  });

  test.it("falls back to any author text on a legacy object flag", function () {
    assert.equal(fmt.humanizeReportFlag({ message: "something odd" }), "something odd");
    assert.equal(fmt.humanizeReportFlag({ level: "warn" }), "warn");
    assert.equal(fmt.humanizeReportFlag({}), "");
  });

  test.it("shows only the base label for a bare-string flag", function () {
    // The trailing remainder ("_logly") is dropped on purpose — it read as
    // distracting, ambiguous parentheses.
    assert.equal(fmt.humanizeReportFlag("cpa_over_target_logly"), "CPA over target");
  });

  test.it("humanizes an unregistered bare-string flag", function () {
    assert.equal(fmt.humanizeReportFlag("weird_new_ctr_thing"), "Weird new CTR thing");
    assert.equal(fmt.humanizeReportFlag(null), "");
  });
});

test.describe("pickLocalizedLabel", function () {
  test.it("passes a plain string through", function () {
    assert.equal(fmt.pickLocalizedLabel("Budget parked"), "Budget parked");
  });

  test.it("picks the active configure-UI locale", function () {
    globalThis.document.documentElement.lang = "ja";
    assert.equal(fmt.pickLocalizedLabel({ en: "Parked", ja: "停止中" }), "停止中");
  });

  test.it("falls back to English, then to any string it has", function () {
    globalThis.document.documentElement.lang = "de";
    assert.equal(fmt.pickLocalizedLabel({ en: "Parked", ja: "停止中" }), "Parked");
    assert.equal(fmt.pickLocalizedLabel({ ja: "停止中" }), "停止中");
  });

  test.it("returns empty rather than throwing on junk", function () {
    assert.equal(fmt.pickLocalizedLabel(null), "");
    assert.equal(fmt.pickLocalizedLabel(42), "");
    assert.equal(fmt.pickLocalizedLabel({ en: 7 }), "");
  });
});

// ---------------------------------------------------------------------------
// Severity — the colour an operator triages by
// ---------------------------------------------------------------------------

test.describe("flagChipKind", function () {
  test.it("infers a kind from legacy free-form level words", function () {
    assert.equal(fmt.flagChipKind("critical"), "is-danger");
    assert.equal(fmt.flagChipKind("ERROR"), "is-danger");
    assert.equal(fmt.flagChipKind("watch"), "is-warn");
    assert.equal(fmt.flagChipKind("healthy"), "is-success");
    assert.equal(fmt.flagChipKind("whatever"), "");
    assert.equal(fmt.flagChipKind(null), "");
  });
});

test.describe("reportFlagKind", function () {
  test.it("maps the four canonical severities", function () {
    assert.equal(fmt.reportFlagKind({ code: "x", severity: "action" }), "is-danger");
    assert.equal(fmt.reportFlagKind({ code: "x", severity: "watch" }), "is-warn");
    assert.equal(fmt.reportFlagKind({ code: "x", severity: "info" }), "is-info");
    assert.equal(fmt.reportFlagKind({ code: "x", severity: "positive" }), "is-success");
  });

  test.it("does not colour an info or positive flag like an alarm", function () {
    // "info" contains no danger/warn keyword, so the legacy inference would
    // return "" — the canonical map must be consulted FIRST.
    const info = fmt.reportFlagKind({ code: "pending_observations", severity: "info" });
    assert.equal(info, "is-info");
    assert.notEqual(info, "is-danger");
    assert.notEqual(info, "is-warn");
  });

  test.it("falls back to keyword inference for an unmapped severity", function () {
    assert.equal(fmt.reportFlagKind({ code: "x", severity: "critical" }), "is-danger");
    assert.equal(fmt.reportFlagKind({ code: "x", level: "warn" }), "is-warn");
  });

  test.it("uses the curated severity of a bare string's base", function () {
    // Every shipped base infers "" under the legacy keyword rule, so the
    // curated severity is the only thing that can produce these.
    assert.equal(fmt.reportFlagKind("zero_conversions"), "is-danger");
    assert.equal(fmt.reportFlagKind("cpa_under_target"), "is-success");
    assert.equal(fmt.reportFlagKind("goals_met"), "is-success");
    assert.equal(fmt.reportFlagKind("ga4_not_configured"), "is-info");
    assert.equal(fmt.reportFlagKind("nothing_registered"), "");
  });

  test.it("still infers a kind for an unregistered flag that carries one", function () {
    // The fallback arm: dropping it would leave an agent-authored flag that
    // says "critical" rendering as an uncoloured tag. No shipped base
    // reaches this arm, so nothing else in this file would notice.
    assert.equal(fmt.reportFlagKind("some_critical_thing"), "is-danger");
    assert.equal(fmt.reportFlagKind("unregistered_warn_case"), "is-warn");
  });
});

test.describe("flagSeverityRank", function () {
  test.it("sorts most urgent first and puts info below the colours", function () {
    const flags = [
      "ga4_not_configured", // is-info
      "goals_met", // is-success
      "nothing_registered", // ""
      "zero_conversions", // is-danger
      "spend_spike", // is-warn
    ];
    const sorted = flags.slice().sort(function (a, b) {
      return fmt.flagSeverityRank(a) - fmt.flagSeverityRank(b);
    });
    assert.deepEqual(sorted, [
      "zero_conversions",
      "spend_spike",
      "goals_met",
      "ga4_not_configured",
      "nothing_registered",
    ]);
  });
});

// ---------------------------------------------------------------------------
// Which flags a client card shows
// ---------------------------------------------------------------------------

test.describe("clientReportFlags", function () {
  test.it("prefers daily, then weekly, then goal", function () {
    const summary = {
      reports: {
        daily: { flags: ["a"] },
        weekly: { flags: ["b"] },
        goal: { flags: ["c"] },
      },
    };
    assert.deepEqual(fmt.clientReportFlags(summary), ["a"]);
    delete summary.reports.daily;
    assert.deepEqual(fmt.clientReportFlags(summary), ["b"]);
    delete summary.reports.weekly;
    assert.deepEqual(fmt.clientReportFlags(summary), ["c"]);
  });

  test.it("is empty rather than throwing when there is no report", function () {
    assert.deepEqual(fmt.clientReportFlags(null), []);
    assert.deepEqual(fmt.clientReportFlags({}), []);
    assert.deepEqual(fmt.clientReportFlags({ reports: {} }), []);
    assert.deepEqual(fmt.clientReportFlags({ reports: { daily: {} } }), []);
  });
});

// ---------------------------------------------------------------------------
// Figures
// ---------------------------------------------------------------------------

test.describe("formatNumber", function () {
  test.it("groups a finite number", function () {
    assert.equal(fmt.formatNumber(1234567), (1234567).toLocaleString());
  });

  test.it("passes non-numbers through as plain text, never 'null'", function () {
    assert.equal(fmt.formatNumber(null), "");
    assert.equal(fmt.formatNumber(undefined), "");
    assert.equal(fmt.formatNumber("n/a"), "n/a");
    assert.equal(fmt.formatNumber(NaN), "NaN");
    assert.equal(fmt.formatNumber(Infinity), "Infinity");
  });
});

test.describe("formatKpi", function () {
  test.it("scales a CTR fraction and a CTR percentage to the same figure", function () {
    // The heuristic: <= 1 is a fraction (0.034 → 3.4%). Locale-independent —
    // it asserts the SCALING, not the separator.
    assert.equal(fmt.formatKpi("ctr", 0.034), fmt.formatKpi("ctr", 3.4));
    assert.equal(fmt.formatKpi("ctr", 1), fmt.formatKpi("ctr", 100));
    assert.ok(fmt.formatKpi("ctr", 0.034).endsWith("%"));
  });

  test.it("does not percent-ize a non-CTR metric", function () {
    assert.equal(fmt.formatKpi("clicks", 0.5), fmt.formatNumber(0.5));
    assert.ok(!fmt.formatKpi("clicks", 0.5).includes("%"));
  });

  test.it("leaves a non-numeric CTR alone", function () {
    assert.equal(fmt.formatKpi("ctr", null), "");
    assert.equal(fmt.formatKpi("ctr", "—"), "—");
  });
});

// ---------------------------------------------------------------------------
// Flag params → the drill-down line
// ---------------------------------------------------------------------------

test.describe("flagParamLabel", function () {
  test.it("localizes a known param key", function () {
    assert.equal(fmt.flagParamLabel("adspot"), "Ad spot");
  });

  test.it("humanizes an unlocalized one rather than showing the i18n key", function () {
    const label = fmt.flagParamLabel("pool_ratio");
    assert.equal(label, "Pool ratio");
    assert.ok(!label.includes("dashboard."));
  });
});

test.describe("formatFlagParam", function () {
  test.it("localizes booleans instead of shipping English true/false", function () {
    assert.equal(fmt.formatFlagParam("unlogged", true), "yes");
    assert.equal(fmt.formatFlagParam("unlogged", false), "no");
  });

  test.it("joins arrays and drops the empties", function () {
    assert.equal(fmt.formatFlagParam("adspots", ["a", "b"]), "a, b");
    assert.equal(fmt.formatFlagParam("adspots", ["a", null, "b"]), "a, b");
    assert.equal(fmt.formatFlagParam("adspots", []), "");
  });

  test.it("routes ctr through the percentage rule", function () {
    assert.equal(fmt.formatFlagParam("ctr", 0.034), fmt.formatKpi("ctr", 0.034));
  });

  test.it("groups other numbers and stringifies the rest", function () {
    assert.equal(fmt.formatFlagParam("spend", 1234567), (1234567).toLocaleString());
    assert.equal(fmt.formatFlagParam("note", null), "");
    assert.equal(fmt.formatFlagParam("note", "raw"), "raw");
  });
});

test.describe("buildFlagDetail", function () {
  test.it("renders label: value pairs joined by a middot", function () {
    const detail = fmt.buildFlagDetail({
      code: "zero_cv_adspots",
      params: { adspot: "A-1", spend: 12000 },
    });
    assert.equal(detail, "Ad spot: A-1 · Spend: " + (12000).toLocaleString());
  });

  test.it("skips params that format to nothing", function () {
    const detail = fmt.buildFlagDetail({ params: { adspot: "A-1", note: null } });
    assert.equal(detail, "Ad spot: A-1");
  });

  test.it("returns empty when there is nothing to drill into", function () {
    // "" is what makes the chip render as a plain, non-interactive tag —
    // an interactive chip that discloses nothing is a dead control.
    assert.equal(fmt.buildFlagDetail("cpa_over_target"), "");
    assert.equal(fmt.buildFlagDetail(null), "");
    assert.equal(fmt.buildFlagDetail({ code: "x" }), "");
    assert.equal(fmt.buildFlagDetail({ code: "x", params: {} }), "");
    assert.equal(fmt.buildFlagDetail({ code: "x", params: "nope" }), "");
  });
});

// ---------------------------------------------------------------------
// The stored report's headline figures (#662)
// ---------------------------------------------------------------------
//
// `mureo_state_report_set` defines the summary as {totals/kpis, flags,
// narrative}, and the view rendered `narrative` into a single <p> on the
// assumption that it is short. Real reports fold the period, the figures,
// the per-ad findings and the proposal into that one string, and the
// operator's verdict on it was that nobody reads it.
//
// This is the read half: figures the writer DID put in the structure are
// rendered as figures. It is deliberately narrow — only the canonical
// metric vocabulary, only real numbers — because everything it accepts it
// presents as a headline figure, and a report already on disk must stay
// readable rather than be reformatted by guesswork.

test.describe("a stored report's headline figures", function () {
  test.it("reads the canonical metrics in display order", function () {
    assert.deepEqual(
      fmt.reportSummaryTotals({
        // Deliberately out of display order in the payload.
        totals: { conversions: 50, spend: 773957, cpa: 15479 },
      }),
      [
        { key: "spend", value: 773957 },
        { key: "conversions", value: 50 },
        { key: "cpa", value: 15479 },
      ]
    );
  });

  test.it("accepts `kpis`, the other spelling the schema documents", function () {
    // The report-set tool's own description says "kpis (per-platform /
    // totals headline numbers)"; #662 calls the same field `totals`. Both
    // are the product's own words for it, so both are read.
    assert.deepEqual(fmt.reportSummaryTotals({ kpis: { spend: 100 } }), [
      { key: "spend", value: 100 },
    ]);
    // `totals` wins where a report carries both.
    assert.deepEqual(
      fmt.reportSummaryTotals({ totals: { spend: 1 }, kpis: { spend: 2 } }),
      [{ key: "spend", value: 1 }]
    );
  });

  test.it("unwraps a per-platform payload's own totals", function () {
    // "per-platform / totals" — a writer may key by platform and put the
    // roll-up under `totals`. The per-platform half is not headline figures.
    assert.deepEqual(
      fmt.reportSummaryTotals({
        kpis: {
          google_ads: { spend: 60 },
          meta_ads: { spend: 40 },
          totals: { spend: 100, conversions: 4 },
        },
      }),
      [
        { key: "spend", value: 100 },
        { key: "conversions", value: 4 },
      ]
    );
  });

  test.it("takes only real numbers, and only the canonical vocabulary", function () {
    // Everything this returns is presented as a headline figure. A string,
    // a null or a name mureo has no label for belongs to the narrative.
    assert.deepEqual(
      fmt.reportSummaryTotals({
        totals: {
          spend: 100,
          conversions: null,
          cpa: "15,479 yen",
          roas: 3.4,
          clicks: NaN,
          impressions: Infinity,
        },
      }),
      [{ key: "spend", value: 100 }]
    );
  });

  test.it("returns nothing for a report that stated no structure", function () {
    // The reports already on disk. They stay readable — as prose, which is
    // what they are — rather than being reformatted by guesswork.
    [
      { narrative: "one very long paragraph" },
      { totals: null },
      { totals: "773,957 yen" },
      { totals: [] },
      {},
      null,
      undefined,
      "report",
    ].forEach(function (report) {
      assert.deepEqual(fmt.reportSummaryTotals(report), []);
    });
  });
});

// ---------------------------------------------------------------------
// The stats a report states that are not headline figures (#670)
// ---------------------------------------------------------------------
//
// #662 chose, deliberately, to STORE what a report writes outside the six
// canonical metrics: a goal review carries a CVR, a per-goal target and a
// per-platform split, and refusing those sends exactly that content back
// into the paragraph the length bound exists to empty. But nothing read
// them — accepted on write, invisible for good, which is #659's shape one
// field over.
//
// So this is the read half of that decision: everything in the block the
// headline row read, minus what the headline row rendered. Two rules make
// it safe to show content mureo has no vocabulary for:
//
//   • the VALUE is passed through untouched. "0.21%" stays "0.21%" and
//     30000 stays 30000 — reformatting an author's figure is how a view
//     ends up answering for a period it was never given.
//   • what cannot be shown flat is COUNTED, never dropped. A silently
//     discarded entry is the bug this issue is about.

test.describe("a stored report's own statistics", function () {
  test.it("returns what the headline row left behind, value untouched", function () {
    assert.deepEqual(
      fmt.reportSecondaryStats({
        totals: { spend: 773957, cvr: "0.21%", goal_target_cpa: 30000 },
      }),
      {
        entries: [
          { path: ["cvr"], value: "0.21%" },
          { path: ["goal_target_cpa"], value: 30000 },
        ],
        hidden: 0,
      }
    );
  });

  test.it("keeps a number a number, so the renderer prints what was written", function () {
    // Not "30,000", not "¥30,000" — no separator, no unit, no rounding.
    // The report's own figure, in the report's own words.
    const stats = fmt.reportSecondaryStats({ totals: { goal_target_cpa: 30000 } });
    assert.equal(typeof stats.entries[0].value, "number");
    assert.equal(stats.entries[0].value, 30000);
  });

  test.it("shows a canonical figure the headline row could not render", function () {
    // The write guard refuses `cpa: "15,479 yen"` at this level, so this is
    // a report that arrived another way (a hand-written STATE.json, an
    // import). The headline row still will not state it as a figure — but
    // it is no longer invisible.
    assert.deepEqual(
      fmt.reportSecondaryStats({ totals: { spend: 100, cpa: "15,479 yen" } }),
      { entries: [{ path: ["cpa"], value: "15,479 yen" }], hidden: 0 }
    );
  });

  test.it("flattens a per-platform split one level, strings and all", function () {
    // The write guard's coverage stops at the flat headline dict, so a
    // string figure nested under a platform is neither refused nor rendered
    // as a figure. It is content an agent wrote, and it reads here as text.
    assert.deepEqual(
      fmt.reportSecondaryStats({
        kpis: {
          google_ads: { spend: "¥773,957", clicks: 1200 },
          totals: { spend: 773957, conversions: 50, cvr: "0.21%" },
        },
      }),
      {
        entries: [
          { path: ["google_ads", "spend"], value: "¥773,957" },
          { path: ["google_ads", "clicks"], value: 1200 },
          { path: ["cvr"], value: "0.21%" },
        ],
        hidden: 0,
      }
    );
  });

  test.it("counts what it cannot show flat instead of dropping it", function () {
    // A deeper tree and a list have no honest one-line rendering here. The
    // operator is told they exist; the stored report is where they are read.
    assert.deepEqual(
      fmt.reportSecondaryStats({
        totals: { spend: 1, breakdown: { daily: { mon: 1 } }, top_terms: ["a", "b"] },
      }),
      { entries: [], hidden: 2 }
    );
  });

  test.it("treats an absent value as absent, not as a hidden entry", function () {
    assert.deepEqual(fmt.reportSecondaryStats({ totals: { spend: 1, note: null } }), {
      entries: [],
      hidden: 0,
    });
  });

  test.it("has nothing to say about a report that stated no structure", function () {
    [
      { narrative: "one very long paragraph" },
      { totals: null },
      { totals: "773,957 yen" },
      { totals: [] },
      {},
      null,
      undefined,
      "report",
    ].forEach(function (report) {
      assert.deepEqual(fmt.reportSecondaryStats(report), { entries: [], hidden: 0 });
    });
  });

  test.it("labels a path with the humanizer the flag params already use", function () {
    // No new vocabulary is invented for a key mureo has no label for: the
    // same snake_case humanizer, one path segment at a time.
    assert.equal(fmt.reportStatLabel(["cvr"]), "CVR");
    assert.equal(fmt.reportStatLabel(["goal_target_cpa"]), "Goal target CPA");
    assert.equal(fmt.reportStatLabel(["google_ads", "spend"]), "Google ads · Spend");
    assert.equal(fmt.reportStatLabel([]), "");
  });
});
