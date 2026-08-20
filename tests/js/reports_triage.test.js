// Behavioural tests for the multi-client triage layer (#651).
//
// Run with:  node --test tests/js/*.test.js
//
// These EXECUTE the shipped bytes — `require` loads the same files the
// browser gets over /static/, no build step and no copy.
//
// The layer exists because everything mureo knew about a client that was
// WRONG was rendered inside that client's own card, at the same visual
// weight as everything that was fine. Two field incidents were on screen
// the whole time: a double-counted ad account (#636) and an eleven-day-old
// figure (#638). Neither was a missing signal; both were unsurfaced ones.
//
// So what is pinned here is not wording. It is the four properties that
// make the layer worth looking at:
//   1. the ORDER is stated in code, not left to render order;
//   2. every item says what to RUN next;
//   3. a withheld figure is an ITEM, never a blank that reads as zero;
//   4. the count and the marked cards are one list, so they cannot disagree.
//
// i18n: MUREO.t is stubbed to return the key it was handed and to record
// the interpolated params, so assertions are on WHICH string was chosen,
// not on English wording.

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

// reports_triage.js reads reports_logic.js off the page global at CALL
// time, exactly as it reads MUREO.t — so the browser's load order
// (app.html) is the only coupling. Here we ARE the page.
globalThis.window = globalThis;
require(path.join(WEB, "reports_logic.js"));
const triage = require(path.join(WEB, "reports_triage.js"));

test.beforeEach(function () {
  calls.length = 0;
});

const DAY_MS = 24 * 60 * 60 * 1000;

/** An ISO timestamp `days` in the past. */
function ago(days) {
  return new Date(Date.now() - days * DAY_MS).toISOString();
}

function client(slug) {
  return { slug: slug, name: slug.toUpperCase(), active: true };
}

/** A healthy client: fresh figures, no conflicts, nothing outstanding. */
function healthySummary() {
  return {
    platforms: [
      {
        key: "google_ads",
        display_name: "Google Ads",
        totals: { spend: 1000, conversions: 10 },
        metrics_period: "YESTERDAY",
        freshness: { fetched_at: ago(0), stale: false, stale_after_days: 2 },
        not_collected: null,
      },
    ],
    platform_conflicts: [],
    observations_due: { count: 0, oldest_due: null },
  };
}

/** A client whose totals are withheld because one account is counted twice. */
function doubleCountedSummary() {
  const s = healthySummary();
  s.platforms.push({
    key: "plugin:acme-ads",
    display_name: "Acme Ads (plugin)",
    totals: { spend: 1000, conversions: 10 },
    metrics_period: "YESTERDAY",
    freshness: { fetched_at: ago(0), stale: false, stale_after_days: 2 },
    not_collected: null,
  });
  s.platform_conflicts = [
    {
      kind: "duplicate_account",
      platform_keys: ["google_ads", "plugin:acme-ads"],
      account_known: true,
    },
  ];
  return s;
}

/** A client whose only problem is an eleven-day-old rollup (#638). */
function staleSummary() {
  const s = healthySummary();
  s.platforms[0].freshness = {
    fetched_at: ago(11),
    stale: true,
    stale_after_days: 2,
  };
  return s;
}

function notCollectedSummary() {
  const s = healthySummary();
  s.platforms[0].not_collected = {
    attempted_at: ago(1),
    reason: "the Meta access token expired",
  };
  return s;
}

function unknownKeySummary() {
  const s = healthySummary();
  s.platform_conflicts = [
    { kind: "unrecognized_key", platform_keys: ["mystery"], account_known: false },
  ];
  return s;
}

function observationsDueSummary() {
  const s = healthySummary();
  s.observations_due = { count: 3, oldest_due: "2026-08-01" };
  return s;
}

/** Kinds present in a built layer, in the order the layer renders them. */
function kinds(built) {
  return built.items.map(function (i) {
    return i.kind;
  });
}

// ---------------------------------------------------------------------
// 4. Silence when there is nothing
// ---------------------------------------------------------------------

test.describe("silence when there is nothing", function () {
  test.it("gives a healthy roster no items and no marked clients", function () {
    const built = triage.buildReportsTriage(
      [client("acme"), client("globex")],
      [healthySummary(), healthySummary()]
    );
    assert.deepEqual(built.items, []);
    assert.deepEqual(built.clients, []);
  });

  test.it("survives an empty roster and a missing summary", function () {
    assert.deepEqual(triage.buildReportsTriage([], []).items, []);
    assert.deepEqual(triage.buildReportsTriage([client("a")], [null]).items, []);
    assert.deepEqual(triage.buildReportsTriage(null, null).items, []);
    assert.deepEqual(
      triage.buildReportsTriage([client("a")], [{ platforms: "nope" }]).items,
      []
    );
  });
});

// ---------------------------------------------------------------------
// 1. The order is stated in code
// ---------------------------------------------------------------------

test.describe("the ranking is stated in code", function () {
  test.it("names every kind once, most actionable first", function () {
    assert.deepEqual(triage.REPORTS_TRIAGE_KINDS, [
      "totals_double_counted",
      "totals_stale",
      "not_collected",
      "unrecognized_key",
      "observation_due",
    ]);
  });

  test.it("gives each item the rank its kind holds in that table", function () {
    const built = triage.buildReportsTriage(
      [client("acme")],
      [observationsDueSummary()]
    );
    built.items.forEach(function (item) {
      assert.equal(
        item.rank,
        triage.REPORTS_TRIAGE_KINDS.indexOf(item.kind),
        item.kind + " does not carry its table rank"
      );
    });
  });

  test.it(
    "puts a client whose totals are withheld above one that is only stale",
    function () {
      // The acceptance criterion, and the reason render order is not
      // trusted: `stale` is listed FIRST in the roster here.
      const built = triage.buildReportsTriage(
        [client("stale-co"), client("conflicted-co")],
        [staleSummary(), doubleCountedSummary()]
      );
      assert.deepEqual(kinds(built), ["totals_double_counted", "totals_stale"]);
      assert.deepEqual(
        built.clients.map(function (c) {
          return c.slug;
        }),
        ["conflicted-co", "stale-co"]
      );
    }
  );

  test.it("ranks every kind against every other, pairwise", function () {
    // One assertion per adjacent pair would miss a table reordered wholesale.
    const cases = [
      ["totals_double_counted", doubleCountedSummary()],
      ["totals_stale", staleSummary()],
      ["not_collected", notCollectedSummary()],
      ["unrecognized_key", unknownKeySummary()],
      ["observation_due", observationsDueSummary()],
    ];
    // Fed in REVERSE, so anything that survives came from the ranking.
    const reversed = cases.slice().reverse();
    const built = triage.buildReportsTriage(
      reversed.map(function (c, i) {
        return client("c" + i);
      }),
      reversed.map(function (c) {
        return c[1];
      })
    );
    assert.deepEqual(
      kinds(built),
      cases.map(function (c) {
        return c[0];
      })
    );
  });

  test.it("breaks a rank tie by the operator's own card order", function () {
    const built = triage.buildReportsTriage(
      [client("second"), client("first")],
      [staleSummary(), staleSummary()]
    );
    assert.deepEqual(
      built.items.map(function (i) {
        return i.slug;
      }),
      ["second", "first"]
    );
  });
});

// ---------------------------------------------------------------------
// 2. Every item says what to do next
// ---------------------------------------------------------------------

test.describe("every item says what to do next", function () {
  const EVERY_KIND = [
    doubleCountedSummary(),
    staleSummary(),
    notCollectedSummary(),
    unknownKeySummary(),
    observationsDueSummary(),
  ];

  test.it("produces one item for every kind the table names", function () {
    const built = triage.buildReportsTriage(
      EVERY_KIND.map(function (s, i) {
        return client("c" + i);
      }),
      EVERY_KIND
    );
    assert.deepEqual(kinds(built).slice().sort(), triage.REPORTS_TRIAGE_KINDS.slice().sort());
  });

  test.it("gives each of them a non-empty next step", function () {
    // "An item with no next step is a bug in the item, not a display
    // detail" — #636 was reported because the dashboard said "resolve
    // this" and no command existed that could.
    const built = triage.buildReportsTriage(
      EVERY_KIND.map(function (s, i) {
        return client("c" + i);
      }),
      EVERY_KIND
    );
    built.items.forEach(function (item) {
      const step = triage.triageItemNextStep(item);
      assert.ok(step, item.kind + " has no next step");
      assert.notEqual(step, "", item.kind + " has an empty next step");
    });
  });

  test.it("points a duplicated account at the command that can clear it", function () {
    const built = triage.buildReportsTriage(
      [client("acme")],
      [doubleCountedSummary()]
    );
    assert.equal(
      triage.triageItemNextStep(built.items[0]),
      "dashboard.reports_conflict_duplicate_repair_hint"
    );
  });

  test.it("points an unrecognised key at the survey command instead", function () {
    const built = triage.buildReportsTriage([client("acme")], [unknownKeySummary()]);
    assert.equal(
      triage.triageItemNextStep(built.items[0]),
      "dashboard.reports_conflict_repair_hint"
    );
  });

  test.it("refuses a next step for a kind it does not know", function () {
    assert.equal(triage.triageItemNextStep({ kind: "invented" }), "");
    assert.equal(triage.triageItemNextStep(null), "");
  });
});

// ---------------------------------------------------------------------
// 3. A withheld figure is an item, never a blank
// ---------------------------------------------------------------------

test.describe("a withheld figure is a triage item", function () {
  const logic = require(path.join(WEB, "reports_logic.js"));

  test.it("raises an item for exactly the clients whose totals are withheld", function () {
    [doubleCountedSummary(), staleSummary()].forEach(function (summary) {
      const kpis = logic.aggregateClientKpis(summary);
      // The card renders "—" for these. That is the blank the layer exists
      // to name.
      assert.equal(kpis.spend, null);
      assert.equal(kpis.conversions, null);
      const built = triage.buildReportsTriage([client("acme")], [summary]);
      assert.equal(built.items.length > 0, true, "a withheld client raised nothing");
      assert.equal(built.clients.length, 1);
    });
  });

  test.it("says mureo cannot state the figures, rather than stating one", function () {
    const built = triage.buildReportsTriage(
      [client("acme"), client("globex")],
      [doubleCountedSummary(), staleSummary()]
    );
    const texts = built.items.map(function (i) {
      return triage.triageItemText(i);
    });
    assert.deepEqual(texts, [
      "dashboard.reports_triage_double_counted",
      "dashboard.reports_triage_stale",
    ]);
    // No number reaches the layer for a client whose figures are withheld:
    // the params carry keys and an age, never a spend or a conversion count.
    calls.forEach(function (c) {
      assert.equal("spend" in c.params, false, c.key + " carries a withheld spend");
      assert.equal(
        "conversions" in c.params,
        false,
        c.key + " carries a withheld conversion count"
      );
    });
  });

  test.it("still names a stale client whose collection time is unknown", function () {
    // The mixed case: mureo knows something IS stale but cannot quote an
    // age. Saying nothing here would be the blank all over again.
    const summary = staleSummary();
    summary.platforms[0].freshness = { fetched_at: "not-a-timestamp", stale: true };
    const built = triage.buildReportsTriage([client("acme")], [summary]);
    assert.deepEqual(kinds(built), ["totals_stale"]);
    assert.equal(
      triage.triageItemText(built.items[0]),
      "dashboard.reports_triage_stale_undated"
    );
  });

  test.it("reports a double count and a stale rollup as two items", function () {
    // Two findings with two different next steps. The card suppresses the
    // stale restatement when the sum is double-counted (that figure is
    // wrong at every age); the ITEM is not a figure, and dropping it would
    // hide a collector that stopped.
    const summary = doubleCountedSummary();
    summary.platforms[0].freshness = { fetched_at: ago(11), stale: true };
    const built = triage.buildReportsTriage([client("acme")], [summary]);
    assert.deepEqual(kinds(built), ["totals_double_counted", "totals_stale"]);
    assert.equal(built.clients.length, 1);
  });
});

// ---------------------------------------------------------------------
// The other two sources: why nothing was collected, and what is overdue
// ---------------------------------------------------------------------

test.describe("the notes mureo already computes", function () {
  test.it("carries a not-collected reason through verbatim", function () {
    const built = triage.buildReportsTriage(
      [client("acme")],
      [notCollectedSummary()]
    );
    assert.deepEqual(kinds(built), ["not_collected"]);
    assert.equal(
      triage.triageItemText(built.items[0]),
      "dashboard.reports_triage_not_collected"
    );
    const params = calls[calls.length - 1].params;
    assert.equal(params.reason, "the Meta access token expired");
    assert.equal(params.platform, "Google Ads");
  });

  test.it("drops a note that states no reason", function () {
    const summary = notCollectedSummary();
    summary.platforms[0].not_collected = { attempted_at: ago(1), reason: "  " };
    assert.deepEqual(triage.buildReportsTriage([client("a")], [summary]).items, []);
  });

  test.it("states the overdue count and the oldest date the server sent", function () {
    const built = triage.buildReportsTriage(
      [client("acme")],
      [observationsDueSummary()]
    );
    assert.deepEqual(kinds(built), ["observation_due"]);
    assert.equal(
      triage.triageItemText(built.items[0]),
      "dashboard.reports_triage_observation_due"
    );
    assert.deepEqual(calls[calls.length - 1].params, { n: 3, date: "2026-08-01" });
  });

  test.it("says nothing about observations the server did not count", function () {
    // The count is the server's to make: `recent_actions` is capped and
    // carries no `evaluation_of`, so a browser-side count would both
    // under-report a long log and nag about reviews already done. An
    // absent key is a daemon that does not supply the seam — not a zero.
    const summary = healthySummary();
    delete summary.observations_due;
    assert.deepEqual(triage.buildReportsTriage([client("a")], [summary]).items, []);
    const zero = healthySummary();
    assert.deepEqual(triage.buildReportsTriage([client("a")], [zero]).items, []);
    const junk = healthySummary();
    junk.observations_due = { count: "3", oldest_due: null };
    assert.deepEqual(triage.buildReportsTriage([client("a")], [junk]).items, []);
  });
});

// ---------------------------------------------------------------------
// 5. The count and the marked cards are one list
// ---------------------------------------------------------------------

test.describe("the count agrees with the cards below", function () {
  const ROSTER = [
    client("healthy"),
    client("conflicted"),
    client("stale"),
    client("quiet"),
  ];
  const SUMMARIES = [
    healthySummary(),
    doubleCountedSummary(),
    staleSummary(),
    healthySummary(),
  ];

  test.it("marks exactly the clients the heading counts", function () {
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    // What dashboard.js does: the heading prints built.clients.length and
    // the grid asks triageMarksClient for each card, in roster order.
    const marked = ROSTER.filter(function (c, index) {
      return triage.triageMarksClient(built, index);
    });
    assert.equal(marked.length, built.clients.length);
    assert.deepEqual(
      marked.map(function (c) {
        return c.slug;
      }),
      ["conflicted", "stale"]
    );
  });

  test.it("counts a client once however many items it raises", function () {
    const summary = doubleCountedSummary();
    summary.platforms[0].freshness = { fetched_at: ago(11), stale: true };
    summary.platforms[0].not_collected = { attempted_at: ago(1), reason: "quota" };
    summary.observations_due = { count: 2, oldest_due: "2026-08-01" };
    const built = triage.buildReportsTriage([client("busy")], [summary]);
    assert.equal(built.items.length, 4);
    assert.equal(built.clients.length, 1);
    assert.equal(triage.triageMarksClient(built, 0), true);
  });

  test.it("marks by position, so two clients cannot share a mark", function () {
    // Slugs come from a third-party client registry; two blank ones must
    // not collapse into one mark and desync the count from the grid.
    const built = triage.buildReportsTriage(
      [{ slug: "", name: "One" }, { slug: "", name: "Two" }],
      [staleSummary(), staleSummary()]
    );
    assert.equal(built.clients.length, 2);
    assert.equal(triage.triageMarksClient(built, 0), true);
    assert.equal(triage.triageMarksClient(built, 1), true);
    assert.equal(triage.triageMarksClient(built, 2), false);
  });

  test.it("marks nothing when there is nothing", function () {
    const built = triage.buildReportsTriage([client("a")], [healthySummary()]);
    assert.equal(triage.triageMarksClient(built, 0), false);
    assert.equal(triage.triageMarksClient(null, 0), false);
  });
});

// ---------------------------------------------------------------------
// 5. How a finding reads on the card it belongs to
// ---------------------------------------------------------------------
//
// The index view colours a client's card and offers a "needs attention /
// watch / ok" filter over the grid. Both must come from the findings this
// module already produces rather than from a second opinion about the same
// payload — a card the alert list calls urgent and the grid colours green
// is the failure the whole layer exists to prevent.

test.describe("a finding's severity", function () {
  test.it("calls the two withholding kinds attention and the rest watch", function () {
    // The line is the one reports_logic.js already draws: does this finding
    // mean a number on the card is NOT the selected window's answer?
    const severities = triage.REPORTS_TRIAGE_KINDS.map(function (kind) {
      return triage.triageItemSeverity({ kind: kind });
    });
    assert.deepEqual(severities, [
      "attention",
      "attention",
      "watch",
      "watch",
      "watch",
    ]);
  });

  test.it("gives every kind a severity and a tag", function () {
    // Derived from the ranking table, not restated: a kind added there
    // without a severity would render an uncoloured, unlabelled alert.
    triage.REPORTS_TRIAGE_KINDS.forEach(function (kind) {
      const row = { kind: kind };
      assert.ok(
        ["attention", "watch"].indexOf(triage.triageItemSeverity(row)) !== -1,
        kind + " has no severity"
      );
      assert.ok(triage.triageItemTag(row), kind + " has no tag");
    });
  });

  test.it("never throws on a row it did not produce", function () {
    [null, undefined, {}, "totals_stale", { kind: "invented" }].forEach(
      function (row) {
        assert.equal(typeof triage.triageItemSeverity(row), "string");
        assert.equal(typeof triage.triageItemTag(row), "string");
      }
    );
    assert.equal(triage.triageItemTag({ kind: "invented" }), "");
  });
});

test.describe("a client's health, for the grid and its filter", function () {
  const ROSTER = [client("conflicted"), client("overdue"), client("fine")];
  const SUMMARIES = [doubleCountedSummary(), observationsDueSummary(), healthySummary()];

  test.it("takes the worst severity the client raised", function () {
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    assert.equal(triage.triageClientHealth(built, 0), "attention");
    assert.equal(triage.triageClientHealth(built, 1), "watch");
    assert.equal(triage.triageClientHealth(built, 2), "ok");
  });

  test.it("does not let a lesser finding soften a withheld total", function () {
    // A client that is BOTH double-counted and merely overdue is not amber.
    const summary = doubleCountedSummary();
    summary.observations_due = { count: 2, oldest_due: "2026-08-01" };
    const built = triage.buildReportsTriage([client("busy")], [summary]);
    assert.equal(triage.triageClientHealth(built, 0), "attention");
  });

  test.it("agrees with the marks: exactly the ok cards are unmarked", function () {
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    ROSTER.forEach(function (_c, index) {
      assert.equal(
        triage.triageClientHealth(built, index) === "ok",
        !triage.triageMarksClient(built, index),
        "card " + index + " is marked and healthy at once"
      );
    });
  });

  test.it("counts the grid by health, including the cards it never saw", function () {
    // The counts sit on the filter chips, so they are over the WHOLE grid:
    // a client with no findings raises no item and must still be counted.
    const counts = triage.triageHealthCounts(
      triage.buildReportsTriage(ROSTER, SUMMARIES),
      ROSTER.length
    );
    assert.deepEqual(counts, { all: 3, attention: 1, watch: 1, ok: 1 });
  });

  test.it("counts a roster it has no findings for at all", function () {
    const built = triage.buildReportsTriage([], []);
    assert.deepEqual(triage.triageHealthCounts(built, 4), {
      all: 4,
      attention: 0,
      watch: 0,
      ok: 4,
    });
    assert.deepEqual(triage.triageHealthCounts(null, 0), {
      all: 0,
      attention: 0,
      watch: 0,
      ok: 0,
    });
  });

  test.it("calls an unknown card healthy rather than throwing", function () {
    const built = triage.buildReportsTriage(ROSTER, SUMMARIES);
    assert.equal(triage.triageClientHealth(built, 99), "ok");
    assert.equal(triage.triageClientHealth(null, 0), "ok");
  });
});

// ---------------------------------------------------------------------
// 6. One row per kind, not one row per client
// ---------------------------------------------------------------------
//
// Field report from the 27-client install: the layer rendered sixteen rows,
// six of them the same sentence about the same unresolvable platform key
// under six different client names. A list that repeats itself is a wall
// again, which is the exact failure #651 exists to end — so the rows are
// grouped by KIND and name the clients they cover.
//
// Grouping is a display aggregation and nothing more. The client set it
// covers is the same set, which is what keeps "N clients need attention"
// above it honest, and the kind order is still the ranking.

test.describe("findings are grouped by kind", function () {
  const ROSTER = [client("acme"), client("globex"), client("initech")];

  test.it("puts one row per kind, in the ranking's order", function () {
    const built = triage.buildReportsTriage(ROSTER, [
      unknownKeySummary(),
      staleSummary(),
      unknownKeySummary(),
    ]);
    const groups = triage.groupReportsTriage(built);
    assert.deepEqual(
      groups.map(function (g) {
        return g.kind;
      }),
      ["totals_stale", "unrecognized_key"]
    );
    assert.deepEqual(
      groups.map(function (g) {
        return g.rank;
      }),
      groups
        .map(function (g) {
          return triage.triageRank(g.kind);
        })
        .slice()
    );
  });

  test.it("names every client the row covers, in card order", function () {
    const built = triage.buildReportsTriage(ROSTER, [
      unknownKeySummary(),
      staleSummary(),
      unknownKeySummary(),
    ]);
    const groups = triage.groupReportsTriage(built);
    const unknown = groups[1];
    assert.deepEqual(
      unknown.clients.map(function (c) {
        return c.name;
      }),
      ["ACME", "INITECH"]
    );
    assert.deepEqual(
      unknown.clients.map(function (c) {
        return c.index;
      }),
      [0, 2]
    );
  });

  test.it("covers exactly the clients the heading counts", function () {
    // The invariant grouping must not touch: the layer's count, the cards it
    // marks and the clients these rows cover are ONE set. Aggregating rows
    // for display may not quietly drop a client from it.
    const built = triage.buildReportsTriage(ROSTER, [
      doubleCountedSummary(),
      staleSummary(),
      healthySummary(),
    ]);
    const covered = {};
    triage.groupReportsTriage(built).forEach(function (group) {
      group.clients.forEach(function (c) {
        covered[c.index] = true;
      });
    });
    assert.deepEqual(
      Object.keys(covered).sort(),
      built.clients
        .map(function (c) {
          return String(c.index);
        })
        .sort()
    );
  });

  test.it("counts one client once inside a group", function () {
    // Two findings of the SAME kind for one client (two duplicate-account
    // conflicts) is one client on that row, not two.
    const summary = doubleCountedSummary();
    summary.platform_conflicts.push({
      kind: "duplicate_account",
      platform_keys: ["google_ads", "plugin:other"],
      account_known: true,
    });
    const groups = triage.groupReportsTriage(
      triage.buildReportsTriage([client("busy")], [summary])
    );
    assert.equal(groups[0].items.length, 2);
    assert.equal(groups[0].clients.length, 1);
  });

  test.it("carries the kind's severity onto the row", function () {
    const groups = triage.groupReportsTriage(
      triage.buildReportsTriage(
        [client("a"), client("b")],
        [staleSummary(), observationsDueSummary()]
      )
    );
    assert.deepEqual(
      groups.map(function (g) {
        return g.severity;
      }),
      ["attention", "watch"]
    );
  });

  test.it("groups nothing out of nothing", function () {
    assert.deepEqual(triage.groupReportsTriage(null), []);
    assert.deepEqual(triage.groupReportsTriage({}), []);
    assert.deepEqual(
      triage.groupReportsTriage(triage.buildReportsTriage([client("a")], [healthySummary()])),
      []
    );
  });
});

// ---------------------------------------------------------------------
// 7. The card's badges
// ---------------------------------------------------------------------
//
// The same field report: each client card carried the full sentences AND
// the repair command, and the identical text was already on screen in the
// alert list directly above it. The card keeps the STATE — which is what
// stops a "—" reading as zero — and gives up the explanation.

test.describe("what a card says about its own findings", function () {
  test.it("gives one short badge per kind, in ranking order", function () {
    const summary = doubleCountedSummary();
    summary.observations_due = { count: 2, oldest_due: "2026-08-01" };
    const built = triage.buildReportsTriage([client("busy")], [summary]);
    assert.deepEqual(
      triage.triageClientBadges(built, 0).map(function (b) {
        return b.kind;
      }),
      ["totals_double_counted", "observation_due"]
    );
  });

  test.it("says how old a stale figure is, because that is the state", function () {
    // "—" alone reads as zero. "— / figures 11 days old" does not, and it
    // is a state, not an explanation: no command, no sentence.
    const built = triage.buildReportsTriage([client("a")], [staleSummary()]);
    const badge = triage.triageClientBadges(built, 0)[0];
    assert.equal(badge.kind, "totals_stale");
    assert.equal(calls[calls.length - 1].key, "dashboard.reports_triage_tag_stale_aged");
    assert.ok(badge.text);
  });

  test.it("falls back to the plain tag when the age is unknown", function () {
    const summary = staleSummary();
    summary.platforms[0].freshness = { fetched_at: "not-a-date", stale: true };
    const built = triage.buildReportsTriage([client("a")], [summary]);
    const badge = triage.triageClientBadges(built, 0)[0];
    assert.equal(badge.text, "dashboard.reports_triage_tag_stale");
  });

  test.it("gives a card with nothing raised no badges at all", function () {
    const built = triage.buildReportsTriage([client("a")], [healthySummary()]);
    assert.deepEqual(triage.triageClientBadges(built, 0), []);
    assert.deepEqual(triage.triageClientBadges(null, 0), []);
    assert.deepEqual(triage.triageClientBadges(built, 99), []);
  });
});

// ---------------------------------------------------------------------
// 8. Dismissing a MESSAGE hides it and resolves nothing
// ---------------------------------------------------------------------
//
// An operator can close an alert. What must never follow from that is the
// finding disappearing: hiding is a view operation, the condition is still
// true, and #636/#638 both happened because something true was not on
// screen. So the identity a dismissal is stored under is a fingerprint of
// what the message SAID — when the content changes, it is a different
// message and comes back.
//
// One message, not one row. The rows are grouped by kind, and a row can
// cover six clients: closing "unknown key" as a category would take five
// findings the operator never looked at with it. So the ✕ on a message
// hides that message; the ✕ on the row is defined as "every message on it",
// which is the only reading that stays consistent with the first.

test.describe("a dismissal is keyed to what the message said", function () {
  function itemsOf(summaries, roster) {
    return triage.buildReportsTriage(roster || [client("a")], summaries).items;
  }

  test.it("is stable while nothing about the message changed", function () {
    assert.equal(
      triage.triageItemKey(itemsOf([staleSummary()])[0]),
      triage.triageItemKey(itemsOf([staleSummary()])[0])
    );
  });

  test.it("tells two clients' identical findings apart", function () {
    // The whole point of going per-message: six clients raising the same
    // kind are six dismissals, not one.
    const items = itemsOf([staleSummary(), staleSummary()], [client("a"), client("b")]);
    assert.equal(items.length, 2);
    assert.notEqual(triage.triageItemKey(items[0]), triage.triageItemKey(items[1]));
  });

  test.it("changes when a stale figure gets another day older", function () {
    const younger = staleSummary();
    younger.platforms[0].freshness = { fetched_at: ago(11), stale: true };
    const older = staleSummary();
    older.platforms[0].freshness = { fetched_at: ago(29), stale: true };
    assert.notEqual(
      triage.triageItemKey(itemsOf([younger])[0]),
      triage.triageItemKey(itemsOf([older])[0])
    );
  });

  test.it("changes when the reason a collection failed changes", function () {
    const first = notCollectedSummary();
    const second = notCollectedSummary();
    second.platforms[0].not_collected.reason = "the account was suspended";
    assert.notEqual(
      triage.triageItemKey(itemsOf([first])[0]),
      triage.triageItemKey(itemsOf([second])[0])
    );
  });

  test.it("changes when more observations fall due", function () {
    const first = observationsDueSummary();
    const second = observationsDueSummary();
    second.observations_due = { count: 9, oldest_due: "2026-07-01" };
    assert.notEqual(
      triage.triageItemKey(itemsOf([first])[0]),
      triage.triageItemKey(itemsOf([second])[0])
    );
  });

  test.it("tells two kinds apart even when they cover the same client", function () {
    const summary = doubleCountedSummary();
    summary.platforms[0].freshness = { fetched_at: ago(11), stale: true };
    const items = itemsOf([summary]);
    assert.notEqual(triage.triageItemKey(items[0]), triage.triageItemKey(items[1]));
  });

  test.it("never throws on a row it did not produce", function () {
    [null, undefined, {}, "totals_stale", 7].forEach(function (row) {
      assert.equal(typeof triage.triageItemKey(row), "string");
    });
  });
});

test.describe("a dismissed message is hidden, counted and restorable", function () {
  const store = {};
  globalThis.window.localStorage = {
    getItem: function (k) {
      return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
    },
    setItem: function (k, v) {
      store[k] = String(v);
    },
  };

  test.beforeEach(function () {
    Object.keys(store).forEach(function (k) {
      delete store[k];
    });
  });

  /** Six clients raising the same kind, plus one raising another. */
  function roster() {
    const rows = [];
    const bodies = [];
    for (let i = 0; i < 6; i++) {
      rows.push(client("unknown" + i));
      bodies.push(unknownKeySummary());
    }
    rows.push(client("stale"));
    bodies.push(staleSummary());
    return triage.groupReportsTriage(triage.buildReportsTriage(rows, bodies));
  }

  test.it("hides only the message that was dismissed", function () {
    const groups = roster();
    const unknown = groups.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    triage.dismissTriageItem(unknown.items[0]);
    const split = triage.partitionTriageGroups(roster());
    const stillThere = split.visible.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    assert.equal(stillThere.items.length, 5);
    assert.equal(split.hiddenCount, 1);
  });

  test.it("shrinks the row's own count as its messages go", function () {
    // "unknown key x6" -> dismiss four -> "x2". The row names the clients it
    // still covers, so the two have to be recomputed together.
    const groups = roster();
    const unknown = groups.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    unknown.items.slice(0, 4).forEach(triage.dismissTriageItem);
    const split = triage.partitionTriageGroups(roster());
    const left = split.visible.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    assert.equal(left.items.length, 2);
    assert.equal(left.clients.length, 2);
    assert.deepEqual(
      left.clients.map(function (c) {
        return c.name;
      }),
      ["UNKNOWN4", "UNKNOWN5"]
    );
    assert.equal(split.hiddenCount, 4);
  });

  test.it("drops the row entirely once every message on it is gone", function () {
    const groups = roster();
    const unknown = groups.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    unknown.items.forEach(triage.dismissTriageItem);
    const split = triage.partitionTriageGroups(roster());
    assert.deepEqual(
      split.visible.map(function (g) {
        return g.kind;
      }),
      ["totals_stale"]
    );
    assert.equal(split.hiddenCount, 6);
  });

  test.it("closes a whole row as every message on it", function () {
    // The row-level ✕ is not a second concept: it is the message-level one
    // applied to each message, so a row closed as a category and a row
    // closed one message at a time end up in the same state.
    const groups = roster();
    triage.dismissTriageGroup(
      groups.find(function (g) {
        return g.kind === "unrecognized_key";
      })
    );
    const split = triage.partitionTriageGroups(roster());
    assert.equal(split.visible.length, 1);
    assert.equal(split.hiddenCount, 6);
  });

  test.it("counts hidden MESSAGES, not hidden rows", function () {
    // The "N hidden" line is the receipt for what was closed. Counting rows
    // would say "1" for six findings nobody can see.
    const groups = roster();
    const unknown = groups.find(function (g) {
      return g.kind === "unrecognized_key";
    });
    unknown.items.slice(0, 3).forEach(triage.dismissTriageItem);
    assert.equal(triage.partitionTriageGroups(roster()).hiddenCount, 3);
  });

  test.it("brings every hidden message back", function () {
    roster().forEach(triage.dismissTriageGroup);
    assert.equal(triage.partitionTriageGroups(roster()).visible.length, 0);
    triage.restoreTriageDismissals();
    const split = triage.partitionTriageGroups(roster());
    assert.equal(split.hiddenCount, 0);
    assert.equal(split.visible.length, 2);
  });

  test.it("brings a message back by itself when its content changed", function () {
    // The whole point: it was hidden, the condition was not resolved, and
    // the figures are eighteen days older than they were. That is a
    // different message and it is on screen again.
    const young = staleSummary();
    young.platforms[0].freshness = { fetched_at: ago(11), stale: true };
    const old = staleSummary();
    old.platforms[0].freshness = { fetched_at: ago(29), stale: true };
    const rows = [client("a")];
    const before = triage.groupReportsTriage(triage.buildReportsTriage(rows, [young]));
    triage.dismissTriageItem(before[0].items[0]);
    assert.equal(triage.partitionTriageGroups(before).visible.length, 0);
    const after = triage.groupReportsTriage(triage.buildReportsTriage(rows, [old]));
    assert.equal(triage.partitionTriageGroups(after).visible.length, 1);
  });

  test.it("never hides anything when storage cannot be read", function () {
    const real = globalThis.window.localStorage;
    globalThis.window.localStorage = {
      getItem: function () {
        throw new Error("storage disabled");
      },
      setItem: function () {
        throw new Error("storage disabled");
      },
    };
    try {
      triage.dismissTriageItem(roster()[0].items[0]); // must not throw
      assert.equal(triage.partitionTriageGroups(roster()).hiddenCount, 0);
    } finally {
      globalThis.window.localStorage = real;
    }
  });

  test.it("ignores a stored value that is not a list of keys", function () {
    store["mureo.reports.triage.dismissed"] = '{"not":"an array"}';
    assert.equal(triage.partitionTriageGroups(roster()).hiddenCount, 0);
    store["mureo.reports.triage.dismissed"] = "}}}not json";
    assert.equal(triage.partitionTriageGroups(roster()).hiddenCount, 0);
  });

  test.it("does not change which clients the layer counts", function () {
    // Hiding is a view operation. The heading, the KPI cell and the marked
    // cards all read built.clients, and dismissal never touches it.
    const built = triage.buildReportsTriage(
      [client("a"), client("b")],
      [staleSummary(), observationsDueSummary()]
    );
    const before = built.clients.length;
    triage.groupReportsTriage(built).forEach(triage.dismissTriageGroup);
    assert.equal(built.clients.length, before);
    assert.equal(triage.triageMarksClient(built, 0), true);
    assert.equal(triage.triageMarksClient(built, 1), true);
    assert.equal(triage.triageClientHealth(built, 0), "attention");
  });

  test.it("keeps the stored list bounded", function () {
    // Written on every dismissal, expired by nothing; and now one entry per
    // MESSAGE rather than per row, so it fills faster than it used to.
    for (let i = 0; i < 400; i++) {
      triage.dismissTriageItem({ kind: "totals_stale", slug: "c" + i });
    }
    const stored = JSON.parse(store["mureo.reports.triage.dismissed"]);
    assert.ok(stored.length <= triage.REPORTS_TRIAGE_DISMISS_CAP, stored.length);
    // The most recent dismissal survives the trim.
    assert.ok(
      stored.indexOf(triage.triageItemKey({ kind: "totals_stale", slug: "c399" })) !== -1
    );
  });
});

// ---------------------------------------------------------------------
// 9. A withheld figure is never a bare dash
// ---------------------------------------------------------------------
//
// The card slimmed down: the sentences and the repair command moved to the
// alert row and the detail view. What could NOT move is the reason the card
// prints "—" where a figure belongs, because a dash on its own reads as
// zero — which is exactly #638, on this exact grid.
//
// The card renders `triageClientBadges`, so the guarantee is this: a client
// whose totals reports_logic.js refuses to state always has at least one
// badge. It holds by construction (the two withholding kinds are raised
// from the same two conditions that null the figures), and it is asserted
// here rather than assumed, because the two are now in different files.

test.describe("a withheld card always says why", function () {
  const logic = require(path.join(WEB, "reports_logic.js"));

  [
    ["double-counted", doubleCountedSummary],
    ["stale", staleSummary],
  ].forEach(function (row) {
    test.it("badges a " + row[0] + " client whose figures are withheld", function () {
      const summary = row[1]();
      // Precondition: reports_logic.js really is withholding the figures.
      assert.equal(logic.aggregateClientKpis(summary).spend, null);
      const built = triage.buildReportsTriage([client("a")], [summary]);
      const badges = triage.triageClientBadges(built, 0);
      assert.ok(badges.length > 0, "a withheld card carries no badge");
      assert.equal(badges[0].severity, "attention");
    });
  });

  test.it("badges nothing on a card whose figures ARE stated", function () {
    const summary = healthySummary();
    assert.notEqual(logic.aggregateClientKpis(summary).spend, null);
    const built = triage.buildReportsTriage([client("a")], [summary]);
    assert.deepEqual(triage.triageClientBadges(built, 0), []);
  });
});

// ---------------------------------------------------------------------
// 10. The list opens short
// ---------------------------------------------------------------------
//
// Grouping cut sixteen rows to six. Six rows of alerts plus ten client
// cards is still two screens before the operator has read anything, and
// the complaint that started this was the height of the page.
//
// So the list opens at its top few rows — the ranking is stated in code
// precisely so that "the top few" is a defensible thing to show — with the
// rest one click away. What is NOT collapsed is the count: the heading, the
// KPI cell and the marked cards are all over every finding, whether its row
// is on screen or not.

test.describe("the alert list opens short", function () {
  function groups(n) {
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push({ kind: "k" + i, items: [], clients: [{ index: i }] });
    }
    return out;
  }

  test.it("shows the top rows and counts the rest", function () {
    const shown = triage.collapseTriageGroups(groups(6), false);
    assert.equal(shown.rows.length, triage.REPORTS_TRIAGE_COLLAPSED_ROWS);
    assert.equal(shown.remaining, 6 - triage.REPORTS_TRIAGE_COLLAPSED_ROWS);
    assert.equal(shown.collapsed, true);
  });

  test.it("keeps the ranking — the top rows are the top-ranked rows", function () {
    const all = groups(6);
    const shown = triage.collapseTriageGroups(all, false);
    assert.deepEqual(
      shown.rows.map(function (g) {
        return g.kind;
      }),
      all
        .map(function (g) {
          return g.kind;
        })
        .slice(0, triage.REPORTS_TRIAGE_COLLAPSED_ROWS)
    );
  });

  test.it("shows everything once the operator asks", function () {
    const shown = triage.collapseTriageGroups(groups(6), true);
    assert.equal(shown.rows.length, 6);
    assert.equal(shown.remaining, 0);
    assert.equal(shown.collapsed, false);
  });

  test.it("does not collapse a list that already fits", function () {
    // No "show all (0)" control on a list of three.
    const shown = triage.collapseTriageGroups(
      groups(triage.REPORTS_TRIAGE_COLLAPSED_ROWS),
      false
    );
    assert.equal(shown.remaining, 0);
    assert.equal(shown.collapsed, false);
    assert.equal(shown.rows.length, triage.REPORTS_TRIAGE_COLLAPSED_ROWS);
  });

  test.it("never throws on a list it did not expect", function () {
    [null, undefined, "rows", 3].forEach(function (bad) {
      const shown = triage.collapseTriageGroups(bad, false);
      assert.deepEqual(shown.rows, []);
      assert.equal(shown.remaining, 0);
    });
  });

  test.it("collapsing hides rows and counts nothing out", function () {
    // The property the collapse must not break: the layer's count is over
    // every finding, not over the rows that happen to be on screen.
    const built = triage.buildReportsTriage(
      [client("a"), client("b"), client("c")],
      [doubleCountedSummary(), staleSummary(), notCollectedSummary()]
    );
    const all = triage.groupReportsTriage(built);
    const shown = triage.collapseTriageGroups(all, false);
    assert.ok(shown.rows.length <= all.length);
    assert.equal(built.clients.length, 3);
    assert.equal(triage.triageHealthCounts(built, 3).ok, 0);
  });
});
