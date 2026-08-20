// The shipping contract for the extracted modules (#540, #556).
//
// Run with:  node --test tests/js/
//
// The per-module suites (reports_logic.test.js, reports_format.test.js,
// reports_order.test.js) prove the LOGIC is right; this file proves the
// splits did not change how mureo SHIPS. mureo serves mureo/_data/web/*.js
// as plain `<script>`-loaded assets — no bundler, no module system, no
// build step — so the risk of "make it testable" is that the browser gets
// a file it can no longer evaluate. Each module carries a `module.exports`
// tail for the test runner; here the same bytes are evaluated in a context
// that has NO module/exports/require, i.e. the browser's, and asserted to
// publish their global anyway.
//
// Every property below is asserted for EVERY module from one table, not
// duplicated per file: publishes exactly one global, that global is the
// same object Node sees, and dashboard.js binds it.
//
// The table is not the source of truth for WHICH modules exist — the
// directory is. `MODULES` is cross-checked against every `reports_*.js`
// actually shipped in mureo/_data/web/, so a module dropped in without a
// row fails loudly here instead of quietly receiving none of these checks.
// The row still carries what a glob cannot know: which names dashboard.js
// binds, and which definitions must not have survived in it.
//
// dashboard.js is then evaluated on top of them, in load order, against a
// stub DOM — which is what proves the binding block at the top of its
// Reports section resolves against the real modules rather than against
// names an extraction forgot to export.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

/**
 * Every extracted module, in the <script> order app.html pins, with the
 * functions the browser build of dashboard.js binds at load.
 *
 * `bound` is deliberately the exact bind list and not "everything the
 * module exports": these are the names whose absence would leave
 * dashboard.js holding `undefined` at render time.
 */
const MODULES = [
  {
    file: "reports_logic.js",
    global: "MUREO_REPORTS_LOGIC",
    bound: [
      "relativeAge",
      "reportsPlatformLabels",
      "reportsConflictText",
      "reportsRepairHint",
      "reportsConflictsForKey",
      "reportsFreshnessLabel",
      "reportsRowIsStale",
      "reportsNotCollectedNote",
      "reportsNotCollectedNotes",
      "reportsNotCollectedText",
      "reportsCardFreshness",
      "aggregateClientKpis",
    ],
    // Definitions that must NOT survive in dashboard.js: a leftover copy
    // would shadow the module and drift from it.
    moved: [
      "relativeAge",
      "reportsPlatformLabels",
      "reportsConflictText",
      "reportsRepairHint",
      "reportsConflictsForKey",
      "reportsFreshnessLabel",
      "reportsRowIsStale",
      "reportsNotCollectedNote",
      "reportsNotCollectedNotes",
      "reportsNotCollectedText",
      "reportsCardFreshness",
      "aggregateClientKpis",
      "reportsHasDoubleCount",
      "reportsConflictsOfKind",
    ],
  },
  {
    file: "reports_format.js",
    global: "MUREO_REPORTS_FORMAT",
    bound: [
      "reportsPeriodLabel",
      "isCanonicalReportsPeriod",
      "humanizeReportFlag",
      "reportFlagKind",
      "flagSeverityRank",
      "clientReportFlags",
      "buildFlagDetail",
      "formatNumber",
      "formatKpi",
      "reportSummaryTotals",
    ],
    moved: [
      "reportsPeriodLabel",
      "isCanonicalReportsPeriod",
      "humanizeReportFlag",
      "reportFlagKind",
      "flagSeverityRank",
      "clientReportFlags",
      "buildFlagDetail",
      "formatNumber",
      "formatKpi",
      "humanizeFlagWords",
      "matchReportFlagBase",
      "pickLocalizedLabel",
      "flagChipKind",
      "flagParamLabel",
      "formatFlagParam",
      "reportSummaryTotals",
    ],
  },
  {
    file: "reports_order.js",
    global: "MUREO_REPORTS_ORDER",
    bound: ["orderReportsClients", "persistReportsOrderFromDom", "moveReportsCard"],
    moved: [
      "orderReportsClients",
      "persistReportsOrderFromDom",
      "moveReportsCard",
      "readReportsOrder",
      "writeReportsOrder",
    ],
  },
  {
    file: "reports_triage.js",
    global: "MUREO_REPORTS_TRIAGE",
    bound: [
      "buildReportsTriage",
      "triageMarksClient",
      "triageItemText",
      "triageItemNextStep",
      "triageItemSeverity",
      "triageItemTag",
      "triageClientHealth",
      "triageHealthCounts",
      "triageClientBadges",
      "groupReportsTriage",
      "collapseTriageGroups",
      "partitionTriageGroups",
      "dismissTriageGroup",
      "restoreTriageDismissals",
    ],
    moved: [
      "buildReportsTriage",
      "triageMarksClient",
      "triageItemText",
      "triageItemNextStep",
      "triageItemsForClient",
      "triageRank",
      "triageItemSeverity",
      "triageItemTag",
      "triageClientHealth",
      "triageHealthCounts",
      "triageClientBadges",
      "triageItemBadge",
      "groupReportsTriage",
      "collapseTriageGroups",
      "partitionTriageGroups",
      "dismissTriageGroup",
      "restoreTriageDismissals",
      "triageGroupKey",
      "triageItemFingerprint",
      "readDismissedTriage",
      "writeDismissedTriage",
    ],
  },
  {
    file: "reports_overview.js",
    global: "MUREO_REPORTS_OVERVIEW",
    bound: [
      "reportsViewToShow",
      "buildReportsPortfolio",
      "clientPlatformSplit",
      "platformColorSlot",
    ],
    moved: [
      "reportsViewToShow",
      "buildReportsPortfolio",
      "clientPlatformSplit",
      "platformColorSlot",
      "statedPlatformRows",
      "splitBySpend",
    ],
  },
];

/** Every extracted module actually shipped, found rather than declared. */
const SHIPPED_MODULES = fs
  .readdirSync(WEB)
  .filter(function (n) {
    return /^reports_.*\.js$/.test(n);
  })
  .sort();

test.describe("the module table covers what actually ships", function () {
  test.it("has a row for every reports_*.js in the web directory", function () {
    // Without this, adding mureo/_data/web/reports_something.js and
    // forgetting the row here means it gets NONE of the checks below while
    // the suite stays green and the header still claims otherwise.
    assert.deepEqual(
      MODULES.map(function (m) {
        return m.file;
      }).sort(),
      SHIPPED_MODULES,
      "MODULES and mureo/_data/web/reports_*.js disagree"
    );
  });

  test.it("gives each module a distinct global", function () {
    const globals = MODULES.map(function (m) {
      return m.global;
    });
    assert.equal(new Set(globals).size, globals.length, "two modules share a global");
  });
});

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
    localStorage: {
      getItem: function () {
        throw new Error("localStorage at load time");
      },
      setItem: function () {
        throw new Error("localStorage at load time");
      },
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

/** Load every module ahead of dashboard.js, skipping `except`. */
function loadModules(context, except) {
  for (const mod of MODULES) {
    if (mod.file === except) continue;
    evaluate(context, mod.file);
  }
}

for (const mod of MODULES) {
  test.describe(mod.file + " as a browser asset", function () {
    test.it("publishes its global with no CommonJS in scope", function () {
      const env = browserContext();
      assert.equal(env.sandbox.module, undefined);
      assert.equal(env.sandbox.exports, undefined);
      assert.equal(env.sandbox.require, undefined);

      evaluate(env.context, mod.file);

      const api = env.sandbox.window[mod.global];
      assert.ok(api, "window." + mod.global + " was not published");
      for (const name of mod.bound) {
        assert.equal(typeof api[name], "function", name + " is not exported");
      }
    });

    test.it("does not leak anything else into the page", function () {
      // A plain <script> shares one global scope with every other asset, so
      // the module must add exactly one name.
      const env = browserContext();
      const before = new Set(Object.keys(env.sandbox));
      evaluate(env.context, mod.file);
      const added = Object.keys(env.sandbox).filter(function (k) {
        return !before.has(k);
      });
      assert.deepEqual(added, [mod.global]);
    });

    test.it("works when required by Node and loaded by a browser alike", function () {
      // Same bytes, both entry points — the test suite is never reading a
      // copy that could drift from the served asset.
      const env = browserContext();
      evaluate(env.context, mod.file);
      const required = require(path.join(WEB, mod.file));
      assert.deepEqual(
        Object.keys(env.sandbox.window[mod.global]).sort(),
        Object.keys(required).sort()
      );
    });

    test.it("keeps no copy of its logic in dashboard.js", function () {
      // A leftover definition would shadow the module and drift from it.
      const js = read("dashboard.js");
      for (const name of mod.moved) {
        assert.ok(
          !js.includes("function " + name + "("),
          name + " is still defined in dashboard.js"
        );
      }
    });
  });
}

test.describe("reports_logic.js constants", function () {
  test.it("still names the two conflict kinds apart", function () {
    const api = require(path.join(WEB, "reports_logic.js"));
    assert.equal(api.REPORTS_CONFLICT_DUPLICATE_ACCOUNT, "duplicate_account");
    assert.equal(api.REPORTS_CONFLICT_UNRECOGNIZED_KEY, "unrecognized_key");
  });
});

test.describe("dashboard.js still evaluates as a plain script", function () {
  test.it("names EVERY missing module, not just the first", function () {
    // The <script> block is usually dropped or reordered as a block, so
    // diagnosing it one reload at a time is the wrong shape of message.
    const env = browserContext();
    assert.throws(
      function () {
        evaluate(env.context, "dashboard.js");
      },
      function (err) {
        for (const mod of MODULES) {
          assert.match(err.message, new RegExp(mod.global));
          assert.match(err.message, new RegExp(mod.file.replace(".", "\\.")));
        }
        return true;
      }
    );
  });

  test.it("binds the extracted modules when loaded after them", function () {
    const env = browserContext();
    loadModules(env.context, null);
    evaluate(env.context, "dashboard.js");
    // Its load-time side effects are unchanged: it only registers listeners.
    assert.deepEqual(env.listeners, [
      "mureo:ready",
      "mureo:route_changed",
      "mureo:locale_changed",
    ]);
  });

  for (const mod of MODULES) {
    test.it("fails loudly AND diagnosably without " + mod.file, function () {
      // The failure mode that must NOT exist: dashboard.js loading anyway and
      // rendering a conflicted client's double-counted totals because the
      // withholding helper quietly became undefined. So it throws — but this
      // file IS the configure UI, so the throw blanks the whole dashboard,
      // and whoever sees it must not have to reverse-engineer a bare "cannot
      // read properties of undefined". The message names THE module that is
      // missing — not just the first one anybody ever extracted — and the
      // load order that fixes it.
      const env = browserContext();
      loadModules(env.context, mod.file);
      assert.throws(
        function () {
          evaluate(env.context, "dashboard.js");
        },
        function (err) {
          // Raised inside the vm realm, so `instanceof` does not apply.
          assert.equal(err.name, "Error");
          assert.match(err.message, new RegExp(mod.global));
          assert.match(err.message, new RegExp(mod.file.replace(".", "\\.")));
          assert.match(err.message, /BEFORE/);
          for (const other of MODULES) {
            if (other === mod) continue;
            assert.ok(
              !err.message.includes(other.global),
              "the message names " + other.global + ", which IS loaded"
            );
          }
          return true;
        }
      );
      // The guard is not literally the file's first statement — ~1800 lines of
      // declarations precede it — but it does run before anything OBSERVABLE,
      // which is the property that matters: a half-initialised dashboard with
      // live listeners and no working KPI logic would be worse than none.
      assert.deepEqual(env.listeners, [], "a listener was registered before the guard");
    });
  }
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
    for (const name of SHIPPED_MODULES) {
      assert.ok(scripts.includes(name), name + " is not in " + WEB);
    }
  });
});
