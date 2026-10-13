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

// ----- every other rule (#843) -----------------------------------------
//
// Below the currency select the card lists every `## Guardrails` field the
// server describes. Three things can be silently wrong and are pinned:
// an undeclared rule must SAY "not set" rather than show a blank cell;
// Save must send only what the operator changed (so one edit writes one
// bullet), with an emptied field as a removal rather than a `0`; and what
// is shown after a save must be what the SERVER answered, not what was
// typed.

const GUARDRAILS_ENDPOINT = "/api/strategy/guardrails";

function fieldRow(key, kind, overrides) {
  return Object.assign(
    {
      key: key,
      kind: kind,
      unit: null,
      min: null,
      max: null,
      label: "label of " + key,
      desc: "desc of " + key,
      value: null,
      raw: null,
      recognised: true,
    },
    overrides || {}
  );
}

const FIELDS_BODY = {
  status: "ok",
  client: null,
  path: "/w/STRATEGY.md",
  exists: true,
  guardrails_present: true,
  fields: [
    fieldRow("max_total_daily_budget", "money", {
      unit: "currency",
      min: 0,
      value: 900,
      raw: "900",
    }),
    fieldRow("max_daily_budget_per_campaign", "money", {
      unit: "currency",
      min: 0,
      value: null,
      raw: "lots",
      recognised: false,
    }),
    fieldRow("max_delivery_share_removed_pct", "percent", {
      unit: "%",
      min: 0,
      max: 100,
    }),
    fieldRow("currency", "currency", { value: "EUR", raw: "EUR" }),
    fieldRow("blocked_operations", "string_set", {
      value: ["a_tool", "b_tool"],
      raw: "a_tool, b_tool",
    }),
    fieldRow("block_learning_resets", "bool"),
    fieldRow("exclusion_impact_window_days", "integer_days", {
      unit: "days",
      min: 1,
      max: 365,
    }),
  ],
};

function loadRules(fieldsBody) {
  return loadDashboardPage({
    "/api/reports/clients": { clients: ROSTER, can_archive: false },
    "/api/reports/summary": {},
    "/api/strategy/currency": CURRENCY_BODY,
    "/api/strategy/guardrails": fieldsBody || FIELDS_BODY,
  });
}

async function openRules(fieldsBody) {
  const page = loadRules(fieldsBody);
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  openSection(page);
  return page;
}

function row(page, key) {
  return page.root
    .querySelectorAll("[data-guardrails-row]")
    .find((el) => el.getAttribute("data-guardrails-row") === key);
}

function control(page, key) {
  return row(page, key).querySelector("[data-guardrails-field]");
}

function stateText(page, key) {
  return row(page, key).querySelector("[data-guardrails-state]").textContent;
}

function fieldsResult(page) {
  return page.root.querySelector("[data-guardrails-fields-result]").textContent;
}

function recordPosts(page, answer) {
  const posted = [];
  page.sandbox.MUREO.postJson = function (url, body) {
    posted.push({ url: url, body: JSON.parse(JSON.stringify(body)) });
    return Promise.resolve(answer);
  };
  return posted;
}

function clickSaveRules(page) {
  page.root.querySelector("[data-guardrails-fields-save]").click();
}

test.describe("the rules table", function () {
  test.it("lists every field but the currency, which has its own select", async function () {
    const page = await openRules();
    const keys = page.root
      .querySelectorAll("[data-guardrails-row]")
      .map((el) => el.getAttribute("data-guardrails-row"));
    assert.deepEqual(keys, [
      "max_total_daily_budget",
      "max_daily_budget_per_campaign",
      "max_delivery_share_removed_pct",
      "blocked_operations",
      "block_learning_resets",
      "exclusion_impact_window_days",
    ]);
  });

  test.it("names each rule from the UI catalog, not by its key", async function () {
    const page = loadRules();
    // A catalog that knows the field keys, so a hit is distinguishable
    // from the harness's echo (which app.js's t() returns on a miss).
    const echo = page.sandbox.MUREO.t;
    page.sandbox.MUREO.t = function (key, params) {
      return key.indexOf("guardrails.field.") === 0 ? "tr:" + key : echo(key, params);
    };
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    openSection(page);
    const target = row(page, "max_total_daily_budget");
    assert.equal(
      target.querySelector("[data-guardrails-label]").textContent,
      "tr:guardrails.field.max_total_daily_budget.label"
    );
    assert.equal(
      target.querySelector("[data-guardrails-desc]").textContent,
      "tr:guardrails.field.max_total_daily_budget.desc"
    );
  });

  test.it("falls back to the server's label on a catalog miss", async function () {
    const page = await openRules();
    const target = row(page, "max_total_daily_budget");
    assert.equal(
      target.querySelector("[data-guardrails-label]").textContent,
      "label of max_total_daily_budget"
    );
    assert.equal(
      target.querySelector("[data-guardrails-desc]").textContent,
      "desc of max_total_daily_budget"
    );
  });

  test.it("says 'not set' for an undeclared rule instead of a blank", async function () {
    const page = await openRules();
    assert.equal(
      stateText(page, "max_delivery_share_removed_pct"),
      "dashboard.guardrails_field_not_set"
    );
    assert.equal(control(page, "max_delivery_share_removed_pct").value, "");
    assert.equal(
      stateText(page, "block_learning_resets"),
      "dashboard.guardrails_field_not_set_off"
    );
    assert.equal(
      stateText(page, "exclusion_impact_window_days"),
      "dashboard.guardrails_field_not_set_default"
    );
  });

  test.it("fills in a declared value and shows it as written", async function () {
    const page = await openRules();
    assert.equal(control(page, "max_total_daily_budget").value, "900");
    assert.equal(
      stateText(page, "max_total_daily_budget"),
      "dashboard.guardrails_field_set|raw=900"
    );
    assert.equal(control(page, "blocked_operations").value, "a_tool, b_tool");
  });

  test.it("says a line it cannot read is being ignored", async function () {
    const page = await openRules();
    assert.equal(
      stateText(page, "max_daily_budget_per_campaign"),
      "dashboard.guardrails_field_ignored|raw=lots"
    );
    assert.equal(control(page, "max_daily_budget_per_campaign").value, "");
  });

  test.it("gives a number field its bounds", async function () {
    const page = await openRules();
    const input = control(page, "exclusion_impact_window_days");
    assert.equal(input.getAttribute("type"), "number");
    assert.equal(input.getAttribute("min"), "1");
    assert.equal(input.getAttribute("max"), "365");
    assert.equal(input.getAttribute("step"), "1");
  });

  test.it("offers not set / on / off for a switch", async function () {
    const page = await openRules();
    const select = control(page, "block_learning_resets");
    assert.deepEqual(
      select.children.map((o) => o.getAttribute("value")),
      ["", "true", "false"]
    );
  });

  test.it("asks for the rules once, naming no client", async function () {
    const page = await openRules();
    assert.deepEqual(
      page.requests.filter((url) => url.startsWith(GUARDRAILS_ENDPOINT)),
      [GUARDRAILS_ENDPOINT]
    );
  });

  test.it("asks for nothing when the server served no card", async function () {
    const page = loadRules();
    const card = page.root.querySelector("[data-dashboard-guardrails]");
    card.parentNode.removeChild(card);
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    assert.deepEqual(
      page.requests.filter((url) => url.startsWith(GUARDRAILS_ENDPOINT)),
      []
    );
  });
});

test.describe("saving the rules", function () {
  test.it("sends only the rule that changed", async function () {
    const page = await openRules();
    const posted = recordPosts(page, { ok: true, body: FIELDS_BODY });
    control(page, "max_total_daily_budget").value = "1200";
    clickSaveRules(page);
    await settle();
    assert.equal(posted.length, 1);
    assert.equal(posted[0].url, GUARDRAILS_ENDPOINT);
    assert.deepEqual(posted[0].body, {
      set: { max_total_daily_budget: "1200" },
      clear: [],
    });
  });

  test.it("sends an emptied rule as a removal, never as zero", async function () {
    const page = await openRules();
    const posted = recordPosts(page, { ok: true, body: FIELDS_BODY });
    control(page, "max_total_daily_budget").value = "";
    clickSaveRules(page);
    await settle();
    assert.deepEqual(posted[0].body, {
      set: {},
      clear: ["max_total_daily_budget"],
    });
  });

  test.it("sends nothing when nothing changed", async function () {
    const page = await openRules();
    const posted = recordPosts(page, { ok: true, body: FIELDS_BODY });
    clickSaveRules(page);
    await settle();
    assert.equal(posted.length, 0);
    assert.equal(fieldsResult(page), "dashboard.guardrails_fields_unchanged");
  });

  test.it("redraws from the server's answer, not from what was typed", async function () {
    const page = await openRules();
    const answer = JSON.parse(JSON.stringify(FIELDS_BODY));
    answer.fields[0].value = 2000;
    answer.fields[0].raw = "2000";
    recordPosts(page, { ok: true, body: answer });
    control(page, "max_total_daily_budget").value = "1200";
    clickSaveRules(page);
    await settle();
    assert.equal(control(page, "max_total_daily_budget").value, "2000");
    assert.equal(
      stateText(page, "max_total_daily_budget"),
      "dashboard.guardrails_field_set|raw=2000"
    );
    assert.equal(fieldsResult(page), "dashboard.guardrails_fields_saved|count=1");
  });

  test.it("names the rule the server refused, and why", async function () {
    const page = await openRules();
    recordPosts(page, {
      ok: false,
      status: 400,
      body: { error: "out_of_range", field: "exclusion_impact_window_days" },
    });
    control(page, "exclusion_impact_window_days").value = "999";
    clickSaveRules(page);
    await settle();
    assert.equal(
      fieldsResult(page),
      "dashboard.guardrails_fields_refused" +
        "|label=label of exclusion_impact_window_days" +
        ",reason=dashboard.guardrails_error_out_of_range"
    );
    // The typed value is left in place for the operator to correct.
    assert.equal(control(page, "exclusion_impact_window_days").value, "999");
  });
});

test.describe("saving the currency next to an edited rule", function () {
  test.it("leaves the rules table and its typed values alone", async function () {
    // The currency select and the rules table are saved by two buttons.
    // Saving the first must not throw away an edit in the second.
    const page = await openRules();
    recordPosts(page, { ok: true, body: { status: "ok", currency: "JPY" } });
    control(page, "max_total_daily_budget").value = "1200";
    currencySelect(page).value = "JPY";
    page.root.querySelector("[data-guardrails-save]").click();
    await settle();
    assert.equal(control(page, "max_total_daily_budget").value, "1200");
    assert.deepEqual(
      page.requests.filter((url) => url.startsWith(GUARDRAILS_ENDPOINT)),
      [GUARDRAILS_ENDPOINT]
    );
    // ...while the currency side is re-read from the server.
    assert.deepEqual(currencyRequests(page), [CURRENCY_ENDPOINT, CURRENCY_ENDPOINT]);
  });
});

test.describe("a number the browser could not read", function () {
  test.it("is refused in place, not sent as a removal", async function () {
    // An <input type="number"> holding text it cannot parse reports an
    // EMPTY value — which, unguarded, would read as "clear this rule".
    const page = await openRules();
    const posted = recordPosts(page, { ok: true, body: FIELDS_BODY });
    const input = control(page, "max_total_daily_budget");
    input.value = "";
    input.validity = { badInput: true };
    clickSaveRules(page);
    await settle();
    assert.equal(posted.length, 0);
    assert.equal(
      fieldsResult(page),
      "dashboard.guardrails_fields_refused" +
        "|label=label of max_total_daily_budget" +
        ",reason=dashboard.guardrails_error_invalid_value"
    );
  });
});
