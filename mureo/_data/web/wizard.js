// wizard.js — main configure-UI wizard state machine.
// Implements the design doc 2026-05-14 step flow with dynamic step
// counter + auto-skip based on platform / provider selection.

(function () {
  "use strict";

  const PLATFORMS = ["google_ads", "meta_ads", "search_console", "ga4"];

  // Platforms whose official provider is a hosted_http catalog entry
  // (auth is client-side browser OAuth on first use in Claude). Source
  // of truth: catalog.py install_kind === "hosted_http". Phase 1: only
  // meta-ads-official (the meta_ads platform). Extend this list when a
  // new hosted provider is added to the catalog.
  const HOSTED_PLATFORMS = ["meta_ads"];

  const STATE = {
    host: "claude-code",
    basicInstallCompleted: false,
    basicInstallSkippedByAdvanced: false,
    platforms: {
      google_ads: false,
      meta_ads: false,
      search_console: false,
      ga4: false,
    },
    providerChoice: {
      google_ads: null, // "official" | "native"
      meta_ads: null,
    },
    providerInstalled: {
      "google-ads-official": false,
      "meta-ads-official": false,
      "ga4-official": false,
    },
    // Existing on-disk credentials state, hydrated from /api/status. The
    // auth queue uses these flags to skip OAuth slots whose tokens are
    // already saved (e.g. Search Console reuses Google Ads OAuth).
    existing: {
      google: { has_oauth: false },
      meta: { has_oauth: false },
    },
    stepIndex: 0,
  };

  // ``auth`` MUST precede ``providers_install``: the official upstream
  // MCPs read credentials ONLY from env vars resolved (at install time)
  // from ~/.mureo/credentials.json, so the Developer-Token + OAuth slot
  // has to populate that file BEFORE the provider block is written.
  // (Native flows never show ``providers_install``, so the swap is inert
  // for them.)
  const ALL_STEPS = [
    "host",
    "basic",
    "platforms",
    "provider_choice",
    "auth",
    "providers_install",
    "completed",
  ];

  const STEPS_WITHOUT_SKIP = new Set([
    "host",
    "basic",
    "platforms",
    "completed",
  ]);

  function hasGoogleOrMetaPlatform() {
    return STATE.platforms.google_ads || STATE.platforms.meta_ads;
  }

  function hasOfficialProviderQueued() {
    return (
      (STATE.platforms.google_ads &&
        STATE.providerChoice.google_ads === "official") ||
      (STATE.platforms.meta_ads &&
        STATE.providerChoice.meta_ads === "official") ||
      STATE.platforms.ga4
    );
  }

  function hasAuthQueued() {
    // INVARIANT: ``auth`` MUST stay ordered AFTER ``provider_choice`` in
    // ALL_STEPS. This predicate is true for google_ads regardless of
    // provider choice, so surfacing the auth step before the choice is
    // made would strand the user on an ambiguous slot.
    // Google Ads: BOTH native and official need the same credentials
    // (Developer Token + Google OAuth refresh token). The official
    // upstream MCP can't see credentials.json, so the auth step still
    // runs to collect them — they're injected as env at install time.
    // Meta: only the native path is queued here; official Meta is a
    // hosted MCP whose OAuth is the HTTP-transport handshake Claude
    // performs on first connect (handled on the providers_install page).
    return (
      STATE.platforms.google_ads ||
      (STATE.platforms.meta_ads &&
        STATE.providerChoice.meta_ads === "native") ||
      STATE.platforms.search_console ||
      STATE.platforms.ga4
    );
  }

  function isStepRelevant(step) {
    if (step === "provider_choice") return hasGoogleOrMetaPlatform();
    if (step === "providers_install") return hasOfficialProviderQueued();
    if (step === "auth") return hasAuthQueued();
    return true;
  }

  function effectiveSteps() {
    return ALL_STEPS.filter(isStepRelevant);
  }

  function currentStep() {
    const steps = effectiveSteps();
    if (STATE.stepIndex >= steps.length) {
      STATE.stepIndex = steps.length - 1;
    }
    return steps[STATE.stepIndex];
  }

  function gotoNext() {
    const steps = effectiveSteps();
    if (STATE.stepIndex < steps.length - 1) {
      STATE.stepIndex += 1;
      render();
    }
  }

  function gotoPrev() {
    if (STATE.stepIndex > 0) {
      STATE.stepIndex -= 1;
      render();
    }
  }

  function isNextEnabled() {
    const step = currentStep();
    if (step === "host") return Boolean(STATE.host);
    if (step === "basic")
      return STATE.basicInstallCompleted || STATE.basicInstallSkippedByAdvanced;
    if (step === "platforms")
      return PLATFORMS.some(function (p) {
        return STATE.platforms[p];
      });
    if (step === "provider_choice") {
      if (STATE.platforms.google_ads && !STATE.providerChoice.google_ads)
        return false;
      if (STATE.platforms.meta_ads && !STATE.providerChoice.meta_ads)
        return false;
      return true;
    }
    return true;
  }

  function updateProgress() {
    const node = document.querySelector("[data-wizard-progress]");
    if (!node) return;
    const steps = effectiveSteps();
    const current = STATE.stepIndex + 1;
    const total = steps.length;
    node.textContent = MUREO.t("wizard.step_progress", {
      current: current,
      total: total,
    });
  }

  function deriveCompletion(status) {
    if (!status) return false;
    const parts = status.setup_parts || {};
    return Boolean(parts.mureo_mcp && parts.auth_hook && parts.skills);
  }

  function hydrateStateFromStatus(status) {
    if (!status) return;
    if (status.host) STATE.host = status.host;
    if (deriveCompletion(status)) {
      STATE.basicInstallCompleted = true;
    }
    const installed = status.providers_installed || {};
    Object.keys(STATE.providerInstalled).forEach(function (key) {
      STATE.providerInstalled[key] = Boolean(installed[key]);
    });
    const oauth = status.credentials_oauth || {};
    STATE.existing.google.has_oauth = Boolean(oauth.google);
    STATE.existing.meta.has_oauth = Boolean(oauth.meta);
  }

  // ------------------------------------------------------------------
  // Step body builders
  // ------------------------------------------------------------------
  function buildStepBody_host() {
    const wrap = document.createElement("div");
    wrap.innerHTML =
      '<h2>' + MUREO.t("wizard.host.title") + "</h2>" +
      '<div class="wizard-host-options">' +
      '<label><input type="radio" name="host" value="claude-code">' +
      MUREO.t("wizard.host.claude_code") + "</label><br>" +
      '<label><input type="radio" name="host" value="claude-desktop">' +
      MUREO.t("wizard.host.claude_desktop") + "</label>" +
      "</div>";
    wrap.querySelectorAll('input[name="host"]').forEach(function (input) {
      input.checked = input.value === STATE.host;
      input.addEventListener("change", function () {
        STATE.host = input.value;
        MUREO.postJson("/api/host", { host: input.value }).catch(function () {});
        updateNextEnabled();
      });
    });
    return wrap;
  }

  function buildStepBody_basic() {
    const wrap = document.createElement("div");
    const status = MUREO.state.status || {};
    const parts = status.setup_parts || {};
    function pill(installed, label) {
      const cls = installed ? "done" : "not-done";
      const mark = installed ? "✓" : "✗";
      return '<span class="wizard-step-pill ' + cls + '">' + mark + " " + label + "</span>";
    }
    // The credential-guard hook has no surface on Claude Desktop
    // (install_auth_hook returns noop:unsupported_on_desktop there), so
    // annotate the row when the chosen host is the Desktop app.
    let authHookLabel = MUREO.t("wizard.basic.auth_hook");
    if (STATE.host === "claude-desktop") {
      authHookLabel += " " + MUREO.t("wizard.basic.auth_hook_desktop_na");
    }
    wrap.innerHTML =
      '<h2>' + MUREO.t("wizard.basic.title") + "</h2>" +
      '<p>' + MUREO.t("wizard.basic.desc") + "</p>" +
      '<ul class="wizard-basic-parts">' +
      '<li>' + pill(parts.mureo_mcp, MUREO.t("wizard.basic.mureo_mcp")) + "</li>" +
      '<li>' + pill(parts.auth_hook, authHookLabel) + "</li>" +
      '<li>' + pill(parts.skills, MUREO.t("wizard.basic.skills")) + "</li>" +
      "</ul>" +
      '<button type="button" class="btn btn-primary" data-basic-install>' +
      MUREO.t("wizard.basic.install_button") + "</button>" +
      '<div class="wizard-advanced-skip">' +
      MUREO.t("wizard.basic.advanced_skip") +
      ' <a data-advanced-skip>' + MUREO.t("wizard.skip") + "</a></div>";

    wrap.querySelector("[data-basic-install]").addEventListener("click", async function () {
      const res = await MUREO.postJson("/api/setup/basic", {});
      if (res.ok) {
        STATE.basicInstallCompleted = true;
        await MUREO.loadStatus();
        render();
      } else {
        MUREO.toast("Setup failed");
      }
    });
    wrap.querySelector("[data-advanced-skip]").addEventListener("click", function () {
      STATE.basicInstallSkippedByAdvanced = true;
      MUREO.toast(MUREO.t("wizard.basic.advanced_skip_note"));
      updateNextEnabled();
    });
    return wrap;
  }

  function buildStepBody_platforms() {
    const wrap = document.createElement("div");
    wrap.innerHTML =
      '<h2>' + MUREO.t("wizard.platforms.title") + "</h2>" +
      '<p>' + MUREO.t("wizard.platforms.desc") + "</p>";
    PLATFORMS.forEach(function (p) {
      const label = document.createElement("label");
      label.style.display = "block";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = STATE.platforms[p];
      checkbox.addEventListener("change", function () {
        STATE.platforms[p] = checkbox.checked;
        updateNextEnabled();
      });
      label.appendChild(checkbox);
      label.appendChild(
        document.createTextNode(" " + MUREO.t("wizard.platforms." + p))
      );
      wrap.appendChild(label);
    });
    return wrap;
  }

  function buildChoiceCard(platform) {
    const wrap = document.createElement("fieldset");
    wrap.style.marginTop = "16px";
    const legend = document.createElement("legend");
    legend.textContent = MUREO.t("wizard.provider_banner." + platform);
    wrap.appendChild(legend);

    const officialKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads_official"
      : "wizard.provider_choice.meta_ads_official";
    const nativeKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads_native"
      : "wizard.provider_choice.meta_ads_native";
    // Optional benefit/desc lines — currently only Google Ads ships
    // them (per design doc §3 Step 4). MUREO.t falls back to the key
    // itself when missing, so we render only when the lookup actually
    // resolves to a different string.
    const officialDescKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads.official_desc"
      : null;
    const nativeBenefitKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads.mureo_benefit"
      : null;

    // Official first, mureo native second (design doc §1.4).
    [
      { value: "official", label: MUREO.t(officialKey), descKey: officialDescKey },
      { value: "native", label: MUREO.t(nativeKey), descKey: nativeBenefitKey },
    ].forEach(function (opt) {
      const label = document.createElement("label");
      label.style.display = "block";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "provider-" + platform;
      radio.value = opt.value;
      radio.checked = STATE.providerChoice[platform] === opt.value;
      radio.addEventListener("change", function () {
        STATE.providerChoice[platform] = radio.value;
        updateNextEnabled();
      });
      label.appendChild(radio);
      label.appendChild(document.createTextNode(" " + opt.label));
      // "Already configured" badge.
      const installedKey = platform + "-official";
      if (
        opt.value === "official" &&
        STATE.providerInstalled[installedKey]
      ) {
        const badge = document.createElement("span");
        badge.className = "wizard-choice-already-done";
        badge.textContent = "(" + MUREO.t("wizard.step_already_done") + ")";
        label.appendChild(badge);
      }
      wrap.appendChild(label);

      // Benefit/desc line — small muted text under the radio. Rendered
      // only when an i18n key was declared AND resolves to a string
      // different from the key (MUREO.t echoes the key on miss).
      if (opt.descKey) {
        const translated = MUREO.t(opt.descKey);
        if (translated && translated !== opt.descKey) {
          const desc = document.createElement("div");
          desc.className = "wizard-choice-desc";
          desc.textContent = translated;
          wrap.appendChild(desc);
        }
      }

      // hosted_http note — attached DIRECTLY under the OFFICIAL option
      // (never at the bottom of the card, where it read as if it
      // described the mureo-native option). Makes clear it's the
      // official/hosted choice that is set up later via Connectors.
      if (
        opt.value === "official" &&
        HOSTED_PLATFORMS.indexOf(platform) !== -1
      ) {
        const noteKey = "wizard.provider_choice.hosted_oauth_note";
        const noteText = MUREO.t(noteKey);
        if (noteText && noteText !== noteKey) {
          const note = document.createElement("div");
          note.className = "wizard-choice-desc";
          note.textContent = noteText;
          wrap.appendChild(note);
        }
      }
    });

    return wrap;
  }

  function buildStepBody_provider_choice() {
    const wrap = document.createElement("div");
    wrap.innerHTML = '<h2>' + MUREO.t("wizard.provider_choice.title") + "</h2>";
    if (STATE.platforms.google_ads) wrap.appendChild(buildChoiceCard("google_ads"));
    if (STATE.platforms.meta_ads) wrap.appendChild(buildChoiceCard("meta_ads"));
    return wrap;
  }

  function buildStepBody_providers_install() {
    const wrap = document.createElement("div");
    wrap.innerHTML = '<h2>' + MUREO.t("wizard.providers_install.title") + "</h2>";
    // Delegated to auth_wizards.js to render the per-provider queue.
    if (window.MUREO_AUTH && typeof window.MUREO_AUTH.renderProvidersInstall === "function") {
      window.MUREO_AUTH.renderProvidersInstall(wrap, STATE, render);
    }
    return wrap;
  }

  function buildStepBody_auth() {
    const wrap = document.createElement("div");
    if (window.MUREO_AUTH && typeof window.MUREO_AUTH.renderSequentialQueue === "function") {
      window.MUREO_AUTH.renderSequentialQueue(wrap, STATE, render);
    } else {
      wrap.innerHTML = "<p>Auth flow…</p>";
    }
    return wrap;
  }

  function buildStepBody_completed() {
    const wrap = document.createElement("div");
    // data-i18n on every text node so a language switch AFTER this
    // screen is rendered re-translates it (setLocale → applyTranslations
    // only re-resolves [data-i18n] nodes; build-time MUREO.t() alone
    // would freeze the completed screen in the build-time locale).
    wrap.innerHTML =
      '<h2 data-i18n="wizard.completed.title">' +
      MUREO.t("wizard.completed.title") +
      "</h2>" +
      '<p data-i18n="wizard.completed.desc">' +
      MUREO.t("wizard.completed.desc") +
      "</p>";
    // Official Meta still has a pending step on BOTH hosts after the
    // wizard: Meta's hosted MCP has no OAuth dynamic client
    // registration, so mureo never registers/authenticates it locally —
    // the user adds it as a Claude.ai account connector. Don't list
    // Meta as "saved"; surface an explicit, actionable reminder (the
    // pending_meta copy covers both hosts).
    const metaPending =
      STATE.platforms.meta_ads &&
      STATE.providerChoice.meta_ads === "official";

    const summary = document.createElement("ul");
    summary.className = "wizard-completed-summary";
    PLATFORMS.forEach(function (p) {
      if (!STATE.platforms[p]) return;
      if (p === "meta_ads" && metaPending) return;
      const li = document.createElement("li");
      li.textContent = MUREO.t("wizard.platforms." + p);
      li.setAttribute("data-i18n", "wizard.platforms." + p);
      summary.appendChild(li);
    });
    if (summary.children.length > 0) wrap.appendChild(summary);

    if (metaPending) {
      const reminder = document.createElement("div");
      reminder.className = "wizard-pending-reminder";
      const head = document.createElement("strong");
      head.textContent = MUREO.t("wizard.platforms.meta_ads");
      head.setAttribute("data-i18n", "wizard.platforms.meta_ads");
      const body = document.createElement("span");
      body.textContent = MUREO.t("wizard.completed.pending_meta");
      body.setAttribute("data-i18n", "wizard.completed.pending_meta");
      reminder.appendChild(head);
      reminder.appendChild(body);
      wrap.appendChild(reminder);
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.textContent = MUREO.t("wizard.completed.dashboard_button");
    btn.setAttribute("data-i18n", "wizard.completed.dashboard_button");
    btn.addEventListener("click", function () {
      MUREO.navigateToDashboard();
    });
    wrap.appendChild(btn);
    return wrap;
  }

  // ------------------------------------------------------------------
  // Renderer
  // ------------------------------------------------------------------
  const BUILDERS = {
    host: buildStepBody_host,
    basic: buildStepBody_basic,
    platforms: buildStepBody_platforms,
    provider_choice: buildStepBody_provider_choice,
    providers_install: buildStepBody_providers_install,
    auth: buildStepBody_auth,
    completed: buildStepBody_completed,
  };

  function showWizardSection() {
    const wizardEl = document.querySelector("[data-wizard]");
    if (wizardEl) wizardEl.hidden = false;
    const dashboardEl = document.querySelector("[data-dashboard]");
    if (dashboardEl) dashboardEl.hidden = true;
  }

  function render() {
    showWizardSection();
    const stepEl = document.querySelector("[data-wizard-step]");
    if (!stepEl) return;
    while (stepEl.firstChild) stepEl.removeChild(stepEl.firstChild);
    const step = currentStep();
    const builder = BUILDERS[step];
    if (builder) stepEl.appendChild(builder());
    updateNavVisibility();
    updateNextEnabled();
    updateProgress();
  }

  function updateNavVisibility() {
    const actions = document.querySelector("[data-wizard-actions]");
    if (!actions) return;
    const step = currentStep();
    const prevBtn = actions.querySelector('[data-wizard-action="prev"]');
    const nextBtn = actions.querySelector('[data-wizard-action="next"]');
    const skipBtn = actions.querySelector('[data-wizard-action="skip"]');
    // While the sub-wizard is active (`auth` step) it manages its own
    // controls and hands control back to the outer wizard on completion,
    // so the outer Back/Next/Skip must stay hidden to avoid duplicate
    // affordances. See design doc §1.3.
    const subWizardActive = step === "auth";
    if (prevBtn) prevBtn.hidden = STATE.stepIndex === 0 || subWizardActive;
    if (skipBtn) skipBtn.hidden = STEPS_WITHOUT_SKIP.has(step) || subWizardActive;
    if (nextBtn) nextBtn.hidden = step === "completed" || subWizardActive;
  }

  function updateNextEnabled() {
    const nextBtn = document.querySelector('[data-wizard-action="next"]');
    if (!nextBtn) return;
    nextBtn.disabled = !isNextEnabled();
  }

  function wireNav() {
    const actions = document.querySelector("[data-wizard-actions]");
    if (!actions) return;
    const prevBtn = actions.querySelector('[data-wizard-action="prev"]');
    const nextBtn = actions.querySelector('[data-wizard-action="next"]');
    const skipBtn = actions.querySelector('[data-wizard-action="skip"]');
    if (prevBtn) prevBtn.addEventListener("click", gotoPrev);
    if (nextBtn) nextBtn.addEventListener("click", gotoNext);
    if (skipBtn) skipBtn.addEventListener("click", gotoNext);
  }

  function onReady(evt) {
    const status = evt.detail && evt.detail.state ? evt.detail.state.status : null;
    hydrateStateFromStatus(status);
    wireNav();
    if (MUREO.isDashboardRoute()) {
      document.querySelector("[data-wizard]").hidden = true;
      return;
    }
  }

  document.addEventListener("mureo:ready", onReady);
  document.addEventListener("mureo:wizard_start", function () {
    STATE.stepIndex = 0;
    render();
  });
  document.addEventListener("mureo:locale_changed", function () {
    if (!document.querySelector("[data-wizard]").hidden) {
      render();
    }
  });
  document.addEventListener("mureo:route_changed", function (evt) {
    if (evt.detail && evt.detail.route === "wizard") {
      const wiz = document.querySelector("[data-wizard]");
      if (wiz && !wiz.hidden) render();
    }
  });

  window.MUREO_WIZARD = {
    state: STATE,
    effectiveSteps: effectiveSteps,
    isNextEnabled: isNextEnabled,
    render: render,
    gotoNext: gotoNext,
    gotoPrev: gotoPrev,
    hydrateStateFromStatus: hydrateStateFromStatus,
  };
})();
