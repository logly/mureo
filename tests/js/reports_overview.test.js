// Behavioural tests for the Reports section's view routing (#651 follow-up).
//
// Run with:  node --test tests/js/*.test.js
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/, no build step and no copy.
//
// The reported bug: an operator opens a client's report, then clicks
// "Reports" in the left menu, and lands back on that same client rather
// than on the list they asked for. The menu is the only global way back to
// the list, so the view had no way out but the breadcrumb.
//
// The fix cannot be "always go to the index", because the SAME function
// re-renders the section on a period switch and on a status refresh, and a
// re-render that kicks the operator off the detail they are reading is the
// opposite bug. What separates the two is WHY the render happened, so that
// is an input here rather than something inferred from state.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

globalThis.MUREO = {
  t: function (key) {
    return key;
  },
};
globalThis.window = globalThis;
const overview = require(path.join(WEB, "reports_overview.js"));

/** The routing inputs of an Agency install sitting on a live detail view. */
function onDetail(extra) {
  const state = {
    entry: overview.REPORTS_ENTRY_RERENDER,
    currentView: "detail",
    hasIndex: true,
    selectionAlive: true,
  };
  Object.keys(extra || {}).forEach(function (k) {
    state[k] = extra[k];
  });
  return state;
}

test.describe("the left menu always lands on the list", function () {
  test.it("returns to the index from a live detail view", function () {
    // The bug, stated: menu entry beats a perfectly valid selection.
    assert.equal(
      overview.reportsViewToShow(onDetail({ entry: overview.REPORTS_ENTRY_MENU })),
      "index"
    );
  });

  test.it("stays on the index when it is already there", function () {
    assert.equal(
      overview.reportsViewToShow(
        onDetail({ entry: overview.REPORTS_ENTRY_MENU, currentView: "index" })
      ),
      "index"
    );
  });
});

test.describe("a re-render leaves the operator where they are", function () {
  test.it("keeps a live detail view across a period switch or a refresh", function () {
    // renderReports() is also the period toggle's and renderAll()'s entry
    // point. Kicking a reader back to the grid on every status poll is the
    // opposite of the bug above, and just as unusable.
    assert.equal(overview.reportsViewToShow(onDetail()), "detail");
  });

  test.it("falls back to the index when the selected client is gone", function () {
    // Archiving the client on screen, or a registry that dropped it: the
    // detail view would be about a client that no longer exists.
    assert.equal(
      overview.reportsViewToShow(onDetail({ selectionAlive: false })),
      "index"
    );
  });

  test.it("keeps the index when that is the current view", function () {
    assert.equal(
      overview.reportsViewToShow(onDetail({ currentView: "index" })),
      "index"
    );
  });
});

test.describe("a single workspace has no index to route to", function () {
  test.it("shows the detail whatever the entry point is", function () {
    // An OSS single-workspace install has one client and no grid. The menu
    // cannot send an operator to a view that does not exist.
    [overview.REPORTS_ENTRY_MENU, overview.REPORTS_ENTRY_RERENDER].forEach(
      function (entry) {
        assert.equal(
          overview.reportsViewToShow({
            entry: entry,
            currentView: "index",
            hasIndex: false,
            selectionAlive: false,
          }),
          "detail"
        );
      }
    );
  });
});

test.describe("it never throws on a state it did not expect", function () {
  test.it("answers with a real view for a missing / malformed state", function () {
    // This decides a render. A throw here blanks the whole Reports view, so
    // every input has an answer — and the answer for "nothing was stated"
    // is the detail, because an index nobody said exists is an empty grid.
    [null, undefined, {}, "index", 3].forEach(function (state) {
      assert.equal(overview.reportsViewToShow(state), "detail");
    });
  });

  test.it("treats an unknown entry token as a re-render", function () {
    // Only the menu forces the index. Anything else must not be able to
    // eject a reader from the detail view by accident.
    assert.equal(overview.reportsViewToShow(onDetail({ entry: "whatever" })), "detail");
    assert.equal(overview.reportsViewToShow(onDetail({ entry: null })), "detail");
  });
});

// ---------------------------------------------------------------------
// The portfolio figures above the grid
// ---------------------------------------------------------------------
//
// The index view states cross-client totals. Every one of them is a sum
// over clients whose figures mureo is willing to state at all — #636 and
// #638 both shipped because a number that could not be vouched for was
// rendered anyway, and a portfolio total is the easiest place in the
// product to hide one: a client whose totals are withheld would silently
// contribute zero and nothing on screen would say so.
//
// So the coverage travels WITH the figure. `stated` and `total` are not
// diagnostics; they are what makes the number readable.

// reports_overview.js reads reports_logic.js off the page global at CALL
// time, exactly as reports_triage.js does. Here we ARE the page.
require(path.join(WEB, "reports_logic.js"));

const DAY_MS = 24 * 60 * 60 * 1000;

function ago(days) {
  return new Date(Date.now() - days * DAY_MS).toISOString();
}

function platform(key, name, spend, conversions) {
  return {
    key: key,
    display_name: name,
    totals: { spend: spend, conversions: conversions },
    metrics_period: "YESTERDAY",
    freshness: { fetched_at: ago(0), stale: false, stale_after_days: 2 },
    not_collected: null,
  };
}

/** A client mureo can state: two platforms, fresh, no conflicts. */
function statedSummary(spend, conversions) {
  return {
    platforms: [
      platform("google_ads", "Google Ads", spend * 0.75, conversions),
      platform("meta_ads", "Meta Ads", spend * 0.25, 0),
    ],
    platform_conflicts: [],
  };
}

/** A client whose totals are withheld: one account counted twice (#636). */
function withheldSummary(spend) {
  const s = statedSummary(spend, 10);
  s.platform_conflicts = [
    {
      kind: "duplicate_account",
      platform_keys: ["google_ads", "meta_ads"],
      account_known: true,
    },
  ];
  return s;
}

/** A client whose totals are withheld because they are eleven days old. */
function staleSummary(spend) {
  const s = statedSummary(spend, 10);
  s.platforms[0].freshness = { fetched_at: ago(11), stale: true, stale_after_days: 2 };
  return s;
}

test.describe("the portfolio totals state their own coverage", function () {
  test.it("sums only the clients mureo can state, and says how many", function () {
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }, { slug: "b" }, { slug: "c" }],
      [statedSummary(1000, 10), statedSummary(3000, 30), withheldSummary(9999)]
    );
    assert.equal(built.total, 3);
    assert.equal(built.spend.value, 4000);
    assert.equal(built.spend.stated, 2);
    assert.equal(built.conversions.value, 40);
    assert.equal(built.conversions.stated, 2);
  });

  test.it("does not let a withheld client contribute a silent zero", function () {
    // The failure this exists to prevent: 9999 is neither added (it is not
    // mureo's to state) nor counted as 0 (which would drag every derived
    // figure below down).
    const withheldOnly = overview.buildReportsPortfolio(
      [{ slug: "a" }],
      [withheldSummary(9999)]
    );
    assert.equal(withheldOnly.spend.value, null);
    assert.equal(withheldOnly.spend.stated, 0);
    assert.equal(withheldOnly.total, 1);
  });

  test.it("withholds a stale client's figures too (#638)", function () {
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }, { slug: "b" }],
      [statedSummary(1000, 10), staleSummary(5000)]
    );
    assert.equal(built.spend.value, 1000);
    assert.equal(built.spend.stated, 1);
  });

  test.it("derives the CPA from the clients that stated BOTH figures", function () {
    // Spend from one set of clients over conversions from another is not a
    // CPA, so the pair is taken per client and the coverage is its own.
    const noConversions = statedSummary(2000, 0);
    noConversions.platforms[0].totals.conversions = null;
    noConversions.platforms[1].totals.conversions = null;
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }, { slug: "b" }],
      [statedSummary(1000, 10), noConversions]
    );
    assert.equal(built.spend.value, 3000);
    assert.equal(built.spend.stated, 2);
    assert.equal(built.cpa.value, 100);
    assert.equal(built.cpa.stated, 1);
  });

  test.it("states no CPA when nothing converted", function () {
    // A division by zero is not "0 CPA", and "—" is the honest answer.
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }],
      [statedSummary(1000, 0)]
    );
    assert.equal(built.cpa.value, null);
    assert.equal(built.cpa.stated, 0);
  });

  test.it("answers for an empty grid without inventing zeros", function () {
    const built = overview.buildReportsPortfolio([], []);
    assert.equal(built.total, 0);
    assert.equal(built.spend.value, null);
    assert.equal(built.conversions.value, null);
    assert.equal(built.cpa.value, null);
    assert.deepEqual(built.platforms, []);
  });

  test.it("never throws on a payload it did not expect", function () {
    [
      [null, null],
      [[{ slug: "a" }], [null]],
      [[{ slug: "a" }], [{ platforms: "nope" }]],
      ["clients", "summaries"],
    ].forEach(function (args) {
      const built = overview.buildReportsPortfolio(args[0], args[1]);
      assert.equal(built.spend.value, null);
      assert.deepEqual(built.platforms, []);
    });
  });
});

test.describe("the platform split", function () {
  test.it("sums each platform over the clients mureo can state", function () {
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }, { slug: "b" }],
      [statedSummary(1000, 10), withheldSummary(4000)]
    );
    assert.deepEqual(built.platforms, [
      { key: "google_ads", label: "Google Ads", spend: 750, share: 0.75 },
      { key: "meta_ads", label: "Meta Ads", spend: 250, share: 0.25 },
    ]);
  });

  test.it("ranks by spend, largest first", function () {
    const s = statedSummary(1000, 10);
    s.platforms = [platform("meta_ads", "Meta Ads", 100, 1), platform("google_ads", "Google Ads", 900, 9)];
    const built = overview.buildReportsPortfolio([{ slug: "a" }], [s]);
    assert.deepEqual(
      built.platforms.map(function (p) {
        return p.key;
      }),
      ["google_ads", "meta_ads"]
    );
  });

  test.it("drops a platform that stated no spend rather than showing 0%", function () {
    const s = statedSummary(1000, 10);
    s.platforms.push(platform("plugin:acme-ads", "Acme Ads (plugin)", null, null));
    const built = overview.buildReportsPortfolio([{ slug: "a" }], [s]);
    assert.deepEqual(
      built.platforms.map(function (p) {
        return p.key;
      }),
      ["google_ads", "meta_ads"]
    );
  });

  test.it("states no split at all when the total spend is zero", function () {
    // Every share would be 0/0. A bar of equal slices over no money is a
    // picture of nothing.
    const built = overview.buildReportsPortfolio(
      [{ slug: "a" }],
      [statedSummary(0, 0)]
    );
    assert.deepEqual(built.platforms, []);
  });

  test.it("splits one client the same way, for its own card", function () {
    assert.deepEqual(overview.clientPlatformSplit(statedSummary(1000, 10)), [
      { key: "google_ads", label: "Google Ads", spend: 750, share: 0.75 },
      { key: "meta_ads", label: "Meta Ads", spend: 250, share: 0.25 },
    ]);
  });

  test.it("shows no split for a client whose totals are withheld", function () {
    // The bar would be drawn from exactly the rows the card refuses to add
    // up. Withholding the number and drawing its shares is the same claim.
    assert.deepEqual(overview.clientPlatformSplit(withheldSummary(1000)), []);
    assert.deepEqual(overview.clientPlatformSplit(staleSummary(1000)), []);
    assert.deepEqual(overview.clientPlatformSplit(null), []);
  });

  test.it("falls back to the raw key when a platform has no display name", function () {
    const s = statedSummary(1000, 10);
    delete s.platforms[0].display_name;
    assert.equal(overview.clientPlatformSplit(s)[0].label, "google_ads");
  });
});

test.describe("a platform's colour", function () {
  test.it("is the same wherever that platform is drawn", function () {
    // The split is ranked by spend, so a position-based colour would give
    // the same platform a different colour on every card — and the bar
    // would then be unreadable without its legend.
    assert.equal(
      overview.platformColorSlot("google_ads"),
      overview.platformColorSlot("google_ads")
    );
    assert.notEqual(
      overview.platformColorSlot("google_ads"),
      overview.platformColorSlot("meta_ads")
    );
  });

  test.it("always names a slot the stylesheet has", function () {
    ["", "google_ads", "meta_ads", "plugin:some-very-long-distribution-name"].forEach(
      function (key) {
        const slot = overview.platformColorSlot(key);
        assert.ok(Number.isInteger(slot), key + " has no integer slot");
        assert.ok(slot >= 0 && slot < overview.REPORTS_PLATFORM_COLOR_SLOTS);
      }
    );
    assert.equal(overview.platformColorSlot(null), 0);
  });
});
