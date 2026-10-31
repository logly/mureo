// The configure wizard's basic step describes the chosen host (#960).
//
// Run with:  node --test tests/js/*.test.js
//
// The status snapshot (`setup_parts`) is computed by the server for its
// session host. The host step pushes the chosen host with `POST /api/host`;
// when the loaded snapshot was taken under another host, the wizard reloads
// the status once the post succeeds, so the basic step's pills describe the
// chosen host. These tests pin when the reload happens, that a reload which
// answers after the operator moved on redraws the basic step, and that the
// refresh never pushes the host again.
//
// MUREO.t here returns the KEY, so the pill is found by its key.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadWizardPage, settle } = require("./dom_harness.js");

const STALE = {
  host: "codex",
  setup_parts: {
    mureo_mcp: true,
    auth_hook: true,
    skills: false,
    skills_state: "missing",
  },
};

const FRESH = {
  host: "claude-code",
  setup_parts: {
    mureo_mcp: true,
    auth_hook: true,
    skills: true,
    skills_state: "current",
  },
};

function hostAccepted(host) {
  return { ok: true, status: 200, body: { host: host } };
}

function hostRejected() {
  return { ok: false, status: 400, body: { error: "invalid_host" } };
}

// A wizard page whose stored host is Claude Code and whose loaded snapshot
// is `status`. `options.answer` is the `/api/host` reply; `options.fresh`
// is what the reload resolves to (a promise holds the answer back).
function boot(status, options) {
  const opts = options || {};
  const p = loadWizardPage({});
  const posts = [];
  let reloads = 0;
  p.localStore.set("mureo.host", "claude-code");
  p.sandbox.MUREO.isDashboardRoute = () => false;
  p.sandbox.MUREO.state.status = status;
  p.sandbox.MUREO.postJson = function (url, payload) {
    posts.push([url, payload.host]);
    return Promise.resolve(opts.answer || hostAccepted(payload.host));
  };
  p.sandbox.MUREO.loadStatus = function () {
    reloads += 1;
    const answer = "fresh" in opts ? opts.fresh : FRESH;
    return Promise.resolve(answer).then(function (fresh) {
      if (fresh) p.sandbox.MUREO.state.status = fresh;
      return fresh;
    });
  };
  return page(p, posts, () => reloads);
}

function page(p, posts, reloads) {
  const wizard = p.sandbox.MUREO_WIZARD;
  return {
    wizard: wizard,
    posts: posts,
    reloads: reloads,
    enterHostStep: async function () {
      wizard.state.stepIndex = 0;
      wizard.render();
      await settle();
    },
    skillsPill: function () {
      return p.root
        .querySelectorAll(".wizard-step-pill")
        .find((pill) => pill.textContent.includes("wizard.basic.skills"));
    },
    step: () => wizard.effectiveSteps()[wizard.state.stepIndex],
    stepHtml: () => p.root.querySelector("[data-wizard-step]").innerHTML,
  };
}

function isDone(pill) {
  const cls = pill.getAttribute("class").split(/\s+/);
  return cls.includes("done") && !cls.includes("not-done");
}

test.describe("wizard host step refreshes the status for the chosen host", function () {
  test.it("reloads once after the host post, then the basic step reads done", async function () {
    const p = boot(STALE);
    await p.enterHostStep();
    assert.deepEqual(p.posts, [["/api/host", "claude-code"]]);
    assert.equal(p.reloads(), 1);
    p.wizard.gotoNext();
    assert.equal(p.step(), "basic");
    assert.equal(isDone(p.skillsPill()), true);
  });

  test.it("redraws the basic step when the reload answers after Next", async function () {
    let answer;
    const held = new Promise((resolve) => {
      answer = resolve;
    });
    const p = boot(STALE, { fresh: held });
    p.wizard.state.stepIndex = 0;
    p.wizard.render();
    p.wizard.gotoNext();
    assert.equal(isDone(p.skillsPill()), false);
    answer(FRESH);
    await settle();
    assert.equal(isDone(p.skillsPill()), true);
    assert.equal(p.step(), "basic");
  });

  test.it("reloads nothing when the snapshot is already for the chosen host", async function () {
    const p = boot(FRESH);
    await p.enterHostStep();
    assert.equal(p.reloads(), 0);
  });

  test.it("reloads nothing when the host post fails", async function () {
    const p = boot(STALE, { answer: hostRejected() });
    await p.enterHostStep();
    assert.equal(p.posts.length, 1);
    assert.equal(p.reloads(), 0);
  });

  test.it("leaves a later step alone when the reload answers there", async function () {
    let answer;
    const held = new Promise((resolve) => {
      answer = resolve;
    });
    const p = boot(STALE, { fresh: held });
    p.wizard.state.stepIndex = 0;
    p.wizard.render();
    p.wizard.gotoNext();
    p.wizard.state.basicInstallCompleted = true;
    p.wizard.gotoNext();
    assert.equal(p.step(), "platforms");
    const before = p.stepHtml();
    answer(FRESH);
    await settle();
    assert.equal(p.step(), "platforms");
    assert.equal(p.stepHtml(), before);
  });

  test.it("keeps the pills and the step when the reload answers null", async function () {
    const p = boot(STALE, { fresh: null });
    await p.enterHostStep();
    p.wizard.gotoNext();
    assert.equal(p.reloads(), 1);
    assert.equal(p.step(), "basic");
    assert.equal(isDone(p.skillsPill()), false);
  });

  test.it("posts the host exactly once across the refresh", async function () {
    const p = boot(STALE);
    await p.enterHostStep();
    p.wizard.gotoNext();
    await settle();
    assert.equal(p.reloads(), 1);
    assert.equal(p.posts.length, 1);
  });
});
