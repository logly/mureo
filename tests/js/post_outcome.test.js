// The configure UI reads every action response one way (#864).
//
// Run with:  node --test tests/js/*.test.js
//
// The server answers a refused request with HTTP 400 and a failed one with
// HTTP 500, both as `{"error": <code>, "detail"?}`; a success is HTTP 200
// with the route's own body. `MUREO.postOutcome` (app.js) is the one place
// that turns a `postJson` result into "succeeded" or "failed with this
// code", and these tests pin it and the dashboard branches that use it.
//
// MUREO.t here returns the KEY (plus its interpolated params), so the
// assertions are about which string was chosen, never about wording.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  appFunction,
  loadAuthWizardPage,
  loadDashboardPage,
  settle,
} = require("./dom_harness.js");

const postOutcome = appFunction("postOutcome");

test.describe("postOutcome", function () {
  test.it("is a success for a 2xx JSON object", function () {
    const body = { status: "noop", detail: "not_installed" };
    const outcome = postOutcome({ ok: true, status: 200, body: body });
    assert.deepEqual([outcome.ok, outcome.code], [true, null]);
    assert.equal(outcome.body, body);
  });

  test.it("reads the code from `error` on an HTTP error", function () {
    const body = { error: "internal_error", detail: "OSError" };
    const outcome = postOutcome({ ok: false, status: 500, body: body });
    assert.equal(outcome.ok, false);
    assert.equal(outcome.code, "internal_error");
    assert.equal(outcome.body, body);
  });

  test.it("falls back to `detail` when there is no `error`", function () {
    const outcome = postOutcome({ ok: false, status: 400, body: { detail: "x" } });
    assert.deepEqual([outcome.ok, outcome.code], [false, "x"]);
  });

  test.it("has no code when there was no response or no JSON", function () {
    for (const res of [null, { ok: false, status: 502, body: null }]) {
      const outcome = postOutcome(res);
      assert.deepEqual([outcome.ok, outcome.code, outcome.body], [false, null, null]);
    }
  });

  test.it("is not a success for a 2xx answer that is not a JSON object", function () {
    assert.equal(postOutcome({ ok: true, status: 200, body: null }).ok, false);
  });
});

// A dashboard page whose POSTs answer from `answers` (URL -> postJson
// result) and whose toasts are recorded.
function page(answers) {
  const loaded = loadDashboardPage({});
  const posts = [];
  const toasts = [];
  loaded.sandbox.MUREO.postJson = function (url, payload) {
    posts.push([url, payload]);
    const answer = answers[url];
    return Promise.resolve(answer || { ok: true, status: 200, body: {} });
  };
  loaded.sandbox.MUREO.toast = function (message, kind) {
    toasts.push([message, kind]);
  };
  return Object.assign(loaded, { posts: posts, toasts: toasts });
}

function refused(code, detail) {
  const body = { error: code };
  if (detail) body.detail = detail;
  return { ok: false, status: 400, body: body };
}

function failed(code, detail) {
  return { ok: false, status: 500, body: { error: code, detail: detail } };
}

function succeeded(body) {
  return { ok: true, status: 200, body: body };
}

function click(node) {
  node.dispatchEvent({ type: "click" });
}

test.describe("demo / BYOD show the message for a refusal code", function () {
  async function createDemo(answer) {
    const p = page({ "/api/demo/init": answer });
    p.root.querySelector("[data-demo-target]").value = "/tmp/demo";
    p.sandbox.MUREO_DASHBOARD_WORKSPACE.wireDemoCreate();
    click(p.root.querySelector("[data-demo-create]"));
    await settle();
    return p.root.querySelector("[data-demo-result]").textContent;
  }

  async function importBundle(answer) {
    const p = page({ "/api/byod/import": answer });
    p.root.querySelector("[data-byod-file]").value = "/tmp/data.csv";
    p.sandbox.MUREO_DASHBOARD_WORKSPACE.wireByodImport();
    click(p.root.querySelector("[data-byod-import]"));
    await settle();
    return p.root.querySelector("[data-byod-result]").textContent;
  }

  test.it("a known demo code reads as its message", async function () {
    assert.equal(
      await createDemo(refused("target_control_characters")),
      "dashboard.demo_failed|detail=dashboard.demo_target_control_characters"
    );
  });

  test.it("any other demo code is shown as the code, never as 'error'", async function () {
    assert.equal(
      await createDemo(failed("demo_init_failed", "DemoInitError")),
      "dashboard.demo_failed|detail=demo_init_failed"
    );
  });

  test.it("a demo success still reads as created", async function () {
    assert.equal(
      await createDemo(succeeded({ status: "ok", created_path: "/tmp/demo" })),
      "dashboard.demo_success|path=/tmp/demo"
    );
  });

  test.it("a known import code reads as its message", async function () {
    assert.equal(
      await importBundle(refused("file_path_not_xlsx")),
      "dashboard.byod_import_failed|detail=dashboard.byod_file_not_xlsx"
    );
  });

  test.it("a failed import shows its code", async function () {
    assert.equal(
      await importBundle(failed("bundle_import_failed", "BundleImportError")),
      "dashboard.byod_import_failed|detail=bundle_import_failed"
    );
  });

  test.it("an import that got no JSON back names that, not 'error'", async function () {
    assert.equal(
      await importBundle({ ok: false, status: 502, body: null }),
      "dashboard.byod_import_failed|detail=request_failed"
    );
  });
});

test.describe("BYOD clear treats noop as done and an HTTP error as failed", function () {
  async function clear(answer) {
    const p = page({ "/api/byod/clear": answer });
    p.sandbox.MUREO_DASHBOARD_WORKSPACE.wireByodClear();
    click(p.root.querySelector("[data-byod-clear]"));
    await settle();
    return p.toasts;
  }

  test.it("noop is a success", async function () {
    assert.deepEqual(await clear(succeeded({ status: "noop" })), [
      ["dashboard.byod_clear_success", "success"],
    ]);
  });

  test.it("a 500 is a failure", async function () {
    assert.deepEqual(await clear(failed("internal_error", "OSError")), [
      ["dashboard.byod_clear_failed", "error"],
    ]);
  });

  test.it("an unknown success status is not read as success", async function () {
    assert.deepEqual(await clear(succeeded({ status: "error" })), [
      ["dashboard.byod_clear_failed", "error"],
    ]);
  });
});

test.describe("basic setup rows read the HTTP status", function () {
  const STATUS = {
    host: "claude-code",
    setup_parts: { mureo_mcp: true, auth_hook: true, skills: true },
  };

  function basicPage(answers) {
    const p = page(answers);
    p.sandbox.MUREO.state.status = STATUS;
    p.sandbox.MUREO_DASHBOARD_SETUP.renderBasicSection(STATUS);
    return p;
  }

  test.it("a remove that answers noop raises no failure toast", async function () {
    const p = basicPage({ "/api/setup/hook/remove": succeeded({ status: "noop" }) });
    click(p.root.querySelector('[data-basic-remove="auth_hook"]'));
    await settle();
    assert.deepEqual(p.toasts, []);
  });

  test.it("a remove that answers 500 is a failure", async function () {
    const p = basicPage({
      "/api/setup/hook/remove": failed("internal_error", "OSError"),
    });
    click(p.root.querySelector('[data-basic-remove="auth_hook"]'));
    await settle();
    assert.deepEqual(p.toasts, [["dashboard.remove_failed", "error"]]);
  });

  test.it("an install that answers 500 is a failure", async function () {
    const p = basicPage({
      "/api/setup/skills/install": failed("internal_error", "OSError"),
    });
    click(p.root.querySelector('[data-basic-install="skills"]'));
    await settle();
    assert.deepEqual(p.toasts, [["dashboard.install_failed", "error"]]);
  });

  test.it("an install that answers ok still says installed", async function () {
    const p = basicPage({ "/api/setup/skills/install": succeeded({ status: "ok" }) });
    click(p.root.querySelector('[data-basic-install="skills"]'));
    await settle();
    assert.deepEqual(p.toasts, [["dashboard.install_done", "success"]]);
  });
});

test.describe("provider rows read the refusal code", function () {
  const STATUS = {
    host: "claude-code",
    providers_installed: { mureo: true, "google-ads-official": true },
    mureo_disable: {},
  };

  function googleRow(answers) {
    const p = page(answers);
    p.sandbox.MUREO.state.status = STATUS;
    p.sandbox.MUREO_DASHBOARD_SETUP.renderProvidersSection(STATUS);
    const row = p.root.querySelector('[data-platform="google-ads-official"]');
    assert.ok(row, "the Google Ads provider row must render");
    return Object.assign(p, { row: row });
  }

  test.it("the tool toggle maps the code in `error` to its message", async function () {
    const p = googleRow({
      "/api/providers/native-toggle": refused("provider_not_installed"),
    });
    click(p.row.querySelector('[data-i18n="dashboard.tooluse_use_official"]'));
    await settle();
    assert.deepEqual(p.toasts, [
      ["dashboard.tooluse_err_provider_not_installed", "error"],
    ]);
  });

  test.it("a provider remove that answers 400 is a failure", async function () {
    const p = googleRow({ "/api/providers/remove": refused("unknown_provider") });
    click(p.row.querySelector('[data-i18n="dashboard.action_remove"]'));
    await settle();
    assert.deepEqual(p.toasts, [["app.toast_operation_failed", "error"]]);
  });

  test.it("a provider remove that answers noop is not a failure", async function () {
    const p = googleRow({
      "/api/providers/remove": succeeded({ status: "noop", detail: "not_registered" }),
    });
    click(p.row.querySelector('[data-i18n="dashboard.action_remove"]'));
    await settle();
    assert.deepEqual(p.toasts, []);
  });
});

test.describe("the wizard's provider install reads the failure code", function () {
  function installCard(answer) {
    const p = loadAuthWizardPage({});
    const toasts = [];
    const t = p.sandbox.MUREO.t;
    // The failure template carries the detail; every other key stays a key.
    p.sandbox.MUREO.t = function (key, params) {
      return key === "wizard.providers_install.failed" ? "failed:{detail}" : t(key, params);
    };
    p.sandbox.MUREO.postJson = function () {
      return Promise.resolve(answer);
    };
    p.sandbox.MUREO.toast = function (message) {
      toasts.push(message);
    };
    const state = {
      host: "claude-code",
      platforms: { google_ads: true },
      providerChoice: { google_ads: "official" },
      providerInstalled: {},
    };
    const host = p.document.createElement("div");
    const done = [];
    p.sandbox.MUREO_AUTH.renderProvidersInstall(host, state, function () {
      done.push(true);
    });
    const button = host
      .querySelectorAll("button")
      .find((b) => b.textContent === "dashboard.action_install");
    assert.ok(button, "the install button must render");
    return { button: button, toasts: toasts, done: done, state: state };
  }

  test.it("a failed install shows its code (error, then detail)", async function () {
    const card = installCard(failed("install_failed", "install_returncode_2"));
    card.button.click();
    await settle();
    assert.deepEqual(card.toasts, ["failed:install_failed"]);
  });

  test.it("a refusal without a detail shows its code", async function () {
    const card = installCard(refused("unknown_provider"));
    card.button.click();
    await settle();
    assert.deepEqual(card.toasts, ["failed:unknown_provider"]);
  });

  test.it("noop (already registered) completes the step like ok", async function () {
    const card = installCard(succeeded({ status: "noop", detail: "already_configured" }));
    card.button.click();
    await settle();
    assert.deepEqual([card.toasts, card.done.length], [[], 1]);
    assert.equal(card.state.providerInstalled["google-ads-official"], true);
  });
});

// A dashboard page whose GETs answer from `answers` (URL -> [status, body]);
// a URL mapped to null rejects, as fetch does when there is no answer.
function getPage(answers) {
  const p = page({});
  p.sandbox.fetch = function (url) {
    const answer = answers[String(url)];
    if (answer === null) return Promise.reject(new Error("network"));
    const status = answer ? answer[0] : 200;
    const body = answer ? answer[1] : {};
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status: status,
      json: () => Promise.resolve(body),
    });
  };
  return p;
}

test.describe("the About update check reads a failed check as failed", function () {
  async function summaryAfter(answer) {
    const p = getPage({ "/api/updates": answer });
    const summary = p.root.querySelector("[data-about-updates-summary]");
    summary.textContent = "before";
    await p.sandbox.MUREO_DASHBOARD_ABOUT.renderUpdates();
    await settle();
    return summary.textContent;
  }

  test.it("a 500 says the check failed", async function () {
    assert.equal(
      await summaryAfter([500, { error: "update_check_failed" }]),
      "dashboard.about_update_check_failed"
    );
  });

  test.it("an up-to-date answer still says so", async function () {
    assert.equal(
      await summaryAfter([200, { status: "ok", any_update: false, packages: [] }]),
      "dashboard.about_up_to_date"
    );
  });

  test.it("no answer at all leaves the line as it was", async function () {
    assert.equal(await summaryAfter(null), "before");
  });
});

test.describe("the demo scenario list ignores a failed listing", function () {
  async function optionsAfter(answer) {
    const p = getPage({ "/api/demo/scenarios": answer });
    await p.sandbox.MUREO_DASHBOARD_WORKSPACE.loadDemoScenarios();
    return p.root
      .querySelector("[data-demo-scenario]")
      .querySelectorAll("option")
      .map((o) => o.value);
  }

  test.it("a 500 leaves the select alone", async function () {
    assert.deepEqual(
      await optionsAfter([500, { error: "internal_error", detail: "KeyError" }]),
      []
    );
  });

  test.it("a listing fills the select", async function () {
    const scenarios = [{ name: "seasonality-trap", title: "T", default: true }];
    assert.deepEqual(
      await optionsAfter([200, { status: "ok", scenarios: scenarios }]),
      ["seasonality-trap"]
    );
  });
});

test.describe("the Browse buttons read a failed picker as failed", function () {
  async function browse(answer) {
    const p = page({ "/api/pick/directory": answer });
    p.sandbox.MUREO_DASHBOARD_WORKSPACE.wirePickers();
    click(p.root.querySelector("[data-demo-browse]"));
    await settle();
    return [p.toasts, p.root.querySelector("[data-demo-target]").value];
  }

  test.it("a 500 is the picker error", async function () {
    assert.deepEqual(await browse(failed("picker_failed", "tkinter_unavailable")), [
      [["dashboard.picker_error", "error"]],
      "",
    ]);
  });

  test.it("cancelled is silent", async function () {
    assert.deepEqual(await browse(succeeded({ status: "cancelled" })), [[], ""]);
  });

  test.it("a chosen path fills the field", async function () {
    assert.deepEqual(
      await browse(succeeded({ status: "ok", path: "/abs/demo" })),
      [[], "/abs/demo"]
    );
  });
});

test.describe("the Meta token card shows mureo's message only", function () {
  test.it("Graph's reply in `detail` is never put on the card", async function () {
    const p = loadAuthWizardPage({});
    p.sandbox.MUREO.postJson = function () {
      return Promise.resolve(
        refused("token_invalid", "Graph said fbtrace_id=SECRET-TRACE")
      );
    };
    p.sandbox.MUREO.toast = function () {};
    const card = p.sandbox.MUREO_AUTH_META.buildMetaTokenCard(function () {});
    card.querySelectorAll("input").find((i) => i.type === "password").value = "tok";
    card
      .querySelector('[data-i18n="wizard.auth.meta_token_validate_button"]')
      .click();
    await settle();
    assert.ok(card.textContent.includes("wizard.auth.meta_token_invalid"));
    assert.ok(!card.textContent.includes("SECRET-TRACE"));
  });
});
