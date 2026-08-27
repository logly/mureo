// The contract-driven detail screen, as an operator sees it (#706 step 3-a).
//
// Run with:  node --test tests/js/*.test.js
//
// Driven against the real dashboard, the real app.html AND the real app.css,
// because that is what the three defects this suite exists to prevent turn
// on. A DOM-shape assertion cannot see any of them:
//
//   • a section rendered but never un-hidden (the #691 bug: a data attribute
//     already in use elsewhere, so querySelector returned the wrong node);
//   • an author `display` rule beating `[hidden]`, so a "hidden" section
//     stays on screen — the reason this harness exists at all;
//   • the LEGACY screen and the contract screen both drawing at once, which
//     is a correct render of each and a nonsense page.
//
// THREE STATES, and all three are supported paths rather than one path and
// two edge cases:
//
//   • **full** — a contract stating every section;
//   • **none** — no `display` at all, which is every client on every install
//     until a skill writes one, and which must still render the three-tier
//     screen that shipped before this;
//   • **partial** — a contract stating one section (a nav line and nothing
//     else). This is the state the whole design turns on: every other
//     section must vanish frame and all, because an empty box promising a
//     chart is worse than no chart.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  loadDashboardPage,
  settle,
  isVisible,
  cascade,
} = require("./dom_harness.js");

const TODAY = new Date().toISOString().slice(0, 10);

/** `n` days before today, as `YYYY-MM-DD`. */
function daysAgo(n) {
  return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
}

function platform(key, totals, daily) {
  return {
    key: key,
    display_name: key === "google_ads" ? "Google Ads" : key,
    totals: totals || null,
    metrics_period: "YESTERDAY",
    campaign_count: 2,
    freshness: { fetched_at: new Date().toISOString(), stale: false },
    not_collected: null,
    daily: daily || [],
    daily_delta: null,
  };
}

/** Seven calendar-adjacent days of one metric — enough to draw. */
function week(metric) {
  const out = [];
  for (let i = 7; i >= 1; i--) {
    const totals = {};
    totals[metric] = 10 + i;
    out.push({ date: daysAgo(i), totals: totals });
  }
  return out;
}

function summaryWith(overrides) {
  return Object.assign(
    {
      client: "alpha",
      period: "YESTERDAY",
      periods: ["YESTERDAY"],
      non_canonical_periods: [],
      last_synced_at: new Date().toISOString(),
      platforms: [],
      platform_conflicts: [],
      recent_actions: [],
      reports: {},
      display: null,
      server_today: TODAY,
    },
    overrides
  );
}

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

//: A contract stating all five sections plus its attribution.
const FULL_DISPLAY = {
  source: "daily-check",
  generated_at: new Date(Date.now() - 3 * 3600000).toISOString(),
  nav_message: "CPA is over target — pause the two worst ad groups",
  highlights: [
    { tone: "bad", text: "CPA 12% over target" },
    { tone: "good", text: "CV goal met" },
  ],
  proposals: [
    { title: "Pause two ad groups", body: "Both 3x target CPA", date: TODAY },
    { title: "Raise Brand budget", status: "done", date: TODAY },
  ],
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

const FULL_PLATFORMS = [
  platform(
    "google_ads",
    { spend: 42000, impressions: 100000, clicks: 900, conversions: 8, cpa: 5250 },
    week("conversions")
  ),
];

/** The winning declaration for `property` on the first `sel` in the page. */
function styleOf(page, sel, property) {
  return styleOfNode(page.root.querySelector(sel), sel, property);
}

/**
 * The same, for a node the caller already found.
 *
 * The harness's querySelector takes ONE simple selector (see its header), so
 * a compound like `.reports-chart-tab.is-active` has to be resolved by
 * filtering rather than queried — while `cascade` itself understands the
 * compound perfectly, which is the whole point of asking it.
 */
function styleOfNode(node, label, property) {
  assert.ok(node, label + " is not in the page");
  const won = cascade(node, property);
  return won ? won.value : undefined;
}

/** The first `.cls` element that also carries `extra`. */
function withClass(page, cls, extra) {
  return page.root.querySelectorAll("." + cls).find(function (n) {
    return (n.getAttribute("class") || "").split(/\s+/).indexOf(extra) !== -1;
  });
}

function shown(page, attr) {
  const node = page.root.querySelector("[" + attr + "]");
  return !!node && isVisible(node);
}

// ---------------------------------------------------------------------
// State 1: a contract stating everything
// ---------------------------------------------------------------------

test.describe("a client with a full display contract", function () {
  test.it("shows the operator line, and says who wrote the screen", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-nav"));
    assert.equal(
      page.root.querySelector("[data-reports-nav-text]").textContent,
      FULL_DISPLAY.nav_message
    );
    // The contract is replaced whole by whoever writes it last, so the
    // content cannot answer "whose answer is this?" — the band does.
    const by = page.root.querySelector("[data-reports-nav-by]").textContent;
    assert.match(by, /daily-check/);
  });

  test.it("draws the funnel from the canonical totals", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-funnel"));
    const body = page.root.querySelector("[data-reports-funnel-body]");
    const labels = body
      .querySelectorAll(".reports-funnel-label")
      .map(function (n) {
        return n.textContent;
      });
    assert.equal(labels.length, 4, "four steps: spend → impr → clicks → CV");
    // Derived, not written: this is exactly why #706 kept the funnel out of
    // the contract. CPC = 42000/900 = 46.67 → 47.
    const subs = body.querySelectorAll(".reports-funnel-sub-value").map(function (n) {
      return n.textContent;
    });
    assert.equal(subs.length, 3, "impressions, clicks and CV carry a rate");
    assert.equal(subs[1], "47");
  });

  test.it("draws the daily chart with its granularity switch", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-chart"));
    assert.ok(page.root.querySelector(".reports-chart-svg"), "an svg was drawn");
    const grains = page.root
      .querySelector("[data-reports-chart-grains]")
      .querySelectorAll(".reports-chart-tab");
    assert.equal(grains.length, 3, "day / week / month");
  });

  test.it("lists the open proposals and counts the done ones", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-proposals"));
    const items = page.root
      .querySelector("[data-reports-proposals-list]")
      .querySelectorAll(".reports-proposal");
    assert.equal(items.length, 1, "only the one that is not done");
    assert.match(
      page.root.querySelector("[data-reports-proposals-count]").textContent,
      /1/
    );
  });

  test.it("draws both breakdown tables with state badges", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-breakdown-campaigns"));
    assert.ok(shown(page, "data-reports-breakdown-adgroups"));
    const badge = page.root.querySelector(".reports-state-badge");
    assert.ok(badge, "the closed state vocabulary is drawn as a badge");
    // The enum reaches the DOM as a semantic class, not as a raw token —
    // and `worsening` gets its OWN class rather than sharing the alert one,
    // because it is amber: red on these screens is "act now" and nothing
    // else.
    assert.match(badge.getAttribute("class"), /is-worsening/);
  });

  test.it("shows a figure the row does not state as a dash", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    // The ad-group row carries no mcpa: a campaign with no conversions has
    // no cost per acquisition, and 0 would state a perfect one.
    const cells = page.root
      .querySelector("[data-reports-breakdown-adgroups-body]")
      .querySelectorAll(".reports-breakdown-num")
      .map(function (n) {
        return n.textContent;
      });
    assert.equal(cells[1], "—");
  });

  test.it("shows stated values as chips, never the legacy table", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      reports: {
        daily: {
          generated_at: new Date().toISOString(),
          narrative: "Healthy overall.",
          totals: { spend: 42000, cvr: 0.021 },
        },
      },
    });
    assert.ok(shown(page, "data-reports-stated"));
    const chips = page.root
      .querySelector("[data-reports-stated-body]")
      .querySelectorAll(".reports-stated-chip");
    assert.equal(chips.length, 2);
    // The old label/value table lives inside tier (1), which a contract
    // replaces outright — two renderings of "what this report stated" on one
    // screen is the thing the contract exists to end.
    assert.equal(shown(page, "data-reports-latest"), false);
  });

  test.it("colours the highlight chips from their tone", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-highlights"));
    const chips = page.root
      .querySelector("[data-reports-highlights]")
      .querySelectorAll(".reports-highlight");
    assert.equal(chips.length, 2);
    assert.match(chips[0].getAttribute("class"), /is-bad/);
    assert.match(chips[1].getAttribute("class"), /is-good/);
  });

  test.it("moves the narrative behind a disclosure", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      reports: {
        daily: {
          generated_at: new Date().toISOString(),
          narrative: "Healthy: both goals are met on the current trend.",
        },
      },
    });
    const prose = page.root.querySelector("[data-reports-prose]");
    assert.ok(isVisible(prose), "the disclosure is offered");
    assert.equal(prose.tagName, "DETAILS", "closed until it is opened");
    assert.match(
      page.root.querySelector("[data-reports-prose-body]").textContent,
      /both goals are met/
    );
  });

  test.it("hides every legacy tier", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      reports: { daily: { generated_at: new Date().toISOString(), narrative: "x." } },
    });
    // Both screens drawing at once is a correct render of each and a
    // nonsense page — the same content twice, in two shapes.
    assert.equal(shown(page, "data-reports-latest"), false);
    assert.equal(shown(page, "data-reports-changes"), false);
    assert.equal(shown(page, "data-reports-platform-tier"), false);
  });
});

// ---------------------------------------------------------------------
// State 2: no contract — the screen every client has until a skill runs
// ---------------------------------------------------------------------

test.describe("a client with no display contract", function () {
  test.it("still gets the three-tier screen", async function () {
    const page = await openDetail({
      platforms: FULL_PLATFORMS,
      reports: {
        daily: {
          generated_at: new Date().toISOString(),
          narrative: "Healthy: nothing needs attention today.",
          totals: { spend: 42000 },
        },
      },
    });
    // Not a fallback and not deprecated: this is what a correct client
    // without a contract looks like, and it must keep working unchanged.
    assert.ok(shown(page, "data-reports-latest"));
    assert.ok(shown(page, "data-reports-platform-tier"));
  });

  test.it("draws none of the contract sections", async function () {
    const page = await openDetail({
      platforms: FULL_PLATFORMS,
      reports: { daily: { generated_at: new Date().toISOString(), narrative: "x." } },
    });
    [
      "data-reports-nav",
      "data-reports-funnel",
      "data-reports-chart",
      "data-reports-proposals",
      "data-reports-breakdown-campaigns",
      "data-reports-breakdown-adgroups",
      "data-reports-stated",
      "data-reports-highlights",
      "data-reports-prose",
    ].forEach(function (attr) {
      assert.equal(shown(page, attr), false, attr + " must not be on screen");
    });
  });
});

// ---------------------------------------------------------------------
// State 3: a contract stating ONE section
// ---------------------------------------------------------------------

test.describe("a contract stating only a nav line", function () {
  test.it("shows the band and nothing else the contract owns", async function () {
    const page = await openDetail({
      display: { source: "weekly-report", nav_message: "Spend is on pace" },
      platforms: FULL_PLATFORMS,
    });
    assert.ok(shown(page, "data-reports-nav"));
    // An empty frame is a promise the data has not kept — this is the state
    // the whole design turns on, and it is the COMMON one.
    assert.equal(shown(page, "data-reports-proposals"), false);
    assert.equal(shown(page, "data-reports-breakdown-campaigns"), false);
    assert.equal(shown(page, "data-reports-breakdown-adgroups"), false);
    assert.equal(shown(page, "data-reports-stated"), false);
    assert.equal(shown(page, "data-reports-highlights"), false);
  });

  test.it("still draws the funnel and chart, which are NOT the contract", async function () {
    const page = await openDetail({
      display: { source: "weekly-report", nav_message: "Spend is on pace" },
      platforms: FULL_PLATFORMS,
    });
    // Derived from the stored totals and the day-grain history, so they do
    // not depend on what the skill chose to write.
    assert.ok(shown(page, "data-reports-funnel"));
    assert.ok(shown(page, "data-reports-chart"));
  });

  test.it("hides the funnel and the chart when the platform has neither", async function () {
    const page = await openDetail({
      display: { source: "weekly-report", nav_message: "Spend is on pace" },
      platforms: [platform("google_ads", null, [])],
    });
    assert.equal(shown(page, "data-reports-funnel"), false);
    assert.equal(shown(page, "data-reports-chart"), false);
    assert.ok(shown(page, "data-reports-nav"), "…and the band survives alone");
  });

  test.it("says nothing about the author when the contract predates it", async function () {
    const page = await openDetail({
      display: { nav_message: "Spend is on pace" },
      platforms: FULL_PLATFORMS,
    });
    // Contracts written before #706's review round carry no attribution,
    // and a guess would be worse than silence.
    assert.equal(page.root.querySelector("[data-reports-nav-by]").textContent, "");
  });
});

// ---------------------------------------------------------------------
// The action log, which both screens share
// ---------------------------------------------------------------------

test.describe("the action log", function () {
  test.it("shows a display line alone when the entry has one", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      recent_actions: [
        {
          timestamp: new Date().toISOString(),
          action: "google_ads_budget_update",
          platform: "google_ads",
          summary: "a".repeat(400),
          display_title: "Raised the Brand budget",
          display_summary: "Capped every afternoon; +20% daily.",
          observation_due: null,
        },
      ],
    });
    const row = page.root.querySelector(".report-action");
    assert.match(row.textContent, /Raised the Brand budget/);
    assert.match(row.textContent, /Capped every afternoon/);
    // The work-journal note is NOT on screen: it was written for the next
    // agent, and it is what turned this list into a wall.
    assert.equal(row.textContent.indexOf("a".repeat(200)), -1);
  });

  test.it("cuts a legacy summary short and offers the rest", async function () {
    // No trailing space: the strip pass trims, and a fixture that ended in
    // one would be asserting the whitespace rather than the text.
    const long = ("Budget raised. " + "detail ".repeat(40)).trim();
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      recent_actions: [
        {
          timestamp: new Date().toISOString(),
          action: "google_ads_budget_update",
          platform: "google_ads",
          summary: long,
          observation_due: null,
        },
      ],
    });
    const shortText = page.root.querySelector(".report-action-summary").textContent;
    assert.ok(shortText.length < long.length, "the row is not the wall");
    // Nothing is lost: the whole string is one click away, and the STORED
    // entry was never touched.
    const more = page.root.querySelector(".report-action-more");
    assert.ok(more, "the rest is offered");
    assert.equal(page.root.querySelector(".report-action-full").textContent, long);
  });

  test.it("strips markdown emphasis a person would read as asterisks", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
      recent_actions: [
        {
          timestamp: new Date().toISOString(),
          action: "google_ads_budget_update",
          platform: "google_ads",
          summary: "**Brand Search** budget raised to *12,000*",
          observation_due: null,
        },
      ],
    });
    const text = page.root.querySelector(".report-action-summary").textContent;
    assert.equal(text.indexOf("*"), -1, "raw markers never reach the screen");
    assert.match(text, /Brand Search budget raised to 12,000/);
  });
});

// ---------------------------------------------------------------------
// The platform picker
// ---------------------------------------------------------------------

test.describe("the platform picker", function () {
  test.it("is offered only when there is a choice", async function () {
    const one = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.equal(shown(one, "data-reports-detail-platform"), false);

    const two = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS.concat([
        platform("meta_ads", { spend: 1000, clicks: 10 }, []),
      ]),
    });
    assert.ok(shown(two, "data-reports-detail-platform"));
    const options = two.root
      .querySelector(".reports-platform-select")
      .querySelectorAll("option");
    assert.equal(options.length, 2);
  });
});

// ---------------------------------------------------------------------
// The mockup's design language
// ---------------------------------------------------------------------

test.describe("the screen's visual language", function () {
  test.it("puts the spend movement on the funnel, in blue", async function () {
    const withDelta = FULL_PLATFORMS.map(function (p) {
      return Object.assign({}, p, {
        daily_delta: { from: daysAgo(2), to: daysAgo(1), metrics: { spend: 35156 } },
      });
    });
    const page = await openDetail({ display: FULL_DISPLAY, platforms: withDelta });
    const delta = page.root.querySelector(".reports-funnel-delta");
    assert.ok(delta, "spend states how it moved");
    assert.match(delta.textContent, /35,156/);
    // Blue, not red or green: a rise in spend is neither good nor bad
    // without a target nobody has put on the wire, and #694's capture found
    // that colouring it trains an operator to ignore the colour entirely.
    assert.equal(
      styleOf(page, ".reports-funnel-delta", "color"),
      "var(--report-blue-ink)"
    );
  });

  test.it("states no movement when the wire states none", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    // #690 emits a delta only across two CALENDAR-ADJACENT stored days, so
    // "no delta" is the common case and must not render as "± 0".
    assert.equal(page.root.querySelector(".reports-funnel-delta"), null);
  });

  test.it("makes the nav band a solid blue banner", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    assert.equal(
      styleOf(page, ".reports-nav-band", "background"),
      "var(--report-blue)"
    );
    assert.equal(
      styleOf(page, ".reports-nav-text", "color"),
      "var(--report-on-blue)"
    );
    assert.ok(
      page.root.querySelector(".reports-nav-mark"),
      "the mockup's mark leads the band"
    );
  });

  test.it("fills the selected chart tab rather than lifting it", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    // On a strip of three, a shadow alone is not a selection anyone can see.
    assert.equal(
      styleOfNode(
        withClass(page, "reports-chart-tab", "is-active"),
        ".reports-chart-tab.is-active",
        "background"
      ),
      "var(--report-blue)"
    );
  });

  test.it("keeps red for act-now and paints a worsening row amber", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    // The semantic discipline #691 set: red means "act now" and nothing
    // else, so a row trending the wrong way is a warning colour.
    assert.equal(
      styleOfNode(
        withClass(page, "reports-state-badge", "is-worsening"),
        ".reports-state-badge.is-worsening",
        "color"
      ),
      "var(--status-watch)"
    );
    assert.equal(
      styleOfNode(
        withClass(page, "reports-state-badge", "is-good"),
        ".reports-state-badge.is-good",
        "color"
      ),
      "var(--status-ok)"
    );
  });

  test.it("emphasises the figures in the proposals count", async function () {
    const page = await openDetail({
      display: FULL_DISPLAY,
      platforms: FULL_PLATFORMS,
    });
    const strong = page.root
      .querySelector("[data-reports-proposals-count]")
      .querySelectorAll("b");
    assert.ok(strong.length >= 1, "the numbers carry the emphasis");
    assert.equal(
      styleOfNode(strong[0], ".reports-proposals-count b", "color"),
      "var(--report-blue-ink)"
    );
  });
});

// ---------------------------------------------------------------------
// Token discipline
// ---------------------------------------------------------------------

test.describe("the detail screen's colours are tokens", function () {
  const fs = require("node:fs");
  const path = require("node:path");
  const CSS = fs.readFileSync(
    path.join(__dirname, "..", "..", "mureo", "_data", "web", "app.css"),
    "utf-8"
  );

  //: The blues the mockup's detail screen is built on. Added BESIDE --accent
  //: rather than over it: --accent is the indigo every control on every other
  //: screen uses, and repainting it would redesign six screens to style one.
  const NEW_TOKENS = [
    "--report-blue",
    "--report-blue-press",
    "--report-blue-ink",
    "--report-chart",
    "--report-chart-fill",
    "--report-chart-grid",
    "--report-on-blue",
  ];

  test.it("defines every new token in both themes", function () {
    // A token defined once is a token that looks wrong in the other theme —
    // #1b6ce0 as a banner fill on a #0e0f12 page is a hole in it.
    NEW_TOKENS.forEach(function (name) {
      const uses = CSS.split(name + ":").length - 1;
      assert.ok(uses >= 2, name + " is defined " + uses + " time(s), needs light + dark");
    });
  });

  test.it("uses no hard-coded colour in the new blocks", function () {
    // Every colour on this screen resolves through a token, so a theme
    // switch reaches all of it and the semantic vocabulary stays one
    // vocabulary. The one literal allowed is a font-size, not a colour.
    const start = CSS.indexOf("#706 step 3-a — the contract-driven detail screen");
    assert.ok(start > 0, "the section comment is the anchor for this scan");
    const block = CSS.slice(start);
    const literals = block
      .split("\n")
      .filter(function (line) {
        return (
          /:\s*(#[0-9a-fA-F]{3,8}|rgba?\()/.test(line) && !/^\s*(\/\*|\*)/.test(line)
        );
      });
    assert.deepEqual(literals, [], "hard-coded colours: " + literals.join(" | "));
  });
});
