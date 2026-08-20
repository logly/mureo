// Closing an alert, one message at a time, driven the way an operator does.
//
// Run with:  node --test tests/js/*.test.js
//
// The ✕ used to close a whole ROW, and the rows are grouped by kind: one of
// them can cover six clients, so "hide" took five findings the operator had
// never read. It is per message now, and the three things that must hold
// while it is are behavioural, not structural:
//
//   • closing one message shrinks the row it was on — its count and the
//     clients it names — rather than removing the row;
//   • closing the last one takes the row with it;
//   • nothing goes quiet. The "N hidden" line counts MESSAGES and offers the
//     way back, and the layer's own count above (and every marked card
//     below) is untouched, because the condition is still true.
//
// Driven through the real dashboard.js against the real app.html — see
// tests/js/dom_harness.js.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle, isVisible } = require("./dom_harness.js");

const DAY_MS = 24 * 60 * 60 * 1000;
const ago = (days) => new Date(Date.now() - days * DAY_MS).toISOString();

/** A client whose entries mureo cannot resolve to a platform. */
function unknownKeySummary() {
  return {
    client: "x",
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: ago(0),
    platforms: [
      {
        key: "google_ads",
        display_name: "Google Ads",
        totals: { spend: 1000, conversions: 10 },
        metrics_period: "YESTERDAY",
        freshness: { fetched_at: ago(0), stale: false, stale_after_days: 2 },
        not_collected: null,
      },
    ],
    platform_conflicts: [
      { kind: "unrecognized_key", platform_keys: ["logly_ads_context"], account_known: false },
    ],
    recent_actions: [],
    reports: null,
    observations_due: { count: 0, oldest_due: null },
    server_today: new Date().toISOString().slice(0, 10),
  };
}

const ROSTER = [
  { slug: "alpha", name: "Alpha", active: true },
  { slug: "bravo", name: "Bravo", active: true },
  { slug: "carol", name: "Carol", active: true },
];

async function openReportsIndex() {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: true },
    "/api/reports/summary": () => unknownKeySummary(),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

const rows = (page) =>
  page.root.querySelector("[data-reports-triage-list]").querySelectorAll("[data-triage-kind]");

const messages = (page) =>
  page.root
    .querySelector("[data-reports-triage-list]")
    .querySelectorAll(".reports-triage-detail-row");

/** Open the first row's disclosure, where the per-message controls live. */
async function expandFirstRow(page) {
  rows(page)[0].querySelectorAll(".reports-triage-toggle")[0].click();
  await settle(2);
}

async function dismissMessage(page, index) {
  const drop = messages(page)[index].querySelectorAll(".reports-triage-dismiss")[0];
  assert.ok(drop, "message " + index + " has no dismiss control");
  drop.click();
  await settle(3);
}

function hiddenLine(page) {
  return page.root.querySelector("[data-reports-triage-hidden]");
}

test.describe("closing one message", function () {
  test.it("puts three clients on one row and a control on each message", async function () {
    const page = await openReportsIndex();
    assert.equal(rows(page).length, 1, "the findings did not group into one row");
    await expandFirstRow(page);
    assert.equal(messages(page).length, 3);
    messages(page).forEach(function (line) {
      assert.equal(line.querySelectorAll(".reports-triage-dismiss").length, 1);
    });
  });

  test.it("shrinks the row rather than removing it", async function () {
    const page = await openReportsIndex();
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    assert.equal(rows(page).length, 1, "one dismissal took the whole row");
    assert.equal(messages(page).length, 2);
    // …and the row's own count follows the messages it still holds.
    const badge = rows(page)[0].querySelectorAll(".reports-count-badge")[0];
    assert.ok(badge.textContent.includes("2"), badge.textContent);
  });

  test.it("keeps the row open, so the next one is one click away", async function () {
    // A row that snapped shut after every ✕ would make closing three
    // findings three trips through the disclosure.
    const page = await openReportsIndex();
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    assert.equal(messages(page).length, 2, "the row closed itself after a dismissal");
  });

  test.it("takes the row with the last message on it", async function () {
    const page = await openReportsIndex();
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    assert.equal(rows(page).length, 0);
    // The panel itself stays: it still has to say what was hidden.
    assert.ok(isVisible(page.root.querySelector("[data-reports-triage]")));
  });
});

test.describe("closing a message is never silent", function () {
  test.it("counts hidden MESSAGES on screen, with the way back", async function () {
    const page = await openReportsIndex();
    assert.ok(!isVisible(hiddenLine(page)), "the hidden line shows with nothing hidden");
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    const line = hiddenLine(page);
    assert.ok(isVisible(line));
    assert.ok(line.textContent.includes("2"), line.textContent);
    // In words: hiding resolved nothing.
    assert.ok(line.textContent.includes("dashboard.reports_triage_hidden_note"));
    assert.ok(line.querySelectorAll(".reports-triage-restore").length === 1);
  });

  test.it("brings every message back", async function () {
    const page = await openReportsIndex();
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    hiddenLine(page).querySelectorAll(".reports-triage-restore")[0].click();
    await settle(3);
    assert.equal(rows(page).length, 1);
    assert.ok(!isVisible(hiddenLine(page)));
  });

  test.it("leaves the layer's count and the marked cards alone", async function () {
    // The condition is still true for all three clients. Hiding is a view
    // operation, and the count above the list is not a view of the list.
    const page = await openReportsIndex();
    const heading = page.root.querySelector("[data-reports-triage-title]").textContent;
    const marked = page.root
      .querySelector("[data-reports-clients]")
      .querySelectorAll(".reports-client-card-mark").length;
    await expandFirstRow(page);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    await dismissMessage(page, 0);
    assert.equal(rows(page).length, 0);
    assert.equal(page.root.querySelector("[data-reports-triage-title]").textContent, heading);
    assert.equal(
      page.root
        .querySelector("[data-reports-clients]")
        .querySelectorAll(".reports-client-card-mark").length,
      marked
    );
    assert.equal(marked, 3, "the grid stopped marking the clients it triaged");
  });
});

test.describe("closing a whole row", function () {
  test.it("is every message on it, counted as such", async function () {
    const page = await openReportsIndex();
    rows(page)[0].querySelectorAll(".reports-triage-dismiss")[0].click();
    await settle(3);
    assert.equal(rows(page).length, 0);
    const line = hiddenLine(page);
    assert.ok(isVisible(line));
    assert.ok(line.textContent.includes("3"), "the row counted as one hidden thing");
  });
});
