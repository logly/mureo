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
