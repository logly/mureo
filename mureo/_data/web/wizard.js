// wizard.js — main configure-UI wizard state machine.
// Implements the step flow in ALL_STEPS with dynamic step
// counter + auto-skip based on platform / provider selection.

(function () {
  "use strict";

  const PLATFORMS = [
    "google_ads",
    "meta_ads",
    "search_console",
    "ga4",
    "tiktok_ads",
    "amazon_ads",
  ];

  // The user's explicit host choice is persisted client-side so it
  // survives a page reload AND a `mureo configure` server restart
  // (which resets the in-memory session host to the claude-code
  // default). It is the authoritative source for host-dependent
  // actions; the server session is reconciled FROM it.
  const HOST_KEY = "mureo.host";

  function readStoredHost() {
    try {
      const v = window.localStorage.getItem(HOST_KEY);
      return v === "claude-code" || v === "claude-desktop" || v === "codex"
        ? v
        : null;
    } catch (_e) {
      return null;
    }
  }

  // Push the host to the server, retrying once, and surfacing a toast
  // instead of silently swallowing a persistent failure (a silent
  // failure is exactly what routed a Desktop user down the Code path).
  function syncHostToServer(host, retried) {
    return MUREO.postJson("/api/host", { host: host }).catch(function () {
      if (!retried) return syncHostToServer(host, true);
      MUREO.toast(MUREO.t("wizard.host.sync_failed"));
    });
  }

  const STATE = {
    host: "claude-code",
    basicInstallCompleted: false,
    basicInstallSkippedByAdvanced: false,
    // #891: the steps the last basic install could not do ([{step, code}],
    // MUREO.stepFailures), listed under the install button until a run
    // succeeds.
    basicInstallFailures: [],
    platforms: {
      google_ads: false,
      meta_ads: false,
      search_console: false,
      ga4: false,
      tiktok_ads: false,
      amazon_ads: false,
    },
    providerChoice: {
      google_ads: null, // "official" | "native" | a plugin provider's name
      meta_ads: null,
      // "native" | a plugin provider's name; only asked when a plugin
      // provider serves Search Console.
      search_console: null,
    },
    providerInstalled: {
      "google-ads-official": false,
      "meta-ads-official": false,
      "ga4-official": false,
    },
    // Hydrated from /api/status `plugin_platforms`. Selection-independent,
    // so re-hydrating mid-run cannot change effectiveSteps(): the auth step
    // is queued on the choice, not on `configured`.
    pluginPlatforms: {},
    // Existing on-disk credentials state, hydrated from /api/status. The
    // auth queue uses these flags to skip OAuth slots whose tokens are
    // already saved (e.g. Search Console reuses Google Ads OAuth).
    existing: {
      google: { has_oauth: false },
      meta: { has_oauth: false },
      // Amazon has no OAuth handshake mureo can run — its credentials are
      // Login-with-Amazon material typed into a form — so its "already
      // configured?" probe is the backend's own usability verdict
      // (credentials_present.amazon_ads), not a token flag.
      amazon: { configured: false },
      // GA4's "configured?" probe is credentials_present.ga4, the same
      // backend verdict the dashboard uses (a complete (usable) ``ga4``
      // section: credential file path and project id both set).
      ga4: { configured: false },
    },
    // existing.ga4.configured is read ONCE per wizard run (see
    // probeGa4Section). It is disk-derived and changes mid-run (saving
    // the GA4 slot writes the section; finishInstall re-hydrates after
    // every install), while every other hasAuthQueued term is
    // selection-derived. Re-reading it would drop ``auth`` from
    // effectiveSteps() under a stale stepIndex. wizard_start re-probes
    // from the latest status snapshot and sets this again.
    ga4Probed: false,
    // Set when the operator presses "Re-authorize Google" on the auth step;
    // forces the Google OAuth slot back into the queue for this wizard run
    // only (never persisted).
    reauthorizeGoogle: false,
    stepIndex: 0,
  };

  // ``auth`` MUST precede ``providers_install``: the official upstream
  // MCPs read credentials ONLY from env vars resolved (at install time)
  // from ~/.mureo/credentials.json, so the Google OAuth slot
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

  // Steps where the shared footer Skip button is hidden. ``platforms``
  // is intentionally absent: its Next button is gated on at least one
  // platform being selected, so an operator who wants to defer platform
  // setup needs Skip to leave the step (Skip → gotoNext → with no
  // platforms selected the provider/auth steps drop out and the wizard
  // lands on ``completed``). ``host`` requires a host choice, ``basic``
  // has its own inline advanced-skip link, and ``completed`` is
  // terminal — all keep their no-skip status.
  const STEPS_WITHOUT_SKIP = new Set(["host", "basic", "completed"]);

  function hasGoogleOrMetaPlatform() {
    return STATE.platforms.google_ads || STATE.platforms.meta_ads;
  }

  // Search Console has no official MCP, so it only has a choice to make
  // when a plugin provider serves it.
  function scChoiceOffered() {
    return Boolean(STATE.platforms.search_console && STATE.pluginPlatforms.search_console);
  }

  function isPluginChoice(platform) {
    return window.MUREO_WIZARD_CHOICE.isPluginChoice(STATE, platform);
  }

  function hasOfficialProviderQueued() {
    return (
      (STATE.platforms.google_ads &&
        STATE.providerChoice.google_ads === "official") ||
      (STATE.platforms.meta_ads &&
        STATE.providerChoice.meta_ads === "official") ||
      STATE.platforms.ga4 ||
      // TikTok is official-only (no mureo-native tools), so selecting it
      // always queues the providers_install step (its hosted setup card).
      STATE.platforms.tiktok_ads
    );
  }

  function hasAuthQueued() {
    // INVARIANT: ``auth`` MUST stay ordered AFTER ``provider_choice`` in
    // ALL_STEPS. This predicate is true for google_ads regardless of
    // provider choice, so surfacing the auth step before the choice is
    // made would strand the user on an ambiguous slot.
    // Google Ads: BOTH native and official need the same credentials
    // (Google OAuth client + refresh token; the legacy Developer Token
    // is optional). The official upstream MCP can't see
    // credentials.json, so the auth step still runs to collect them —
    // they're injected as env at install time.
    // Meta: only the native path is queued here; official Meta is a
    // hosted MCP whose OAuth is the HTTP-transport handshake Claude
    // performs on first connect (handled on the providers_install page).
    // Amazon: mureo brokers the official Amazon MCP itself (no separate
    // provider install, no native↔official choice), so selecting it queues
    // exactly one thing — the credential slot that fills the ``amazon_ads``
    // section the bridge reads.
    // GA4: its slot is skipped when the store already holds the ``ga4``
    // section (a credential provider hook may have written it), for the
    // same reason the Google slot is skipped on a saved token.
    // A plugin provider's slot is queued on the choice alone; when its
    // section is already configured the slot is skipped inside the queue,
    // which keeps effectiveSteps() stable across a mid-run re-hydrate.
    return (
      STATE.platforms.google_ads ||
      (STATE.platforms.meta_ads &&
        (STATE.providerChoice.meta_ads === "native" || isPluginChoice("meta_ads"))) ||
      STATE.platforms.search_console ||
      (STATE.platforms.ga4 && !STATE.existing.ga4.configured) ||
      STATE.platforms.amazon_ads
    );
  }

  function isStepRelevant(step) {
    if (step === "provider_choice") return hasGoogleOrMetaPlatform() || scChoiceOffered();
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
      if (scChoiceOffered() && !STATE.providerChoice.search_console) return false;
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
    // #222: a multi-account backend never registers the bare `mureo` MCP
    // entry (per-client entries are the correct wiring), so it is not a
    // completion requirement there.
    const mcpOk = status.multi_account_auth || Boolean(parts.mureo_mcp);
    return Boolean(mcpOk && parts.auth_hook && parts.skills);
  }

  // The provider names are resolved by the server in the session locale, so
  // they are re-read from the latest snapshot on every run and after a
  // locale switch, not only on the first load. Each entry is copied, so the
  // wizard never shares an object with the snapshot.
  function hydratePluginPlatforms(status) {
    if (!status) return;
    const served = status.plugin_platforms || {};
    const copy = {};
    Object.keys(served).forEach(function (platform) {
      copy[platform] = Object.assign({}, served[platform]);
    });
    STATE.pluginPlatforms = copy;
  }

  function hydrateStateFromStatus(status) {
    if (!status) return;
    // An explicit, persisted user choice wins over the server-echoed
    // host: if the configure process restarted, status.host is the
    // claude-code default and must NOT clobber the real selection.
    const stored = readStoredHost();
    if (stored) {
      STATE.host = stored;
    } else if (status.host) {
      STATE.host = status.host;
    }
    if (deriveCompletion(status)) {
      STATE.basicInstallCompleted = true;
    }
    const installed = status.providers_installed || {};
    Object.keys(STATE.providerInstalled).forEach(function (key) {
      STATE.providerInstalled[key] = Boolean(installed[key]);
    });
    hydratePluginPlatforms(status);
    const oauth = status.credentials_oauth || {};
    STATE.existing.google.has_oauth = Boolean(oauth.google);
    STATE.existing.meta.has_oauth = Boolean(oauth.meta);
    const present = status.credentials_present || {};
    STATE.existing.amazon.configured = Boolean(present.amazon_ads);
    probeGa4Section(status);
  }

  // Snapshot "is the ga4 section on disk?" once per wizard run (see the
  // STATE.ga4Probed comment). A no-op until wizard_start clears the flag.
  function probeGa4Section(status) {
    if (STATE.ga4Probed || !status) return;
    const present = status.credentials_present || {};
    STATE.existing.ga4.configured = Boolean(present.ga4);
    STATE.ga4Probed = true;
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
      MUREO.t("wizard.host.claude_desktop") + "</label><br>" +
      '<label><input type="radio" name="host" value="codex">' +
      MUREO.t("wizard.host.codex") + "</label>" +
      "</div>";
    // Assert the current selection to the server on step entry too —
    // not only on a radio `change`. A resumed wizard / restarted
    // configure process can leave the desktop radio pre-checked (no
    // change event) while the server session is still the default.
    syncHostToServer(STATE.host);
    wrap.querySelectorAll('input[name="host"]').forEach(function (input) {
      input.checked = input.value === STATE.host;
      input.addEventListener("change", function () {
        STATE.host = input.value;
        try {
          window.localStorage.setItem(HOST_KEY, input.value);
        } catch (_e) {
          /* private-mode / disabled storage — server sync still runs */
        }
        syncHostToServer(input.value);
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
    // #222: a multi-account backend wires per-client `mureo-<slug>` entries
    // instead of the bare `mureo` MCP, so the registration pill must not
    // render (the backend skips the write too).
    const mcpRow = status.multi_account_auth
      ? ""
      : '<li>' + pill(parts.mureo_mcp, MUREO.t("wizard.basic.mureo_mcp")) + "</li>";
    wrap.innerHTML =
      '<h2>' + MUREO.t("wizard.basic.title") + "</h2>" +
      '<p>' + MUREO.t("wizard.basic.desc") + "</p>" +
      '<ul class="wizard-basic-parts">' +
      mcpRow +
      '<li>' + pill(parts.auth_hook, authHookLabel) + "</li>" +
      '<li>' + pill(parts.skills, MUREO.t("wizard.basic.skills")) + "</li>" +
      "</ul>" +
      '<button type="button" class="btn btn-primary" data-basic-install>' +
      MUREO.t("wizard.basic.install_button") + "</button>" +
      '<div class="wizard-advanced-skip">' +
      MUREO.t("wizard.basic.advanced_skip") +
      ' <a data-advanced-skip>' + MUREO.t("wizard.skip") + "</a></div>";

    const installBtn = wrap.querySelector("[data-basic-install]");
    installBtn.addEventListener("click", runBasicInstall);
    if (STATE.basicInstallFailures.length > 0) {
      wrap.insertBefore(buildBasicFailures(), installBtn.nextSibling);
    }
    wrap.querySelector("[data-advanced-skip]").addEventListener("click", function () {
      STATE.basicInstallSkippedByAdvanced = true;
      MUREO.toast(MUREO.t("wizard.basic.advanced_skip_note"));
      updateNextEnabled();
    });
    return wrap;
  }

  // #891: the route answers 200 with one entry per step, or 500 with the
  // same entries in ``steps`` when every step failed. Only a 200 with no
  // failed step completes the basic step. A run starts with no list, so a
  // failure that names no step never leaves the previous run's list up.
  async function runBasicInstall() {
    STATE.basicInstallFailures = [];
    let res;
    try {
      res = await MUREO.postJson("/api/setup/basic", {});
    } catch (_err) {
      MUREO.toast(MUREO.t("app.toast_setup_failed"), "error");
      render();
      return;
    }
    const outcome = MUREO.postOutcome(res);
    const steps = outcome.ok ? outcome.body : outcome.body && outcome.body.steps;
    const failures = MUREO.stepFailures(steps);
    if (outcome.ok && failures.length === 0) {
      STATE.basicInstallCompleted = true;
    } else if (failures.length > 0) {
      STATE.basicInstallFailures = failures;
      MUREO.toast(MUREO.t("wizard.basic.steps_failed"), "error");
    } else {
      MUREO.toast(MUREO.t("app.toast_setup_failed"), "error");
      render();
      return;
    }
    await MUREO.loadStatus();
    render();
  }

  function buildBasicFailures() {
    const list = document.createElement("ul");
    list.className = "wizard-basic-failures";
    list.setAttribute("role", "alert");
    list.setAttribute("data-basic-failures", "");
    STATE.basicInstallFailures.forEach(function (failure) {
      const item = document.createElement("li");
      item.textContent = MUREO.stepFailureText(failure);
      list.appendChild(item);
    });
    return list;
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

  function buildStepBody_provider_choice() {
    const wrap = document.createElement("div");
    wrap.innerHTML = '<h2>' + MUREO.t("wizard.provider_choice.title") + "</h2>";
    // The cards live in wizard_provider_choice.js (loaded first).
    const choice = window.MUREO_WIZARD_CHOICE;
    // The Search Console card's "mureo standard" wording depends on the
    // Google Ads choice, so a Google Ads change redraws the step when both
    // cards are shown.
    const onGoogleChoice = scChoiceOffered() ? render : updateNextEnabled;
    if (STATE.platforms.google_ads)
      wrap.appendChild(choice.buildChoiceCard("google_ads", STATE, onGoogleChoice));
    if (STATE.platforms.meta_ads)
      wrap.appendChild(choice.buildChoiceCard("meta_ads", STATE, updateNextEnabled));
    if (scChoiceOffered())
      wrap.appendChild(choice.buildChoiceCard("search_console", STATE, updateNextEnabled));
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

  // One saved-platform row. A platform connected through a plugin provider
  // names it after the platform; data-i18n sits on an inner span only, so a
  // re-translation cannot wipe the provider's name.
  function buildCompletedRow(p) {
    const li = document.createElement("li");
    const key = "wizard.platforms." + p;
    if (!isPluginChoice(p) || !STATE.pluginPlatforms[p]) {
      li.textContent = MUREO.t(key);
      li.setAttribute("data-i18n", key);
      return li;
    }
    const text = document.createElement("span");
    text.textContent = MUREO.t(key);
    text.setAttribute("data-i18n", key);
    li.appendChild(text);
    li.appendChild(document.createTextNode(" — " + STATE.pluginPlatforms[p].display_name));
    return li;
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
    // Codex has no claude.ai connector, so official Meta is never the
    // active path there (mureo-native Meta stays) — don't show the
    // Claude.ai-connector reminder; Meta surfaces as a normal saved row.
    const metaPending =
      STATE.host !== "codex" &&
      STATE.platforms.meta_ads &&
      STATE.providerChoice.meta_ads === "official";
    // TikTok's hosted MCP always needs a post-wizard step (browser OAuth
    // via `claude mcp add` on Code / a connector on Desktop), so it is
    // surfaced as a pending reminder rather than a "saved" summary row.
    // Not applicable on Codex, where it is not wired.
    const tiktokPending = STATE.host !== "codex" && STATE.platforms.tiktok_ads;
    // Amazon's tools come from a locally generated manifest, so saved
    // credentials alone do not yet expose a single tool. That is a real
    // remaining step on every host — surfaced as a reminder rather than a
    // "saved" row that would overstate what is working.
    const amazonPending = STATE.platforms.amazon_ads;

    const summary = document.createElement("ul");
    summary.className = "wizard-completed-summary";
    PLATFORMS.forEach(function (p) {
      if (!STATE.platforms[p]) return;
      if (p === "meta_ads" && metaPending) return;
      // TikTok is never a "saved" row: pending (Code/Desktop) → shown as a
      // reminder below; on Codex it is omitted (not available there).
      if (p === "tiktok_ads") return;
      if (p === "amazon_ads" && amazonPending) return;
      summary.appendChild(buildCompletedRow(p));
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
    if (tiktokPending) {
      const reminder = document.createElement("div");
      reminder.className = "wizard-pending-reminder";
      const head = document.createElement("strong");
      head.textContent = MUREO.t("wizard.platforms.tiktok_ads");
      head.setAttribute("data-i18n", "wizard.platforms.tiktok_ads");
      const body = document.createElement("span");
      body.textContent = MUREO.t("wizard.completed.pending_tiktok");
      body.setAttribute("data-i18n", "wizard.completed.pending_tiktok");
      reminder.appendChild(head);
      reminder.appendChild(body);
      wrap.appendChild(reminder);
    }
    if (amazonPending) {
      const reminder = document.createElement("div");
      reminder.className = "wizard-pending-reminder";
      const head = document.createElement("strong");
      head.textContent = MUREO.t("wizard.platforms.amazon_ads");
      head.setAttribute("data-i18n", "wizard.platforms.amazon_ads");
      const body = document.createElement("span");
      body.textContent = MUREO.t("wizard.completed.pending_amazon");
      body.setAttribute("data-i18n", "wizard.completed.pending_amazon");
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
    // affordances.
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
    // Reconcile a (possibly reset/stale) server session FROM the
    // persisted client choice up-front, so a host-dependent action
    // reached without revisiting the host step still uses the real
    // host. Confirm also sends host in its payload as a second guard.
    if (readStoredHost()) syncHostToServer(STATE.host);
    wireNav();
    if (MUREO.isDashboardRoute()) {
      document.querySelector("[data-wizard]").hidden = true;
      return;
    }
  }

  document.addEventListener("mureo:ready", onReady);
  document.addEventListener("mureo:wizard_start", function () {
    STATE.stepIndex = 0;
    // A new run re-reads whether the store holds the ga4 section, from
    // the latest status snapshot right here: the landing Start button and
    // the dashboard re-run button dispatch this event without loading
    // status, so the next hydrate would otherwise be finishInstall's,
    // mid-run (MUREO.state.status is null only before the first load; the
    // flag then stays clear and that first hydrate takes the snapshot).
    STATE.ga4Probed = false;
    probeGa4Section(MUREO.state && MUREO.state.status);
    hydratePluginPlatforms(MUREO.state && MUREO.state.status);
    render();
  });
  document.addEventListener("mureo:locale_changed", function () {
    hydratePluginPlatforms(MUREO.state && MUREO.state.status);
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
    isPluginChoice: isPluginChoice,
    render: render,
    gotoNext: gotoNext,
    gotoPrev: gotoPrev,
    hydrateStateFromStatus: hydrateStateFromStatus,
  };
})();
