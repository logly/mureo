// dashboard.js — `#dashboard` route renderer.
// Surfaces installed providers, basic-setup parts, host, and the env-
// var form. Listens for `mureo:route_changed` to toggle visibility.
//
// Per-row [Remove] buttons: each installed basic-setup row gets a delete
// button that confirms via MUREO.confirmAction, POSTs to the matching
// backend route, then re-fetches /api/status and re-renders. Errors
// surface via MUREO.toast — never an unhandled exception, never a stack
// trace in the DOM.
//
// [Clear All] button: double-confirm bulk clear. Posts to
// /api/setup/basic/clear which intentionally does NOT touch
// ~/.mureo/credentials.json (per CTO decision #3, surfaced in the
// second confirmation dialog).

(function () {
  "use strict";

  // Official provider ids whose catalog entry is a hosted_http server
  // (auth is client-side browser OAuth on first use in Claude). Source
  // of truth: catalog.py install_kind === "hosted_http". Phase 1: only
  // meta-ads-official. Extend when a new hosted provider is added.
  const HOSTED_PROVIDER_IDS = ["meta-ads-official"];

  // Official provider id → the mureo-native platform it overlaps. Drives
  // the per-platform native↔official tool toggle. GA4 is intentionally
  // ABSENT: mureo has no native GA4 tools (official-only), so there is
  // nothing to toggle between for it.
  const PROVIDER_PLATFORM = {
    "google-ads-official": "google_ads",
    "meta-ads-official": "meta_ads",
  };

  // Colored ✓ / ✗ status mark as its own element (kept separate from any
  // data-i18n text node so a locale re-translation can't wipe it).
  function statusMark(ok) {
    const m = document.createElement("span");
    m.className = ok ? "mark-ok" : "mark-no";
    m.textContent = ok ? "✓" : "✗";
    return m;
  }

  // Basic-setup row definitions. Keyed entries map a status part to its
  // label, per-row remove endpoint, confirmation key, and button label.
  // Kept as a module-local constant so renderBasicSection stays small.
  const BASIC_ROWS = [
    {
      key: "mureo_mcp",
      labelKey: "wizard.basic.mureo_mcp",
      removeUrl: "/api/setup/mcp/remove",
      confirmKey: "dashboard.confirm_remove_mcp",
      actionKey: "dashboard.action_remove_mcp",
    },
    {
      key: "auth_hook",
      labelKey: "wizard.basic.auth_hook",
      removeUrl: "/api/setup/hook/remove",
      confirmKey: "dashboard.confirm_remove_hook",
      actionKey: "dashboard.action_remove_hook",
    },
    {
      key: "skills",
      labelKey: "wizard.basic.skills",
      removeUrl: "/api/setup/skills/remove",
      confirmKey: "dashboard.confirm_remove_skills",
      actionKey: "dashboard.action_remove_skills",
    },
  ];

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

  function renderHostSection(status) {
    const node = document.querySelector("[data-dashboard-host-value]");
    if (!node || !status) return;
    // Show the friendly host name (same labels as the wizard host
    // selector), not the raw "claude-desktop" / "claude-code" id.
    const hostKey =
      status.host === "claude-desktop"
        ? "wizard.host.claude_desktop"
        : status.host === "claude-code"
        ? "wizard.host.claude_code"
        : null;
    if (hostKey) {
      node.textContent = MUREO.t(hostKey);
      node.setAttribute("data-i18n", hostKey);
    } else {
      node.textContent = status.host || "";
      node.removeAttribute("data-i18n");
    }
  }

  function buildBasicRemoveButton(row) {
    // Returns a button element wired to call `row.removeUrl` after a
    // single confirm. Toast (not throw) on failure.
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t(row.actionKey);
    btn.setAttribute("data-i18n", row.actionKey);
    btn.setAttribute("data-basic-remove", row.key);
    btn.addEventListener("click", async function () {
      const confirmed = await MUREO.confirmAction(MUREO.t(row.confirmKey));
      if (!confirmed) return;
      let res;
      try {
        res = await MUREO.postJson(row.removeUrl, {});
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
        return;
      }
      if (!res || !res.ok) {
        MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
        return;
      }
      await MUREO.loadStatus();
      renderAll();
    });
    return btn;
  }

  function renderBasicSection(status) {
    const list = document.querySelector("[data-dashboard-basic-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const parts = (status && status.setup_parts) || {};
    // #222: a multi-account backend never registers the bare `mureo` MCP
    // entry (per-client `mureo-<slug>` entries are the correct wiring), so
    // the MCP row must not render here either.
    const suppressMcp = Boolean(status && status.multi_account_auth);
    BASIC_ROWS.forEach(function (row) {
      if (suppressMcp && row.key === "mureo_mcp") return;
      const li = document.createElement("li");
      const installed = parts[row.key] === true;
      const labelSpan = document.createElement("span");
      let labelText = MUREO.t(row.labelKey);
      // The credential-guard hook has no surface on Claude Desktop, so
      // annotate it inline rather than implying it can be installed.
      if (
        row.key === "auth_hook" &&
        status &&
        status.host === "claude-desktop"
      ) {
        labelText += " " + MUREO.t("wizard.basic.auth_hook_desktop_na");
      }
      labelSpan.appendChild(statusMark(installed));
      labelSpan.appendChild(document.createTextNode(" " + labelText));
      li.appendChild(labelSpan);
      if (installed) {
        li.appendChild(buildBasicRemoveButton(row));
      }
      list.appendChild(li);
    });
  }

  // Connected-state for hosted_http providers (account-level Connectors
  // mureo never writes to the config file, so providers_installed always
  // reports them ✗). Lazily fetched once from /api/providers/hosted-status
  // and cached; null = not fetched yet.
  let hostedConnected = null;
  let hostedFetchInFlight = false;

  function renderProvidersSection(status) {
    const list = document.querySelector("[data-dashboard-providers-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const providers = (status && status.providers_installed) || {};
    let anyNotInstalled = false;
    let needHostedProbe = false;
    [
      "google-ads-official",
      "meta-ads-official",
      "ga4-official",
    ].forEach(function (pid) {
      const li = document.createElement("li");
      // Tag the row with its provider id so CSS can apply a
      // platform-tinted left-accent stripe (Google blue / Meta blue /
      // GA4 orange). The data attribute is also a stable hook for
      // future per-platform UI (icons, links, etc.). See #183 review.
      li.dataset.platform = pid;
      const isHosted = HOSTED_PROVIDER_IDS.indexOf(pid) !== -1;
      // Hosted providers are "installed" ⇔ their account-level Connector
      // is Connected (mureo never registers them in the config file).
      let installed;
      if (isHosted) {
        installed = Boolean(hostedConnected && hostedConnected[pid] === true);
        if (hostedConnected === null) needHostedProbe = true;
      } else {
        installed = providers[pid];
        if (!installed) anyNotInstalled = true;
      }
      const labelSpan = document.createElement("span");
      labelSpan.appendChild(statusMark(installed));
      labelSpan.appendChild(document.createTextNode(" " + pid));
      li.appendChild(labelSpan);
      // No Remove for hosted here: a hosted MCP's lifecycle (the
      // ~/.claude.json http entry + its `/mcp` OAuth) is managed via
      // the wizard / `claude mcp remove`, not this dashboard row. Only
      // file-registered (pipx) providers get a Remove button.
      if (installed && !isHosted) {
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "btn btn-secondary";
        removeBtn.textContent = MUREO.t("dashboard.action_remove");
        removeBtn.setAttribute("data-i18n", "dashboard.action_remove");
        removeBtn.addEventListener("click", async function () {
          const res = await MUREO.postJson("/api/providers/remove", {
            provider_id: pid,
          });
          if (res.ok) {
            await MUREO.loadStatus();
            renderAll();
          } else {
            MUREO.toast(MUREO.t("app.toast_operation_failed"), "error");
          }
        });
        li.appendChild(removeBtn);
      }

      // hosted_http note(s) live INSIDE the provider's own <li> so
      // they read as part of the same Meta Ads row — not as separate
      // bordered list items. Guarded so a missing translation never
      // echoes the key.
      if (HOSTED_PROVIDER_IDS.indexOf(pid) !== -1) {
        function appendNote(key) {
          const text = MUREO.t(key);
          if (!text || text === key) return;
          const note = document.createElement("div");
          note.className = "dashboard-provider-hosted-note";
          note.textContent = text;
          note.setAttribute("data-i18n", key);
          li.appendChild(note);
        }
        if (status && status.host === "claude-desktop") {
          // Desktop: a remote MCP can't be wired from here (Desktop
          // rejects http config; Meta's hosted MCP has no OAuth DCR).
          // Only the Connectors instruction applies.
          appendNote("dashboard.provider_desktop_connectors_note");
        } else {
          appendNote("dashboard.provider_hosted_oauth_note");
        }
      }

      // Per-platform native↔official tool toggle. Only meaningful when
      // the mureo MCP itself is configured (otherwise there are no
      // native tools to step aside). Server enforces the no-strand
      // guard; the UI just reflects state and surfaces the reason.
      const platform = PROVIDER_PLATFORM[pid];
      if (platform && providers.mureo) {
        const md = (status && status.mureo_disable) || {};
        const preferred = md[platform] === true;
        const tg = document.createElement("div");
        tg.className = "dashboard-provider-hosted-note dashboard-tooluse";
        const stateKey = preferred
          ? "dashboard.tooluse_state_official"
          : "dashboard.tooluse_state_native";
        const stateSpan = document.createElement("span");
        stateSpan.textContent =
          MUREO.t("dashboard.tooluse_label") + " " + MUREO.t(stateKey);
        tg.appendChild(stateSpan);
        const toKey = preferred
          ? "dashboard.tooluse_use_native"
          : "dashboard.tooluse_use_official";
        const tBtn = document.createElement("button");
        tBtn.type = "button";
        tBtn.className = "btn btn-secondary";
        tBtn.textContent = MUREO.t(toKey);
        tBtn.setAttribute("data-i18n", toKey);
        tBtn.addEventListener("click", async function () {
          const res = await MUREO.postJson(
            "/api/providers/native-toggle",
            { platform: platform, prefer_official: !preferred }
          );
          const body = res && res.body;
          if (res.ok && body && (body.status === "ok" || body.status === "noop")) {
            MUREO.toast(MUREO.t("dashboard.tooluse_restart_note"), "success");
            await MUREO.loadStatus();
            renderAll();
            return;
          }
          const detail = body && body.detail;
          const errKey =
            detail === "provider_not_installed"
              ? "dashboard.tooluse_err_provider_not_installed"
              : detail === "connector_not_connected"
              ? "dashboard.tooluse_err_connector_not_connected"
              : detail === "no_mureo_block"
              ? "dashboard.tooluse_err_no_mureo_block"
              : "dashboard.tooluse_err_generic";
          MUREO.toast(MUREO.t(errKey), "error");
        });
        tg.appendChild(tBtn);
        li.appendChild(tg);
      }
      list.appendChild(li);
    });
    if (anyNotInstalled) {
      const note = document.createElement("li");
      note.className = "dashboard-provider-add-note";
      note.textContent = MUREO.t("dashboard.provider_add_via_wizard");
      note.setAttribute("data-i18n", "dashboard.provider_add_via_wizard");
      list.appendChild(note);
    }

    // Probe the hosted connectors' Connected state once, then re-render
    // so a finished account-level Connector flips ✗ → ✓ without a manual
    // page reload. Cached + in-flight guarded so this never loops.
    if (needHostedProbe && !hostedFetchInFlight) {
      hostedFetchInFlight = true;
      MUREO.postJson("/api/providers/hosted-status", {})
        .then(function (res) {
          hostedConnected =
            (res && res.body && res.body.hosted_connected) || {};
        })
        .catch(function () {
          hostedConnected = {}; // best-effort: leave rows as ✗
        })
        .then(function () {
          hostedFetchInFlight = false;
          renderProvidersSection(MUREO.state && MUREO.state.status);
        });
    }
  }

  function wireEnvForm() {
    const form = document.querySelector("[data-env-form]");
    if (!form) return;
    form.addEventListener("submit", async function (evt) {
      evt.preventDefault();
      const name = form.querySelector("[data-env-name]").value;
      const value = form.querySelector('[name="env_value"]').value;
      if (!name || !value) return;
      const res = await MUREO.postJson("/api/credentials/env-var", {
        name: name,
        value: value,
      });
      if (res.ok) {
        form.querySelector('[name="env_value"]').value = "";
        MUREO.toast(MUREO.t("app.toast_saved"), "success");
        // Refresh to surface the freshly-saved value preview.
        await MUREO.loadStatus();
        renderEnvVarsSection(MUREO.state.status);
      } else {
        MUREO.toast(MUREO.t("app.toast_save_failed"), "error");
      }
    });
  }

  function renderEnvVarsSection(status) {
    // Renders one row per known env var: <name> <masked-or-full-preview>.
    // Secret-named vars arrive already masked from status_collector —
    // this function does NOT mask, and the raw value is never available
    // to the browser. Unset vars get a localised "(not set)" placeholder.
    const list = document.querySelector("[data-dashboard-env-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const envVars = (status && status.env_vars) || {};
    const names = Object.keys(envVars).sort();
    names.forEach(function (name) {
      const entry = envVars[name] || {};
      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.className = "dashboard-env-name";
      nameSpan.textContent = name;
      const valueSpan = document.createElement("span");
      valueSpan.className = "dashboard-env-value";
      if (entry.set && entry.value_preview != null) {
        valueSpan.textContent = entry.value_preview;
      } else {
        valueSpan.classList.add("dashboard-env-unset");
        valueSpan.textContent = MUREO.t("dashboard.env_value_unset");
      }
      li.appendChild(nameSpan);
      li.appendChild(valueSpan);
      list.appendChild(li);
    });
  }

  function wireRerunWizardButton() {
    const btn = document.querySelector("[data-dashboard-rerun-wizard]");
    if (!btn) return;
    btn.addEventListener("click", function () {
      MUREO.navigateToWizard();
      document.dispatchEvent(
        new CustomEvent("mureo:wizard_start", { detail: {} })
      );
    });
  }

  async function runBulkClear() {
    // Two-step confirmation. Either decline aborts.
    const ok1 = await MUREO.confirmAction(MUREO.t("dashboard.confirm_clear_all_1"));
    if (!ok1) return;
    const ok2 = await MUREO.confirmAction(MUREO.t("dashboard.confirm_clear_all_2"));
    if (!ok2) return;
    let res;
    try {
      res = await MUREO.postJson("/api/setup/basic/clear", {});
    } catch (_err) {
      MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
      return;
    }
    if (!res || !res.ok) {
      MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
      return;
    }
    await MUREO.loadStatus();
    renderAll();
    MUREO.toast(MUREO.t("dashboard.clear_all_success"), "success");
  }

  function wireBulkClearButton() {
    const btn = document.querySelector("[data-dashboard-clear-all]");
    if (!btn) return;
    btn.addEventListener("click", runBulkClear);
  }

  // ----- Demo section -------------------------------------------------

  async function loadDemoScenarios() {
    const select = document.querySelector("[data-demo-scenario]");
    if (!select) return;
    let body;
    try {
      const res = await fetch("/api/demo/scenarios");
      body = await res.json();
    } catch (_err) {
      return;
    }
    if (!body || body.status !== "ok" || !Array.isArray(body.scenarios)) {
      return;
    }
    while (select.firstChild) select.removeChild(select.firstChild);
    body.scenarios.forEach(function (sc) {
      const opt = document.createElement("option");
      opt.value = sc.name;
      // Prefer a localised title; MUREO.t returns the key verbatim when
      // missing, so an unknown scenario falls back to the API title.
      const titleKey = "demo.scenario." + sc.name;
      const localised = MUREO.t(titleKey);
      const title = localised === titleKey ? sc.title : localised;
      // Title only: sc.blurb is hardcoded English from the Python
      // scenario registry, so appending it would leave an English
      // tail on a Japanese option under locale=ja.
      opt.textContent = title;
      if (sc.default) opt.selected = true;
      select.appendChild(opt);
    });
  }

  function wireDemoCreate() {
    const btn = document.querySelector("[data-demo-create]");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const scenario = document.querySelector("[data-demo-scenario]");
      const targetNode = document.querySelector("[data-demo-target]");
      const resultNode = document.querySelector("[data-demo-result]");
      const target = targetNode ? targetNode.value.trim() : "";
      if (!target) {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.demo_target_required");
        }
        return;
      }
      if (resultNode) resultNode.textContent = MUREO.t("dashboard.demo_creating");
      let res;
      try {
        res = await MUREO.postJson("/api/demo/init", {
          scenario_name: scenario ? scenario.value : "",
          target: target,
          force: false,
          skip_import: false,
        });
      } catch (_err) {
        const msg = MUREO.t("dashboard.demo_failed", { detail: "network" });
        if (resultNode) resultNode.textContent = msg;
        // Inline result stays for scroll-anchored context; toast is the
        // scroll-resistant surface for operators scrolled to the bottom
        // of a long Dashboard (#184).
        MUREO.toast(msg, "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        const msg = MUREO.t("dashboard.demo_success", {
          path: data.created_path || target,
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "success");
      } else {
        const msg = MUREO.t("dashboard.demo_failed", {
          detail: (data && data.detail) || "error",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
      }
    });
  }

  function wireBrowseButton(buttonSelector, inputSelector, endpoint, body) {
    const btn = document.querySelector(buttonSelector);
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const input = document.querySelector(inputSelector);
      let res;
      try {
        res = await MUREO.postJson(endpoint, body);
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.picker_error"), "error");
        return;
      }
      const data = (res && res.body) || {};
      if (data.status === "ok" && data.path) {
        if (input) input.value = data.path;
      } else if (data.status === "cancelled") {
        return;
      } else {
        MUREO.toast(MUREO.t("dashboard.picker_error"), "error");
      }
    });
  }

  function wirePickers() {
    wireBrowseButton(
      "[data-demo-browse]",
      "[data-demo-target]",
      "/api/pick/directory",
      { title: MUREO.t("dashboard.browse") }
    );
    wireBrowseButton(
      "[data-byod-browse]",
      "[data-byod-file]",
      "/api/pick/file",
      { title: MUREO.t("dashboard.browse"), kind: "xlsx" }
    );
  }

  // ----- BYOD section -------------------------------------------------

  function byodModeLabel(mode) {
    if (mode === "byod") return MUREO.t("dashboard.byod_mode_byod");
    if (mode === "not_configured") {
      return MUREO.t("dashboard.byod_mode_not_configured");
    }
    return MUREO.t("dashboard.byod_mode_live");
  }

  function buildByodRemoveButton(platform) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.byod_remove");
    btn.setAttribute("data-i18n", "dashboard.byod_remove");
    btn.addEventListener("click", async function () {
      const confirmed = await MUREO.confirmAction(
        MUREO.t("dashboard.byod_confirm_remove", { platform: platform })
      );
      if (!confirmed) return;
      let res;
      try {
        res = await MUREO.postJson("/api/byod/remove", {
          google_ads: platform === "google_ads",
          meta_ads: platform === "meta_ads",
        });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"), "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status !== "error") {
        await renderByodStatus();
      } else {
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"), "error");
      }
    });
    return btn;
  }

  function appendByodRow(tbody, p) {
    const tr = document.createElement("tr");
    const platformCell = document.createElement("td");
    platformCell.textContent = p.platform;
    const modeCell = document.createElement("td");
    modeCell.textContent = byodModeLabel(p.mode);
    const detailCell = document.createElement("td");
    if (p.mode === "byod") {
      const range = p.date_range
        ? (p.date_range.start || "?") + ".." + (p.date_range.end || "?")
        : "";
      detailCell.textContent =
        (p.rows != null ? p.rows + " rows" : "") +
        (range ? " (" + range + ")" : "");
    }
    const actionCell = document.createElement("td");
    if (p.mode === "byod") {
      actionCell.appendChild(buildByodRemoveButton(p.platform));
    }
    tr.appendChild(platformCell);
    tr.appendChild(modeCell);
    tr.appendChild(detailCell);
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  }

  async function renderByodStatus() {
    const tbody = document.querySelector("[data-byod-status-body]");
    if (!tbody) return;
    let body;
    try {
      const res = await fetch("/api/byod/status");
      body = await res.json();
    } catch (_err) {
      return;
    }
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    if (!body || body.status !== "ok" || !Array.isArray(body.platforms)) {
      return;
    }
    body.platforms.forEach(function (p) {
      appendByodRow(tbody, p);
    });
  }

  function wireByodImport() {
    const btn = document.querySelector("[data-byod-import]");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const fileNode = document.querySelector("[data-byod-file]");
      const replaceNode = document.querySelector("[data-byod-replace]");
      const resultNode = document.querySelector("[data-byod-result]");
      const filePath = fileNode ? fileNode.value.trim() : "";
      if (!filePath) {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.byod_file_required");
        }
        return;
      }
      if (resultNode) {
        resultNode.textContent = MUREO.t("dashboard.byod_importing");
      }
      let res;
      try {
        res = await MUREO.postJson("/api/byod/import", {
          file_path: filePath,
          replace: replaceNode ? replaceNode.checked : false,
        });
      } catch (_err) {
        const msg = MUREO.t("dashboard.byod_import_failed", {
          detail: "network",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        const msg = MUREO.t("dashboard.byod_import_success");
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "success");
        await renderByodStatus();
      } else {
        const msg = MUREO.t("dashboard.byod_import_failed", {
          detail: (data && data.detail) || "error",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
      }
    });
  }

  async function runByodClear() {
    const ok1 = await MUREO.confirmAction(
      MUREO.t("dashboard.byod_confirm_clear_1")
    );
    if (!ok1) return;
    const ok2 = await MUREO.confirmAction(
      MUREO.t("dashboard.byod_confirm_clear_2")
    );
    if (!ok2) return;
    let res;
    try {
      res = await MUREO.postJson("/api/byod/clear", {});
    } catch (_err) {
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"), "error");
      return;
    }
    const data = (res && res.body) || {};
    if (res && res.ok && data.status !== "error") {
      MUREO.toast(MUREO.t("dashboard.byod_clear_success"), "success");
      await renderByodStatus();
    } else {
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"), "error");
    }
  }

  function wireByodClear() {
    const btn = document.querySelector("[data-byod-clear]");
    if (!btn) return;
    btn.addEventListener("click", runByodClear);
  }

  // mureo-native platforms (mureo ships native tools for these:
  // Google Ads, Meta Ads, Search Console — there is NO native GA4, so
  // GA4 is deliberately NOT a row here; it is an official-provider-only
  // platform). Search Console has no own credentials.json section — it
  // reuses the google_ads Google OAuth (adwords + webmasters scopes),
  // so it is a status-only row (configured ⇔ the shared Google OAuth is
  // present, which the wizard's Search Console step writes) with no
  // standalone Remove (removing it would nuke the shared Google sign-in
  // / Google Ads — done from the Google Ads row instead).
  const NATIVE_SECTIONS = [
    {
      key: "google_ads",
      section: "google_ads",
      labelKey: "wizard.platforms.google_ads",
      removable: true,
      configured: function (s, present) {
        return present.google_ads === true;
      },
    },
    {
      key: "meta_ads",
      section: "meta_ads",
      labelKey: "wizard.platforms.meta_ads",
      removable: true,
      configured: function (s, present) {
        return present.meta_ads === true;
      },
    },
    {
      key: "search_console",
      labelKey: "wizard.platforms.search_console",
      removable: false,
      noteKey: "dashboard.native_sc_row_note",
      configured: function (s) {
        return Boolean(
          s && s.credentials_oauth && s.credentials_oauth.google
        );
      },
    },
  ];

  function renderNativeSection(status) {
    const list = document.querySelector("[data-dashboard-native-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const present = (status && status.credentials_present) || {};
    let any = false;
    NATIVE_SECTIONS.forEach(function (row) {
      const configured = row.configured(status, present);
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.appendChild(statusMark(configured));
      label.appendChild(document.createTextNode(" "));
      // data-i18n on an INNER span only, so a locale re-translation
      // (which overwrites the node's textContent) can't wipe the mark.
      const labelText = document.createElement("span");
      labelText.textContent = MUREO.t(row.labelKey);
      labelText.setAttribute("data-i18n", row.labelKey);
      label.appendChild(labelText);
      li.appendChild(label);
      if (configured) any = true;
      if (configured && row.removable) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-secondary";
        btn.textContent = MUREO.t("dashboard.action_remove");
        btn.setAttribute("data-i18n", "dashboard.action_remove");
        btn.addEventListener("click", async function () {
          const ok = await MUREO.confirmAction(
            MUREO.t("dashboard.confirm_remove_credentials")
          );
          if (!ok) return;
          const res = await MUREO.postJson("/api/credentials/remove", {
            section: row.section,
          });
          if (res.ok) {
            await MUREO.loadStatus();
            renderAll();
          } else {
            MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
          }
        });
        li.appendChild(btn);
      }
      // Google Ads + Search Console share the one Google OAuth.
      if (configured && row.key === "google_ads") {
        const note = document.createElement("div");
        note.className = "dashboard-provider-hosted-note";
        note.textContent = MUREO.t("dashboard.native_sc_shared");
        note.setAttribute("data-i18n", "dashboard.native_sc_shared");
        li.appendChild(note);
      }
      // Search Console row: always explain the shared-sign-in coupling.
      if (row.noteKey) {
        const note = document.createElement("div");
        note.className = "dashboard-provider-hosted-note";
        note.textContent = MUREO.t(row.noteKey);
        note.setAttribute("data-i18n", row.noteKey);
        li.appendChild(note);
      }
      list.appendChild(li);
    });
    if (!any) {
      const none = document.createElement("li");
      none.className = "dashboard-provider-hosted-note";
      none.textContent = MUREO.t("dashboard.native_none");
      none.setAttribute("data-i18n", "dashboard.native_none");
      list.appendChild(none);
    }
  }

  // #229 — About tab: mureo version + every installed package that
  // contributes to mureo's plugin entry-point groups. Read-only; the
  // server payload carries only distribution names and versions.
  // Silent failure like renderByodStatus — the section is non-critical.
  async function renderAbout() {
    const versionNode = document.querySelector(
      "[data-dashboard-about-version]"
    );
    const tbody = document.querySelector("[data-about-packages-body]");
    if (!versionNode || !tbody) return;
    let body;
    try {
      const res = await fetch("/api/about");
      if (!res.ok) return;
      body = await res.json();
    } catch (_err) {
      return;
    }
    const mureoVersion =
      body && body.mureo && body.mureo.version ? body.mureo.version : "";
    versionNode.textContent = mureoVersion
      ? MUREO.t("dashboard.about_version", { version: mureoVersion })
      : "";
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    if (!body || !Array.isArray(body.packages)) return;
    body.packages.forEach(function (pkg) {
      const tr = document.createElement("tr");
      const nameCell = document.createElement("td");
      nameCell.textContent = pkg && pkg.name ? pkg.name : "";
      const versionCell = document.createElement("td");
      versionCell.textContent = pkg && pkg.version ? pkg.version : "";
      tr.appendChild(nameCell);
      tr.appendChild(versionCell);
      tbody.appendChild(tr);
    });
  }

  // #239 — background update check. Runs on dashboard load WITHOUT
  // blocking render: the menu shows immediately, and only once pip
  // reports ≥1 outdated mureo/plugin does the About nav item gain a red
  // indicator and the About tab populate its update area. Silent failure
  // like renderAbout — a degraded/errored check simply shows nothing.

  // Append a red "update available" badge to the About nav item (once).
  function setAboutNavBadge() {
    const navItem = document.querySelector('[data-dashboard-nav="about"]');
    if (!navItem) return;
    if (navItem.querySelector(".nav-badge-update")) return;
    const badge = document.createElement("span");
    badge.className = "nav-badge-update";
    badge.setAttribute("data-i18n", "dashboard.about_update_badge");
    badge.setAttribute("aria-label", MUREO.t("dashboard.about_update_badge"));
    badge.title = MUREO.t("dashboard.about_update_badge");
    badge.textContent = "●";
    navItem.appendChild(badge);
  }

  // Remove the red "update available" badge from the About nav item (if any).
  // Called when a check reports up-to-date and after a successful upgrade, so
  // the indicator never lingers once there is nothing left to update.
  function removeAboutNavBadge() {
    const navItem = document.querySelector('[data-dashboard-nav="about"]');
    if (!navItem) return;
    const badge = navItem.querySelector(".nav-badge-update");
    if (badge) navItem.removeChild(badge);
  }

  // Render one "name: installed → latest" list item (outdated → red).
  // textContent only — never innerHTML — so package names can't inject markup.
  function buildUpdateRow(pkg) {
    const li = document.createElement("li");
    li.className = "about-update-outdated";
    li.textContent = MUREO.t("dashboard.about_update_row", {
      name: pkg && pkg.name ? pkg.name : "",
      installed: pkg && pkg.installed ? pkg.installed : "",
      latest: pkg && pkg.latest ? pkg.latest : "",
    });
    return li;
  }

  // POST /api/upgrade (CSRF via MUREO.postJson). ONE click on "Update all"
  // runs the upgrade directly — no second confirm step. The server derives
  // the package list itself, so we send an empty body. Progress, success, and
  // failure all surface in the SAME summary line that showed "Updates are
  // available." so the operator sees the outcome where they were looking.
  let upgradeInProgress = false;
  async function runUpgrade() {
    if (upgradeInProgress) return;
    const button = document.querySelector("[data-about-update-button]");
    const summary = document.querySelector("[data-about-updates-summary]");
    const list = document.querySelector("[data-about-updates-list]");
    upgradeInProgress = true;
    if (button) button.disabled = true;
    if (summary) setSummary(summary, "dashboard.about_update_running");
    let res;
    try {
      res = await MUREO.postJson("/api/upgrade", {});
    } catch (_err) {
      res = null;
    }
    const ok = res && res.ok && res.body && res.body.status === "ok";
    if (!ok) {
      if (summary) setSummary(summary, "dashboard.about_update_failed");
      if (button) button.disabled = false;
      upgradeInProgress = false;
      return;
    }
    // Success: the on-disk version is now upgraded. Drop the outdated list,
    // the "Update all" button, and the nav badge.
    if (list) {
      while (list.firstChild) list.removeChild(list.firstChild);
    }
    if (button) {
      button.hidden = true;
      button.disabled = false;
    }
    removeAboutNavBadge();
    if (res.body.restarting) {
      // Always-on service: the daemon is restarting itself on the new code.
      // Show "restarting…", wait for it to come back, then reload so both the
      // UI and the running code are the new version — the operator does
      // nothing.
      if (summary) setSummary(summary, "dashboard.about_update_restarting");
      upgradeInProgress = false;
      pollServiceRestartThenReload(summary);
      return;
    }
    // Interactive mode (no supervisor): keep the manual "restart" prompt and
    // refresh the displayed (on-disk) version — the running process keeps the
    // old code until the operator restarts, which the message tells them.
    if (summary) setSummary(summary, "dashboard.about_update_done_restart");
    renderAbout();
    upgradeInProgress = false;
  }

  // Poll /api/ping until the daemon has clearly RESTARTED, then reload onto the
  // new version. "Clearly restarted" = the reported version changed, OR we saw
  // the server go DOWN and then come back UP (covers a plugin-only upgrade where
  // the mureo version is unchanged). Gating on those signals — rather than the
  // first 200 — avoids reloading onto the OLD process, which can still answer
  // briefly while it shuts down. Falls back to the manual prompt after 60s.
  async function pollServiceRestartThenReload(summary) {
    let oldVersion = null;
    try {
      const r = await fetch("/api/ping", { cache: "no-store" });
      if (r && r.ok) {
        const b = await r.json().catch(function () {
          return null;
        });
        oldVersion = b && b.version ? b.version : null;
      }
    } catch (_e) {
      // Already down — fine, we'll detect the come-back-up below.
    }
    let sawDown = false;
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      await sleep(1500);
      try {
        const res = await fetch("/api/ping", { cache: "no-store" });
        if (res && res.ok) {
          const body = await res.json().catch(function () {
            return null;
          });
          const version = body && body.version ? body.version : null;
          const versionChanged = oldVersion && version && version !== oldVersion;
          if (versionChanged || sawDown) {
            location.reload();
            return;
          }
        } else {
          sawDown = true;
        }
      } catch (_e) {
        sawDown = true; // down mid-restart — a restart is happening
      }
    }
    if (summary) setSummary(summary, "dashboard.about_update_done_restart");
  }

  // Wire the "Update all" button to upgrade DIRECTLY on click (one step — no
  // confirm panel). Idempotent (onclick, not addEventListener) so repeated
  // renders never stack handlers.
  function wireUpgradeButton() {
    const button = document.querySelector("[data-about-update-button]");
    if (!button) return;
    button.onclick = function () {
      runUpgrade();
    };
  }

  function setSummary(node, key) {
    node.textContent = MUREO.t(key);
    node.setAttribute("data-i18n", key);
  }

  // Apply an /api/updates envelope to the About update area, handling every
  // status: checking (a check is in flight), error (couldn't check), and ok
  // (up-to-date vs updates available). Extracted so the passive render and the
  // manual "check now" poll share one code path.
  function applyUpdatesBody(body) {
    const summary = document.querySelector("[data-about-updates-summary]");
    const list = document.querySelector("[data-about-updates-list]");
    const button = document.querySelector("[data-about-update-button]");
    if (!summary || !list || !button) return;
    if (!body || !body.status) return;
    if (body.status === "checking") {
      setSummary(summary, "dashboard.about_update_checking");
      return;
    }
    if (body.status !== "ok") {
      setSummary(summary, "dashboard.about_update_check_failed");
      button.hidden = true;
      return;
    }
    const outdated = Array.isArray(body.packages) ? body.packages : [];
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!body.any_update || outdated.length === 0) {
      setSummary(summary, "dashboard.about_up_to_date");
      button.hidden = true;
      // Up to date now — clear any stale "update available" nav badge.
      removeAboutNavBadge();
      return;
    }
    setSummary(summary, "dashboard.about_update_available");
    outdated.forEach(function (pkg) {
      list.appendChild(buildUpdateRow(pkg));
    });
    button.hidden = false;
    setAboutNavBadge();
    wireUpgradeButton();
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  // Wire the always-visible "check for updates" button. Idempotent (onclick,
  // not addEventListener) so repeated renders never stack handlers.
  function wireCheckButton() {
    const btn = document.querySelector("[data-about-check-button]");
    if (!btn) return;
    btn.onclick = function () {
      runCheckNow();
    };
  }

  // Poll GET /api/updates until the status settles (no longer "checking") or
  // the deadline passes, then apply the result. The check runs server-side on
  // a background thread and can take up to the pip timeout, so the deadline
  // comfortably exceeds it. ``updatePollActive`` coalesces callers so the
  // passive load (when the first fetch is still mid-check) and the manual
  // "check now" button share ONE poll instead of stacking two — and a double
  // renderAll() (#223) cannot start a second loop.
  // Poll cadence for the background update check. The server runs pip on a
  // worker thread (bounded by its own ~60s pip timeout), so a 75s deadline
  // comfortably outlasts it; 1.5s between polls keeps the UI responsive
  // without hammering the endpoint.
  const UPDATE_POLL_DEADLINE_MS = 75000;
  const UPDATE_POLL_INTERVAL_MS = 1500;
  let updatePollActive = false;
  async function pollUpdatesUntilSettled() {
    if (updatePollActive) return;
    updatePollActive = true;
    const summary = document.querySelector("[data-about-updates-summary]");
    try {
      if (summary) setSummary(summary, "dashboard.about_update_checking");
      let body = null;
      const deadline = Date.now() + UPDATE_POLL_DEADLINE_MS;
      while (Date.now() < deadline) {
        await sleep(UPDATE_POLL_INTERVAL_MS);
        try {
          const res = await fetch("/api/updates");
          body = res.ok ? await res.json() : null;
        } catch (_e) {
          body = null;
        }
        if (body && body.status && body.status !== "checking") break;
      }
      if (!body || body.status === "checking") {
        // Poll exhausted without the check settling — don't leave a stuck
        // "Checking…"; surface that it couldn't complete.
        if (summary) setSummary(summary, "dashboard.about_update_check_failed");
      } else {
        applyUpdatesBody(body);
      }
    } finally {
      // Always clear the guard — even if a render/DOM op throws — so the
      // feature can never wedge itself permanently.
      updatePollActive = false;
    }
  }

  // POST /api/updates/refresh to drop the cache and start a fresh pip check,
  // then poll until the status settles.
  async function runCheckNow() {
    if (updatePollActive) return;
    const btn = document.querySelector("[data-about-check-button]");
    if (btn) btn.disabled = true;
    try {
      try {
        await MUREO.postJson("/api/updates/refresh", {});
      } catch (_err) {
        // Even if the trigger POST fails, poll the cache: a periodic refresh
        // may already be in flight.
      }
      await pollUpdatesUntilSettled();
    } finally {
      // Re-enable the button no matter how the poll ends.
      if (btn) btn.disabled = false;
    }
  }

  async function renderUpdates() {
    const area = document.querySelector("[data-about-updates]");
    if (!area) return;
    // Always reveal the area so the "check for updates" button is available,
    // even when everything is up to date or the last check errored / was cold.
    area.hidden = false;
    wireCheckButton();
    let body = null;
    try {
      const res = await fetch("/api/updates");
      body = res.ok ? await res.json() : null;
    } catch (_err) {
      body = null;
    }
    // A cold/stale cache answers "checking" while the background pip check
    // runs (the server starts it on this very fetch). The passive load must
    // then poll until it settles — otherwise the summary is stuck on
    // "Checking…" forever, since only the manual button used to poll. Fire it
    // without awaiting so renderAll() is not blocked; it repaints the DOM when
    // the check completes.
    if (body && body.status === "checking") {
      pollUpdatesUntilSettled();
      return;
    }
    applyUpdatesBody(body);
  }

  function renderAll() {
    const status = MUREO.state.status;
    renderHostSection(status);
    renderBasicSection(status);
    renderNativeSection(status);
    renderProvidersSection(status);
    renderPluginCredentials();
    renderEnvVarsSection(status);
    loadDemoScenarios();
    renderByodStatus();
    renderAbout();
    renderUpdates();
  }

  // #223: monotonic render generation. renderPluginCredentials is async
  // (clear → await fetch → append); during init renderAll() runs twice, so
  // two calls can interleave and BOTH append, rendering every card twice.
  // Each call captures its generation and bails if a newer render started
  // while it awaited — so only the latest result ever clears + appends.
  let pluginRenderSeq = 0;

  // Plugin credentials section — one collapsible form per provider
  // declaring AccountCredentialField entries. Fetches once per render
  // call. secret=True fields render as type="password" and submit
  // blank → "keep existing value" per the helper's contract.
  async function renderPluginCredentials() {
    const container = document.querySelector(
      "[data-dashboard-plugin-credentials-list]"
    );
    if (!container) return;
    const seq = ++pluginRenderSeq;
    let plugins = [];
    try {
      const res = await fetch("/api/credentials/plugins", { credentials: "same-origin" });
      if (!res.ok) throw new Error("status " + res.status);
      const body = await res.json();
      plugins = Array.isArray(body.plugins) ? body.plugins : [];
    } catch (_e) {
      // Silent failure — section is non-critical. Other dashboard
      // sections continue to function.
      return;
    }
    // A newer render superseded us while we awaited — drop this stale
    // result so concurrent renders can't both append (#223).
    if (seq !== pluginRenderSeq) return;
    // Clear AFTER the await, immediately before appending, so the section
    // is never emptied by a render that then bails on the guard above.
    container.textContent = "";
    if (plugins.length === 0) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.setAttribute("data-i18n", "dashboard.plugin_credentials_empty");
      empty.textContent = MUREO.t("dashboard.plugin_credentials_empty");
      container.appendChild(empty);
      return;
    }
    plugins.forEach(function (plugin) {
      container.appendChild(buildPluginCredentialsForm(plugin));
    });
  }

  // Collect ``{name: value}`` from every input in a plugin form. Shared by
  // the manual-save and Authenticate-is-save submit paths.
  function gatherFormValues(form) {
    const values = {};
    Array.from(form.querySelectorAll("input")).forEach(function (input) {
      values[input.name] = input.value;
    });
    return values;
  }

  // #217 — read-only status row for an OAuth-obtained target field (the
  // refresh token is acquired via consent, never typed).
  function appendOAuthTargetStatus(form, field) {
    const row = document.createElement("p");
    row.className = "plugin-oauth-target muted";
    const rowLabel = document.createElement("span");
    rowLabel.textContent = field.display_name + ": ";
    const rowValue = document.createElement("span");
    rowValue.setAttribute("data-oauth-target-status", "");
    rowValue.textContent = MUREO.t("dashboard.plugin_oauth_target_unset");
    row.appendChild(rowLabel);
    row.appendChild(rowValue);
    form.appendChild(row);
  }

  // One editable credential input (text or masked secret) + optional hint.
  function appendCredentialInput(form, field) {
    const label = document.createElement("label");
    const labelText = document.createElement("span");
    labelText.textContent = field.display_name;
    if (field.required) labelText.textContent += " *";
    label.appendChild(labelText);
    const input = document.createElement("input");
    input.name = field.key;
    input.type = field.secret ? "password" : "text";
    // ``new-password`` defeats browser autofill of saved site passwords
    // into the per-account credential input — ``off`` is ignored by
    // Safari/Chrome on password inputs.
    input.autocomplete = field.secret ? "new-password" : "off";
    if (field.secret) {
      // #224: a secret value never round-trips to the browser — pre-fill
      // only the placeholder. A *configured* secret shows the
      // leave-blank-to-keep hint; an unset one shows its own placeholder.
      input.placeholder = field.configured
        ? MUREO.t("dashboard.plugin_credentials_secret_placeholder")
        : field.placeholder || "";
    } else {
      // #224: pre-fill the stored non-secret value (e.g. base_account_id)
      // so a restart shows the current config instead of a blank form.
      if (field.value) input.value = field.value;
      if (field.placeholder) input.placeholder = field.placeholder;
    }
    label.appendChild(input);
    if (field.description) {
      const hint = document.createElement("small");
      hint.className = "field-hint";
      hint.textContent = field.description;
      label.appendChild(hint);
    }
    form.appendChild(label);
  }

  // #216/#217 — OAuth card controls: the operator-supplied loopback
  // callback URL input + a single Authenticate-IS-save submit (no Save).
  function appendOAuthControls(form, plugin) {
    // Pre-fill the saved callback URL (surfaced by the list endpoint) or a
    // shown well-known default; the operator must register this exact URL
    // provider-side.
    const cbLabel = document.createElement("label");
    const cbText = document.createElement("span");
    cbText.textContent = MUREO.t("dashboard.plugin_oauth_callback_label");
    cbLabel.appendChild(cbText);
    const cbInput = document.createElement("input");
    cbInput.name = "oauth_callback_url";
    cbInput.type = "text";
    cbInput.autocomplete = "off";
    // Pre-fill priority: the operator's saved URL, then the provider's
    // declared canonical port (#220 — Yahoo et al. that pin an exact
    // redirect_uri), then a generic loopback default.
    cbInput.value =
      plugin.oauth_callback_url ||
      (plugin.oauth && plugin.oauth.default_callback_url) ||
      "http://127.0.0.1:8765/oauth/callback";
    cbLabel.appendChild(cbInput);
    const cbHint = document.createElement("small");
    cbHint.className = "field-hint";
    cbHint.textContent = MUREO.t("dashboard.plugin_oauth_callback_hint");
    cbLabel.appendChild(cbHint);
    form.appendChild(cbLabel);

    const authBtn = document.createElement("button");
    authBtn.type = "submit";
    authBtn.className = "btn btn-primary";
    authBtn.textContent = MUREO.t("dashboard.plugin_oauth_authenticate");
    form.appendChild(authBtn);
    const status = document.createElement("span");
    status.className = "plugin-oauth-status muted";
    form.appendChild(status);

    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      startPluginOAuth(
        plugin.provider_name,
        authBtn,
        status,
        gatherFormValues(form)
      );
    });
  }

  // Manual-entry provider (#201): a Save button that persists every field.
  function appendManualSave(form, plugin) {
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn btn-primary";
    submit.textContent = MUREO.t("dashboard.plugin_credentials_save");
    form.appendChild(submit);

    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      submitPluginCredentials(plugin.provider_name, gatherFormValues(form), form);
    });
  }

  function buildPluginCredentialsForm(plugin) {
    const wrap = document.createElement("details");
    wrap.className = "plugin-credentials-form";
    const summary = document.createElement("summary");
    summary.textContent = plugin.display_name;
    wrap.appendChild(summary);

    // ``oauth`` block ({target_field, client_id_field, client_secret_field})
    // is present only for a provider whose secret is obtained via the
    // authorization-code flow (#201). For those providers the card is
    // Authenticate-IS-save (#217): no Save button, the target_field is a
    // read-only status row, and the operator supplies the loopback callback
    // URL they registered (#216). Providers without it keep manual Save +
    // entry, unchanged.
    const oauth = plugin.oauth;
    const form = document.createElement("form");
    plugin.fields.forEach(function (field) {
      if (oauth && field.key === oauth.target_field) {
        appendOAuthTargetStatus(form, field);
      } else {
        appendCredentialInput(form, field);
      }
    });
    if (oauth) {
      appendOAuthControls(form, plugin);
    } else {
      appendManualSave(form, plugin);
    }
    wrap.appendChild(form);
    return wrap;
  }

  // #201/#216/#217 — start a plugin's authorization-code OAuth flow.
  // Authenticate IS save: the operator's current form values (client
  // id/secret + the registered loopback callback URL + any non-OAuth
  // field) are POSTed; the server validates the callback URL, binds its
  // port, and returns the external provider consent URL. We open it in a
  // new tab and poll for completion; on success the bridge persists the
  // form values together with the obtained token.
  async function startPluginOAuth(providerName, btn, statusNode, values) {
    btn.disabled = true;
    statusNode.textContent = MUREO.t("dashboard.plugin_oauth_connecting");
    const base =
      "/api/credentials/plugins/" + encodeURIComponent(providerName) + "/oauth";
    let res;
    try {
      res = await MUREO.postJson(base + "/start", { values: values || {} });
    } catch (_e) {
      res = null;
    }
    if (!res || !res.ok || !res.body || !res.body.url) {
      btn.disabled = false;
      statusNode.textContent = "";
      MUREO.toast(MUREO.t(oauthStartErrorKey(res)), "error");
      return;
    }
    window.open(res.body.url, "_blank", "noopener");
    pollPluginOAuth(base + "/status", btn, statusNode);
  }

  // Map a failed /oauth/start response to the most specific toast string
  // so the operator knows whether to save the client creds, fix the
  // callback URL (#216), or free the port — not just "failed".
  function oauthStartErrorKey(res) {
    const err = res && res.body && res.body.error;
    if (err === "client_credentials_missing")
      return "dashboard.plugin_oauth_save_client_first";
    if (err === "callback_url_invalid")
      return "dashboard.plugin_oauth_callback_invalid";
    if (err === "callback_port_unavailable")
      return "dashboard.plugin_oauth_port_unavailable";
    return "dashboard.plugin_oauth_failed";
  }

  function pollPluginOAuth(statusUrl, btn, statusNode) {
    const deadline = Date.now() + 5 * 60 * 1000;
    const timer = setInterval(async function () {
      if (Date.now() > deadline) {
        clearInterval(timer);
        btn.disabled = false;
        statusNode.textContent = "";
        return;
      }
      let data;
      try {
        const res = await fetch(statusUrl, { credentials: "same-origin" });
        if (!res.ok) return;
        data = await res.json();
      } catch (_e) {
        return;
      }
      if (data.success) {
        clearInterval(timer);
        btn.disabled = false;
        statusNode.textContent = MUREO.t("dashboard.plugin_oauth_connected");
        MUREO.toast(MUREO.t("dashboard.plugin_oauth_connected"), "success");
      } else if (data.error) {
        clearInterval(timer);
        btn.disabled = false;
        statusNode.textContent = "";
        MUREO.toast(MUREO.t("dashboard.plugin_oauth_failed"), "error");
      }
    }, 1500);
  }

  async function submitPluginCredentials(providerName, values, form) {
    let res;
    try {
      res = await MUREO.postJson("/api/credentials/plugins/save", {
        provider_name: providerName,
        values: values,
      });
    } catch (_e) {
      MUREO.toast(MUREO.t("dashboard.plugin_credentials_save_failed"), "error");
      return;
    }
    // ``postJson`` returns ``{ok, status: <HTTP code>, body}`` — the
    // server's logical ``"ok"`` envelope lives inside ``body.status``.
    if (res && res.ok && res.body && res.body.status === "ok") {
      MUREO.toast(MUREO.t("dashboard.plugin_credentials_saved"), "success");
      // Clear secret inputs so the next view starts from the "keep
      // existing" baseline rather than the just-typed plain text.
      Array.from(form.querySelectorAll('input[type="password"]')).forEach(
        function (input) {
          input.value = "";
        }
      );
    } else {
      MUREO.toast(MUREO.t("dashboard.plugin_credentials_save_failed"), "error");
    }
  }

  document.addEventListener("mureo:ready", function () {
    wireDashboardNav();
    wireEnvForm();
    wireRerunWizardButton();
    wireBulkClearButton();
    wireDemoCreate();
    wireByodImport();
    wireByodClear();
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
})();
