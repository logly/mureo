// plugin_disconnect.js — the plugin OAuth card's stored-token pieces: the
// read-only status row of the token field and the Disconnect button (#970)
// shown once a token is stored. Loaded before dashboard_plugins.js, which
// reads window.MUREO_PLUGIN_DISCONNECT at call time.

(function () {
  "use strict";

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

  // Disconnect removes the provider's saved credentials (the server revokes
  // the stored token first when the provider supports it). A plain button,
  // not a submit: it sits in the Authenticate form's action row. `onDone`
  // re-renders whatever shows the provider's stored state. A "noop" answer
  // means nothing was stored any more (removed elsewhere since the render),
  // so it gets a neutral toast and the same re-render.
  function buildDisconnectButton(providerName, onDone) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary plugin-disconnect-btn";
    btn.setAttribute("data-plugin-disconnect", providerName);
    btn.textContent = MUREO.t("dashboard.plugin_oauth_disconnect");
    btn.addEventListener("click", async function () {
      const ok = await MUREO.confirmAction(
        MUREO.t("dashboard.confirm_plugin_disconnect")
      );
      if (!ok) return;
      btn.disabled = true;
      const res = await MUREO.postJson(
        "/api/credentials/plugins/" + encodeURIComponent(providerName) + "/disconnect",
        {}
      );
      const outcome = MUREO.postOutcome(res);
      const status = outcome.ok ? outcome.body.status : null;
      if (status === "ok") {
        MUREO.toast(MUREO.t("dashboard.plugin_oauth_disconnected"), "success");
      } else if (status === "noop") {
        MUREO.toast(MUREO.t("dashboard.plugin_oauth_disconnect_noop"), "info");
      } else {
        btn.disabled = false;
        MUREO.toast(MUREO.t("dashboard.plugin_oauth_disconnect_failed"), "error");
        return;
      }
      if (typeof onDone === "function") onDone();
    });
    return btn;
  }

  const api = {
    appendOAuthTargetStatus: appendOAuthTargetStatus,
    buildDisconnectButton: buildDisconnectButton,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_PLUGIN_DISCONNECT = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
