// The ops history section on a client's detail view (#849).
//
// Run with:  node --test tests/js/*.test.js
//
// Drives the real dashboard against the real app.html: the section is
// drawn under the recent-actions block from `/api/reports/ops-history`, and
// is not in the DOM at all while the workspace's ops history is off.
//
// MUREO.t returns the key it was handed (plus any params), so assertions
// are about WHICH string was chosen, never about English wording.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle, isVisible } = require("./dom_harness.js");

const TODAY = "2026-10-14";
const FEED = "/api/reports/ops-history";

function summary() {
  return {
    client: "alpha",
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: new Date().toISOString(),
    platforms: [
      {
        key: "google_ads",
        display_name: "Google Ads",
        totals: { spend: 1000 },
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
  };
}

function evaluation(overall, rows) {
  return {
    index: 9,
    timestamp: "2026-10-12T10:00:00+09:00",
    overall: overall,
    summary: null,
    reason: null,
    table: { overall: overall, basis: "expected", metrics: rows },
  };
}

function action(extra) {
  return Object.assign(
    {
      index: 0,
      timestamp: "2026-10-01T10:00:00+09:00",
      action: "google_ads_budget_update",
      platform: "google_ads",
      campaign_id: "c1",
      entity_type: "budget",
      entity_id: "b1",
      reason: "Budget capped by noon.",
      before: { amount: 10000 },
      after: { amount: 12000 },
      observation_due: "2026-10-08",
      state: "evaluated",
      skipped_reason: null,
      evaluation: null,
      rolled_back_by: null,
    },
    extra
  );
}

function item(id, day, opts) {
  const o = opts || {};
  const decision =
    o.noDecision === true
      ? null
      : {
          decision_id: id,
          status: "adopted",
          recorded_at: day + "T10:00:00+09:00",
          title: "Decision " + id,
          rationale:
            o.rationale !== undefined
              ? o.rationale
              : "CPA has been above target for two weeks at steady volume.",
          expected: o.expected || [{ metric: "cpa", direction: "down" }],
          platform: o.platform || "google_ads",
        };
  return {
    decision: decision,
    actions: [
      action({
        timestamp: day + "T10:00:00+09:00",
        platform: o.platform || "google_ads",
        state: o.state,
        evaluation: o.evaluation || null,
        skipped_reason: o.skipped || null,
      }),
    ],
    state: o.state,
    verdict: o.verdict || null,
    rolled_back: !!o.rolledBack,
  };
}

const CPA_DOWN = [
  {
    metric: "cpa",
    before: 1840,
    after: 1520,
    delta_pct: -17.4,
    verdict: "improved",
    note: "expected down",
    role: "primary",
  },
];

const CPA_UP = [
  {
    metric: "cpa",
    before: 1500,
    after: 1900,
    delta_pct: 26.7,
    verdict: "regressed",
    note: "expected down; moved up",
    role: "primary",
  },
  {
    metric: "clicks",
    before: 900,
    after: 950,
    delta_pct: 5.6,
    verdict: "inconclusive",
    note: "within band",
    role: "reference",
  },
];

/** Server order: newest first, whatever the outcome. */
function populated() {
  return [
    item("improved", "2026-10-12", {
      state: "evaluated",
      verdict: "improved",
      evaluation: evaluation("improved", CPA_DOWN),
    }),
    item("observing", "2026-10-11", { state: "observing" }),
    item("inconclusive", "2026-10-10", {
      state: "evaluated",
      verdict: "inconclusive",
      evaluation: evaluation("inconclusive", []),
      platform: "meta_ads",
    }),
    item("regressed", "2026-10-05", {
      state: "evaluated",
      verdict: "regressed",
      evaluation: evaluation("regressed", CPA_UP),
      rationale: "Too high.",
      rolledBack: true,
    }),
  ];
}

function feed(enabled, items) {
  return {
    client: "alpha",
    since: "2026-09-14",
    until: TODAY,
    server_today: TODAY,
    enabled: enabled,
    items: items,
  };
}

async function openDetail(feedBody) {
  const page = loadDashboardPage({
    "/api/reports/clients": {
      clients: [{ slug: "alpha", name: "Alpha", active: true }],
      can_archive: false,
    },
    "/api/reports/summary": summary,
    [FEED]: typeof feedBody === "function" ? feedBody : () => feedBody,
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

function section(page) {
  return page.root.querySelector("[data-ops-history-section]");
}

function rowIds(page) {
  return section(page)
    .querySelectorAll("[data-ops-history-row]")
    .map((row) => row.getAttribute("data-decision"));
}

function change(select, value) {
  select.value = value;
  select.dispatchEvent({ type: "change" });
}

test.describe("the ops history section", function () {
  test.it("is not in the DOM while ops history is off", async function () {
    const page = await openDetail(feed(false, populated()));
    assert.ok(page.requests.some((url) => url.startsWith(FEED)));
    assert.equal(section(page), null);
  });

  test.it("sits directly below the recent-actions block", async function () {
    const page = await openDetail(feed(true, populated()));
    const actions = page.root.querySelector("[data-reports-actions]");
    assert.equal(actions.nextSibling, section(page));
    assert.ok(isVisible(section(page)));
  });

  test.it("asks for the client it is drawn for", async function () {
    const page = await openDetail(feed(true, []));
    // One fetch per summary render (the dashboard renders the detail on
    // load and again on the nav click); every one names the client and,
    // at the default period, no dates.
    const asked = page.requests.filter((url) => url.startsWith(FEED));
    assert.ok(asked.length >= 1);
    asked.forEach((url) => assert.equal(url, FEED + "?client=alpha"));
  });

  test.it("carries the permanent note", async function () {
    const page = await openDetail(feed(true, populated()));
    const note = section(page).querySelector("[data-ops-history-note]");
    assert.equal(note.textContent, "ops_history_section.note");
  });

  test.it("says so in one sentence when the window is empty", async function () {
    const page = await openDetail(feed(true, []));
    const empty = section(page).querySelector("[data-ops-history-empty]");
    assert.equal(empty.textContent, "ops_history_section.empty");
    assert.equal(section(page).querySelectorAll("[data-ops-history-row]").length, 0);
  });

  test.it("orders regressed, observing, the rest, then improved", async function () {
    const page = await openDetail(feed(true, populated()));
    assert.deepEqual(rowIds(page), ["regressed", "observing", "inconclusive", "improved"]);
  });

  test.it("keeps newest first inside one group", async function () {
    const items = [
      item("older", "2026-10-01", { state: "observing" }),
      item("newer", "2026-10-09", { state: "observing" }),
    ];
    const page = await openDetail(feed(true, items));
    assert.deepEqual(rowIds(page), ["newer", "older"]);
  });

  test.it("states the primary metric before and after", async function () {
    const page = await openDetail(feed(true, populated()));
    const cells = section(page).querySelectorAll("[data-ops-history-metric]");
    const byRow = {};
    rowIds(page).forEach((id, i) => (byRow[id] = cells[i].textContent));
    assert.equal(byRow.improved, "CPA 1,840 → 1,520 ▼17%");
    assert.equal(byRow.regressed, "CPA 1,500 → 1,900 ▲27%");
    assert.equal(byRow.observing, "—");
  });

  test.it("names a change with no decision as such", async function () {
    const items = [item("x", "2026-10-02", { state: "executed", noDecision: true })];
    const page = await openDetail(feed(true, items));
    const title = section(page).querySelector("[data-ops-history-title]");
    assert.equal(title.textContent, "ops_history_section.no_decision");
    assert.ok(title.classList.contains("is-muted"));
  });

  test.it("marks a weak rationale and leaves a real one alone", async function () {
    const items = populated().concat([
      item("empty", "2026-10-03", { state: "executed", rationale: "" }),
    ]);
    const page = await openDetail(feed(true, items));
    const rows = section(page).querySelectorAll("[data-ops-history-row]");
    const weak = rows
      .filter((row) => row.hasAttribute("data-ops-history-weak"))
      .map((row) => row.getAttribute("data-decision"));
    assert.deepEqual(weak.sort(), ["empty", "regressed"]);
    const chip = rows[0].querySelector("[data-ops-history-weak-chip]");
    assert.equal(chip.textContent, "ops_history_section.weak_rationale");
  });

  test.it("expands a row into its evaluation table", async function () {
    const page = await openDetail(feed(true, populated()));
    const row = section(page).querySelectorAll("[data-ops-history-row]")[0];
    const detail = row.nextSibling;
    assert.ok(detail.hasAttribute("data-ops-history-detail"));
    assert.equal(isVisible(detail), false);
    row.querySelector("[data-ops-history-expand]").click();
    assert.equal(isVisible(detail), true);
    const table = detail.querySelector("[data-ops-history-evaluation]");
    const cells = table
      .querySelectorAll("tr")
      .slice(1)
      .map((tr) => tr.querySelectorAll("td").map((td) => td.textContent));
    assert.deepEqual(cells[0], [
      "CPA",
      "1,500",
      "1,900",
      "▲27%",
      "ops_history_section.verdict_regressed",
      "expected down; moved up",
    ]);
    assert.equal(cells.length, 2);
    assert.ok(detail.querySelector("[data-ops-history-rolled-back]"));
    const ops = detail.querySelector("[data-ops-history-operations]");
    assert.match(ops.textContent, /amount: 10,000 → amount: 12,000/);
    assert.match(ops.textContent, /Budget capped by noon\./);
    row.querySelector("[data-ops-history-expand]").click();
    assert.equal(isVisible(detail), false);
  });

  test.it("gives the skip reason for a change that was not evaluated", async function () {
    const items = [item("s", "2026-10-02", { state: "skipped", skipped: "no_baseline" })];
    const page = await openDetail(feed(true, items));
    const row = section(page).querySelector("[data-ops-history-row]");
    row.click();
    const skip = row.nextSibling.querySelector("[data-ops-history-skipped]");
    assert.equal(skip.textContent, "ops_history_section.skipped|reason=No baseline");
  });

  test.it("filters by verdict without asking the server again", async function () {
    const page = await openDetail(feed(true, populated()));
    const before = page.requests.length;
    change(section(page).querySelector("[data-ops-history-verdict]"), "improved");
    assert.deepEqual(rowIds(page), ["improved"]);
    assert.equal(page.requests.length, before);
  });

  test.it("filters by platform from the platforms the items name", async function () {
    const page = await openDetail(feed(true, populated()));
    const select = section(page).querySelector("[data-ops-history-platform]");
    const values = select.querySelectorAll("option").map((o) => o.value);
    assert.deepEqual(values, ["", "google_ads", "meta_ads"]);
    change(select, "meta_ads");
    assert.deepEqual(rowIds(page), ["inconclusive"]);
  });

  test.it("filters by state", async function () {
    const page = await openDetail(feed(true, populated()));
    change(section(page).querySelector("[data-ops-history-state]"), "observing");
    assert.deepEqual(rowIds(page), ["observing"]);
  });

  test.it("re-fetches when the period changes", async function () {
    const page = await openDetail(feed(true, populated()));
    const period = section(page).querySelector("[data-ops-history-period]");
    assert.equal(period.value, "30");
    change(period, "7");
    await settle();
    const asked = page.requests.filter((url) => url.startsWith(FEED));
    // Seven calendar days ending today, today included.
    assert.equal(asked[asked.length - 1], FEED + "?client=alpha&since=2026-10-08&until=2026-10-14");
    assert.equal(section(page).querySelector("[data-ops-history-period]").value, "7");
  });

  test.it("draws no section when the feed cannot be read", async function () {
    const page = await openDetail(() => {
      throw new Error("unreadable");
    });
    assert.ok(page.requests.some((url) => url.startsWith(FEED)));
    assert.equal(section(page), null);
  });

  test.it("puts the weak-rationale boundary at twenty characters", async function () {
    const nineteen = "a".repeat(19);
    const items = [
      item("short", "2026-10-02", { state: "executed", rationale: "  **" + nineteen + "**  " }),
      item("exact", "2026-10-01", { state: "executed", rationale: " **" + nineteen + "b** " }),
    ];
    const page = await openDetail(feed(true, items));
    const weak = section(page)
      .querySelectorAll("[data-ops-history-row]")
      .filter((row) => row.hasAttribute("data-ops-history-weak"))
      .map((row) => row.getAttribute("data-decision"));
    assert.deepEqual(weak, ["short"]);
  });

  test.it("puts a title carrying markup on the page as text", async function () {
    const items = [item("x", "2026-10-02", { state: "executed" })];
    items[0].decision.title = "</script><b>bold</b>";
    const page = await openDetail(feed(true, items));
    const title = section(page).querySelector("[data-ops-history-title]");
    assert.equal(title.textContent, "</script><b>bold</b>");
    assert.equal(title.querySelectorAll("b").length, 0);
  });

  test.it("falls back to the primary row, then to the first row", async function () {
    const roles = [
      { metric: "clicks", before: 900, after: 950, delta_pct: 5.6, verdict: "inconclusive", role: "reference" },
      { metric: "ctr", before: 2, after: 2.5, delta_pct: 25, verdict: "improved", role: "primary" },
    ];
    const firstOnly = [
      { metric: "clicks", before: 900, after: 950, delta_pct: 5.6, verdict: "inconclusive", role: "reference" },
      { metric: "cvr", before: 1.5, after: 1.2, delta_pct: -20, verdict: "regressed", role: "reference" },
    ];
    const items = [
      item("primary", "2026-10-03", {
        state: "evaluated",
        verdict: "improved",
        expected: [{ metric: "cpa", direction: "down" }],
        evaluation: evaluation("improved", roles),
      }),
      item("first", "2026-10-02", {
        state: "evaluated",
        verdict: "improved",
        expected: [],
        evaluation: evaluation("improved", firstOnly),
      }),
    ];
    const page = await openDetail(feed(true, items));
    const cells = section(page).querySelectorAll("[data-ops-history-metric]");
    const byRow = {};
    rowIds(page).forEach((id, i) => (byRow[id] = cells[i].textContent));
    assert.equal(byRow.primary, "CTR 2 → 2.5 ▲25%");
    assert.equal(byRow.first, "Clicks 900 → 950 ▲6%");
  });

  test.it("states a nested value as bounded JSON, never as [object Object]", async function () {
    const items = [item("n", "2026-10-02", { state: "executed" })];
    items[0].actions[0].before = { nested: { a: 1 } };
    items[0].actions[0].after = { nested: { a: 2 }, long: "x".repeat(200) };
    const page = await openDetail(feed(true, items));
    const row = section(page).querySelector("[data-ops-history-row]");
    row.click();
    const ops = row.nextSibling.querySelector("[data-ops-history-operations]").textContent;
    assert.doesNotMatch(ops, /object Object/);
    assert.match(ops, /nested: \{"a":1\} → nested: \{"a":2\}/);
    assert.match(ops, /long: x{79}…/);
    assert.doesNotMatch(ops, /x{81}/);
  });

  test.it("puts writer text on the page as text", async function () {
    const items = [
      item("x", "2026-10-02", {
        state: "executed",
        rationale: "<img src=x onerror=alert(1)> **bold** reason that is long enough",
      }),
    ];
    const page = await openDetail(feed(true, items));
    const row = section(page).querySelector("[data-ops-history-row]");
    row.click();
    const rationale = row.nextSibling.querySelector("[data-ops-history-rationale]");
    assert.equal(
      rationale.textContent,
      "<img src=x onerror=alert(1)> bold reason that is long enough"
    );
    assert.equal(rationale.querySelectorAll("img").length, 0);
  });
});
