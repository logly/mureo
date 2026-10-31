// auth_wizards.js — the configure wizard's auth step: the sequential queue
// of per-provider slots and the in-wizard OAuth handoffs. Hides outer
// Back/Next while a sub-wizard is active.
//
// The pieces it composes load first and are read at call time: the Meta
// cards (auth_wizards_meta.js, window.MUREO_AUTH_META), a plugin provider's
// slot pieces (auth_wizards_plugin.js, window.MUREO_AUTH_PLUGIN), the
// providers-install step (wizard_install_slots.js,
// window.MUREO_AUTH_INSTALL), the queue and its "already stored" checks
// (wizard_auth_queue.js, window.MUREO_AUTH_QUEUE) and the declarative
// credential slot (wizard_plugin_slot.js, window.MUREO_AUTH_PLUGIN_SLOT).

(function () {
  "use strict";
  // Leave the auth step: the outer wizard owns the step order, so hand
  // control to its gotoNext when it is there and fall back to a re-render.
  function leaveAuthStep(render) {
    if (
      window.MUREO_WIZARD &&
      typeof window.MUREO_WIZARD.gotoNext === "function"
    ) {
      window.MUREO_WIZARD.gotoNext();
    } else {
      render();
    }
  }

  // The Google OAuth already on disk covers Google Ads AND Search Console,
  // so their slots were skipped. Say so — a silently missing auth step is
  // mysterious — and offer the deliberate way back in: re-authorizing
  // rebuilds the queue with the Google slot in it (this run only; the flag
  // is never persisted).
  function buildGoogleReusedNote(state, render) {
    const note = document.createElement("div");
    note.className = "wizard-shared-with-sc-note";
    note.setAttribute("data-google-oauth-reused", "");
    const text = document.createElement("span");
    const textKey = "auth_wizard.google.already_authenticated";
    text.textContent = MUREO.t(textKey);
    text.setAttribute("data-i18n", textKey);
    note.appendChild(text);
    note.appendChild(document.createTextNode(" "));
    note.appendChild(
      buildReauthorizeGoogleButton(state, render, "data-google-reauthorize")
    );
    return note;
  }

  // "Re-authorize Google": sets the run-local flag (never persisted) that
  // queues the Google slot, then `onClick` brings that slot in. `marker` is
  // the data attribute naming which note the button belongs to.
  function buildReauthorizeGoogleButton(state, onClick, marker) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("auth_wizard.google.reauthorize");
    btn.setAttribute("data-i18n", "auth_wizard.google.reauthorize");
    btn.setAttribute(marker, "");
    btn.addEventListener("click", function () {
      state.reauthorizeGoogle = true;
      onClick();
    });
    return btn;
  }

  // The store already holds the ``ga4`` section, so its slot was skipped.
  // Say so; there is no re-authorize button because GA4 has no OAuth here —
  // the path and project id are edited from the dashboard env-var rows.
  function buildGa4ReusedNote() {
    const note = document.createElement("div");
    note.className = "wizard-shared-with-sc-note";
    note.setAttribute("data-ga4-credentials-reused", "");
    const text = document.createElement("span");
    const textKey = "auth_wizard.ga4.already_configured";
    text.textContent = MUREO.t(textKey);
    text.setAttribute("data-i18n", textKey);
    note.appendChild(text);
    return note;
  }

  // The Google authorization this run just saved carried GA4 read-only, so
  // the server derived the ``ga4`` section from it (mureo.core.ga4_adc) and
  // the GA4 slot was dropped. Say so, in place of the slot.
  function buildGa4FromGoogleNote() {
    const note = document.createElement("div");
    note.className = "wizard-shared-with-sc-note";
    note.setAttribute("data-ga4-from-google-oauth", "");
    const text = document.createElement("span");
    const textKey = "auth_wizard.ga4.from_google_oauth";
    text.textContent = MUREO.t(textKey);
    text.setAttribute("data-i18n", textKey);
    note.appendChild(text);
    return note;
  }

  // Google OAuth slot done: when GA4 is selected and its input slot is still
  // ahead, re-read /api/status once. A usable ``ga4`` section there means
  // the authorization filled it, so the slot leaves the queue and a note
  // goes above slotHost, where advancing the queue cannot clear it.
  // Returns the Promise of that check (resolving to whether the slot was
  // dropped), or null when none is due, so every other slot still advances
  // synchronously.
  function dropGa4SlotIfSaved(queue, cursor, state, host, slotHost) {
    const done = queue[cursor.index];
    if (!done || done.oauthProvider !== "google" || !state.platforms.ga4) return null;
    const ga4Index = queue.findIndex(function (slot, i) {
      return i > cursor.index && slot.key === "ga4";
    });
    if (ga4Index === -1 || typeof MUREO.loadStatus !== "function") return null;
    return MUREO.loadStatus().then(function () {
      const status = MUREO.state && MUREO.state.status;
      const present = (status && status.credentials_present) || {};
      if (!present.ga4) return false;
      // Set before the DOM check: a step left while the status loaded is
      // rendered again later from state, and only this flag keeps that
      // render from bringing the GA4 slot back.
      state.ga4SavedByGoogleOauth = true;
      // The step was left while the status loaded; its DOM is gone.
      if (slotHost.isConnected === false) return false;
      queue.splice(ga4Index, 1);
      host.insertBefore(buildReusedHeading("wizard.auth.ga4_title"), slotHost);
      host.insertBefore(buildGa4FromGoogleNote(), slotHost);
      return true;
    });
  }

  // GA4 inputs shown while a Google authorization is on disk: it lacks GA4
  // read-only (minted before mureo asked for it, or unticked), and
  // re-authorizing is how mureo fills both values. The button is offered
  // only when this run can queue a Google OAuth slot; otherwise the hint
  // names the CLI command instead. `onReauthorize` brings the Google slot in
  // at the current position, so the GA4 slot follows it.
  function appendGa4ReauthorizeHint(wrap, state, onReauthorize) {
    const q = window.MUREO_AUTH_QUEUE;
    if (!q.googleHasOauthOnDisk(state)) return;
    const canQueueGoogle =
      (state.platforms.google_ads && !q.isPluginChoice(state, "google_ads")) ||
      (state.platforms.search_console && !q.isPluginChoice(state, "search_console"));
    const hint = document.createElement("p");
    hint.className = "wizard-shared-with-sc-note";
    hint.setAttribute("data-ga4-reauthorize-hint", "");
    const text = document.createElement("span");
    const textKey = canQueueGoogle
      ? "auth_wizard.ga4.reauthorize_hint"
      : "auth_wizard.ga4.reauthorize_hint_cli";
    text.textContent = MUREO.t(textKey);
    text.setAttribute("data-i18n", textKey);
    hint.appendChild(text);
    if (canQueueGoogle) {
      hint.appendChild(document.createTextNode(" "));
      hint.appendChild(
        buildReauthorizeGoogleButton(state, onReauthorize, "data-ga4-reauthorize")
      );
    }
    wrap.appendChild(hint);
  }

  // Nothing left to authorize. Outer Back/Next are hidden while the auth
  // step is active, so the step renders its own Continue. The success line
  // is only honest when something was actually authorized here — after a
  // reuse the note above already explains why the step is empty.
  function appendQueueDoneControls(slotHost, anyReused, render) {
    if (!anyReused) {
      const note = document.createElement("p");
      note.textContent = MUREO.t("wizard.auth.oauth_success");
      slotHost.appendChild(note);
    }
    const continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.className = "btn btn-primary";
    continueBtn.textContent = MUREO.t("wizard.next");
    continueBtn.addEventListener("click", function () {
      leaveAuthStep(render);
    });
    continueBtn.style.marginTop = "16px";
    slotHost.appendChild(continueBtn);
  }

  // A reused note replaces the slot that carried the heading, so it brings
  // that slot's own; otherwise it would read as part of the next slot.
  function buildReusedHeading(key) {
    const heading = document.createElement("h3");
    heading.textContent = MUREO.t(key);
    heading.setAttribute("data-i18n", key);
    return heading;
  }

  // One note per slot skipped because its credentials are stored; true when
  // any was. The Google note goes under Google Ads when that platform takes
  // the Google OAuth, otherwise under Search Console.
  function appendReusedNotes(host, state, render) {
    const q = window.MUREO_AUTH_QUEUE;
    const googleAds = state.platforms.google_ads && !q.isPluginChoice(state, "google_ads");
    const googleSc = state.platforms.search_console && !q.isPluginChoice(state, "search_console");
    const googleReused =
      (googleAds || googleSc) && q.googleHasOauthOnDisk(state) && !state.reauthorizeGoogle;
    const ga4Reused = state.platforms.ga4 && q.ga4CredentialsOnDisk(state);
    const pluginReused = ["google_ads", "search_console", "meta_ads"].filter(function (p) {
      return state.platforms[p] && q.isPluginChoice(state, p) && q.pluginConfigured(state, p);
    });
    if (googleReused) {
      const key = googleAds ? "google_ads" : "search_console";
      host.appendChild(buildReusedHeading("wizard.auth." + key + "_title"));
      host.appendChild(buildGoogleReusedNote(state, render));
    }
    if (ga4Reused) {
      // A re-render mid-step keeps the note the dropped slot left behind.
      host.appendChild(buildReusedHeading("wizard.auth.ga4_title"));
      host.appendChild(
        state.ga4SavedByGoogleOauth ? buildGa4FromGoogleNote() : buildGa4ReusedNote()
      );
    }
    pluginReused.forEach(function (p) {
      host.appendChild(buildReusedHeading("wizard.auth." + p + "_title"));
      host.appendChild(window.MUREO_AUTH_PLUGIN.buildPluginReusedNote(state.pluginPlatforms[p]));
    });
    return Boolean(googleReused || ga4Reused || pluginReused.length > 0);
  }

  // Re-authorize Google from the GA4 slot: the Google slot goes in at the
  // current position, so it is authorized in place and the GA4 slot follows
  // it (dropped by dropGa4SlotIfSaved when Google filled the section),
  // instead of the whole queue re-rendering from its first slot. Matched on
  // the OAuth provider: a plugin provider's Google Ads slot is not it.
  // Returns whether a slot went in.
  function queueGoogleSlotHere(queue, cursor, state) {
    state.reauthorizeGoogle = true;
    const google = window.MUREO_AUTH_QUEUE.buildAuthQueue(state).find(function (s) {
      return s.oauthProvider === "google";
    });
    if (!google) return false;
    queue.splice(cursor.index, 0, google);
    return true;
  }

  // The GA4 check of a finished Google slot has answered (a failed reload
  // reads as "not dropped"). The step may have been left while the status
  // loaded; then nothing advances or renders. When the dropped GA4 slot was
  // the last one, the step stays with the Continue an empty queue renders,
  // so the note above is read first. `run` is the queue's
  // {slotHost, cursor, queue, advance, render}.
  function afterGa4Check(run, dropped) {
    const slotHost = run.slotHost;
    if (slotHost.isConnected === false) return;
    if (dropped && run.cursor.index + 1 >= run.queue.length) {
      while (slotHost.firstChild) slotHost.removeChild(slotHost.firstChild);
      appendQueueDoneControls(slotHost, false, run.render);
    } else {
      run.advance();
    }
  }

  function renderSequentialQueue(host, state, render) {
    const anyReused = appendReusedNotes(host, state, render);
    // Slots live in their own child element: advancing the queue clears
    // ONLY that element, so the notes above survive the whole step.
    const slotHost = document.createElement("div");
    host.appendChild(slotHost);

    const queue = window.MUREO_AUTH_QUEUE.buildAuthQueue(state);
    if (queue.length === 0) {
      appendQueueDoneControls(slotHost, anyReused, render);
      return;
    }

    const cursor = { index: 0 };
    function advance() {
      cursor.index += 1;
      if (cursor.index < queue.length) {
        renderCurrent();
      } else {
        leaveAuthStep(render);
      }
    }
    const run = {
      slotHost: slotHost, cursor: cursor, queue: queue, advance: advance, render: render,
    };
    function renderCurrent() {
      while (slotHost.firstChild) slotHost.removeChild(slotHost.firstChild);
      const slot = queue[cursor.index];
      if (!slot) return;
      const wrap = renderStepWizard(slot, state, function onSlotDone() {
        const check = dropGa4SlotIfSaved(queue, cursor, state, host, slotHost);
        if (!check) return advance();
        // A failed status reload must not stall the queue: the GA4 slot
        // then simply stays and asks for its two values.
        check
          .catch(function () { return false; })
          .then(function (dropped) { afterGa4Check(run, dropped); });
      }, state, reauthorizeGoogleHere);
      slotHost.appendChild(wrap);
    }
    function reauthorizeGoogleHere() {
      if (queueGoogleSlotHere(queue, cursor, state)) renderCurrent();
    }
    renderCurrent();
  }

  function renderStepWizard(slot, state, onAllDone, outerState, onReauthorize) {
    const wrap = document.createElement("section");
    const titleKey = "wizard.auth." + slot.key + "_title";
    wrap.innerHTML = "<h3>" + MUREO.t(titleKey) + "</h3>";

    // Declarative slot (Amazon Ads, or a plugin provider chosen for a
    // built-in platform): fields come from the provider registry, so it
    // owns the whole card and returns before every branch below.
    if (slot.pluginProvider) {
      window.MUREO_AUTH_PLUGIN_SLOT.renderPluginCredentialSlot(
        wrap, slot, outerState || state, onAllDone
      );
      return wrap;
    }

    if (slot.key === "google_ads") {
      // Scope guidance: the OAuth button mints a refresh token with the
      // adwords + webmasters + analytics.readonly scopes
      // (mureo.auth_setup._GOOGLE_SCOPES).
      // A reused token lacking the adwords scope fails at runtime with
      // ACCESS_TOKEN_SCOPE_INSUFFICIENT, so spell this out + link the
      // official scope reference.
      const scopeNote = document.createElement("p");
      scopeNote.className = "wizard-shared-with-sc-note";
      const scopeText = document.createElement("span");
      scopeText.textContent = MUREO.t("auth_wizard.google_ads.scope_note");
      scopeText.setAttribute("data-i18n", "auth_wizard.google_ads.scope_note");
      const scopeLink = document.createElement("a");
      scopeLink.href =
        "https://developers.google.com/google-ads/api/docs/oauth/overview";
      scopeLink.target = "_blank";
      scopeLink.rel = "noopener noreferrer";
      scopeLink.textContent = MUREO.t("auth_wizard.google_ads.scope_doc_link");
      scopeLink.setAttribute(
        "data-i18n", "auth_wizard.google_ads.scope_doc_link"
      );
      scopeNote.appendChild(scopeText);
      scopeNote.appendChild(document.createTextNode(" "));
      scopeNote.appendChild(scopeLink);
      wrap.appendChild(scopeNote);
    }

    if (
      slot.key === "google_ads" && outerState && outerState.platforms.search_console &&
      !window.MUREO_AUTH_QUEUE.isPluginChoice(outerState, "search_console")
    ) {
      const note = document.createElement("div");
      note.className = "wizard-shared-with-sc-note";
      note.textContent = MUREO.t("auth_wizard.google_ads.step2_shared_with_sc");
      wrap.appendChild(note);
    }

    if (slot.key === "search_console") {
      const desc = document.createElement("p");
      desc.textContent = MUREO.t("auth_wizard.search_console.step1_desc");
      wrap.appendChild(desc);
    }

    // Input-based slots (e.g. GA4) need an explicit "Done" button
    // gated by the inputs being filled. OAuth-only slots auto-advance
    // on pollOAuth success — no inner Next button.
    let doneBtn = null;
    if (slot.inputs) {
      if (slot.key === "ga4") {
        appendGa4ReauthorizeHint(wrap, outerState || state, onReauthorize);
      }
      doneBtn = document.createElement("button");
      doneBtn.type = "button";
      doneBtn.className = "btn btn-primary";
      doneBtn.textContent = MUREO.t("wizard.auth.done_button");
      doneBtn.setAttribute("data-i18n", "wizard.auth.done_button");
      doneBtn.disabled = true;

      const status = document.createElement("p");
      status.className = "wizard-shared-with-sc-note";
      status.hidden = true;

      const values = {};
      const completionFlags = {};
      slot.inputs.forEach(function (spec) {
        const label = document.createElement("label");
        label.style.display = "block";
        label.textContent = MUREO.t(spec.labelKey);
        label.setAttribute("data-i18n", spec.labelKey);
        const input = document.createElement("input");
        input.type = "text";
        input.addEventListener("input", function () {
          values[spec.name] = input.value;
          completionFlags[spec.name] = Boolean(input.value);
          const allFilled = slot.inputs.every(function (s) {
            return completionFlags[s.name];
          });
          doneBtn.disabled = !allFilled;
        });
        label.appendChild(input);
        wrap.appendChild(label);
      });

      doneBtn.addEventListener("click", async function () {
        // Persist each value to credentials.json via the allow-listed
        // env-var writer BEFORE advancing. Without this the entered
        // GA4 service-account path / project id were discarded and the
        // official GA4 MCP launched unauthenticated.
        doneBtn.disabled = true;
        status.hidden = false;
        status.textContent = MUREO.t("wizard.auth.saving");
        try {
          for (let i = 0; i < slot.inputs.length; i += 1) {
            const spec = slot.inputs[i];
            const res = await MUREO.postJson("/api/credentials/env-var", {
              name: spec.name,
              value: values[spec.name],
            });
            if (!res.ok) {
              const msg = MUREO.t("wizard.auth.save_failed");
              status.textContent = msg;
              MUREO.toast(msg, "error");
              doneBtn.disabled = false;
              return;
            }
          }
        } catch (_e) {
          const msg = MUREO.t("wizard.auth.save_failed");
          status.textContent = msg;
          MUREO.toast(msg, "error");
          doneBtn.disabled = false;
          return;
        }
        onAllDone();
      });
      wrap.appendChild(status);
    }

    if (slot.oauthProvider) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-primary";
      btn.textContent = slot.oauthProvider === "meta"
        ? MUREO.t("wizard.auth.meta_oauth_button")
        : MUREO.t("wizard.auth.oauth_button");
      const status = document.createElement("p");
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        status.textContent = MUREO.t("wizard.auth.oauth_waiting");
        const res = await MUREO.postJson(
          "/api/oauth/" + slot.oauthProvider + "/start", {}
        );
        if (res.ok && res.body && res.body.url) {
          window.open(res.body.url, "_blank", "noopener");
          pollOAuth(slot.oauthProvider, status, btn, function () {
            // Auto-advance: intermediate slots roll to the next slot;
            // the final slot hands control back to the outer wizard.
            onAllDone();
          });
        } else {
          const msg = MUREO.t("wizard.auth.oauth_failed");
          status.textContent = msg;
          MUREO.toast(msg, "error");
          btn.disabled = false;
        }
      });
      if (slot.oauthProvider === "meta") {
        // #458 / field feedback: the two Meta auth paths are mutually
        // exclusive ALTERNATIVES, not a primary plus a fallback. A Live-mode
        // app can never complete localhost OAuth (Facebook rejects the
        // redirect) and a Development-mode app cannot create creatives
        // (subcode 1885183). Rendering the Facebook button up front with the
        // token card collapsed underneath made token-bound operators click
        // the loud button and dead-end, so the step now opens with an
        // explicit either/or chooser and reveals ONLY the chosen flow.
        //
        // Both panels are built once and toggled, so switching options does
        // not discard a token the operator already typed.
        const oauthPanel = document.createElement("div");
        oauthPanel.className = "auth-method-panel";
        oauthPanel.setAttribute("data-auth-method-panel", "oauth");
        oauthPanel.hidden = true;
        oauthPanel.appendChild(btn);
        oauthPanel.appendChild(status);

        const tokenCard = window.MUREO_AUTH_META.buildMetaTokenCard(onAllDone);
        const tokenPanel = document.createElement("div");
        tokenPanel.className = "auth-method-panel";
        tokenPanel.setAttribute("data-auth-method-panel", "token");
        tokenPanel.hidden = true;
        tokenPanel.appendChild(tokenCard);

        // Chooser FIRST, then the panels — the pollOAuth timeout hint tells
        // the operator to switch to the token option *above*.
        wrap.appendChild(
          window.MUREO_AUTH_META.buildMetaMethodChooser(
            tokenPanel, oauthPanel, tokenCard
          )
        );
        wrap.appendChild(tokenPanel);
        wrap.appendChild(oauthPanel);
      } else {
        wrap.appendChild(btn);
        wrap.appendChild(status);
      }
    }

    if (doneBtn) wrap.appendChild(doneBtn);

    return wrap;
  }

  function pollOAuth(provider, statusNode, btn, onFinished) {
    // Bounded poll (mirrors dashboard.js pollPluginOAuth): without a deadline
    // the loop re-arms forever if the operator closes the consent tab, and the
    // Connect button stays disabled until a full page reload. On timeout we
    // re-enable the button and clear the status so the flow can be retried.
    const deadline = Date.now() + 5 * 60 * 1000;
    let cancelled = false;
    function tick() {
      if (cancelled) return;
      if (Date.now() > deadline) {
        cancelled = true;
        // #458: a Live-mode Meta app never fires our callback (the failure
        // happens on Facebook's localhost-redirect rejection), so the silent
        // reset just looks broken — point the operator at the token option.
        statusNode.textContent = provider === "meta"
          ? MUREO.t("wizard.auth.meta_oauth_localhost_hint")
          : "";
        if (btn) btn.disabled = false;
        return;
      }
      fetch("/api/oauth/" + provider + "/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.success) {
            statusNode.textContent = MUREO.t("wizard.auth.oauth_success");
            cancelled = true;
            onFinished();
          } else if (data && data.error) {
            // #458: for Meta, surface the localhost-OAuth dead-end guidance
            // instead of the generic failure; Google keeps the generic text.
            const msg = provider === "meta"
              ? MUREO.t("wizard.auth.meta_oauth_localhost_hint")
              : MUREO.t("wizard.auth.oauth_failed");
            statusNode.textContent = msg;
            MUREO.toast(msg, "error");
            cancelled = true;
            if (btn) btn.disabled = false;
          } else {
            setTimeout(tick, 750);
          }
        })
        .catch(function () { setTimeout(tick, 750); });
    }
    tick();
  }

  // renderProvidersInstall and buildAuthQueue live in their own files;
  // they are re-exported here so callers keep window.MUREO_AUTH as the
  // one entry point.
  window.MUREO_AUTH = {
    renderProvidersInstall: function (host, state, render) {
      return window.MUREO_AUTH_INSTALL.renderProvidersInstall(host, state, render);
    },
    renderSequentialQueue: renderSequentialQueue,
    buildAuthQueue: function (state) {
      return window.MUREO_AUTH_QUEUE.buildAuthQueue(state);
    },
  };
})();
