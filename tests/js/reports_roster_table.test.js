// The agency roster as a table (#691 phase 3).
//
// Run with:  node --test tests/js/*.test.js
//
// Drives the real dashboard against the real app.html AND the real app.css,
// because half of what this feature is are things a DOM assertion cannot see:
// whether a row is on screen, whether the filter still reaches it after a
// re-sort, and whether the view an operator chose survives.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle, isVisible, cascade } = require("./dom_harness.js");

//: The storage key, restated here because the view has to be seeded BEFORE
//: the page evaluates its scripts. A test below asserts the module agrees,
//: so the two cannot drift apart silently.
const ROSTER_VIEW_KEY = "mureo.reports.roster_view";

/**
 * The table module as the BROWSER has it.
 *
 * It reads `window.MUREO_DASHBOARD_REPORTS_STATE` at load, so `require()`-ing
 * it in Node throws — the same shape every dashboard_reports_*.js module has.
 * Reaching it through the evaluated page is not a workaround: it is the only
 * way to exercise the bytes that actually ship.
 */
const tableApi = (page) => page.sandbox.MUREO_DASHBOARD_REPORTS_TABLE;

const DAY = 86400000;
const ago = (d) => new Date(Date.now() - d * DAY).toISOString();

/**
 * One client's summary. `kind` picks what the triage layer makes of it:
 *   stale -> "attention" (its totals are withheld)
 *   ok    -> "ok"
 */
function summaryFor(slug, kind, totals) {
  return {
    client: slug,
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: ago(0),
    platforms: [
      {
        key: "google_ads",
        display_name: "Google Ads",
        totals: totals,
        metrics_period: "YESTERDAY",
        campaign_count: 2,
        freshness: {
          fetched_at: ago(kind === "stale" ? 11 : 0),
          stale: kind === "stale",
          stale_after_days: 2,
        },
        not_collected: null,
        daily: [],
        daily_delta: null,
      },
    ],
    platform_conflicts: [],
    recent_actions: [],
    reports: {},
    observations_due: { count: 0, oldest_due: null },
    server_today: new Date().toISOString().slice(0, 10),
  };
}

// clicks + impressions are carried because a client CTR is DERIVED from them
// (total clicks over total impressions), not read off a platform row — the
// real payload carries all four.
const CLIENTS = {
  alpha: summaryFor("alpha", "stale", {
    spend: 63000, conversions: 15, cpa: 4200, ctr: 2.22,
    clicks: 1400, impressions: 63000,
  }),
  bravo: summaryFor("bravo", "ok", {
    spend: 128400, conversions: 46, cpa: 2791, ctr: 3.1,
    clicks: 3980, impressions: 128400,
  }),
  carol: summaryFor("carol", "ok", {
    spend: 35800, conversions: 22, cpa: 1627, ctr: 3.76,
    clicks: 1346, impressions: 35800,
  }),
};

const ROSTER = [
  { slug: "alpha", name: "Alpha Trading", active: true },
  { slug: "bravo", name: "Bravo Logistics", active: true },
  { slug: "carol", name: "Carol Foods", active: true },
];

async function openRoster(options) {
  const opts = options || {};
  const clients = opts.clients || ROSTER;
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: clients, can_archive: false },
    "/api/reports/summary": (url) => {
      const m = /client=([^&]+)/.exec(url);
      const slug = m ? decodeURIComponent(m[1]) : clients[0].slug;
      return (opts.summaries || CLIENTS)[slug] || summaryFor(slug, "ok", { spend: 1 });
    },
  });
  // Seed the remembered view BEFORE the render, which is when it is read.
  if (opts.stored) page.localStore.set(ROSTER_VIEW_KEY, opts.stored);
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

const rows = (page) => page.root.querySelectorAll(".roster-row");
const names = (page) =>
  rows(page).map((r) => r.getAttribute("data-client-name"));
const visibleNames = (page) =>
  rows(page).filter(isVisible).map((r) => r.getAttribute("data-client-name"));

function viewButton(page, view) {
  return page.root
    .querySelectorAll("[data-reports-view]")
    .find((b) => b.getAttribute("data-reports-view") === view);
}

function sortHeader(page, key) {
  return page.root
    .querySelectorAll("[data-reports-sort]")
    .find((b) => b.getAttribute("data-reports-sort") === key);
}

// ---------------------------------------------------------------------
// Who gets the table
// ---------------------------------------------------------------------

test.describe("the table is for a roster worth comparing", function () {
  test.it("is the default view at two or more clients", async function () {
    const page = await openRoster();
    const host = page.root.querySelector("[data-reports-roster-table]");
    assert.equal(host.hidden, false, "the table is hidden by default");
    assert.ok(isVisible(host), "the table computes to display:none");
    assert.equal(rows(page).length, 3);
    // …and the grid steps aside rather than both being on screen.
    assert.equal(
      isVisible(page.root.querySelector("[data-reports-clients]")),
      false,
      "the card grid is still showing under the table"
    );
  });

  test.it("is not offered at all for a single visible client", async function () {
    // A one-row table is a worse card. The index still renders — an archived
    // sibling is what put it there — but the toggle is not on screen.
    const page = await openRoster({
      clients: [
        { slug: "alpha", name: "Alpha Trading", active: true },
        { slug: "zulu", name: "Zulu Ltd", active: false, archived: true },
      ],
    });
    const tools = page.root.querySelector("[data-reports-roster-tools]");
    assert.equal(tools.hidden, true, "the view switch is offered for one client");
    assert.equal(rows(page).length, 0, "a table was built for one client");
    assert.ok(
      isVisible(page.root.querySelector("[data-reports-clients]")),
      "the cards are not showing"
    );
  });

  test.it("agrees with the module's own threshold and storage key", async function () {
    const api = tableApi(await openRoster());
    assert.equal(api.ROSTER_TABLE_MIN, 2);
    assert.equal(api.rosterViewFor(1), "cards");
    assert.equal(api.rosterViewFor(2), "table");
    assert.equal(api.ROSTER_VIEW_KEY, ROSTER_VIEW_KEY, "the storage key drifted");
  });
});

// ---------------------------------------------------------------------
// Order
// ---------------------------------------------------------------------

test.describe("status order is the default, and it is an argument", function () {
  test.it("puts the clients needing action first", async function () {
    const page = await openRoster();
    // Alpha is stale -> attention. Bravo and Carol are ok, and within a
    // status group the bigger spender leads.
    assert.deepEqual(names(page), ["Alpha Trading", "Bravo Logistics", "Carol Foods"]);
  });

  test.it("says what it is sorted by", async function () {
    const page = await openRoster();
    const label = page.root.querySelector("[data-reports-sorted-by]");
    assert.equal(label.hidden, false);
    assert.match(label.textContent, /status/i);
  });

  test.it("sorts by a column when its header is clicked", async function () {
    const page = await openRoster();
    sortHeader(page, "spend").click();
    await settle();
    // First click on a figure column is descending — the biggest first is
    // what somebody clicking "spend" is looking for. Alpha is last in BOTH
    // directions: it is stale, so its spend is withheld rather than small.
    assert.deepEqual(names(page), ["Bravo Logistics", "Carol Foods", "Alpha Trading"]);
  });

  test.it("flips direction on a second click of the same column", async function () {
    const page = await openRoster();
    sortHeader(page, "spend").click();
    await settle();
    sortHeader(page, "spend").click();
    await settle();
    assert.deepEqual(names(page), ["Carol Foods", "Bravo Logistics", "Alpha Trading"]);
  });

  test.it("marks the sorted column, and only it", async function () {
    const page = await openRoster();
    sortHeader(page, "spend").click();
    await settle();
    const marked = page.root
      .querySelectorAll(".roster-head")
      .filter((th) => (th.className || "").split(/\s+/).includes("is-sorted"));
    assert.equal(marked.length, 1, "more than one column claims to be sorted");
    // The direction is a character too, not colour and weight alone.
    assert.equal(page.root.querySelectorAll(".roster-sort-arrow").length, 1);
  });

  test.it("sorts a figure mureo will not state to the end, both ways", async function () {
    // "Unknown" is not a small number. Floating it to the top of an ascending
    // sort would put the least informative rows where the most urgent belong.
    const api = tableApi(await openRoster());
    const withNull = [
      { slug: "a", name: "A", health: "ok", spend: 10, cpa: null },
      { slug: "b", name: "B", health: "ok", spend: 20, cpa: 5 },
    ];
    assert.deepEqual(
      api.sortRows(withNull, { key: "cpa", dir: "asc" }).map((r) => r.name),
      ["B", "A"]
    );
    assert.deepEqual(
      api.sortRows(withNull, { key: "cpa", dir: "desc" }).map((r) => r.name),
      ["B", "A"]
    );
  });
});

// ---------------------------------------------------------------------
// The view switch, and remembering it
// ---------------------------------------------------------------------

test.describe("the operator's choice of view survives", function () {
  test.it("switches to the cards and back", async function () {
    const page = await openRoster();
    viewButton(page, "cards").click();
    await settle();
    assert.ok(isVisible(page.root.querySelector("[data-reports-clients]")));
    assert.equal(isVisible(page.root.querySelector("[data-reports-roster-table]")), false);
    viewButton(page, "table").click();
    await settle();
    assert.ok(isVisible(page.root.querySelector("[data-reports-roster-table]")));
  });

  test.it("writes the choice to storage", async function () {
    const page = await openRoster();
    viewButton(page, "cards").click();
    await settle();
    assert.equal(page.localStore.get(ROSTER_VIEW_KEY), "cards");
  });

  test.it("opens on the remembered choice", async function () {
    const page = await openRoster({ stored: "cards" });
    assert.ok(
      isVisible(page.root.querySelector("[data-reports-clients]")),
      "a remembered 'cards' did not survive the reload"
    );
    assert.equal(rows(page).length, 0);
  });

  test.it("does not resurrect a table for a roster that shrank to one", async function () {
    // A remembered "table" must not outlive the roster that earned it.
    const page = await openRoster({ stored: "table" });
    assert.equal(tableApi(page).rosterViewFor(1), "cards");
  });

  test.it("marks the active button for a screen reader too", async function () {
    const page = await openRoster();
    assert.equal(viewButton(page, "table").getAttribute("aria-pressed"), "true");
    assert.equal(viewButton(page, "cards").getAttribute("aria-pressed"), "false");
  });
});

// ---------------------------------------------------------------------
// The filter and the search reach the table's rows
// ---------------------------------------------------------------------

test.describe("filtering works in the table, not only in the grid", function () {
  async function clickFilter(page, name) {
    const chip = page.root
      .querySelectorAll("[data-reports-filter]")
      .find((c) => c.getAttribute("data-reports-filter") === name);
    assert.ok(chip, "no filter chip for " + name);
    chip.click();
    await settle();
    return chip;
  }

  test.it("hides the rows at other healths", async function () {
    const page = await openRoster();
    await clickFilter(page, "attention");
    assert.deepEqual(visibleNames(page), ["Alpha Trading"]);
  });

  test.it("brings them back on All", async function () {
    const page = await openRoster();
    await clickFilter(page, "attention");
    await clickFilter(page, "all");
    assert.equal(visibleNames(page).length, 3);
  });

  test.it("keeps the filter across a re-sort", async function () {
    // The rows are new nodes after a sort, so a filter that was not
    // re-applied would silently come undone.
    const page = await openRoster();
    await clickFilter(page, "attention");
    sortHeader(page, "spend").click();
    await settle();
    assert.deepEqual(visibleNames(page), ["Alpha Trading"]);
  });

  test.it("keeps the filter across a view switch", async function () {
    const page = await openRoster();
    await clickFilter(page, "attention");
    viewButton(page, "cards").click();
    await settle();
    const shown = page.root
      .querySelector("[data-reports-clients]")
      .querySelectorAll("[data-health]")
      .filter(isVisible);
    assert.equal(shown.length, 1, "the filter did not follow to the cards");
  });

  test.it("hides a row the stylesheet would otherwise still show", async function () {
    // #665's discipline, for the new rows: `hidden` only works if nothing
    // gives the element a display that outranks the UA rule.
    const page = await openRoster();
    await clickFilter(page, "attention");
    const hiddenRow = rows(page).find((r) => r.hidden);
    assert.ok(hiddenRow, "nothing was hidden");
    const display = cascade(hiddenRow, "display");
    assert.ok(
      display && display.value === "none",
      "a hidden row computes display:" +
        (display && display.value) +
        " via `" +
        (display && display.selector) +
        "`"
    );
  });

  test.it("narrows to a client by name, and says when nothing matches", async function () {
    const page = await openRoster();
    const search = page.root.querySelector("[data-reports-client-search]");
    search.value = "bravo";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.deepEqual(visibleNames(page), ["Bravo Logistics"]);

    search.value = "nothing-like-this";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.deepEqual(visibleNames(page), []);
    assert.equal(
      page.root.querySelector("[data-reports-search-empty]").hidden,
      false,
      "an empty result says nothing at all"
    );
  });

  test.it("composes the search with the health filter", async function () {
    // Both narrow; neither overrides. The intersection is what is left.
    const page = await openRoster();
    await clickFilter(page, "attention");
    const search = page.root.querySelector("[data-reports-client-search]");
    search.value = "bravo";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.deepEqual(visibleNames(page), []);
  });
});

// ---------------------------------------------------------------------
// The figures
// ---------------------------------------------------------------------

test.describe("the table states figures it can and refuses the rest", function () {
  test.it("omits the CPA-target column when no client has a target", async function () {
    // Nothing on the reports wire carries a target CPA today. A column that
    // said "—" the whole way down would advertise a comparison mureo cannot
    // make, so the column is not drawn at all.
    const page = await openRoster();
    const headers = page.root
      .querySelectorAll("[data-reports-sort]")
      .map((b) => b.getAttribute("data-reports-sort"));
    assert.ok(!headers.includes("cpaRatio"), "a target column with no targets");
  });

  test.it("draws the column as soon as one client has a target", async function () {
    // The renderer is ready; only the datum is missing. Feeding one proves
    // the path is live rather than dead code.
    const withGoal = Object.assign({}, CLIENTS);
    withGoal.bravo = Object.assign({}, CLIENTS.bravo, {
      goals: { target_cpa: 2000 },
    });
    const page = await openRoster({ summaries: withGoal });
    const headers = page.root
      .querySelectorAll("[data-reports-sort]")
      .map((b) => b.getAttribute("data-reports-sort"));
    assert.ok(headers.includes("cpaRatio"), "the target column did not appear");
    const value = page.root.querySelector(".roster-ratio-value");
    assert.ok(value, "no ratio was rendered");
  });

  test.it("says a CPA is not calculable rather than printing a zero", async function () {
    const row = tableApi(await openRoster()).rosterRow(
      { slug: "z", name: "Z" },
      summaryFor("z", "ok", { spend: 48500, conversions: 0, ctr: 1.86 }),
      "attention"
    );
    assert.equal(row.cpa, null, "a CPA was invented from zero conversions");
    assert.equal(row.cpaUnavailable, true);
  });

  test.it("prints 'not calculable' on the CPA cell, which always renders", async function () {
    // The distinction this pins: two rows both show "—" in the CPA column,
    // and they mean different things. Carol's is withheld; Zero's cannot be
    // divided. Only the second carries the note.
    //
    // It has to hang off the CPA cell specifically. It first shipped on the
    // CPA-vs-target cell, a column that is dropped when no client has a
    // target — so on every install that exists, the note never rendered. A
    // pin on `row.cpaUnavailable` alone (above) stayed green throughout that,
    // which is why this one reads the cell.
    const withZero = Object.assign({}, CLIENTS, {
      zero: summaryFor("zero", "ok", {
        spend: 46900, conversions: 0, cpa: null, ctr: 2.67,
        clicks: 1250, impressions: 46900,
      }),
    });
    const page = await openRoster({
      clients: ROSTER.concat([{ slug: "zero", name: "Zero Convert", active: true }]),
      summaries: withZero,
    });

    const rowFor = (name) =>
      rows(page).find((r) => r.getAttribute("data-client-name") === name);

    const notes = rowFor("Zero Convert").querySelectorAll(".roster-note");
    assert.equal(notes.length, 1, "the CPA cell carried no explanation");
    const cpaCell = rowFor("Zero Convert").querySelector(".roster-cpa");
    assert.equal(
      cpaCell.querySelectorAll(".roster-note").length,
      1,
      "the note is not on the CPA cell"
    );
    assert.match(cpaCell.textContent, /—/, "the dash it explains is missing");
    assert.ok(isVisible(notes[0]), "the note rendered but is not on screen");

    // A client whose CPA is simply withheld says nothing extra: it is not
    // "not calculable", it is "not vouched for", and claiming the first would
    // be wrong about why.
    assert.equal(
      rowFor("Alpha Trading").querySelectorAll(".roster-note").length,
      0,
      "a withheld CPA was labelled as non-calculable"
    );
  });

  test.it("keeps the screen-reader labels off the screen", async function () {
    // `.sr-only` was used by the toolbar markup before app.css defined it,
    // so both labels simply rendered as body text next to the controls.
    // Asserting the rule exists would not have caught it either — this reads
    // the resolved cascade the browser would.
    const page = await openRoster();
    const labels = page.root.querySelectorAll(".sr-only");
    assert.ok(labels.length >= 2, "the toolbar labels are gone entirely");
    labels.forEach((el) => {
      assert.equal(
        cascade(el, "position").value,
        "absolute",
        "a .sr-only label is still in the layout: " + el.textContent
      );
      assert.equal(cascade(el, "width").value, "1px");
    });
  });

  test.it("labels the client search in the operator's language", async function () {
    // app.js's `data-i18n` sweep only rewrites text nodes, so a placeholder
    // set in the markup stays English forever. With the visible label now
    // correctly hidden, the placeholder is the field's only label.
    const page = await openRoster();
    const search = page.root.querySelector("[data-reports-client-search]");
    const placeholder = search.getAttribute("placeholder");
    assert.ok(placeholder, "the search field has no placeholder at all");
    assert.equal(
      placeholder,
      page.sandbox.MUREO.t("dashboard.reports_search_clients"),
      "the placeholder is not the translated string"
    );
  });

  test.it("totals spend and conversions, and weights the CPA", async function () {
    const page = await openRoster();
    const foot = page.root
      .querySelector(".roster-total")
      .children.map((td) => td.textContent);
    // Alpha is stale, so mureo will not state its figures and they are not in
    // the total either — a roster sum that quietly included a withheld client
    // would be the #638 bug one level up.
    //
    // Bravo + Carol: 128,400 + 35,800 = 164,200 over 46 + 22 = 68, which is
    // 2,415. NOT the mean of 2,791 and 1,627 (2,209): a weighted average is
    // what stops the smaller spender pulling the roster figure as hard as the
    // larger one.
    assert.match(foot.join(" "), /164,200/);
    assert.match(foot.join(" "), /68/);
    assert.match(foot.join(" "), /2,415/);
  });

  test.it("prints a real CTR per row and in no total", async function () {
    // The regression this pins: aggregateClientKpis carried no `ctr` at all,
    // so every row of this column rendered "—" — a dead column, which is the
    // very thing the CPA-target column is omitted to avoid.
    const page = await openRoster();
    const ctrs = rows(page).map((r) => r.children[4].textContent);
    // Alpha is stale so its figures are withheld; the other two are stated.
    assert.deepEqual(ctrs.filter((t) => t !== "—").length, 2, ctrs.join(" | "));
    assert.ok(
      ctrs.some((t) => /%/.test(t)),
      "no row printed a percentage: " + ctrs.join(" | ")
    );
    // The roster has no single CTR worth stating, so the total stays "—".
    const foot = page.root
      .querySelector(".roster-total")
      .children.map((td) => td.textContent);
    assert.equal(foot[foot.length - 3], "—");
  });

  test.it("shows a dash when the client carried no impressions", async function () {
    const noImpressions = Object.assign({}, CLIENTS);
    noImpressions.bravo = summaryFor("bravo", "ok", {
      spend: 128400,
      conversions: 46,
      clicks: 3980,
    });
    const page = await openRoster({ summaries: noImpressions });
    const bravo = rows(page).find(
      (r) => r.getAttribute("data-client-name") === "Bravo Logistics"
    );
    assert.equal(bravo.children[4].textContent, "—", "a CTR was invented");
  });

  test.it("leaves CTR out of the totals rather than averaging it", async function () {
    // Averaging CTRs across clients with different impression volumes states
    // a number nobody measured.
    const page = await openRoster();
    const foot = page.root
      .querySelector(".roster-total")
      .children.map((td) => td.textContent);
    assert.equal(foot[foot.length - 3], "—", "a roster CTR was invented");
  });
});

// ---------------------------------------------------------------------
// The totals row answers the question the operator narrowed to
// ---------------------------------------------------------------------

test.describe("the total follows the filter", function () {
  const foot = (page) =>
    page.root.querySelector(".roster-total").children.map((td) => td.textContent);

  async function clickFilter(page, name) {
    const chip = page.root
      .querySelectorAll("[data-reports-filter]")
      .find((c) => c.getAttribute("data-reports-filter") === name);
    assert.ok(chip, "no filter chip for " + name);
    chip.click();
    await settle();
    return chip;
  }

  test.it("sums only the rows on screen once a filter is applied", async function () {
    // Alpha is stale, so it withholds its figures and contributes nothing to
    // any total. Bravo (128,400 / 46) and Carol (35,800 / 22) are the whole
    // roster's stated figures, so the unfiltered total is both of them.
    const page = await openRoster();
    assert.match(foot(page).join(" "), /164,200/, "the roster total is not both clients");

    // "ok" is Bravo and Carol; narrowing to it changes nothing but the label.
    // "watch" would be empty here, so filter to a single stated client
    // instead by searching, which the next test does. Here: attention only,
    // which is Alpha — and Alpha states nothing.
    await clickFilter(page, "attention");
    const attention = foot(page);
    assert.equal(attention[1], "—", "a withheld client was totalled as a figure");
    assert.equal(attention[3], "—", "a withheld client was totalled as a figure");
  });

  test.it("re-totals to exactly the visible client when a search narrows to one", async function () {
    const page = await openRoster();
    const search = page.root.querySelector("[data-reports-client-search]");
    search.value = "bravo";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.deepEqual(visibleNames(page), ["Bravo Logistics"]);

    // Bravo alone: 128,400 over 46 = 2,791. NOT the roster's 164,200 / 68.
    const row = foot(page);
    assert.match(row.join(" "), /128,400/, "the total still counts hidden rows");
    assert.ok(!row.join(" ").includes("164,200"), "the total still counts hidden rows");
    assert.match(row.join(" "), /2,791/);
    assert.match(row.join(" "), /\b46\b/);
  });

  test.it("says the total is over the visible rows, and only while it is", async function () {
    const page = await openRoster();
    const t = (k, p) => page.sandbox.MUREO.t(k, p);

    // Unfiltered: the plain roster label, counting every client.
    assert.equal(foot(page)[0], t("dashboard.reports_roster_total", { n: 3 }));

    const search = page.root.querySelector("[data-reports-client-search]");
    search.value = "bravo";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.equal(foot(page)[0], t("dashboard.reports_roster_total_shown", { n: 1 }));
    assert.notEqual(
      t("dashboard.reports_roster_total_shown", { n: 1 }),
      t("dashboard.reports_roster_total", { n: 1 }),
      "the two labels are the same string, so this test proves nothing"
    );

    // Cleared: back to the whole roster, and back to the plain label.
    search.value = "";
    search.dispatchEvent({ type: "input" });
    await settle();
    assert.equal(foot(page)[0], t("dashboard.reports_roster_total", { n: 3 }));
    assert.match(foot(page).join(" "), /164,200/);
  });

  test.it("survives a re-sort with the filter still on", async function () {
    // The rows are rebuilt on every sort, so the totals row is too — and the
    // filter is re-applied over the new nodes. If the re-total ran against
    // the old <tbody> this would silently go back to the full roster.
    const page = await openRoster();
    const search = page.root.querySelector("[data-reports-client-search]");
    search.value = "bravo";
    search.dispatchEvent({ type: "input" });
    await settle();

    sortHeader(page, "spend").click();
    await settle();

    assert.deepEqual(visibleNames(page), ["Bravo Logistics"]);
    assert.match(foot(page).join(" "), /128,400/, "the re-sort lost the filtered total");
    assert.ok(!foot(page).join(" ").includes("164,200"));
  });
});

// ---------------------------------------------------------------------
// A metric's name fits the space it is given
// ---------------------------------------------------------------------

test.describe("card KPI labels do not break mid-word", function () {
  test.it("uses the short conversions label inside a client card", async function () {
    // A card cell is a third of a card wide. Japanese has no spaces, so the
    // browser wrapped the long name wherever it liked — "コンバージョ / ン",
    // which reads as a typo rather than as a wrap.
    const page = await openRoster();
    viewButton(page, "cards").click();
    await settle();
    const labels = page.root
      .querySelector("[data-reports-clients]")
      .querySelectorAll(".reports-client-kpi-label")
      .map((el) => el.textContent);
    const t = (k) => page.sandbox.MUREO.t(k);
    assert.ok(
      labels.includes(t("dashboard.reports_kpi_conversions_short")),
      "no card used the short label: " + labels.join(" | ")
    );
    assert.ok(
      !labels.includes(t("dashboard.reports_kpi_conversions")),
      "a card still uses the long label: " + labels.join(" | ")
    );
  });

  test.it("keeps the full name on the table's column header", async function () {
    // The column has a whole column's width. Shortening it there would be
    // abbreviating for no reason.
    const page = await openRoster();
    const header = sortHeader(page, "conversions");
    assert.match(
      header.textContent,
      new RegExp(page.sandbox.MUREO.t("dashboard.reports_kpi_conversions"))
    );
  });

  test.it("forbids the label wrapping at all, whatever it says", async function () {
    // The short label is what makes it fit today; this is what stops a
    // future string quietly doing the same thing again.
    const page = await openRoster();
    viewButton(page, "cards").click();
    await settle();
    const label = page.root
      .querySelector("[data-reports-clients]")
      .querySelector(".reports-client-kpi-label");
    const ws = cascade(label, "white-space");
    assert.ok(ws, "nothing declares white-space on a card KPI label");
    assert.equal(ws.value, "nowrap", "won by: " + ws.selector);
  });
});
