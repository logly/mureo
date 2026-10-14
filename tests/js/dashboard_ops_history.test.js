// The ops history switch (#848): what the card shows and what Save sends.
//
// Run with:  node --test tests/js/*.test.js
//
// Turning this on makes every later change require a reason and an
// expected effect, so the two things pinned are that the select shows the
// value STATE.json holds, and that Save posts a real boolean and nothing
// that names a client.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const ENDPOINT = "/api/settings/ops_history";

const BODY = {
  status: "ok",
  client: null,
  path: "/w/STATE.json",
  enabled: true,
  exists: true,
};

function load(body) {
  return loadDashboardPage({
    "/api/reports/clients": { clients: [], can_archive: false },
    "/api/reports/summary": {},
    "/api/settings/ops_history": body || BODY,
  });
}

async function open(body) {
  const page = load(body);
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  return page;
}

function select(page) {
  return page.root.querySelector("[data-ops-history-enabled]");
}

function requests(page) {
  return page.requests.filter((url) => url.startsWith(ENDPOINT));
}

test.describe("the ops history card", function () {
  test.it("shows the value STATE.json holds", async function () {
    assert.equal(select(await open()).value, "on");
    const off = await open(Object.assign({}, BODY, { enabled: false }));
    assert.equal(select(off).value, "off");
  });

  test.it("names the file it writes to", async function () {
    const page = await open();
    const hint = page.root.querySelector("[data-ops-history-path]");
    assert.equal(hint.textContent, "dashboard.ops_history_path|path=/w/STATE.json");
  });

  test.it("reads the active workspace once, naming no client", async function () {
    assert.deepEqual(requests(await open()), [ENDPOINT]);
  });

  test.it("says so when the setting cannot be read", async function () {
    const page = await open({ error: "read_failed" });
    const result = page.root.querySelector("[data-ops-history-result]");
    assert.equal(result.textContent, "dashboard.ops_history_load_failed");
  });

  test.it("does nothing when the server served no card", async function () {
    const page = load();
    const card = page.root.querySelector("[data-dashboard-ops-history]");
    assert.ok(card, "the fixture page should carry the card to remove");
    card.parentNode.removeChild(card);
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    assert.deepEqual(requests(page), []);
  });
});

test.describe("saving the switch", function () {
  test.it("posts a boolean and redraws from the answer", async function () {
    const page = await open(Object.assign({}, BODY, { enabled: false }));
    const posted = [];
    page.sandbox.MUREO.postJson = function (url, body) {
      posted.push({ url: url, body: body });
      return Promise.resolve({
        ok: true,
        body: Object.assign({}, BODY, { enabled: true }),
      });
    };
    select(page).value = "on";
    page.root.querySelector("[data-ops-history-save]").click();
    await settle();
    assert.equal(posted.length, 1);
    assert.equal(posted[0].url, ENDPOINT);
    assert.equal(posted[0].body.enabled, true);
    assert.deepEqual(Object.keys(posted[0].body), ["enabled"]);
    const result = page.root.querySelector("[data-ops-history-result]");
    assert.equal(result.textContent, "dashboard.ops_history_saved_on");
    assert.equal(select(page).value, "on");
  });

  test.it("keeps the stored value when the write fails", async function () {
    const page = await open(Object.assign({}, BODY, { enabled: false }));
    page.sandbox.MUREO.postJson = function () {
      return Promise.resolve({ ok: false, body: { error: "write_failed" } });
    };
    select(page).value = "on";
    page.root.querySelector("[data-ops-history-save]").click();
    await settle();
    const result = page.root.querySelector("[data-ops-history-result]");
    assert.equal(result.textContent, "dashboard.ops_history_save_failed");
  });
});
