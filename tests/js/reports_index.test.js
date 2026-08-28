// Behavioural tests for the list screen's model (#715).
//
// Run with:  node --test tests/js/*.test.js
//
// These EXECUTE the shipped bytes — `require` loads the same files the
// browser gets over /static/, no build step and no copy.
//
// `buildReportsIndexModel` is the one place the Reports index decides what it
// is about to say: the alert layer, each client's health, the health split,
// the band and the portfolio figures. It was extracted so those five stop
// being recomputed by whoever happens to draw them next — which is only worth
// doing if the extraction can be shown to have changed no answer.
//
// So NOTHING here is asserted against a literal health. Every case compares
// the model against the SAME lower-level function run independently:
// `triageClientHealth` per client, `triageHealthCounts` over the grid,
// `buildReportsHero`, `buildReportsPortfolio`, `buildReportsTriage`. A
// literal would pass just as happily if the model quietly stopped consulting
// the triage layer at all, which is the exact failure this file exists for.
//
// The second half is the defensive surface. This runs mid-render over
// payloads that may come from an older daemon, and a throw here blanks the
// whole Reports view — so a roster that is not an array, a summaries array
// shorter than its roster, and a health vocabulary the triage layer does not
// recognise all have to land somewhere sane rather than nowhere.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

globalThis.MUREO = {
  t: function (key) {
    return key;
  },
};

// The pure modules, as the browser has them: one shared global, each file
// publishing onto it and reading its peers off it at CALL time. Loading them
// in app.html's order is the module's dependency, not a test fixture.
globalThis.window = globalThis;
require(path.join(WEB, "reports_logic.js"));
require(path.join(WEB, "reports_format.js"));
const triage = require(path.join(WEB, "reports_triage.js"));
const overview = require(path.join(WEB, "reports_overview.js"));
const hero = require(path.join(WEB, "reports_hero.js"));
const index = require(path.join(WEB, "reports_index.js"));

const DAY = 86400000;
const ago = (d) => new Date(Date.now() - d * DAY).toISOString();
const TODAY = new Date().toISOString().slice(0, 10);

//: The three verdicts the triage layer produces. Stated rather than
//: imported because reports_triage.js keeps the array private — a model
//: entry outside this set is a health nothing in the product can paint.
const HEALTHS = ["attention", "watch", "ok"];

/**
 * One client's summary, shaped by what the TRIAGE LAYER makes of it — the
 * only thing that decides a client's health anywhere in this product:
 *   stale — its figures are eleven days old, so its totals are withheld
 *   due   — a review mureo owes is past due
 *   ok    — nothing raised
 *   idle  — nothing raised and no figures at all (the band's fourth block)
 */
function summaryFor(slug, kind) {
  const platform = {
    key: "google_ads",
    display_name: "Google Ads",
    totals: { spend: 42000, conversions: 12, cpa: 3500, clicks: 900, impressions: 40000 },
    metrics_period: "YESTERDAY",
    campaign_count: 2,
    freshness: {
      fetched_at: ago(kind === "stale" ? 11 : 0),
      stale: kind === "stale",
      stale_after_days: 2,
    },
    not_collected: null,
    daily: [],
    daily_delta: null,
  };
  return {
    client: slug,
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: ago(0),
    platforms: kind === "idle" ? [] : [platform],
    platform_conflicts: [],
    recent_actions: [],
    reports: {},
    observations_due: kind === "due" ? { count: 1, oldest_due: TODAY } : { count: 0 },
    display: null,
    server_today: TODAY,
  };
}

const ROSTER = [
  { slug: "alpha", name: "Alpha Trading", active: true },
  { slug: "bravo", name: "Bravo Logistics", active: true },
  { slug: "carol", name: "Carol Foods", active: true },
  { slug: "delta", name: "Delta Studio", active: true },
];

const KINDS = ["stale", "due", "ok", "idle"];

const SUMMARIES = ROSTER.map(function (c, i) {
  return summaryFor(c.slug, KINDS[i]);
});

test.describe("the model is the triage layer's own answers, not a copy", function () {
  test.it("builds the same alert layer the renderers would have built", function () {
    const model = index.buildReportsIndexModel(ROSTER, SUMMARIES);
    assert.deepEqual(model.triage, triage.buildReportsTriage(ROSTER, SUMMARIES));
  });

  test.it("grades every client exactly as triageClientHealth does", function () {
    // The property the whole extraction rests on: the array IS the function's
    // answer, position by position. A model that graded the roster itself —
    // or that fell back to "ok" for a client it could not place — would be a
    // second opinion beside the cards, and this is where it shows up.
    const model = index.buildReportsIndexModel(ROSTER, SUMMARIES);
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    assert.equal(model.healthByIndex.length, ROSTER.length);
    ROSTER.forEach(function (_client, i) {
      assert.equal(
        model.healthByIndex[i],
        triage.triageClientHealth(built, i),
        "client " + i + " is graded twice and differently"
      );
      assert.ok(HEALTHS.includes(model.healthByIndex[i]));
    });
    // …and the roster really does exercise more than one verdict, or the
    // assertion above would hold for any constant.
    assert.ok(new Set(model.healthByIndex).size > 1, "the fixture grades nothing");
  });

  test.it("splits the grid exactly as triageHealthCounts does unaided", function () {
    // The counts are built from the precomputed array; this compares them
    // against the two-argument call, which scans the layer itself. The whole
    // point of the third argument is that these two can never differ.
    const model = index.buildReportsIndexModel(ROSTER, SUMMARIES);
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    assert.deepEqual(
      model.healthCounts,
      triage.triageHealthCounts(built, ROSTER.length)
    );
    // The chips count the WHOLE grid, marked or not.
    assert.equal(model.healthCounts.all, ROSTER.length);
    assert.equal(
      model.healthCounts.attention + model.healthCounts.watch + model.healthCounts.ok,
      ROSTER.length
    );
  });

  test.it("hands the band the counts and the verdicts it was given", function () {
    const model = index.buildReportsIndexModel(ROSTER, SUMMARIES);
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    const counts = triage.triageHealthCounts(built, ROSTER.length);
    assert.deepEqual(
      model.hero,
      hero.buildReportsHero(counts, SUMMARIES, function (i) {
        return triage.triageClientHealth(built, i);
      })
    );
    // The fourth block is carved out of OK, so the band cannot be identical
    // to the chips — which is what makes the comparison above worth making.
    assert.equal(model.hero.idle, 1);
    assert.equal(model.hero.ok, model.healthCounts.ok - model.hero.idle);
  });

  test.it("builds the portfolio strip from the cards' own summaries", function () {
    const model = index.buildReportsIndexModel(ROSTER, SUMMARIES);
    assert.deepEqual(
      model.portfolio,
      overview.buildReportsPortfolio(ROSTER, SUMMARIES)
    );
    // The strip states over how many clients it holds — and the count the
    // health split is taken over is that same roster.
    assert.equal(model.portfolio.total, model.healthCounts.all);
  });
});

test.describe("a payload an older daemon could send", function () {
  test.it("treats a roster that is not an array as an empty one", function () {
    // A throw here blanks the whole Reports view.
    [null, undefined, "alpha", 3, {}].forEach(function (rows) {
      const model = index.buildReportsIndexModel(rows, SUMMARIES);
      assert.deepEqual(model.healthByIndex, []);
      assert.equal(model.healthCounts.all, 0);
      assert.equal(model.portfolio.total, 0);
      assert.equal(model.hero.show, false);
      assert.deepEqual(model.triage.items, []);
      assert.deepEqual(model.triage.clients, []);
    });
  });

  test.it("treats summaries that are not an array as none received", function () {
    [null, undefined, "yesterday", {}].forEach(function (summaries) {
      const model = index.buildReportsIndexModel(ROSTER, summaries);
      // Still one entry per client — the grid is the roster, not the fetches.
      assert.equal(model.healthByIndex.length, ROSTER.length);
      assert.equal(model.healthCounts.all, ROSTER.length);
      assert.deepEqual(
        model.healthByIndex,
        index.buildReportsIndexModel(ROSTER, []).healthByIndex
      );
    });
  });

  test.it("keeps one entry per client when a fetch is missing", function () {
    // `fetchClientCardSummary` yields null for a request that failed, and a
    // short array is the same absence one step further along. Neither may
    // shorten the grid, because the cards are drawn from the roster.
    const short = [SUMMARIES[0], SUMMARIES[1]];
    const model = index.buildReportsIndexModel(ROSTER, short);
    assert.equal(model.healthByIndex.length, ROSTER.length);
    assert.equal(model.healthCounts.all, ROSTER.length);
    const built = triage.buildReportsTriage(ROSTER, short);
    ROSTER.forEach(function (_client, i) {
      assert.equal(model.healthByIndex[i], triage.triageClientHealth(built, i));
    });
    // A summary that never arrived is not evidence about an ad account, so
    // it is neither an alert nor a figure — but it is still a card.
    assert.equal(model.portfolio.total, ROSTER.length);
  });

  test.it("ignores summaries for clients that are not on the grid", function () {
    const extra = SUMMARIES.concat([summaryFor("echo", "stale")]);
    const model = index.buildReportsIndexModel(ROSTER, extra);
    assert.equal(model.healthByIndex.length, ROSTER.length);
    assert.deepEqual(
      model.healthCounts,
      index.buildReportsIndexModel(ROSTER, SUMMARIES).healthCounts
    );
  });
});

test.describe("triageHealthCounts is handed the array, never trusted blindly", function () {
  const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
  const unaided = triage.triageHealthCounts(built, ROSTER.length);

  test.it("counts the same with the array as without it", function () {
    const healths = ROSTER.map(function (_client, i) {
      return triage.triageClientHealth(built, i);
    });
    assert.deepEqual(triage.triageHealthCounts(built, ROSTER.length, healths), unaided);
  });

  test.it("falls back to the decision function for a word it does not know", function () {
    // The third argument is a shortcut, not a channel for a new vocabulary:
    // an entry outside the layer's own verdicts is ignored and the client is
    // graded properly, so a caller cannot invent a health by passing one.
    const bogus = ["healthy", null, undefined, {}];
    assert.deepEqual(triage.triageHealthCounts(built, ROSTER.length, bogus), unaided);
    const half = ROSTER.map(function (_client, i) {
      return i === 0 ? "excellent" : triage.triageClientHealth(built, i);
    });
    assert.deepEqual(triage.triageHealthCounts(built, ROSTER.length, half), unaided);
    // …and no key the chips do not have has appeared on the object.
    assert.deepEqual(
      Object.keys(triage.triageHealthCounts(built, ROSTER.length, bogus)).sort(),
      ["all", "attention", "ok", "watch"]
    );
  });

  test.it("falls back for an array that is not the grid's length", function () {
    const shortArr = [triage.triageClientHealth(built, 0)];
    assert.deepEqual(
      triage.triageHealthCounts(built, ROSTER.length, shortArr),
      unaided
    );
    const longArr = ROSTER.map(function (_client, i) {
      return triage.triageClientHealth(built, i);
    }).concat(["ok", "ok", "ok"]);
    assert.deepEqual(triage.triageHealthCounts(built, ROSTER.length, longArr), unaided);
  });

  test.it("ignores an argument that is not an array at all", function () {
    ["ok", 7, {}, null].forEach(function (healths) {
      assert.deepEqual(
        triage.triageHealthCounts(built, ROSTER.length, healths),
        unaided
      );
    });
  });
});
