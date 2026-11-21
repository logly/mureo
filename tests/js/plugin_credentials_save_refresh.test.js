// A provider's manual credential form shows the stored state right after
// Save (#1025).
//
// Run with:  node --test tests/js/*.test.js
//
// The ✓ / ✗ mark and the placeholder of a secret field are computed from the
// descriptor the form was built with. A successful Save used to clear the
// typed secret and stop there, so a value that was just stored still read
// "Not set" until the section was rendered again. A successful Save now reads
// /api/credentials/plugins again and rebuilds the section, keeping the chosen
// tab; a failed Save changes nothing.
//
// Driven against the real dashboard_plugins.js. The harness's MUREO.t returns
// the key it was given, so assertions are on i18n keys and class names.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const LIST_URL = "/api/credentials/plugins";
const SAVE_URL = "/api/credentials/plugins/save";

function plugin(name, configured) {
  return {
    provider_name: name,
    display_name: name,
    fields: [
      {
        key: name + "_api_key",
        display_name: "API Key",
        secret: true,
        required: true,
        configured: configured,
      },
    ],
  };
}

/**
 * Render the section for `names`, all unset. `state.stored` lists the
 * providers the descriptor route reports as configured, so a test can flip
 * a provider to stored before the refetch. `saveAnswer` is what postJson
 * resolves to for the save route.
 */
async function renderPage(names, saveAnswer) {
  const state = { stored: [] };
  const page = loadDashboardPage({
    [LIST_URL]: function () {
      return {
        plugins: names.map(function (name) {
          return plugin(name, state.stored.includes(name));
        }),
      };
    },
  });
  const posted = [];
  const toasts = [];
  page.sandbox.MUREO.postJson = function (url, body) {
    posted.push([url, body]);
    return Promise.resolve(saveAnswer);
  };
  page.sandbox.MUREO.toast = function (message, kind) {
    toasts.push([message, kind]);
  };
  await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
  await settle();
  return { page, state, posted, toasts };
}

function panel(page, name) {
  const found = page.root.querySelector('[data-plugin-panel="' + name + '"]');
  assert.ok(found, "no panel rendered for " + name);
  return found;
}

function secretInput(page, name) {
  const input = panel(page, name).querySelector('input[type="password"]');
  assert.ok(input, "no secret input in " + name);
  return input;
}

/** The <label> around `name`'s secret input. */
function secretLabel(page, name) {
  let node = secretInput(page, name).parentNode;
  while (node && node.tagName !== "LABEL") node = node.parentNode;
  assert.ok(node, "the secret input of " + name + " is not inside a <label>");
  return node;
}

function statusKeys(label) {
  return label
    .querySelectorAll("span")
    .map(function (el) {
      return el.getAttribute("data-i18n");
    })
    .filter(Boolean);
}

function assertConfigured(page, name) {
  const label = secretLabel(page, name);
  assert.ok(label.querySelector(".mark-ok"), "no ✓ after a successful save");
  assert.equal(label.querySelector(".mark-no"), null);
  assert.ok(statusKeys(label).includes("dashboard.credential_secret_configured"));
  assert.equal(
    secretInput(page, name).placeholder,
    "dashboard.plugin_credentials_secret_placeholder"
  );
}

function assertUnset(page, name) {
  const label = secretLabel(page, name);
  assert.ok(label.querySelector(".mark-no"), "the ✗ is gone");
  assert.equal(label.querySelector(".mark-ok"), null);
  assert.ok(statusKeys(label).includes("dashboard.credential_secret_unset"));
}

/** Type `value` into `name`'s secret and submit its form. */
async function typeAndSave(page, name, value) {
  secretInput(page, name).value = value;
  panel(page, name).querySelector("form").dispatchEvent({ type: "submit" });
  await settle();
}

function listFetches(page) {
  return page.requests.filter(function (url) {
    return url === LIST_URL;
  }).length;
}

function activeTab(page) {
  return page.root
    .querySelectorAll('[role="tab"]')
    .filter(function (tab) {
      return tab.classList.contains("is-active");
    })
    .map(function (tab) {
      return tab.getAttribute("data-plugin-tab");
    });
}

const SAVED = { ok: true, status: 200, body: { status: "ok" } };

test.describe("manual credential save", function () {
  test.it("shows the secret as configured once the save succeeds", async function () {
    const { page, state, posted, toasts } = await renderPage(["solo_ads"], SAVED);
    assertUnset(page, "solo_ads");
    state.stored.push("solo_ads");
    await typeAndSave(page, "solo_ads", "typed-secret");
    assert.equal(posted.length, 1);
    assert.equal(posted[0][0], SAVE_URL);
    assert.equal(posted[0][1].values.solo_ads_api_key, "typed-secret");
    assert.deepEqual(toasts, [["dashboard.plugin_credentials_saved", "success"]]);
    assertConfigured(page, "solo_ads");
    assert.equal(secretInput(page, "solo_ads").value, "");
  });

  test.it("keeps the chosen tab across the re-render", async function () {
    const { page, state } = await renderPage(["first_ads", "second_ads"], SAVED);
    page.root.querySelector('[data-plugin-tab="second_ads"]').click();
    assert.deepEqual(activeTab(page), ["second_ads"]);
    state.stored.push("second_ads");
    await typeAndSave(page, "second_ads", "typed-secret");
    assertConfigured(page, "second_ads");
    assert.deepEqual(activeTab(page), ["second_ads"]);
    assert.equal(panel(page, "second_ads").hidden, false);
    assert.equal(panel(page, "first_ads").hidden, true);
  });

  const FAILURES = {
    "a logical error": { ok: true, status: 200, body: { status: "error" } },
    "a non-2xx answer": { ok: false, status: 500, body: { error: "internal_error" } },
  };
  Object.keys(FAILURES).forEach(function (label) {
    test.it("changes nothing on " + label, async function () {
      const { page, state, toasts } = await renderPage(["solo_ads"], FAILURES[label]);
      const before = listFetches(page);
      state.stored.push("solo_ads");
      await typeAndSave(page, "solo_ads", "typed-secret");
      assert.equal(listFetches(page), before, "the section was read again");
      assert.deepEqual(toasts, [["dashboard.plugin_credentials_save_failed", "error"]]);
      assertUnset(page, "solo_ads");
      assert.equal(secretInput(page, "solo_ads").value, "typed-secret");
    });
  });

  test.it("clears the typed secret even when the refetch fails", async function () {
    const { page } = await renderPage(["solo_ads"], SAVED);
    const form = panel(page, "solo_ads").querySelector("form");
    const input = secretInput(page, "solo_ads");
    const realFetch = page.sandbox.fetch;
    let refetched = 0;
    page.sandbox.fetch = function (url) {
      if (String(url) !== LIST_URL) return realFetch(url);
      refetched += 1;
      return Promise.resolve({
        ok: false,
        status: 500,
        json: function () {
          return Promise.resolve({});
        },
      });
    };
    await typeAndSave(page, "solo_ads", "typed-secret");
    assert.equal(refetched, 1, "the section was not read again");
    assert.equal(input.value, "");
    const list = page.root.querySelector("[data-dashboard-plugin-credentials-list]");
    assert.ok(list.querySelectorAll("form").includes(form), "the old form left the page");
  });
});
