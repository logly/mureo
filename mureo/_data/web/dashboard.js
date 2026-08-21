// dashboard.js — the `#dashboard` route's shell: nav, repaint, bootstrap.
//
// This file was 4,624 lines and ~40 render functions across eight left-nav
// sections, and every recent change to it paid for that: implementers
// merge-conflicted inside it on unrelated features, and reviewers had to
// re-derive which renderer belonged to which section. #678 moved each
// section out verbatim into its own `<script>` module. What is left is the
// shell:
//
//   - the left-nav: which group is visible, and which one the dashboard
//     opens on;
//   - show()/hide(), the route's own visibility;
//   - renderAll(), the full-page repaint every section renderer hangs off;
//   - the three listeners that drive all of it (`mureo:ready`,
//     `mureo:route_changed`, `mureo:locale_changed`).
//
// The sections themselves live in dashboard_setup.js, dashboard_workspace.js,
// dashboard_about.js, dashboard_advisors.js, dashboard_reports.js,
// dashboard_creative.js and dashboard_plugins.js — each a plain
// `<script>`-loaded file publishing one global, all of them ahead of this one
// in app.html.
//
// Why the modules are resolved per call rather than bound at load
// ---------------------------------------------------------------
// Every one of these files shares a single global scope and app.html loads
// this one last, so binding each module once at load would work in a browser.
// It is the wrong shape anyway. A dropped `<script>` tag would then blank the
// whole configure UI at load, naming nothing, instead of failing at the
// moment a section is asked for and saying which file is missing — and the
// suite evaluates this file against the reports_*.js modules alone, which a
// load-time bind would turn into an import-time crash.
//
// So each module is looked up on `window` per call, exactly as
// reports_triage.js looks up reports_logic.js, and the forwarders below carry
// the original names. renderAll() and the `mureo:ready` listener therefore
// read exactly as they did when all of this was one closure — which is the
// point: the call sites are the part that must not change.
//
// The one edge that runs the other way is renderAll() itself, which
// dashboard_setup.js and dashboard_workspace.js call after a mutation. They
// resolve `window.MUREO_DASHBOARD` per call for the same reason, which is why
// this file publishes one.

(function () {
  "use strict";

  // Look a section module up at call time, or say precisely what is missing.
  // Never called at load, so a page served without one of these still
  // evaluates every script — it fails when that section is rendered, naming
  // the file whose `<script>` tag to restore.
  function sectionModule(global, file) {
    const api = typeof window !== "undefined" ? window[global] : null;
    if (!api) {
      throw new Error(
        "dashboard.js: window." +
          global +
          " (" +
          file +
          ") is missing. It must be served (see _STATIC_ALLOWLIST in " +
          "mureo/web/handlers.py) and its <script> tag must come BEFORE " +
          "dashboard.js in app.html."
      );
    }
    return api;
  }

  function setupSection() {
    return sectionModule("MUREO_DASHBOARD_SETUP", "dashboard_setup.js");
  }

  function workspaceSection() {
    return sectionModule("MUREO_DASHBOARD_WORKSPACE", "dashboard_workspace.js");
  }

  function aboutSection() {
    return sectionModule("MUREO_DASHBOARD_ABOUT", "dashboard_about.js");
  }

  function advisorsSection() {
    return sectionModule("MUREO_DASHBOARD_ADVISORS", "dashboard_advisors.js");
  }

  function reportsSection() {
    return sectionModule("MUREO_DASHBOARD_REPORTS", "dashboard_reports.js");
  }

  function creativeSection() {
    return sectionModule("MUREO_DASHBOARD_CREATIVE", "dashboard_creative.js");
  }

  function pluginsSection() {
    return sectionModule("MUREO_DASHBOARD_PLUGINS", "dashboard_plugins.js");
  }

  // The section renderers, under their original names. renderAll() below is
  // unchanged from when they were defined in this file.
  function renderHostSection(status) {
    return setupSection().renderHostSection(status);
  }

  function renderBasicSection(status) {
    return setupSection().renderBasicSection(status);
  }

  function renderProvidersSection(status) {
    return setupSection().renderProvidersSection(status);
  }

  function renderEnvVarsSection(status) {
    return setupSection().renderEnvVarsSection(status);
  }

  function renderCreativeStudioSection(status) {
    return setupSection().renderCreativeStudioSection(status);
  }

  function renderNativeSection(status) {
    return workspaceSection().renderNativeSection(status);
  }

  function loadDemoScenarios() {
    return workspaceSection().loadDemoScenarios();
  }

  function renderByodStatus() {
    return workspaceSection().renderByodStatus();
  }

  function renderAbout() {
    return aboutSection().renderAbout();
  }

  function renderUpdates() {
    return aboutSection().renderUpdates();
  }

  function renderAdvisors() {
    return advisorsSection().renderAdvisors();
  }

  function renderReports(entry) {
    return reportsSection().renderReports(entry);
  }

  function renderCreativeGallery() {
    return creativeSection().renderCreativeGallery();
  }

  function renderPluginCredentials() {
    return pluginsSection().renderPluginCredentials();
  }

  // The one-time wiring each section installs on `mureo:ready`, and the
  // Reports section's "the menu asked for the client list" entry point.
  function wireEnvForm() {
    return setupSection().wireEnvForm();
  }

  function wireRerunWizardButton() {
    return setupSection().wireRerunWizardButton();
  }

  function wireBulkClearButton() {
    return workspaceSection().wireBulkClearButton();
  }

  function wireDemoCreate() {
    return workspaceSection().wireDemoCreate();
  }

  function wireByodImport() {
    return workspaceSection().wireByodImport();
  }

  function wireByodClear() {
    return workspaceSection().wireByodClear();
  }

  function wirePickers() {
    return workspaceSection().wirePickers();
  }

  function wireAdvisorForm() {
    return advisorsSection().wireAdvisorForm();
  }

  function wireReportsBackButton() {
    return reportsSection().wireReportsBackButton();
  }

  function enterReportsSection() {
    return reportsSection().enterReportsSection();
  }

  // The Reports section's DOM-free decision modules, checked here at load.
  //
  // dashboard_reports.js binds them and carries the same check for its own
  // sake; this one is the SHELL's, and the case it catches is the one that
  // actually happens: a deployment that dropped the whole `<script>` block,
  // where dashboard_reports.js is missing too and nothing else is left to
  // say so. Failing at load is deliberate — the alternative is a conflicted
  // client's double-counted totals rendering because the withholding helper
  // quietly became `undefined`.
  //
  // Everything above this point is declarations, so nothing observable has
  // happened yet when this throws: no listener is registered, no fetch is
  // issued, no node reaches the DOM. But it does take the whole configure UI
  // with it, so it names WHICH modules are missing and what fixes it rather
  // than leaving whoever hits it to reverse-engineer a bare "cannot read
  // properties of undefined".
  //
  // ALL of them, not the first: a deployment that dropped the whole block of
  // <script> tags would otherwise be diagnosed one reload at a time.
  const missingReportsModules = [
    ["MUREO_REPORTS_LOGIC", "reports_logic.js"],
    ["MUREO_REPORTS_FORMAT", "reports_format.js"],
    ["MUREO_REPORTS_ORDER", "reports_order.js"],
    ["MUREO_REPORTS_TRIAGE", "reports_triage.js"],
    ["MUREO_REPORTS_OVERVIEW", "reports_overview.js"],
  ].filter(function (mod) {
    return !window[mod[0]];
  });
  if (missingReportsModules.length) {
    throw new Error(
      "dashboard.js: " +
        missingReportsModules
          .map(function (mod) {
            return "window." + mod[0] + " (" + mod[1] + ")";
          })
          .join(", ") +
        " is missing. Each must be served (see _STATIC_ALLOWLIST in " +
        "mureo/web/handlers.py) and its <script> tag must come BEFORE " +
        "dashboard.js in app.html."
    );
  }

  // Default left-nav group shown when the dashboard opens.
  const DEFAULT_NAV = "setup";

  function selectNavGroup(name) {
    const groups = document.querySelectorAll("[data-dashboard-group]");
    groups.forEach(function (g) {
      g.hidden = g.getAttribute("data-dashboard-group") !== name;
    });
    const items = document.querySelectorAll("[data-dashboard-nav]");
    items.forEach(function (item) {
      const active = item.getAttribute("data-dashboard-nav") === name;
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });
    const rerun = document.querySelector("[data-dashboard-rerun-wizard]");
    if (rerun) {
      // .btn sets an explicit `display`, which overrides the UA
      // `[hidden]{display:none}` rule — toggle display directly.
      rerun.style.display = name === "setup" ? "" : "none";
    }
    // Asking for the Reports section is asking for the client list. The
    // section keeps its own view state across renders (so a period switch
    // does not eject a reader from a report), which is exactly why arriving
    // from the menu has to say so — otherwise the menu item lands on
    // whatever client was open last and there is no global way back to the
    // list at all. See renderReports().
    if (name === "reports") enterReportsSection();
  }

  function wireDashboardNav() {
    const items = document.querySelectorAll("[data-dashboard-nav]");
    items.forEach(function (item) {
      const name = item.getAttribute("data-dashboard-nav");
      item.addEventListener("click", function (evt) {
        evt.preventDefault();
        selectNavGroup(name);
      });
      item.addEventListener("keydown", function (evt) {
        if (evt.key === "Enter" || evt.key === " " || evt.key === "Spacebar") {
          evt.preventDefault();
          selectNavGroup(name);
        }
      });
    });
  }

  function show() {
    document.querySelector("[data-wizard]").hidden = true;
    document.querySelector("[data-landing]").hidden = true;
    document.querySelector("[data-dashboard]").hidden = false;
    selectNavGroup(DEFAULT_NAV);
    // Render third-party extension tabs (if any). The init call is
    // idempotent — see ``mureo/_data/web/extensions.js``.
    if (MUREO.extensions && typeof MUREO.extensions.init === "function") {
      MUREO.extensions.init();
    }
  }

  function hide() {
    document.querySelector("[data-dashboard]").hidden = true;
  }


  function renderAll() {
    const status = MUREO.state.status;
    renderHostSection(status);
    renderBasicSection(status);
    renderNativeSection(status);
    renderProvidersSection(status);
    renderPluginCredentials();
    renderCreativeStudioSection(status);
    renderEnvVarsSection(status);
    loadDemoScenarios();
    renderByodStatus();
    renderAdvisors();
    renderReports();
    renderCreativeGallery();
    renderAbout();
    renderUpdates();
  }

  document.addEventListener("mureo:ready", function () {
    wireDashboardNav();
    wireEnvForm();
    wireRerunWizardButton();
    wireBulkClearButton();
    wireDemoCreate();
    wireByodImport();
    wireByodClear();
    wireAdvisorForm();
    wireReportsBackButton();
    wirePickers();
    if (MUREO.isDashboardRoute()) {
      show();
      renderAll();
    }
  });

  document.addEventListener("mureo:route_changed", function (evt) {
    if (evt.detail && evt.detail.route === "dashboard") {
      show();
      MUREO.loadStatus().then(renderAll);
    } else {
      hide();
    }
  });

  // Re-render JS-built sections on locale change. `data-i18n` static
  // text is handled by app.js; dynamic nodes built via MUREO.t(...)
  // (demo scenario options, BYOD rows, env-var rows, provider/basic
  // rows) are frozen at first render, so reuse renderAll() to rebuild
  // them. renderAll() reads cached MUREO.state.status (no extra fetch)
  // and clears each container before rebuilding, so repeated locale
  // switches stay idempotent (no duplicate rows/options). Guarded so
  // it is a no-op when the dashboard is absent or hidden. Listener is
  // registered once at module eval — no double-binding.
  document.addEventListener("mureo:locale_changed", function () {
    const dashboard = document.querySelector("[data-dashboard]");
    if (!dashboard || dashboard.hidden) return;
    renderAll();
  });

  // Published for dashboard_setup.js and dashboard_workspace.js, which call
  // renderAll() after a mutation and load BEFORE this file — the one edge in
  // this family that runs backwards. Nothing else is exported: a section
  // module is reached through its own global, not through this one.
  if (typeof window !== "undefined") {
    window.MUREO_DASHBOARD = { renderAll: renderAll };
  }
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = { renderAll: renderAll };
  }
})();
