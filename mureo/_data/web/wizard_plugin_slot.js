// wizard_plugin_slot.js — the auth-step slot for a declarative credential
// provider (Amazon Ads, or a plugin provider chosen for a built-in
// platform): the slot's frame, the declared-field form and its save, and
// Amazon's inline authorization once the save lands. Kept out of
// auth_wizards.js so that file stays within the 800-line budget. Loaded
// BEFORE auth_wizards.js and consumed through window.MUREO_AUTH_PLUGIN_SLOT;
// the descriptor fetch, the field inputs and the OAuth card are read off
// window.MUREO_AUTH_PLUGIN at call time.

(function () {
  "use strict";

  // The descriptor fetch, the declared-field inputs and the OAuth card live
  // in auth_wizards_plugin.js (window.MUREO_AUTH_PLUGIN, loaded first).
  function renderPluginCredentialSlot(wrap, slot, state, onAllDone) {
    const descKey = "wizard.auth." + slot.key + "_desc";
    const descText = MUREO.t(descKey);
    if (descText && descText !== descKey) {
      const desc = document.createElement("p");
      desc.textContent = descText;
      desc.setAttribute("data-i18n", descKey);
      wrap.appendChild(desc);
    }
    // Configured state comes from the wizard's hydrated /api/status view —
    // the same backend verdict the dashboard row uses.
    if (
      slot.key === "amazon_ads" &&
      state.existing &&
      state.existing.amazon &&
      state.existing.amazon.configured
    ) {
      const done = document.createElement("p");
      done.className = "wizard-shared-with-sc-note";
      done.textContent = MUREO.t("wizard.step_already_done");
      done.setAttribute("data-i18n", "wizard.step_already_done");
      wrap.appendChild(done);
    }

    const fieldHost = document.createElement("div");
    wrap.appendChild(fieldHost);
    const status = document.createElement("p");
    status.className = "wizard-shared-with-sc-note";
    status.hidden = true;
    wrap.appendChild(status);

    const doneBtn = document.createElement("button");
    doneBtn.type = "button";
    doneBtn.className = "btn btn-primary";
    doneBtn.textContent = MUREO.t("wizard.auth.done_button");
    doneBtn.setAttribute("data-i18n", "wizard.auth.done_button");
    doneBtn.disabled = true;
    wrap.appendChild(doneBtn);

    window.MUREO_AUTH_PLUGIN.fetchPluginDescriptor(slot.pluginProvider).then(function (plugin) {
      renderResolvedPluginSlot(wrap, slot, plugin, fieldHost, status, doneBtn, onAllDone);
    });
  }

  // The slot once its descriptor is in: a notice when the provider is
  // unreachable, the dashboard's card for an OAuth provider, otherwise one
  // input per declared field behind a Done gated on the required ones.
  function renderResolvedPluginSlot(wrap, slot, plugin, fieldHost, status, doneBtn, onAllDone) {
    if (!plugin) {
      // The provider is unreachable/unregistered — say so and let the
      // operator move on rather than stranding the wizard on an empty
      // step (they can finish from the dashboard card).
      status.hidden = false;
      status.textContent = MUREO.t("wizard.auth.save_failed");
      doneBtn.disabled = false;
      doneBtn.addEventListener("click", onAllDone);
      return;
    }
    // An OAuth provider gets the dashboard's own card. dashboard_plugins.js
    // loads after this file but is read at render time; without it (the
    // auth-wizard test harness) the manual path below runs.
    const cards = window.MUREO_DASHBOARD_PLUGINS;
    if (plugin.oauth && cards && typeof cards.buildPluginCredentialsForm === "function") {
      window.MUREO_AUTH_PLUGIN.renderPluginOAuthSlot(wrap, plugin, doneBtn, status, onAllDone);
      return;
    }
    const pluginSlot = window.MUREO_AUTH_PLUGIN;
    const inputs = [];
    plugin.fields.forEach(function (field) {
      pluginSlot.appendDeclaredField(fieldHost, field, inputs);
    });
    inputs.forEach(function (item) {
      item.input.addEventListener("input", function () {
        doneBtn.disabled = !pluginSlot.requiredFieldsSatisfied(inputs);
      });
    });
    doneBtn.disabled = !pluginSlot.requiredFieldsSatisfied(inputs);
    doneBtn.addEventListener("click", function () {
      savePluginSlot(wrap, slot, inputs, doneBtn, status, onAllDone);
    });
  }

  // Done on the declared-field form: one save of every input, then Amazon's
  // authorization controls or the next slot.
  async function savePluginSlot(wrap, slot, inputs, doneBtn, status, onAllDone) {
    doneBtn.disabled = true;
    status.hidden = false;
    status.textContent = MUREO.t("wizard.auth.saving");
    const values = {};
    inputs.forEach(function (item) {
      values[item.key] = item.input.value;
    });
    let res;
    try {
      res = await MUREO.postJson("/api/credentials/plugins/save", {
        provider_name: slot.pluginProvider,
        values: values,
      });
    } catch (_e) {
      res = null;
    }
    if (MUREO.postOutcome(res).ok && res.body.status === "ok") {
      appendAmazonAuthorization(wrap, slot, doneBtn, status, onAllDone);
      return;
    }
    const msg = MUREO.t("wizard.auth.save_failed");
    status.textContent = msg;
    MUREO.toast(msg, "error");
    doneBtn.disabled = false;
  }

  // Amazon's credentials are only half the setup: the saved client
  // id/secret still have to be turned into tokens by the paste-code
  // authorization flow (#121). Rather than sending the operator to the
  // dashboard for it, the wizard shows the SAME controls (built by
  // amazon_oauth.js) inline once the save lands, and turns Done into a
  // Continue that leaves the queue when they are finished. Authorization
  // stays optional here — an operator who pasted a refresh token by hand
  // is already done and can simply continue.
  function appendAmazonAuthorization(wrap, slot, doneBtn, status, onAllDone) {
    if (slot.pluginProvider !== "amazon_ads" || !window.MUREO_AMAZON_OAUTH) {
      onAllDone();
      return;
    }
    status.textContent = MUREO.t("wizard.auth.amazon_saved_now_authorize");
    wrap.appendChild(window.MUREO_AMAZON_OAUTH.buildAuthorizeSection());
    // Retire the Save button rather than re-labelling it: its click
    // listener still saves, and a Continue that also re-submitted the
    // form would be a surprise.
    doneBtn.hidden = true;
    wrap.appendChild(window.MUREO_AUTH_PLUGIN.buildContinueButton(onAllDone));
  }

  window.MUREO_AUTH_PLUGIN_SLOT = {
    renderPluginCredentialSlot: renderPluginCredentialSlot,
  };
})();
