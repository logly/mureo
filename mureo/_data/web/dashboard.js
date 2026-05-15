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

  function renderAll() {
    const status = MUREO.state.status;
    renderHostSection(status);
    renderBasicSection(status);
    renderProvidersSection(status);
    renderEnvVarsSection(status);
  }

  document.addEventListener("mureo:ready", function () {
    wireEnvForm();
    wireRerunWizardButton();
    wireBulkClearButton();
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
