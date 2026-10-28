// The "possible duplicate" hint on the ops history section (#851).
//
// Run with:  node --test tests/js/*.test.js
//
// A decision recorded on its own and a change made with only a `reason`
// leave two decisions for one change. The server names the pair in
// `decision.possible_duplicate_of`; the row carries a chip and the expanded
// row says what happened and how to avoid it. Nothing is joined or linked.
//
// MUREO.t returns the key it was handed (plus any params), so assertions
// are about WHICH string was chosen, never about English wording.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const FEED = "/api/reports/ops-history";

function summary() {
  return {
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
  };
}

function item(id, duplicateOf) {
  return {
    decision: {
      decision_id: id,
      status: "adopted",
      recorded_at: "2026-10-10T10:00:00+09:00",
      title: "Decision " + id,
      rationale: "CPA has been above target for two weeks at steady volume.",
      expected: [],
      platform: "google_ads",
      possible_duplicate_of: duplicateOf,
    },
    actions: [],
    state: "adopted",
    verdict: null,
    rolled_back: false,
  };
}

async function openDetail(items) {
  const body = {
    client: "alpha",
    since: "2026-09-15",
    until: "2026-10-14",
    server_today: "2026-10-14",
    enabled: true,
    items: items,
  };
  const page = loadDashboardPage({
    "/api/reports/clients": {
      clients: [{ slug: "alpha", name: "Alpha", active: true }],
      can_archive: false,
    },
    "/api/reports/summary": summary,
    [FEED]: () => body,
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page.root.querySelector("[data-ops-history-section]");
}

function rowOf(section, id) {
  return section
    .querySelectorAll("[data-ops-history-row]")
    .find((row) => row.getAttribute("data-decision") === id);
}

test.describe("the possible-duplicate hint", function () {
  test.it("marks the row and chips the title", async function () {
    const section = await openDetail([item("dec-r", "dec-k"), item("dec-k", null)]);
    const marked = rowOf(section, "dec-r");
    assert.ok(marked.hasAttribute("data-ops-history-duplicate"));
    const chip = marked.querySelector("[data-ops-history-duplicate-chip]");
    assert.equal(chip.textContent, "ops_history_section.possible_duplicate");
    assert.ok(chip.classList.contains("report-chip"));
    assert.ok(chip.classList.contains("is-info"));
    const plain = rowOf(section, "dec-k");
    assert.equal(plain.hasAttribute("data-ops-history-duplicate"), false);
    assert.equal(plain.querySelector("[data-ops-history-duplicate-chip]"), null);
  });

  test.it("explains the pair in the expanded row, as text", async function () {
    const section = await openDetail([item("dec-r", "dec-<b>k</b>")]);
    const detail = rowOf(section, "dec-r").nextSibling;
    const note = detail.querySelector("[data-ops-history-duplicate-note]");
    assert.equal(note.tagName, "P");
    assert.ok(note.classList.contains("ops-history-duplicate-note"));
    assert.equal(
      note.textContent,
      "ops_history_section.possible_duplicate_detail|id=dec-<b>k</b>,hours=24"
    );
    assert.equal(note.querySelector("a"), null);
    assert.equal(note.querySelector("b"), null);
  });

  test.it("says nothing when the server names no pair", async function () {
    const section = await openDetail([item("dec-k", null)]);
    const detail = rowOf(section, "dec-k").nextSibling;
    assert.equal(detail.querySelector("[data-ops-history-duplicate-note]"), null);
  });
});
