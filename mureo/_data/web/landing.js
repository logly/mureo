// landing.js — Welcome (pre-wizard) section.
// Single CTA: "Start setup" button.

(function () {
  "use strict";

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

  function onReady(evt) {
    const status = evt.detail && evt.detail.state ? evt.detail.state.status : null;
    showLandingIfFirstTime(status);
    wireStartButton();
  }

  document.addEventListener("mureo:ready", onReady);
})();
