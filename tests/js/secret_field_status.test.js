// A secret credential field says whether a value is already stored.
//
// Run with:  node --test tests/js/*.test.js
//
// A secret never travels to the browser, so the input is always empty. Before
// this, a stored secret and a missing one differed only by placeholder text,
// and an operator could not tell at a glance which fields still needed a
// value. Each secret field now leads with the same ✓ / ✗ mark the Creative
// Studio keys use, followed by a short "Configured" / "Not set" status.
//
// Both renderers of provider-declared fields are driven here against the real
// files: the dashboard's plugin credential cards (dashboard_plugins.js) and
// the auth wizard's declarative slot (auth_wizards.js). Assertions are on
// i18n keys and class names — the harness's MUREO.t returns the key.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  loadDashboardPage,
  loadAuthWizardPage,
  settle,
} = require("./dom_harness.js");

const PROVIDER_PLACEHOLDER = "e.g. sk-...";

/** One field of each shape the status mark has to tell apart. */
const FIELDS = [
  {
    key: "stored_secret",
    display_name: "Stored Secret",
    secret: true,
    required: true,
    configured: true,
    placeholder: PROVIDER_PLACEHOLDER,
  },
  {
    key: "unset_secret",
    display_name: "Unset Secret",
    secret: true,
    required: false,
    configured: false,
  },
  {
    key: "unset_secret_with_hint",
    display_name: "Unset Secret With Placeholder",
    secret: true,
    required: false,
    configured: false,
    placeholder: PROVIDER_PLACEHOLDER,
  },
  {
    key: "plain_id",
    display_name: "Plain Id",
    secret: false,
    required: false,
    configured: true,
    value: "12345",
  },
];

function descriptor(providerName) {
  return {
    plugins: [
      {
        provider_name: providerName,
        display_name: "Example Provider",
        fields: FIELDS,
      },
    ],
  };
}

/** The <label> wrapping the input named `key`. */
function labelFor(host, key) {
  const input = host.querySelectorAll("input").find(function (el) {
    return el.name === key;
  });
  assert.ok(input, "no input rendered for " + key);
  let node = input.parentNode;
  while (node && node.tagName !== "LABEL") node = node.parentNode;
  assert.ok(node, "input " + key + " is not inside a <label>");
  return { label: node, input: input };
}

/** The i18n keys of every span in the label. */
function statusTexts(label) {
  return label
    .querySelectorAll("span")
    .map(function (el) {
      return el.getAttribute("data-i18n");
    })
    .filter(Boolean);
}

/** The four cases, asserted against whatever `host` the renderer filled. */
function assertSecretStatus(host) {
  test.it("marks a stored secret as configured and keeps the keep-current placeholder", function () {
    const { label, input } = labelFor(host(), "stored_secret");
    assert.ok(label.querySelector(".mark-ok"), "no ✓ on a configured secret");
    assert.equal(label.querySelector(".mark-no"), null);
    assert.equal(label.querySelector(".mark-ok").textContent, "✓");
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.ok(label.textContent.includes("Stored Secret *"), "required marker lost");
    assert.equal(
      input.placeholder,
      "dashboard.plugin_credentials_secret_placeholder"
    );
  });

  test.it("marks an unset secret as not set and says to enter a value", function () {
    const { label, input } = labelFor(host(), "unset_secret");
    assert.ok(label.querySelector(".mark-no"), "no ✗ on an unset secret");
    assert.equal(label.querySelector(".mark-ok"), null);
    assert.equal(label.querySelector(".mark-no").textContent, "✗");
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.equal(
      input.placeholder,
      "dashboard.plugin_credentials_secret_unset_placeholder"
    );
  });

  test.it("lets the provider's own placeholder win on an unset secret", function () {
    const { label, input } = labelFor(host(), "unset_secret_with_hint");
    assert.ok(label.querySelector(".mark-no"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.equal(input.placeholder, PROVIDER_PLACEHOLDER);
  });

  test.it("leaves a non-secret field without a mark", function () {
    const { label, input } = labelFor(host(), "plain_id");
    assert.equal(label.querySelector(".mark-ok"), null);
    assert.equal(label.querySelector(".mark-no"), null);
    assert.ok(!statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.ok(!statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.equal(input.value, "12345");
  });

  test.it("keeps data-i18n off every element that holds the mark", function () {
    // A locale switch overwrites the textContent of every [data-i18n]
    // element; one that contained the mark would lose it.
    const { label } = labelFor(host(), "stored_secret");
    let node = label.querySelector(".mark-ok");
    assert.ok(node, "no ✓ on a configured secret");
    while (node && node !== label.parentNode) {
      assert.equal(node.getAttribute("data-i18n"), null);
      node = node.parentNode;
    }
  });
}

test.describe("dashboard plugin credential card", function () {
  let container = null;
  test.before(async function () {
    const page = loadDashboardPage({
      "/api/credentials/plugins": descriptor("example_ads"),
    });
    await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
    await settle();
    container = page.root.querySelector(
      "[data-dashboard-plugin-credentials-list]"
    );
  });
  assertSecretStatus(function () {
    return container;
  });
});

test.describe("auth wizard declarative credential slot", function () {
  let host = null;
  test.before(async function () {
    const page = loadAuthWizardPage({
      "/api/credentials/plugins": descriptor("amazon_ads"),
    });
    host = page.document.createElement("div");
    const state = {
      host: "claude-code",
      platforms: { amazon_ads: true },
      providerChoice: {},
      providerInstalled: {},
      multiAccountAuth: false,
      reauthorizeGoogle: false,
      existing: {
        google: { has_oauth: false },
        meta: { has_oauth: false },
        amazon: { configured: false },
      },
    };
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});
    await settle();
  });
  assertSecretStatus(function () {
    return host;
  });
});

test.describe("creative studio key form", function () {
  // Its ✓ / ✗ mark and placeholders were already there; it gains the same
  // status text so the three credential forms read alike.
  let list = null;
  test.before(function () {
    const page = loadDashboardPage({});
    page.sandbox.MUREO_DASHBOARD_SETUP.renderCreativeStudioSection({
      env_vars: { OPENAI_API_KEY: { set: true } },
    });
    list = page.root.querySelector("[data-dashboard-creative-studio-list]");
  });

  test.it("says Configured next to a stored key", function () {
    const { label, input } = labelFor(list, "OPENAI_API_KEY");
    assert.ok(label.querySelector(".mark-ok"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.equal(
      input.placeholder,
      "dashboard.plugin_credentials_secret_placeholder"
    );
  });

  test.it("says Not set next to a missing key and keeps its own placeholder", function () {
    const { label, input } = labelFor(list, "GEMINI_API_KEY");
    assert.ok(label.querySelector(".mark-no"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.equal(input.placeholder, "dashboard.creative_studio_key_placeholder");
  });
});

test.describe("Meta token card's optional app credentials", function () {
  const APP_SECRET_LABEL = "wizard.auth.meta_token_app_secret_label";
  const APP_ID_LABEL = "wizard.auth.meta_token_app_id_label";

  /** Build the card against a status snapshot carrying `envVars`. */
  function buildCard(envVars) {
    const page = loadAuthWizardPage({});
    page.sandbox.MUREO.state.status = { env_vars: envVars };
    const host = page.document.createElement("div");
    host.appendChild(page.sandbox.MUREO_AUTH_META.buildMetaTokenCard(function () {}));
    return host;
  }

  /** The <label> whose inner span (or itself) carries `i18nKey`. */
  function labelByKey(host, i18nKey) {
    const label = host.querySelectorAll("label").find(function (el) {
      return (
        el.getAttribute("data-i18n") === i18nKey ||
        el.querySelectorAll("span").some(function (s) {
          return s.getAttribute("data-i18n") === i18nKey;
        })
      );
    });
    assert.ok(label, "no label for " + i18nKey);
    return { label: label, input: label.querySelector("input") };
  }

  test.it("marks a stored App secret as configured", function () {
    const host = buildCard({ META_ADS_APP_SECRET: { set: true, value_preview: "••••abcd" } });
    const { label, input } = labelByKey(host, APP_SECRET_LABEL);
    assert.ok(label.querySelector(".mark-ok"));
    assert.equal(label.querySelector(".mark-no"), null);
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.equal(input.type, "password");
    assert.equal(input.value, "");
    assert.equal(input.placeholder, "dashboard.plugin_credentials_secret_placeholder");
  });

  test.it("marks a missing App secret as not set", function () {
    const host = buildCard({ META_ADS_APP_SECRET: { set: false, value_preview: null } });
    const { label, input } = labelByKey(host, APP_SECRET_LABEL);
    assert.ok(label.querySelector(".mark-no"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.equal(
      input.placeholder,
      "dashboard.plugin_credentials_secret_unset_placeholder"
    );
  });

  test.it("keeps data-i18n off the App secret label and the mark's parent", function () {
    const host = buildCard({ META_ADS_APP_SECRET: { set: true } });
    const { label } = labelByKey(host, APP_SECRET_LABEL);
    assert.equal(label.getAttribute("data-i18n"), null);
    assert.equal(label.querySelector(".mark-ok").parentNode.getAttribute("data-i18n"), null);
  });

  test.it("pre-fills a stored App ID and gives it no mark", function () {
    const host = buildCard({ META_ADS_APP_ID: { set: true, value_preview: "1234567890" } });
    const { label, input } = labelByKey(host, APP_ID_LABEL);
    assert.equal(input.value, "1234567890");
    assert.equal(label.querySelector(".mark-ok"), null);
    assert.equal(label.querySelector(".mark-no"), null);
  });

  test.it("never pre-fills the App ID from a masked preview", function () {
    const host = buildCard({ META_ADS_APP_ID: { set: true, value_preview: "••••7890" } });
    assert.equal(labelByKey(host, APP_ID_LABEL).input.value, "");
  });

  test.it("puts no mark on the token input itself", function () {
    // The token field always takes a NEW token; there is nothing to keep.
    const host = buildCard({ META_ADS_ACCESS_TOKEN: { set: true } });
    const { label } = labelByKey(host, "wizard.auth.meta_token_label");
    assert.equal(label.querySelector(".mark-ok"), null);
    assert.equal(label.querySelector(".mark-no"), null);
  });
});

test.describe("advanced credentials form", function () {
  /** The dashboard page with the env form wired and `name` selected. */
  function openForm(envVars, name) {
    const page = loadDashboardPage({});
    page.sandbox.MUREO.state.status = { env_vars: envVars };
    const form = page.root.querySelector("[data-env-form]");
    form.querySelector("[data-env-name]").value = name;
    page.sandbox.MUREO_DASHBOARD_SETUP.wireEnvForm();
    page.sandbox.MUREO_DASHBOARD_SETUP.renderEnvVarsSection(
      page.sandbox.MUREO.state.status
    );
    return { page: page, form: form };
  }

  function valueLabel(form) {
    const input = form.querySelector('[name="env_value"]');
    return { label: input.parentNode, input: input };
  }

  test.it("marks the selected field as configured on the first render", function () {
    const { form } = openForm(
      { META_ADS_APP_SECRET: { set: true, value_preview: "••••abcd" } },
      "META_ADS_APP_SECRET"
    );
    const { label, input } = valueLabel(form);
    assert.ok(label.querySelector(".mark-ok"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.equal(input.placeholder, "dashboard.plugin_credentials_secret_placeholder");
  });

  test.it("follows the select when another field is picked", function () {
    const { form } = openForm(
      {
        META_ADS_APP_SECRET: { set: true, value_preview: "••••abcd" },
        GOOGLE_ADS_CLIENT_SECRET: { set: false, value_preview: null },
      },
      "META_ADS_APP_SECRET"
    );
    const select = form.querySelector("[data-env-name]");
    select.value = "GOOGLE_ADS_CLIENT_SECRET";
    select.dispatchEvent({ type: "change" });
    const { label, input } = valueLabel(form);
    assert.equal(label.querySelector(".mark-ok"), null);
    assert.ok(label.querySelector(".mark-no"));
    assert.ok(statusTexts(label).includes("dashboard.credential_secret_unset"));
    assert.ok(!statusTexts(label).includes("dashboard.credential_secret_configured"));
    assert.equal(
      input.placeholder,
      "dashboard.plugin_credentials_secret_unset_placeholder"
    );
  });

  test.it("turns to configured after a successful save", async function () {
    const { page, form } = openForm(
      { GOOGLE_ADS_CLIENT_SECRET: { set: false, value_preview: null } },
      "GOOGLE_ADS_CLIENT_SECRET"
    );
    assert.ok(valueLabel(form).label.querySelector(".mark-no"));
    form.querySelector('[name="env_value"]').value = "new-secret";
    // What the post-save status refresh will answer with.
    page.sandbox.MUREO.state.status = {
      env_vars: { GOOGLE_ADS_CLIENT_SECRET: { set: true, value_preview: "••••cret" } },
    };
    form.dispatchEvent({ type: "submit" });
    await settle();
    const { label } = valueLabel(form);
    assert.ok(label.querySelector(".mark-ok"));
    assert.equal(label.querySelector(".mark-no"), null);
  });

  test.it("keeps data-i18n off the element that holds the mark", function () {
    const { form } = openForm({ META_ADS_APP_SECRET: { set: true } }, "META_ADS_APP_SECRET");
    const holder = valueLabel(form).label.querySelector(".mark-ok").parentNode;
    assert.equal(holder.getAttribute("data-i18n"), null);
  });
});
