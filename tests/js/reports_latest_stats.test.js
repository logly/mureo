// What a report stated outside the six canonical metrics, on screen (#670).
//
// Run with:  node --test tests/js/*.test.js
//
// #662 made the write side accept those keys on purpose — a goal review
// carries a CVR, a per-goal target, a per-platform split — and then nothing
// rendered them. Written successfully, invisible for good.
//
// This drives the real dashboard.js against the real app.html, because the
// two things that matter here are DOM facts a substring pin cannot read:
//
//   • the value reaches the screen exactly as it was written. 30000 is not
//     "30,000" and "0.21%" is not re-derived from anything;
//   • the headline row above is untouched — its cells, its order, its
//     formatting are what #662/#663 pinned and this block sits BELOW them.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const ROSTER = [{ slug: "alpha", name: "Alpha", active: true }];

function summaryWith(report) {
  return {
    client: "alpha",
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: new Date().toISOString(),
    platforms: [],
    platform_conflicts: [],
    recent_actions: [],
    reports: { daily: report },
    observations_due: { count: 0, oldest_due: null },
    server_today: new Date().toISOString().slice(0, 10),
  };
}

async function openDetail(report) {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: false },
    "/api/reports/summary": () => summaryWith(report),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

const body = (page) => page.root.querySelector("[data-reports-latest-body]");

const statTexts = (page) =>
  body(page)
    .querySelectorAll(".report-stat")
    .map((el) => el.textContent);

test.describe("the stats a report stated outside the headline vocabulary", function () {
  test.it("puts them on screen, verbatim", async function () {
    const page = await openDetail({
      period: "2026-08-01..2026-08-18",
      totals: { spend: 773957, conversions: 50, cvr: "0.21%", goal_target_cpa: 30000 },
      narrative: "CPA is below target.",
    });
    const texts = statTexts(page);
    assert.equal(texts.length, 2);
    // The humanized key and the author's own value — no separator inserted
    // into 30000, no percentage re-derived from "0.21%".
    assert.ok(texts[0].includes("0.21%"), texts[0]);
    assert.ok(texts[1].includes("30000"), texts[1]);
    assert.ok(!texts[1].includes("30,000"), texts[1]);
  });

  test.it("sits below the headline figures, under the conclusion", async function () {
    // Same pin, restated for the three-tier detail view (#691): the tier now
    // leads with the narrative, because the conclusion is what an operator
    // opened the page for, and the flag row moved to tier (2) — it is a list
    // of what is WRONG, which is that tier's job.
    //
    // What this asserts has not changed: the stated-values block comes AFTER
    // the headline figures, so it can never be read as them.
    const page = await openDetail({
      totals: { spend: 773957, cvr: "0.21%" },
      flags: ["cpa_under_target"],
      narrative: "prose",
    });
    const classes = body(page).children.map((el) => el.className);
    assert.deepEqual(classes, [
      "report-latest-narrative",
      "report-latest-kpis",
      "report-latest-stats",
    ]);
    // The flags are still rendered — in tier (2), not dropped.
    const flags = page.root.querySelectorAll(".report-flags");
    assert.equal(flags.length, 1, "the flag row left the page entirely");
  });

  test.it("leaves the headline row exactly as it was", async function () {
    // The figure row is #662's, pinned by #663/#669. This block adds to the
    // report; it does not reinterpret what the report already stated.
    const page = await openDetail({
      totals: { spend: 773957, cvr: "0.21%" },
    });
    const cells = body(page)
      .querySelector(".report-latest-kpis")
      .querySelectorAll(".reports-client-kpi-value")
      .map((el) => el.textContent);
    assert.deepEqual(cells, ["773,957"]);
  });

  test.it("says a nested entry exists rather than dropping it", async function () {
    const page = await openDetail({
      totals: { spend: 1, breakdown: { daily: { mon: 1 } } },
    });
    const more = body(page).querySelectorAll(".report-stat-more");
    assert.equal(more.length, 1);
    assert.equal(more[0].textContent, "dashboard.reports_stats_more|n=1");
  });

  test.it("shows a nested per-platform figure the guard never saw", async function () {
    // `{"google_ads": {"spend": "¥773,957"}}` — not refused on write (the
    // guard reads the flat headline dict), not a headline figure, and until
    // now not rendered anywhere either.
    const page = await openDetail({
      kpis: { google_ads: { spend: "¥773,957" }, totals: { spend: 773957 } },
    });
    const texts = statTexts(page);
    assert.equal(texts.length, 1);
    assert.ok(texts[0].includes("¥773,957"), texts[0]);
  });

  test.it("renders no block at all for a report that stated nothing extra", async function () {
    const page = await openDetail({
      totals: { spend: 773957, conversions: 50 },
      narrative: "one paragraph, as reports on disk already are",
    });
    assert.equal(body(page).querySelectorAll(".report-latest-stats").length, 0);
  });
});
