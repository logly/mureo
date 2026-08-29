// One surface per section on the detail screen (#731).
//
// Run with:  node --test tests/js/*.test.js
//
// The report screens share ONE container — `[data-dashboard-reports]` wraps
// the list and the detail alike — and that container carries the ground both
// screens sit on. The owner asked for the detail screen to stop being one
// continuous tinted page and become a column of bounded blocks instead, and
// the index to keep exactly what it has.
//
// So the two screens now want different paint out of one element, which is
// the whole difficulty and the whole of what this suite guards:
//
//   • the container is MARKED while the detail view is up, and unmarked on
//     the way back — a class the stylesheet scopes on, put on by the one
//     function that already decides which screen is showing. Miss the
//     unmark and the index loses its ground the first time an operator
//     opens a client and comes back;
//   • every top-level grouping of the detail view carries the ground itself,
//     so nothing sits bare on the page;
//   • the index is UNTOUCHED — asserted here rather than left to a capture,
//     because "the other screen still looks the same" is exactly the claim a
//     shared container makes easy to break and hard to see.
//
// Driven against the real app.css through the harness's cascade, because a
// scoped override is a specificity question and a substring pin cannot ask
// it: `.reports-panel` is on both screens, and only the detail's copy may
// be repainted.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { loadDashboardPage, settle, cascade } = require("./dom_harness.js");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

//: The modifier the shared container carries while the detail view is up,
//: restated here because app.css scopes the detail screen's paint on it. A
//: test below asserts the module publishes this exact string, so the test,
//: the stylesheet and the JS cannot drift apart silently.
const DETAIL_CLASS = "is-detail";

const TODAY = new Date().toISOString().slice(0, 10);

/** `n` days before today, as `YYYY-MM-DD`. */
function daysAgo(n) {
  return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
}

/** Seven calendar-adjacent days of one metric — enough for the chart. */
function week(metric) {
  const out = [];
  for (let i = 7; i >= 1; i--) {
    const totals = {};
    totals[metric] = 10 + i;
    out.push({ date: daysAgo(i), totals: totals });
  }
  return out;
}

function platform(totals, daily) {
  return {
    key: "google_ads",
    display_name: "Google Ads",
    totals: totals,
    metrics_period: "YESTERDAY",
    campaign_count: 2,
    freshness: { fetched_at: new Date().toISOString(), stale: false },
    not_collected: null,
    daily: daily || [],
    daily_delta: null,
  };
}

const PLATFORMS = [
  platform(
    { spend: 42000, impressions: 100000, clicks: 900, conversions: 8, cpa: 5250 },
    week("conversions")
  ),
];

const ACTIONS = [
  {
    at: new Date().toISOString(),
    kind: "budget",
    platform: "google_ads",
    summary: "Raised the Brand budget",
  },
];

//: A contract stating the sections the legacy screen does not draw.
const DISPLAY = {
  source: "daily-check",
  generated_at: new Date(Date.now() - 3 * 3600000).toISOString(),
  nav_message: "CPA is over target — pause the two worst ad groups",
  proposals: [{ title: "Pause two ad groups", body: "Both 3x target CPA", date: TODAY }],
};

function summaryWith(overrides) {
  return Object.assign(
    {
      client: "alpha",
      period: "YESTERDAY",
      periods: ["YESTERDAY"],
      non_canonical_periods: [],
      last_synced_at: new Date().toISOString(),
      platforms: PLATFORMS,
      platform_conflicts: [],
      recent_actions: ACTIONS,
      reports: {},
      observations_due: { count: 0, oldest_due: null },
      display: null,
      server_today: TODAY,
    },
    overrides
  );
}

/** A single-client (OSS-shaped) install, which opens on the detail view. */
async function openDetail(overrides) {
  const page = loadDashboardPage({
    "/api/reports/clients": {
      clients: [{ slug: "alpha", name: "Alpha", active: true }],
      can_archive: false,
    },
    "/api/reports/summary": () => summaryWith(overrides),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

/** A two-client roster, which opens on the index. */
async function openIndex() {
  const roster = [
    { slug: "alpha", name: "Alpha", active: true },
    { slug: "beta", name: "Beta", active: true },
  ];
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: roster, can_archive: false },
    "/api/reports/summary": () => summaryWith({}),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

const container = (page) => page.root.querySelector("[data-dashboard-reports]");

/** The winning declaration for `property` on `node`. */
function styleOfNode(node, label, property) {
  assert.ok(node, label + " is not in the page");
  const won = cascade(node, property);
  return won ? won.value : undefined;
}

function styleOf(page, sel, property) {
  return styleOfNode(page.root.querySelector(sel), sel, property);
}

// ---------------------------------------------------------------------
// The scope: one container, two screens
// ---------------------------------------------------------------------

test.describe("the detail view marks the container it shares with the index", function () {
  test.it("marks it on the way in and clears it on the way back", async function () {
    const page = await openIndex();
    assert.equal(
      container(page).classList.contains(DETAIL_CLASS),
      false,
      "the index is already marked as the detail screen"
    );

    page.root.querySelector(".roster-name").click();
    await settle();
    assert.equal(
      container(page).classList.contains(DETAIL_CLASS),
      true,
      "opening a client did not mark the container"
    );

    page.root.querySelector("[data-reports-back]").click();
    await settle();
    assert.equal(
      container(page).classList.contains(DETAIL_CLASS),
      false,
      "the mark survived the trip back to the index"
    );
  });

  test.it("marks it on a single-client install too, which never sees an index", async function () {
    // The OSS shape: the detail IS the section, so it is reached without a
    // click on anything. A mark applied only from the card grid would leave
    // this install on the index's paint forever.
    const page = await openDetail();
    assert.equal(container(page).classList.contains(DETAIL_CLASS), true);
  });

  test.it("publishes the class name the stylesheet scopes on", async function () {
    // The string is in three files. This is the one place they meet.
    const page = await openDetail();
    assert.equal(page.sandbox.MUREO_DASHBOARD_REPORTS.REPORTS_DETAIL_CLASS, DETAIL_CLASS);
    const fs = require("node:fs");
    const css = fs.readFileSync(path.join(WEB, "app.css"), "utf-8");
    assert.ok(
      css.includes(".dashboard-reports." + DETAIL_CLASS + " {"),
      "app.css scopes nothing on " + DETAIL_CLASS
    );
  });
});

// ---------------------------------------------------------------------
// The ground comes off the container, and onto the sections
// ---------------------------------------------------------------------

test.describe("the detail screen's ground is its sections', not the page's", function () {
  test.it("takes the slab off the container while the detail is up", async function () {
    const page = await openDetail();
    assert.equal(
      styleOfNode(container(page), ".dashboard-reports", "background"),
      "transparent",
      "the whole-report slab is still painted under the detail view"
    );
    // Transparent rather than dropped: the border and the padding are still
    // in the box, so nothing inside it moves by a pixel.
    assert.equal(
      styleOfNode(container(page), ".dashboard-reports", "border-color"),
      "transparent"
    );
    assert.equal(styleOfNode(container(page), ".dashboard-reports", "padding"), "16px");
  });

  //: Every top-level grouping of the detail view, and the screen it appears
  //: on: the legacy three-tier screen, or the contract-driven one.
  const SECTIONS = [
    [".reports-tier", "legacy"],
    [".dashboard-reports-block", "legacy"],
    [".reports-prose", "legacy"],
    [".reports-funnel", "contract"],
    [".reports-chart", "contract"],
    [".reports-proposals", "contract"],
  ];

  test.it("gives every grouping the report surface, rounded and padded", async function () {
    const pages = {
      legacy: await openDetail({
        reports: {
          YESTERDAY: {
            narrative: "Spend held, CPA improved.",
            generated_at: new Date().toISOString(),
          },
        },
      }),
      contract: await openDetail({ display: DISPLAY }),
    };
    SECTIONS.forEach(function ([sel, screen]) {
      const page = pages[screen];
      assert.equal(
        styleOf(page, sel, "background"),
        "var(--report-surface)",
        sel + " is not on the report surface"
      );
      assert.equal(
        styleOf(page, sel, "border-radius"),
        "var(--r-lg)",
        sel + " is not a rounded block"
      );
      assert.equal(
        styleOf(page, sel, "border"),
        "1px solid var(--report-line)",
        sel + " has no edge on that ground"
      );
      assert.ok(styleOf(page, sel, "padding"), sel + " has no padding of its own");
    });
  });

  test.it("keeps the funnel's gap outside the block it now sits in", async function () {
    // The row carried `margin-bottom: 20px` to separate the funnel from the
    // chart. Left there it would open 20px of empty tint INSIDE the new
    // block instead of between it and the next one.
    const page = await openDetail({ display: DISPLAY });
    assert.equal(styleOf(page, ".reports-funnel-row", "margin-bottom"), "0");
    assert.equal(styleOf(page, ".reports-funnel", "margin-bottom"), "20px");
  });

  test.it("separates the blocks that sit in the flow with whitespace", async function () {
    // Two surfaces touching read as one section with a seam. The chart and
    // the proposals are grid items and take their gap from the grid; these
    // four are in the flow and have to state it. The recent-actions log is
    // the one that had air above it and none below, which was the right
    // answer for a block with no edges.
    const page = await openDetail({
      display: DISPLAY,
      reports: { YESTERDAY: { narrative: "Spend held.", generated_at: TODAY } },
    });
    [".reports-tier", ".dashboard-reports-block", ".reports-funnel", ".reports-prose"].forEach(
      function (sel) {
        const gap = styleOf(page, sel, "margin-bottom") || styleOf(page, sel, "margin");
        assert.ok(gap, sel + " states no gap to the block under it");
        assert.ok(
          parseFloat(String(gap).split(/\s+/).pop()) > 0,
          sel + " meets the next block with no whitespace: " + gap
        );
      }
    );
  });

  test.it("leaves the 運用ナビ band blue — it is a voice, not a section", async function () {
    const page = await openDetail({ display: DISPLAY });
    assert.equal(styleOf(page, ".reports-nav-band", "background"), "var(--report-blue)");
  });
});

// ---------------------------------------------------------------------
// The index screen is out of scope, and stays that way
// ---------------------------------------------------------------------

test.describe("the list screen keeps the ground it had", function () {
  test.it("keeps the slab on the container", async function () {
    const page = await openIndex();
    assert.equal(
      styleOfNode(container(page), ".dashboard-reports", "background"),
      "var(--report-surface)"
    );
    assert.equal(
      styleOfNode(container(page), ".dashboard-reports", "border"),
      "1px solid var(--report-line)"
    );
  });

  test.it("keeps its panels white on that slab", async function () {
    // `.reports-panel` is on BOTH screens. Repainting it outright — rather
    // than inside the detail's scope — would recolour the client list, the
    // alert layer and the rail, which is the one thing #731 must not do.
    const page = await openIndex();
    const grid = page.root.querySelector("[data-reports-index-grid]");
    const panels = grid.querySelectorAll(".reports-panel");
    assert.ok(panels.length >= 2, "the index rendered no panels to check");
    panels.forEach(function (node) {
      assert.equal(
        styleOfNode(node, ".reports-panel", "background"),
        "var(--surface)",
        "an index panel was repainted with the detail screen's ground"
      );
    });
  });

  test.it("still comes back to the slab after a client and back", async function () {
    // The end-to-end of the mark: paint, not just a class attribute.
    const page = await openIndex();
    page.root.querySelector(".roster-name").click();
    await settle();
    page.root.querySelector("[data-reports-back]").click();
    await settle();
    assert.equal(
      styleOfNode(container(page), ".dashboard-reports", "background"),
      "var(--report-surface)"
    );
  });
});
