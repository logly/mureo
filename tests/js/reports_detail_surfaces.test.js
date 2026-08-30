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
    timestamp: new Date().toISOString(),
    action: "budget_raised",
    platform: "google_ads",
    summary: "Raised the Brand budget",
    observation_due: TODAY,
  },
];

//: A contract stating the sections the legacy screen does not draw. Five
//: proposals, because the list caps at four and the "+N more" row is one of
//: the lines this suite is about.
const DISPLAY = {
  source: "daily-check",
  generated_at: new Date(Date.now() - 3 * 3600000).toISOString(),
  nav_message: "CPA is over target — pause the two worst ad groups",
  highlights: [
    { tone: "bad", text: "CPA 12% over target" },
    { tone: "good", text: "CV goal met" },
  ],
  proposals: [1, 2, 3, 4, 5].map(function (n) {
    return { title: "Pause ad group " + n, body: "3x target CPA", date: TODAY };
  }),
  breakdown: {
    campaigns: [
      {
        name: "Brand Search",
        spend: 42000,
        mcpa: 5200,
        target_cpa: 4500,
        state: "worsening",
        note: "capped every afternoon",
      },
    ],
    adgroups: [{ name: "Brand — exact", spend: 12000, state: "target_met" }],
  },
  stated_values: [
    { label: "CVR", value: 0.021 },
    { label: "goals met", value: "3 of 7" },
  ],
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

const detailView = (page) => page.root.querySelector("[data-reports-detail]");

/**
 * The same, for the first `sel` INSIDE the detail view.
 *
 * Several of these class names are on both screens — `.reports-panel-note`
 * is the index rail's note too, and it comes first in the document — so a
 * page-wide querySelector would answer about the wrong screen.
 */
function styleIn(page, sel, property) {
  return styleOfNode(detailView(page).querySelectorAll(sel)[0], sel, property);
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
    [".reports-breakdown", "contract"],
    [".reports-stated", "contract"],
    [".reports-highlights", "contract"],
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
// What the sections do to the things inside them
// ---------------------------------------------------------------------

test.describe("nothing inside a block goes flat against it", function () {
  test.it("steps the breakdown header off both the block and the table", async function () {
    // The header row took --report-surface, which was a tint on a white
    // table while the section around it was the page. Now that the section
    // IS that colour the same fill would read as the ground showing through
    // the table — a header that has stopped being a header.
    const page = await openDetail({ display: DISPLAY });
    const table = page.root.querySelector(".reports-breakdown-table");
    assert.ok(table, "the breakdown table did not render");
    const th = table.querySelectorAll("th")[0];
    const section = styleOf(page, ".reports-breakdown", "background");
    const body = styleOfNode(table, ".reports-breakdown-table", "background");
    const header = styleOfNode(th, ".reports-breakdown-table thead th", "background");
    assert.equal(section, "var(--report-surface)");
    assert.equal(body, "var(--surface)");
    assert.equal(header, "var(--report-line)");
    assert.equal(
      new Set([section, body, header]).size,
      3,
      "the block, the table and its header are not three different fills"
    );
  });

  test.it("leaves the list screen's roster header on the ground it had", async function () {
    // The same token, on the other screen, where the table sits inside a
    // WHITE panel and the tint is exactly what separates the header from it.
    const page = await openIndex();
    const th = page.root.querySelector(".roster").querySelectorAll("th")[0];
    assert.equal(
      styleOfNode(th, ".roster thead th", "background"),
      "var(--report-surface)"
    );
  });

  test.it("insets the proposal cards from the panel's own edges", async function () {
    // The tinted cards ran the full width of the panel's padding box and
    // read as pressed against the frame (#734). The inset is on the LIST,
    // so the cards move in as a group and the panel's heading, count and
    // "more" line keep the edge they share with every other panel.
    const page = await openDetail({ display: DISPLAY });
    assert.equal(styleIn(page, ".reports-proposal-list", "padding"), "0 10px");
    // Not by moving the text that introduces them.
    assert.equal(
      styleIn(page, ".reports-proposals-count", "padding"),
      undefined,
      "the panel's count line gained a padding of its own"
    );
  });

  test.it("leaves the list screen's proposals list where it was", async function () {
    // Detail scope only: the index has its own uses of the panel, and the
    // acceptance condition for the whole #731/#734 pass is that it does not
    // move.
    const page = await openIndex();
    const css = require("node:fs").readFileSync(path.join(WEB, "app.css"), "utf-8");
    const at = css.indexOf("\n.reports-proposal-list {");
    assert.notEqual(at, -1, ".reports-proposal-list has no base rule");
    assert.match(css.slice(at).split("}", 1)[0], /padding: 0;/);
    assert.ok(page.root.querySelector("[data-reports-index-grid]"), "index drew");
  });
});

// ---------------------------------------------------------------------
// The action log: cards on the rail
// ---------------------------------------------------------------------

test.describe("each logged entry lifts off the block's ground", function () {
  /** The declarations of the first rule whose selector is exactly `sel`. */
  function ruleOf(css, sel) {
    const at = css.indexOf("\n" + sel + " {");
    assert.notEqual(at, -1, sel + " has no rule in app.css");
    return css.slice(at).split("}", 1)[0];
  }

  /** The first number in `prop`'s declaration in `body`. */
  function px(body, prop) {
    // `[{;]` and not `^`: `ruleOf` hands back the selector as well as the
    // body, so the first declaration follows the brace rather than starting
    // the string.
    const m = new RegExp("[{;]\\s*" + prop + "\\s*:\\s*(-?[\\d.]+)px").exec(body);
    assert.ok(m, prop + " is not a px length in: " + body.trim());
    return parseFloat(m[1]);
  }

  test.it("draws an entry as a white card, not a ruled row", async function () {
    const page = await openDetail({ display: DISPLAY });
    const row = detailView(page).querySelectorAll(".report-action")[0];
    assert.ok(row, "the log drew no entry");
    assert.equal(styleOfNode(row, ".report-action", "background"), "var(--surface)");
    assert.equal(
      styleOfNode(row, ".report-action", "border"),
      "1px solid var(--hairline)"
    );
    assert.equal(styleOfNode(row, ".report-action", "border-radius"), "var(--r-md)");
    // …on the ground the block still carries, which is what it lifts off.
    assert.equal(
      styleOf(page, ".dashboard-reports-block", "background"),
      "var(--report-surface)"
    );
  });

  test.it("gives the last card its bottom edge back", async function () {
    // `.report-action:last-child` exists to END a ruled sheet by removing
    // that hairline. On a card it would cut the bottom edge off the last
    // entry, so the scoped reset has to outrank it rather than merely
    // follow it in the file.
    const fs = require("node:fs");
    const css = fs.readFileSync(path.join(WEB, "app.css"), "utf-8");
    const scoped = ruleOf(
      css,
      ".dashboard-reports-detail .dashboard-reports-actions-list .report-action:last-child"
    );
    assert.match(scoped, /border-bottom: 1px solid var\(--hairline\);/);
    assert.match(scoped, /margin-bottom: 0;/);
  });

  test.it("keeps the dot straddling the rail the cards moved away from", function () {
    // The #691 timeline is the ul's `border-left` and a ::before per entry.
    // A card drawn at the old 2px inset takes that dot under its own left
    // border, so the list opens a gutter and the dot's offset is re-stated
    // against the card's padding box. This is that arithmetic, read out of
    // the stylesheet — the harness models no layout, and a dot that has
    // drifted off the rail is invisible to every other assertion here.
    const fs = require("node:fs");
    const css = fs.readFileSync(path.join(WEB, "app.css"), "utf-8");

    const railWidth = 1; // .dashboard-reports-block .dashboard-reports-actions-list
    assert.match(
      ruleOf(css, ".dashboard-reports-block .dashboard-reports-actions-list"),
      /border-left: 1px solid var\(--hairline\);/,
      "the rail is gone"
    );
    const gutter = px(
      ruleOf(
        css,
        ".dashboard-reports-detail .dashboard-reports-block .dashboard-reports-actions-list"
      ),
      "padding-left"
    );
    const card = ruleOf(
      css,
      ".dashboard-reports-detail .dashboard-reports-actions-list .report-action"
    );
    const cardBorder = px(card, "border");
    const dot = ruleOf(css, ".dashboard-reports-actions-list .report-action::before");
    const size = px(dot, "width");
    const offset = px(
      ruleOf(
        css,
        ".dashboard-reports-detail .dashboard-reports-actions-list .report-action::before"
      ),
      "left"
    );

    // x = 0 at the rail's left edge; the line covers 0..railWidth.
    const cardPaddingBox = railWidth + gutter + cardBorder;
    const dotLeft = cardPaddingBox + offset;
    const dotCentre = dotLeft + size / 2;
    assert.ok(
      dotCentre >= -1 && dotCentre <= railWidth + 1,
      "the dot no longer straddles the rail: centre at " + dotCentre
    );
    // …and it clears the card, rather than sitting under its left border.
    assert.ok(
      dotLeft + size <= railWidth + gutter,
      "the dot runs under the card's left edge"
    );
  });
});

// ---------------------------------------------------------------------
// The captions that moved from a white panel onto the ground
// ---------------------------------------------------------------------

test.describe("small text on the ground keeps AA", function () {
  //: Every --muted line the new blocks put on the ground itself. --muted is
  //: 4.96:1 on a white panel and 4.31:1 on this ground, which is under AA
  //: for small text, so each of these takes --ink-soft (9.2:1 light,
  //: 11.5:1 dark) inside the detail scope. Restated here so the set is
  //: checkable at a glance, and asserted against the stylesheet below.
  //:
  //: The proposal DATE is the one that is not on the ground — it is on the
  //: --warn-tint proposal, where it measured 4.49:1 on its own terms.
  const LIFTED = [
    ".reports-panel-note",
    ".reports-proposals-count",
    ".reports-proposal-more",
    ".reports-proposal-date",
    ".reports-chart-tick",
    ".reports-tier-note",
    ".reports-client-kpi-label",
    ".report-latest-generated",
    ".report-latest-stats caption.report-stats-title",
    ".report-latest-stats .report-stat-key",
    ".report-latest-stats .report-stat-more",
    ".dashboard-reports-block h3",
    ".reports-actions-page-btn",
    ".reports-actions-page-count",
  ];

  //: The two that came BACK off the lift. The log's entries are white cards
  //: now, so its time and observation-due lines are on --surface again —
  //: 4.96:1, the same "kept its background" rule as everything else here.
  const RESTORED = [".report-action-time", ".report-action-meta"];

  test.it("scopes every one of them, and scopes them to the detail", function () {
    const fs = require("node:fs");
    const css = fs.readFileSync(path.join(WEB, "app.css"), "utf-8");
    LIFTED.forEach(function (sel) {
      assert.ok(
        css.includes(".dashboard-reports-detail " + sel + ",\n") ||
          css.includes(".dashboard-reports-detail " + sel + " {"),
        sel + " is not lifted off --muted in the detail scope"
      );
    });
    RESTORED.forEach(function (sel) {
      assert.equal(
        css.includes(".dashboard-reports-detail " + sel + ",\n"),
        false,
        sel + " is lifted again, and it is back on a white card"
      );
    });
  });

  test.it("resolves to --ink-soft on the nodes an operator sees", async function () {
    // The stylesheet pin above cannot see a rule that loses its cascade.
    // These are the same lines, asked of the rendered page — and asked
    // INSIDE the detail view, because `.reports-panel-note` is also the
    // index rail's note and it comes first in the document.
    const page = await openDetail({ display: DISPLAY });
    [
      ".reports-panel-note",
      ".reports-proposals-count",
      ".reports-proposal-more",
      ".reports-proposal-date",
      ".reports-chart-tick",
      ".reports-tier-note",
      // `.reports-actions-page-btn` is deliberately NOT here: its `:hover`
      // rule outranks the lift, and the harness treats an unmodelled
      // pseudo-class as matching, so it would answer for a hover state no
      // operator is in. The stylesheet pin above covers it.
      ".reports-actions-page-count",
    ].forEach(function (sel) {
      assert.equal(
        styleIn(page, sel, "color"),
        "var(--ink-soft)",
        sel + " is still --muted on the report ground"
      );
    });
    // `.dashboard-reports-block h3` — the log's own caption heading — is
    // not asked here either: the harness's compound matcher rejects a type
    // selector carrying a digit, so `h3` matches nothing and the cascade
    // comes back empty for BOTH rules. The stylesheet pin covers it.
  });

  test.it("leaves --muted alone where the background did not move", async function () {
    // A caption inside a white card or a --surface-2 chip kept its
    // background, so it keeps its colour: this is a repair of a regression,
    // not a repaint of the screen.
    const page = await openDetail({ display: DISPLAY });
    [
      ".reports-funnel-label",
      ".report-action-platform",
      ".reports-stated-label",
      ".reports-breakdown-note",
    ].concat(RESTORED).forEach(function (sel) {
      assert.equal(
        styleIn(page, sel, "color"),
        "var(--muted)",
        sel + " was recoloured, and its background never moved"
      );
    });
    // A chart tab that is not the selected one — the selected segment is
    // filled and carries its own colour, which is not what this asks.
    const tab = detailView(page)
      .querySelectorAll(".reports-chart-tab")
      .find(function (n) {
        return !n.classList.contains("is-active");
      });
    assert.ok(tab, "the chart drew no idle tab to check");
    assert.equal(styleOfNode(tab, ".reports-chart-tab", "color"), "var(--muted)");
  });

  test.it("does not reach the list screen's copies of the same classes", async function () {
    // `.reports-panel-note` is the rail's note over there, on a white panel.
    const page = await openIndex();
    const grid = page.root.querySelector("[data-reports-index-grid]");
    const note = grid.querySelectorAll(".reports-panel-note")[0];
    assert.ok(note, "the index rendered no panel note to check");
    assert.equal(styleOfNode(note, ".reports-panel-note", "color"), "var(--muted)");
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
