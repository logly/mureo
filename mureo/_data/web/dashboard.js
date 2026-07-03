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
  // of truth: catalog.py install_kind === "hosted_http": meta-ads-official
  // and tiktok-ads-official. Extend when a new hosted provider is added.
  const HOSTED_PROVIDER_IDS = ["meta-ads-official", "tiktok-ads-official"];

  // Per-hosted-provider setup note key, selected by the running host.
  // Meta is connector-only (its endpoint has no OAuth dynamic client
  // registration); TikTok DOES support DCR, so on Claude Code it is
  // registered directly with `claude mcp add` rather than a claude.ai
  // connector — hence a distinct note set. Missing/unknown host falls
  // back to the claude-code key.
  const HOSTED_NOTE_KEYS = {
    "meta-ads-official": {
      "claude-code": "dashboard.provider_hosted_oauth_note",
      "claude-desktop": "dashboard.provider_desktop_connectors_note",
      codex: "dashboard.provider_codex_hosted_na_note",
    },
    "tiktok-ads-official": {
      "claude-code": "dashboard.provider_tiktok_oauth_note",
      "claude-desktop": "dashboard.provider_tiktok_desktop_note",
      codex: "dashboard.provider_tiktok_codex_note",
    },
  };

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
        : status.host === "codex"
        ? "wizard.host.codex"
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
        // Send the client's known host so the server self-heals a session
        // whose host reset to the claude-code default after a daemon restart
        // (see handlers._resolve_host); otherwise the removal could target
        // the wrong host's config.
        res = await MUREO.postJson(row.removeUrl, {
          host: MUREO.state.status && MUREO.state.status.host,
        });
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
      "tiktok-ads-official",
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
      // they read as part of the same provider row (Meta or TikTok) —
      // not as separate bordered list items. Guarded so a missing
      // translation never echoes the key.
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
        // The setup note is provider- and host-specific (see
        // HOSTED_NOTE_KEYS): Meta is connector-only on every host; TikTok
        // registers directly on Claude Code (DCR) but still needs the
        // Connectors flow on Desktop.
        const noteKeys = HOSTED_NOTE_KEYS[pid];
        if (noteKeys) {
          const host = (status && status.host) || "claude-code";
          appendNote(noteKeys[host] || noteKeys["claude-code"]);
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
      // Send the client's known host so the server self-heals a stale/reset
      // session host (see handlers._resolve_host).
      res = await MUREO.postJson("/api/setup/basic/clear", {
        host: MUREO.state.status && MUREO.state.status.host,
      });
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

  // ----- Advanced: External advisor MCP -------------------------------

  // Parse a textarea of "one entry per line" into a trimmed string array,
  // dropping blank lines. Used for stdio args.
  function parseLines(text) {
    return (text || "")
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .filter(function (line) {
        return line.length > 0;
      });
  }

  // Parse a textarea of "KEY=VALUE" lines into an object. Blank lines and
  // lines without "=" are skipped. The first "=" splits key/value so a
  // value may itself contain "=".
  function parseKeyValueLines(text) {
    const out = {};
    parseLines(text).forEach(function (line) {
      const eq = line.indexOf("=");
      if (eq <= 0) return;
      const key = line.slice(0, eq).trim();
      const value = line.slice(eq + 1).trim();
      if (key) out[key] = value;
    });
    return out;
  }

  function buildAdvisorRemoveButton(name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.advisors_remove");
    btn.setAttribute("data-i18n", "dashboard.advisors_remove");
    btn.setAttribute("aria-label", MUREO.t("dashboard.advisors_remove"));
    btn.addEventListener("click", async function () {
      const ok = await MUREO.confirmAction(
        MUREO.t("dashboard.advisors_confirm_remove")
      );
      if (!ok) return;
      let res;
      try {
        res = await MUREO.postJson("/api/advisors/remove", { name: name });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.advisors_remove_failed"), "error");
        return;
      }
      const body = (res && res.body) || {};
      if (res && res.ok && body.status === "ok") {
        renderAdvisorsList(body.advisors);
        MUREO.toast(MUREO.t("dashboard.advisors_removed"), "success");
      } else {
        MUREO.toast(MUREO.t("dashboard.advisors_remove_failed"), "error");
      }
    });
    return btn;
  }

  // Render the advisor rows from a list payload (or [] when absent).
  function renderAdvisorsList(advisors) {
    const list = document.querySelector("[data-dashboard-advisors-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const rows = Array.isArray(advisors) ? advisors : [];
    if (rows.length === 0) {
      const empty = document.createElement("li");
      empty.className = "dashboard-provider-hosted-note";
      empty.textContent = MUREO.t("dashboard.advisors_empty");
      empty.setAttribute("data-i18n", "dashboard.advisors_empty");
      list.appendChild(empty);
      return;
    }
    rows.forEach(function (a) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      // textContent only — an advisor name / target is operator config but
      // must never be interpreted as markup.
      label.textContent =
        (a.name || "") + " — " + (a.transport || "") + " · " + (a.target || "");
      li.appendChild(label);
      li.appendChild(buildAdvisorRemoveButton(a.name || ""));
      list.appendChild(li);
    });
  }

  async function renderAdvisors() {
    const list = document.querySelector("[data-dashboard-advisors-list]");
    if (!list) return;
    let body;
    try {
      const res = await fetch("/api/advisors", { credentials: "same-origin" });
      if (!res.ok) return;
      body = await res.json();
    } catch (_err) {
      // Silent failure — the section is non-critical.
      return;
    }
    renderAdvisorsList(body && body.advisors);
  }

  // Toggle the stdio-only / remote-only field blocks based on transport.
  function syncAdvisorTransportFields(form) {
    const transport = form.querySelector("[data-advisor-transport]");
    const stdio = form.querySelector("[data-advisor-stdio-fields]");
    const remote = form.querySelector("[data-advisor-remote-fields]");
    if (!transport || !stdio || !remote) return;
    const isStdio = transport.value === "stdio";
    stdio.hidden = !isStdio;
    remote.hidden = isStdio;
  }

  // Map a failed /api/advisors/add response to the most specific toast.
  function advisorAddErrorKey(res) {
    const err = res && res.body && res.body.error;
    if (err === "duplicate_name") return "dashboard.advisors_err_duplicate_name";
    if (err === "invalid_advisor") return "dashboard.advisors_err_invalid";
    return "dashboard.advisors_add_failed";
  }

  function wireAdvisorForm() {
    const form = document.querySelector("[data-advisor-form]");
    if (!form) return;
    const transport = form.querySelector("[data-advisor-transport]");
    if (transport) {
      transport.addEventListener("change", function () {
        syncAdvisorTransportFields(form);
      });
    }
    syncAdvisorTransportFields(form);
    form.addEventListener("submit", async function (evt) {
      evt.preventDefault();
      const name = (form.querySelector("[data-advisor-name]").value || "").trim();
      const tool = (form.querySelector("[data-advisor-tool]").value || "").trim();
      if (!name) {
        MUREO.toast(MUREO.t("dashboard.advisors_name_required"), "error");
        return;
      }
      if (!tool) {
        MUREO.toast(MUREO.t("dashboard.advisors_tool_required"), "error");
        return;
      }
      const transportValue = transport ? transport.value : "stdio";
      const payload = { name: name, transport: transportValue, tool: tool };
      if (transportValue === "stdio") {
        payload.command = (
          form.querySelector("[data-advisor-command]").value || ""
        ).trim();
        payload.args = parseLines(form.querySelector("[data-advisor-args]").value);
        const env = parseKeyValueLines(
          form.querySelector("[data-advisor-env]").value
        );
        if (Object.keys(env).length > 0) payload.env = env;
      } else {
        payload.url = (form.querySelector("[data-advisor-url]").value || "").trim();
        const headers = parseKeyValueLines(
          form.querySelector("[data-advisor-headers]").value
        );
        if (Object.keys(headers).length > 0) payload.headers = headers;
      }
      let res;
      try {
        res = await MUREO.postJson("/api/advisors/add", payload);
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.advisors_add_failed"), "error");
        return;
      }
      const body = (res && res.body) || {};
      if (res && res.ok && body.status === "ok") {
        form.reset();
        syncAdvisorTransportFields(form);
        renderAdvisorsList(body.advisors);
        MUREO.toast(MUREO.t("dashboard.advisors_added"), "success");
      } else {
        MUREO.toast(MUREO.t(advisorAddErrorKey(res)), "error");
      }
    });
  }

  // ----------------------------------------------------------------------
  // Reports dashboard (read-only, STATE.json-sourced via /api/reports/*).
  //
  // Platform-agnostic: a KPI card is rendered for EVERY platform the API
  // returns — built-in google_ads/meta_ads AND plugin:<dist> bridges. A
  // platform with no synced metrics (totals null/empty) still gets a card
  // labelled "no synced metrics yet" instead of a broken/empty one.
  //
  // Period toggle (YESTERDAY default / LAST_30_DAYS): the summary carries a
  // `periods` union of the windows that have data; the toggle is rendered
  // ONLY for those, and only when there is a real choice (>= 2). Each call
  // requests `?period=`, and the cards show that window's totals. Overall
  // freshness still comes from last_synced_at ("synced N ago").
  // ----------------------------------------------------------------------

  // Canonical secondary KPI vocabulary → i18n label key. Headline (spend)
  // is rendered separately. Order here is the on-card display order.
  const REPORTS_KPI_LABELS = {
    conversions: "dashboard.reports_kpi_conversions",
    cpa: "dashboard.reports_kpi_cpa",
    ctr: "dashboard.reports_kpi_ctr",
    clicks: "dashboard.reports_kpi_clicks",
    impressions: "dashboard.reports_kpi_impressions",
  };

  // Canonical period token → i18n label key. Unknown tokens fall back to the
  // raw token (so a future window still renders a button, just unlocalized).
  const REPORTS_PERIOD_LABELS = {
    YESTERDAY: "dashboard.reports_period_yesterday",
    LAST_7_DAYS: "dashboard.reports_period_last_7_days",
    LAST_30_DAYS: "dashboard.reports_period_last_30_days",
  };

  function reportsPeriodLabel(token) {
    const key = REPORTS_PERIOD_LABELS[token];
    return key ? MUREO.t(key) : String(token);
  }

  // Report flags (reports.daily.flags) are free-form snake_case tags the
  // analysis skill authors (e.g. "cpa_over_target_logly"). Map the common
  // bases to friendly localized labels; anything unknown is humanized
  // generically so a raw snake_case token never reaches the operator. The
  // LONGEST matching base wins. Only the base label is shown — the trailing
  // remainder (a platform or a descriptor) is dropped: it was inconsistent
  // across flags and read as distracting, ambiguous parentheses. Detail
  // lives in the report narrative. The 3rd element is the chip severity
  // (is-warn / is-danger / is-success) so flags read as coloured tags:
  // off-target / setup gaps = warn (amber), data-integrity / runaway = danger
  // (red), on-target = success (green).
  const REPORTS_FLAG_BASES = [
    ["cpa_over_target", "dashboard.reports_flag_cpa_over_target", "is-warn"],
    ["cpa_under_target", "dashboard.reports_flag_cpa_under_target", "is-success"],
    ["cv_below_target", "dashboard.reports_flag_cv_below_target", "is-warn"],
    ["conversions_below_target", "dashboard.reports_flag_cv_below_target", "is-warn"],
    ["cv_above_target", "dashboard.reports_flag_cv_above_target", "is-success"],
    ["operation_mode_mismatch", "dashboard.reports_flag_operation_mode_mismatch", "is-warn"],
    ["low_cvr_lp_conversion", "dashboard.reports_flag_low_cvr_lp", "is-warn"],
    ["low_cvr", "dashboard.reports_flag_low_cvr", "is-warn"],
    ["sparse_conversions_tracking_suspect", "dashboard.reports_flag_tracking_suspect", "is-danger"],
    ["tracking_suspect", "dashboard.reports_flag_tracking_suspect", "is-danger"],
    ["zero_conversions", "dashboard.reports_flag_zero_conversions", "is-danger"],
    ["budget_overspend", "dashboard.reports_flag_budget_overspend", "is-danger"],
    ["spend_spike", "dashboard.reports_flag_spend_spike", "is-warn"],
    ["search_console_no", "dashboard.reports_flag_sc_no_property", "is-warn"],
  ];

  // snake_case tokens that read better upper-cased (metric acronyms).
  const REPORTS_FLAG_ACRONYMS = {
    cpa: "CPA",
    cpc: "CPC",
    cpm: "CPM",
    ctr: "CTR",
    cvr: "CVR",
    cv: "CV",
    roas: "ROAS",
    roi: "ROI",
    lp: "LP",
    ga4: "GA4",
    seo: "SEO",
    url: "URL",
  };

  function humanizeFlagWords(token) {
    const words = String(token == null ? "" : token)
      .split("_")
      .filter(Boolean)
      .map(function (w) {
        return REPORTS_FLAG_ACRONYMS[w] || w;
      });
    if (!words.length) return "";
    const s = words.join(" ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // The longest base entry that a bare-string flag matches (or null).
  function matchReportFlagBase(raw) {
    let best = null;
    for (let i = 0; i < REPORTS_FLAG_BASES.length; i++) {
      const base = REPORTS_FLAG_BASES[i][0];
      if (
        (raw === base || raw.indexOf(base + "_") === 0) &&
        (!best || base.length > best[0].length)
      ) {
        best = REPORTS_FLAG_BASES[i];
      }
    }
    return best;
  }

  function humanizeReportFlag(flag) {
    const raw = String(flag == null ? "" : flag);
    const best = matchReportFlagBase(raw);
    // A matched base shows only its localized label (no trailing context).
    return best ? MUREO.t(best[1]) : humanizeFlagWords(raw);
  }

  // Severity class for a flag's coloured chip. Object flags carry an explicit
  // level; a bare string uses its base entry's curated severity, falling back
  // to keyword inference (flagChipKind) for unmapped flags.
  function reportFlagKind(flag) {
    if (flag && typeof flag === "object") {
      return flagChipKind(flag.level || flag.kind);
    }
    const best = matchReportFlagBase(String(flag == null ? "" : flag));
    return (best && best[2]) || flagChipKind(flag);
  }

  // The selected window. Default = YESTERDAY (daily-check runs every day, so
  // the prior day is what an operator checks first). Reconciled against the
  // summary's `periods` union on each render — falls back to the first
  // available window when YESTERDAY has no data yet.
  let reportsPeriod = "YESTERDAY";

  // The client whose detail is on screen — so the period toggle re-fetches
  // the SAME client.
  let reportsActiveClient = null;

  // Reports navigation: "index" (the client overview grid) or "detail" (one
  // client's full report). A single-client (OSS) install has no index and
  // stays on "detail". The last-fetched client list is cached so a back /
  // period re-render does not need to re-resolve it.
  let reportsView = "index";
  let reportsClients = [];

  // Monotonic render generation (mirrors renderPluginCredentials #223):
  // the section clears then awaits a fetch, so an interleaved re-render
  // (locale change, client switch, period switch) must not let a stale
  // result append.
  let reportsRenderSeq = 0;

  // Humanize an ISO-8601 timestamp into a coarse "N ago" string. Falls
  // back to the raw string if it cannot be parsed (never throws).
  function relativeAge(iso) {
    if (!iso) return "";
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return String(iso);
    const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (secs < 60) return MUREO.t("dashboard.reports_age_just_now");
    const mins = Math.floor(secs / 60);
    if (mins < 60) return MUREO.t("dashboard.reports_age_minutes", { n: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return MUREO.t("dashboard.reports_age_hours", { n: hours });
    const days = Math.floor(hours / 24);
    return MUREO.t("dashboard.reports_age_days", { n: days });
  }

  // Format a raw number with thousands separators (no currency symbol —
  // the API returns raw numbers and we must not assume a currency). Non-
  // numbers pass through as plain text.
  function formatNumber(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value.toLocaleString();
    }
    return value == null ? "" : String(value);
  }

  // CTR is a ratio/percentage — render with up to 2 decimals + "%".
  function formatKpi(key, value) {
    if (key === "ctr" && typeof value === "number" && Number.isFinite(value)) {
      // Heuristic: a value <= 1 is a fraction (0.034 → 3.4%); otherwise it
      // is already a percentage figure from the platform. NOTE: totals are
      // platform-agnostic (built-in + arbitrary plugin:<dist> bridges) with no
      // guaranteed CTR-unit convention, so a bridge reporting "0.8" meaning
      // 0.8% would render as 80%. The real fix is normalizing CTR units in the
      // backend (PR-1) so the frontend doesn't guess; tracked as a follow-up.
      const pct = value <= 1 ? value * 100 : value;
      return pct.toLocaleString(undefined, { maximumFractionDigits: 2 }) + "%";
    }
    return formatNumber(value);
  }

  // Build one KPI card for a single platform entry.
  function buildReportCard(platform) {
    const card = document.createElement("article");
    card.className = "report-card";
    // Defensive: a null/non-object element in the platforms array must not
    // throw and break the whole render (Array.isArray guards the list, not
    // its elements).
    if (!platform || typeof platform !== "object") return card;

    const head = document.createElement("header");
    head.className = "report-card-head";
    const name = document.createElement("h3");
    name.className = "report-card-name";
    name.textContent = platform.display_name || platform.key || "";
    head.appendChild(name);
    const period = platform.metrics_period;
    if (period) {
      const periodEl = document.createElement("span");
      periodEl.className = "report-card-period";
      periodEl.textContent = String(period);
      head.appendChild(periodEl);
    }
    card.appendChild(head);

    const totals =
      platform.totals && typeof platform.totals === "object"
        ? platform.totals
        : null;
    const hasMetrics = totals && Object.keys(totals).length > 0;

    if (!hasMetrics) {
      // Advisory bridge / not-yet-synced platform: a deliberate, complete
      // card (display name + status + campaign count), never empty.
      const empty = document.createElement("p");
      empty.className = "report-card-empty";
      empty.textContent = MUREO.t("dashboard.reports_no_metrics");
      card.appendChild(empty);
      card.appendChild(buildReportCardFoot(platform));
      return card;
    }

    // Headline number: spend, large, mono so digits align.
    const headline = document.createElement("div");
    headline.className = "report-card-headline";
    const headlineValue = document.createElement("span");
    headlineValue.className = "report-card-headline-value";
    headlineValue.textContent = formatNumber(totals.spend != null ? totals.spend : 0);
    const headlineLabel = document.createElement("span");
    headlineLabel.className = "report-card-headline-label";
    headlineLabel.textContent = MUREO.t("dashboard.reports_kpi_spend");
    headline.appendChild(headlineValue);
    headline.appendChild(headlineLabel);
    card.appendChild(headline);

    // Secondary KPIs in a tidy 2-col grid — only those present in totals.
    const grid = document.createElement("dl");
    grid.className = "report-card-kpis";
    Object.keys(REPORTS_KPI_LABELS).forEach(function (key) {
      if (totals[key] == null) return;
      const term = document.createElement("dt");
      term.textContent = MUREO.t(REPORTS_KPI_LABELS[key]);
      const def = document.createElement("dd");
      def.textContent = formatKpi(key, totals[key]);
      grid.appendChild(term);
      grid.appendChild(def);
    });
    if (grid.childNodes.length > 0) card.appendChild(grid);

    card.appendChild(buildReportCardFoot(platform));
    return card;
  }

  // Card footer: campaign count + any free-form report flags as chips.
  function buildReportCardFoot(platform) {
    const foot = document.createElement("footer");
    foot.className = "report-card-foot";
    const count = document.createElement("span");
    count.className = "report-card-count";
    const n = typeof platform.campaign_count === "number" ? platform.campaign_count : 0;
    count.textContent = MUREO.t("dashboard.reports_campaign_count", { n: n });
    foot.appendChild(count);
    return foot;
  }

  // Map a free-form flag (string) to a chip kind. Defensive: any field may
  // be absent and the value may be an object with {level, label}.
  function flagChipKind(level) {
    const l = String(level || "").toLowerCase();
    if (l.indexOf("danger") >= 0 || l.indexOf("critical") >= 0 || l.indexOf("error") >= 0)
      return "is-danger";
    if (l.indexOf("warn") >= 0 || l.indexOf("watch") >= 0) return "is-warn";
    if (l.indexOf("ok") >= 0 || l.indexOf("good") >= 0 || l.indexOf("healthy") >= 0)
      return "is-success";
    return "";
  }

  // Render the "latest report" block from reports.{daily|weekly|goal}. The
  // object is free-form; render defensively (any field may be absent).
  function renderReportsLatest(reports) {
    const block = document.querySelector("[data-reports-latest]");
    const body = document.querySelector("[data-reports-latest-body]");
    if (!block || !body) return;
    body.textContent = "";
    const obj = reports && typeof reports === "object" ? reports : null;
    // Prefer daily → weekly → goal, whichever is present.
    const report = obj && (obj.daily || obj.weekly || obj.goal) ? obj.daily || obj.weekly || obj.goal : null;
    if (!report || typeof report !== "object") {
      block.hidden = true;
      return;
    }
    block.hidden = false;

    if (report.period) {
      const period = document.createElement("p");
      period.className = "report-latest-period";
      period.textContent = String(report.period);
      body.appendChild(period);
    }
    // Flags as small tinted chips (warn/danger/success).
    const flags = Array.isArray(report.flags) ? report.flags : [];
    if (flags.length > 0) {
      const chips = document.createElement("div");
      chips.className = "report-flags";
      flags.forEach(function (flag) {
        const isObj = flag && typeof flag === "object";
        // Object flags carry their own author-written label; a bare string is
        // a free-form snake_case code we humanize into a friendly label.
        const label = isObj
          ? flag.label || flag.message || flag.level || ""
          : humanizeReportFlag(flag);
        const chip = document.createElement("span");
        chip.className = "report-chip " + reportFlagKind(flag);
        chip.textContent = String(label);
        chips.appendChild(chip);
      });
      body.appendChild(chips);
    }
    if (report.narrative) {
      const narrative = document.createElement("p");
      narrative.className = "report-latest-narrative";
      narrative.textContent = String(report.narrative);
      body.appendChild(narrative);
    }
    if (report.generated_at) {
      const gen = document.createElement("p");
      gen.className = "report-latest-generated";
      gen.textContent = MUREO.t("dashboard.reports_generated", {
        ago: relativeAge(report.generated_at),
      });
      body.appendChild(gen);
    }
  }

  // Render the recent-actions list from the action log.
  function renderReportsActions(actions) {
    const block = document.querySelector("[data-reports-actions]");
    const list = document.querySelector("[data-reports-actions-list]");
    if (!block || !list) return;
    list.textContent = "";
    const rows = Array.isArray(actions) ? actions : [];
    if (rows.length === 0) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    rows.forEach(function (a) {
      const li = document.createElement("li");
      li.className = "report-action";
      const top = document.createElement("div");
      top.className = "report-action-top";
      const action = document.createElement("span");
      action.className = "report-action-name";
      action.textContent = a.action || "";
      const platform = document.createElement("span");
      platform.className = "report-action-platform";
      platform.textContent = a.platform || "";
      top.appendChild(action);
      top.appendChild(platform);
      li.appendChild(top);
      if (a.summary) {
        const summary = document.createElement("p");
        summary.className = "report-action-summary";
        summary.textContent = String(a.summary);
        li.appendChild(summary);
      }
      const meta = document.createElement("div");
      meta.className = "report-action-meta";
      if (a.timestamp) {
        const ts = document.createElement("span");
        ts.textContent = relativeAge(a.timestamp);
        meta.appendChild(ts);
      }
      if (a.observation_due) {
        const due = document.createElement("span");
        due.textContent = MUREO.t("dashboard.reports_observation_due", {
          date: String(a.observation_due),
        });
        meta.appendChild(due);
      }
      if (meta.childNodes.length > 0) li.appendChild(meta);
      list.appendChild(li);
    });
  }

  // ----------------------------------------------------------------------
  // Multi-client overview (#307): a card grid (one per client) replaces the
  // old single-select dropdown. Each card shows that client's headline KPIs
  // + latest report flags; clicking it loads the existing per-client detail.
  // ----------------------------------------------------------------------

  const REPORTS_CLIENT_FLAG_CAP = 3; // chips per card before collapsing to +N

  // Fetch JSON defensively — null on any failure / non-object body.
  async function fetchReportsJson(url) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return null;
      const body = await res.json();
      return body && typeof body === "object" ? body : null;
    } catch (_err) {
      return null;
    }
  }

  // Sum a client's headline KPIs across its platforms. null when absent so a
  // missing metric reads as "—" rather than a misleading zero.
  function aggregateClientKpis(summary) {
    const platforms =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    let spend = 0;
    let conv = 0;
    let hasSpend = false;
    let hasConv = false;
    platforms.forEach(function (p) {
      const t = p && typeof p.totals === "object" ? p.totals : null;
      if (!t) return;
      if (typeof t.spend === "number" && isFinite(t.spend)) {
        spend += t.spend;
        hasSpend = true;
      }
      if (typeof t.conversions === "number" && isFinite(t.conversions)) {
        conv += t.conversions;
        hasConv = true;
      }
    });
    return {
      spend: hasSpend ? spend : null,
      conversions: hasConv ? conv : null,
      cpa: hasSpend && hasConv && conv > 0 ? spend / conv : null,
    };
  }

  // Flags from a client's latest report (daily → weekly → goal).
  function clientReportFlags(summary) {
    const reports =
      summary && typeof summary.reports === "object" ? summary.reports : null;
    if (!reports) return [];
    const r = reports.daily || reports.weekly || reports.goal;
    return r && Array.isArray(r.flags) ? r.flags : [];
  }

  // Sort flags danger → warn → success → neutral (most urgent first).
  const REPORTS_FLAG_SEVERITY_ORDER = ["is-danger", "is-warn", "is-success", ""];
  function flagSeverityRank(flag) {
    const idx = REPORTS_FLAG_SEVERITY_ORDER.indexOf(reportFlagKind(flag));
    return idx === -1 ? REPORTS_FLAG_SEVERITY_ORDER.length : idx;
  }

  // Fetch a client's summary for its overview card. Honours the period toggle,
  // and when the selected window has no totals (a period-bucketed client whose
  // passthrough rollup is blank) falls back to the first window with data.
  async function fetchClientCardSummary(slug) {
    function summaryUrl(period) {
      const params = [];
      if (slug) params.push("client=" + encodeURIComponent(slug));
      if (period) params.push("period=" + encodeURIComponent(period));
      return (
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "")
      );
    }
    let summary = (await fetchReportsJson(summaryUrl(reportsPeriod))) || {};
    const kpis = aggregateClientKpis(summary);
    const periods = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    if (kpis.spend == null && kpis.conversions == null && periods.length) {
      const fallback = periods.indexOf(reportsPeriod) === -1 ? periods[0] : null;
      if (fallback) {
        const alt = await fetchReportsJson(summaryUrl(fallback));
        if (alt) summary = alt;
      }
    }
    return summary;
  }

  function clientKpiCell(labelKey, value) {
    const cell = document.createElement("div");
    cell.className = "reports-client-kpi";
    const v = document.createElement("span");
    v.className = "reports-client-kpi-value";
    v.textContent = value;
    const l = document.createElement("span");
    l.className = "reports-client-kpi-label";
    l.textContent = MUREO.t(labelKey);
    cell.appendChild(v);
    cell.appendChild(l);
    return cell;
  }

  function buildClientCard(client, summary) {
    const slug = client && client.slug ? client.slug : "";
    const card = document.createElement("button");
    card.type = "button";
    card.className = "reports-client-card";
    card.setAttribute("role", "listitem");
    card.setAttribute("data-client", slug);

    const head = document.createElement("div");
    head.className = "reports-client-card-head";
    const name = document.createElement("span");
    name.className = "reports-client-card-name";
    name.textContent = (client && (client.name || client.slug)) || "";
    head.appendChild(name);
    const fresh = document.createElement("span");
    fresh.className = "reports-client-card-fresh";
    fresh.textContent =
      summary && summary.last_synced_at ? relativeAge(summary.last_synced_at) : "";
    head.appendChild(fresh);
    card.appendChild(head);

    const kpis = aggregateClientKpis(summary);
    const krow = document.createElement("div");
    krow.className = "reports-client-card-kpis";
    krow.appendChild(
      clientKpiCell(
        "dashboard.reports_kpi_spend",
        // "—" (not 0) when absent — a no-data client must not read as zero
        // spend in this at-a-glance triage view.
        kpis.spend != null ? formatNumber(kpis.spend) : "—"
      )
    );
    if (kpis.conversions != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_conversions",
          formatNumber(kpis.conversions)
        )
      );
    }
    if (kpis.cpa != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_cpa",
          formatNumber(Math.round(kpis.cpa))
        )
      );
    }
    card.appendChild(krow);

    const flags = clientReportFlags(summary)
      .slice()
      .sort(function (a, b) {
        return flagSeverityRank(a) - flagSeverityRank(b);
      });
    if (flags.length) {
      const chips = document.createElement("div");
      chips.className = "reports-client-card-flags";
      flags.slice(0, REPORTS_CLIENT_FLAG_CAP).forEach(function (flag) {
        const chip = document.createElement("span");
        chip.className = "report-chip " + reportFlagKind(flag);
        chip.textContent = humanizeReportFlag(flag);
        chips.appendChild(chip);
      });
      const overflow = flags.length - REPORTS_CLIENT_FLAG_CAP;
      if (overflow > 0) {
        const more = document.createElement("span");
        more.className = "report-chip reports-client-flag-more";
        more.textContent = "+" + overflow;
        chips.appendChild(more);
      }
      card.appendChild(chips);
    }

    card.addEventListener("click", function () {
      reportsActiveClient = slug;
      showReportsClientDetail(slug);
    });
    return card;
  }

  // Default slug for a client list: the first active client, else the first.
  function defaultClientSlug(rows) {
    if (!rows.length) return null;
    const active = rows.find(function (c) {
      return c && c.active;
    });
    return ((active || rows[0]) || {}).slug || null;
  }

  // Toggle the index (client grid) vs detail (one client) views, and the
  // detail's back bar (only meaningful when there is an index to return to).
  function setReportsView(view) {
    reportsView = view;
    const index = document.querySelector("[data-reports-clients]");
    const detail = document.querySelector("[data-reports-detail]");
    const back = document.querySelector("[data-reports-back]");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (index) index.hidden = view !== "index";
    if (detail) detail.hidden = view !== "detail";
    // The back link (under the "Reports" heading) and the client-name heading
    // appear only in a multi-client detail view — an OSS single client has no
    // index to go back to and no sibling to disambiguate.
    const showClientChrome = view === "detail" && reportsClients.length > 1;
    if (back) back.hidden = !showClientChrome;
    if (nameEl) nameEl.hidden = !showClientChrome;
  }

  // INDEX view: a card per client (KPIs + flags for the selected window).
  // Fetches each client's summary in parallel; a period toggle built from the
  // union of windows lets the operator triage by Yesterday / Last 30 days.
  async function renderReportsIndex(seq) {
    const wrap = document.querySelector("[data-reports-clients]");
    if (!wrap) return;
    const rows = reportsClients;
    const summaries = await Promise.all(
      rows.map(function (c) {
        return fetchClientCardSummary(c && c.slug ? c.slug : "");
      })
    );
    if (seq !== reportsRenderSeq) return; // superseded by a newer render
    // Commit the view switch only once the data is ready — switching before
    // the await would expose an empty index grid if this render is superseded.
    setReportsView("index");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (freshness) freshness.textContent = "";
    wrap.textContent = "";
    rows.forEach(function (c, i) {
      wrap.appendChild(buildClientCard(c, summaries[i]));
    });
    // Period toggle from the union of windows any client advertises.
    const union = [];
    summaries.forEach(function (s) {
      (s && Array.isArray(s.periods) ? s.periods : []).forEach(function (p) {
        if (typeof p === "string" && p && union.indexOf(p) === -1) union.push(p);
      });
    });
    renderReportsPeriodToggle(union);
  }

  // DETAIL view: one client's full report (per-platform KPIs, latest report,
  // recent activity, period toggle). Sets the back bar + client name.
  function showReportsClientDetail(slug) {
    setReportsView("detail");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (nameEl) {
      const c = reportsClients.find(function (r) {
        return r && r.slug === slug;
      });
      nameEl.textContent = c ? c.name || c.slug || "" : "";
    }
    // Bump the generation so any in-flight render is dropped, then load.
    reportsRenderSeq++;
    renderReportsSummary(slug || null);
  }

  // Render the period toggle from the summary's `periods` union. Shown only
  // when there is a real choice (>= 2 windows); a single-window account has
  // nothing to switch, so the toggle stays hidden. Buttons are recreated on
  // every render, so their click handlers never accumulate.
  function renderReportsPeriodToggle(periods) {
    const wrap = document.querySelector("[data-reports-period]");
    if (!wrap) return;
    const list = Array.isArray(periods)
      ? periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    wrap.textContent = "";
    if (list.length < 2) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    list.forEach(function (token) {
      const active = token === reportsPeriod;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "reports-period-btn" + (active ? " is-active" : "");
      btn.setAttribute("data-period", token);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.textContent = reportsPeriodLabel(token);
      btn.addEventListener("click", function () {
        if (token === reportsPeriod) return;
        reportsPeriod = token;
        // Re-render the CURRENT view for the new window: the index re-fetches
        // every client's card, the detail re-fetches the selected client.
        // renderReports() preserves the active view + client via state.
        renderReports();
      });
      wrap.appendChild(btn);
    });
  }

  // Fetch + render the summary for a given client (or the default one).
  async function renderReportsSummary(client) {
    const seq = reportsRenderSeq;
    // NB: reportsActiveClient is set only after the stale-render guards below,
    // so a superseded call can never reset it to a no-longer-shown client
    // (which would make the period toggle re-fetch the wrong one).
    const cards = document.querySelector("[data-reports-cards]");
    const empty = document.querySelector("[data-reports-empty]");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (!cards) return;

    let summary;
    try {
      const params = [];
      if (client) params.push("client=" + encodeURIComponent(client));
      if (reportsPeriod) params.push("period=" + encodeURIComponent(reportsPeriod));
      const url =
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "");
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      summary = await res.json();
    } catch (_err) {
      // Fetch/parse failed. Clear any prior render so a failed client switch
      // never leaves a different client's numbers on screen — degrade to the
      // empty state rather than stale data.
      if (seq !== reportsRenderSeq) return;
      reportsActiveClient = client || null;
      cards.textContent = "";
      if (freshness) freshness.textContent = "";
      renderReportsPeriodToggle([]);
      renderReportsLatest(null);
      renderReportsActions(null);
      if (empty) empty.hidden = false;
      return;
    }
    if (seq !== reportsRenderSeq) return; // Superseded by a newer render.
    reportsActiveClient = client || null;
    // A 200 whose body is not a JSON object (null / string / number from a
    // misbehaving backend or proxy) must not crash the render — coerce to an
    // empty summary so the guarded accessors below fall back to the empty state.
    if (!summary || typeof summary !== "object") summary = {};

    // Reconcile the selected window against the windows that actually carry
    // data. When the preferred window (YESTERDAY) has nothing yet, fall back
    // to the first available and re-fetch ONCE — the corrected period is
    // guaranteed to be in `available`, so the re-entry can't loop.
    const available = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    if (available.length && available.indexOf(reportsPeriod) === -1) {
      reportsPeriod =
        available.indexOf("YESTERDAY") !== -1 ? "YESTERDAY" : available[0];
      return renderReportsSummary(client);
    }
    renderReportsPeriodToggle(available);

    cards.textContent = "";

    const platforms = Array.isArray(summary.platforms) ? summary.platforms : [];
    if (freshness) {
      freshness.textContent = summary.last_synced_at
        ? MUREO.t("dashboard.reports_synced", {
            ago: relativeAge(summary.last_synced_at),
          })
        : "";
    }

    if (platforms.length === 0) {
      if (empty) empty.hidden = false;
    } else {
      if (empty) empty.hidden = true;
      platforms.forEach(function (p) {
        cards.appendChild(buildReportCard(p));
      });
    }

    renderReportsLatest(summary.reports);
    renderReportsActions(summary.recent_actions);
  }

  // Entry point: fetch the client list, then show the right view. Re-runnable
  // (tab open, locale / period change, navigation). Routing:
  //   • 0–1 client (OSS)  → detail of the single client; no index, no back.
  //   • >1 client (Agency) → keep the current view across re-renders, defaulting
  //     to the index on first entry (or when the selected client disappears).
  async function renderReports() {
    const cards = document.querySelector("[data-reports-cards]");
    if (!cards) return;
    const seq = ++reportsRenderSeq;
    const body = await fetchReportsJson("/api/reports/clients");
    if (seq !== reportsRenderSeq) return;
    reportsClients = body && Array.isArray(body.clients) ? body.clients : [];

    if (reportsClients.length <= 1) {
      // OSS single workspace: no index page — open the detail directly.
      // showReportsClientDetail() sets the view + syncs the DOM.
      reportsActiveClient = defaultClientSlug(reportsClients);
      showReportsClientDetail(reportsActiveClient);
      return;
    }

    const selectionAlive =
      reportsActiveClient &&
      reportsClients.some(function (c) {
        return c && c.slug === reportsActiveClient;
      });
    if (reportsView === "detail" && selectionAlive) {
      showReportsClientDetail(reportsActiveClient);
    } else {
      await renderReportsIndex(seq);
    }
  }

  // Wire the back-to-index button once. Re-fetches the client list (a fresh
  // sync may have changed it) and shows the index.
  function wireReportsBackButton() {
    const back = document.querySelector("[data-reports-back]");
    if (!back) return;
    back.addEventListener("click", function () {
      reportsView = "index";
      renderReports();
    });
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
    renderAdvisors();
    renderReports();
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
      // #336 — skip the account-picker radios (UI-only, grouped by a
      // non-field name): they must not leak into the OAuth
      // Authenticate-is-save payload. The chosen account rides on the
      // hidden input named after the field key, which is collected here.
      if (input.type === "radio") return;
      values[input.name] = input.value;
    });
    return values;
  }

  // #217/#338 — read-only status row for an OAuth-obtained target field
  // (the token is acquired via consent, never typed). #338: reflect the
  // stored state — a configured token shows "Configured ✓" instead of the
  // "click Authenticate" prompt, so the operator isn't told to re-auth an
  // already-connected provider.
  function appendOAuthTargetStatus(form, field) {
    const row = document.createElement("p");
    row.className = "plugin-oauth-target muted";
    const rowLabel = document.createElement("span");
    rowLabel.textContent = field.display_name + ": ";
    const rowValue = document.createElement("span");
    rowValue.setAttribute("data-oauth-target-status", "");
    rowValue.textContent = field.configured
      ? MUREO.t("dashboard.plugin_oauth_target_configured")
      : MUREO.t("dashboard.plugin_oauth_target_unset");
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
    // #336 — whether the OAuth token is already stored. The post-auth
    // account picker can only enumerate once a token exists, so its Load
    // control stays disabled until then.
    let authConfigured = false;
    if (oauth) {
      const tf = plugin.fields.find(function (f) {
        return f.key === oauth.target_field;
      });
      authConfigured = !!(tf && tf.configured);
    }
    plugin.fields.forEach(function (field) {
      if (oauth && field.key === oauth.target_field) {
        appendOAuthTargetStatus(form, field);
      } else if (
        oauth &&
        oauth.has_account_lister &&
        field.key === oauth.accounts_field
      ) {
        // #336 — render this field as a post-auth account picker instead
        // of a free-text input (the operator chooses from the accounts the
        // obtained token can reach).
        appendAccountPicker(form, plugin, field, authConfigured);
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

  // #336 — post-auth account picker for an OAuth provider's accounts_field.
  // A hidden input carries the chosen id (so the OAuth card's existing
  // gatherFormValues sees it); a Load button fetches the accounts the
  // obtained token can reach and renders them as radios; a dedicated Save
  // (type="button", so it never triggers the card's Authenticate submit)
  // persists just the chosen id. Load is disabled until a token exists.
  function appendAccountPicker(form, plugin, field, authConfigured) {
    const label = document.createElement("label");
    const labelText = document.createElement("span");
    labelText.textContent = field.display_name;
    if (field.required) labelText.textContent += " *";
    label.appendChild(labelText);

    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = field.key;
    if (field.value) hidden.value = field.value;
    label.appendChild(hidden);

    const current = document.createElement("span");
    current.className = "plugin-account-current muted";
    current.setAttribute("data-account-current", "");
    current.textContent = field.value || MUREO.t("dashboard.plugin_account_none");
    label.appendChild(current);

    if (field.description) {
      const hint = document.createElement("small");
      hint.className = "field-hint";
      hint.textContent = field.description;
      label.appendChild(hint);
    }
    form.appendChild(label);

    const loadBtn = document.createElement("button");
    loadBtn.type = "button";
    loadBtn.className = "btn";
    loadBtn.textContent = MUREO.t("dashboard.plugin_accounts_load");
    loadBtn.disabled = !authConfigured;
    form.appendChild(loadBtn);

    const status = document.createElement("span");
    status.className = "plugin-accounts-status muted";
    status.setAttribute("data-accounts-status", "");
    if (!authConfigured) {
      status.textContent = MUREO.t("dashboard.plugin_accounts_authenticate_first");
    }
    form.appendChild(status);

    const options = document.createElement("div");
    options.className = "plugin-accounts-options";
    options.setAttribute("data-account-options", "");
    form.appendChild(options);

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-primary plugin-account-save";
    saveBtn.textContent = MUREO.t("dashboard.plugin_accounts_save");
    saveBtn.disabled = true;
    form.appendChild(saveBtn);

    const ui = { loadBtn, status, options, hidden, current, saveBtn, field };
    loadBtn.addEventListener("click", function () {
      loadPluginAccounts(plugin.provider_name, ui);
    });
    saveBtn.addEventListener("click", function () {
      savePluginAccount(plugin.provider_name, field.key, hidden.value, ui);
    });
  }

  // Map a failed /accounts response error code to the clearest toast.
  function accountsErrorKey(err) {
    if (err === "not_authenticated")
      return "dashboard.plugin_accounts_authenticate_first";
    return "dashboard.plugin_accounts_failed";
  }

  async function loadPluginAccounts(providerName, ui) {
    ui.loadBtn.disabled = true;
    ui.status.textContent = MUREO.t("dashboard.plugin_accounts_loading");
    ui.options.textContent = "";
    let res;
    let body = {};
    try {
      res = await fetch(
        "/api/credentials/plugins/" +
          encodeURIComponent(providerName) +
          "/accounts",
        { credentials: "same-origin" }
      );
      body = await res.json().catch(function () {
        return {};
      });
    } catch (_e) {
      ui.loadBtn.disabled = false;
      ui.status.textContent = "";
      MUREO.toast(MUREO.t("dashboard.plugin_accounts_failed"), "error");
      return;
    }
    ui.loadBtn.disabled = false;
    if (!res.ok) {
      ui.status.textContent = "";
      MUREO.toast(MUREO.t(accountsErrorKey(body.error)), "error");
      return;
    }
    const accounts = Array.isArray(body.accounts) ? body.accounts : [];
    if (accounts.length === 0) {
      ui.status.textContent = MUREO.t("dashboard.plugin_accounts_empty");
      return;
    }
    ui.status.textContent = "";
    renderAccountRadios(accounts, ui);
  }

  function renderAccountRadios(accounts, ui) {
    ui.options.textContent = "";
    const groupName = "account_pick_" + ui.field.key;
    accounts.forEach(function (acct) {
      const row = document.createElement("label");
      row.className = "plugin-account-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = groupName;
      radio.value = acct.id;
      if (acct.id === ui.hidden.value) {
        // Pre-select the stored account. Programmatic `checked` does NOT
        // fire `change`, so enable Save here too — otherwise a re-load of
        // an already-saved account leaves Save permanently disabled.
        radio.checked = true;
        ui.saveBtn.disabled = false;
      }
      radio.addEventListener("change", function () {
        ui.hidden.value = acct.id;
        ui.current.textContent = acct.name || acct.id;
        ui.saveBtn.disabled = false;
      });
      const text = document.createElement("span");
      text.textContent =
        acct.name && acct.name !== acct.id
          ? acct.name + " (" + acct.id + ")"
          : acct.id;
      row.appendChild(radio);
      row.appendChild(text);
      ui.options.appendChild(row);
    });
  }

  async function savePluginAccount(providerName, key, value, ui) {
    if (!value) {
      MUREO.toast(MUREO.t("dashboard.plugin_accounts_pick_first"), "error");
      return;
    }
    // Disable during the in-flight request so a double-click can't fire two
    // concurrent saves; re-enabled on failure, kept disabled on success.
    ui.saveBtn.disabled = true;
    const values = {};
    values[key] = value;
    let res;
    try {
      res = await MUREO.postJson("/api/credentials/plugins/save", {
        provider_name: providerName,
        values: values,
      });
    } catch (_e) {
      ui.saveBtn.disabled = false;
      MUREO.toast(MUREO.t("dashboard.plugin_credentials_save_failed"), "error");
      return;
    }
    if (res && res.ok && res.body && res.body.status === "ok") {
      ui.saveBtn.disabled = true;
      MUREO.toast(MUREO.t("dashboard.plugin_accounts_saved"), "success");
    } else {
      ui.saveBtn.disabled = false;
      MUREO.toast(MUREO.t("dashboard.plugin_credentials_save_failed"), "error");
    }
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
        // #336/#338 — refresh the section so the target shows "Configured ✓"
        // and the account picker's Load control becomes usable now that a
        // token exists.
        renderPluginCredentials();
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
})();
