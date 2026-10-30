// The hint under a plugin OAuth card's callback URL input (#828).
//
// Run with:  node --test tests/js/*.test.js
//
// The generic hint tells the operator to register the callback URL in the
// provider's developer console. For a brokered flow the authorization server
// redirects to the broker's own callback and the loopback URL is only the
// second hop, so that advice is wrong. The list endpoint therefore carries
// the provider's choice as `oauth.callback_hint`:
//
//   absent / null -> the generic i18n hint, unchanged;
//   a string      -> that text, verbatim, instead of the generic one;
//   ""            -> no hint row at all.
//
// Driven against the real dashboard_plugins.js. The harness's MUREO.t returns
// the key it was given, so the generic hint reads as its i18n key.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle } = require("./dom_harness.js");

const GENERIC_KEY = "dashboard.plugin_oauth_callback_hint";
const CUSTOM_HINT = "Nothing to register: <b>the broker</b> handles the redirect.";

const FIELDS = [
  { key: "client_id", display_name: "Client ID", secret: false },
  { key: "client_secret", display_name: "Client Secret", secret: true },
  { key: "refresh_token", display_name: "Refresh Token", secret: true },
];

function plugin(name, extraOauth) {
  return {
    provider_name: name,
    display_name: name,
    fields: FIELDS,
    oauth: Object.assign(
      {
        target_field: "refresh_token",
        client_id_field: "client_id",
        client_secret_field: "client_secret",
      },
      extraOauth
    ),
  };
}

/** The <label> holding the callback URL input of `name`'s tab panel. */
function callbackLabel(container, name) {
  const panel = container.querySelector('[data-plugin-panel="' + name + '"]');
  assert.ok(panel, "no panel rendered for " + name);
  const input = panel.querySelectorAll("input").find(function (el) {
    return el.name === "oauth_callback_url";
  });
  assert.ok(input, "no callback URL input on " + name);
  return input.parentNode;
}

function hints(label) {
  return label.querySelectorAll("small").filter(function (el) {
    return el.classList.contains("field-hint");
  });
}

test.describe("plugin OAuth callback hint", function () {
  let container = null;
  test.before(async function () {
    const page = loadDashboardPage({
      "/api/credentials/plugins": {
        plugins: [
          plugin("absent_hint", {}),
          plugin("null_hint", { callback_hint: null }),
          plugin("custom_hint", { callback_hint: CUSTOM_HINT }),
          plugin("empty_hint", { callback_hint: "" }),
        ],
      },
    });
    await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
    await settle();
    container = page.root.querySelector(
      "[data-dashboard-plugin-credentials-list]"
    );
  });

  test.it("keeps the generic hint when the provider sets none", function () {
    for (const name of ["absent_hint", "null_hint"]) {
      const rows = hints(callbackLabel(container, name));
      assert.equal(rows.length, 1, name + " should have one hint row");
      assert.equal(rows[0].textContent, GENERIC_KEY);
    }
  });

  test.it("shows the provider's hint verbatim instead of the generic one", function () {
    const label = callbackLabel(container, "custom_hint");
    const rows = hints(label);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].textContent, CUSTOM_HINT);
    assert.ok(!label.textContent.includes(GENERIC_KEY), "generic hint still shown");
  });

  test.it("renders the provider's hint as text, never as markup", function () {
    const [row] = hints(callbackLabel(container, "custom_hint"));
    assert.equal(row.querySelector("b"), null, "hint was parsed as HTML");
    assert.equal(row.childNodes.length, 1);
    assert.equal(row.childNodes[0].nodeType, 3);
  });

  test.it("renders no hint row when the provider sets an empty hint", function () {
    const label = callbackLabel(container, "empty_hint");
    assert.equal(hints(label).length, 0);
    assert.ok(!label.textContent.includes(GENERIC_KEY), "generic hint still shown");
    // The input itself is still there.
    assert.ok(label.querySelector("input"));
  });
});
