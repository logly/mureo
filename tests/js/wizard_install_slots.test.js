// The providers-install step of the configure wizard (#964).
//
// One slot per official MCP the operator chose, its Install button, every
// answer of /api/providers/install the click distinguishes, the
// save-and-retry card a `needs_credentials` answer opens, and the hosted
// TikTok and Meta cards with their shared endpoint copy row.
//
// Assertions are on i18n keys, data attributes, class names and recorded
// calls — never on wording, since the harness's MUREO.t returns the key it
// was handed.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadAuthWizardPage, settle } = require("./dom_harness");

const INSTALL_URL = "/api/providers/install";
const ENV_VAR_URL = "/api/credentials/env-var";
const TIKTOK_URL = "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer";
const META_URL = "https://mcp.facebook.com/ads";
const GOOGLE_ID = "google-ads-official";
const SA_PATH = "/keys/service-account.json";

// A postJson answer that fails at the network layer.
const DOWN = Object.freeze({ down: true });

// Templates that carry {detail}, so a test sees which detail was inserted.
const DETAIL_TEMPLATES = {
  "wizard.providers_install.failed": "failed:{detail}",
  "wizard.providers_install.installer_missing": "missing:{detail}",
};

/** An auth-step STATE; `patch` sets host, platforms, choices and installs. */
function makeState(patch) {
  const state = {
    host: patch.host || "claude-code",
    platforms: {
      google_ads: false,
      search_console: false,
      meta_ads: false,
      ga4: false,
      tiktok_ads: false,
      amazon_ads: false,
    },
    providerChoice: { google_ads: null, meta_ads: null, search_console: null },
    providerInstalled: Object.assign({}, patch.installed),
    pluginPlatforms: {},
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

function googleState(host) {
  return makeState({
    host: host,
    platforms: { google_ads: true },
    choice: { google_ads: "official" },
  });
}

/** A promise the test settles by hand. */
function deferred() {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise: promise, resolve: resolve };
}

/** The next answer queued for `url`: a reply, DOWN, or a pending promise. */
function reply(answers, url) {
  const next = (answers[url] || []).shift();
  if (next === DOWN) return Promise.reject(new Error("down"));
  if (next && typeof next.then === "function") return next;
  return Promise.resolve(next || { ok: true, body: {} });
}

/** Record postJson, toast, loadStatus and the status re-hydration. */
function recordCalls(page, answers) {
  const calls = { posts: [], toasts: [], loadStatus: 0, hydrated: [] };
  const mureo = page.sandbox.MUREO;
  mureo.postJson = (url, payload) => {
    calls.posts.push({ url: url, payload: JSON.parse(JSON.stringify(payload)) });
    return reply(answers, url);
  };
  mureo.toast = (msg) => {
    calls.toasts.push(msg);
  };
  mureo.loadStatus = () => {
    calls.loadStatus += 1;
    return Promise.resolve({});
  };
  page.sandbox.MUREO_WIZARD = {
    hydrateStateFromStatus: (status) => calls.hydrated.push(status),
  };
  return calls;
}

/** Make MUREO.t answer `templates[key]` for the keys it names. */
function withTemplates(page, templates) {
  const t = page.sandbox.MUREO.t;
  page.sandbox.MUREO.t = (key, params) =>
    Object.prototype.hasOwnProperty.call(templates, key) ? templates[key] : t(key, params);
}

/** Render the step for `state` with postJson answering from `answers`. */
function setUp(state, answers, templates) {
  const page = loadAuthWizardPage({});
  const calls = recordCalls(page, answers || {});
  if (templates) withTemplates(page, templates);
  const host = page.document.createElement("div");
  const completed = [];
  page.sandbox.MUREO_AUTH.renderProvidersInstall(host, state, () => completed.push(true));
  return { page: page, calls: calls, host: host, state: state, completed: completed };
}

function headingsOf(host) {
  return host.children
    .filter((el) => el.tagName === "SECTION")
    .map((section) => section.querySelector("h3").textContent);
}

function slotFor(host, platform) {
  return host.children.find(
    (el) =>
      el.tagName === "SECTION" &&
      el.querySelector("h3").textContent === "wizard.provider_banner." + platform
  );
}

function installButtonsOf(section) {
  return section
    .querySelectorAll("button")
    .filter(
      (b) => b.classList.contains("btn-primary") && b.textContent === "dashboard.action_install"
    );
}

/** The direct-child status line under the Install button. */
function statusLineOf(section) {
  return section.children.find(
    (el) => el.tagName === "P" && el.classList.contains("dashboard-provider-hosted-note")
  );
}

/** The inline recovery card a `needs_credentials` answer appends. */
function credentialsCardOf(section) {
  return section.children.find(
    (el) => el.tagName === "DIV" && el.classList.contains("dashboard-provider-hosted-note")
  );
}

/** Render one slot for `state`, click its Install button and let it settle. */
async function clickInstall(state, platform, answers, templates) {
  const env = setUp(state, answers, templates);
  const section = slotFor(env.host, platform);
  const button = installButtonsOf(section)[0];
  const statusLine = statusLineOf(section);
  button.click();
  await settle();
  return Object.assign(env, { section: section, button: button, statusLine: statusLine });
}

function installAnswer(status, detail) {
  return { ok: true, body: detail ? { status: status, detail: detail } : { status: status } };
}

/** Install answers needs_credentials; type the path and click Save & retry. */
async function retryWithPath(answers, templates) {
  const queued = Object.assign({}, answers);
  queued[INSTALL_URL] = [installAnswer("needs_credentials")].concat(answers[INSTALL_URL] || []);
  const env = await clickInstall(googleState(), "google_ads", queued, templates);
  const card = credentialsCardOf(env.section);
  const input = card.querySelector("input[type=text]");
  const retry = card.querySelector('button[data-i18n="wizard.providers_install.save_retry"]');
  input.value = SA_PATH;
  input.dispatchEvent({ type: "input" });
  retry.click();
  await settle();
  const cardStatus = card.children.find((el) => el.tagName === "P" && el.className);
  return Object.assign(env, { card: card, retry: retry, cardStatus: cardStatus });
}

function installPosts(calls) {
  return calls.posts.filter((p) => p.url === INSTALL_URL);
}

test.describe("slot rendering", () => {
  test("one slot per chosen official MCP, in install order", () => {
    const state = makeState({
      platforms: { google_ads: true, meta_ads: true, ga4: true, tiktok_ads: true },
      choice: { google_ads: "official", meta_ads: "official" },
    });
    const { host } = setUp(state);

    assert.deepEqual(headingsOf(host), [
      "wizard.provider_banner.google_ads",
      "wizard.provider_banner.meta_ads",
      "wizard.provider_banner.ga4",
      "wizard.provider_banner.tiktok_ads",
    ]);
  });

  test("no Google Ads slot when it runs natively or is off", () => {
    const native = makeState({
      platforms: { google_ads: true, ga4: true },
      choice: { google_ads: "native" },
    });
    const off = makeState({ platforms: { ga4: true }, choice: { google_ads: "official" } });

    assert.deepEqual(headingsOf(setUp(native).host), ["wizard.provider_banner.ga4"]);
    assert.deepEqual(headingsOf(setUp(off).host), ["wizard.provider_banner.ga4"]);
  });

  test("an installed provider shows the installed line and no button", () => {
    const state = makeState({
      platforms: { google_ads: true, ga4: true },
      choice: { google_ads: "official" },
      installed: { [GOOGLE_ID]: true },
    });
    const { host } = setUp(state);
    const google = slotFor(host, "google_ads");
    const ga4 = slotFor(host, "ga4");

    assert.equal(google.querySelector("p").textContent, "✓ dashboard.installed");
    assert.equal(google.querySelectorAll("button").length, 0);
    assert.equal(ga4.querySelector("p").textContent, "✗ dashboard.not_installed");
    assert.equal(installButtonsOf(ga4).length, 1);
    assert.equal(ga4.querySelectorAll("button").length, 1);
  });
});

test.describe("the Install button and each install answer", () => {
  for (const status of ["ok", "noop"]) {
    test("`" + status + "` records the install, re-reads status and advances", async () => {
      const env = await clickInstall(googleState(), "google_ads", {
        [INSTALL_URL]: [installAnswer(status)],
      });

      assert.deepEqual(env.calls.posts, [{ url: INSTALL_URL, payload: { provider_id: GOOGLE_ID } }]);
      assert.equal(env.state.providerInstalled[GOOGLE_ID], true);
      assert.equal(env.calls.loadStatus, 1);
      assert.equal(env.calls.hydrated.length, 1);
      assert.equal(env.calls.hydrated[0], env.page.sandbox.MUREO.state.status);
      assert.equal(env.completed.length, 1);
    });
  }

  test("`needs_credentials` on Google Ads opens the service-account card", async () => {
    const env = await clickInstall(googleState(), "google_ads", {
      [INSTALL_URL]: [installAnswer("needs_credentials")],
    });
    const card = credentialsCardOf(env.section);
    const input = card.querySelector("input[type=text]");
    const retry = card.querySelector('button[data-i18n="wizard.providers_install.save_retry"]');

    assert.equal(env.button.parentNode, null);
    assert.equal(env.statusLine.hidden, true);
    assert.ok(card.querySelector('p[data-i18n="wizard.providers_install.needs_credentials.google_ads"]'));
    assert.ok(card.querySelector('label[data-i18n="wizard.providers_install.sa_path_label"]'));
    assert.equal(input.parentNode.getAttribute("data-i18n"), "wizard.providers_install.sa_path_label");
    assert.equal(retry.disabled, true);
    input.value = SA_PATH;
    input.dispatchEvent({ type: "input" });
    assert.equal(retry.disabled, false);
    input.value = "";
    input.dispatchEvent({ type: "input" });
    assert.equal(retry.disabled, true);
    assert.equal(env.completed.length, 0);
  });

  test("`needs_credentials` on GA4 shows the generic card without a field", async () => {
    const state = makeState({ platforms: { ga4: true } });
    const env = await clickInstall(state, "ga4", {
      [INSTALL_URL]: [installAnswer("needs_credentials")],
    });
    const card = credentialsCardOf(env.section);

    assert.deepEqual(env.calls.posts[0].payload, { provider_id: "ga4-official" });
    assert.ok(card.querySelector('p[data-i18n="wizard.providers_install.needs_credentials.generic"]'));
    assert.equal(card.querySelector("input"), null);
    assert.equal(card.querySelector("button"), null);
    assert.equal(env.completed.length, 0);
  });

  const connectorCases = [
    { status: "auth_required", host: "claude-code", title: "connector.code.setup_title" },
    { status: "manual_required", host: "claude-code", title: "connector.code.setup_title" },
    { status: "manual_required", host: "claude-desktop", title: "connector.setup_title" },
  ];
  for (const c of connectorCases) {
    test("`" + c.status + "` on " + c.host + " shows the connector steps", async () => {
      const env = await clickInstall(googleState(c.host), "google_ads", {
        [INSTALL_URL]: [installAnswer(c.status)],
      });
      const card = env.section.querySelector(".connector-setup-card");

      assert.equal(env.state.providerInstalled[GOOGLE_ID], true);
      assert.equal(env.button.parentNode, null);
      assert.equal(env.statusLine.hidden, true);
      assert.equal(card.parentNode, env.section);
      assert.ok(card.querySelector('h4[data-i18n="' + c.title + '"]'));
      assert.equal(env.completed.length, 0);
    });
  }

  test("another status shows the failure inline and as a toast", async () => {
    const env = await clickInstall(googleState(), "google_ads", {
      [INSTALL_URL]: [installAnswer("weird", "boom")],
    });

    assert.equal(env.statusLine.hidden, false);
    assert.equal(env.statusLine.textContent, "wizard.providers_install.failed");
    assert.deepEqual(env.calls.toasts, ["wizard.providers_install.failed"]);
    assert.equal(env.button.disabled, false);
    assert.equal(env.completed.length, 0);
  });

  test("the detail fills every {detail} and `$` patterns stay literal", async () => {
    const env = await clickInstall(
      googleState(),
      "google_ads",
      { [INSTALL_URL]: [installAnswer("weird", "$&x")] },
      { "wizard.providers_install.failed": "failed:{detail}/{detail}" }
    );

    assert.equal(env.statusLine.textContent, "failed:$&x/$&x");
  });

  test("a refused request names its error code", async () => {
    const env = await clickInstall(
      googleState(),
      "google_ads",
      { [INSTALL_URL]: [{ ok: false, body: { error: "unknown_provider" } }] },
      DETAIL_TEMPLATES
    );

    assert.equal(env.statusLine.textContent, "failed:unknown_provider");
  });

  test("a missing installer names the executable", async () => {
    const answer = { ok: false, body: { error: "installer_missing", detail: "pipx" } };
    const plain = await clickInstall(googleState(), "google_ads", { [INSTALL_URL]: [answer] });
    const filled = await clickInstall(
      googleState(),
      "google_ads",
      { [INSTALL_URL]: [Object.assign({}, answer)] },
      DETAIL_TEMPLATES
    );

    assert.equal(plain.statusLine.textContent, "wizard.providers_install.installer_missing");
    assert.equal(filled.statusLine.textContent, "missing:pipx");
  });

  test("a network error fails as network_error and re-enables the button", async () => {
    const env = await clickInstall(
      googleState(),
      "google_ads",
      { [INSTALL_URL]: [DOWN] },
      DETAIL_TEMPLATES
    );

    assert.equal(env.statusLine.textContent, "failed:network_error");
    assert.deepEqual(env.calls.toasts, ["failed:network_error"]);
    assert.equal(env.button.disabled, false);
    assert.equal(GOOGLE_ID in env.state.providerInstalled, false);
  });

  test("a pending install disables the button and says it is installing", async () => {
    const pending = deferred();
    const env = await clickInstall(googleState(), "google_ads", {
      [INSTALL_URL]: [pending.promise],
    });

    assert.equal(env.button.disabled, true);
    assert.equal(env.statusLine.hidden, false);
    assert.equal(env.statusLine.textContent, "wizard.providers_install.installing");
    pending.resolve(installAnswer("ok"));
    await settle();
    assert.equal(env.completed.length, 1);
  });
});

test.describe("save and retry on the service-account card", () => {
  test("saves the path into the google_ads section", async () => {
    const env = await retryWithPath({ [INSTALL_URL]: [installAnswer("ok")] });

    assert.deepEqual(env.calls.posts[1], {
      url: ENV_VAR_URL,
      payload: { name: "GOOGLE_APPLICATION_CREDENTIALS", value: SA_PATH, section: "google_ads" },
    });
  });

  const refusedSaves = [
    { name: "a refused save", answer: { ok: false, body: { error: "write_failed" } } },
    { name: "a save that fails at the network", answer: DOWN },
  ];
  for (const c of refusedSaves) {
    test(c.name + " stops before a second install", async () => {
      const env = await retryWithPath({ [ENV_VAR_URL]: [c.answer] });

      assert.equal(env.cardStatus.textContent, "wizard.auth.save_failed");
      assert.equal(env.retry.disabled, false);
      assert.equal(installPosts(env.calls).length, 1);
    });
  }

  test("a retried install that fails at the network names network_error", async () => {
    const env = await retryWithPath({ [INSTALL_URL]: [DOWN] }, DETAIL_TEMPLATES);

    assert.equal(env.cardStatus.textContent, "failed:network_error");
    assert.equal(env.retry.disabled, false);
  });

  for (const status of ["ok", "noop"]) {
    test("a retried install answering `" + status + "` advances", async () => {
      const env = await retryWithPath({ [INSTALL_URL]: [installAnswer(status)] });

      assert.deepEqual(installPosts(env.calls)[1].payload, { provider_id: GOOGLE_ID });
      assert.equal(env.state.providerInstalled[GOOGLE_ID], true);
      assert.equal(env.completed.length, 1);
      assert.equal(env.calls.hydrated.length, 1);
    });
  }

  test("a retried install still short of credentials says so", async () => {
    const env = await retryWithPath({ [INSTALL_URL]: [installAnswer("needs_credentials")] });

    assert.equal(env.cardStatus.textContent, "wizard.providers_install.still_needs_credentials");
    assert.equal(env.retry.disabled, false);
    assert.equal(env.completed.length, 0);
  });

  test("a retried install with another status names its detail", async () => {
    const env = await retryWithPath(
      { [INSTALL_URL]: [installAnswer("weird", "boom")] },
      DETAIL_TEMPLATES
    );

    assert.equal(env.cardStatus.textContent, "failed:boom");
    assert.equal(env.retry.disabled, false);
  });

  test("a retried install with a missing installer names the executable", async () => {
    const answer = { ok: false, body: { error: "installer_missing", detail: "npm" } };
    const plain = await retryWithPath({ [INSTALL_URL]: [answer] });
    const filled = await retryWithPath(
      { [INSTALL_URL]: [Object.assign({}, answer)] },
      DETAIL_TEMPLATES
    );

    assert.equal(plain.cardStatus.textContent, "wizard.providers_install.installer_missing");
    assert.equal(filled.cardStatus.textContent, "missing:npm");
  });

  test("the card says saving, then installing", async () => {
    const save = deferred();
    const install = deferred();
    const env = await retryWithPath({
      [ENV_VAR_URL]: [save.promise],
      [INSTALL_URL]: [install.promise],
    });

    assert.equal(env.cardStatus.textContent, "wizard.auth.saving");
    assert.equal(env.retry.disabled, true);
    save.resolve({ ok: true, body: {} });
    await settle();
    assert.equal(env.cardStatus.textContent, "wizard.providers_install.installing");
    install.resolve(installAnswer("ok"));
    await settle();
    assert.equal(env.completed.length, 1);
  });
});

/** The TikTok slot alone, for `host`. */
function tiktokSlot(host) {
  const env = setUp(makeState({ host: host, platforms: { tiktok_ads: true } }));
  return Object.assign(env, { section: slotFor(env.host, "tiktok_ads") });
}

test.describe("the TikTok hosted card", () => {
  const notes = [
    { host: "claude-code", note: "dashboard.provider_tiktok_oauth_note", row: true },
    { host: "claude-desktop", note: "dashboard.provider_tiktok_desktop_note", row: true },
    { host: "codex", note: "dashboard.provider_tiktok_codex_note", row: false },
  ];
  for (const c of notes) {
    test("on " + c.host + " shows its own note", () => {
      const { section } = tiktokSlot(c.host);
      const row = section.querySelector(".connector-url-row");

      assert.equal(section.querySelector("h3").textContent, "wizard.provider_banner.tiktok_ads");
      assert.ok(section.querySelector('p[data-i18n="' + c.note + '"]'));
      assert.equal(installButtonsOf(section).length, 0);
      assert.equal(Boolean(row), c.row);
      if (row) assert.equal(row.querySelector("code").textContent, TIKTOK_URL);
    });
  }

  test("the copy button writes the URL and reads copied for 1.5 s", async () => {
    const env = tiktokSlot("claude-code");
    const written = [];
    const timers = [];
    env.page.sandbox.navigator = {
      clipboard: { writeText: (u) => (written.push(u), Promise.resolve()) },
    };
    env.page.sandbox.setTimeout = (fn, ms) => timers.push({ fn: fn, ms: ms });
    const copyBtn = env.section.querySelector(".connector-copy-btn");

    copyBtn.click();
    await settle();
    assert.deepEqual(written, [TIKTOK_URL]);
    assert.equal(copyBtn.textContent, "connector.copied");
    assert.deepEqual(timers.map((t) => t.ms), [1500]);
    timers[0].fn();
    assert.equal(copyBtn.textContent, "connector.copy");
  });

  test("a refused clipboard write shows the URL as a toast", async () => {
    const env = tiktokSlot("claude-code");
    env.page.sandbox.navigator = {
      clipboard: { writeText: () => Promise.reject(new Error("denied")) },
    };
    const copyBtn = env.section.querySelector(".connector-copy-btn");

    copyBtn.click();
    await settle();
    assert.deepEqual(env.calls.toasts, [TIKTOK_URL]);
    assert.equal(copyBtn.textContent, "connector.copy");
  });

  test("without a clipboard the URL is shown as a toast", () => {
    const env = tiktokSlot("claude-code");
    env.page.sandbox.navigator = {};
    const copyBtn = env.section.querySelector(".connector-copy-btn");

    copyBtn.click();
    assert.deepEqual(env.calls.toasts, [TIKTOK_URL]);
    assert.equal(copyBtn.textContent, "connector.copy");
  });
});

/** The Meta slot alone, chosen official, for `host`. */
function metaSlot(host) {
  const env = setUp(
    makeState({ host: host, platforms: { meta_ads: true }, choice: { meta_ads: "official" } })
  );
  return Object.assign(env, { section: slotFor(env.host, "meta_ads") });
}

test.describe("the Meta hosted card", () => {
  const titles = [
    { host: "claude-code", title: "connector.code.setup_title" },
    { host: "claude-desktop", title: "connector.setup_title" },
  ];
  for (const c of titles) {
    test("on " + c.host + " shows the connector steps with the endpoint row", () => {
      const env = metaSlot(c.host);
      const card = env.section.querySelector(".connector-setup-card");
      const row = card.querySelector(".connector-url-row");

      assert.ok(card.querySelector('h4[data-i18n="' + c.title + '"]'));
      assert.equal(row.querySelector("code").textContent, META_URL);
      assert.ok(row.querySelector(".connector-copy-btn"));
      assert.equal(installButtonsOf(env.section).length, 0);
      assert.equal(env.completed.length, 0);
    });
  }

  test("on codex says the hosted MCP is not available", () => {
    const env = metaSlot("codex");

    assert.ok(env.section.querySelector('p[data-i18n="dashboard.provider_codex_hosted_na_note"]'));
    assert.equal(env.section.querySelector(".connector-setup-card"), null);
    assert.equal(installButtonsOf(env.section).length, 0);
  });
});
