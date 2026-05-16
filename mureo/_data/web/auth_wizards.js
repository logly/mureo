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
    // hosted_http providers (catalog install_kind === "hosted_http").
    // Phase 1: only meta-ads-official. Extend when a new one is added.
    const isHosted = providerId === "meta-ads-official";
    const onDesktop = state.host === "claude-desktop";

    // Meta's official hosted Ads MCP endpoint (matches catalog.py).
    const META_HOSTED_URL = "https://mcp.facebook.com/ads";

    // Render the manual Connectors setup as an actionable card:
    // numbered steps + a copy-to-clipboard URL. No own "Continue"
    // button — the outer wizard's Next advances this step. Always
    // returns true (the card has no missing-translation failure mode;
    // labels fall back via MUREO.t).
    function showManualSetup() {
      // mureo cannot perform the hosted MCP's OAuth — but the finish
      // steps genuinely differ by host:
      //   - Claude Code: mureo already REGISTERED the http entry; the
      //     user authenticates interactively via `/mcp` → Authenticate
      //     (connector.code.* steps; Meta is no-DCR so a pre-registered
      //     OAuth client / the account connector is the fallback).
      //   - Claude Desktop: no in-Code `/mcp`; add it via Settings →
      //     Connectors → Add custom connector (connector.* steps).
      // Pick the host-specific i18n family accordingly.
      const isDesktopHost = state.host === "claude-desktop";
      const kp = isDesktopHost ? "connector." : "connector.code.";
      const card = document.createElement("div");
      card.className = "connector-setup-card";

      const h = document.createElement("h4");
      h.textContent = MUREO.t(kp + "setup_title");
      h.setAttribute("data-i18n", kp + "setup_title");
      card.appendChild(h);

      const lead = document.createElement("p");
      lead.className = "connector-setup-lead";
      lead.textContent = MUREO.t(kp + "setup_lead");
      lead.setAttribute("data-i18n", kp + "setup_lead");
      card.appendChild(lead);

      const ol = document.createElement("ol");
      [kp + "step1", kp + "step2"].forEach(function (k) {
        const liEl = document.createElement("li");
        liEl.textContent = MUREO.t(k);
        liEl.setAttribute("data-i18n", k);
        ol.appendChild(liEl);
      });
      // Step 3: the reference endpoint with an inline copy button
      // (Desktop pastes it into the custom-connector dialog; Code users
      // rarely need it but it's handy to confirm the right endpoint).
      const liUrl = document.createElement("li");
      const step3 = document.createElement("span");
      step3.textContent = MUREO.t(kp + "step3");
      step3.setAttribute("data-i18n", kp + "step3");
      liUrl.appendChild(step3);
      const urlRow = document.createElement("div");
      urlRow.className = "connector-url-row";
      const code = document.createElement("code");
      code.textContent = META_HOSTED_URL;
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn-secondary connector-copy-btn";
      copyBtn.textContent = MUREO.t("connector.copy");
      copyBtn.setAttribute("data-i18n", "connector.copy");
      copyBtn.addEventListener("click", function () {
        const done = function () {
          copyBtn.textContent = MUREO.t("connector.copied");
          setTimeout(function () {
            copyBtn.textContent = MUREO.t("connector.copy");
          }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(META_HOSTED_URL).then(done, function () {
            MUREO.toast(META_HOSTED_URL);
          });
        } else {
          MUREO.toast(META_HOSTED_URL);
        }
      });
      urlRow.appendChild(code);
      urlRow.appendChild(copyBtn);
      liUrl.appendChild(urlRow);
      ol.appendChild(liUrl);

      const liStep4 = document.createElement("li");
      liStep4.textContent = MUREO.t(kp + "step4");
      liStep4.setAttribute("data-i18n", kp + "step4");
      ol.appendChild(liStep4);

      card.appendChild(ol);

      // "I've connected it — finalize" : verifies the connector is
      // actually Connected, then disables the overlapping mureo-native
      // tool family so the model stops calling the credential-less
      // native tools. Never disables native unless the official path is
      // confirmed working (no stranding).
      const finalizeBtn = document.createElement("button");
      finalizeBtn.type = "button";
      finalizeBtn.className = "btn btn-secondary";
      finalizeBtn.textContent = MUREO.t("connector.finalize");
      finalizeBtn.setAttribute("data-i18n", "connector.finalize");
      const fStatus = document.createElement("p");
      fStatus.className = "dashboard-provider-hosted-note";
      fStatus.hidden = true;
      finalizeBtn.addEventListener("click", async function () {
        finalizeBtn.disabled = true;
        fStatus.hidden = false;
        fStatus.textContent = MUREO.t("connector.finalize_checking");
        let res;
        try {
          res = await MUREO.postJson("/api/providers/confirm", {
            provider_id: providerId,
          });
        } catch (_e) {
          finalizeBtn.disabled = false;
          fStatus.textContent = MUREO.t("connector.finalize_failed");
          return;
        }
        finalizeBtn.disabled = false;
        const st = res && res.body && res.body.status;
        const key =
          st === "ok"
            ? "connector.finalize_ok"
            : st === "noop"
            ? "connector.finalize_already"
            : st === "not_connected"
            ? "connector.finalize_not_connected"
            : st === "manual"
            ? "connector.finalize_manual"
            : "connector.finalize_failed";
        fStatus.textContent = MUREO.t(key);
        fStatus.setAttribute("data-i18n", key);
      });
      card.appendChild(finalizeBtn);
      card.appendChild(fStatus);

      wrap.appendChild(card);
      return true;
    }

    // Claude DESKTOP hosted MCP: there is no in-Code `/mcp` OAuth and
    // Desktop's config can't carry the remote http shape — the user
    // adds it via Settings → Connectors. Show those steps directly
    // (no Install button — nothing for mureo to register on Desktop).
    // Claude CODE hosted falls through to the normal Install button:
    // mureo registers the http entry, the result is `auth_required`,
    // and the `/mcp` Authenticate steps are shown afterwards.
    if (isHosted && onDesktop) {
      wrap.innerHTML =
        "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>";
      if (!showManualSetup()) onComplete();
      return wrap;
    }

    wrap.innerHTML =
      "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>" +
      "<p>" + (installed ? "✓ " + MUREO.t("dashboard.installed") : "✗ " + MUREO.t("dashboard.not_installed")) + "</p>";

    if (!installed) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-primary";
      btn.textContent = MUREO.t("dashboard.action_install");
      // Status line so a slow pipx/git build doesn't look frozen and
      // a failure shows WHY (not a silent no-op — issue #1).
      const statusLine = document.createElement("p");
      statusLine.className = "dashboard-provider-hosted-note";
      statusLine.hidden = true;
      function fail(detail) {
        const tmpl = MUREO.t("wizard.providers_install.failed");
        const msg = tmpl.replace("{detail}", detail || "unknown");
        statusLine.hidden = false;
        statusLine.textContent = msg;
        MUREO.toast(msg);
      }
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        statusLine.hidden = false;
        statusLine.textContent = MUREO.t("wizard.providers_install.installing");
        let res;
        try {
          res = await MUREO.postJson("/api/providers/install", {
            provider_id: providerId,
          });
        } catch (_e) {
          btn.disabled = false;
          fail("network_error");
          return;
        }
        btn.disabled = false;
        if (!res.ok || !res.body) {
          fail(res && res.body ? res.body.detail : "request_failed");
          return;
        }
        const st = res.body.status;
        if (st === "ok") {
          // Re-sync wizard state from the authoritative /api/status
          // (the optimistic local flag alone left the row showing
          // "✗ not registered" when status disagreed — issue #1).
          state.providerInstalled[providerId] = true;
          await MUREO.loadStatus();
          if (
            window.MUREO_WIZARD &&
            typeof window.MUREO_WIZARD.hydrateStateFromStatus === "function" &&
            MUREO.state &&
            MUREO.state.status
          ) {
            window.MUREO_WIZARD.hydrateStateFromStatus(MUREO.state.status);
          }
          onComplete();
        } else if (st === "auth_required" || st === "manual_required") {
          // auth_required: Claude Code registered the hosted http entry;
          // the user must finish OAuth via `/mcp` (showManualSetup
          // renders the connector.code.* `/mcp` steps for this host).
          // manual_required: Claude Desktop → Settings → Connectors.
          state.providerInstalled[providerId] = true;
          btn.remove();
          statusLine.hidden = true;
          if (!showManualSetup()) onComplete();
        } else {
          fail(res.body.detail || st);
        }
      });
      wrap.appendChild(btn);
      wrap.appendChild(statusLine);
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
    if (state.platforms.google_ads) {
      // Native AND official Google Ads both need the same Developer
      // Token + Google OAuth refresh token. The official upstream MCP
      // cannot read credentials.json, so we still collect them here and
      // inject them as env into its MCP block at install time.
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
    // NOTE: official Meta (hosted_http) is intentionally NOT queued for
    // OAuth here. Its OAuth is the MCP HTTP-transport handshake performed
    // by Claude itself on first connect (RFC 9728) — configure cannot and
    // must not do it. The provider-choice "next page" (providers_install
    // step) shows the manual setup instructions instead.
    if (state.platforms.ga4) {
      // Each input carries the credentials.json-backed env var NAME it
      // persists to (POSTed to /api/credentials/env-var on Done) plus a
      // localized label key. GA4-official reads these env vars at
      // launch, so they MUST be saved here — collecting without
      // persisting silently leaves the official MCP unauthenticated.
      queue.push({
        key: "ga4",
        inputs: [
          {
            name: "GOOGLE_APPLICATION_CREDENTIALS",
            labelKey: "wizard.auth.ga4_sa_path",
          },
          {
            name: "GOOGLE_PROJECT_ID",
            labelKey: "wizard.auth.ga4_project_id",
          },
        ],
      });
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
              status.textContent = MUREO.t("wizard.auth.save_failed");
              doneBtn.disabled = false;
              return;
            }
          }
        } catch (_e) {
          status.textContent = MUREO.t("wizard.auth.save_failed");
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
