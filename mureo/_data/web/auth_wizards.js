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
        // Replacement via a function so a server-derived detail containing
        // "$" sequences (e.g. "$&", "$1") is inserted literally rather than
        // triggering String.replace's special-pattern substitution.
        status.textContent = tmpl.replace("{detail}", function () {
          return detail;
        });
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
        // Function replacement so a "$"-containing detail is inserted
        // literally (see the note at the providers-install failure path).
        const safeDetail = detail || "unknown";
        const msg = tmpl.replace("{detail}", function () {
          return safeDetail;
        });
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
        (platform === "ga4" && state.platforms.ga4 && !state.multiAccountAuth) ||
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
    if (state.platforms.ga4 && !state.multiAccountAuth) {
      // #442: under a multi-account backend GA4 is wired per-account, not as
      // one shared service account, so the Setup-tab GA4 slot is hidden. The
      // server also refuses the write (_post_env_var); this is the UX half.
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

        const tokenCard = buildMetaTokenCard(onAllDone);
        const tokenPanel = document.createElement("div");
        tokenPanel.className = "auth-method-panel";
        tokenPanel.setAttribute("data-auth-method-panel", "token");
        tokenPanel.hidden = true;
        tokenPanel.appendChild(tokenCard);

        // Chooser FIRST, then the panels — the pollOAuth timeout hint tells
        // the operator to switch to the token option *above*.
        wrap.appendChild(
          buildMetaMethodChooser(tokenPanel, oauthPanel, tokenCard)
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

  // The two Meta connection methods, in the order the operator sees them.
  // The system-user token leads and carries the Recommended badge: it is the
  // only path that works for a Live-mode app, which is the common case once
  // an account leaves development.
  const META_AUTH_METHODS = [
    {
      method: "token",
      titleKey: "wizard.auth.meta_method_token_title",
      descKey: "wizard.auth.meta_method_token_desc",
      badgeKey: "wizard.auth.meta_method_recommended_badge",
    },
    {
      method: "oauth",
      titleKey: "wizard.auth.meta_method_oauth_title",
      descKey: "wizard.auth.meta_method_oauth_desc",
      badgeKey: null,
    },
  ];

  const META_CHOOSER_TITLE_ID = "meta-method-chooser-title";

  // Heading, subline and the (empty) radiogroup the option cards go into.
  function buildChooserFrame() {
    const chooser = document.createElement("div");
    chooser.className = "auth-method-chooser";

    const heading = document.createElement("h4");
    heading.className = "auth-method-chooser-title";
    heading.id = META_CHOOSER_TITLE_ID;
    heading.textContent = MUREO.t("wizard.auth.meta_method_chooser_title");
    heading.setAttribute("data-i18n", "wizard.auth.meta_method_chooser_title");
    chooser.appendChild(heading);

    const sub = document.createElement("p");
    sub.className = "auth-method-chooser-sub";
    sub.textContent = MUREO.t("wizard.auth.meta_method_chooser_subtitle");
    sub.setAttribute("data-i18n", "wizard.auth.meta_method_chooser_subtitle");
    chooser.appendChild(sub);

    const group = document.createElement("div");
    group.className = "auth-method-options";
    group.setAttribute("role", "radiogroup");
    // Labelled by the heading NODE rather than an aria-label string, so the
    // locale switcher (applyTranslations rewrites [data-i18n] text) keeps the
    // accessible name in sync for free.
    group.setAttribute("aria-labelledby", META_CHOOSER_TITLE_ID);
    chooser.appendChild(group);

    return { chooser: chooser, group: group };
  }

  // Title row (+ optional Recommended badge) and description. Each string is
  // its own leaf node: applyTranslations assigns textContent to every
  // [data-i18n] element, so a key on the card itself would wipe its children
  // on a locale switch.
  function fillMethodOptionCard(card, spec) {
    const head = document.createElement("div");
    head.className = "auth-method-option-head";
    const title = document.createElement("span");
    title.className = "auth-method-option-title";
    title.textContent = MUREO.t(spec.titleKey);
    title.setAttribute("data-i18n", spec.titleKey);
    head.appendChild(title);
    if (spec.badgeKey) {
      const badge = document.createElement("span");
      badge.className = "auth-method-option-badge";
      badge.textContent = MUREO.t(spec.badgeKey);
      badge.setAttribute("data-i18n", spec.badgeKey);
      head.appendChild(badge);
    }
    card.appendChild(head);

    const desc = document.createElement("span");
    desc.className = "auth-method-option-desc";
    desc.textContent = MUREO.t(spec.descKey);
    desc.setAttribute("data-i18n", spec.descKey);
    card.appendChild(desc);
  }

  // The WAI-ARIA radio keyboard contract: Space/Enter select, arrows step,
  // Home/End jump to the edges. Unhandled keys fall through untouched.
  function handleMethodOptionKey(ev, method, handlers) {
    const key = ev.key;
    if (key === " " || key === "Spacebar" || key === "Enter") {
      handlers.select(method);
    } else if (key === "ArrowDown" || key === "ArrowRight") {
      handlers.moveFocus(1);
    } else if (key === "ArrowUp" || key === "ArrowLeft") {
      handlers.moveFocus(-1);
    } else if (key === "Home") {
      handlers.toEdge(0);
    } else if (key === "End") {
      handlers.toEdge(-1);
    } else {
      return;
    }
    ev.preventDefault();
  }

  // One option card. `handlers` supplies the group-level behavior the card
  // cannot know about: {select(method), moveFocus(delta), toEdge(index)}.
  function buildMethodOptionCard(spec, index, handlers) {
    const card = document.createElement("div");
    card.className = "auth-method-option";
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", "false");
    card.setAttribute("data-auth-method", spec.method);
    // With no radio checked, the first option is the group's tab stop.
    card.tabIndex = index === 0 ? 0 : -1;
    fillMethodOptionCard(card, spec);

    card.addEventListener("click", function () {
      // Safari does not focus a clicked tabindex div, which would leave the
      // roving-tabindex "current" item behind the visible selection and make
      // the next arrow key step from the wrong place.
      card.focus();
      handlers.select(spec.method);
    });
    card.addEventListener("keydown", function (ev) {
      handleMethodOptionKey(ev, spec.method, handlers);
    });
    return card;
  }

  function buildMetaMethodChooser(tokenPanel, oauthPanel, tokenCard) {
    // Framework-free radiogroup: plain divs carrying role/aria-checked and a
    // roving tabindex, so it behaves like a native radio group for keyboard
    // and screen-reader users without pulling in a UI library.
    const frame = buildChooserFrame();
    const cards = [];
    // NOTHING is preselected — this is the actual fix. Any default makes one
    // path look like "the" path, which is exactly how token-bound operators
    // ended up in the OAuth dead end.
    let selectedMethod = null;

    function select(method) {
      selectedMethod = method;
      cards.forEach(function (card) {
        const isOn = card.getAttribute("data-auth-method") === selectedMethod;
        card.setAttribute("aria-checked", isOn ? "true" : "false");
        // Roving tabindex: the checked option is the group's single tab stop.
        card.tabIndex = isOn ? 0 : -1;
      });
      // Both panels are derived from the selection rather than one being
      // toggled, so re-picking the same option is idempotent and switching
      // swaps the visible flow instead of stacking a second one.
      tokenPanel.hidden = method !== "token";
      oauthPanel.hidden = method !== "oauth";
      // The token flow is the destination, not another disclosure to hunt
      // for — reveal the card already expanded.
      if (method === "token" && tokenCard) tokenCard.open = true;
    }

    function focusCard(card) {
      card.focus();
      select(card.getAttribute("data-auth-method"));
    }

    function moveFocus(delta) {
      const current = cards.indexOf(document.activeElement);
      focusCard(current === -1
        ? cards[0]
        : cards[(current + delta + cards.length) % cards.length]);
    }

    // Home/End: index 0 or -1 (last), completing the WAI-ARIA radio pattern.
    function toEdge(index) {
      focusCard(index < 0 ? cards[cards.length - 1] : cards[index]);
    }

    const handlers = { select: select, moveFocus: moveFocus, toEdge: toEdge };
    META_AUTH_METHODS.forEach(function (spec, index) {
      const card = buildMethodOptionCard(spec, index, handlers);
      cards.push(card);
      frame.group.appendChild(card);
    });

    return frame.chooser;
  }

  function buildMetaTokenCard(onDone) {
    // Paste a Business Manager system-user token instead of running the
    // browser OAuth. Framework-free — a native <details> element, plain
    // inputs, and MUREO.postJson to the #458 route.
    //
    // Still a <details class="meta-token-card">: the chooser opens it on
    // selection, and downstream extensions locate the card (and its optional
    // account picker) through exactly this tag + class.
    const details = document.createElement("details");
    details.className = "meta-token-card";

    const summary = document.createElement("summary");
    // De-emphasized, not removed: the chooser already reveals the card
    // expanded, so the toggle is redundant chrome — but it stays in the DOM
    // as the disclosure control and as a pinned downstream hook.
    summary.className = "meta-token-card-summary";
    summary.textContent = MUREO.t("wizard.auth.meta_token_card_title");
    summary.setAttribute("data-i18n", "wizard.auth.meta_token_card_title");
    details.appendChild(summary);

    const intro = document.createElement("p");
    intro.textContent = MUREO.t("wizard.auth.meta_token_card_intro");
    intro.setAttribute("data-i18n", "wizard.auth.meta_token_card_intro");
    details.appendChild(intro);

    // The 4-step Business Manager token guide.
    const guide = document.createElement("ol");
    ["wizard.auth.meta_token_guide_1", "wizard.auth.meta_token_guide_2",
      "wizard.auth.meta_token_guide_3", "wizard.auth.meta_token_guide_4"
    ].forEach(function (key) {
      const li = document.createElement("li");
      li.textContent = MUREO.t(key);
      li.setAttribute("data-i18n", key);
      guide.appendChild(li);
    });
    details.appendChild(guide);

    // Token entry — password-typed and opted out of autofill (a
    // never-expiring secret must not be remembered by the browser).
    const tokenLabel = document.createElement("label");
    tokenLabel.style.display = "block";
    tokenLabel.textContent = MUREO.t("wizard.auth.meta_token_label");
    tokenLabel.setAttribute("data-i18n", "wizard.auth.meta_token_label");
    const tokenInput = document.createElement("input");
    tokenInput.type = "password";
    tokenInput.autocomplete = "new-password";
    tokenLabel.appendChild(tokenInput);
    details.appendChild(tokenLabel);

    const validateBtn = document.createElement("button");
    validateBtn.type = "button";
    validateBtn.className = "btn btn-secondary";
    validateBtn.textContent = MUREO.t("wizard.auth.meta_token_validate_button");
    validateBtn.setAttribute("data-i18n", "wizard.auth.meta_token_validate_button");
    details.appendChild(validateBtn);

    // Probe results (scopes + account picker) — hidden until validated.
    const results = document.createElement("div");
    results.hidden = true;
    const grantedP = document.createElement("p");
    const missingP = document.createElement("p");
    const accountLabel = document.createElement("label");
    accountLabel.style.display = "block";
    accountLabel.textContent = MUREO.t("wizard.auth.meta_token_account_label");
    accountLabel.setAttribute("data-i18n", "wizard.auth.meta_token_account_label");
    const accountSelect = document.createElement("select");
    accountLabel.appendChild(accountSelect);
    // The account is OPTIONAL — say so under the picker rather than leaving
    // the operator to guess (some deployments assign the ad account through a
    // separate management surface, so a global selection is unnecessary).
    const accountHint = document.createElement("small");
    accountHint.className = "field-hint";
    accountHint.textContent = MUREO.t("wizard.auth.meta_token_account_hint");
    accountHint.setAttribute("data-i18n", "wizard.auth.meta_token_account_hint");
    results.appendChild(grantedP);
    results.appendChild(missingP);
    results.appendChild(accountLabel);
    results.appendChild(accountHint);
    details.appendChild(results);

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-primary";
    saveBtn.textContent = MUREO.t("wizard.auth.meta_token_save_button");
    saveBtn.setAttribute("data-i18n", "wizard.auth.meta_token_save_button");
    saveBtn.disabled = true;
    details.appendChild(saveBtn);

    const status = document.createElement("p");
    status.className = "wizard-shared-with-sc-note";
    details.appendChild(status);

    function renderProbe(body) {
      const granted = (body.scopes || []).join(", ");
      const missing = (body.missing_scopes || []).join(", ");
      grantedP.textContent =
        MUREO.t("wizard.auth.meta_token_scopes_granted") + ": " + granted;
      missingP.textContent =
        MUREO.t("wizard.auth.meta_token_scopes_missing") + ": " + (missing || "-");
      accountSelect.innerHTML = "";
      // Placeholder FIRST so it is the default selection: a <select> with no
      // explicit selection defaults to its first option, which without this
      // silently pre-selects the first probed account and Save would persist
      // an account the operator never chose. Its empty value makes the save
      // handler's `accountSelect.value || null` post account_id: null.
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = MUREO.t(
        "wizard.auth.meta_token_account_placeholder");
      placeholder.setAttribute(
        "data-i18n", "wizard.auth.meta_token_account_placeholder");
      accountSelect.appendChild(placeholder);
      (body.accounts || []).forEach(function (acct) {
        const opt = document.createElement("option");
        opt.value = acct.id;
        opt.textContent = (acct.name || acct.id) + " (" + acct.id + ")";
        accountSelect.appendChild(opt);
      });
      const noAccounts = (body.accounts || []).length === 0;
      accountLabel.hidden = noAccounts;
      accountHint.hidden = noAccounts;
      results.hidden = false;
      saveBtn.disabled = false;
    }

    validateBtn.addEventListener("click", async function () {
      const token = tokenInput.value.trim();
      if (!token) return;
      validateBtn.disabled = true;
      status.textContent = "";
      const res = await MUREO.postJson("/api/credentials/meta/token", {
        access_token: token,
        validate_only: true,
      });
      validateBtn.disabled = false;
      if (res.ok && res.body) {
        renderProbe(res.body);
      } else {
        const msg = (res.body && res.body.detail) ||
          MUREO.t("wizard.auth.oauth_failed");
        status.textContent = msg;
        MUREO.toast(msg, "error");
      }
    });

    saveBtn.addEventListener("click", async function () {
      const token = tokenInput.value.trim();
      if (!token) return;
      saveBtn.disabled = true;
      const res = await MUREO.postJson("/api/credentials/meta/token", {
        access_token: token,
        account_id: accountSelect.value || null,
      });
      if (res.ok && res.body && res.body.status === "ok") {
        const msg = MUREO.t("wizard.auth.meta_token_saved");
        status.textContent = msg;
        MUREO.toast(msg, "success");
        onDone();
      } else {
        const msg = (res.body && res.body.detail) ||
          MUREO.t("wizard.auth.oauth_failed");
        status.textContent = msg;
        MUREO.toast(msg, "error");
        saveBtn.disabled = false;
      }
    });

    return details;
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

  window.MUREO_AUTH = {
    renderProvidersInstall: renderProvidersInstall,
    renderSequentialQueue: renderSequentialQueue,
    buildAuthQueue: buildAuthQueue,
  };
})();
