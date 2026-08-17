// Behavioural tests for mureo/_data/web/reports_logic.js (#540).
//
// Run with:  node --test tests/js/
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/reports_logic.js, no build step and no copy.
// That is the whole point: the Python guards in tests/test_web_assets_*.py
// pin the shape of the assets (a name, a string, a selector) and cannot
// catch an inverted condition, a flipped comparison or a dropped branch.
// The three behaviours below are exactly those failure modes, and each is
// money-safety logic:
//
//   • aggregateClientKpis WITHHOLDS spend/conversions/CPA when the summary
//     reports a double-counted ad account (#533). Inverting that condition
//     puts a figure mureo knows is wrong in front of an operator.
//   • reportsCardFreshness takes the OLDEST contributor, never the newest
//     (#535). Taking the newest lets a fresh sibling vouch for stale data.
//   • the conflict KIND routes to two different findings with two different
//     operator next-moves. Collapsing them loses that.
//
// i18n: MUREO.t is stubbed to return the key it was handed and to record
// the interpolated params, so assertions are on WHICH string was chosen
// (and with what age), not on English wording.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
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

// Loaded AFTER the stub only for tidiness — reports_logic.js reads MUREO
// from the global at call time, so it has no load-order dependency.
const logic = require(path.join(WEB, "reports_logic.js"));

test.beforeEach(function () {
  calls.length = 0;
});

/** Params of the most recent MUREO.t call for `key` ({} if never called). */
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

// ---------------------------------------------------------------------------
// The KPI-withholding condition (#533)
// ---------------------------------------------------------------------------

test.describe("aggregateClientKpis — withholding", function () {
  test.it("sums across genuinely different platforms", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000, conversions: 40 }),
        platform("meta_ads", { spend: 500, conversions: 10 }),
      ],
      platform_conflicts: [],
    });
    assert.equal(kpis.spend, 1500);
    assert.equal(kpis.conversions, 50);
    assert.equal(kpis.cpa, 30);
    assert.equal(kpis.hasFigures, true);
    assert.equal(kpis.doubleCounted, false);
  });

  test.it("withholds every money figure when an account is double-counted", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000, conversions: 40 }),
        platform("google_ads_legacy", { spend: 1000, conversions: 40 }),
      ],
      platform_conflicts: [
        {
          kind: "duplicate_account",
          platform_keys: ["google_ads", "google_ads_legacy"],
        },
      ],
    });
    // The regression this exists for: a doubled 2000 spend reads as a real
    // outlier and gets acted on. No figure is better than a wrong one.
    assert.equal(kpis.spend, null);
    assert.equal(kpis.conversions, null);
    assert.equal(kpis.cpa, null);
    assert.equal(kpis.doubleCounted, true);
    // …but the client DOES have data: the caller must not go re-fetch
    // another period window hoping to find some.
    assert.equal(kpis.hasFigures, true);
  });

  test.it("does not withhold for an unrecognized key alone", function () {
    // A different finding with a different next move. "This entry's identity
    // cannot be established" does not mean the totals on screen are wrong,
    // so collapsing the two kinds would hide real figures for no reason.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("google_ads", { spend: 1000, conversions: 40 }),
        platform("plugin:mystery", { spend: 200, conversions: 10 }),
      ],
      platform_conflicts: [
        { kind: "unrecognized_key", platform_keys: ["plugin:mystery"] },
      ],
    });
    assert.equal(kpis.spend, 1200);
    assert.equal(kpis.conversions, 50);
    assert.equal(kpis.doubleCounted, false);
  });

  test.it("withholds when a duplicate rides along with other kinds", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 10, conversions: 1 })],
      platform_conflicts: [
        { kind: "unrecognized_key", platform_keys: ["plugin:mystery"] },
        { kind: "duplicate_account", platform_keys: ["a", "b"] },
      ],
    });
    assert.equal(kpis.spend, null);
    assert.equal(kpis.doubleCounted, true);
  });

  test.it("ignores a malformed conflict row rather than throwing", function () {
    // platform_keys missing/not an array: the row cannot name anything, so
    // it is not a usable finding. It must neither crash the card nor
    // withhold figures on the strength of a row we cannot render.
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 10, conversions: 2 })],
      platform_conflicts: [{ kind: "duplicate_account" }, null, "nonsense"],
    });
    assert.equal(kpis.doubleCounted, false);
    assert.equal(kpis.spend, 10);
  });

  test.it("treats a summary with no conflicts key as unconflicted", function () {
    // An older daemon or a proxy may not send platform_conflicts at all.
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 10, conversions: 2 })],
    });
    assert.equal(kpis.doubleCounted, false);
    assert.equal(kpis.spend, 10);
  });
});

test.describe("aggregateClientKpis — absent vs zero", function () {
  test.it("reports a missing metric as null, never as 0", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("plugin:advisory", {})],
    });
    assert.equal(kpis.spend, null);
    assert.equal(kpis.conversions, null);
    assert.equal(kpis.cpa, null);
    assert.equal(kpis.hasFigures, false);
  });

  test.it("keeps a real zero as zero", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 0, conversions: 0 })],
    });
    assert.equal(kpis.spend, 0);
    assert.equal(kpis.conversions, 0);
    assert.equal(kpis.hasFigures, true);
  });

  test.it("refuses a CPA when there are no conversions", function () {
    // spend / 0 is Infinity, which would render as a money figure.
    const kpis = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 900, conversions: 0 })],
    });
    assert.equal(kpis.spend, 900);
    assert.equal(kpis.conversions, 0);
    assert.equal(kpis.cpa, null);
  });

  test.it("skips non-numeric and non-finite totals", function () {
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("a", { spend: "1000", conversions: null }),
        platform("b", { spend: Infinity, conversions: NaN }),
        platform("c", { spend: 25, conversions: 5 }),
      ],
    });
    assert.equal(kpis.spend, 25);
    assert.equal(kpis.conversions, 5);
    assert.equal(kpis.cpa, 5);
  });

  test.it("refuses a numeric-STRING metric instead of concatenating it", function () {
    // `+=` on a string does not add, it concatenates: "5" then 3 gives "53",
    // and the CPA computed from it is arithmetic on a corrupted total. A
    // legacy daemon or a proxy emitting quoted numbers is a plausible wire
    // shape, and it takes a SECOND contributing platform for the corruption
    // to appear — which is why `typeof === "number"` cannot be inferred from
    // `isFinite` alone (isFinite("5") and isFinite(null) are both true).
    // Asserted for both metrics: the two guards are siblings, and symmetry
    // between them is not a reason to test only one.
    const kpis = logic.aggregateClientKpis({
      platforms: [
        platform("a", { spend: "10", conversions: "5" }),
        platform("b", { spend: 20, conversions: 3 }),
      ],
    });
    assert.equal(kpis.spend, 20);
    assert.equal(kpis.conversions, 3);
    assert.equal(kpis.cpa, 20 / 3);
    // Type, not just value — "20" would satisfy an == comparison.
    assert.equal(typeof kpis.spend, "number");
    assert.equal(typeof kpis.conversions, "number");
    assert.equal(typeof kpis.cpa, "number");

    // The same shapes alone, with nothing to concatenate onto, are still
    // absent rather than a zero-ish figure.
    const only = logic.aggregateClientKpis({
      platforms: [platform("a", { spend: "10", conversions: "5" })],
    });
    assert.equal(only.spend, null);
    assert.equal(only.conversions, null);
    assert.equal(only.hasFigures, false);
  });

  test.it("survives a null summary and a null platform row", function () {
    assert.equal(logic.aggregateClientKpis(null).hasFigures, false);
    assert.equal(logic.aggregateClientKpis({ platforms: null }).spend, null);
    assert.equal(
      logic.aggregateClientKpis({ platforms: [null, { totals: null }] }).spend,
      null
    );
  });

  test.it("reports hasFigures for a client carrying only ONE of the metrics", function () {
    // hasFigures is not cosmetic: fetchClientCardSummary re-requests another
    // period window when it is false. A spend-only client (no conversion
    // tracking configured — common) has data, so treating "some figures" as
    // "needs both" would send the card off to a different window and show
    // the operator a period they did not select.
    const spendOnly = logic.aggregateClientKpis({
      platforms: [platform("google_ads", { spend: 1000 })],
    });
    assert.equal(spendOnly.hasFigures, true);
    assert.equal(spendOnly.spend, 1000);
    assert.equal(spendOnly.conversions, null);
    assert.equal(spendOnly.cpa, null);

    const convOnly = logic.aggregateClientKpis({
      platforms: [platform("plugin:crm", { conversions: 12 })],
    });
    assert.equal(convOnly.hasFigures, true);
    assert.equal(convOnly.conversions, 12);
    assert.equal(convOnly.spend, null);
    assert.equal(convOnly.cpa, null);
  });
});

// ---------------------------------------------------------------------------
// The freshness aggregation (#535)
// ---------------------------------------------------------------------------

test.describe("reportsCardFreshness", function () {
  test.it("quotes the OLDEST contributor, not the newest", function () {
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("recent", { spend: 1 }, {
          fetched_at: ago(HOUR_MS),
          stale: false,
        }),
        platform("old", { spend: 1 }, {
          fetched_at: ago(10 * DAY_MS),
          stale: false,
        }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_updated");
    assert.equal(fresh.stale, false);
    // An aggregate is only as current as its stalest input: the age quoted
    // must be the 10-day-old row's, not the 1-hour-old sibling's.
    assert.equal(paramsFor("dashboard.reports_platform_updated").ago,
      "dashboard.reports_age_days");
    assert.equal(paramsFor("dashboard.reports_age_days").n, 10);
    assert.equal(paramsFor("dashboard.reports_age_hours"), null);
  });

  test.it("marks the card stale when any contributor is stale", function () {
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("fresh", { spend: 1 }, { fetched_at: ago(HOUR_MS), stale: false }),
        platform("stale", { spend: 1 }, { fetched_at: ago(3 * DAY_MS), stale: true }),
      ],
    });
    // A fresh sibling must never vouch for a stale one.
    assert.equal(fresh.stale, true);
    assert.equal(fresh.text, "dashboard.reports_platform_stale");
    assert.equal(paramsFor("dashboard.reports_age_days").n, 3);
  });

  test.it("ignores platforms that contribute no totals", function () {
    // An advisory bridge adds nothing to the sum, so its absent fetched_at
    // says nothing about the number on screen — it must not drag the card
    // into "unknown".
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("google_ads", { spend: 1 }, { fetched_at: ago(2 * HOUR_MS), stale: false }),
        { key: "plugin:advisory", totals: null, freshness: null },
        { key: "plugin:advisory2" },
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_updated");
    assert.equal(fresh.stale, false);
    assert.equal(paramsFor("dashboard.reports_age_hours").n, 2);
  });

  test.it("says 'unknown' — not 'fresh' — when a contributor has no age", function () {
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("known", { spend: 1 }, { fetched_at: ago(HOUR_MS), stale: false }),
        platform("nameless", { spend: 1 }, null),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
    assert.equal(fresh.stale, false);
  });

  test.it("a known fetched_at with an UNKNOWN stale flag is still unknown", function () {
    // The nastiest shape on this wire: the row HAS a timestamp, so it looks
    // answerable, but the server did not say whether it is stale. `stale`
    // is resolved server-side against the window the figure covers; a null
    // means "not computed", never "fine". Letting the timestamp alone carry
    // the row would quote a confident "Updated 2h ago" for an aggregate
    // whose staleness nobody established — the exact reassurance #535 says
    // must not be invented. Its fresh sibling must not cover for it either.
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("answered", { spend: 1 }, {
          fetched_at: ago(2 * HOUR_MS),
          stale: false,
        }),
        platform("unanswered", { spend: 1 }, {
          fetched_at: ago(HOUR_MS),
          stale: null,
        }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
    assert.equal(fresh.stale, false);
    // …and no age was quoted at all, from either row.
    assert.equal(paramsFor("dashboard.reports_platform_updated"), null);
  });

  test.it("a contributor with no fetched_at is unknown even beside a dated one", function () {
    // Same masking risk from the other side: `stale` is answered but the
    // timestamp is absent. Without a dated sibling the card lands on
    // "unknown" anyway (there is no age to quote); WITH one, dropping this
    // guard would let the sibling's age stand in for the whole aggregate.
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("dated", { spend: 1 }, { fetched_at: ago(3 * HOUR_MS), stale: false }),
        platform("undated", { spend: 1 }, { fetched_at: null, stale: false }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
    assert.equal(fresh.stale, false);
    assert.equal(paramsFor("dashboard.reports_platform_updated"), null);
  });

  test.it("says stale-partial when something is stale AND something is unknown", function () {
    // The mixed case: we know something IS stale, but we cannot honestly
    // quote an age. "Unknown" in stale-red would be a lie in both halves.
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("stale", { spend: 1 }, { fetched_at: ago(4 * DAY_MS), stale: true }),
        platform("nameless", { spend: 1 }, { fetched_at: null, stale: null }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_stale_partial");
    assert.equal(fresh.stale, true);
  });

  test.it("accepts only a plain object as a contributor's freshness", function () {
    // Same guard as reportsFreshnessLabel's, and it has to be repeated here
    // because the aggregation loop reads the block directly rather than
    // going through the label helper.
    const callable = function () {};
    callable.fetched_at = ago(HOUR_MS);
    callable.stale = false;
    const fresh = logic.reportsCardFreshness({
      platforms: [platform("odd", { spend: 1 }, callable)],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
    assert.equal(fresh.stale, false);
  });

  test.it("treats an unparseable fetched_at as no age at all", function () {
    const fresh = logic.reportsCardFreshness({
      platforms: [platform("bad", { spend: 1 }, { fetched_at: "yesterday", stale: true })],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_stale_partial");
    assert.equal(fresh.stale, true);
  });

  test.it("survives a null or non-object platform row", function () {
    // `Array.isArray` guards the LIST, not its elements. This runs inside a
    // forEach with no try/catch: a throw here escapes buildClientCard and,
    // through the Promise.all in renderReportsIndex, blanks the whole client
    // grid rather than one card. Its twin in aggregateClientKpis is tested;
    // this one is the same hazard on the same wire.
    const fresh = logic.reportsCardFreshness({
      platforms: [
        null,
        undefined,
        "nonsense",
        7,
        platform("real", { spend: 1 }, { fetched_at: ago(2 * HOUR_MS), stale: false }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_updated");
    assert.equal(fresh.stale, false);
    assert.equal(paramsFor("dashboard.reports_age_hours").n, 2);
  });

  test.it("treats an OMITTED stale key exactly like an explicit null", function () {
    // `stale` is optional and writer-dependent, so "the key is not there" is
    // the shape a real writer produces — not the explicit null every other
    // test here passes. `== null` covers both; `===` would cover only the
    // explicit one and let the omitted case read as answered-and-fresh.
    const fresh = logic.reportsCardFreshness({
      platforms: [
        platform("dated", { spend: 1 }, { fetched_at: ago(2 * HOUR_MS) }),
        platform("answered", { spend: 1 }, {
          fetched_at: ago(HOUR_MS),
          stale: false,
        }),
      ],
    });
    assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
    assert.equal(fresh.stale, false);
    assert.equal(paramsFor("dashboard.reports_platform_updated"), null);
  });

  test.it("returns unknown-and-not-stale for a client with no platforms", function () {
    for (const summary of [null, {}, { platforms: [] }, { platforms: "no" }]) {
      const fresh = logic.reportsCardFreshness(summary);
      assert.equal(fresh.text, "dashboard.reports_platform_age_unknown");
      assert.equal(fresh.stale, false);
    }
  });
});

test.describe("reportsFreshnessLabel", function () {
  test.it("reads a null stale flag as unknown rather than fresh", function () {
    // fetched_at is optional and writer-dependent, so "we were not told"
    // is its own state. Calling it fresh would be an invented reassurance.
    const label = logic.reportsFreshnessLabel({ fetched_at: ago(HOUR_MS), stale: null });
    assert.equal(label.text, "dashboard.reports_platform_age_unknown");
    assert.equal(label.stale, false);
  });

  test.it("reads an OMITTED stale key the same way", function () {
    // The shape a writer that simply does not compute staleness produces.
    // `== null` is doing the work here; `===` would read this as answered.
    const label = logic.reportsFreshnessLabel({ fetched_at: ago(HOUR_MS) });
    assert.equal(label.text, "dashboard.reports_platform_age_unknown");
    assert.equal(label.stale, false);
  });

  test.it("reads a missing block or missing fetched_at as unknown", function () {
    for (const input of [null, undefined, "nope", {}, { stale: false }]) {
      const label = logic.reportsFreshnessLabel(input);
      assert.equal(label.text, "dashboard.reports_platform_age_unknown");
      assert.equal(label.stale, false);
    }
  });

  test.it("accepts only a plain object as a freshness block", function () {
    // `typeof f === "object"` is not redundant with the property checks
    // below it: something callable can carry `fetched_at`/`stale` and would
    // otherwise be read as a real freshness block. JSON cannot produce one
    // today, so this is the guard holding the line for the first caller
    // that builds a summary in-process instead of parsing one off the wire.
    const callable = function () {};
    callable.fetched_at = ago(HOUR_MS);
    callable.stale = false;
    const label = logic.reportsFreshnessLabel(callable);
    assert.equal(label.text, "dashboard.reports_platform_age_unknown");
    assert.equal(label.stale, false);
  });

  test.it("distinguishes stale from updated", function () {
    const stale = logic.reportsFreshnessLabel({ fetched_at: ago(2 * DAY_MS), stale: true });
    assert.equal(stale.text, "dashboard.reports_platform_stale");
    assert.equal(stale.stale, true);

    const ok = logic.reportsFreshnessLabel({ fetched_at: ago(2 * DAY_MS), stale: false });
    assert.equal(ok.text, "dashboard.reports_platform_updated");
    assert.equal(ok.stale, false);
  });
});

test.describe("relativeAge", function () {
  test.it("buckets an age into the coarse unit it belongs to", function () {
    assert.equal(logic.relativeAge(ago(5000)), "dashboard.reports_age_just_now");
    assert.equal(logic.relativeAge(ago(5 * 60 * 1000)), "dashboard.reports_age_minutes");
    assert.equal(paramsFor("dashboard.reports_age_minutes").n, 5);
    assert.equal(logic.relativeAge(ago(5 * HOUR_MS)), "dashboard.reports_age_hours");
    assert.equal(paramsFor("dashboard.reports_age_hours").n, 5);
    assert.equal(logic.relativeAge(ago(5 * DAY_MS)), "dashboard.reports_age_days");
    assert.equal(paramsFor("dashboard.reports_age_days").n, 5);
  });

  test.it("never throws on absent or unparseable input", function () {
    assert.equal(logic.relativeAge(null), "");
    assert.equal(logic.relativeAge(""), "");
    assert.equal(logic.relativeAge("not-a-date"), "not-a-date");
  });

  test.it("clamps a future timestamp to 'just now' instead of a negative age", function () {
    assert.equal(
      logic.relativeAge(new Date(Date.now() + 5 * DAY_MS).toISOString()),
      "dashboard.reports_age_just_now"
    );
  });
});

// ---------------------------------------------------------------------------
// Conflict-kind routing
// ---------------------------------------------------------------------------

test.describe("conflict kinds", function () {
  const DUP = { kind: "duplicate_account", platform_keys: ["google_ads", "gads_legacy"] };
  // `account_known` is what splits the unrecognised-key note in two (#606):
  // true means the entry named an ad account mureo could resolve, so only
  // the PLATFORM is unknown; false means the entry named none, which is the
  // one shape where "this may be a duplicate mureo cannot see" is true.
  const UNK = {
    kind: "unrecognized_key",
    platform_keys: ["plugin:mystery"],
    account_known: true,
  };
  const summary = {
    platforms: [
      { key: "google_ads", display_name: "Google Ads" },
      { key: "gads_legacy" },
    ],
    platform_conflicts: [DUP, UNK],
  };

  test.it("keeps the two findings on separate strings", function () {
    const labels = logic.reportsPlatformLabels(summary);
    assert.equal(
      logic.reportsConflictText(DUP, labels),
      "dashboard.reports_conflict_double_counted"
    );
    assert.equal(
      logic.reportsConflictText(UNK, labels),
      "dashboard.reports_conflict_unknown_key"
    );
  });

  test.it("splits the unrecognised-key note on whether the account is known", function () {
    // #606: the condition behind `unrecognized_key` never looked at the
    // account id, so ONE string claimed the ad account could not be
    // identified even for an entry whose id `duplicate_account` had just
    // reported with certainty. Two strings, chosen on the fact itself.
    const labels = logic.reportsPlatformLabels(summary);
    const noAccount = {
      kind: "unrecognized_key",
      platform_keys: ["plugin:mystery"],
      account_known: false,
    };
    assert.equal(
      logic.reportsConflictText(noAccount, labels),
      "dashboard.reports_conflict_unknown_key_no_account"
    );
    assert.equal(
      paramsFor("dashboard.reports_conflict_unknown_key_no_account").keys,
      "plugin:mystery"
    );
  });

  test.it("keeps the review-by-hand wording when the field is absent", function () {
    // A summary from an older or out-of-tree producer says nothing about
    // the account. Unknown is not "known", so the cautious string — the one
    // that tells the operator to check by hand — stays the answer.
    const labels = logic.reportsPlatformLabels(summary);
    for (const account_known of [undefined, null, "yes", 1]) {
      const row = {
        kind: "unrecognized_key",
        platform_keys: ["plugin:mystery"],
        account_known: account_known,
      };
      assert.equal(
        logic.reportsConflictText(row, labels),
        "dashboard.reports_conflict_unknown_key_no_account"
      );
    }
  });

  test.it("gives one key in BOTH findings two notes that agree", function () {
    // The #606 report: two unrecognisable keys under one ad account, so the
    // same key carries a duplicate_account row AND an unrecognized_key row.
    // The pair must not assert opposite facts about that account.
    const bothDup = {
      kind: "duplicate_account",
      platform_keys: ["ads_key_a", "ads_key_b"],
      account_known: true,
    };
    const bothUnkA = {
      kind: "unrecognized_key",
      platform_keys: ["ads_key_a"],
      account_known: true,
    };
    const bothSummary = {
      platforms: [{ key: "ads_key_a" }, { key: "ads_key_b" }],
      platform_conflicts: [bothDup, bothUnkA],
    };
    const rows = logic.reportsConflictsForKey(bothSummary, "ads_key_a");
    assert.deepEqual(rows, [bothDup, bothUnkA]);

    const labels = logic.reportsPlatformLabels(bothSummary);
    const texts = rows.map(function (row) {
      return logic.reportsConflictText(row, labels);
    });
    assert.deepEqual(texts, [
      "dashboard.reports_conflict_double_counted",
      "dashboard.reports_conflict_unknown_key",
    ]);
    // Specifically NOT the string that says the ad account cannot be
    // identified — the note above it just identified it.
    assert.ok(!texts.includes("dashboard.reports_conflict_unknown_key_no_account"));
  });

  test.it("names the platforms the way the rest of the view does", function () {
    const labels = logic.reportsPlatformLabels(summary);
    logic.reportsConflictText(DUP, labels);
    // display_name where the summary has one, raw key where it does not —
    // a conflict must never name a platform the operator cannot find.
    assert.equal(
      paramsFor("dashboard.reports_conflict_double_counted").keys,
      "Google Ads, gads_legacy"
    );
  });

  test.it("falls back to the raw key at BOTH levels independently", function () {
    // reportsPlatformLabels and reportsKeyList each fall back to the raw
    // key, and end-to-end either one alone is enough — which means testing
    // only through reportsConflictText lets one of them be deleted with the
    // suite still green. Pin them separately so neither can mask the other.
    // What is at stake is small but real: a conflict note reading
    // "undefined is double-counted" names nothing the operator can act on.
    const labels = logic.reportsPlatformLabels(summary);
    assert.equal(labels.google_ads, "Google Ads");
    assert.equal(labels.gads_legacy, "gads_legacy", "no display_name fallback");

    assert.equal(logic.reportsKeyList(["plugin:mystery"], labels), "plugin:mystery");
    assert.equal(logic.reportsKeyList(["google_ads"], labels), "Google Ads");
    assert.equal(logic.reportsKeyList(["a", "b"], null), "a, b");
  });

  test.it("builds labels from a summary that is missing or malformed", function () {
    // fetchClientCardSummary yields `{}` on any fetch failure, and these run
    // during a render — a throw here blanks the whole Reports view.
    for (const bad of [null, undefined, {}, { platforms: null }, { platforms: "x" }]) {
      assert.deepEqual(logic.reportsPlatformLabels(bad), {});
    }
    assert.deepEqual(
      logic.reportsPlatformLabels({ platforms: [null, { key: 7 }, {}] }),
      {}
    );
    assert.deepEqual(logic.reportsKeyList(null, {}), "");
    assert.deepEqual(logic.reportsKeyList(undefined, {}), "");
  });

  test.it("selects by kind and only from rows that name platforms", function () {
    const dups = logic.reportsConflictsOfKind(summary, "duplicate_account");
    assert.equal(dups.length, 1);
    assert.equal(dups[0], DUP);
    assert.equal(logic.reportsConflictsOfKind(summary, "unrecognized_key").length, 1);
    assert.equal(logic.reportsConflictsOfKind(summary, "made_up").length, 0);
    assert.equal(logic.reportsConflictsOfKind(null, "duplicate_account").length, 0);
    assert.equal(
      logic.reportsConflictsOfKind(
        { platform_conflicts: [{ kind: "duplicate_account", platform_keys: "gads" }] },
        "duplicate_account"
      ).length,
      0
    );
  });

  test.it("flags a double count only for the duplicate kind", function () {
    assert.equal(logic.reportsHasDoubleCount(summary), true);
    assert.equal(
      logic.reportsHasDoubleCount({ platform_conflicts: [UNK] }),
      false
    );
    assert.equal(logic.reportsHasDoubleCount({ platform_conflicts: [] }), false);
  });

  test.it("hands every conflict naming a key to that platform's card", function () {
    // The index card only renders for multi-client installs, so the
    // per-platform card is the only surface a single-client setup sees.
    assert.deepEqual(logic.reportsConflictsForKey(summary, "gads_legacy"), [DUP]);
    assert.deepEqual(logic.reportsConflictsForKey(summary, "plugin:mystery"), [UNK]);
    assert.deepEqual(logic.reportsConflictsForKey(summary, "meta_ads"), []);
    assert.deepEqual(logic.reportsConflictsForKey(null, "google_ads"), []);
  });

  test.it("exposes the wire vocabulary it routes on", function () {
    assert.equal(logic.REPORTS_CONFLICT_DUPLICATE_ACCOUNT, "duplicate_account");
    assert.equal(logic.REPORTS_CONFLICT_UNRECOGNIZED_KEY, "unrecognized_key");
  });

  // #636: the card does not merely report a double-counted account, it
  // WITHHOLDS the client's totals until it is gone — so the hint under it
  // has to name the command that ends it. A duplicate is resolved by the
  // operator naming the losing key (`--drop-duplicate`); every other finding
  // still has only the survey command to offer, and the two must not be
  // collapsed into one string.
  test.it("points a duplicate at the command that resolves it", function () {
    assert.equal(
      logic.reportsRepairHint([DUP]),
      "dashboard.reports_conflict_duplicate_repair_hint"
    );
    assert.equal(
      logic.reportsRepairHint([UNK]),
      "dashboard.reports_conflict_repair_hint"
    );
    // A card carrying both findings is a card whose totals are withheld.
    assert.equal(
      logic.reportsRepairHint([UNK, DUP]),
      "dashboard.reports_conflict_duplicate_repair_hint"
    );
  });

  test.it("never throws on a malformed conflict list", function () {
    // These run during a render; a throw here blanks the Reports view.
    for (const bad of [null, undefined, "rows", [null], [{}], [{ kind: 7 }]]) {
      assert.equal(
        logic.reportsRepairHint(bad),
        "dashboard.reports_conflict_repair_hint"
      );
    }
  });
});

// ---------------------------------------------------------------------------
// The strings this logic selects have to exist
// ---------------------------------------------------------------------------

test.describe("i18n", function () {
  test.it("only ever selects keys that ship in both locales", function () {
    const data = JSON.parse(fs.readFileSync(path.join(WEB, "i18n.json"), "utf-8"));
    // Drive every branch that reaches MUREO.t, then check the keys exist.
    logic.reportsCardFreshness({
      platforms: [
        { key: "a", totals: { spend: 1 }, freshness: { fetched_at: ago(DAY_MS), stale: false } },
      ],
    });
    logic.reportsCardFreshness({
      platforms: [
        { key: "a", totals: { spend: 1 }, freshness: { fetched_at: ago(DAY_MS), stale: true } },
        { key: "b", totals: { spend: 1 }, freshness: null },
      ],
    });
    logic.reportsCardFreshness({ platforms: [{ key: "b", totals: {}, freshness: null }] });
    logic.relativeAge(ago(1000));
    logic.relativeAge(ago(60 * 1000));
    logic.relativeAge(ago(HOUR_MS));
    logic.reportsConflictText({ kind: "duplicate_account", platform_keys: [] }, {});
    logic.reportsConflictText({ kind: "unrecognized_key", platform_keys: [] }, {});
    logic.reportsRepairHint([{ kind: "duplicate_account", platform_keys: [] }]);
    logic.reportsRepairHint([{ kind: "unrecognized_key", platform_keys: [] }]);

    assert.ok(calls.length > 0, "no i18n key was selected at all");
    for (const call of calls) {
      for (const locale of ["en", "ja"]) {
        assert.ok(
          data[locale] && data[locale][call.key],
          `${call.key} missing from i18n.json[${locale}]`
        );
      }
    }
  });
});
