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
// …and reports_format.js, for the same reason: the action feed asks it to
// humanize an action name, off the page global, at call time.
require(path.join(WEB, "reports_format.js"));
// …and reports_display.js, which is where the ONE line an action-log entry
// shows is decided (#706 step 3-b): the display line the writer wrote for a
// row like this one, or the work-journal summary with its markdown emphasis
// stripped and cut. Same call-time read, same reason.
require(path.join(WEB, "reports_display.js"));

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

// ---------------------------------------------------------------------
// What mureo did today, across the roster
// ---------------------------------------------------------------------
//
// Every client's summary already carries `recent_actions` — the index
// fetches all of them in parallel to draw the cards, so the feed costs no
// request. What it cannot do by itself is decide what "today" is.
//
// An action-log `timestamp` is stamped server-side from `server_now`: the
// HOST's local wall clock, offset and all. A browser deciding the day from
// its own clock draws the boundary in its own timezone, and an operator in
// London reading a Tokyo host would see nine hours of yesterday's work
// listed as today's. So the summary states `server_today` and the browser
// compares the first ten characters of a timestamp against it — two strings
// out of one clock, and no timezone arithmetic anywhere.

function action(timestamp, summary, extra) {
  const row = {
    timestamp: timestamp,
    action: "budget_update",
    platform: "google_ads",
    campaign_id: null,
    summary: summary,
    observation_due: null,
  };
  Object.keys(extra || {}).forEach(function (k) {
    row[k] = extra[k];
  });
  return row;
}

function withActions(rows, today) {
  const s = { platforms: [], platform_conflicts: [], recent_actions: rows };
  if (today !== undefined) s.server_today = today;
  return s;
}

const TODAY = "2026-08-20";

test.describe("the day comes from the server, never from the browser", function () {
  test.it("keeps the entries whose server date is today", function () {
    const feed = overview.buildReportsActionFeed(
      [{ slug: "acme", name: "Acme" }],
      [
        withActions(
          [
            action(TODAY + "T09:15:00+09:00", "raised the daily budget"),
            action("2026-08-19T23:59:59+09:00", "yesterday, one second before"),
          ],
          TODAY
        ),
      ]
    );
    assert.equal(feed.items.length, 1);
    assert.equal(feed.items[0].text, "raised the daily budget");
  });

  test.it("draws the boundary at the server's midnight, not at UTC's", function () {
    // 00:00 local on the server's today is TODAY; the same instant is
    // yesterday in UTC. Comparing the string is what keeps them apart.
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [
        withActions(
          [
            action(TODAY + "T00:00:00+09:00", "just after midnight"),
            action(TODAY + "T23:59:59+09:00", "just before the next one"),
          ],
          TODAY
        ),
      ]
    );
    assert.equal(feed.items.length, 2);
  });

  test.it("states nothing at all when the server did not state a date", function () {
    // Silence, not a guess. An older daemon, a proxy, or a single-workspace
    // install (which never sends it) must not produce a feed dated by the
    // browser's own clock.
    [undefined, null, "", "not-a-date", 20260820].forEach(function (today) {
      const feed = overview.buildReportsActionFeed(
        [{ slug: "a", name: "A" }],
        [withActions([action(TODAY + "T09:15:00+09:00", "today's work")], today)]
      );
      assert.deepEqual(feed.items, [], String(today));
    });
  });

  test.it("takes the date from the summary and not from Date.now()", function () {
    // The strongest form of the rule: with the server a day behind this
    // machine, the feed follows the SERVER.
    const yesterday = "2026-08-19";
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [
        withActions(
          [
            action(yesterday + "T10:00:00+09:00", "the server's today"),
            action(TODAY + "T10:00:00+09:00", "the browser's today"),
          ],
          yesterday
        ),
      ]
    );
    assert.deepEqual(
      feed.items.map(function (i) {
        return i.text;
      }),
      ["the server's today"]
    );
  });

  test.it("drops an entry whose timestamp it cannot read", function () {
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [
        withActions(
          [action(null, "no timestamp"), action(12345, "not a string"), action("", "")],
          TODAY
        ),
      ]
    );
    assert.deepEqual(feed.items, []);
  });
});

test.describe("the feed reads as a feed", function () {
  test.it("is newest first, across every client", function () {
    const feed = overview.buildReportsActionFeed(
      [
        { slug: "acme", name: "Acme" },
        { slug: "globex", name: "Globex" },
      ],
      [
        withActions([action(TODAY + "T09:00:00+09:00", "early")], TODAY),
        withActions([action(TODAY + "T17:30:00+09:00", "late")], TODAY),
      ]
    );
    assert.deepEqual(
      feed.items.map(function (i) {
        return i.text;
      }),
      ["late", "early"]
    );
    assert.deepEqual(
      feed.items.map(function (i) {
        return i.name;
      }),
      ["Globex", "Acme"]
    );
  });

  test.it("carries the clock time as the server wrote it", function () {
    // Sliced out of the string for the same reason the date is: converting
    // the instant would render it in the browser's zone.
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [withActions([action(TODAY + "T17:05:00+09:00", "done")], TODAY)]
    );
    assert.equal(feed.items[0].time, "17:05");
  });

  test.it("names the client the way its card does", function () {
    const feed = overview.buildReportsActionFeed(
      [{ slug: "only-a-slug" }],
      [withActions([action(TODAY + "T10:00:00+09:00", "done")], TODAY)]
    );
    assert.equal(feed.items[0].name, "only-a-slug");
    assert.equal(feed.items[0].slug, "only-a-slug");
    assert.equal(feed.items[0].index, 0);
  });

  test.it("falls back to the action name when there is no summary", function () {
    // `summary` is optional on an action-log entry. The row still has to say
    // what happened, so the action's own name is used — humanized by
    // reports_format.js rather than printed as `budget_update`.
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [
        withActions(
          [action(TODAY + "T10:00:00+09:00", null, { action: "budget_update" })],
          TODAY
        ),
      ]
    );
    assert.equal(feed.items[0].text, "Budget update");
  });

  test.it("drops an entry that says nothing at all", function () {
    // No summary and no action name is not a row; it is a blank line.
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [
        withActions(
          [action(TODAY + "T10:00:00+09:00", "  ", { action: "" })],
          TODAY
        ),
      ]
    );
    assert.deepEqual(feed.items, []);
  });
});

test.describe("the feed is bounded", function () {
  function manyToday(n) {
    const rows = [];
    for (let i = 0; i < n; i++) {
      const hh = String(i % 24).padStart(2, "0");
      rows.push(action(TODAY + "T" + hh + ":00:00+09:00", "action " + i));
    }
    return rows;
  }

  test.it("shows at most the cap and counts the rest", function () {
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [withActions(manyToday(20), TODAY)]
    );
    assert.equal(feed.items.length, overview.REPORTS_ACTION_FEED_CAP);
    assert.equal(feed.total, 20);
    assert.equal(feed.remaining, 20 - overview.REPORTS_ACTION_FEED_CAP);
  });

  test.it("counts nothing extra when everything fits", function () {
    const feed = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [withActions(manyToday(2), TODAY)]
    );
    assert.equal(feed.items.length, 2);
    assert.equal(feed.total, 2);
    assert.equal(feed.remaining, 0);
  });

  test.it("says nothing on a day nothing happened", function () {
    // No "0 actions" panel. The default is silence, exactly as it is for the
    // alert layer that has nothing to raise.
    const quiet = overview.buildReportsActionFeed(
      [{ slug: "a", name: "A" }],
      [withActions([action("2026-08-19T10:00:00+09:00", "yesterday")], TODAY)]
    );
    assert.deepEqual(quiet.items, []);
    assert.equal(quiet.total, 0);
    assert.equal(quiet.remaining, 0);
  });

  test.it("never throws on a payload it did not expect", function () {
    [
      [null, null],
      [[{ slug: "a" }], [null]],
      [[{ slug: "a" }], [{ recent_actions: "nope", server_today: TODAY }]],
      ["clients", "summaries"],
    ].forEach(function (args) {
      const feed = overview.buildReportsActionFeed(args[0], args[1]);
      assert.deepEqual(feed.items, []);
      assert.equal(feed.total, 0);
    });
  });
});
