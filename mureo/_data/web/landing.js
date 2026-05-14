// landing.js — Welcome (pre-wizard) section.
// Single CTA: "Start setup" button. Conditionally shows the legacy-
// commands cleanup notice if /api/status reports any legacy file
// present. Also handles the cleanup POST.

(function () {
  "use strict";

  function applyLegacyNoticeVisibility(status) {
    const notice = document.querySelector("[data-landing-legacy-notice]");
    if (!notice) return;
    notice.hidden = !(status && status.legacy_commands_present);
  }

  function showLandingIfFirstTime(status) {
    const landing = document.querySelector("[data-landing]");
    if (!landing) return;
    if (MUREO.isDashboardRoute()) {
      landing.hidden = true;
      return;
    }
    // If basic parts are fully installed AND no host-dependent wizard
    // state is missing, jump straight to the dashboard (re-run case).
    const fullyConfigured =
      status &&
      status.setup_parts &&
      status.setup_parts.mureo_mcp &&
      status.setup_parts.auth_hook &&
      status.setup_parts.skills;
    if (fullyConfigured) {
      MUREO.navigateToDashboard();
      landing.hidden = true;
      return;
    }
    landing.hidden = false;
  }

  function wireStartButton() {
    const btn = document.querySelector("[data-landing-start]");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const landing = document.querySelector("[data-landing]");
      if (landing) landing.hidden = true;
      document.dispatchEvent(
        new CustomEvent("mureo:wizard_start", { detail: {} })
      );
    });
  }

  function wireLegacyRemoveButton() {
    const btn = document.querySelector("[data-landing-legacy-remove]");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const confirmed = await MUREO.confirmAction(MUREO.t("landing.legacy_confirm"));
      if (!confirmed) return;
      const res = await MUREO.postJson("/api/legacy/cleanup", {});
      if (res.ok) {
        MUREO.toast(MUREO.t("landing.legacy_removed_toast"));
        const notice = document.querySelector("[data-landing-legacy-notice]");
        if (notice) notice.hidden = true;
      } else {
        MUREO.toast(MUREO.t("landing.legacy_remove_failed"));
      }
    });
  }

  function onReady(evt) {
    const status = evt.detail && evt.detail.state ? evt.detail.state.status : null;
    applyLegacyNoticeVisibility(status);
    showLandingIfFirstTime(status);
    wireStartButton();
    wireLegacyRemoveButton();
  }

  document.addEventListener("mureo:ready", onReady);
})();
