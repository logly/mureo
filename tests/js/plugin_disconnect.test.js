// The Disconnect button on a plugin OAuth card (#970).
//
// Run with:  node --test tests/js/*.test.js
//
// A card whose OAuth token is stored offers Disconnect: after a confirm it
// POSTs /api/credentials/plugins/<name>/disconnect, which removes the
// provider's saved credentials (revoking the token first when the provider
// supports it), then re-renders the section. A card with no stored token
// has nothing to disconnect, so it shows no button. A "noop" answer (the
// section was already gone) gets a neutral toast instead of the success one.
//
// Driven against the real dashboard_plugins.js + plugin_disconnect.js. The
// harness's MUREO.t returns the key it was given, so text reads as its key.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const LIST_URL = "/api/credentials/plugins";

function plugin(name, configured) {
  return {
    provider_name: name,
    display_name: name,
    fields: [
      { key: "client_id", display_name: "Client ID", secret: false },
      { key: "client_secret", display_name: "Client Secret", secret: true },
      {
        key: "refresh_token",
        display_name: "Refresh Token",
        secret: true,
        configured: configured,
      },
    ],
    oauth: {
      target_field: "refresh_token",
      client_id_field: "client_id",
      client_secret_field: "client_secret",
    },
  };
}

/** Render the section with one connected and one fresh provider, and record
 * every postJson URL and toast instead of sending or showing them. A
 * successful POST answers `{status: options.status || "ok"}`. */
async function renderPage(options) {
  const page = loadDashboardPage({
    [LIST_URL]: { plugins: [plugin("linked_ads", true), plugin("fresh_ads", false)] },
  });
  const posted = [];
  const toasts = [];
  page.sandbox.MUREO.postJson = function (url) {
    posted.push(url);
    const body = options.ok
      ? { status: options.status || "ok", provider: "linked_ads" }
      : { error: "internal_error" };
    return Promise.resolve({ ok: options.ok, status: options.ok ? 200 : 500, body });
  };
  page.sandbox.MUREO.confirmAction = function () {
    return Promise.resolve(options.confirm);
  };
  page.sandbox.MUREO.toast = function (message, kind) {
    toasts.push([message, kind]);
  };
  await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
  await settle();
  return { page, posted, toasts };
}

function disconnectButtons(page, name) {
  const panel = page.root.querySelector('[data-plugin-panel="' + name + '"]');
  assert.ok(panel, "no panel rendered for " + name);
  return panel.querySelectorAll("[data-plugin-disconnect]");
}

function listFetches(page) {
  return page.requests.filter(function (url) {
    return url === LIST_URL;
  }).length;
}

test.describe("plugin OAuth Disconnect button", function () {
  test.it("is offered only when the token is stored", async function () {
    const { page } = await renderPage({ ok: true, confirm: true });
    const linked = disconnectButtons(page, "linked_ads");
    assert.equal(linked.length, 1);
    assert.equal(linked[0].getAttribute("data-plugin-disconnect"), "linked_ads");
    assert.equal(linked[0].textContent, "dashboard.plugin_oauth_disconnect");
    assert.equal(linked[0].type, "button", "must not submit the Authenticate form");
    assert.equal(disconnectButtons(page, "fresh_ads").length, 0);
  });

  test.it("POSTs the provider's disconnect route and re-renders", async function () {
    const { page, posted, toasts } = await renderPage({ ok: true, confirm: true });
    const before = listFetches(page);
    disconnectButtons(page, "linked_ads")[0].click();
    await settle();
    assert.deepEqual(posted, ["/api/credentials/plugins/linked_ads/disconnect"]);
    assert.deepEqual(toasts, [["dashboard.plugin_oauth_disconnected", "success"]]);
    assert.equal(listFetches(page), before + 1, "the section was not re-rendered");
  });

  test.it("shows a neutral toast when nothing was stored", async function () {
    const { page, toasts } = await renderPage({ ok: true, confirm: true, status: "noop" });
    const before = listFetches(page);
    disconnectButtons(page, "linked_ads")[0].click();
    await settle();
    assert.deepEqual(toasts, [["dashboard.plugin_oauth_disconnect_noop", "info"]]);
    assert.equal(listFetches(page), before + 1, "the section was not re-rendered");
  });

  test.it("sends nothing when the confirm is declined", async function () {
    const { page, posted, toasts } = await renderPage({ ok: true, confirm: false });
    const before = listFetches(page);
    disconnectButtons(page, "linked_ads")[0].click();
    await settle();
    assert.deepEqual(posted, []);
    assert.deepEqual(toasts, []);
    assert.equal(listFetches(page), before);
  });

  test.it("shows the failure toast and re-enables the button", async function () {
    const { page, posted, toasts } = await renderPage({ ok: false, confirm: true });
    const button = disconnectButtons(page, "linked_ads")[0];
    button.click();
    await settle();
    assert.equal(posted.length, 1);
    assert.deepEqual(toasts, [["dashboard.plugin_oauth_disconnect_failed", "error"]]);
    assert.equal(button.disabled, false);
  });

  test.it("runs the caller's onStored after a disconnect", async function () {
    // The setup wizard builds the card with an onStored that refreshes its
    // own step; a disconnect must reach it as a consent or Save does.
    const { page } = await renderPage({ ok: true, confirm: true });
    let stored = 0;
    const card = page.sandbox.MUREO_DASHBOARD_PLUGINS.buildPluginCredentialsForm(
      plugin("linked_ads", true),
      function () {
        stored += 1;
      }
    );
    const before = listFetches(page);
    card.querySelectorAll("[data-plugin-disconnect]")[0].click();
    await settle();
    assert.equal(stored, 1);
    assert.equal(listFetches(page), before + 1, "the section was not re-rendered");
  });
});
