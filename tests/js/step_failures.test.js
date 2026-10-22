// The multi-step routes report each step's outcome (#891).
//
// Run with:  node --test tests/js/*.test.js
//
// `POST /api/setup/basic` and `POST /api/setup/basic/clear` answer HTTP 200
// with one entry per step, or HTTP 500 `{"error": ..., "steps": <the same
// entries>}` when every step failed. `MUREO.stepFailures` (app.js) is the
// one reading of those entries and `MUREO.stepFailureText` the one way a
// failed step is put into words; these tests pin both, and the wizard and
// Danger Zone branches that use them.
//
// MUREO.t here returns the KEY (plus its interpolated params), so the
// assertions are about which string was chosen, never about wording.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  appFunction,
  loadDashboardPage,
  loadWizardPage,
  settle,
} = require("./dom_harness.js");

const stepFailures = appFunction("stepFailures");

// The function runs in its own context; compare plain data, not prototypes.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

const OK = { status: "ok" };
const SKIPPED = { status: "skipped", detail: "multi_account_auth" };
const FAILED = { status: "error", error: "internal_error", detail: "OSError" };

function succeeded(body) {
  return { ok: true, status: 200, body: body };
}

function everyStepFailed(code, steps) {
  return { ok: false, status: 500, body: { error: code, steps: steps } };
}

test.describe("stepFailures", function () {
  test.it("lists the failed steps of a 200 envelope", function () {
    const steps = { mureo_mcp: OK, auth_hook: FAILED, skills: OK };
    assert.deepEqual(plain(stepFailures(steps)), [
      { step: "auth_hook", code: "internal_error" },
    ]);
  });

  test.it("lists the steps of a 500's `steps`", function () {
    const body = everyStepFailed("basic_setup_failed", {
      mureo_mcp: SKIPPED,
      auth_hook: FAILED,
      skills: FAILED,
    }).body;
    assert.deepEqual(plain(stepFailures(body.steps)), [
      { step: "auth_hook", code: "internal_error" },
      { step: "skills", code: "internal_error" },
    ]);
  });

  test.it("reads each provider as a step of its own", function () {
    const steps = {
      mureo_mcp: OK,
      providers: {
        "google-ads-official": { status: "error", error: "unknown_provider" },
        "meta-ads-official": OK,
      },
    };
    assert.deepEqual(plain(stepFailures(steps)), [
      { step: "google-ads-official", code: "unknown_provider" },
    ]);
  });

  test.it("is empty when nothing failed", function () {
    assert.deepEqual(plain(stepFailures({ a: OK, b: SKIPPED, providers: {} })), []);
  });

  test.it("is empty for anything that is not an object", function () {
    for (const input of [null, undefined, "error", 5, [FAILED]]) {
      assert.deepEqual(plain(stepFailures(input)), [], String(input));
    }
  });
});

// The same envelopes as PARITY_CASES in tests/test_web_action_result.py:
// the server decides "every step failed" and the page lists the failed
// steps by one flattening rule, so both sides read each case alike.
const PARITY_CASES = [
  {
    envelope: { mureo_mcp: SKIPPED, auth_hook: FAILED, skills: FAILED },
    failed: ["auth_hook", "skills"],
  },
  {
    envelope: { skills: FAILED, providers: { p1: OK } },
    failed: ["skills"],
  },
  {
    envelope: { skills: FAILED, providers: { p1: { note: "no status" } } },
    failed: ["skills"],
  },
  {
    envelope: { skills: OK, providers: { p1: FAILED, p2: "not a step" } },
    failed: ["p1"],
  },
];

test.describe("stepFailures reads an envelope as the server does", function () {
  PARITY_CASES.forEach(function (c, i) {
    test.it("case " + i, function () {
      assert.deepEqual(
        plain(stepFailures(c.envelope)).map((f) => f.step),
        c.failed
      );
    });
  });
});

test.describe("stepFailureText", function () {
  const text = loadDashboardPage({}).sandbox.MUREO.stepFailureText;

  test.it("names a basic step by its wizard label", function () {
    assert.equal(
      text({ step: "skills", code: "internal_error" }),
      "wizard.basic.skills: app.step_err_internal_error"
    );
  });

  test.it("names a provider by its id", function () {
    assert.equal(
      text({ step: "google-ads-official", code: "unknown_provider" }),
      "google-ads-official: app.step_err_unknown_provider"
    );
  });

  test.it("shows a code it has no message for as the code", function () {
    assert.equal(
      text({ step: "auth_hook", code: "something_new" }),
      "wizard.basic.auth_hook: something_new"
    );
  });

  test.it("shows only the step when there is no code", function () {
    assert.equal(text({ step: "skills", code: null }), "wizard.basic.skills");
  });
});

// The wizard on its basic step, answering the install from `answers` (a
// list, one per click) and recording toasts and status reloads.
function basicStep(answers) {
  const p = loadWizardPage({});
  const toasts = [];
  let reloads = 0;
  p.sandbox.MUREO.isDashboardRoute = () => false;
  p.sandbox.MUREO.postJson = function () {
    const answer = answers.shift();
    return answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer);
  };
  p.sandbox.MUREO.toast = function (message, kind) {
    toasts.push([message, kind]);
  };
  p.sandbox.MUREO.loadStatus = function () {
    reloads += 1;
    return Promise.resolve({});
  };
  const wizard = p.sandbox.MUREO_WIZARD;
  wizard.state.stepIndex = 1;
  wizard.render();
  return {
    wizard: wizard,
    toasts: toasts,
    reloads: () => reloads,
    install: async function () {
      p.root.querySelector("[data-basic-install]").click();
      await settle();
    },
    failures: function () {
      const list = p.root.querySelector("[data-basic-failures]");
      if (!list) return null;
      return {
        role: list.getAttribute("role"),
        items: list.querySelectorAll("li").map((li) => li.textContent),
      };
    },
  };
}

test.describe("the wizard's basic install reads each step", function () {
  test.it("a step that failed keeps the step open and lists it", async function () {
    const step = basicStep([
      succeeded({ mureo_mcp: OK, auth_hook: FAILED, skills: OK }),
    ]);
    await step.install();
    assert.equal(step.wizard.state.basicInstallCompleted, false);
    assert.deepEqual(step.failures(), {
      role: "alert",
      items: ["wizard.basic.auth_hook: app.step_err_internal_error"],
    });
    assert.deepEqual(step.toasts, [["wizard.basic.steps_failed", "error"]]);
    assert.equal(step.reloads(), 1);
  });

  test.it("the list survives a re-render", async function () {
    const step = basicStep([
      succeeded({ mureo_mcp: OK, auth_hook: OK, skills: FAILED }),
    ]);
    await step.install();
    step.wizard.render();
    assert.deepEqual(step.failures().items, [
      "wizard.basic.skills: app.step_err_internal_error",
    ]);
  });

  test.it("every step failed (500 with steps) lists them all", async function () {
    const step = basicStep([
      everyStepFailed("basic_setup_failed", {
        mureo_mcp: SKIPPED,
        auth_hook: FAILED,
        skills: FAILED,
      }),
    ]);
    await step.install();
    assert.equal(step.wizard.state.basicInstallCompleted, false);
    assert.deepEqual(step.failures().items, [
      "wizard.basic.auth_hook: app.step_err_internal_error",
      "wizard.basic.skills: app.step_err_internal_error",
    ]);
    assert.deepEqual(step.toasts, [["wizard.basic.steps_failed", "error"]]);
  });

  test.it("every step succeeding completes the step", async function () {
    const step = basicStep([
      succeeded({ mureo_mcp: OK, auth_hook: { status: "noop" }, skills: OK }),
    ]);
    await step.install();
    assert.equal(step.wizard.state.basicInstallCompleted, true);
    assert.equal(step.failures(), null);
    assert.deepEqual(step.toasts, []);
  });

  test.it("a successful re-run clears the list", async function () {
    const step = basicStep([
      succeeded({ mureo_mcp: OK, auth_hook: FAILED, skills: OK }),
      succeeded({ mureo_mcp: OK, auth_hook: OK, skills: OK }),
    ]);
    await step.install();
    await step.install();
    assert.equal(step.wizard.state.basicInstallCompleted, true);
    assert.equal(step.failures(), null);
  });

  test.it("a failure without steps is still 'setup failed'", async function () {
    for (const answer of [
      { ok: false, status: 500, body: { error: "internal_error" } },
      { ok: false, status: 502, body: null },
      new Error("network"),
    ]) {
      const step = basicStep([answer]);
      await step.install();
      assert.equal(step.wizard.state.basicInstallCompleted, false);
      assert.equal(step.failures(), null);
      assert.deepEqual(step.toasts, [["app.toast_setup_failed", "error"]]);
    }
  });

  test.it("a failure without steps drops the previous run's list", async function () {
    for (const answer of [
      { ok: false, status: 500, body: { error: "internal_error" } },
      { ok: false, status: 502, body: null },
      new Error("network"),
    ]) {
      const step = basicStep([
        succeeded({ mureo_mcp: OK, auth_hook: FAILED, skills: OK }),
        answer,
      ]);
      await step.install();
      assert.ok(step.failures(), "the first run lists its failed step");
      await step.install();
      assert.equal(step.failures(), null);
      step.wizard.render();
      assert.equal(step.failures(), null);
    }
  });
});

test.describe("the Danger Zone's clear-all reads each step", function () {
  async function clearAll(answer) {
    const p = loadDashboardPage({});
    const toasts = [];
    p.sandbox.MUREO.postJson = function () {
      return answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer);
    };
    p.sandbox.MUREO.toast = function (message, kind) {
      toasts.push([message, kind]);
    };
    p.sandbox.MUREO_DASHBOARD_WORKSPACE.wireBulkClearButton();
    p.root.querySelector("[data-dashboard-clear-all]").click();
    await settle();
    return toasts;
  }

  test.it("a step that failed names it", async function () {
    const toasts = await clearAll(
      succeeded({
        mureo_mcp: OK,
        auth_hook: OK,
        skills: FAILED,
        providers: { "google-ads-official": { status: "error", error: "x_y" } },
      })
    );
    assert.deepEqual(toasts, [
      [
        "dashboard.clear_all_steps_failed|items=wizard.basic.skills: " +
          "app.step_err_internal_error" +
          "dashboard.clear_all_steps_failed_separator" +
          "google-ads-official: x_y",
        "error",
      ],
    ]);
  });

  test.it("every step failed (500 with steps) names them", async function () {
    const toasts = await clearAll(
      everyStepFailed("basic_clear_failed", {
        mureo_mcp: FAILED,
        auth_hook: FAILED,
        skills: FAILED,
        providers: {},
      })
    );
    const items = ["mureo_mcp", "auth_hook", "skills"]
      .map((step) => "wizard.basic." + step + ": app.step_err_internal_error")
      .join("dashboard.clear_all_steps_failed_separator");
    assert.deepEqual(toasts, [["dashboard.clear_all_steps_failed|items=" + items, "error"]]);
  });

  test.it("nothing failed is still 'cleanup complete'", async function () {
    const toasts = await clearAll(
      succeeded({ mureo_mcp: OK, auth_hook: { status: "noop" }, skills: OK, providers: {} })
    );
    assert.deepEqual(toasts, [["dashboard.clear_all_success", "success"]]);
  });

  test.it("a failure without steps is still 'removal failed'", async function () {
    for (const answer of [
      { ok: false, status: 500, body: { error: "internal_error" } },
      { ok: false, status: 502, body: null },
      new Error("network"),
    ]) {
      assert.deepEqual(await clearAll(answer), [["dashboard.remove_failed", "error"]]);
    }
  });
});
