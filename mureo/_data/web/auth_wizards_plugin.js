// auth_wizards_plugin.js — the auth-step pieces for a declarative plugin
// slot: a plugin credential provider chosen on the wizard's connection step
// (a provider declaring `serves_platform`), and Amazon Ads. Kept out of
// auth_wizards.js, which is over the 800-line budget. Loaded BEFORE
// auth_wizards.js and consumed through window.MUREO_AUTH_PLUGIN: the one
// descriptor fetch, the declared-field inputs, the step's Continue button,
// the note shown when the provider's section is already configured, and
// the provider's own OAuth card as a queue slot.

(function () {
  "use strict";

  // Fetch one provider's descriptor from the shared plugin-credentials
  // list endpoint. Returns null when the request fails or the provider is
  // not registered, so the caller can show an actionable message instead
  // of an empty step.
  async function fetchPluginDescriptor(providerName) {
    let body;
    try {
      const res = await fetch("/api/credentials/plugins", {
        credentials: "same-origin",
      });
      if (!res.ok) return null;
      body = await res.json();
    } catch (_e) {
      return null;
    }
    const plugins = body && Array.isArray(body.plugins) ? body.plugins : [];
    for (let i = 0; i < plugins.length; i += 1) {
      if (plugins[i].provider_name === providerName) return plugins[i];
    }
    return null;
  }

  // The step's own Continue: outer Back/Next are hidden while a slot is
  // active, so a slot that is finished without a Done of its own leaves
  // the queue through this button.
  function buildContinueButton(onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.textContent = MUREO.t("wizard.next");
    btn.setAttribute("data-i18n", "wizard.next");
    btn.addEventListener("click", onClick);
    return btn;
  }

  // Colored ✓ / ✗ status mark as its own element (kept separate from any
  // data-i18n text node so a locale re-translation can't wipe it). Same
  // mark as dashboard_setup.js's statusMark; MUREO exposes no shared DOM
  // helpers, so this file keeps its own five-line copy.
  function statusMark(ok) {
    const m = document.createElement("span");
    m.className = ok ? "mark-ok" : "mark-no";
    m.textContent = ok ? "✓" : "✗";
    return m;
  }

  // "Configured" / "Not set" after a secret field's name — the empty
  // input alone cannot say whether a value is stored.
  function secretStatusText(configured) {
    const key = configured
      ? "dashboard.credential_secret_configured"
      : "dashboard.credential_secret_unset";
    const text = document.createElement("span");
    text.className = "muted";
    text.setAttribute("data-i18n", key);
    text.textContent = MUREO.t(key);
    return text;
  }

  // The label head, as on the dashboard card: the field name (+ " *" when
  // required), wrapped as "[✓|✗] name  status" for a secret field.
  // data-i18n sits on the status span only, never on the mark's parent.
  function buildFieldLabelHead(field) {
    const labelText = document.createElement("span");
    labelText.textContent = field.display_name + (field.required ? " *" : "");
    if (!field.secret) return labelText;
    const head = document.createElement("span");
    head.appendChild(statusMark(field.configured));
    head.appendChild(document.createTextNode(" "));
    head.appendChild(labelText);
    head.appendChild(document.createTextNode(" "));
    head.appendChild(secretStatusText(field.configured));
    return head;
  }

  // One input per declared field. Mirrors the dashboard card's rules: a
  // secret never round-trips, so its label carries the configured mark, a
  // configured secret shows the leave-blank-to-keep placeholder and an
  // unset one asks for a value; a non-secret pre-fills its stored value so
  // a resumed wizard shows the current config.
  function appendDeclaredField(host, field, inputs) {
    const label = document.createElement("label");
    label.style.display = "block";
    label.appendChild(buildFieldLabelHead(field));

    const input = document.createElement("input");
    input.name = field.key;
    input.type = field.secret ? "password" : "text";
    input.autocomplete = field.secret ? "new-password" : "off";
    if (field.secret) {
      input.placeholder = field.configured
        ? MUREO.t("dashboard.plugin_credentials_secret_placeholder")
        : field.placeholder ||
          MUREO.t("dashboard.plugin_credentials_secret_unset_placeholder");
    } else {
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
    host.appendChild(label);
    inputs.push({ key: field.key, input: input, field: field });
  }

  // Enable Done once every required field has a value — either typed now
  // or already stored (a configured secret may legitimately stay blank).
  function requiredFieldsSatisfied(inputs) {
    return inputs.every(function (item) {
      if (!item.field.required) return true;
      return Boolean(item.input.value) || Boolean(item.field.configured);
    });
  }

  // The provider's section already holds every required field, so its slot
  // was skipped. The text carries the provider's name, so there is no
  // data-i18n on it; the step is rebuilt on every render.
  function buildPluginReusedNote(served) {
    const note = document.createElement("div");
    note.className = "wizard-shared-with-sc-note";
    note.setAttribute("data-plugin-credentials-reused", served.provider_name);
    note.textContent = MUREO.t("auth_wizard.plugin.already_configured", {
      provider: served.display_name,
    });
    return note;
  }

  // The card reads the stored state once, when built: after a store the
  // token row should read Configured and the account picker's Load should
  // open, so the card is rebuilt from a fresh descriptor. Resolves to
  // `{ card, fresh }`: the card now in the DOM (the old one stays when the
  // refetch fails) and the fresh descriptor, null when it failed.
  async function refreshCard(wrap, card, providerName, onStored) {
    const fresh = await fetchPluginDescriptor(providerName);
    if (!fresh || card.parentNode !== wrap) return { card: card, fresh: fresh };
    const next = window.MUREO_DASHBOARD_PLUGINS.buildPluginCredentialsForm(fresh, onStored);
    next.open = true;
    wrap.replaceChild(next, card);
    return { card: next, fresh: fresh };
  }

  // An OAuth provider's slot is the dashboard's own card for it (callback
  // URL, Authenticate-is-save, the account picker when declared), so
  // nothing about that flow is copied here. The slot's Done button is
  // retired: the card saves on Authenticate. Continue opens once the
  // provider reads configured — a consent alone may still leave a required
  // field (the account) to pick — or when the refetch fails, so the
  // operator is never stranded on the step.
  function renderPluginOAuthSlot(wrap, plugin, doneBtn, status, onAllDone) {
    doneBtn.hidden = true;
    const continueBtn = buildContinueButton(onAllDone);
    // Closed until the provider's section reads configured; a slot built
    // from a stale snapshot for an already complete section opens at once.
    continueBtn.disabled = !plugin.configured;

    let card = null;
    // One refresh at a time: two quick stores would otherwise both replace
    // the same card, and the second would find it detached.
    let pending = Promise.resolve();
    function onStored() {
      status.hidden = false;
      status.textContent = MUREO.t("dashboard.plugin_oauth_connected");
      pending = pending
        .then(function () {
          return refreshCard(wrap, card, plugin.provider_name, onStored);
        })
        .then(
          function (result) {
            card = result.card;
            continueBtn.disabled = Boolean(result.fresh) && !result.fresh.configured;
          },
          function () {
            continueBtn.disabled = false;
          }
        );
    }
    card = window.MUREO_DASHBOARD_PLUGINS.buildPluginCredentialsForm(plugin, onStored);
    card.open = true;
    wrap.appendChild(card);
    // Moved below the card so "Connected." reads under what it reports on.
    wrap.appendChild(status);
    wrap.appendChild(continueBtn);
  }

  window.MUREO_AUTH_PLUGIN = {
    appendDeclaredField: appendDeclaredField,
    buildContinueButton: buildContinueButton,
    buildPluginReusedNote: buildPluginReusedNote,
    fetchPluginDescriptor: fetchPluginDescriptor,
    renderPluginOAuthSlot: renderPluginOAuthSlot,
    requiredFieldsSatisfied: requiredFieldsSatisfied,
  };
})();
