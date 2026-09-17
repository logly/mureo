// The configure wizard's auth step: which OAuth slots it queues, and what
// it renders when Google is already authorized (#761).
//
// An operator re-running `configure` with a working Google OAuth refresh
// token was asked to authorize Google again for Google Ads (but not for
// Search Console, which already checked). The "already authenticated" note
// that was supposed to explain a skipped slot was also wiped by the queue
// renderer whenever another slot followed it.
//
// Assertions are on slot keys and on data-attribute selectors — never on
// wording, since the harness's MUREO.t returns the key it was handed.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadAuthWizardPage } = require("./dom_harness");

/** A wizard STATE with nothing selected; `patch` turns the pieces on. */
function makeState(patch) {
  const state = {
    host: "claude-code",
    platforms: {
      google_ads: false,
      search_console: false,
      meta_ads: false,
      ga4: false,
      tiktok_ads: false,
      amazon_ads: false,
    },
    providerChoice: { google_ads: "native", meta_ads: "native" },
    providerInstalled: {},
    multiAccountAuth: false,
    reauthorizeGoogle: false,
    existing: {
      google: { has_oauth: false },
      meta: { has_oauth: false },
      amazon: { configured: false },
    },
  };
  Object.assign(state.platforms, (patch || {}).platforms);
  Object.assign(state.existing.google, (patch || {}).google);
  if (patch && patch.reauthorizeGoogle) state.reauthorizeGoogle = true;
  return state;
}

function keysOf(queue) {
  return queue.map(function (slot) {
    return slot.key;
  });
}

test.describe("buildAuthQueue and the saved Google OAuth token", () => {
  test("queues Google Ads when no Google OAuth is on disk", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({ platforms: { google_ads: true } });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(keys.includes("google_ads"));
  });

  test("skips Google Ads when the saved token already covers it", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({
      platforms: { google_ads: true },
      google: { has_oauth: true },
    });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(!keys.includes("google_ads"));
  });

  test("queues no Google slot at all for Ads + Search Console", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({
      platforms: { google_ads: true, search_console: true },
      google: { has_oauth: true },
    });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(!keys.includes("google_ads"));
    assert.ok(!keys.includes("search_console"));
  });

  test("re-authorize puts the Google Ads slot back in the queue", () => {
    const page = loadAuthWizardPage({});
    const state = makeState({
      platforms: { google_ads: true, search_console: true },
      google: { has_oauth: true },
      reauthorizeGoogle: true,
    });

    const keys = keysOf(page.sandbox.MUREO_AUTH.buildAuthQueue(state));

    assert.ok(keys.includes("google_ads"));
  });
});

test.describe("renderSequentialQueue with a reused Google token", () => {
  test("keeps the reuse note while a later slot renders", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      platforms: { google_ads: true, meta_ads: true },
      google: { has_oauth: true },
    });

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(host.querySelector("[data-google-oauth-reused]"));
    // The Meta slot is the queue's only entry and must still be on screen —
    // the note used to be removed together with it.
    assert.ok(host.querySelector("[data-auth-method-panel]"));
  });

  test("re-authorize flags the state and re-renders the step once", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      platforms: { google_ads: true, meta_ads: true },
      google: { has_oauth: true },
    });
    let renders = 0;

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {
      renders += 1;
    });
    host.querySelector("[data-google-reauthorize]").click();

    assert.equal(state.reauthorizeGoogle, true);
    assert.equal(renders, 1);
  });

  test("an empty queue offers the note and Continue, not a success line", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      platforms: { google_ads: true },
      google: { has_oauth: true },
    });

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(host.querySelector("[data-google-oauth-reused]"));
    const buttons = host.querySelectorAll("button").map(function (b) {
      return b.textContent;
    });
    assert.ok(buttons.includes("wizard.next"));
    assert.ok(!host.textContent.includes("wizard.auth.oauth_success"));
  });

  test("the reused note carries the heading of the slot it replaced", () => {
    const page = loadAuthWizardPage({});
    const headingFor = function (platforms) {
      const host = page.document.createElement("div");
      const state = makeState({ platforms, google: { has_oauth: true } });
      page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});
      return host.querySelector("h3").textContent;
    };
    assert.equal(
      headingFor({ google_ads: true, search_console: true }),
      "wizard.auth.google_ads_title"
    );
    assert.equal(
      headingFor({ search_console: true }),
      "wizard.auth.search_console_title"
    );
  });
});
