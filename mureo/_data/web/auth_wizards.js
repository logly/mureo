// auth_wizards.js — provider-install and per-provider auth wizards.
// Renders the sequential queue of provider installs (Step 5+) and the
// in-wizard OAuth handoffs. Hides outer Back/Next while a sub-wizard
// is active.

(function () {
  "use strict";

  const PROVIDER_INSTALL_ORDER = ["google_ads", "meta_ads", "ga4"];

  // ------------------------------------------------------------------
  // Provider install slots (Step: providers_install)
  // ------------------------------------------------------------------
  function buildProviderInstallSlot(state, platform, onComplete) {
    const wrap = document.createElement("section");
    wrap.style.marginTop = "16px";
    const providerId = platform.replace("_", "-") + "-official";
    const installed = state.providerInstalled[providerId];
    wrap.innerHTML =
      "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>" +
      "<p>" + (installed ? "✓ " + MUREO.t("dashboard.installed") : "✗ " + MUREO.t("dashboard.not_installed")) + "</p>";
    if (!installed) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-primary";
      btn.textContent = MUREO.t("dashboard.action_install");
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        const res = await MUREO.postJson("/api/providers/install", {
          provider_id: providerId,
        });
        btn.disabled = false;
        if (res.ok && res.body && res.body.status === "ok") {
          state.providerInstalled[providerId] = true;
          await MUREO.loadStatus();
          onComplete();
        } else {
          MUREO.toast("Install failed");
        }
      });
      wrap.appendChild(btn);
    }
    return wrap;
  }

  function renderProvidersInstall(host, state, render) {
    PROVIDER_INSTALL_ORDER.forEach(function (platform) {
      const needsOfficial =
        (platform === "google_ads" && state.platforms.google_ads &&
          state.providerChoice.google_ads === "official") ||
        (platform === "meta_ads" && state.platforms.meta_ads &&
          state.providerChoice.meta_ads === "official") ||
        (platform === "ga4" && state.platforms.ga4);
      if (needsOfficial) {
        host.appendChild(buildProviderInstallSlot(state, platform, render));
      }
    });
  }

  // ------------------------------------------------------------------
  // Auth queue (Step: auth)
  // ------------------------------------------------------------------
  function googleHasOauthOnDisk(state) {
    // True iff /api/status reported credentials_oauth.google. The
    // adwords + webmasters scopes share a single refresh token (see
    // mureo.auth_setup._GOOGLE_SCOPES), so any prior Google OAuth
    // satisfies both Google Ads and Search Console requirements.
    return Boolean(
      state.existing && state.existing.google && state.existing.google.has_oauth
    );
  }

  function buildAuthQueue(state) {
    const queue = [];
    if (state.platforms.google_ads && state.providerChoice.google_ads === "native") {
      queue.push({ key: "google_ads", oauthProvider: "google" });
    }
    if (
      state.platforms.search_console &&
      !state.platforms.google_ads &&
      !googleHasOauthOnDisk(state)
    ) {
      // SC standalone — own Google OAuth slot.
      queue.push({ key: "search_console", oauthProvider: "google" });
    }
    if (state.platforms.meta_ads && state.providerChoice.meta_ads === "native") {
      queue.push({ key: "meta_ads", oauthProvider: "meta" });
    }
    if (
      state.platforms.meta_ads &&
      state.providerChoice.meta_ads === "official"
    ) {
      // Official Meta uses the same OAuth bridge.
      queue.push({
        key: "meta_ads_official",
        oauthProvider: "meta",
        action: "oauth_meta",
      });
    }
    if (state.platforms.ga4) {
      queue.push({ key: "ga4", inputs: ["service_account_path", "project_id"] });
    }
    return queue;
  }

  function renderSequentialQueue(host, state, render) {
    // Inline note: Search Console alone + Google already authenticated
    // means we silently skipped the SC OAuth slot. Tell the user so the
    // wizard's "no auth step shown" isn't mysterious.
    const scSkippedByGoogle =
      state.platforms.search_console &&
      !state.platforms.google_ads &&
      googleHasOauthOnDisk(state);
    if (scSkippedByGoogle) {
      const note = document.createElement("div");
      note.className = "wizard-shared-with-sc-note";
      note.textContent = MUREO.t("auth_wizard.google.already_authenticated");
      host.appendChild(note);
    }

    const queue = buildAuthQueue(state);
    if (queue.length === 0) {
      // Empty queue can happen when the only selected platform is
      // Search Console AND Google OAuth is already on disk (Issue #7).
      // Outer Back/Next are hidden while the auth step is active, so
      // we render a Continue button that hands control back to the
      // outer wizard's gotoNext.
      if (!scSkippedByGoogle) {
        const note = document.createElement("p");
        note.textContent = MUREO.t("wizard.auth.oauth_success");
        host.appendChild(note);
      }
      const continueBtn = document.createElement("button");
      continueBtn.type = "button";
      continueBtn.className = "btn btn-primary";
      continueBtn.textContent = MUREO.t("wizard.next");
      continueBtn.addEventListener("click", function () {
        if (
          window.MUREO_WIZARD &&
          typeof window.MUREO_WIZARD.gotoNext === "function"
        ) {
          window.MUREO_WIZARD.gotoNext();
        } else {
          render();
        }
      });
      host.appendChild(continueBtn);
      return;
    }

    const cursor = { index: 0 };
    function renderCurrent() {
      while (host.firstChild) host.removeChild(host.firstChild);
      const slot = queue[cursor.index];
      if (!slot) return;
      const wrap = renderStepWizard(slot, state, function onSlotDone() {
        cursor.index += 1;
        if (cursor.index < queue.length) {
          renderCurrent();
        } else if (
          window.MUREO_WIZARD &&
          typeof window.MUREO_WIZARD.gotoNext === "function"
        ) {
          // Hand control back to outer wizard once the queue empties.
          window.MUREO_WIZARD.gotoNext();
        } else {
          render();
        }
      }, state);
      host.appendChild(wrap);
    }
    renderCurrent();
  }

  function renderStepWizard(slot, state, onAllDone, outerState) {
    const wrap = document.createElement("section");
    const titleKey = "wizard.auth." + slot.key + "_title";
    wrap.innerHTML = "<h3>" + MUREO.t(titleKey) + "</h3>";

    if (slot.key === "google_ads" && outerState && outerState.platforms.search_console) {
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

    // Input-based slots (e.g. GA4) need an explicit "完了 / Done" button
    // gated by the inputs being filled. OAuth-only slots auto-advance
    // on pollOAuth success — no inner Next button.
    let doneBtn = null;
    if (slot.inputs) {
      doneBtn = document.createElement("button");
      doneBtn.type = "button";
      doneBtn.className = "btn btn-primary";
      doneBtn.textContent = MUREO.t("wizard.auth.done_button");
      doneBtn.setAttribute("data-i18n", "wizard.auth.done_button");
      doneBtn.disabled = true;
      doneBtn.addEventListener("click", function () { onAllDone(); });

      const completionFlags = {};
      slot.inputs.forEach(function (field) {
        const label = document.createElement("label");
        label.style.display = "block";
        label.textContent = field;
        const input = document.createElement("input");
        input.type = "text";
        input.addEventListener("input", function () {
          completionFlags[field] = Boolean(input.value);
          const allFilled = slot.inputs.every(function (f) {
            return completionFlags[f];
          });
          doneBtn.disabled = !allFilled;
        });
        label.appendChild(input);
        wrap.appendChild(label);
      });
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
          pollOAuth(slot.oauthProvider, status, function () {
            // Auto-advance: intermediate slots roll to the next slot;
            // the final slot hands control back to the outer wizard.
            onAllDone();
          });
        } else {
          status.textContent = MUREO.t("wizard.auth.oauth_failed");
          btn.disabled = false;
        }
      });
      wrap.appendChild(btn);
      wrap.appendChild(status);
    }

    if (doneBtn) wrap.appendChild(doneBtn);

    return wrap;
  }

  function pollOAuth(provider, statusNode, onFinished) {
    let cancelled = false;
    function tick() {
      if (cancelled) return;
      fetch("/api/oauth/" + provider + "/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.success) {
            statusNode.textContent = MUREO.t("wizard.auth.oauth_success");
            cancelled = true;
            onFinished();
          } else if (data && data.error) {
            statusNode.textContent = MUREO.t("wizard.auth.oauth_failed");
            cancelled = true;
          } else {
            setTimeout(tick, 750);
          }
        })
        .catch(function () { setTimeout(tick, 750); });
    }
    tick();
  }

  window.MUREO_AUTH = {
    renderProvidersInstall: renderProvidersInstall,
    renderSequentialQueue: renderSequentialQueue,
    buildAuthQueue: buildAuthQueue,
  };
})();
