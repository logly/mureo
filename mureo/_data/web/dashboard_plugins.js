// dashboard_plugins.js — the per-plugin credentials and OAuth cards.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move.
//
// One card per registered provider, built from what the provider DECLARES
// rather than from anything hard-coded here: which fields it needs, whether
// they are secret, whether it authenticates by OAuth, and whether it can list
// the accounts its token reaches. That last one is why the picker exists — a
// provider with `accounts_field` + `has_account_lister` gets Load → radios →
// Save instead of a free-text id an operator has to copy from somewhere else.
//
// `pluginRenderSeq` is the #223 generation guard: the render is async, and
// renderAll() runs it twice during init.
//
// A secret value is never shipped back to the browser. A configured secret
// field renders a placeholder keyed off `field.configured`; only a non-secret
// field is pre-filled from `field.value`.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_PLUGINS`. Must load BEFORE dashboard.js.

(function () {
  "use strict";

  // Registry name of the Amazon bridge — the provider_name its generic
  // credentials card is keyed by (mirrors AmazonAdsBridge.name).
  const AMAZON_PROVIDER_NAME = "amazon_ads";

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
    // Amazon-only extra controls (keyed off the provider name so no other
    // plugin card grows them): saved credentials alone leave the bridge
    // toolless until the local tool manifest is generated, and the
    // paste-code authorization flow is what obtains the tokens in the
    // first place (#121). Both live in amazon_oauth.js, shared with the
    // setup wizard's Amazon step.
    if (plugin.provider_name === AMAZON_PROVIDER_NAME) {
      wrap.appendChild(buildAmazonManifestRefresh());
      if (window.MUREO_AMAZON_OAUTH) {
        wrap.appendChild(window.MUREO_AMAZON_OAUTH.buildAuthorizeSection());
        const expiring = window.MUREO_AMAZON_OAUTH.buildExpiringHint(
          MUREO.state.status
        );
        if (expiring) wrap.appendChild(expiring);
      }
    }
    return wrap;
  }

  // Amazon tool-manifest refresh: POSTs to the server, which runs the same
  // generator as `mureo amazon refresh-manifest` (one authenticated session
  // to the region endpoint) and replies with a tool count. The response
  // carries no credential material, and neither does the status line — a
  // failure is reported as localized prose plus the server's machine code.
  function buildAmazonManifestRefresh() {
    const box = document.createElement("div");
    box.className = "plugin-amazon-manifest";

    const hint = document.createElement("small");
    hint.className = "field-hint";
    hint.textContent = MUREO.t("dashboard.amazon_refresh_manifest_hint");
    hint.setAttribute("data-i18n", "dashboard.amazon_refresh_manifest_hint");
    box.appendChild(hint);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.amazon_refresh_manifest");
    btn.setAttribute("data-i18n", "dashboard.amazon_refresh_manifest");
    box.appendChild(btn);

    const status = document.createElement("span");
    status.className = "plugin-amazon-manifest-status muted";
    box.appendChild(status);

    btn.addEventListener("click", function () {
      refreshAmazonManifest(btn, status);
    });
    return box;
  }

  async function refreshAmazonManifest(btn, status) {
    btn.disabled = true;
    status.textContent = MUREO.t("dashboard.amazon_refresh_manifest_running");
    let res;
    try {
      res = await MUREO.postJson("/api/amazon/refresh-manifest", {});
    } catch (_e) {
      res = null;
    }
    btn.disabled = false;
    if (res && res.ok && res.body && res.body.status === "ok") {
      const msg = MUREO.t("dashboard.amazon_refresh_manifest_done", {
        count: res.body.tool_count,
      });
      status.textContent = msg;
      MUREO.toast(msg, "success");
      return;
    }
    // "Not configured yet" is a distinct, actionable state — don't collapse
    // it into the generic failure.
    const err = res && res.body ? res.body.error : null;
    const key =
      err === "amazon_credentials_missing"
        ? "dashboard.amazon_refresh_manifest_no_credentials"
        : "dashboard.amazon_refresh_manifest_failed";
    status.textContent = MUREO.t(key);
    MUREO.toast(MUREO.t(key), "error");
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
  const api = {
    renderPluginCredentials: renderPluginCredentials,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_PLUGINS = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
