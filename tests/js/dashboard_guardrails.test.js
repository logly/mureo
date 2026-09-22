// The Guardrails card: what the operator sees, and what Save sends (#786).
//
// Run with:  node --test tests/js/*.test.js
//
// This is a money control — the code it writes decides whether a Meta
// `daily_budget` of 25000 is read as €250.00 or as €25,000 — so the two
// things asserted here are the two that can silently be wrong: which option
// is SELECTED when the card opens (a dropdown that lost the stored value
// invites an operator to "fix" it to something else), and what the Save
// button actually posts.
//
// Since #790 the card knows nothing about clients. It reads and writes the
// ACTIVE workspace's STRATEGY.md and nothing else, and a multi-client
// backend is served no card at all — the markup is stripped before the
// document leaves the server (`mureo/web/app_html.py`). So two more things
// are pinned here: that nothing this module sends names a client, and that
// a page served WITHOUT the card asks the currency endpoint for nothing.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const CURRENCY_ENDPOINT = "/api/strategy/currency";

const CURRENCY_BODY = {
  status: "ok",
  currency: "EUR",
  raw_value: "EUR",
  options: [
    { code: "EUR", minor_units: 100 },
    { code: "JPY", minor_units: 1 },
  ],
  path: "/w/STRATEGY.md",
  guardrails_present: true,
  exists: true,
};

// A roster of two: the exact backend the deleted picker existed for. Every
// test below runs against it, so each one also says that the card no longer
// changes shape or destination when a client registry is present.
const ROSTER = [
  { slug: "acme", name: "Acme", active: true, archived: false },
  { slug: "globex", name: "Globex", active: false, archived: false },
];

function loadGuardrails(currencyBody) {
  return loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: false },
    "/api/reports/summary": {},
    "/api/strategy/currency": currencyBody || CURRENCY_BODY,
  });
}

async function openGuardrails(currencyBody) {
  const page = loadGuardrails(currencyBody);
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  // The dashboard opens on Setup, and isVisible() walks the ancestors — so
  // without this every question about the card answers "hidden" for a
  // reason that has nothing to do with the card. The card is a sub-card of
  // Advanced, not a nav entry of its own, so Advanced is what opens it.
  openSection(page);
  return page;
}

function openSection(page) {
  page.root
    .querySelectorAll("[data-dashboard-nav]")
    .find((el) => el.getAttribute("data-dashboard-nav") === "advanced")
    .click();
}

function currencySelect(page) {
  return page.root.querySelector("[data-guardrails-currency]");
}

function currencyRequests(page) {
  return page.requests.filter((url) => url.startsWith(CURRENCY_ENDPOINT));
}

test.describe("the Guardrails card", function () {
  test.it("offers 'not set' plus every code the server listed", async function () {
    const page = await openGuardrails();
    const options = currencySelect(page).children;
    assert.equal(options.length, 3);
    assert.equal(options[0].getAttribute("value"), "");
    assert.equal(options[0].textContent, "dashboard.guardrails_not_set");
    assert.deepEqual(
      options.slice(1).map((o) => o.getAttribute("value")),
      ["EUR", "JPY"]
    );
  });

  test.it("selects the code STRATEGY.md already carries", async function () {
    const page = await openGuardrails();
    assert.equal(currencySelect(page).value, "EUR");
  });

  test.it("marks a zero-decimal currency as whole units", async function () {
    const page = await openGuardrails();
    const jpy = currencySelect(page).children[2];
    assert.equal(jpy.getAttribute("value"), "JPY");
    assert.ok(
      jpy.textContent.startsWith("JPY"),
      "expected the code first, got " + jpy.textContent
    );
    assert.ok(
      jpy.textContent.endsWith("dashboard.guardrails_zero_decimal"),
      "expected the whole-units suffix, got " + jpy.textContent
    );
    // ...and the offset-100 one says nothing extra.
    assert.equal(currencySelect(page).children[1].textContent, "EUR");
  });

  test.it("names the file it writes to", async function () {
    const page = await openGuardrails();
    const hint = page.root.querySelector("[data-guardrails-path]");
    assert.equal(hint.textContent, "dashboard.guardrails_path|path=/w/STRATEGY.md");
  });

  test.it("reads the active workspace, naming no client", async function () {
    // Replaces the picker cases: the card used to ask
    // /api/reports/clients first and hang a `client=` on this URL once the
    // roster had two entries. With that same roster served, it asks once,
    // for the one file the page is about (#790).
    const page = await openGuardrails();
    assert.deepEqual(currencyRequests(page), [CURRENCY_ENDPOINT]);
  });

  test.it("shows no client control, roster or no roster", async function () {
    const page = await openGuardrails();
    assert.equal(page.root.querySelector("[data-guardrails-client-row]"), null);
    assert.equal(page.root.querySelector("[data-guardrails-client]"), null);
  });

  test.it("does nothing when the server served no card", async function () {
    // A multi-client backend gets the markup stripped server-side, so the
    // whole module has to be inert on a page without it — not throw, and
    // above all not read a file the operator is not looking at.
    const page = loadGuardrails();
    const card = page.root.querySelector("[data-dashboard-guardrails]");
    assert.ok(card, "the fixture page should carry the card to remove");
    card.parentNode.removeChild(card);
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    openSection(page);
    assert.deepEqual(currencyRequests(page), []);
  });
});

test.describe("saving", function () {
  test.it("posts the chosen code and names no client", async function () {
    // dom_harness's MUREO.postJson is a bare resolved stub that records
    // nothing, so the test installs a recording one over it.
    const page = await openGuardrails();
    const posted = [];
    page.sandbox.MUREO.postJson = function (url, body) {
      posted.push({ url: url, body: body });
      return Promise.resolve({ ok: true, body: { status: "ok", currency: "JPY" } });
    };
    currencySelect(page).value = "JPY";
    page.root.querySelector("[data-guardrails-save]").click();
    await settle();
    // Compared field by field: the recorded object was built inside the
    // page's vm realm, so deepEqual would fail on the prototype alone.
    assert.equal(posted.length, 1);
    assert.equal(posted[0].url, CURRENCY_ENDPOINT);
    assert.equal(posted[0].body.currency, "JPY");
    // Not "client: null" — the card has no client to name at all (#790).
    assert.deepEqual(Object.keys(posted[0].body), ["currency"]);
  });

  test.it("says so when the saved code is one mureo does not know", async function () {
    const page = await openGuardrails(
      Object.assign({}, CURRENCY_BODY, { currency: null, raw_value: "XYZ" })
    );
    const result = page.root.querySelector("[data-guardrails-result]");
    assert.equal(result.textContent, "dashboard.guardrails_unknown_code|code=XYZ");
    assert.equal(currencySelect(page).value, "");
  });
});
