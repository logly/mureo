// dashboard_ops_history.js — the ops history switch (#848).
//
// `settings.ops_history.enabled` in STATE.json. While it is on, every
// mutating call must carry a reason and an expected effect, so the card
// renders what the SERVER says the file holds and re-renders from the
// server's answer after a save: an operator must never believe the
// requirement is off when it is on, or the other way round.
//
// One workspace, one file, like the Guardrails card above it: the card
// reads and writes the active workspace's STATE.json and sends nothing
// that names another workspace. A backend with a roster is served the page
// without it (`mureo/web/app_html.py`), so render and wire are guarded on
// the card being PRESENT and do nothing at all on a page without it.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_OPS_HISTORY`. Loads BEFORE dashboard.js.

(function () {
  "use strict";

  const ENDPOINT = "/api/settings/ops_history";
  const ON = "on";
  const OFF = "off";

  function node(selector) {
    return document.querySelector(selector);
  }

  function setResult(text) {
    const result = node("[data-ops-history-result]");
    if (result) result.textContent = text || "";
  }

  function fill(body) {
    const select = node("[data-ops-history-enabled]");
    if (select) select.value = body.enabled === true ? ON : OFF;
    const hint = node("[data-ops-history-path]");
    if (hint) {
      hint.textContent = body.path
        ? MUREO.t("dashboard.ops_history_path", { path: body.path })
        : "";
    }
  }

  async function renderOpsHistory() {
    if (!node("[data-dashboard-ops-history]")) return;
    let body;
    try {
      const res = await fetch(ENDPOINT);
      body = await res.json();
    } catch (_err) {
      body = null;
    }
    if (!body || body.status !== "ok") {
      setResult(MUREO.t("dashboard.ops_history_load_failed"));
      return;
    }
    fill(body);
  }

  async function save(button) {
    const select = node("[data-ops-history-enabled]");
    if (!select) return;
    const enabled = select.value === ON;
    // The request writes to a file; a second click must not race the first.
    button.disabled = true;
    let res;
    try {
      res = await MUREO.postJson(ENDPOINT, { enabled: enabled });
    } catch (_err) {
      res = null;
    } finally {
      button.disabled = false;
    }
    const data = (res && res.body) || {};
    if (!res || !res.ok || data.status !== "ok") {
      const failed = MUREO.t("dashboard.ops_history_save_failed");
      setResult(failed);
      MUREO.toast(failed, "error");
      return;
    }
    // Drawn from the server's answer, not from what was selected.
    fill(data);
    const msg = MUREO.t(
      data.enabled === true
        ? "dashboard.ops_history_saved_on"
        : "dashboard.ops_history_saved_off"
    );
    setResult(msg);
    MUREO.toast(msg, "success");
  }

  function wireOpsHistory() {
    const button = node("[data-ops-history-save]");
    if (!button) return;
    button.addEventListener("click", function () {
      save(button);
    });
  }

  const api = {
    renderOpsHistory: renderOpsHistory,
    wireOpsHistory: wireOpsHistory,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_OPS_HISTORY = api;
  // Node (test runner only): dead code in a browser.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
