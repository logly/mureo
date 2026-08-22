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
    daily: [],
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
