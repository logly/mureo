// The shipping contract for the extracted module (#540).
//
// Run with:  node --test tests/js/
//
// reports_logic.test.js proves the LOGIC is right; this file proves the
// split did not change how mureo SHIPS. mureo serves mureo/_data/web/*.js
// as plain `<script>`-loaded assets — no bundler, no module system, no
// build step — so the risk of "make it testable" is that the browser gets
// a file it can no longer evaluate. reports_logic.js carries a
// `module.exports` tail for the test runner; here the same bytes are
// evaluated in a context that has NO module/exports/require, i.e. the
// browser's, and asserted to publish window.MUREO_REPORTS_LOGIC anyway.
//
// dashboard.js is then evaluated on top of it, in load order, against a
// stub DOM — which is what proves the binding block at the top of its
// Reports section resolves against the real module rather than against a
// name the extraction forgot to export.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

/** Every function the browser build of dashboard.js binds at load. */
const BOUND_BY_DASHBOARD = [
  "relativeAge",
  "reportsPlatformLabels",
  "reportsConflictText",
  "reportsConflictsForKey",
  "reportsFreshnessLabel",
  "reportsCardFreshness",
  "aggregateClientKpis",
];

function read(name) {
  return fs.readFileSync(path.join(WEB, name), "utf-8");
}

/**
 * A context shaped like a browser: a `window` that is also the global, a
 * `document` that only records listeners, and no CommonJS anywhere.
 */
function browserContext() {
  const listeners = [];
  const sandbox = {
    document: {
      addEventListener: function (type) {
        listeners.push(type);
      },
      querySelector: function () {
        return null;
      },
      querySelectorAll: function () {
        return [];
      },
      createElement: function () {
        throw new Error("createElement at load time — nothing should render yet");
      },
    },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    fetch: function () {
      throw new Error("fetch at load time");
    },
    MUREO: {
      t: function (key) {
        return key;
      },
    },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  const context = vm.createContext(sandbox);
  return { context: context, sandbox: sandbox, listeners: listeners };
}

function evaluate(context, name) {
  // `new vm.Script` is also the parse check: a syntax error the browser
  // would choke on fails here, before anything runs.
  new vm.Script(read(name), { filename: name }).runInContext(context);
}

test.describe("reports_logic.js as a browser asset", function () {
  test.it("publishes its global with no CommonJS in scope", function () {
    const env = browserContext();
    assert.equal(env.sandbox.module, undefined);
    assert.equal(env.sandbox.exports, undefined);
    assert.equal(env.sandbox.require, undefined);

    evaluate(env.context, "reports_logic.js");

    const api = env.sandbox.window.MUREO_REPORTS_LOGIC;
    assert.ok(api, "window.MUREO_REPORTS_LOGIC was not published");
    for (const name of BOUND_BY_DASHBOARD) {
      assert.equal(typeof api[name], "function", `${name} is not exported`);
    }
    assert.equal(api.REPORTS_CONFLICT_DUPLICATE_ACCOUNT, "duplicate_account");
  });

  test.it("does not leak anything else into the page", function () {
    // A plain <script> shares one global scope with every other asset, so
    // the module must add exactly one name.
    const env = browserContext();
    const before = new Set(Object.keys(env.sandbox));
    evaluate(env.context, "reports_logic.js");
    const added = Object.keys(env.sandbox).filter(function (k) {
      return !before.has(k);
    });
    assert.deepEqual(added, ["MUREO_REPORTS_LOGIC"]);
  });

  test.it("works when required by Node and loaded by a browser alike", function () {
    // Same bytes, both entry points — the test suite is never reading a
    // copy that could drift from the served asset.
    const env = browserContext();
    evaluate(env.context, "reports_logic.js");
    const required = require(path.join(WEB, "reports_logic.js"));
    assert.deepEqual(
      Object.keys(env.sandbox.window.MUREO_REPORTS_LOGIC).sort(),
      Object.keys(required).sort()
    );
  });
});

test.describe("dashboard.js still evaluates as a plain script", function () {
  test.it("binds the extracted logic when loaded after it", function () {
    const env = browserContext();
    evaluate(env.context, "reports_logic.js");
    evaluate(env.context, "dashboard.js");
    // Its load-time side effects are unchanged: it only registers listeners.
    assert.deepEqual(env.listeners, [
      "mureo:ready",
      "mureo:route_changed",
      "mureo:locale_changed",
    ]);
  });

  test.it("fails loudly AND diagnosably if the module is missing", function () {
    // The failure mode that must NOT exist: dashboard.js loading anyway and
    // rendering a conflicted client's double-counted totals because the
    // withholding helper quietly became undefined. So it throws — but this
    // file IS the configure UI, so the throw blanks the whole dashboard,
    // and whoever sees it must not have to reverse-engineer a bare "cannot
    // read properties of undefined". The message names the missing module
    // and the load order that fixes it.
    const env = browserContext();
    assert.throws(
      function () {
        evaluate(env.context, "dashboard.js");
      },
      function (err) {
        // Raised inside the vm realm, so `instanceof` does not apply.
        assert.equal(err.name, "Error");
        assert.match(err.message, /MUREO_REPORTS_LOGIC/);
        assert.match(err.message, /reports_logic\.js/);
        assert.match(err.message, /BEFORE/);
        return true;
      }
    );
    // The guard is not literally the file's first statement — ~1800 lines of
    // declarations precede it — but it does run before anything OBSERVABLE,
    // which is the property that matters: a half-initialised dashboard with
    // live listeners and no working KPI logic would be worse than none.
    assert.deepEqual(env.listeners, [], "a listener was registered before the guard");
  });

  test.it("keeps no copy of the moved logic", function () {
    // A leftover definition would shadow the module and drift from it.
    const js = read("dashboard.js");
    for (const name of BOUND_BY_DASHBOARD) {
      assert.ok(
        !js.includes("function " + name + "("),
        name + " is still defined in dashboard.js"
      );
    }
    assert.ok(!js.includes("function reportsHasDoubleCount("));
    assert.ok(!js.includes("function reportsConflictsOfKind("));
  });
});

test.describe("every served asset parses", function () {
  // Cheap blanket guard: a syntax error in any bundled script is a blank
  // page, and nothing else in the repo would catch one.
  const scripts = fs.readdirSync(WEB).filter(function (n) {
    return n.endsWith(".js");
  });

  for (const name of scripts) {
    test.it(name, function () {
      new vm.Script(read(name), { filename: name });
    });
  }

  test.it("covers the whole web directory", function () {
    assert.ok(scripts.includes("dashboard.js"));
    assert.ok(scripts.includes("reports_logic.js"));
  });
});
