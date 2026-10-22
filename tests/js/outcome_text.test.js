// The outcome verdict in words (#894): outcome_text.js.
//
// Run with:  node --test tests/js/*.test.js
//
// EXECUTES the shipped bytes. MUREO.t below returns the key it was handed,
// with any interpolated params appended, so every assertion is about WHICH
// string was chosen and what was put into it — never about English wording.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

globalThis.MUREO = {
  t: function (key, params) {
    const entries = Object.entries(params || {});
    return entries.length
      ? key + "|" + entries.map(([k, v]) => k + "=" + v).join(",")
      : key;
  },
};
globalThis.window = globalThis;
// outcome_text.js reads reports_format.js off the page at call time (the
// metric names and the numbers are printed the way the rest of the screen
// prints them). Here we ARE the page.
require(path.join(WEB, "reports_format.js"));
const outcome = require(path.join(WEB, "outcome_text.js"));
const CATALOG = require(path.join(WEB, "i18n.json"));

const JOIN = "outcome.note_join";
const SEP = "outcome.summary_sep";

// Runs `fn` with MUREO.t rendering the shipped catalog for `locale`
// (falling back to English, as app.js does), then puts the key stub back.
function inLocale(locale, fn) {
  const stub = globalThis.MUREO.t;
  globalThis.MUREO.t = function (key, params) {
    const own = CATALOG[locale][key];
    const template = own != null ? own : CATALOG.en[key];
    return String(template).replace(/\{(\w+)\}/g, function (_, name) {
      return name in (params || {}) ? params[name] : "{" + name + "}";
    });
  };
  try {
    return fn();
  } finally {
    globalThis.MUREO.t = stub;
  }
}

function parts(extra) {
  return Object.assign(
    {
      kind: null,
      direction: null,
      noise_pct: null,
      per_day: null,
      raw_totals: false,
      held_back: null,
      target: null,
      zero_baseline: false,
    },
    extra
  );
}

test.describe("reasonText", function () {
  test.it("says every reason the evaluator writes", function () {
    [
      "no_primary_metric",
      "insufficient_volume",
      "volume_unknown",
      "period_unknown",
      "zero_baseline",
      "target_not_reached",
      "no_change",
    ].forEach(function (code) {
      assert.equal(outcome.reasonText(code), "outcome.reason_" + code);
    });
  });

  test.it("hands an unknown code back as it is", function () {
    assert.equal(outcome.reasonText("brand_new_reason"), "brand_new_reason");
  });
});

test.describe("summaryText", function () {
  test.it("names the primary and its verdict", function () {
    assert.equal(
      outcome.summaryText({ overall: "improved", primary: "cpa", reason: null }),
      "outcome.summary|metric=CPA,verdict=ops_history_section.verdict_improved"
    );
  });

  test.it("says a held primary with the existing verdict label", function () {
    assert.equal(
      outcome.summaryText({ overall: "held", primary: "spend", reason: null }),
      "outcome.summary|metric=Spend,verdict=ops_history_section.verdict_held"
    );
  });

  test.it("follows the verdict with the reason", function () {
    assert.equal(
      outcome.summaryText({
        overall: "inconclusive",
        primary: "cpa",
        reason: "insufficient_volume",
      }),
      "outcome.summary|metric=CPA,verdict=ops_history_section.verdict_inconclusive" +
        SEP +
        "outcome.reason_insufficient_volume"
    );
  });

  test.it("says no primary could be judged when there is none", function () {
    assert.equal(
      outcome.summaryText({ overall: "inconclusive", primary: null, reason: null }),
      "outcome.summary_no_primary|verdict=ops_history_section.verdict_inconclusive" +
        SEP +
        "outcome.reason_no_primary_metric"
    );
    assert.equal(
      outcome.summaryText({
        overall: "inconclusive",
        primary: null,
        reason: "no_primary_metric",
      }),
      "outcome.summary_no_primary|verdict=ops_history_section.verdict_inconclusive" +
        SEP +
        "outcome.reason_no_primary_metric"
    );
  });

  test.it("puts no space between the sentences in Japanese", function () {
    const evaluation = {
      overall: "inconclusive",
      primary: "cpa",
      reason: "insufficient_volume",
    };
    assert.equal(
      inLocale("ja", function () {
        return outcome.summaryText(evaluation);
      }),
      "成果の判定（CPA）: 判定不能。件数が下限に届かないため、判定を保留しました。"
    );
    assert.equal(
      inLocale("en", function () {
        return outcome.summaryText(evaluation);
      }),
      "Outcome on CPA: Inconclusive. Held back: the volume is below the floor."
    );
  });

  test.it("returns null for a verdict it does not know", function () {
    assert.equal(outcome.summaryText({ overall: "great", primary: "cpa" }), null);
    assert.equal(outcome.summaryText({ overall: null }), null);
    assert.equal(outcome.summaryText(null), null);
  });
});

test.describe("noteText", function () {
  test.it("returns null without parts, so the stored note is shown", function () {
    assert.equal(outcome.noteText(null), null);
    assert.equal(outcome.noteText(undefined), null);
  });

  test.it("says the noise band", function () {
    assert.equal(
      outcome.noteText(parts({ kind: "band", noise_pct: 10 })),
      "outcome.note_band|pct=10"
    );
  });

  test.it("says which way is better", function () {
    assert.equal(
      outcome.noteText(parts({ kind: "direction", direction: "lower_is_better" })),
      "outcome.note_lower_is_better"
    );
    assert.equal(
      outcome.noteText(parts({ kind: "direction", direction: "higher_is_better" })),
      "outcome.note_higher_is_better"
    );
  });

  test.it("says a volume metric and a zero baseline", function () {
    assert.equal(outcome.noteText(parts({ kind: "neutral" })), "outcome.note_neutral");
    assert.equal(
      outcome.noteText(parts({ kind: "zero_baseline", zero_baseline: true })),
      "outcome.note_zero_baseline"
    );
  });

  test.it("says the intended direction, then the band it was judged with", function () {
    assert.equal(
      outcome.noteText(parts({ kind: "expected", direction: "up", noise_pct: 10 })),
      "outcome.note_expected|direction=ops_history_section.direction_up" +
        JOIN +
        "outcome.note_noise_band_used|pct=10"
    );
  });

  test.it("says an intended direction judged from a zero baseline", function () {
    assert.equal(
      outcome.noteText(
        parts({
          kind: "expected",
          direction: "up",
          per_day: { before_days: 7, after_days: 7 },
          target: { value: 1000, reached: true, window_total: 5000 },
          zero_baseline: true,
        })
      ),
      [
        "outcome.note_expected|direction=ops_history_section.direction_up",
        "outcome.note_zero_baseline",
        "outcome.note_per_day|before=7,after=7",
        "outcome.note_target_reached|value=" + (1000).toLocaleString(),
        "outcome.note_window_total|value=" + (5000).toLocaleString(),
      ].join(JOIN)
    );
  });

  test.it("never calls a move outside the band 'within' it", function () {
    // What note_parts reads from the stored note
    // "expected up; +30% (noise band ±10%); per day over 7d / 7d;
    //  target 1e+06 not reached (window total 1300)".
    const moved = parts({
      kind: "expected",
      direction: "up",
      noise_pct: 10,
      per_day: { before_days: 7, after_days: 7 },
      target: { value: 1000000, reached: false, window_total: 1300 },
    });
    const en = inLocale("en", function () {
      return outcome.noteText(moved);
    });
    const ja = inLocale("ja", function () {
      return outcome.noteText(moved);
    });
    assert.doesNotMatch(en, /within/);
    assert.doesNotMatch(ja, /の中/);
    assert.match(en, /noise band ±10%/);
    assert.match(ja, /ノイズ幅 ±10%/);
  });

  test.it("puts every part in its order", function () {
    const text = outcome.noteText(
      parts({
        kind: "expected",
        direction: "down",
        noise_pct: 7.5,
        per_day: { before_days: 7, after_days: 14 },
        held_back: "insufficient_volume",
        target: { value: 1000, reached: false, window_total: 1800 },
      })
    );
    assert.deepEqual(text.split(JOIN), [
      "outcome.note_held_back",
      "outcome.note_expected|direction=ops_history_section.direction_down",
      "outcome.note_noise_band_used|pct=" + (7.5).toLocaleString(),
      "outcome.note_per_day|before=7,after=14",
      "outcome.note_target_missed|value=" + (1000).toLocaleString(),
      "outcome.note_window_total|value=" + (1800).toLocaleString(),
    ]);
  });

  test.it("says a reached target, and no window total when there is none", function () {
    assert.equal(
      outcome.noteText(
        parts({
          kind: "expected",
          direction: "down",
          noise_pct: 10,
          target: { value: 60, reached: true, window_total: null },
        })
      ),
      "outcome.note_expected|direction=ops_history_section.direction_down" +
        JOIN +
        "outcome.note_noise_band_used|pct=10" +
        JOIN +
        "outcome.note_target_reached|value=60"
    );
  });

  test.it("says totals compared without periods", function () {
    assert.equal(
      outcome.noteText(parts({ kind: "neutral", raw_totals: true })),
      "outcome.note_neutral" + JOIN + "outcome.note_raw_totals"
    );
  });

  test.it("gives up on a kind it does not know", function () {
    assert.equal(outcome.noteText(parts({ kind: "sideways" })), null);
    assert.equal(outcome.noteText(parts({ kind: "direction", direction: "up" })), null);
  });
});

test.describe("rowRole", function () {
  test.it("takes the row's own role", function () {
    assert.equal(outcome.rowRole({ metric: "cpa", role: "reference" }, {}), "reference");
    assert.equal(
      outcome.rowRole({ metric: "cpa", role: "primary" }, { primary: "ctr" }),
      "primary"
    );
  });

  test.it("reads an older table's primary when the row has no role", function () {
    const table = { primary: "cpa" };
    assert.equal(outcome.rowRole({ metric: "cpa" }, table), "primary");
    assert.equal(outcome.rowRole({ metric: "clicks" }, table), "reference");
  });

  test.it("knows nothing when the table names no primary", function () {
    assert.equal(outcome.rowRole({ metric: "cpa" }, { overall: "improved" }), null);
    assert.equal(outcome.rowRole({ metric: "cpa" }, { primary: null }), null);
    assert.equal(outcome.rowRole({ metric: "cpa" }, null), null);
  });
});
