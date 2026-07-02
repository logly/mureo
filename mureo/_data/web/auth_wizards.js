// auth_wizards.js — provider-install and per-provider auth wizards.
// Renders the sequential queue of provider installs (Step 5+) and the
// in-wizard OAuth handoffs. Hides outer Back/Next while a sub-wizard
// is active.

(function () {
  "use strict";

  const PROVIDER_INSTALL_ORDER = ["google_ads", "meta_ads", "ga4", "tiktok_ads"];

  // ------------------------------------------------------------------
  // Provider install slots (Step: providers_install)
  // ------------------------------------------------------------------

  // Re-sync wizard state from the authoritative /api/status after a
  // successful install (the optimistic local flag alone left the row
  // showing "✗ not registered" when status disagreed — issue #1), then
  // advance. Shared by the first install and the needs_credentials retry.
  async function finishInstall(state, providerId, onComplete) {
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
  }

  // Inline recovery card shown when install returns `needs_credentials`
  // (#102): the official server registered but cannot authenticate from
  // env alone. Google Ads (ADC) needs a service-account JSON path — collect
  // it, persist it into google_ads.service_account_path via the
  // section-aware env-var writer, then re-run install. mureo-native is NOT
  // disabled by the backend until the official server is credentialed, so
  // the user keeps working throughout.
  function renderNeedsCredentialsCard(platform, providerId, state, onComplete) {
    const card = document.createElement("div");
    card.className = "dashboard-provider-hosted-note";

    const guidanceKey =
      platform === "google_ads"
        ? "wizard.providers_install.needs_credentials.google_ads"
        : "wizard.providers_install.needs_credentials.generic";
    const guidance = document.createElement("p");
    guidance.textContent = MUREO.t(guidanceKey);
    guidance.setAttribute("data-i18n", guidanceKey);
    card.appendChild(guidance);

    // Only Google Ads has an in-wizard credential to collect here (its ADC
    // service-account path). Other providers collect their creds in the
    // auth queue before install, so a generic message is enough.
    if (platform !== "google_ads") {
      return card;
    }

    const label = document.createElement("label");
    label.style.display = "block";
    label.textContent = MUREO.t("wizard.providers_install.sa_path_label");
    label.setAttribute("data-i18n", "wizard.providers_install.sa_path_label");
    const input = document.createElement("input");
    input.type = "text";
    label.appendChild(input);
    card.appendChild(label);

    const status = document.createElement("p");
    status.className = "dashboard-provider-hosted-note";
    status.hidden = true;
    card.appendChild(status);

    function setStatus(key) {
      status.hidden = false;
      status.textContent = MUREO.t(key);
    }

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "btn btn-primary";
    retryBtn.textContent = MUREO.t("wizard.providers_install.save_retry");
    retryBtn.setAttribute("data-i18n", "wizard.providers_install.save_retry");
    retryBtn.disabled = true;
    input.addEventListener("input", function () {
      retryBtn.disabled = !input.value;
    });

    retryBtn.addEventListener("click", async function () {
      retryBtn.disabled = true;
      // 1) Persist the service-account path into
      //    google_ads.service_account_path (section-aware write — the
      //    shared GOOGLE_APPLICATION_CREDENTIALS name).
      setStatus("wizard.auth.saving");
      let saveRes;
      try {
        saveRes = await MUREO.postJson("/api/credentials/env-var", {
          name: "GOOGLE_APPLICATION_CREDENTIALS",
          value: input.value,
          section: "google_ads",
        });
      } catch (_e) {
        setStatus("wizard.auth.save_failed");
        retryBtn.disabled = false;
        return;
      }
      if (!saveRes.ok) {
        setStatus("wizard.auth.save_failed");
        retryBtn.disabled = false;
        return;
      }
      // 2) Re-run install now that ADC creds are present.
      setStatus("wizard.providers_install.installing");
      let res;
      try {
        res = await MUREO.postJson("/api/providers/install", {
          provider_id: providerId,
        });
      } catch (_e) {
        const tmpl = MUREO.t("wizard.providers_install.failed");
        status.hidden = false;
        status.textContent = tmpl.replace("{detail}", "network_error");
        retryBtn.disabled = false;
        return;
      }
      if (res.ok && res.body && res.body.status === "ok") {
        await finishInstall(state, providerId, onComplete);
        return;
      }
      if (res.body && res.body.status === "needs_credentials") {
        // Still short of full creds (e.g. the Developer Token is missing).
        setStatus("wizard.providers_install.still_needs_credentials");
      } else {
        const tmpl = MUREO.t("wizard.providers_install.failed");
        const detail = res.body
          ? res.body.detail || res.body.status
          : "request_failed";
        status.hidden = false;
        status.textContent = tmpl.replace("{detail}", detail);
      }
      retryBtn.disabled = false;
    });

    card.appendChild(retryBtn);
    return card;
  }

  function buildProviderInstallSlot(state, platform, onComplete) {
    const wrap = document.createElement("section");
    wrap.style.marginTop = "16px";
    const providerId = platform.replace("_", "-") + "-official";

    // TikTok (tiktok-ads-official): hosted_http, but it supports OAuth
    // Dynamic Client Registration AND has no mureo-native platform — so it
    // needs neither Meta's connector-confirm flow nor a native-disable
    // step. Show a simple, host-specific setup card (the same DCR guidance
    // as the dashboard) plus a copy-able endpoint. Advancing is via the
    // outer wizard's Next (no Install button — mureo registers nothing;
    // the user runs `claude mcp add` / a connector, then /mcp). Handled by
    // its own branch here, so the Meta-only `isHosted` check below is left
    // untouched.
    if (providerId === "tiktok-ads-official") {
      const TIKTOK_HOSTED_URL =
        "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer";
      wrap.innerHTML =
        "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>";
      const noteKey =
        state.host === "claude-desktop"
          ? "dashboard.provider_tiktok_desktop_note"
          : state.host === "codex"
          ? "dashboard.provider_tiktok_codex_note"
          : "dashboard.provider_tiktok_oauth_note";
      const note = document.createElement("p");
      note.className = "dashboard-provider-hosted-note";
      note.textContent = MUREO.t(noteKey);
      note.setAttribute("data-i18n", noteKey);
      wrap.appendChild(note);
      // Endpoint + copy button — handy for the Desktop custom-connector
      // dialog or to confirm the URL for `claude mcp add`. Omitted on
      // Codex, where the provider is not wired.
      if (state.host !== "codex") {
        const urlRow = document.createElement("div");
        urlRow.className = "connector-url-row";
        const code = document.createElement("code");
        code.textContent = TIKTOK_HOSTED_URL;
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
            navigator.clipboard
              .writeText(TIKTOK_HOSTED_URL)
              .then(done, function () {
                MUREO.toast(TIKTOK_HOSTED_URL);
              });
          } else {
            MUREO.toast(TIKTOK_HOSTED_URL);
          }
        });
        urlRow.appendChild(code);
        urlRow.appendChild(copyBtn);
        wrap.appendChild(urlRow);
      }
      return wrap;
    }

    const installed = state.providerInstalled[providerId];
    // hosted_http providers (catalog install_kind === "hosted_http").
    // meta-ads-official is the only one that reaches THIS branch: TikTok
    // (also hosted_http) is handled by its dedicated DCR card above, and
    // no other hosted provider is a wizard platform. If a Meta-style
    // (no-DCR, native-coexisting) hosted provider is ever added, extend
    // this check.
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
      // mureo never registers the hosted MCP locally on EITHER host
      // (Meta has no OAuth dynamic client registration, so a local
      // user-scope server can't be authenticated). It is added as a
      // Claude.ai account connector; only the surrounding wording
      // differs by host:
      //   - Claude Code: claude.ai → Settings → Connectors → Add
      //     custom connector; /mcp then picks it up account-wide
      //     (connector.code.* steps).
      //   - Claude Desktop: Settings → Connectors → Add custom
      //     connector (connector.* steps).
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
      // Shown only when mureo can't auto-verify (Desktop = no
      // `claude mcp list`; or Claude Code CLI absent / list timed out).
      // The user's explicit "I've verified it" replaces auto-detection
      // (no-strand by deliberate consent, not a silent default).
      const affirmBtn = document.createElement("button");
      affirmBtn.type = "button";
      affirmBtn.className = "btn btn-secondary";
      affirmBtn.textContent = MUREO.t("connector.finalize_affirm");
      affirmBtn.setAttribute("data-i18n", "connector.finalize_affirm");
      affirmBtn.hidden = true;
      const fStatus = document.createElement("p");
      fStatus.className = "dashboard-provider-hosted-note";
      fStatus.hidden = true;

      async function runConfirm(affirm) {
        finalizeBtn.disabled = true;
        affirmBtn.disabled = true;
        fStatus.hidden = false;
        fStatus.textContent = MUREO.t(
          affirm ? "connector.finalize_affirming" : "connector.finalize_checking"
        );
        let res;
        try {
          res = await MUREO.postJson("/api/providers/confirm", {
            provider_id: providerId,
            // Client-authoritative host: the server session can reset
            // to the claude-code default on a configure restart, which
            // used to route a Desktop user down the Code path.
            host: state.host,
            affirm: Boolean(affirm),
          });
        } catch (_e) {
          finalizeBtn.disabled = false;
          affirmBtn.disabled = false;
          const msg = MUREO.t("connector.finalize_failed");
          fStatus.textContent = msg;
          // Inline status stays for accessibility / scroll-anchored
          // context; the toast is the scroll-resistant surface (#184).
          MUREO.toast(msg, "error");
          return;
        }
        finalizeBtn.disabled = false;
        affirmBtn.disabled = false;
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
            : st === "unverifiable"
            ? "connector.finalize_unverifiable"
            : "connector.finalize_failed";
        // manual / unverifiable = "couldn't auto-verify" → reveal the
        // explicit affirm button. ok/noop = done → hide it.
        affirmBtn.hidden = !(st === "manual" || st === "unverifiable");
        fStatus.textContent = MUREO.t(key);
        fStatus.setAttribute("data-i18n", key);
      }

      finalizeBtn.addEventListener("click", function () {
        runConfirm(false);
      });
      affirmBtn.addEventListener("click", function () {
        runConfirm(true);
      });
      card.appendChild(finalizeBtn);
      card.appendChild(affirmBtn);
      card.appendChild(fStatus);

      wrap.appendChild(card);
      return true;
    }

    // Hosted MCP (Meta): mureo never registers it locally on EITHER
    // host. Meta's hosted MCP has no OAuth dynamic client registration,
    // so it cannot be authenticated as a Claude Code user-scope server
    // (`/mcp` fails) and Desktop's config can't carry the remote http
    // shape either. The only working path is a Claude.ai account
    // connector — show those steps directly (no Install button; there
    // is nothing for mureo to register). showManualSetup() picks the
    // connector.code.* (Code) vs connector.* (Desktop) copy by host.
    if (isHosted) {
      wrap.innerHTML =
        "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>";
      // Codex has no claude.ai account connector, so Meta's hosted MCP
      // can't be wired at all — there are no connector steps to show.
      // Surface the "not available, native stays" note and let the user
      // proceed; mureo-native Meta is never disabled here.
      if (state.host === "codex") {
        const note = document.createElement("p");
        note.className = "dashboard-provider-hosted-note";
        note.textContent = MUREO.t("dashboard.provider_codex_hosted_na_note");
        note.setAttribute("data-i18n", "dashboard.provider_codex_hosted_na_note");
        wrap.appendChild(note);
        return wrap;
      }
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
          await finishInstall(state, providerId, onComplete);
        } else if (st === "needs_credentials") {
          // The official server registered but cannot authenticate yet —
          // it needs ADC credentials the wizard hasn't collected (Google
          // Ads: a service-account JSON path). Surface an inline input +
          // "Save & install" instead of a bare error. mureo-native stays
          // ON (backend did not disable it), so the user is never stranded.
          btn.remove();
          statusLine.hidden = true;
          wrap.appendChild(
            renderNeedsCredentialsCard(platform, providerId, state, onComplete)
          );
        } else if (st === "auth_required" || st === "manual_required") {
          // Defensive fallback: hosted (Meta) is short-circuited to the
          // connector card BEFORE this Install button is ever shown
          // (mureo registers nothing locally on either host). If a
          // backend path still reports manual_required/auth_required,
          // surface the Claude.ai connector steps (connector.code.* on
          // Code, connector.* on Desktop) rather than a bare error.
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
        (platform === "ga4" && state.platforms.ga4) ||
        (platform === "tiktok_ads" && state.platforms.tiktok_ads);
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

    if (slot.key === "google_ads") {
      // Scope guidance: the OAuth button mints a refresh token with the
      // adwords + webmasters scopes (mureo.auth_setup._GOOGLE_SCOPES).
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

    // Input-based slots (e.g. GA4) need an explicit "Done" button
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
          pollOAuth(slot.oauthProvider, status, function () {
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
            const msg = MUREO.t("wizard.auth.oauth_failed");
            statusNode.textContent = msg;
            MUREO.toast(msg, "error");
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
