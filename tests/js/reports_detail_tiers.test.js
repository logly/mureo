// The three-tier detail view, as an operator actually sees it (#691 phase 2).
//
// Run with:  node --test tests/js/*.test.js
//
// Every assertion here exists because a capture review caught something the
// rest of the suite could not. The DOM was right in all four cases — the
// nodes were built, with the right classes, in the right order — and the
// screen was still wrong. So these drive the real dashboard against the real
// app.html AND the real app.css, and ask what would be ON SCREEN:
//
//   • tier (3) never appeared, because `data-reports-platforms` was already
//     the INDEX rail's hook. querySelector returned the rail, the tier stayed
//     hidden, and every structural pin passed;
//   • the stated-values table rendered as a wrap of rounded pills, because a
//     superseded `.report-stat { display: inline-flex }` still applied to
//     what is now a <tr>;
//   • every delta was red, including a rise in spend;
//   • the bold lead sentence never fired on an English narrative.
//
// The lesson the first three share: a class name surviving a tag change, and
// an attribute hook surviving a second use, are both invisible to a substring
// pin and to a DOM-shape assertion. Only "would this be displayed" catches
// them.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  loadDashboardPage,
  settle,
  isVisible,
  DISPLAY_BY_CLASS,
  cascade,
} = require("./dom_harness.js");

const TODAY = new Date().toISOString().slice(0, 10);

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
      observations_due: { count: 0, oldest_due: null },
      server_today: TODAY,
    },
    overrides
  );
}

/**
 * The `daily` series a `daily_delta` was derived from.
 *
 * The server never emits one without the other — the delta IS
 * `latest - previous` over these two buckets — and since #691 phase 4 the
 * renderer reads the day it moved FROM out of this series rather than
 * back-calculating it from the window rollup. A fixture with a delta and no
 * series is a shape the wire cannot produce, and it would now (correctly)
 * render no delta at all, so the two are built together here.
 *
 * The newest day is given `totals` verbatim, because the card's headline and
 * the series' last day describe the same day; where they disagree the
 * renderer withholds the delta, which is its own test below.
 */
function dailyFor(totals, delta) {
  if (!delta || !delta.metrics) return [];
  const before = {};
  Object.keys(delta.metrics).forEach(function (key) {
    const now = totals[key];
    if (typeof now === "number") before[key] = now - delta.metrics[key];
  });
  return [
    { date: delta.from, totals: before },
    { date: delta.to, totals: Object.assign({}, totals) },
  ];
}

/** One platform row, optionally carrying a day-over-day delta. */
function platform(key, totals, delta) {
  return {
    key: key,
    display_name: key === "google_ads" ? "Google Ads" : "Meta Ads",
    totals: totals,
    metrics_period: "YESTERDAY",
    campaign_count: 3,
    freshness: { fetched_at: new Date().toISOString(), stale: false },
    not_collected: null,
    daily: dailyFor(totals, delta),
    daily_delta: delta || null,
  };
}

/** A single-client (OSS-shaped) roster, opened on the detail view. */
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

/** A two-client roster, which routes to the index (portfolio strip + grid). */
async function openIndex() {
  const roster = [
    { slug: "alpha", name: "Alpha", active: true },
    { slug: "beta", name: "Beta", active: true },
  ];
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: roster, can_archive: false },
    "/api/reports/summary": () =>
      summaryWith({
        platforms: [platform("google_ads", { spend: 1000, conversions: 10 })],
      }),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

/**
 * A two-client roster whose figures are STALE, so the alert list has a row in
 * it. `openIndex` above deliberately has no findings — the portfolio strip it
 * exists to render is present either way — and an empty alert list would make
 * the assertions below pass by checking nothing.
 */
async function openIndexWithAlert() {
  const stale = new Date(Date.now() - 11 * 86400000).toISOString();
  const roster = [
    { slug: "alpha", name: "Alpha", active: true },
    { slug: "beta", name: "Beta", active: true },
  ];
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: roster, can_archive: false },
    "/api/reports/summary": () =>
      summaryWith({
        platforms: [
          {
            key: "google_ads",
            display_name: "Google Ads",
            totals: { spend: 1000 },
            metrics_period: "YESTERDAY",
            campaign_count: 1,
            freshness: { fetched_at: stale, stale: true, stale_after_days: 2 },
            not_collected: null,
            daily: [],
            daily_delta: null,
          },
        ],
      }),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

// ---------------------------------------------------------------------
// (3) By platform — the tier that vanished
// ---------------------------------------------------------------------

test.describe("tier 3 reaches the screen", function () {
  test.it("is VISIBLE, not merely present, once a platform has figures", async function () {
    // The regression: the section existed with the right class and the right
    // children, and `hidden` was never cleared, so nothing an operator could
    // see was there at all.
    const page = await openDetail({
      platforms: [platform("google_ads", { spend: 42400, cpa: 3855 })],
    });
    const tier = page.root.querySelector("[data-reports-platform-tier]");
    assert.ok(tier, "the tier 3 section is not in app.html");
    assert.equal(tier.hidden, false, "tier 3 was left hidden");
    assert.ok(isVisible(tier), "tier 3 computes to display:none");

    const cards = page.root.querySelectorAll(".report-card");
    assert.ok(cards.length > 0, "no platform card was rendered");
    assert.ok(isVisible(cards[0]), "the platform card is not on screen");
  });

  test.it("does not borrow the index rail's hook", async function () {
    // `data-reports-platforms` belongs to the "Spend by platform" aside on the
    // INDEX. Two elements answering one querySelector is what broke this, and
    // the second use is what must never come back.
    const fs = require("node:fs");
    const path = require("node:path");
    const html = fs.readFileSync(
      path.join(__dirname, "..", "..", "mureo", "_data", "web", "app.html"),
      "utf-8"
    );
    const uses = html.split("data-reports-platforms").length - 1;
    assert.equal(uses, 1, "data-reports-platforms is hooked twice again");
  });

  test.it("stays hidden when the client has no platforms at all", async function () {
    // The other half: an empty roster must not leave an empty numbered
    // heading on the page.
    const page = await openDetail({ platforms: [] });
    const tier = page.root.querySelector("[data-reports-platform-tier]");
    assert.equal(tier.hidden, true, "tier 3 shows with nothing in it");
  });
});

// ---------------------------------------------------------------------
// The stated values, as a table and not as pills
// ---------------------------------------------------------------------

test.describe("the stated values lay out as a table", function () {
  test.it("gives tr.report-stat no display that would break table layout", async function () {
    // The regression, stated against the stylesheet: `.report-stat` was a
    // <span> and is a <tr>. The chip rule that styled the span survived, and
    // `inline-flex` on a table row silently defeats the table.
    const declared = DISPLAY_BY_CLASS.get("report-stat");
    assert.ok(
      declared === undefined || /^table/.test(declared),
      ".report-stat declares display:" + declared + ", which is not a table row"
    );
  });

  test.it("builds real table rows inside a real table", async function () {
    const page = await openDetail({
      reports: { daily: { totals: { spend: 1, cvr: "0.21%" }, narrative: "x" } },
    });
    const table = page.root.querySelector(".report-latest-stats");
    assert.ok(table, "the stated-values block is missing");
    assert.equal(table.tagName, "TABLE");
    const row = page.root.querySelector(".report-stat");
    assert.equal(row.tagName, "TR", "a stated value is not a table row");
    assert.ok(isVisible(row), "the row is not on screen");
  });
});

// ---------------------------------------------------------------------
// (2) Deltas — colour is a verdict, so it is spent sparingly
// ---------------------------------------------------------------------

test.describe("a delta is coloured only where the direction means something", function () {
  async function toneFor(key, before, after) {
    const totals = {};
    totals[key] = after;
    const metrics = {};
    metrics[key] = after - before;
    const page = await openDetail({
      platforms: [
        platform("google_ads", totals, {
          from: "2026-08-20",
          to: "2026-08-21",
          metrics: metrics,
        }),
      ],
    });
    const delta = page.root.querySelector(".reports-change-delta");
    assert.ok(delta, "no change card was rendered for " + key);
    return delta.className;
  }

  test.it("calls a rising CPA bad and a falling one good", async function () {
    assert.match(await toneFor("cpa", 3000, 4200), /is-bad/);
    assert.match(await toneFor("cpa", 4200, 3000), /is-good/);
  });

  test.it("calls falling conversions bad and rising ones good", async function () {
    assert.match(await toneFor("conversions", 8, 4), /is-bad/);
    assert.match(await toneFor("conversions", 4, 8), /is-good/);
  });

  test.it("never paints a spend movement as a verdict", async function () {
    // The regression: spend rose and the card went red. Spending more is
    // usually the plan, and red here is the most misleading thing the tier
    // could say.
    assert.match(await toneFor("spend", 35900, 42400), /is-flat/);
    assert.match(await toneFor("spend", 42400, 35900), /is-flat/);
  });

  test.it("marks a falling CTR, but does not congratulate a rising one", async function () {
    assert.match(await toneFor("ctr", 3.4, 1.2), /is-bad/);
    assert.match(await toneFor("ctr", 1.2, 3.4), /is-flat/);
  });

  test.it("leaves clicks and impressions neutral in both directions", async function () {
    assert.match(await toneFor("clicks", 1284, 900), /is-flat/);
    assert.match(await toneFor("impressions", 900, 37540), /is-flat/);
  });

  test.it("says nothing at all when no platform can state a delta", async function () {
    // `daily_delta` is null for a first day, for a gap, and for a metric only
    // one side carries. A tier heading over nothing claims nothing changed.
    const page = await openDetail({
      platforms: [platform("google_ads", { spend: 42400 }, null)],
    });
    const tier = page.root.querySelector("[data-reports-changes]");
    assert.equal(tier.hidden, true, "tier 2 shows with no delta to show");
  });
});

// ---------------------------------------------------------------------
// (1) The conclusion, in both languages
// ---------------------------------------------------------------------

test.describe("the summary leads with its conclusion", function () {
  async function leadOf(narrative) {
    const page = await openDetail({ reports: { daily: { narrative: narrative } } });
    const lead = page.root.querySelector(".report-latest-lead");
    return lead ? lead.textContent : null;
  }

  test.it("bolds the first sentence of a Japanese narrative", async function () {
    assert.equal(
      await leadOf("CPAが目標を40%超過。配信量は前日と同水準です。"),
      "CPAが目標を40%超過。"
    );
  });

  test.it("bolds the first sentence of an English one", async function () {
    // The regression: the rule knew only `。`, so an English report was never
    // emphasised at all.
    assert.equal(
      await leadOf("CPA is 40% over target. Delivery held steady."),
      "CPA is 40% over target."
    );
  });

  test.it("does not split on a decimal point", async function () {
    // `". "` and not `"."` — a bare period is not a sentence end in a text
    // carrying figures.
    assert.equal(
      await leadOf("CTR moved to 3.42% today. That is within range."),
      "CTR moved to 3.42% today."
    );
  });

  test.it("takes whichever stop comes first", async function () {
    assert.equal(await leadOf("あ。Then b. c"), "あ。");
    assert.equal(await leadOf("Then b. あ。c"), "Then b.");
  });

  test.it("emphasises nothing when it cannot find a sentence end", async function () {
    assert.equal(await leadOf("one long clause with no stop"), null);
  });
});

// ---------------------------------------------------------------------
// Card anatomy — caption, then figure, on every family
// ---------------------------------------------------------------------

test.describe("every KPI cell reads label-then-figure", function () {
  // Twice now a cell has been built figure-first and shipped: the client
  // card's in phase 1, and the platform card's spend headline in phase 2 —
  // the latter sitting on the SAME card as a CPA cell built the right way
  // round, so one card read in two directions at once.
  //
  // Both were invisible to every existing test, because both produced a
  // correct DOM with correct class names in a plausible order. So this pins
  // the whole family at once rather than one cell at a time: for each
  // `<label, value>` pair, the label must come first among its parent's
  // children. A new family added later should be added here.
  const FAMILIES = [
    ["reports-kpi", "reports-kpi-label", "reports-kpi-value"],
    ["reports-client-kpi", "reports-client-kpi-label", "reports-client-kpi-value"],
    ["report-card-headline", "report-card-headline-label", "report-card-headline-value"],
    ["report-card-second", "report-card-second-label", "report-card-second-value"],
    ["reports-change", "reports-change-label", "reports-change-value"],
  ];

  /** Every `<label, value>` pair on a page, checked in order. */
  function auditAnatomy(page, seen) {
    for (const [cell, labelClass, valueClass] of FAMILIES) {
      for (const parent of page.root.querySelectorAll("." + cell)) {
        const classes = parent.children.map((el) => el.className);
        const label = classes.findIndex((c) => c.split(/\s+/).includes(labelClass));
        const value = classes.findIndex((c) => c.split(/\s+/).includes(valueClass));
        if (label === -1 || value === -1) continue;
        assert.ok(
          label < value,
          cell + " puts its figure above its label: " + classes.join(", ")
        );
        seen.add(cell);
      }
    }
  }

  test.it("puts the caption above the number in all of them", async function () {
    const seen = new Set();

    // The detail view carries four of the five families.
    auditAnatomy(
      await openDetail({
        platforms: [
          platform(
            "google_ads",
            { spend: 42400, cpa: 3855, conversions: 11 },
            { from: "2026-08-20", to: "2026-08-21", metrics: { cpa: 200 } }
          ),
        ],
        reports: { daily: { totals: { spend: 42400 }, narrative: "x。y" } },
      }),
      seen
    );

    // The portfolio strip is the INDEX's, so it needs a roster of two.
    auditAnatomy(await openIndex(), seen);

    // Without this the test would pass by checking nothing the day a family
    // stops rendering — which is exactly how the two bugs above survived.
    const missed = FAMILIES.map((f) => f[0]).filter((c) => !seen.has(c));
    assert.deepEqual(missed, [], "these families were never rendered, so never checked");
  });
});

// ---------------------------------------------------------------------
// The action log reads as a log
// ---------------------------------------------------------------------

test.describe("recent actions render as a timeline", function () {
  // The complaint was that the list read as centred text. Nothing centred it
  // — only three rules in app.css set `text-align: center` and none is on
  // this path. What it actually lacked was an AXIS: three stacked blocks per
  // entry, the sentence in the middle and the time underneath, with no left
  // edge for the eye to return to. So what is pinned here is the structure
  // that fixes it, not the absence of a rule nobody wrote.
  async function openWithActions(actions) {
    return openDetail({
      platforms: [platform("google_ads", { spend: 1000 })],
      recent_actions: actions,
    });
  }

  const ACTION = {
    timestamp: new Date().toISOString(),
    action: "budget_update",
    platform: "google_ads",
    campaign_id: "c-1",
    summary: "Raised the daily budget to 18,000.",
    observation_due: "2026-08-27",
  };

  test.it("puts the time and kind ABOVE the sentence", async function () {
    const page = await openWithActions([ACTION]);
    const row = page.root.querySelector(".report-action");
    assert.ok(row, "no action row rendered");
    const classes = row.children.map((el) => el.className);
    // meta line, then the sentence, then what is still owed.
    assert.deepEqual(classes, [
      "report-action-top",
      "report-action-summary",
      "report-action-meta",
    ]);
    const top = page.root.querySelector(".report-action-top");
    const inTop = top.children.map((el) => el.className);
    assert.equal(inTop[0], "report-action-time", "the time does not lead the row");
  });

  test.it("keeps every row left-aligned", async function () {
    // Belt and braces against the complaint literally coming back: no rule on
    // the row or its list may centre it.
    const css = require("node:fs").readFileSync(
      require("node:path").join(
        __dirname, "..", "..", "mureo", "_data", "web", "app.css"
      ),
      "utf-8"
    );
    for (const sel of [".report-action {", ".dashboard-reports-actions-list {"]) {
      const at = css.indexOf(sel);
      assert.notEqual(at, -1, sel + " is gone");
      const block = css.slice(at, css.indexOf("}", at));
      assert.ok(
        !/text-align:\s*center/.test(block),
        sel + " centres its text again"
      );
    }
  });

  test.it("draws the rail the rows hang off", async function () {
    const css = require("node:fs").readFileSync(
      require("node:path").join(
        __dirname, "..", "..", "mureo", "_data", "web", "app.css"
      ),
      "utf-8"
    );
    const list = css.slice(
      css.indexOf(".dashboard-reports-actions-list {"),
      css.indexOf("}", css.indexOf(".dashboard-reports-actions-list {"))
    );
    assert.match(list, /border-left/, "the timeline rail is gone");
    assert.ok(css.includes(".report-action::before"), "the row markers are gone");
  });

  test.it("spells a wire token as words", async function () {
    // `budget_update` is what the action log stores. An operator should not
    // have to read snake_case, and the humanizer is the flag chips' own so
    // the page spells a token one way.
    const page = await openWithActions([ACTION]);
    const name = page.root.querySelector(".report-action-name");
    assert.equal(name.textContent, "Budget update");
  });

  test.it("keeps the observation deadline rather than dropping it", async function () {
    const page = await openWithActions([ACTION]);
    const meta = page.root.querySelector(".report-action-meta");
    assert.ok(meta, "the owed-review line is gone");
    assert.match(meta.textContent, /2026-08-27/);
  });

  test.it("renders a row that carries only a summary", async function () {
    // Every field but `summary` is optional in the stored shape.
    const page = await openWithActions([{ summary: "Something happened." }]);
    const row = page.root.querySelector(".report-action");
    assert.ok(row, "a summary-only entry rendered nothing");
    assert.equal(page.root.querySelectorAll(".report-action-time").length, 0);
    assert.equal(page.root.querySelectorAll(".report-action-platform").length, 0);
    assert.match(
      page.root.querySelector(".report-action-summary").textContent,
      /Something happened/
    );
  });
});

// ---------------------------------------------------------------------
// The action row, by what it COMPUTES to
// ---------------------------------------------------------------------

test.describe("the action row wins its own layout", function () {
  // THE BUG THIS EXISTS FOR, and why the tests above did not catch it.
  //
  // `.report-action` declared `flex-direction: column`. `.dashboard-section
  // li` — the setup screens' generic row styling, which this list sits inside
  // — declared `align-items: center` and `justify-content: space-between`.
  // The generic rule is (0,1,1); the specific one was (0,1,0). The generic
  // rule WON, and `align-items: center` on a column centres every child
  // horizontally. That is the "text is centred" the owner reported twice.
  //
  // Every check written before this one missed it, for the same reason:
  //
  //   • the DOM was correct — right nodes, right classes, right order;
  //   • `text-align: center` appeared nowhere, so a grep for it found
  //     nothing and "proved" the opposite of what was on screen;
  //   • the declaration-absence test added in the previous round asserts that
  //     `.report-action { }` does not CONTAIN centring. It still passes with
  //     the bug present, because the centring was never in that block. That
  //     test is kept — it pins the literal complaint — but it cannot catch
  //     this shape and this comment is here so nobody assumes it does.
  //
  // What catches it is asking the cascade, which is what a browser does.
  const LAYOUT = {
    "flex-direction": "column",
    "align-items": "flex-start",
    "justify-content": "flex-start",
  };

  async function actionRow() {
    const page = await openDetail({
      platforms: [platform("google_ads", { spend: 1000 })],
      recent_actions: [
        {
          timestamp: new Date().toISOString(),
          action: "budget_update",
          platform: "google_ads",
          summary: "Raised the daily budget.",
          observation_due: "2026-08-27",
        },
      ],
    });
    const row = page.root.querySelector(".report-action");
    assert.ok(row, "no action row rendered");
    return row;
  }

  test.it("stacks its children and starts them at the left edge", async function () {
    const row = await actionRow();
    for (const [property, expected] of Object.entries(LAYOUT)) {
      const won = cascade(row, property);
      assert.ok(won, ".report-action computes no " + property + " at all");
      assert.equal(
        won.value,
        expected,
        property + " computes to '" + won.value + "' via `" + won.selector + "`"
      );
    }
  });

  test.it("keeps the padding that makes room for the rail", async function () {
    // The same collision took the row's padding: `.dashboard-section li` sets
    // `padding: 11px 0`, so the 20px left inset the timeline dots sit in was
    // being discarded and the markers landed on top of the text.
    const row = await actionRow();
    const padding = cascade(row, "padding");
    assert.ok(padding, "the row computes no padding");
    assert.match(
      padding.value,
      /20px$/,
      "padding computes to '" + padding.value + "' via `" + padding.selector + "`"
    );
  });

  test.it("keeps the rail on the list itself", async function () {
    const row = await actionRow();
    const list = row.parentNode;
    const border = cascade(list, "border-left");
    assert.ok(
      border && !/^0/.test(border.value),
      "the rail computes to '" + (border && border.value) + "'"
    );
    const padding = cascade(list, "padding");
    assert.match(
      padding.value,
      /2px$/,
      "the list padding computes to '" +
        padding.value +
        "' via `" +
        padding.selector +
        "`"
    );
  });

  test.it("the alert list rows win theirs too", async function () {
    // Same trap, one element away: .reports-triage-row is also an <li> in a
    // .dashboard-section, was also flex-direction:column, and was also being
    // centred by the generic rule. Found by running the resolver above over
    // every list row on these screens rather than by waiting for a third
    // capture review.
    const page = await openIndexWithAlert();
    const row = page.root.querySelector(".reports-triage-row");
    assert.ok(row, "no alert row rendered");
    for (const [property, expected] of Object.entries(LAYOUT)) {
      const won = cascade(row, property);
      assert.equal(
        won && won.value,
        expected,
        property +
          " computes to '" +
          (won && won.value) +
          "' via `" +
          (won && won.selector) +
          "`"
      );
    }
  });

  test.it("resolves specificity the way a browser does", async function () {
    // A guard on the guard: if `specificity` ever scored a two-part selector
    // below a one-class one, every assertion above would silently invert.
    const { specificity } = require("./dom_harness.js");
    assert.ok(
      specificity(".dashboard-section li") > specificity(".report-action"),
      "a descendant selector must outrank a bare class"
    );
    assert.ok(
      specificity(".dashboard-reports-actions-list .report-action") >
        specificity(".dashboard-section li"),
      "two classes must outrank one class plus a type"
    );
  });
});
