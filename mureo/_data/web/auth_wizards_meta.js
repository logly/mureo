// auth_wizards_meta.js — the Meta-specific halves of the auth wizards.
// Split out of auth_wizards.js (house 800-line budget); pure move, no
// behavior change. Loaded BEFORE auth_wizards.js and consumed through
// window.MUREO_AUTH_META: the hosted-connector setup card, the
// connection-method chooser, and the system-user token card.

(function () {
  "use strict";

  // Meta's official hosted Ads MCP endpoint (matches catalog.py).
  const META_HOSTED_URL = "https://mcp.facebook.com/ads";

  // Server-side failure codes from /api/credentials/meta/token mapped to
  // mureo's own wording (#579). Graph answers an expired or revoked token
  // with an error 190 string carrying an fbtrace_id — the right thing to
  // keep for a support thread, the wrong thing to be the only sentence an
  // operator is shown. mureo names the platform, the cause and the single
  // recovery action; Graph's text stays underneath, secondary.
  const META_TOKEN_ERROR_KEYS = {
    token_invalid: "wizard.auth.meta_token_invalid",
    account_fetch_failed: "wizard.auth.meta_token_account_fetch_failed",
  };

  function metaTokenErrorKey(res) {
    const err = res && res.body ? res.body.error : null;
    return (err && META_TOKEN_ERROR_KEYS[err]) || "wizard.auth.oauth_failed";
  }

  // Render the manual Connectors setup as an actionable card:
  // numbered steps + a copy-to-clipboard URL. No own "Continue"
  // button — the outer wizard's Next advances this step. Always
  // returns true (the card has no missing-translation failure mode;
  // labels fall back via MUREO.t).
  function showManualSetup(wrap, state, providerId) {
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

    // Token entry — password-typed and opted out of autofill (a long-lived
    // secret must not be remembered by the browser).
    const tokenLabel = document.createElement("label");
    tokenLabel.style.display = "block";
    tokenLabel.textContent = MUREO.t("wizard.auth.meta_token_label");
    tokenLabel.setAttribute("data-i18n", "wizard.auth.meta_token_label");
    const tokenInput = document.createElement("input");
    tokenInput.type = "password";
    tokenInput.autocomplete = "new-password";
    tokenLabel.appendChild(tokenInput);
    details.appendChild(tokenLabel);

    // OPTIONAL app credentials (#726). A Business Manager system-user token
    // is minted with a 60-day life; with the app pair stored, mureo can
    // exchange it for a fresh one before it dies. Without them the card
    // still works exactly as before — the expiry is shown and warned about,
    // and renewing is a manual re-paste.
    const appIdLabel = document.createElement("label");
    appIdLabel.style.display = "block";
    appIdLabel.textContent = MUREO.t("wizard.auth.meta_token_app_id_label");
    appIdLabel.setAttribute("data-i18n", "wizard.auth.meta_token_app_id_label");
    const appIdInput = document.createElement("input");
    appIdInput.type = "text";
    appIdInput.autocomplete = "off";
    appIdLabel.appendChild(appIdInput);
    details.appendChild(appIdLabel);

    const appSecretLabel = document.createElement("label");
    appSecretLabel.style.display = "block";
    appSecretLabel.textContent = MUREO.t("wizard.auth.meta_token_app_secret_label");
    appSecretLabel.setAttribute(
      "data-i18n", "wizard.auth.meta_token_app_secret_label");
    const appSecretInput = document.createElement("input");
    appSecretInput.type = "password";
    appSecretInput.autocomplete = "new-password";
    appSecretLabel.appendChild(appSecretInput);
    details.appendChild(appSecretLabel);

    const appHint = document.createElement("small");
    appHint.className = "field-hint";
    appHint.textContent = MUREO.t("wizard.auth.meta_token_app_hint");
    appHint.setAttribute("data-i18n", "wizard.auth.meta_token_app_hint");
    details.appendChild(appHint);

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
    // When the token dies, straight from Graph's debug_token (#726).
    const expiryP = document.createElement("p");
    expiryP.className = "field-hint";
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
    results.appendChild(expiryP);
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

    // Graph's own error body, demoted to a second line: the status above
    // says what happened and what to do, this says what Meta replied.
    // Hidden until there is something to show, so a clean card carries no
    // empty row.
    const detail = document.createElement("small");
    detail.className = "field-hint";
    detail.hidden = true;
    details.appendChild(detail);

    function clearError() {
      status.textContent = "";
      detail.textContent = "";
      detail.hidden = true;
    }

    function reportError(res) {
      const msg = MUREO.t(metaTokenErrorKey(res));
      status.textContent = msg;
      const raw = (res && res.body && res.body.detail) || "";
      detail.textContent = raw;
      detail.hidden = !raw;
      MUREO.toast(msg, "error");
    }

    // Whole days from now to an ISO instant, or null when unparseable. The
    // server owns the WARNING threshold (the status snapshot decides that);
    // this is only the countdown shown next to the date it just echoed.
    function daysUntil(iso) {
      const at = Date.parse(iso);
      if (!isFinite(at)) return null;
      return Math.floor((at - Date.now()) / 86400000);
    }

    // #726: a system-user token issued with the 60-day expiry dies on a
    // date. Saying so at paste time is the whole point — an operator who
    // never learns the date finds out when a report fails.
    //
    // #740: and one issued without an expiry does not die at all. Meta
    // reports that explicitly, so the card states it instead of the
    // "no countdown" line, which read as a gap in what mureo knew.
    function renderExpiry(body) {
      if (body && body.token_never_expires === true) {
        expiryP.textContent = MUREO.t("wizard.auth.meta_token_never_expires");
        expiryP.setAttribute("data-i18n", "wizard.auth.meta_token_never_expires");
        return;
      }
      const iso = body && body.token_expires_at;
      const days = iso ? daysUntil(iso) : null;
      if (days === null) {
        expiryP.textContent = MUREO.t("wizard.auth.meta_token_expiry_unknown");
        expiryP.setAttribute("data-i18n", "wizard.auth.meta_token_expiry_unknown");
        return;
      }
      // Re-translating this line would drop the interpolated values, so it
      // carries no data-i18n key (the locale switcher re-renders the card).
      expiryP.removeAttribute("data-i18n");
      expiryP.textContent = MUREO.t("wizard.auth.meta_token_expires_at", {
        date: iso.slice(0, 10),
        days: days,
      });
    }

    // Machine codes from the save/validate response -> operator sentences.
    // token_expiry_unknown is deliberately absent: renderExpiry already
    // states it inline, and saying it twice reads as two problems.
    // token_expiry_untracked is here and token_inspect_failed stays: "mureo
    // did not ask" and "Meta refused" are different problems with different
    // fixes, and the second one used to answer for both (#740).
    const WARNING_KEYS = {
      token_expiry_untracked: "wizard.auth.meta_token_warn_expiry_untracked",
      token_inspect_failed: "wizard.auth.meta_token_warn_inspect_failed",
      auto_refresh_unavailable:
        "wizard.auth.meta_token_warn_auto_refresh_unavailable",
    };

    function renderWarnings(body) {
      const codes = (body && body.warnings) || [];
      const text = codes
        .map(function (code) {
          return WARNING_KEYS[code] ? MUREO.t(WARNING_KEYS[code]) : "";
        })
        .filter(Boolean)
        .join(" ");
      detail.textContent = text;
      detail.hidden = !text;
    }

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
      renderExpiry(body);
      renderWarnings(body);
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
      clearError();
      const res = await MUREO.postJson("/api/credentials/meta/token", {
        access_token: token,
        app_id: appIdInput.value.trim(),
        app_secret: appSecretInput.value.trim(),
        validate_only: true,
      });
      validateBtn.disabled = false;
      if (res.ok && res.body) {
        renderProbe(res.body);
      } else {
        reportError(res);
      }
    });

    saveBtn.addEventListener("click", async function () {
      const token = tokenInput.value.trim();
      if (!token) return;
      saveBtn.disabled = true;
      clearError();
      const res = await MUREO.postJson("/api/credentials/meta/token", {
        access_token: token,
        account_id: accountSelect.value || null,
        app_id: appIdInput.value.trim(),
        app_secret: appSecretInput.value.trim(),
      });
      if (res.ok && res.body && res.body.status === "ok") {
        const msg = MUREO.t("wizard.auth.meta_token_saved");
        status.textContent = msg;
        // The expiry and any warning survive the save, so the operator
        // leaves the card knowing the date rather than just "saved".
        renderExpiry(res.body);
        renderWarnings(res.body);
        MUREO.toast(msg, "success");
        onDone();
      } else {
        reportError(res);
        saveBtn.disabled = false;
      }
    });

    return details;
  }

  // Dashboard re-authentication for the native Meta credentials (#579).
  // A Meta token can expire, and Remove — throwing the credentials away —
  // used to be the only action on its row; the Amazon plugin card has had
  // an authorize section next to its own credentials since #121.
  //
  // The card is opened HERE rather than by sending the operator back to
  // the wizard: "mureo:wizard_start" resets the wizard to step 0, there is
  // no step-jump, and the Meta auth slot is gated on STATE.platforms /
  // STATE.providerChoice, which hydrateStateFromStatus never fills in. So
  // the only wizard route is re-running setup from the host step.
  //
  // Built lazily and toggled: the card carries a 4-step token guide, which
  // does not belong permanently inside a one-line credential row.
  function buildMetaReauthSection(onDone) {
    const box = document.createElement("div");
    box.className = "meta-reauth";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.meta_reauth_button");
    btn.setAttribute("data-i18n", "dashboard.meta_reauth_button");
    box.appendChild(btn);

    const slot = document.createElement("div");
    slot.hidden = true;
    box.appendChild(slot);

    btn.addEventListener("click", function () {
      if (!slot.firstChild) {
        const card = buildMetaTokenCard(onDone);
        // The <details> summary is de-emphasized chrome (see
        // buildMetaTokenCard); a card that opened collapsed would hide the
        // very form the button just promised.
        card.open = true;
        slot.appendChild(card);
      }
      slot.hidden = !slot.hidden;
    });
    return box;
  }

  // Re-authentication nudge, driven by the status snapshot's meta_token
  // row. Two independent signals, and the countdown wins when both fire —
  // "expires in 3 days" is the actionable fact, "the refresh has not run"
  // is the explanation:
  //
  // * #726 ``access_token_expiry_warning`` — Meta's own expiry for this
  //   token is inside the collector's threshold. Needs no app pair; a
  //   token already past its date gets the past-tense line, because
  //   "expires in -3 days" is not a countdown;
  // * #579 ``access_token_expiring`` — the token is older than the refresh
  //   threshold and mureo's exchange has not replaced it. Only a token
  //   stored WITH the app pair can be exchanged, so the collector reports
  //   False without one however old it is, and a token with no obtained-at
  //   stamp has an unknown age that says nothing.
  //
  // #740 ``access_token_never_expires`` outranks both: Meta itself said
  // this token has no end date, so there is nothing to count down and
  // nothing to re-authenticate for. The row states the fact and stops —
  // neutral, not a warning.
  function buildMetaExpiringHint(status) {
    const row = status && status.meta_token ? status.meta_token : null;
    if (!row) return null;
    const note = document.createElement("small");
    // meta-reauth-hint earns the note a full-width line inside the flex
    // credential row, the way dashboard-provider-hosted-note does.
    note.className = "field-hint mark-no meta-reauth-hint";
    if (row.access_token_never_expires === true) {
      note.textContent = MUREO.t("dashboard.meta_token_never_expires");
      note.setAttribute("data-i18n", "dashboard.meta_token_never_expires");
      return note;
    }
    if (row.access_token_expiry_warning === true) {
      const days = row.access_token_expires_in_days;
      const date = (row.access_token_expires_at || "").slice(0, 10);
      note.textContent =
        days < 0
          ? MUREO.t("dashboard.meta_token_expired", { date: date })
          : MUREO.t("dashboard.meta_token_expires_in", {
              days: days,
              date: date,
            });
      return note;
    }
    if (row.access_token_expiring !== true) return null;
    note.textContent = MUREO.t("dashboard.meta_access_token_expiring", {
      days: row.access_token_age_days,
    });
    return note;
  }

  window.MUREO_AUTH_META = {
    showManualSetup: showManualSetup,
    buildMetaMethodChooser: buildMetaMethodChooser,
    buildMetaTokenCard: buildMetaTokenCard,
    buildMetaReauthSection: buildMetaReauthSection,
    buildMetaExpiringHint: buildMetaExpiringHint,
  };
})();
