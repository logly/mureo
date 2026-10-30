// The configure wizard offers GA4 (official MCP) under every backend.
//
// A multi-account backend (/api/status `multi_account_auth`) used to remove
// GA4 from Setup entirely: the platform checkbox, the auth slot and the
// provider-install slot. A credential provider's `on_oauth_persisted` hook can
// now write a complete `ga4` section into the store, so GA4 is offered under
// every backend, and its input slot is skipped only when the store already
// holds a usable section (`credentials_present.ga4`).
//
// Assertions are on slot keys and on data-attribute selectors — never on
// wording, since the harness's MUREO.t returns the key it was handed.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadAuthWizardPage, loadWizardPage } = require("./dom_harness");

/** A wizard STATE with GA4 selected; `patch` adds platforms and flags. */
function makeState(patch) {
  const state = {
    host: "claude-code",
    platforms: {
      google_ads: false,
      search_console: false,
      meta_ads: false,
      ga4: true,
      tiktok_ads: false,
      amazon_ads: false,
    },
    providerChoice: { google_ads: "native", meta_ads: null },
    providerInstalled: {},
    reauthorizeGoogle: false,
    existing: {
      google: { has_oauth: Boolean(patch.googleOauth) },
      meta: { has_oauth: false },
      amazon: { configured: false },
      ga4: { configured: Boolean(patch.ga4Configured) },
    },
  };
  Object.assign(state.platforms, patch.platforms);
  return state;
}

function keysOf(queue) {
  return queue.map(function (slot) {
    return slot.key;
  });
}

function headingsOf(host) {
  return host.querySelectorAll("h3").map(function (h) {
    return h.textContent;
  });
}

test.describe("hydrateStateFromStatus and GA4", () => {
  test("keeps the GA4 selection under a multi-account backend", () => {
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;
    wizard.state.platforms.ga4 = true;

    wizard.hydrateStateFromStatus({
      multi_account_auth: true,
      credentials_present: { ga4: true },
    });

    assert.equal(wizard.state.platforms.ga4, true);
    assert.equal(wizard.state.existing.ga4.configured, true);
  });

  test("marks GA4 unconfigured when the store has no ga4 section", () => {
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;

    wizard.hydrateStateFromStatus({
      multi_account_auth: true,
      credentials_present: {},
    });

    assert.equal(wizard.state.existing.ga4.configured, false);
  });

  test("a mid-run re-hydrate keeps the auth step in the run", () => {
    // finishInstall re-hydrates after every install. Saving the GA4 slot
    // has written the section by then; re-reading it would drop `auth`
    // from effectiveSteps() and move the stale stepIndex past the
    // remaining install slots.
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({ credentials_present: {} });
    wizard.state.platforms.ga4 = true;
    wizard.state.platforms.tiktok_ads = true;
    wizard.state.stepIndex = wizard
      .effectiveSteps()
      .indexOf("providers_install");

    wizard.hydrateStateFromStatus({ credentials_present: { ga4: true } });

    assert.equal(
      wizard.effectiveSteps()[wizard.state.stepIndex],
      "providers_install"
    );
  });

  test("a new wizard run reads the ga4 section from the latest snapshot", () => {
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({ credentials_present: {} });
    // The dashboard refreshed status since (an env-var row edit wrote the
    // section); the re-run button dispatches wizard_start without another
    // load, so the listener must read the snapshot itself.
    page.sandbox.MUREO.state.status = { credentials_present: { ga4: true } };
    // wizard_start renders the host step, whose radio selector the harness
    // does not model; without a step container render() returns early.
    page.root
      .querySelector("[data-wizard-step]")
      .removeAttribute("data-wizard-step");

    page.document.dispatchEvent({ type: "mureo:wizard_start", detail: {} });

    assert.equal(wizard.state.existing.ga4.configured, true);
  });

  test("the probe taken at wizard_start survives a mid-run re-hydrate", () => {
    // Landing Start -> pick GA4 + TikTok -> save the GA4 slot -> install:
    // finishInstall re-hydrates with the section now present. The run
    // started with no section, so the auth step must stay in the run.
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    page.root
      .querySelector("[data-wizard-step]")
      .removeAttribute("data-wizard-step");
    page.document.dispatchEvent({
      type: "mureo:ready",
      detail: { state: { status: { credentials_present: {} } } },
    });
    page.sandbox.MUREO.state.status = { credentials_present: {} };
    page.document.dispatchEvent({ type: "mureo:wizard_start", detail: {} });
    wizard.state.platforms.ga4 = true;
    wizard.state.platforms.tiktok_ads = true;
    wizard.state.stepIndex = wizard
      .effectiveSteps()
      .indexOf("providers_install");

    wizard.hydrateStateFromStatus({ credentials_present: { ga4: true } });

    assert.equal(wizard.state.existing.ga4.configured, false);
    assert.equal(
      wizard.effectiveSteps()[wizard.state.stepIndex],
      "providers_install"
    );
  });
});

test.describe("buildAuthQueue and the stored ga4 section", () => {
  test("queues GA4 when it is not configured", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({ ga4Configured: false });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(keys.includes("ga4"));
  });

  test("skips GA4 when the store already holds it", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({ ga4Configured: true });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(!keys.includes("ga4"));
  });
});

test.describe("wizard steps under a multi-account backend", () => {
  test("the platforms step renders a GA4 checkbox", () => {
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({ multi_account_auth: true });
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("platforms");
    wizard.render();

    const step = page.root.querySelector("[data-wizard-step]");
    const ga4Label = step.querySelectorAll("label").find(function (label) {
      return label.textContent.includes("wizard.platforms.ga4");
    });

    assert.ok(ga4Label, "no GA4 label on the platforms step");
    assert.ok(ga4Label.querySelector("input"));
  });

  test("the auth step drops out when only a configured GA4 is selected", () => {
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({
      multi_account_auth: true,
      credentials_present: { ga4: true },
    });
    wizard.state.platforms.ga4 = true;

    assert.ok(!wizard.effectiveSteps().includes("auth"));
    assert.ok(wizard.effectiveSteps().includes("providers_install"));
  });

  test("renderProvidersInstall appends the GA4 install slot", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({ ga4Configured: true });

    page.sandbox.MUREO_AUTH.renderProvidersInstall(host, state, function () {});

    // buildProviderInstallSlot marks a slot only by its banner heading.
    assert.ok(headingsOf(host).includes("wizard.provider_banner.ga4"));
  });
});

test.describe("renderSequentialQueue with a stored ga4 section", () => {
  test("the GA4 note has its own heading above the next slot", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      ga4Configured: true,
      platforms: { amazon_ads: true },
    });

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(host.querySelector("[data-ga4-credentials-reused]"));
    assert.deepEqual(headingsOf(host), [
      "wizard.auth.ga4_title",
      "wizard.auth.amazon_ads_title",
    ]);
  });

  test("both reuse notes and no success line when nothing is left", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      ga4Configured: true,
      googleOauth: true,
      platforms: { google_ads: true },
    });

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(host.querySelector("[data-google-oauth-reused]"));
    assert.ok(host.querySelector("[data-ga4-credentials-reused]"));
    assert.ok(!host.textContent.includes("wizard.auth.oauth_success"));
  });
});
