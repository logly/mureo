// dashboard.js — `#dashboard` route renderer.
// Surfaces installed providers, basic-setup parts, host, and the env-
// var form. Listens for `mureo:route_changed` to toggle visibility.
//
// Per-row [削除] buttons: each installed basic-setup row gets a delete
// button that confirms via MUREO.confirmAction, POSTs to the matching
// backend route, then re-fetches /api/status and re-renders. Errors
// surface via MUREO.toast — never an unhandled exception, never a stack
// trace in the DOM.
//
// [全削除] button: double-confirm bulk clear. Posts to
// /api/setup/basic/clear which intentionally does NOT touch
// ~/.mureo/credentials.json (per CTO decision #3, surfaced in the
// second confirmation dialog).

(function () {
  "use strict";

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

  function show() {
    document.querySelector("[data-wizard]").hidden = true;
    document.querySelector("[data-landing]").hidden = true;
    document.querySelector("[data-dashboard]").hidden = false;
  }

  function hide() {
    document.querySelector("[data-dashboard]").hidden = true;
  }

  function renderHostSection(status) {
    const node = document.querySelector("[data-dashboard-host-value]");
    if (node && status) node.textContent = status.host || "";
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
        MUREO.toast(MUREO.t("dashboard.remove_failed"));
        return;
      }
      if (!res || !res.ok) {
        MUREO.toast(MUREO.t("dashboard.remove_failed"));
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
    BASIC_ROWS.forEach(function (row) {
      const li = document.createElement("li");
      const installed = parts[row.key] === true;
      const labelSpan = document.createElement("span");
      labelSpan.textContent = (installed ? "✓ " : "✗ ") + MUREO.t(row.labelKey);
      li.appendChild(labelSpan);
      if (installed) {
        li.appendChild(buildBasicRemoveButton(row));
      }
      list.appendChild(li);
    });
  }

  function renderProvidersSection(status) {
    const list = document.querySelector("[data-dashboard-providers-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const providers = (status && status.providers_installed) || {};
    let anyNotInstalled = false;
    [
      "google-ads-official",
      "meta-ads-official",
      "ga4-official",
    ].forEach(function (pid) {
      const li = document.createElement("li");
      const installed = providers[pid];
      if (!installed) anyNotInstalled = true;
      const labelSpan = document.createElement("span");
      labelSpan.textContent =
        (installed ? "✓ " : "✗ ") + pid;
      li.appendChild(labelSpan);
      if (installed) {
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
            MUREO.toast("Operation failed");
          }
        });
        li.appendChild(removeBtn);
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
        MUREO.toast("Saved.");
        // Refresh to surface the freshly-saved value preview.
        await MUREO.loadStatus();
        renderEnvVarsSection(MUREO.state.status);
      } else {
        MUREO.toast("Save failed.");
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
      MUREO.toast(MUREO.t("dashboard.remove_failed"));
      return;
    }
    if (!res || !res.ok) {
      MUREO.toast(MUREO.t("dashboard.remove_failed"));
      return;
    }
    await MUREO.loadStatus();
    renderAll();
    MUREO.toast(MUREO.t("dashboard.clear_all_success"));
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
      opt.textContent = sc.title + " — " + sc.blurb;
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
      const skipNode = document.querySelector("[data-demo-skip-import]");
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
          skip_import: skipNode ? skipNode.checked : false,
        });
      } catch (_err) {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.demo_failed", {
            detail: "network",
          });
        }
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.demo_success", {
            path: data.created_path || target,
          });
        }
      } else if (resultNode) {
        resultNode.textContent = MUREO.t("dashboard.demo_failed", {
          detail: (data && data.detail) || "error",
        });
      }
    });
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
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"));
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status !== "error") {
        await renderByodStatus();
      } else {
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"));
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
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.byod_import_failed", {
            detail: "network",
          });
        }
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.byod_import_success");
        }
        await renderByodStatus();
      } else if (resultNode) {
        resultNode.textContent = MUREO.t("dashboard.byod_import_failed", {
          detail: (data && data.detail) || "error",
        });
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
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"));
      return;
    }
    const data = (res && res.body) || {};
    if (res && res.ok && data.status !== "error") {
      MUREO.toast(MUREO.t("dashboard.byod_clear_success"));
      await renderByodStatus();
    } else {
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"));
    }
  }

  function wireByodClear() {
    const btn = document.querySelector("[data-byod-clear]");
    if (!btn) return;
    btn.addEventListener("click", runByodClear);
  }

  function renderAll() {
    const status = MUREO.state.status;
    renderHostSection(status);
    renderBasicSection(status);
    renderProvidersSection(status);
    renderEnvVarsSection(status);
    loadDemoScenarios();
    renderByodStatus();
  }

  document.addEventListener("mureo:ready", function () {
    wireEnvForm();
    wireRerunWizardButton();
    wireBulkClearButton();
    wireDemoCreate();
    wireByodImport();
    wireByodClear();
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
})();
