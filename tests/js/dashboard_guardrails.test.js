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

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle, isVisible } = require("./dom_harness.js");

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

async function openGuardrails(clients) {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: clients || [], can_archive: false },
    "/api/reports/summary": {},
    "/api/strategy/currency": CURRENCY_BODY,
  });
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

  test.it("hides the client row on a single-workspace install", async function () {
    const page = await openGuardrails([]);
    const row = page.root.querySelector("[data-guardrails-client-row]");
    assert.equal(isVisible(row), false);
  });

  test.it("shows the client picker when there is more than one", async function () {
    const page = await openGuardrails([
      { slug: "acme", name: "Acme", active: true, archived: false },
      { slug: "globex", name: "Globex", active: false, archived: false },
    ]);
    const row = page.root.querySelector("[data-guardrails-client-row]");
    assert.equal(isVisible(row), true);
    const select = page.root.querySelector("[data-guardrails-client]");
    assert.deepEqual(
      select.children.map((o) => o.getAttribute("value")),
      ["acme", "globex"]
    );
    assert.deepEqual(
      select.children.map((o) => o.textContent),
      ["Acme", "Globex"]
    );
    assert.equal(select.value, "acme");
  });
});

test.describe("saving", function () {
  test.it("posts the chosen code and no client on OSS", async function () {
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
    assert.equal(posted[0].url, "/api/strategy/currency");
    assert.equal(posted[0].body.currency, "JPY");
    assert.equal(posted[0].body.client, null);
  });

  test.it("posts the selected client when the picker is shown", async function () {
    const page = await openGuardrails([
      { slug: "acme", name: "Acme", active: true, archived: false },
      { slug: "globex", name: "Globex", active: false, archived: false },
    ]);
    const posted = [];
    page.sandbox.MUREO.postJson = function (url, body) {
      posted.push(body);
      return Promise.resolve({ ok: true, body: { status: "ok", currency: "EUR" } });
    };
    page.root.querySelector("[data-guardrails-client]").value = "globex";
    page.root.querySelector("[data-guardrails-save]").click();
    await settle();
    assert.equal(posted.length, 1);
    assert.equal(posted[0].currency, "EUR");
    assert.equal(posted[0].client, "globex");
  });

  test.it("says so when the saved code is one mureo does not know", async function () {
    const page = loadDashboardPage({
      "/api/reports/clients": { clients: [], can_archive: false },
      "/api/reports/summary": {},
      "/api/strategy/currency": Object.assign({}, CURRENCY_BODY, {
        currency: null,
        raw_value: "XYZ",
      }),
    });
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    openSection(page);
    const result = page.root.querySelector("[data-guardrails-result]");
    assert.equal(result.textContent, "dashboard.guardrails_unknown_code|code=XYZ");
    assert.equal(currencySelect(page).value, "");
  });
});
