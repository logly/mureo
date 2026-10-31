// The configure wizard offers GA4 (official MCP) under every backend.
//
// A multi-account backend (/api/status `multi_account_auth`) used to remove
// GA4 from Setup entirely: the platform checkbox, the auth slot and the
// provider-install slot. A credential provider's `on_oauth_persisted` hook can
// now write a complete `ga4` section into the store, so GA4 is offered under
// every backend, and its input slot is skipped only when the store already
// holds a usable section (`credentials_present.ga4`).
//
// The Google OAuth slot can fill that section too (#938): when it does, the
// GA4 slot leaves the running queue; when an older Google authorization is
// on disk, the GA4 inputs offer re-authorizing Google instead.
//
// Assertions are on slot keys and on data-attribute selectors — never on
// wording, since the harness's MUREO.t returns the key it was handed.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadAuthWizardPage, loadWizardPage, settle } = require("./dom_harness");

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

/** The Google OAuth slot's own button, or undefined. */
function oauthButton(host) {
  return host
    .querySelectorAll("button")
    .find((b) => b.textContent === "wizard.auth.oauth_button");
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

  test("a new wizard run forgets that Google filled the ga4 section", () => {
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.state.ga4SavedByGoogleOauth = true;
    page.root
      .querySelector("[data-wizard-step]")
      .removeAttribute("data-wizard-step");

    page.document.dispatchEvent({ type: "mureo:wizard_start", detail: {} });

    assert.equal(wizard.state.ga4SavedByGoogleOauth, false);
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

test.describe("GA4 filled from the Google authorization", () => {
  test("ga4CredentialsOnDisk reads the run-local flag", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({ ga4Configured: false });
    state.ga4SavedByGoogleOauth = true;

    assert.equal(page.sandbox.MUREO_AUTH_QUEUE.ga4CredentialsOnDisk(state), true);
  });

  /**
   * Render Google Ads + GA4, then finish the Google OAuth slot through its
   * real button and poll; the status reload reports `ga4Present`, or
   * fails outright when `reloadFails` is set.
   */
  async function finishGoogleSlot(ga4Present, reloadFails) {
    const page = loadAuthWizardPage({
      "/api/oauth/google/status": { success: true },
    });
    page.sandbox.open = function () {};
    page.sandbox.MUREO.postJson = function () {
      return Promise.resolve({ ok: true, body: { url: "https://consent.test/" } });
    };
    page.sandbox.MUREO.loadStatus = function () {
      if (reloadFails) return Promise.reject(new Error("offline"));
      page.sandbox.MUREO.state.status = { credentials_present: { ga4: ga4Present } };
      return Promise.resolve(page.sandbox.MUREO.state.status);
    };
    const host = page.document.createElement("div");
    const state = makeState({ platforms: { google_ads: true } });
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});
    const oauthBtn = host
      .querySelectorAll("button")
      .find((b) => b.textContent === "wizard.auth.oauth_button");
    assert.ok(oauthBtn, "no Google OAuth button");
    oauthBtn.click();
    await settle();
    return { host: host, state: state };
  }

  test("drops the GA4 slot when the authorization saved the section", async () => {
    const { host, state } = await finishGoogleSlot(true);

    assert.ok(host.querySelector("[data-ga4-from-google-oauth]"));
    assert.equal(host.querySelectorAll("input").length, 0);
    assert.equal(state.ga4SavedByGoogleOauth, true);
    // GA4 was the last slot: the step stays, with its own Continue, so
    // the note is read before the wizard moves on.
    const continueBtn = host
      .querySelectorAll("button")
      .find((b) => b.textContent === "wizard.next");
    assert.ok(continueBtn, "no Continue after the dropped GA4 slot");
  });

  test("keeps the GA4 slot when the section is still missing", async () => {
    const { host, state } = await finishGoogleSlot(false);

    assert.ok(!host.querySelector("[data-ga4-from-google-oauth]"));
    assert.equal(host.querySelectorAll("input").length, 2);
    assert.ok(!state.ga4SavedByGoogleOauth);
  });

  test("a failed status reload still advances to the GA4 slot", async () => {
    const { host, state } = await finishGoogleSlot(false, true);

    assert.ok(!host.querySelector("[data-ga4-from-google-oauth]"));
    assert.equal(host.querySelectorAll("input").length, 2);
    assert.ok(!state.ga4SavedByGoogleOauth);
  });

  test("a re-render after the drop shows the same note", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({ googleOauth: true, platforms: { google_ads: true } });
    state.ga4SavedByGoogleOauth = true;

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(host.querySelector("[data-ga4-from-google-oauth]"));
    assert.ok(!host.querySelector("[data-ga4-credentials-reused]"));
  });

  function renderGa4Slot(patch) {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState(patch);
    const renders = { count: 0 };
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {
      renders.count += 1;
    });
    return { host: host, state: state, renders: renders };
  }

  test("offers Re-authorize Google beside the GA4 inputs", () => {
    const { host, state, renders } = renderGa4Slot({
      googleOauth: true,
      platforms: { google_ads: true },
    });

    assert.ok(host.querySelector("[data-ga4-reauthorize-hint]"));
    const btn = host.querySelector("[data-ga4-reauthorize]");
    assert.ok(btn);
    btn.click();
    assert.equal(state.reauthorizeGoogle, true);
    // The Google slot comes in where GA4 was; the step is not re-rendered.
    assert.equal(renders.count, 0);
    assert.equal(host.querySelectorAll("input").length, 0);
    assert.ok(oauthButton(host), "no Google OAuth button after Re-authorize");
  });

  test("Re-authorize from GA4 continues the queue in place", async () => {
    const page = loadAuthWizardPage({
      "/api/oauth/meta/status": { success: true },
      "/api/oauth/google/status": { success: true },
    });
    page.sandbox.open = function () {};
    page.sandbox.MUREO.postJson = function () {
      return Promise.resolve({ ok: true, body: { url: "https://consent.test/" } });
    };
    page.sandbox.MUREO.loadStatus = function () {
      page.sandbox.MUREO.state.status = { credentials_present: { ga4: true } };
      return Promise.resolve(page.sandbox.MUREO.state.status);
    };
    const host = page.document.createElement("div");
    const state = makeState({
      googleOauth: true,
      platforms: { google_ads: true, meta_ads: true },
    });
    state.providerChoice.meta_ads = "native";
    const renders = { count: 0 };
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {
      renders.count += 1;
    });
    const slotHost = host.children[host.children.length - 1];
    const metaBtn = slotHost
      .querySelectorAll("button")
      .find((b) => b.textContent === "wizard.auth.meta_oauth_button");
    assert.ok(metaBtn, "no Meta OAuth button");
    metaBtn.click();
    await settle();
    assert.deepEqual(headingsOf(slotHost), ["wizard.auth.ga4_title"]);

    slotHost.querySelector("[data-ga4-reauthorize]").click();

    assert.equal(renders.count, 0);
    assert.deepEqual(headingsOf(slotHost), ["wizard.auth.google_ads_title"]);
    assert.ok(!headingsOf(host).includes("wizard.auth.meta_ads_title"));

    // Google finishes and fills the section: the GA4 slot that followed it
    // leaves the queue and the step offers its Continue.
    oauthButton(slotHost).click();
    await settle();
    assert.ok(host.querySelector("[data-ga4-from-google-oauth]"));
    assert.equal(host.querySelectorAll("input").length, 0);
    assert.ok(
      slotHost.querySelectorAll("button").find((b) => b.textContent === "wizard.next")
    );
  });

  for (const outcome of ["resolves", "rejects"]) {
    test(`a late reload that ${outcome} after the step was left neither advances nor renders`, async () => {
      const page = loadAuthWizardPage({
        "/api/oauth/google/status": { success: true },
      });
      page.sandbox.open = function () {};
      page.sandbox.MUREO.postJson = function () {
        return Promise.resolve({ ok: true, body: { url: "https://consent.test/" } });
      };
      const late = {};
      page.sandbox.MUREO.loadStatus = function () {
        return new Promise(function (resolve, reject) {
          late.resolve = resolve;
          late.reject = reject;
        });
      };
      const host = page.document.createElement("div");
      const state = makeState({ platforms: { google_ads: true } });
      const renders = { count: 0 };
      page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {
        renders.count += 1;
      });
      const slotHost = host.children[host.children.length - 1];
      oauthButton(slotHost).click();
      await settle();
      assert.ok(late.resolve, "the GA4 check never started");

      // The operator leaves the step; then the reload answers.
      slotHost.isConnected = false;
      page.sandbox.MUREO.state.status = { credentials_present: { ga4: false } };
      if (outcome === "resolves") late.resolve(page.sandbox.MUREO.state.status);
      else late.reject(new Error("offline"));
      await settle();

      // Still the Google slot: the GA4 inputs never rendered, the outer
      // wizard was never asked to move on.
      assert.deepEqual(headingsOf(slotHost), ["wizard.auth.google_ads_title"]);
      assert.equal(slotHost.querySelectorAll("input").length, 0);
      assert.equal(renders.count, 0);
    });
  }

  /**
   * Render Google Ads + GA4 and finish the Google OAuth slot, with a status
   * reload that reports a saved `ga4` section only after the step's DOM
   * was detached.
   */
  async function finishGoogleSlotAfterLeaving() {
    const page = loadAuthWizardPage({
      "/api/oauth/google/status": { success: true },
    });
    page.sandbox.open = function () {};
    page.sandbox.MUREO.postJson = function () {
      return Promise.resolve({ ok: true, body: { url: "https://consent.test/" } });
    };
    const host = page.document.createElement("div");
    const state = makeState({ platforms: { google_ads: true } });
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});
    const slotHost = host.children[host.children.length - 1];
    page.sandbox.MUREO.loadStatus = function () {
      slotHost.isConnected = false;
      page.sandbox.MUREO.state.status = { credentials_present: { ga4: true } };
      return Promise.resolve(page.sandbox.MUREO.state.status);
    };
    const before = host.children.length;
    oauthButton(slotHost).click();
    await settle();
    return { page: page, host: host, state: state, before: before };
  }

  test("a status reload that lands after the step was left leaves its DOM", async () => {
    const { host, state, before } = await finishGoogleSlotAfterLeaving();

    assert.equal(host.children.length, before);
    assert.ok(!host.querySelector("[data-ga4-from-google-oauth]"));
    assert.equal(state.ga4SavedByGoogleOauth, true);
  });

  test("the next render after a late reload does not bring the GA4 slot back", async () => {
    const { page, state } = await finishGoogleSlotAfterLeaving();
    const host = page.document.createElement("div");

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(!keysOf(page.sandbox.MUREO_AUTH_QUEUE.buildAuthQueue(state)).includes("ga4"));
    assert.ok(host.querySelector("[data-ga4-from-google-oauth]"));
  });

  test("names the CLI when this run cannot queue a Google slot", () => {
    const { host } = renderGa4Slot({ googleOauth: true });

    assert.ok(host.querySelector("[data-ga4-reauthorize-hint]"));
    assert.ok(!host.querySelector("[data-ga4-reauthorize]"));
  });

  test("no hint without a Google authorization on disk", () => {
    const { host } = renderGa4Slot({ googleOauth: false });

    assert.ok(!host.querySelector("[data-ga4-reauthorize-hint]"));
  });
});
