// The ops history aggregate on the client list (#849): one line per client
// card, and a triage finding for a client whose changes regressed.
//
// Run with:  node --test tests/js/*.test.js
//
// The counts are the server's (`summary.ops_history`); the browser only
// says them. The line is absent while ops history is off and when the
// window holds no change, and the finding is raised only for a regression.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const TODAY = new Date().toISOString().slice(0, 10);

function opsHistory(enabled, counts) {
  return Object.assign(
    {
      enabled: enabled,
      window_days: 30,
      changes: 0,
      improved: 0,
      regressed: 0,
      regressed_open: 0,
      held: 0,
      inconclusive: 0,
      observing: 0,
    },
    counts
  );
}

function summaryFor(slug, ops) {
  return {
    client: slug,
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: new Date().toISOString(),
    platforms: [
      {
        key: "google_ads",
        display_name: "Google Ads",
        totals: { spend: 1000, conversions: 10 },
        metrics_period: "YESTERDAY",
        campaign_count: 1,
        freshness: { fetched_at: new Date().toISOString(), stale: false },
        not_collected: null,
        daily: [],
        daily_delta: null,
      },
    ],
    platform_conflicts: [],
    recent_actions: [],
    reports: {},
    display: null,
    observations_due: { count: 0, oldest_due: null },
    server_today: TODAY,
    ops_history: ops,
  };
}

const ROSTER = [
  { slug: "alpha", name: "Alpha", active: true },
  { slug: "bravo", name: "Bravo", active: true },
  { slug: "carol", name: "Carol", active: true },
  { slug: "delta", name: "Delta", active: true },
];

const SUMMARIES = {
  alpha: summaryFor(
    "alpha",
    opsHistory(true, {
      changes: 6,
      improved: 2,
      regressed: 1,
      regressed_open: 1,
      held: 1,
      inconclusive: 1,
      observing: 1,
    })
  ),
  bravo: summaryFor("bravo", opsHistory(false)),
  carol: summaryFor("carol", opsHistory(true)),
  delta: summaryFor("delta", undefined),
};

async function openIndex() {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: false },
    "/api/reports/summary": (url) => {
      const m = /client=([^&]+)/.exec(url);
      return SUMMARIES[m ? decodeURIComponent(m[1]) : "alpha"];
    },
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

function card(page, slug) {
  return page.root
    .querySelectorAll(".reports-client-card")
    .find((node) => node.getAttribute("data-client") === slug);
}

test.describe("the aggregate line on a client card", function () {
  test.it("states the server's counts when there were changes", async function () {
    const page = await openIndex();
    const line = card(page, "alpha").querySelector("[data-ops-history-aggregate]");
    assert.equal(
      line.textContent,
      "ops_history_section.aggregate|days=30,n=6,improved=2,regressed=1," +
        "held=1,inconclusive=1,observing=1"
    );
  });

  test.it("is absent while ops history is off", async function () {
    const page = await openIndex();
    assert.equal(card(page, "bravo").querySelector("[data-ops-history-aggregate]"), null);
  });

  test.it("is absent when the window holds no change", async function () {
    const page = await openIndex();
    assert.equal(card(page, "carol").querySelector("[data-ops-history-aggregate]"), null);
  });

  test.it("is absent when the server sent no aggregate", async function () {
    const page = await openIndex();
    assert.equal(card(page, "delta").querySelector("[data-ops-history-aggregate]"), null);
  });
});

test.describe("a regressed change in the triage layer", function () {
  function triage(page) {
    return page.sandbox.MUREO_REPORTS_TRIAGE;
  }

  test.it("raises an attention finding naming the count", async function () {
    const page = await openIndex();
    const layer = triage(page);
    const built = layer.buildReportsTriage(
      ROSTER,
      ROSTER.map((c) => SUMMARIES[c.slug])
    );
    const found = built.items.filter((i) => i.kind === "ops_regressed");
    assert.equal(found.length, 1);
    assert.equal(found[0].slug, "alpha");
    assert.equal(found[0].count, 1);
    assert.equal(layer.triageItemSeverity(found[0]), "attention");
    assert.equal(
      layer.triageItemText(found[0]),
      "ops_history_section.regressed_one|n=1"
    );
    assert.equal(layer.triageItemTag(found[0]), "ops_history_section.triage_tag");
    assert.equal(layer.triageItemNextStep(found[0]), "ops_history_section.triage_next");
    assert.equal(layer.triageClientHealth(built, 0), "attention");
  });

  test.it("raises nothing for a client with no regression or with it off", async function () {
    const page = await openIndex();
    const layer = triage(page);
    const off = summaryFor("x", opsHistory(false, { changes: 3, regressed: 2 }));
    const clean = summaryFor("y", opsHistory(true, { changes: 3, improved: 3 }));
    const built = layer.buildReportsTriage(
      [{ slug: "x" }, { slug: "y" }],
      [off, clean]
    );
    assert.equal(built.items.length, 0);
  });

  test.it("counts only regressions that were not rolled back", async function () {
    const page = await openIndex();
    const layer = triage(page);
    const reverted = summaryFor(
      "x",
      opsHistory(true, { changes: 1, regressed: 1, regressed_open: 0 })
    );
    const built = layer.buildReportsTriage([{ slug: "x" }], [reverted]);
    assert.equal(built.items.length, 0);
  });

  test.it("says more than one regression in the plural", async function () {
    const page = await openIndex();
    const layer = triage(page);
    const two = summaryFor(
      "x",
      opsHistory(true, { changes: 3, regressed: 2, regressed_open: 2 })
    );
    const built = layer.buildReportsTriage([{ slug: "x" }], [two]);
    assert.equal(
      layer.triageItemText(built.items[0]),
      "ops_history_section.regressed_other|n=2"
    );
  });

  test.it("ranks by the table, like every other finding", async function () {
    const page = await openIndex();
    const layer = triage(page);
    const kinds = layer.REPORTS_TRIAGE_KINDS;
    assert.ok(kinds.indexOf("ops_regressed") > kinds.indexOf("report_flag"));
    assert.ok(kinds.indexOf("ops_regressed") < kinds.indexOf("not_collected"));
  });

  test.it("marks the card the finding belongs to", async function () {
    const page = await openIndex();
    const item = page.root
      .querySelectorAll(".reports-client-card-item")
      .find((node) => node.getAttribute("data-client") === "alpha");
    assert.equal(item.getAttribute("data-health"), "attention");
  });
});
