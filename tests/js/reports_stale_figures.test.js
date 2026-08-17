// Behavioural tests for the stale-figure withholding in
// mureo/_data/web/reports_logic.js (#638).
//
// Run with:  node --test tests/js/*.test.js
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/reports_logic.js, no build step and no copy.
// Its sibling reports_logic.test.js covers the double-count withholding
// (#533) and the freshness aggregation (#535); this file covers the third
// money-safety decision built on top of them, and lives apart because it is
// one regression with one story:
//
//   A client card rendered 25,862 cost / 2 conversions / 12,931 CPA in bold
//   as the selected window's figures. That window's real cost was 0 —
//   delivery had stopped eleven days earlier and the rollup had not been
//   refreshed since. The disclosure was a small badge beside the numbers,
//   and the operator read the numbers. Staleness is the same class of
//   problem as a double-counted account — mureo cannot vouch for the figure
//   — so it now gets the same treatment: withheld from the position that
//   asserts the window, and restated separately with its age.
//
// i18n: MUREO.t is stubbed to return the key it was handed and to record
// the interpolated params, so assertions are on WHICH string was chosen
// (and with what age), not on English wording.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

/** Every MUREO.t(key, params) the code under test made, most recent last. */
const calls = [];

globalThis.MUREO = {
  t: function (key, params) {
    calls.push({ key: key, params: params || {} });
    return key;
  },
};

const logic = require(path.join(WEB, "reports_logic.js"));

test.beforeEach(function () {
  calls.length = 0;
});

/** Params of the most recent MUREO.t call for `key` (null if never called). */
function paramsFor(key) {
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    if (calls[i].key === key) return calls[i].params;
  }
  return null;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

/** An ISO timestamp `ms` in the past, relative to now. */
function ago(ms) {
  return new Date(Date.now() - ms).toISOString();
}

/** A platform row that contributes totals to the aggregate. */
function platform(key, totals, freshness) {
  return {
    key: key,
    display_name: key.replace("_", " "),
    totals: totals,
    freshness: freshness,
  };
}

test.describe("aggregateClientKpis — stale figures", function () {
  test.it("withholds every figure when a contributor is stale", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 25862, conversions: 2 }, {
          fetched_at: ago(11 * DAY_MS),
          stale: true,
        }),
      ],
    });
    // The regression this exists for: 25,862 was rendered as the selected
    // window's cost while that window's real cost was 0.
    assert.equal(kpis.spend, null);
    assert.equal(kpis.conversions, null);
    assert.equal(kpis.cpa, null);
    assert.equal(kpis.stale, true);
    // Nothing is hidden — the figure is restated as what it IS.
    assert.equal(kpis.staleFigures.spend, 25862);
    assert.equal(kpis.staleFigures.conversions, 2);
    assert.equal(kpis.staleFigures.cpa, 12931);
    assert.equal(typeof kpis.staleFigures.fetched_at, "string");
    // …and the client still HAS data, so no caller goes hunting in another
    // window for figures that are merely withheld.
    assert.equal(kpis.hasFigures, true);
  });

  test.it("leaves a fresh aggregate exactly as it was", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000, conversions: 40 }, {
          fetched_at: ago(HOUR_MS),
          stale: false,
        }),
        platform("meta_ads", { spend: 500, conversions: 10 }, {
          fetched_at: ago(2 * HOUR_MS),
          stale: false,
        }),
      ],
    });
    assert.equal(kpis.spend, 1500);
    assert.equal(kpis.conversions, 50);
    assert.equal(kpis.cpa, 30);
    assert.equal(kpis.stale, false);
    assert.equal(kpis.staleFigures, null);
  });

  test.it("does not withhold when staleness is UNKNOWN", function () {
    // `stale: null` means fetched_at was absent or unparseable — a real
    // state, not a verdict. Withholding on it would blank most cards for
    // documents written before #637 stamped the field.
    for (const freshness of [null, {}, { fetched_at: ago(DAY_MS) }, {
      fetched_at: ago(DAY_MS),
      stale: null,
    }]) {
      const kpis = logic.aggregateClientKpis({
        platforms: [platform("google_ads", { spend: 10, conversions: 2 }, freshness)],
      });
      assert.equal(kpis.spend, 10);
      assert.equal(kpis.conversions, 2);
      assert.equal(kpis.stale, false);
      assert.equal(kpis.staleFigures, null);
    }
  });

  test.it("a fresh sibling cannot vouch for a stale one", function () {
    // The aggregate is a single number and one of its inputs is not the
    // window's answer, so the sum is not either.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000, conversions: 40 }, {
          fetched_at: ago(HOUR_MS),
          stale: false,
        }),
        platform("meta_ads", { spend: 500, conversions: 10 }, {
          fetched_at: ago(30 * DAY_MS),
          stale: true,
        }),
      ],
    });
    assert.equal(kpis.spend, null);
    assert.equal(kpis.stale, true);
    assert.equal(kpis.staleFigures.spend, 1500);
  });

  test.it("quotes the OLDEST stale contributor's age", function () {
    // Same rule as reportsCardFreshness: an aggregate is only as current as
    // its stalest input, so the age beside the restated figures is that
    // one's, never the least-bad of them.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("recent_stale", { spend: 1 }, {
          fetched_at: ago(3 * DAY_MS),
          stale: true,
        }),
        platform("older_stale", { spend: 1 }, {
          fetched_at: ago(40 * DAY_MS),
          stale: true,
        }),
      ],
    });
    assert.equal(logic.relativeAge(kpis.staleFigures.fetched_at),
      "dashboard.reports_age_days");
    assert.equal(paramsFor("dashboard.reports_age_days").n, 40);
  });

  test.it("ignores a stale platform that contributes no totals", function () {
    // An advisory bridge adds nothing to the sum, so its age says nothing
    // about the number on screen — exactly as reportsCardFreshness has it.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 10, conversions: 2 }, {
          fetched_at: ago(HOUR_MS),
          stale: false,
        }),
        { key: "plugin:advisory", totals: null, freshness: { stale: true } },
      ],
    });
    assert.equal(kpis.spend, 10);
    assert.equal(kpis.stale, false);
  });

  test.it("restates nothing when the sum is ALSO double-counted", function () {
    // A doubled figure is wrong at every age. Restating it beside its age
    // would put the wrong number back on the card under a softer label.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000 }, {
          fetched_at: ago(40 * DAY_MS),
          stale: true,
        }),
        platform("google_ads_legacy", { spend: 1000 }, {
          fetched_at: ago(40 * DAY_MS),
          stale: true,
        }),
      ],
      platform_conflicts: [
        { kind: "duplicate_account", platform_keys: ["google_ads", "google_ads_legacy"] },
      ],
    });
    assert.equal(kpis.spend, null);
    assert.equal(kpis.doubleCounted, true);
    assert.equal(kpis.stale, true);
    assert.equal(kpis.staleFigures, null);
  });

  test.it("withholds even when the age itself is unquotable", function () {
    // `stale: true` with no usable timestamp cannot come from mureo's own
    // reader, but a proxy could produce it. The verdict is the authority:
    // withhold, and say the age is unknown rather than invent one.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 10, conversions: 2 }, {
          fetched_at: null,
          stale: true,
        }),
      ],
    });
    assert.equal(kpis.spend, null);
    assert.equal(kpis.stale, true);
    assert.equal(kpis.staleFigures.spend, 10);
    assert.equal(kpis.staleFigures.fetched_at, null);
  });

  test.it("survives a malformed freshness block rather than throwing", function () {
    const callable = function () {};
    callable.stale = true;
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("odd", { spend: 10 }, callable),
        platform("odder", { spend: 5 }, "nonsense"),
      ],
    });
    assert.equal(kpis.spend, 15);
    assert.equal(kpis.stale, false);
  });
});

test.describe("reportsRowIsStale", function () {
  test.it("is true only for a row mureo judged stale", function () {
    assert.equal(
      logic.reportsRowIsStale(platform("g", { spend: 1 }, {
        fetched_at: ago(11 * DAY_MS),
        stale: true,
      })),
      true
    );
  });

  test.it("is false for fresh, for unknown, and for junk", function () {
    // `stale == null` is unknown, and unknown keeps its existing rendering
    // (#637): the platform card still shows its figures and says the update
    // time is unknown.
    const rows = [
      platform("g", { spend: 1 }, { fetched_at: ago(HOUR_MS), stale: false }),
      platform("g", { spend: 1 }, { fetched_at: ago(HOUR_MS), stale: null }),
      platform("g", { spend: 1 }, { fetched_at: ago(HOUR_MS) }),
      platform("g", { spend: 1 }, null),
      platform("g", { spend: 1 }, "nonsense"),
      null,
      undefined,
      "nonsense",
      {},
    ];
    rows.forEach(function (row) {
      assert.equal(logic.reportsRowIsStale(row), false);
    });
  });
});
