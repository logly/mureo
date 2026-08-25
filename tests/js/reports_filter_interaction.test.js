// The client-grid health filter, driven the way an operator drives it.
//
// Run with:  node --test tests/js/*.test.js
//
// This is the test v0.12.0 did not have. The filter shipped green: its unit
// tests asserted that the right card items got `hidden` set on them, and
// they did. On screen nothing moved, because `.reports-client-card-item`
// declares `display: flex` — an author rule, which beats the user agent's
// `[hidden] { display: none }`. The JS was right, the CSS was right on its
// own, and the two together did nothing.
//
// No pin over dashboard.js could have caught that, so this test does not pin
// anything. It evaluates the real modules and the real dashboard.js against
// the real app.html, clicks the real chips, and then asks whether an
// operator would SEE each card — a question answered from the real app.css
// (see tests/js/dom_harness.js, which models the `[hidden]`-vs-`display`
// cascade and nothing else).
//
// What it asserts, therefore, is the behaviour the operator reported
// missing: click a chip, the number of cards on screen changes.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { loadDashboardPage, settle, isVisible, cascade } = require("./dom_harness.js");

const DAY_MS = 24 * 60 * 60 * 1000;
const ago = (days) => new Date(Date.now() - days * DAY_MS).toISOString();

/**
 * One client's summary. `kind` picks what the triage layer will make of it:
 *   stale -> "attention" (its totals are withheld)
 *   due   -> "watch"     (a review is overdue; nothing on screen is wrong)
 *   ok    -> "ok"        (nothing raised)
 */
function summaryFor(kind) {
  return {
    client: kind,
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
        freshness: {
          fetched_at: ago(kind === "stale" ? 11 : 0),
          stale: kind === "stale",
          stale_after_days: 2,
        },
        not_collected: null,
      },
    ],
    platform_conflicts: [],
    recent_actions: [],
    reports: null,
    observations_due:
      kind === "due" ? { count: 2, oldest_due: "2026-08-01" } : { count: 0, oldest_due: null },
    server_today: new Date().toISOString().slice(0, 10),
  };
}

const ROSTER = [
  { slug: "alpha", name: "Alpha", active: true },
  { slug: "bravo", name: "Bravo", active: true },
  { slug: "carol", name: "Carol", active: true },
  { slug: "dave", name: "Dave", active: true },
];
const SUMMARIES = {
  alpha: summaryFor("stale"),
  bravo: summaryFor("due"),
  carol: summaryFor("ok"),
  dave: summaryFor("ok"),
};

/** Open the dashboard, click "Reports" in the left menu, let it settle. */
async function openReportsIndex() {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: true },
    "/api/reports/summary": (url) => {
      const m = /client=([^&]+)/.exec(url);
      return SUMMARIES[m ? decodeURIComponent(m[1]) : "carol"];
    },
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  // The operator's own route in: the left-menu item, which is also what
  // renders the index (see renderReports / REPORTS_ENTRY_MENU).
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

function cards(page) {
  return page.root.querySelector("[data-reports-clients]").querySelectorAll("[data-health]");
}

function visibleHealths(page) {
  return cards(page)
    .filter(isVisible)
    .map((el) => el.getAttribute("data-health"));
}

async function clickFilter(page, name) {
  const chip = page.root
    .querySelectorAll("[data-reports-filter]")
    .find((c) => c.getAttribute("data-reports-filter") === name);
  assert.ok(chip, "no filter chip for " + name);
  chip.click();
  await settle(3);
  return chip;
}

test.describe("the health filter, clicked", function () {
  test.it("renders one card per client, all of them on screen", async function () {
    const page = await openReportsIndex();
    assert.deepEqual(visibleHealths(page).sort(), ["attention", "ok", "ok", "watch"]);
  });

  test.it("shows only the clients at the health that was clicked", async function () {
    // THE REGRESSION. Before the fix this read four cards after every click:
    // the attribute was set on three of them and the stylesheet ignored it.
    const page = await openReportsIndex();
    await clickFilter(page, "attention");
    assert.deepEqual(visibleHealths(page), ["attention"]);

    await clickFilter(page, "watch");
    assert.deepEqual(visibleHealths(page), ["watch"]);

    await clickFilter(page, "ok");
    assert.deepEqual(visibleHealths(page), ["ok", "ok"]);
  });

  test.it("brings every card back when All is clicked", async function () {
    const page = await openReportsIndex();
    await clickFilter(page, "attention");
    assert.equal(visibleHealths(page).length, 1);
    await clickFilter(page, "all");
    assert.equal(visibleHealths(page).length, 4);
  });

  test.it("hides the cards rather than removing them", async function () {
    // The grid is also the operator's own card order (#556): rebuilding it
    // from a filtered list would reorder it. The cards stay in the DOM, in
    // their order, with the attribute set.
    const page = await openReportsIndex();
    const before = cards(page).map((el) => el.getAttribute("data-client"));
    await clickFilter(page, "attention");
    const after = cards(page).map((el) => el.getAttribute("data-client"));
    assert.deepEqual(after, before, "the grid was rebuilt, not filtered");
    assert.equal(cards(page).length, 4);
  });

  test.it("marks the clicked chip as the active one", async function () {
    const page = await openReportsIndex();
    const chip = await clickFilter(page, "watch");
    assert.equal(chip.getAttribute("aria-pressed"), "true");
    assert.ok(chip.classList.contains("is-active"));
    const all = page.root
      .querySelectorAll("[data-reports-filter]")
      .find((c) => c.getAttribute("data-reports-filter") === "all");
    assert.equal(all.getAttribute("aria-pressed"), "false");
  });

  test.it("counts every card on the chips, including the filtered-out ones", async function () {
    const page = await openReportsIndex();
    await clickFilter(page, "attention");
    const counts = {};
    page.root.querySelectorAll("[data-reports-filter]").forEach(function (chip) {
      const label = chip.querySelectorAll(".reports-filter-count")[0];
      counts[chip.getAttribute("data-reports-filter")] = label && label.textContent;
    });
    assert.deepEqual(counts, { all: "4", attention: "1", watch: "1", ok: "2" });
  });

  test.it("starts unfiltered again when the index re-renders", async function () {
    // A filter left over from a previous render would leave cards missing
    // with nothing on screen to say why.
    const page = await openReportsIndex();
    await clickFilter(page, "attention");
    assert.equal(visibleHealths(page).length, 1);
    page.root.querySelector('[data-dashboard-nav="reports"]').click();
    await settle();
    assert.equal(visibleHealths(page).length, 4);
  });
});

test.describe("the stylesheet agrees that a hidden card is hidden", function () {
  test.it("gives every element the view hides an escape from its own display", function () {
    // The general form of the bug: `el.hidden = true` does nothing to an
    // element whose class declares an explicit `display`, because an author
    // rule beats the UA sheet. Every element the Reports view hides this way
    // needs a `[hidden]` rule of its own — this is the list of them.
    const { DISPLAY_BY_CLASS, HIDDEN_DISPLAY_BY_CLASS } = require("./dom_harness.js");
    const HIDDEN_BY_JS = [
      "reports-client-card-item", // the health filter
      "reports-kpis",
      "reports-index-grid",
      "reports-triage",
      "reports-triage-detail",
      "reports-triage-more",
      "reports-triage-hidden",
      "reports-filters",
      "reports-feed-panel",
      "reports-platforms",
      "reports-panel-note",
      "dashboard-reports-clients",
      "dashboard-reports-period",
    ];
    const broken = HIDDEN_BY_JS.filter(function (cls) {
      const display = DISPLAY_BY_CLASS.get(cls);
      if (!display || display === "none") return false; // the UA rule suffices
      return HIDDEN_DISPLAY_BY_CLASS.get(cls) !== "none";
    });
    assert.deepEqual(
      broken,
      [],
      "these declare a display that overrides [hidden], so hiding them does nothing"
    );
  });
});

test.describe("a marked card names its own severity (#697)", function () {
  // The grid marks every client the triage layer put on its list, and the
  // list holds attention AND watch clients. The marker said "needs
  // attention" for all of them, so a watch card carried an urgent word above
  // it and the badge inside it said "watch" — the same card, disagreeing
  // with itself, in the alert colour.
  //
  // This reads the rendered card rather than the call to MUREO.t, because
  // what was wrong was never which function ran: it was which string it was
  // handed.

  const markOf = (page, health) => {
    const card = cards(page).find((c) => c.getAttribute("data-health") === health);
    assert.ok(card, "no card at health " + health);
    return card.querySelector(".reports-client-card-mark");
  };

  test.it("marks the attention client and the watch client differently", async function () {
    const page = await openReportsIndex();
    const t = (k) => page.sandbox.MUREO.t(k);

    assert.equal(markOf(page, "attention").textContent, t("dashboard.reports_health_attention"));
    assert.equal(markOf(page, "watch").textContent, t("dashboard.reports_health_watch"));
    assert.notEqual(
      t("dashboard.reports_health_attention"),
      t("dashboard.reports_health_watch"),
      "the two severities share a string, so this test proves nothing"
    );
  });

  test.it("never says 'needs attention' anywhere on a watch card", async function () {
    // THE REGRESSION, stated the way it was seen: the words on the card.
    const page = await openReportsIndex();
    const attention = page.sandbox.MUREO.t("dashboard.reports_health_attention");
    const card = cards(page).find((c) => c.getAttribute("data-health") === "watch");
    assert.ok(
      !card.textContent.includes(attention),
      "a watch card still reads '" + attention + "': " + card.textContent
    );
  });

  test.it("leaves the untriaged clients unmarked", async function () {
    const page = await openReportsIndex();
    cards(page)
      .filter((c) => c.getAttribute("data-health") === "ok")
      .forEach((c) => {
        assert.equal(
          c.querySelectorAll(".reports-client-card-mark").length,
          0,
          "a client the layer raised nothing about was marked"
        );
      });
  });

  test.it("colours the two markers apart, and the watch one is not the alert red", async function () {
    // Colour is the half of the mark an operator reads first, and red is
    // reserved for act-now. `cascade` resolves this against the real
    // app.css, so a rule that quietly outranks these would show up here.
    const page = await openReportsIndex();
    const alert = cascade(markOf(page, "attention"), "color");
    const watch = cascade(markOf(page, "watch"), "color");
    assert.equal(alert.value, "var(--status-alert)", "won by: " + alert.selector);
    assert.equal(watch.value, "var(--status-watch)", "won by: " + watch.selector);
  });

  test.it("outlines a watch card in the watch colour, not the alert colour", async function () {
    // The border rule is written with a child combinator, which the harness
    // ignored entirely until this change — meaning `cascade` used to answer
    // this question with the wrong rule rather than the winning one.
    const page = await openReportsIndex();
    const cardOf = (health) =>
      cards(page)
        .find((c) => c.getAttribute("data-health") === health)
        .querySelector(".reports-client-card");
    const alert = cascade(cardOf("attention"), "border-color");
    const watch = cascade(cardOf("watch"), "border-color");
    assert.match(alert.value, /--status-alert/, "won by: " + alert.selector);
    assert.match(watch.value, /--status-watch/, "won by: " + watch.selector);
  });
});
