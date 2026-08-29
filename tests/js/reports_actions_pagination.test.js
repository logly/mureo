// The recent-actions log, read a page at a time (#729).
//
// Run with:  node --test tests/js/*.test.js
//
// The server caps the log at twenty entries and sends them newest first. All
// twenty were drawn at once, so the detail screen ended in a column of log
// rows taller than every figure above it — the log stopped being a footnote
// and became the page. This suite pins the fix as an operator sees it: five
// rows, a pager that only exists when there is a second page, ends that do
// not wrap, and page one again whenever the data changes.
//
// It drives the real dashboard against the real app.html AND the real
// app.css, because "the pager is hidden" is a CSS question as much as a DOM
// one: an author `display` on the pager would override the UA sheet's
// `[hidden] { display: none }` and leave it on screen for the quiet account
// this whole block is supposed to stay out of the way of.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { loadDashboardPage, settle, isVisible } = require("./dom_harness.js");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");
const TODAY = new Date().toISOString().slice(0, 10);

/** The page size the renderer is expected to use. */
const PAGE_SIZE = 5;

function summaryWith(overrides) {
  return Object.assign(
    {
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
          campaign_count: 3,
          freshness: { fetched_at: new Date().toISOString(), stale: false },
          not_collected: null,
          daily: [],
          daily_delta: null,
        },
      ],
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
 * `n` log entries, each one identifiable by its sentence.
 *
 * Short summaries on purpose: the read-more disclosure fires above
 * LEGACY_SUMMARY_CHARS, and this suite is about WHICH rows are on the page,
 * not about how one row shortens itself.
 */
function actions(n) {
  const rows = [];
  for (let i = 1; i <= n; i++) {
    rows.push({
      timestamp: new Date().toISOString(),
      action: "budget_update",
      platform: "google_ads",
      summary: "row-" + String(i).padStart(2, "0"),
      observation_due: null,
    });
  }
  return rows;
}

/** The single-client detail screen, opened on a log of `rows`. */
async function openWithActions(rows) {
  const page = loadDashboardPage({
    "/api/reports/clients": {
      clients: [{ slug: "alpha", name: "Alpha", active: true }],
      can_archive: false,
    },
    "/api/reports/summary": () => summaryWith({ recent_actions: rows }),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

/** The sentences currently on screen, in order. */
function rowsOnScreen(page) {
  return page.root
    .querySelectorAll(".report-action-summary")
    .map((el) => el.textContent);
}

function pager(page) {
  return page.root.querySelector("[data-reports-actions-pager]");
}

function pageLabel(page) {
  return page.root.querySelector("[data-reports-actions-page]").textContent;
}

function prevButton(page) {
  return page.root.querySelector("[data-reports-actions-prev]");
}

function nextButton(page) {
  return page.root.querySelector("[data-reports-actions-next]");
}

test.describe("the action log is read a page at a time", function () {
  test.it("draws only the first page of a full log", async function () {
    const page = await openWithActions(actions(20));
    const list = page.root.querySelector("[data-reports-actions-list]");
    assert.equal(
      list.querySelectorAll("li").length,
      PAGE_SIZE,
      "the whole log is still being drawn at once"
    );
    assert.deepEqual(rowsOnScreen(page), [
      "row-01",
      "row-02",
      "row-03",
      "row-04",
      "row-05",
    ]);
    // Server order is newest first and the pager does not reorder anything.
    assert.ok(isVisible(pager(page)), "the pager is not on screen");
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=1,pages=4");
  });

  test.it("moves to the next five rows", async function () {
    const page = await openWithActions(actions(20));
    nextButton(page).click();
    assert.deepEqual(rowsOnScreen(page), [
      "row-06",
      "row-07",
      "row-08",
      "row-09",
      "row-10",
    ]);
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=2,pages=4");
  });

  test.it("moves back again", async function () {
    const page = await openWithActions(actions(20));
    nextButton(page).click();
    prevButton(page).click();
    assert.deepEqual(rowsOnScreen(page), [
      "row-01",
      "row-02",
      "row-03",
      "row-04",
      "row-05",
    ]);
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=1,pages=4");
  });

  test.it("leaves a short last page short", async function () {
    // 12 entries is three pages, the last of which holds two.
    const page = await openWithActions(actions(12));
    nextButton(page).click();
    nextButton(page).click();
    assert.deepEqual(rowsOnScreen(page), ["row-11", "row-12"]);
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=3,pages=3");
  });

  test.it("does not wrap at either end", async function () {
    const page = await openWithActions(actions(20));
    assert.equal(prevButton(page).disabled, true, "page one offers a previous page");
    assert.equal(nextButton(page).disabled, false);
    // A browser would not even deliver this click; the renderer clamps too,
    // so a stray call cannot roll the log back to the top.
    prevButton(page).click();
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=1,pages=4");

    nextButton(page).click();
    nextButton(page).click();
    nextButton(page).click();
    assert.equal(nextButton(page).disabled, true, "the last page offers a next page");
    assert.equal(prevButton(page).disabled, false);
    nextButton(page).click();
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=4,pages=4");
    assert.deepEqual(rowsOnScreen(page), [
      "row-16",
      "row-17",
      "row-18",
      "row-19",
      "row-20",
    ]);
  });

  test.it("shows no pager at all for a log that fits on one page", async function () {
    // The quiet account: exactly the screen that shipped before #729.
    const page = await openWithActions(actions(PAGE_SIZE));
    assert.equal(rowsOnScreen(page).length, PAGE_SIZE);
    const nav = pager(page);
    assert.ok(nav, "the pager markup is gone from app.html");
    assert.equal(nav.hidden, true, "the pager carries no hidden attribute");
    assert.ok(
      !isVisible(nav),
      "the pager is on screen for a log with only one page — an author " +
        "`display` is beating the UA `[hidden] { display: none }`"
    );
  });

  test.it("goes back to page one when the data changes", async function () {
    const page = await openWithActions(actions(20));
    nextButton(page).click();
    nextButton(page).click();
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=3,pages=4");
    // A second client (or a refresh) is a different log; page three of the
    // one just left is not page three of this one.
    const detail = page.sandbox.MUREO_DASHBOARD_REPORTS_DETAIL;
    detail.renderActions(actions(20).map((a, i) => ({ ...a, summary: "new-" + i })));
    assert.equal(pageLabel(page), "dashboard.reports_actions_page|page=1,pages=4");
    assert.deepEqual(rowsOnScreen(page), [
      "new-0",
      "new-1",
      "new-2",
      "new-3",
      "new-4",
    ]);
  });

  test.it("hides the whole block, pager included, for an empty log", async function () {
    const page = await openWithActions([]);
    const block = page.root.querySelector("[data-reports-actions]");
    assert.ok(!isVisible(block), "the empty action block is on screen");
    assert.ok(!isVisible(pager(page)), "the pager outlived the block");
  });

  test.it("ships every string it selects in both locales", function () {
    const data = JSON.parse(fs.readFileSync(path.join(WEB, "i18n.json"), "utf-8"));
    for (const key of [
      "dashboard.reports_actions_prev",
      "dashboard.reports_actions_next",
      "dashboard.reports_actions_page",
    ]) {
      for (const locale of ["en", "ja"]) {
        assert.ok(
          data[locale] && data[locale][key],
          `${key} missing from i18n.json[${locale}]`
        );
      }
    }
  });

  test.it("labels the buttons in a way a screen reader can read", function () {
    // app.js's `data-i18n` sweep owns the static labels, so what is pinned
    // here is that the markup asks for them at all — an unlabelled pair of
    // arrows is two buttons called "button".
    const html = fs.readFileSync(path.join(WEB, "app.html"), "utf-8");
    const at = html.indexOf("data-reports-actions-pager");
    assert.notEqual(at, -1, "the pager is not in app.html");
    const block = html.slice(at, html.indexOf("</div>", at));
    assert.match(block, /data-i18n="dashboard\.reports_actions_prev"/);
    assert.match(block, /data-i18n="dashboard\.reports_actions_next"/);
  });
});
