// wizard_install_slots.js — the providers-install step of the configure
// wizard: one slot per official MCP the operator chose (Google Ads, Meta,
// GA4, TikTok), its Install button, and the inline recovery card for an
// install that answers `needs_credentials`. Kept out of auth_wizards.js so
// that file stays within the 800-line budget. Loaded BEFORE auth_wizards.js,
// which re-exports renderProvidersInstall through window.MUREO_AUTH; the
// Meta connector card is read off window.MUREO_AUTH_META at call time.

(function () {
  "use strict";

  const PROVIDER_INSTALL_ORDER = ["google_ads", "meta_ads", "ga4", "tiktok_ads"];
  const TIKTOK_HOSTED_URL =
    "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer";

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

  // The service-account path field of the needs-credentials card: its label
  // with the input, then the status line the save-and-retry flow writes to.
  function buildServiceAccountField(card) {
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
    return { input: input, status: status, setStatus: setStatus };
  }

  // Persist the service-account path into google_ads.service_account_path
  // (section-aware write — the shared GOOGLE_APPLICATION_CREDENTIALS name).
  // Resolves to whether the write was accepted; a network error is a no.
  async function saveServiceAccountPath(input) {
    let saveRes;
    try {
      saveRes = await MUREO.postJson("/api/credentials/env-var", {
        name: "GOOGLE_APPLICATION_CREDENTIALS",
        value: input.value,
        section: "google_ads",
      });
    } catch (_e) {
      return false;
    }
    return Boolean(saveRes.ok);
  }

  // The retried install answered something other than success.
  function showRetryOutcome(st, outcome, res, status, setStatus) {
    if (st === "needs_credentials") {
      // Still short of full creds (e.g. the service-account path is missing).
      setStatus("wizard.providers_install.still_needs_credentials");
    } else {
      let key = "wizard.providers_install.failed";
      let detail = outcome.ok ? res.body.detail || st : outcome.code || "request_failed";
      if (outcome.code === "installer_missing") { // detail: the executable
        key = "wizard.providers_install.installer_missing";
        detail = outcome.body.detail || "unknown";
      }
      const tmpl = MUREO.t(key);
      status.hidden = false;
      // Replacement via a function so a server-derived detail containing
      // "$" sequences (e.g. "$&", "$1") is inserted literally rather than
      // triggering String.replace's special-pattern substitution; global,
      // since a template may name {detail} more than once.
      status.textContent = tmpl.replace(/\{detail\}/g, function () {
        return detail;
      });
    }
  }

  function wireSaveAndRetry(retryBtn, input, status, setStatus, state, providerId, onComplete) {
    retryBtn.addEventListener("click", async function () {
      retryBtn.disabled = true;
      // 1) Persist the service-account path.
      setStatus("wizard.auth.saving");
      if (!(await saveServiceAccountPath(input))) {
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
      const outcome = MUREO.postOutcome(res);
      const st = outcome.ok ? res.body.status : null;
      if (st === "ok" || st === "noop") { // noop: already registered
        await finishInstall(state, providerId, onComplete);
        return;
      }
      showRetryOutcome(st, outcome, res, status, setStatus);
      retryBtn.disabled = false;
    });
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

    const field = buildServiceAccountField(card);
    const input = field.input;

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "btn btn-primary";
    retryBtn.textContent = MUREO.t("wizard.providers_install.save_retry");
    retryBtn.setAttribute("data-i18n", "wizard.providers_install.save_retry");
    retryBtn.disabled = true;
    input.addEventListener("input", function () {
      retryBtn.disabled = !input.value;
    });

    wireSaveAndRetry(
      retryBtn, input, field.status, field.setStatus, state, providerId, onComplete
    );

    card.appendChild(retryBtn);
    return card;
  }

  // Endpoint + copy button — handy for the Desktop custom-connector
  // dialog or to confirm the URL for `claude mcp add`.
  function buildEndpointCopyRow(url) {
    const urlRow = document.createElement("div");
    urlRow.className = "connector-url-row";
    const code = document.createElement("code");
    code.textContent = url;
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
          .writeText(url)
          .then(done, function () {
            MUREO.toast(url);
          });
      } else {
        MUREO.toast(url);
      }
    });
    urlRow.appendChild(code);
    urlRow.appendChild(copyBtn);
    return urlRow;
  }

  // TikTok (tiktok-ads-official): hosted_http, but it supports OAuth
  // Dynamic Client Registration AND has no mureo-native platform — so it
  // needs neither Meta's connector-confirm flow nor a native-disable
  // step. Show a simple, host-specific setup card (the same DCR guidance
  // as the dashboard) plus a copy-able endpoint. Advancing is via the
  // outer wizard's Next (no Install button — mureo registers nothing;
  // the user runs `claude mcp add` / a connector, then /mcp). Handled by
  // its own branch, so the Meta-only `isHosted` check is left untouched.
  function buildTiktokHostedCard(wrap, state, platform) {
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
    // The endpoint row is omitted on Codex, where the provider is not wired.
    if (state.host !== "codex") {
      wrap.appendChild(buildEndpointCopyRow(TIKTOK_HOSTED_URL));
    }
    return wrap;
  }

  // Hosted MCP (Meta): mureo never registers it locally on EITHER
  // host. Meta's hosted MCP has no OAuth dynamic client registration,
  // so it cannot be authenticated as a Claude Code user-scope server
  // (`/mcp` fails) and Desktop's config can't carry the remote http
  // shape either. The only working path is a Claude.ai account
  // connector — show those steps directly (no Install button; there
  // is nothing for mureo to register). showManualSetup() picks the
  // connector.code.* (Code) vs connector.* (Desktop) copy by host.
  function buildHostedMetaCard(wrap, state, platform, providerId, onComplete) {
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
    if (!window.MUREO_AUTH_META.showManualSetup(wrap, state, providerId)) {
      onComplete();
    }
    return wrap;
  }

  // What the Install click does with an answered request. `ctx` carries the
  // slot's btn, statusLine, wrap, state, platform, providerId, onComplete
  // and fail.
  async function handleInstallOutcome(outcome, ctx) {
    if (!outcome.ok) {
      if (outcome.code === "installer_missing") { // detail: the executable
        return ctx.fail(outcome.body.detail, "wizard.providers_install.installer_missing");
      }
      return ctx.fail(outcome.code || "request_failed"); // error, then detail
    }
    const st = outcome.body.status;
    if (st === "ok" || st === "noop") { // noop: already registered
      await finishInstall(ctx.state, ctx.providerId, ctx.onComplete);
    } else if (st === "needs_credentials") {
      // The official server registered but cannot authenticate yet —
      // it needs ADC credentials the wizard hasn't collected (Google
      // Ads: a service-account JSON path). Surface an inline input +
      // "Save & install" instead of a bare error. mureo-native stays
      // ON (backend did not disable it), so the user is never stranded.
      ctx.btn.remove();
      ctx.statusLine.hidden = true;
      ctx.wrap.appendChild(
        renderNeedsCredentialsCard(ctx.platform, ctx.providerId, ctx.state, ctx.onComplete)
      );
    } else if (st === "auth_required" || st === "manual_required") {
      // Defensive fallback: hosted (Meta) is short-circuited to the
      // connector card BEFORE this Install button is ever shown
      // (mureo registers nothing locally on either host). If a
      // backend path still reports manual_required/auth_required,
      // surface the Claude.ai connector steps (connector.code.* on
      // Code, connector.* on Desktop) rather than a bare error.
      ctx.state.providerInstalled[ctx.providerId] = true;
      ctx.btn.remove();
      ctx.statusLine.hidden = true;
      if (!window.MUREO_AUTH_META.showManualSetup(ctx.wrap, ctx.state, ctx.providerId)) {
        ctx.onComplete();
      }
    } else {
      ctx.fail(outcome.body.detail || st);
    }
  }

  function wireInstallButton(wrap, state, platform, providerId, onComplete) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.textContent = MUREO.t("dashboard.action_install");
    // Status line so a slow pipx/git build doesn't look frozen and
    // a failure shows WHY (not a silent no-op — issue #1).
    const statusLine = document.createElement("p");
    statusLine.className = "dashboard-provider-hosted-note";
    statusLine.hidden = true;
    function fail(detail, key) {
      const tmpl = MUREO.t(key || "wizard.providers_install.failed");
      // Function replacement so a "$"-containing detail is inserted
      // literally (see the note at the providers-install failure path);
      // global, since a template may name {detail} more than once.
      const safeDetail = detail || "unknown";
      const msg = tmpl.replace(/\{detail\}/g, function () {
        return safeDetail;
      });
      statusLine.hidden = false;
      statusLine.textContent = msg;
      MUREO.toast(msg);
    }
    const ctx = {
      btn: btn, statusLine: statusLine, wrap: wrap, state: state, platform: platform,
      providerId: providerId, onComplete: onComplete, fail: fail,
    };
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
      return handleInstallOutcome(MUREO.postOutcome(res), ctx);
    });
    wrap.appendChild(btn);
    wrap.appendChild(statusLine);
  }

  function buildProviderInstallSlot(state, platform, onComplete) {
    const wrap = document.createElement("section");
    wrap.style.marginTop = "16px";
    const providerId = platform.replace("_", "-") + "-official";

    if (providerId === "tiktok-ads-official") {
      return buildTiktokHostedCard(wrap, state, platform);
    }

    const installed = state.providerInstalled[providerId];
    // hosted_http providers (catalog install_kind === "hosted_http").
    // meta-ads-official is the only one that reaches THIS branch: TikTok
    // (also hosted_http) is handled by its dedicated DCR card above, and
    // no other hosted provider is a wizard platform. If a Meta-style
    // (no-DCR, native-coexisting) hosted provider is ever added, extend
    // this check.
    const isHosted = providerId === "meta-ads-official";
    if (isHosted) {
      return buildHostedMetaCard(wrap, state, platform, providerId, onComplete);
    }

    wrap.innerHTML =
      "<h3>" + MUREO.t("wizard.provider_banner." + platform) + "</h3>" +
      "<p>" + (installed ? "✓ " + MUREO.t("dashboard.installed") : "✗ " + MUREO.t("dashboard.not_installed")) + "</p>";

    if (!installed) {
      wireInstallButton(wrap, state, platform, providerId, onComplete);
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

  window.MUREO_AUTH_INSTALL = {
    renderProvidersInstall: renderProvidersInstall,
  };
})();
