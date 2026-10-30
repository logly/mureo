// A plugin credential provider can stand in for a built-in platform.
//
// A provider declaring `serves_platform` reaches the page as
// /api/status `plugin_platforms`. The Setup tab row for that platform reads
// configured through it, the wizard offers it as a third connection choice
// (Search Console gets a card of its own), and the auth step runs the
// provider's own card instead of the built-in OAuth slot.
//
// Assertions are on slot keys, values and data-attribute selectors — never
// on wording, since the harness's MUREO.t returns the key it was handed.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  appFunction,
  loadAuthWizardPage,
  loadDashboardPage,
  loadWizardPage,
  settle,
} = require("./dom_harness");

const GOOGLE_PROVIDER = "acme_google";
const SC_PROVIDER = "acme_search";
const META_PROVIDER = "acme_meta";

/** One `plugin_platforms` entry, as /api/status sends it. */
function served(providerName, configured) {
  return {
    provider_name: providerName,
    display_name: providerName + " display",
    configured: Boolean(configured),
  };
}

/** An auth-step STATE; `patch` sets platforms, choices and served entries. */
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
    providerChoice: { google_ads: null, meta_ads: null, search_console: null },
    providerInstalled: {},
    pluginPlatforms: patch.pluginPlatforms || {},
    reauthorizeGoogle: false,
    existing: {
      google: { has_oauth: false },
      meta: { has_oauth: false },
      amazon: { configured: false },
      ga4: { configured: false },
    },
  };
  Object.assign(state.platforms, patch.platforms);
  Object.assign(state.providerChoice, patch.choice);
  return state;
}

function radiosOf(host) {
  return host.querySelectorAll("input").filter(function (input) {
    return input.type === "radio";
  });
}

function choose(radio) {
  radio.checked = true;
  radio.dispatchEvent({ type: "change" });
}

/** The wizard, hydrated, on the provider_choice step for `platforms`. */
function wizardOnChoiceStep(pluginPlatforms, platforms) {
  const page = loadWizardPage({});
  const wizard = page.sandbox.MUREO_WIZARD;
  wizard.hydrateStateFromStatus({ plugin_platforms: pluginPlatforms });
  Object.assign(wizard.state.platforms, platforms);
  wizard.state.stepIndex = wizard.effectiveSteps().indexOf("provider_choice");
  wizard.render();
  return { page: page, wizard: wizard };
}

test.describe("hydrateStateFromStatus and plugin_platforms", () => {
  test("fills pluginPlatforms from the status snapshot", () => {
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;

    wizard.hydrateStateFromStatus({
      plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, true) },
    });

    assert.equal(
      wizard.state.pluginPlatforms.google_ads.provider_name,
      GOOGLE_PROVIDER
    );
    assert.equal(wizard.state.pluginPlatforms.google_ads.configured, true);
  });

  test("an absent plugin_platforms leaves an empty map", () => {
    const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;

    wizard.hydrateStateFromStatus({});

    assert.deepEqual(Object.keys(wizard.state.pluginPlatforms), []);
  });
});

test.describe("the Google Ads choice card", () => {
  test("offers two choices when no provider serves Google Ads", () => {
    const { page } = wizardOnChoiceStep({}, { google_ads: true });
    const step = page.root.querySelector("[data-wizard-step]");

    assert.deepEqual(
      radiosOf(step).map((r) => r.value),
      ["official", "native"]
    );
    assert.equal(step.querySelector("[data-plugin-choice]"), null);
  });

  test("offers the serving provider as a third choice", () => {
    const { page, wizard } = wizardOnChoiceStep(
      { google_ads: served(GOOGLE_PROVIDER, false) },
      { google_ads: true }
    );
    const step = page.root.querySelector("[data-wizard-step]");
    const radios = radiosOf(step);

    assert.deepEqual(
      radios.map((r) => r.value),
      ["official", "native", GOOGLE_PROVIDER]
    );
    assert.ok(
      step.querySelector('[data-plugin-choice="' + GOOGLE_PROVIDER + '"]')
    );
    assert.equal(wizard.isNextEnabled(), false);

    choose(radios[2]);

    assert.equal(wizard.state.providerChoice.google_ads, GOOGLE_PROVIDER);
    assert.equal(wizard.isPluginChoice("google_ads"), true);
    assert.equal(wizard.isNextEnabled(), true);
  });
});

test.describe("the Search Console choice card", () => {
  test("is offered only when a provider serves Search Console", () => {
    const without = loadWizardPage({}).sandbox.MUREO_WIZARD;
    without.hydrateStateFromStatus({});
    without.state.platforms.search_console = true;
    const withProvider = loadWizardPage({}).sandbox.MUREO_WIZARD;
    withProvider.hydrateStateFromStatus({
      plugin_platforms: { search_console: served(SC_PROVIDER, false) },
    });
    withProvider.state.platforms.search_console = true;

    assert.ok(!without.effectiveSteps().includes("provider_choice"));
    assert.ok(withProvider.effectiveSteps().includes("provider_choice"));
  });

  test("offers mureo standard and the provider, and gates Next", () => {
    const { page, wizard } = wizardOnChoiceStep(
      { search_console: served(SC_PROVIDER, false) },
      { search_console: true }
    );
    const radios = radiosOf(page.root.querySelector("[data-wizard-step]"));

    assert.deepEqual(
      radios.map((r) => r.value),
      ["native", SC_PROVIDER]
    );
    assert.equal(wizard.isNextEnabled(), false);

    choose(radios[0]);

    assert.equal(wizard.state.providerChoice.search_console, "native");
    assert.equal(wizard.isNextEnabled(), true);
  });

  // The "mureo standard" option's label and desc line. MUREO.t is made to
  // translate every key so the desc line (rendered only for a key that
  // resolves) is drawn.
  function scNativeTexts(googleAds, googleChoice) {
    const page = loadWizardPage({});
    page.sandbox.MUREO.t = (key) => "T:" + key;
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({
      plugin_platforms: {
        google_ads: served(GOOGLE_PROVIDER, false),
        search_console: served(SC_PROVIDER, false),
      },
    });
    Object.assign(wizard.state.platforms, { search_console: true, google_ads: googleAds });
    wizard.state.providerChoice.google_ads = googleChoice;
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("provider_choice");
    wizard.render();
    const radio = radiosOf(page.root.querySelector("[data-wizard-step]")).find(
      (r) => r.name === "provider-search_console" && r.value === "native"
    );
    const label = radio.parentNode;
    const siblings = label.parentNode.children;
    const desc = siblings[siblings.indexOf(label) + 1];
    return { label: label.textContent, desc: desc.textContent };
  }

  test("mureo standard shares the sign-in only with built-in Google Ads", () => {
    const shared = scNativeTexts(true, "native");
    const onPlugin = scNativeTexts(true, GOOGLE_PROVIDER);
    const alone = scNativeTexts(false, null);

    assert.ok(shared.label.includes("wizard.provider_choice.search_console_native"));
    assert.ok(!shared.label.includes("search_console_native_own"));
    assert.equal(shared.desc, "T:wizard.provider_choice.search_console.native_desc");
    for (const own of [onPlugin, alone]) {
      assert.ok(own.label.includes("wizard.provider_choice.search_console_native_own"));
      assert.equal(own.desc, "T:wizard.provider_choice.search_console.native_own_desc");
    }
  });

  test("picking the Google Ads provider redraws the Search Console wording", () => {
    const page = loadWizardPage({});
    page.sandbox.MUREO.t = (key) => "T:" + key;
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({
      plugin_platforms: {
        google_ads: served(GOOGLE_PROVIDER, false),
        search_console: served(SC_PROVIDER, false),
      },
    });
    Object.assign(wizard.state.platforms, { search_console: true, google_ads: true });
    wizard.state.providerChoice.google_ads = "native";
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("provider_choice");
    wizard.render();
    const step = () => page.root.querySelector("[data-wizard-step]");
    const scNative = () =>
      radiosOf(step()).find((r) => r.name === "provider-search_console" && r.value === "native")
        .parentNode.textContent;
    assert.ok(!scNative().includes("native_own"));

    const googlePlugin = radiosOf(step()).find(
      (r) => r.name === "provider-google_ads" && r.value === GOOGLE_PROVIDER
    );
    googlePlugin.checked = true;
    googlePlugin.dispatchEvent({ type: "change" });

    assert.equal(wizard.state.providerChoice.google_ads, GOOGLE_PROVIDER);
    assert.ok(scNative().includes("search_console_native_own"));
  });
});

test.describe("provider names after a new status snapshot", () => {
  const RENAMED = "acme_google renamed";

  /** The wizard after mureo:ready, hydrated from one plugin_platforms. */
  function readyWizard() {
    const page = loadWizardPage({});
    page.sandbox.MUREO.state.status = {
      plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, false) },
    };
    page.document.dispatchEvent({
      type: "mureo:ready",
      detail: { state: page.sandbox.MUREO.state },
    });
    return { page: page, wizard: page.sandbox.MUREO_WIZARD };
  }

  function showChoiceStep(wizard) {
    wizard.state.platforms.google_ads = true;
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("provider_choice");
    wizard.render();
  }

  function pluginLabel(page) {
    return page.root.querySelector('[data-plugin-choice="' + GOOGLE_PROVIDER + '"]')
      .textContent;
  }

  test("a new wizard run reads the latest names", () => {
    const { page, wizard } = readyWizard();

    page.sandbox.MUREO.state.status.plugin_platforms.google_ads.display_name = RENAMED;
    // wizard_start renders the host step, whose radio selector the harness
    // does not model; without a step container render() returns early.
    const container = page.root.querySelector("[data-wizard-step]");
    container.removeAttribute("data-wizard-step");
    page.document.dispatchEvent({ type: "mureo:wizard_start" });
    container.setAttribute("data-wizard-step", "");
    showChoiceStep(wizard);

    assert.ok(pluginLabel(page).includes(RENAMED));
  });

  test("a locale switch re-reads the names before re-rendering", () => {
    const { page, wizard } = readyWizard();
    page.root.querySelector("[data-wizard]").hidden = false;
    showChoiceStep(wizard);
    assert.ok(!pluginLabel(page).includes(RENAMED));

    page.sandbox.MUREO.state.status.plugin_platforms.google_ads.display_name = RENAMED;
    page.document.dispatchEvent({ type: "mureo:locale_changed" });

    assert.ok(pluginLabel(page).includes(RENAMED));
  });
});

test.describe("app.js setLocale", () => {
  // setLocale with every free name it reads stubbed; `steps` records the
  // order of the locale POST, the status reload and the event.
  function runSetLocale(postLocale, loadStatus) {
    const steps = [];
    const setLocale = appFunction("setLocale", {
      applyLocale: () => steps.push("apply"),
      document: {
        dispatchEvent: (evt) => steps.push("event:" + evt.type),
      },
      CustomEvent: function (type) {
        this.type = type;
      },
      postLocale: () => {
        steps.push("post");
        return postLocale();
      },
      loadStatus: () => {
        steps.push("status");
        return loadStatus();
      },
    });
    setLocale("ja");
    return steps;
  }

  test("re-reads the status before announcing the new locale", async () => {
    const steps = runSetLocale(
      () => Promise.resolve(),
      () => Promise.resolve({})
    );
    assert.deepEqual(steps, ["apply", "post"]);

    await settle();

    assert.deepEqual(steps, ["apply", "post", "status", "event:mureo:locale_changed"]);
  });

  test("announces the locale even when both requests fail", async () => {
    const steps = runSetLocale(
      () => Promise.reject(new Error("offline")),
      () => Promise.reject(new Error("offline"))
    );

    await settle();

    assert.deepEqual(steps, ["apply", "post", "status", "event:mureo:locale_changed"]);
  });

  test("boot sets the session locale before the first status load", async () => {
    const steps = [];
    const boot = appFunction("boot", {
      loadI18n: () => Promise.resolve(),
      loadCsrf: () => Promise.resolve(),
      readSavedLocale: () => "ja",
      postLocale: () => {
        steps.push("post");
        return Promise.resolve();
      },
      loadStatus: () => {
        steps.push("status");
        return Promise.resolve({});
      },
      wireLangToggles: () => {},
      wireDashboardLink: () => {},
      applyLocale: (locale) => steps.push("apply:" + locale),
      setBaseRoute: () => {},
      STATE: {},
      document: { dispatchEvent: (evt) => steps.push("event:" + evt.type) },
      CustomEvent: function (type) {
        this.type = type;
      },
    });
    await boot();

    assert.deepEqual(steps, ["post", "status", "apply:ja", "event:mureo:ready"]);
  });
});

test.describe("buildAuthQueue with a plugin provider choice", () => {
  // "key:provider" per slot, as plain strings: the queue is built inside
  // the page's own context, whose arrays deepEqual does not treat as ours.
  function slotsOf(queue) {
    return Array.from(queue, function (slot) {
      return slot.key + ":" + (slot.pluginProvider || slot.oauthProvider);
    });
  }

  function queueOf(state) {
    return loadAuthWizardPage({}).sandbox.MUREO_AUTH.buildAuthQueue(state);
  }

  test("a Google Ads plugin choice queues the provider, not Google OAuth", () => {
    const queue = queueOf(
      makeState({
        platforms: { google_ads: true },
        choice: { google_ads: GOOGLE_PROVIDER },
        pluginPlatforms: { google_ads: served(GOOGLE_PROVIDER, false) },
      })
    );

    assert.equal(queue.length, 1);
    assert.equal(queue[0].key, "google_ads");
    assert.equal(queue[0].pluginProvider, GOOGLE_PROVIDER);
    assert.ok(!queue.some((slot) => slot.oauthProvider === "google"));
  });

  test("Search Console on mureo standard keeps its own Google OAuth slot", () => {
    const queue = queueOf(
      makeState({
        platforms: { google_ads: true, search_console: true },
        choice: { google_ads: GOOGLE_PROVIDER, search_console: "native" },
        pluginPlatforms: { google_ads: served(GOOGLE_PROVIDER, false) },
      })
    );

    assert.deepEqual(
      slotsOf(queue),
      ["google_ads:" + GOOGLE_PROVIDER, "search_console:google"]
    );
  });

  test("Google Ads native with a Search Console plugin queues both", () => {
    const queue = queueOf(
      makeState({
        platforms: { google_ads: true, search_console: true },
        choice: { google_ads: "native", search_console: SC_PROVIDER },
        pluginPlatforms: { search_console: served(SC_PROVIDER, false) },
      })
    );

    assert.deepEqual(
      slotsOf(queue),
      ["google_ads:google", "search_console:" + SC_PROVIDER]
    );
  });

  test("a Meta plugin choice queues the provider, not Meta OAuth", () => {
    const queue = queueOf(
      makeState({
        platforms: { meta_ads: true },
        choice: { meta_ads: META_PROVIDER },
        pluginPlatforms: { meta_ads: served(META_PROVIDER, false) },
      })
    );

    assert.equal(queue.length, 1);
    assert.equal(queue[0].pluginProvider, META_PROVIDER);
    assert.ok(!queue.some((slot) => slot.oauthProvider === "meta"));
  });

  test("a configured provider's slot is skipped", () => {
    const queue = queueOf(
      makeState({
        platforms: { google_ads: true, meta_ads: true },
        choice: { google_ads: GOOGLE_PROVIDER, meta_ads: META_PROVIDER },
        pluginPlatforms: {
          google_ads: served(GOOGLE_PROVIDER, true),
          meta_ads: served(META_PROVIDER, true),
        },
      })
    );

    assert.equal(queue.length, 0);
  });

  test("a Meta plugin choice keeps the auth step in the run", () => {
    function stepsWith(choice) {
      const wizard = loadWizardPage({}).sandbox.MUREO_WIZARD;
      wizard.hydrateStateFromStatus({
        plugin_platforms: { meta_ads: served(META_PROVIDER, false) },
      });
      wizard.state.platforms.meta_ads = true;
      wizard.state.providerChoice.meta_ads = choice;
      return wizard.effectiveSteps();
    }

    assert.ok(stepsWith(META_PROVIDER).includes("auth"));
    assert.ok(!stepsWith("official").includes("auth"));
  });
});

test.describe("the Google sign-in notes with a plugin provider choice", () => {
  /** The auth step rendered for `state`; returns the host. */
  function renderQueue(state) {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});
    return host;
  }

  test("a reused Google sign-in sits under the Search Console heading", () => {
    const state = makeState({
      platforms: { google_ads: true, search_console: true },
      choice: { google_ads: GOOGLE_PROVIDER, search_console: "native" },
      pluginPlatforms: { google_ads: served(GOOGLE_PROVIDER, false) },
    });
    state.existing.google.has_oauth = true;

    const host = renderQueue(state);

    const note = host.querySelector("[data-google-oauth-reused]");
    assert.ok(note);
    const heading = host.children[host.children.indexOf(note) - 1];
    assert.equal(heading.getAttribute("data-i18n"), "wizard.auth.search_console_title");
    const headings = host.children.filter((el) => el.tagName === "H3");
    assert.equal(headings.length, 1);
  });

  test("the Google Ads step names the shared sign-in only for built-in Search Console", () => {
    const KEY = "auth_wizard.google_ads.step2_shared_with_sc";
    function googleStepText(scChoice, scServed) {
      return renderQueue(
        makeState({
          platforms: { google_ads: true, search_console: true },
          choice: { google_ads: "native", search_console: scChoice },
          pluginPlatforms: scServed ? { search_console: scServed } : {},
        })
      ).textContent;
    }

    assert.ok(googleStepText("native", null).includes(KEY));
    assert.ok(!googleStepText(SC_PROVIDER, served(SC_PROVIDER, false)).includes(KEY));
  });
});

test.describe("renderSequentialQueue with a configured provider", () => {
  test("shows the reused note and a Continue, not the success line", () => {
    const page = loadAuthWizardPage({});
    const host = page.document.createElement("div");
    const state = makeState({
      platforms: { google_ads: true },
      choice: { google_ads: GOOGLE_PROVIDER },
      pluginPlatforms: { google_ads: served(GOOGLE_PROVIDER, true) },
    });

    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {});

    assert.ok(
      host.querySelector(
        '[data-plugin-credentials-reused="' + GOOGLE_PROVIDER + '"]'
      )
    );
    assert.ok(!host.textContent.includes("wizard.auth.oauth_success"));
    const buttons = host.querySelectorAll("button");
    assert.ok(buttons.some((b) => b.textContent === "wizard.next"));
  });
});

test.describe("the auth step's slot for an unconfigured provider", () => {
  const DESCRIPTOR = {
    provider_name: GOOGLE_PROVIDER,
    display_name: "acme_google display",
    serves_platform: "google_ads",
    configured: false,
    fields: [
      { key: "client_id", required: true, secret: false, configured: false },
      { key: "refresh_token", required: true, secret: true, configured: false },
    ],
  };

  function renderSlot(descriptor, stubCards) {
    // The route answers with the descriptor the test has set at call
    // time, so a test can flip it between the first build and the refetch.
    const route = { descriptor: descriptor };
    const page = loadAuthWizardPage({
      "/api/credentials/plugins": function () {
        return { plugins: [route.descriptor] };
      },
    });
    const captured = { onStored: null, built: [] };
    if (stubCards) {
      page.sandbox.MUREO_DASHBOARD_PLUGINS = {
        buildPluginCredentialsForm: function (plugin, onStored) {
          captured.onStored = onStored;
          captured.built.push(plugin);
          const card = page.document.createElement("details");
          card.setAttribute("data-stub-card", plugin.provider_name);
          card.setAttribute("data-stub-configured", String(plugin.configured));
          return card;
        },
      };
    }
    const host = page.document.createElement("div");
    const state = makeState({
      platforms: { google_ads: true },
      choice: { google_ads: GOOGLE_PROVIDER },
      pluginPlatforms: { google_ads: served(GOOGLE_PROVIDER, false) },
    });
    const renders = { count: 0 };
    page.sandbox.MUREO_AUTH.renderSequentialQueue(host, state, function () {
      renders.count += 1;
    });
    return { page: page, host: host, captured: captured, renders: renders, route: route };
  }

  function continueButton(host) {
    return host
      .querySelectorAll("button")
      .find((b) => b.getAttribute("data-i18n") === "wizard.next");
  }

  test("an OAuth provider gets the dashboard card and a gated Continue", async () => {
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { host, captured, renders, route } = renderSlot(descriptor, true);
    await settle();

    const card = host.querySelector('[data-stub-card="' + GOOGLE_PROVIDER + '"]');
    assert.ok(card);
    assert.equal(card.open, true);
    // The card's own summary names the provider; the slot adds no second
    // name line beside it.
    const nameLines = card.parentNode.children.filter(function (el) {
      return el !== card && el.textContent === DESCRIPTOR.display_name;
    });
    assert.equal(nameLines.length, 0);
    const next = continueButton(host);
    assert.equal(next.disabled, true);

    route.descriptor = Object.assign({}, descriptor, { configured: true });
    captured.onStored();
    await settle();

    assert.equal(next.disabled, false);
    next.click();
    assert.equal(renders.count, 1);
  });

  test("Continue stays closed while the provider still reads unconfigured", async () => {
    // A consent can leave a required field (the account) still to pick.
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { host, captured, route } = renderSlot(descriptor, true);
    await settle();

    route.descriptor = Object.assign({}, descriptor, { configured: false });
    captured.onStored();
    await settle();

    assert.equal(continueButton(host).disabled, true);
    const status = host
      .querySelectorAll("p")
      .find((p) => p.textContent === "dashboard.plugin_oauth_connected");
    assert.ok(status);
  });

  test("a failed refetch keeps the old card and opens Continue", async () => {
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { page, host, captured } = renderSlot(descriptor, true);
    await settle();
    const before = host.querySelector("[data-stub-card]");

    page.sandbox.fetch = function () {
      return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    };
    captured.onStored();
    await settle();

    assert.equal(captured.built.length, 1);
    const cards = host.querySelectorAll("[data-stub-card]");
    assert.equal(cards.length, 1);
    assert.equal(cards[0], before);
    assert.equal(continueButton(host).disabled, false);
  });

  test("quick successive stores rebuild the card in turn", async () => {
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { host, captured, route } = renderSlot(descriptor, true);
    await settle();
    route.descriptor = Object.assign({}, descriptor, { configured: true });

    // Two stores before either refetch lands, then a third: each refresh
    // must start from the card the previous one left in the DOM.
    captured.onStored();
    captured.onStored();
    await settle();
    captured.onStored();
    await settle();

    assert.equal(captured.built.length, 4);
    assert.equal(host.querySelectorAll("[data-stub-card]").length, 1);
    assert.equal(continueButton(host).disabled, false);
  });

  test("a manual provider's save leaves the slot", async () => {
    const { page, host, renders } = renderSlot(DESCRIPTOR, false);
    await settle();
    const posted = [];
    page.sandbox.MUREO.postJson = function (url, payload) {
      posted.push({ url: url, payload: payload });
      return Promise.resolve({ ok: true, status: 200, body: { status: "ok" } });
    };
    host.querySelectorAll("input").forEach(function (input) {
      input.value = "v-" + input.name;
      input.dispatchEvent({ type: "input" });
    });
    const done = host
      .querySelectorAll("button")
      .find((b) => b.getAttribute("data-i18n") === "wizard.auth.done_button");
    assert.equal(done.disabled, false);

    done.click();
    await settle();

    assert.equal(posted.length, 1);
    assert.equal(posted[0].url, "/api/credentials/plugins/save");
    assert.equal(posted[0].payload.provider_name, GOOGLE_PROVIDER);
    // The only slot in the queue, so leaving it leaves the auth step.
    assert.equal(renders.count, 1);
  });

  test("after consent the card is rebuilt from a fresh descriptor", async () => {
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { host, captured, route } = renderSlot(descriptor, true);
    await settle();
    assert.equal(captured.built.length, 1);

    // The consent stored the token: the refetch now reports it configured.
    route.descriptor = Object.assign({}, descriptor, { configured: true });
    captured.onStored();
    await settle();

    assert.equal(captured.built.length, 2);
    assert.equal(captured.built[1].configured, true);
    const cards = host.querySelectorAll("[data-stub-card]");
    assert.equal(cards.length, 1);
    assert.equal(cards[0].getAttribute("data-stub-configured"), "true");
    assert.equal(cards[0].open, true);
    // The success line and Continue still follow the (new) card.
    const children = cards[0].parentNode.children;
    assert.equal(children[children.length - 1].getAttribute("data-i18n"), "wizard.next");
  });

  test("without the dashboard card the declared fields are rendered", async () => {
    const descriptor = Object.assign({}, DESCRIPTOR, {
      oauth: { target_field: "refresh_token", client_id_field: "client_id" },
    });
    const { host } = renderSlot(descriptor, false);
    await settle();

    const names = host.querySelectorAll("input").map((i) => i.name);
    assert.deepEqual(names, ["client_id", "refresh_token"]);
    assert.equal(host.querySelector("[data-stub-card]"), null);
  });
});

test.describe("the Setup tab's mureo integrations rows", () => {
  function renderRows(status) {
    const page = loadDashboardPage({});
    page.sandbox.MUREO_DASHBOARD_WORKSPACE.renderNativeSection(status);
    const rows = page.root
      .querySelector("[data-dashboard-native-list]")
      .querySelectorAll("li");
    return rows;
  }

  function rowFor(rows, platform) {
    const key = "wizard.platforms." + platform;
    return rows.find(function (li) {
      return li
        .querySelectorAll("[data-i18n]")
        .some((el) => el.getAttribute("data-i18n") === key);
    });
  }

  function hasRemove(li) {
    return li
      .querySelectorAll("button")
      .some((b) => b.getAttribute("data-i18n") === "dashboard.action_remove");
  }

  test("a configured provider marks the row and names itself", () => {
    const row = rowFor(
      renderRows({
        credentials_present: {},
        plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, true) },
      }),
      "google_ads"
    );

    assert.ok(row.querySelector(".mark-ok"));
    assert.ok(
      row.querySelector('[data-native-via-plugin="' + GOOGLE_PROVIDER + '"]')
    );
    assert.equal(hasRemove(row), false);
  });

  test("the built-in section keeps Remove and drops the provider note", () => {
    const row = rowFor(
      renderRows({
        credentials_present: { google_ads: true },
        plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, true) },
      }),
      "google_ads"
    );

    assert.ok(row.querySelector(".mark-ok"));
    assert.equal(row.querySelector("[data-native-via-plugin]"), null);
    assert.equal(hasRemove(row), true);
  });

  test("an unconfigured provider leaves the row unconfigured", () => {
    const row = rowFor(
      renderRows({
        credentials_present: {},
        plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, false) },
      }),
      "google_ads"
    );

    assert.ok(row.querySelector(".mark-no"));
    assert.equal(row.querySelector("[data-native-via-plugin]"), null);
  });

  test("Search Console reads configured through its provider", () => {
    const row = rowFor(
      renderRows({
        credentials_present: {},
        credentials_oauth: {},
        plugin_platforms: { search_console: served(SC_PROVIDER, true) },
      }),
      "search_console"
    );

    assert.ok(row.querySelector(".mark-ok"));
    // Only the provider note: the shared-sign-in note would point at the
    // Google Ads row, which this row does not depend on.
    const notes = row.querySelectorAll(".dashboard-provider-hosted-note");
    assert.equal(notes.length, 1);
    assert.equal(notes[0].getAttribute("data-native-via-plugin"), SC_PROVIDER);
  });

  test("Search Console on the shared sign-in keeps its row note", () => {
    const row = rowFor(
      renderRows({ credentials_present: {}, credentials_oauth: { google: true } }),
      "search_console"
    );

    const notes = row.querySelectorAll(".dashboard-provider-hosted-note");
    assert.equal(notes.length, 1);
    assert.equal(notes[0].getAttribute("data-i18n"), "dashboard.native_sc_row_note");
  });
});

test.describe("the completed step", () => {
  test("names the provider after a platform it connected", () => {
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({
      plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, true) },
    });
    wizard.state.platforms.google_ads = true;
    wizard.state.providerChoice.google_ads = GOOGLE_PROVIDER;
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("completed");
    wizard.render();

    const summary = page.root.querySelector(".wizard-completed-summary");
    const span = summary.querySelector(
      '[data-i18n="wizard.platforms.google_ads"]'
    );
    assert.ok(span);
    assert.equal(span.tagName, "SPAN");
    const li = span.parentNode;
    assert.equal(li.hasAttribute("data-i18n"), false);
    assert.ok(li.textContent.includes(GOOGLE_PROVIDER + " display"));
  });

  test("a built-in choice keeps the plain row", () => {
    const page = loadWizardPage({});
    const wizard = page.sandbox.MUREO_WIZARD;
    wizard.hydrateStateFromStatus({
      plugin_platforms: { google_ads: served(GOOGLE_PROVIDER, true) },
    });
    wizard.state.platforms.google_ads = true;
    wizard.state.providerChoice.google_ads = "native";
    wizard.state.stepIndex = wizard.effectiveSteps().indexOf("completed");
    wizard.render();

    const summary = page.root.querySelector(".wizard-completed-summary");
    const li = summary.querySelector('[data-i18n="wizard.platforms.google_ads"]');
    assert.equal(li.tagName, "LI");
    assert.ok(!li.textContent.includes(GOOGLE_PROVIDER));
  });
});
