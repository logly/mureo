// Every stale surface on screen speaks about the same fact (#798).
//
// Run with:  node --test tests/js/*.test.js
//
// The capture that prompted this: one client card said "Stale 2026-09-20,
// updated 14h ago" on its freshness line, "Figures 14h ago old" on its chip
// and "Last collected 14h ago: …" under its cells — and the detail view's
// note said the figures were COLLECTED before the window, when they had been
// collected fourteen hours earlier and merely ran to a day before it. Each
// string was individually true of something; together they contradicted one
// another. The server now says which fact the verdict was taken on
// (`judged_on`), and these drive the real dashboard against the real
// app.html to ask what each surface puts on screen.
//
// MUREO.t in the harness returns the key it was handed with its params
// appended, so the assertions are on which string was chosen and what went
// into it — never on English wording.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const TODAY = new Date().toISOString().slice(0, 10);
const WRITTEN = new Date(Date.now() - 14 * 60 * 60 * 1000).toISOString();

function summaryWith(platforms) {
  return {
    client: "alpha",
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: new Date().toISOString(),
    platforms: platforms,
    platform_conflicts: [],
    recent_actions: [],
    reports: {},
    observations_due: { count: 0, oldest_due: null },
    server_today: TODAY,
  };
}

/** One platform row whose freshness block is exactly `freshness`. */
function platform(key, totals, freshness) {
  return {
    key: key,
    display_name: key === "google_ads" ? "Google Ads" : "Meta Ads",
    totals: totals,
    metrics_period: "YESTERDAY",
    campaign_count: 3,
    freshness: freshness,
    not_collected: null,
    daily: [],
    daily_delta: null,
  };
}

const COVERED_STALE = {
  fetched_at: WRITTEN,
  period_end: "2026-09-20",
  judged_on: "period_end",
  stale: true,
  stale_after_days: 2,
};

const WRITTEN_STALE = {
  fetched_at: new Date(Date.now() - 11 * 86400000).toISOString(),
  period_end: null,
  judged_on: "fetched_at",
  stale: true,
  stale_after_days: 2,
};

async function open(roster, platforms) {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: roster, can_archive: false },
    "/api/reports/summary": () => summaryWith(platforms),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

/** A single-client roster, which opens straight on the detail view. */
function openDetail(platforms) {
  return open([{ slug: "alpha", name: "Alpha", active: true }], platforms);
}

/** A two-client roster, which routes to the index grid of cards. */
function openIndex(platforms) {
  return open(
    [
      { slug: "alpha", name: "Alpha", active: true },
      { slug: "beta", name: "Beta", active: true },
    ],
    platforms
  );
}

function text(page, selector) {
  const el = page.root.querySelector(selector);
  assert.ok(el, selector + " was not rendered");
  return el.textContent;
}

test.describe("the detail view's per-platform card", function () {
  test.it("says the figures RUN TO a day before the window, not that they were collected before it", async function () {
    const page = await openDetail([
      platform("google_ads", { spend: 84000, period_end: "2026-09-20" }, COVERED_STALE),
    ]);
    assert.equal(
      text(page, ".report-card-stale"),
      "dashboard.reports_stale_kpis_withheld_covered"
    );
    const figures = text(page, ".report-card-stale-figures");
    assert.ok(
      figures.startsWith("dashboard.reports_stale_figures_to|"),
      figures
    );
    assert.ok(figures.indexOf("date=2026-09-20") !== -1, figures);
  });

  test.it("reads exactly as before when the verdict was taken on the write time", async function () {
    const page = await openDetail([
      platform("google_ads", { spend: 84000 }, WRITTEN_STALE),
    ]);
    assert.equal(text(page, ".report-card-stale"), "dashboard.reports_stale_kpis_withheld");
    assert.ok(
      text(page, ".report-card-stale-figures").startsWith(
        "dashboard.reports_stale_last_collected|"
      )
    );
  });

  test.it("puts the full freshness line in the footer's title, so a clipped one can be read", async function () {
    const page = await openDetail([
      platform("google_ads", { spend: 84000, period_end: "2026-09-20" }, COVERED_STALE),
    ]);
    const fresh = page.root.querySelector(".report-card-fresh");
    assert.ok(fresh);
    assert.ok(fresh.textContent);
    assert.equal(fresh.getAttribute("title"), fresh.textContent);
  });

  test.it("does not list the covered date under All metrics", async function () {
    // `period_end` is a date beside `period` and `fetched_at`, not a figure;
    // listing it made every rollup that states one grow an "All metrics (1)"
    // disclosure reading `period_end 2026-09-22`.
    const page = await openDetail([
      platform(
        "google_ads",
        {
          spend: 84000,
          conversions: 48,
          period: "YESTERDAY",
          fetched_at: WRITTEN,
          period_end: "2026-09-22",
        },
        {
          fetched_at: WRITTEN,
          period_end: "2026-09-22",
          judged_on: "period_end",
          stale: false,
          stale_after_days: 2,
        }
      ),
    ]);
    assert.ok(page.root.querySelector(".report-card"), "no platform card");
    assert.equal(page.root.querySelector(".report-card-more"), null);
  });
});

test.describe("the index card", function () {
  test.it("names the covered day on the chip and under the cells", async function () {
    const page = await openIndex([
      platform("google_ads", { spend: 84000, conversions: 48 }, COVERED_STALE),
    ]);
    const badge = text(page, ".reports-client-card-badge");
    assert.equal(badge, "dashboard.reports_triage_tag_stale_covered|date=2026-09-20");
    const figures = text(page, ".reports-client-card-stale-figures");
    assert.ok(figures.startsWith("dashboard.reports_stale_figures_to|"), figures);
    assert.ok(figures.indexOf("date=2026-09-20") !== -1, figures);
  });

  test.it("keeps the write-time wording for a verdict taken on the write time", async function () {
    const page = await openIndex([
      platform("google_ads", { spend: 84000, conversions: 48 }, WRITTEN_STALE),
    ]);
    assert.ok(
      text(page, ".reports-client-card-badge").startsWith(
        "dashboard.reports_triage_tag_stale_aged|"
      )
    );
    assert.ok(
      text(page, ".reports-client-card-stale-figures").startsWith(
        "dashboard.reports_stale_last_collected|"
      )
    );
  });

  test.it("puts the full freshness line in its title", async function () {
    const page = await openIndex([
      platform("google_ads", { spend: 84000, conversions: 48 }, COVERED_STALE),
    ]);
    const fresh = page.root.querySelector(".reports-client-card-fresh");
    assert.ok(fresh);
    assert.ok(fresh.textContent);
    assert.equal(fresh.getAttribute("title"), fresh.textContent);
  });
});
