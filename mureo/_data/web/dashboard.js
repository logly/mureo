// dashboard.js — `#dashboard` route renderer.
// Surfaces installed providers, basic-setup parts, host, and the env-
// var form. Listens for `mureo:route_changed` to toggle visibility.

(function () {
  "use strict";

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

  function renderBasicSection(status) {
    const list = document.querySelector("[data-dashboard-basic-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const parts = (status && status.setup_parts) || {};
    [
      { key: "mureo_mcp", label: MUREO.t("wizard.basic.mureo_mcp") },
      { key: "auth_hook", label: MUREO.t("wizard.basic.auth_hook") },
      { key: "skills", label: MUREO.t("wizard.basic.skills") },
    ].forEach(function (part) {
      const li = document.createElement("li");
      const installed = parts[part.key];
      li.textContent =
        (installed ? "✓ " : "✗ ") + part.label;
      list.appendChild(li);
    });
  }

  function renderProvidersSection(status) {
    const list = document.querySelector("[data-dashboard-providers-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const providers = (status && status.providers_installed) || {};
    [
      "google-ads-official",
      "meta-ads-official",
      "ga4-official",
    ].forEach(function (pid) {
      const li = document.createElement("li");
      const installed = providers[pid];
      const labelSpan = document.createElement("span");
      labelSpan.textContent =
        (installed ? "✓ " : "✗ ") + pid;
      li.appendChild(labelSpan);
      const actionBtn = document.createElement("button");
      actionBtn.type = "button";
      actionBtn.textContent = installed
        ? MUREO.t("dashboard.action_remove")
        : MUREO.t("dashboard.action_install");
      actionBtn.addEventListener("click", async function () {
        const url = installed ? "/api/providers/remove" : "/api/providers/install";
        const res = await MUREO.postJson(url, { provider_id: pid });
        if (res.ok) {
          await MUREO.loadStatus();
          renderAll();
        } else {
          MUREO.toast("Operation failed");
        }
      });
      li.appendChild(actionBtn);
      list.appendChild(li);
    });
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
      } else {
        MUREO.toast("Save failed.");
      }
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

  function renderAll() {
    const status = MUREO.state.status;
    renderHostSection(status);
    renderBasicSection(status);
    renderProvidersSection(status);
  }

  document.addEventListener("mureo:ready", function () {
    wireEnvForm();
    wireRerunWizardButton();
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
