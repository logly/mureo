// amazon_oauth.js — Amazon Ads paste-code authorization controls (#121).
//
// Amazon's Login-with-Amazon consent for direct advertisers has no
// loopback callback: consent redirects to a URL listed in the operator's
// own LwA security profile (default https://amazon.com) and the
// authorization code is only visible in the browser's address bar. So
// this is a GUIDED PASTE flow, not the one-click loopback flow the
// Google / Meta cards use — the button opens Amazon's consent page, the
// operator pastes the redirected address back, and the server exchanges
// it for tokens.
//
// Both surfaces render the same controls (the dashboard's Amazon card
// and the setup wizard's Amazon step), so the DOM + fetch logic lives
// here once and is reached through window.MUREO_AMAZON_OAUTH. This file
// must load before dashboard.js and auth_wizards.js.
//
// No credential material is ever placed in the DOM: the requests carry
// only the pasted code, and the responses carry only a region, a machine
// error code, and a scrubbed detail. Every dynamic string is written
// with textContent.

(function () {
  "use strict";

  const AUTHORIZE_URL_ENDPOINT = "/api/amazon/oauth/authorize-url";
  const EXCHANGE_ENDPOINT = "/api/amazon/oauth/exchange";

  // Server error code → i18n key. "Not configured yet" and "that code is
  // dead" stay distinct, actionable outcomes rather than collapsing into
  // the generic failure.
  const AUTHORIZE_ERROR_KEYS = {
    amazon_client_id_missing: "dashboard.amazon_authorize_no_credentials",
    invalid_redirect_uri: "dashboard.amazon_exchange_invalid_redirect",
  };
  const EXCHANGE_ERROR_KEYS = {
    amazon_client_credentials_missing: "dashboard.amazon_exchange_no_credentials",
    authorization_code_required: "dashboard.amazon_exchange_code_required",
    authorization_code_invalid: "dashboard.amazon_exchange_code_expired",
    invalid_redirect_uri: "dashboard.amazon_exchange_invalid_redirect",
  };

  function errorKey(table, res, fallbackKey) {
    const err = res && res.body ? res.body.error : null;
    return (err && table[err]) || fallbackKey;
  }

  async function postSafe(url, payload) {
    try {
      return await MUREO.postJson(url, payload);
    } catch (_e) {
      return null;
    }
  }

  function labelledText(tag, className, key) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = MUREO.t(key);
    node.setAttribute("data-i18n", key);
    return node;
  }

  // Step 1 — ask the server for the consent URL (built from the SAVED
  // client id; nothing about the credentials is typed here) and open it.
  async function openConsent(btn, status) {
    btn.disabled = true;
    const res = await postSafe(AUTHORIZE_URL_ENDPOINT, {});
    btn.disabled = false;
    if (res && res.ok && res.body && res.body.authorize_url) {
      window.open(res.body.authorize_url, "_blank", "noopener,noreferrer");
      status.textContent = MUREO.t("dashboard.amazon_authorize_opening");
      return;
    }
    const key = errorKey(
      AUTHORIZE_ERROR_KEYS,
      res,
      "dashboard.amazon_authorize_failed"
    );
    status.textContent = MUREO.t(key);
    MUREO.toast(MUREO.t(key), "error");
  }

  // Step 2 — hand the pasted address (or bare code) to the server, which
  // exchanges it, stores the tokens, and rebuilds the tool manifest.
  async function submitCode(input, btn, status) {
    const pasted = (input.value || "").trim();
    if (!pasted) {
      status.textContent = MUREO.t("dashboard.amazon_exchange_code_required");
      return;
    }
    btn.disabled = true;
    status.textContent = MUREO.t("dashboard.amazon_exchange_running");
    const res = await postSafe(EXCHANGE_ENDPOINT, { code_or_url: pasted });
    btn.disabled = false;
    if (res && res.ok && res.body && res.body.status === "ok") {
      // The code is single-use — clear it so a retry cannot resend a
      // value Amazon has already burned.
      input.value = "";
      reportSuccess(res.body, status);
      return;
    }
    const key = errorKey(
      EXCHANGE_ERROR_KEYS,
      res,
      "dashboard.amazon_exchange_failed"
    );
    status.textContent = MUREO.t(key);
    MUREO.toast(MUREO.t(key), "error");
  }

  // A manifest failure does not undo the authorization: say so plainly
  // and point at the card's own retry button.
  function reportSuccess(body, status) {
    const ok = body.manifest === "ok";
    const msg = ok
      ? MUREO.t("dashboard.amazon_exchange_done", { count: body.tool_count })
      : MUREO.t("dashboard.amazon_exchange_done_manifest_failed");
    status.textContent = msg;
    MUREO.toast(msg, ok ? "success" : "info");
    if (MUREO.loadStatus) MUREO.loadStatus();
  }

  // The whole authorize → paste → exchange block, ready to append.
  function buildAuthorizeSection() {
    const box = document.createElement("div");
    box.className = "plugin-amazon-authorize";
    box.appendChild(
      labelledText("strong", null, "dashboard.amazon_authorize_title")
    );
    box.appendChild(
      labelledText("small", "field-hint", "dashboard.amazon_authorize_hint")
    );

    const authorizeBtn = labelledText(
      "button",
      "btn btn-secondary",
      "dashboard.amazon_authorize_button"
    );
    authorizeBtn.type = "button";
    box.appendChild(authorizeBtn);

    const label = document.createElement("label");
    label.appendChild(
      labelledText("span", null, "dashboard.amazon_exchange_label")
    );
    const input = document.createElement("input");
    input.type = "text";
    input.autocomplete = "off";
    input.placeholder = MUREO.t("dashboard.amazon_exchange_placeholder");
    label.appendChild(input);
    box.appendChild(label);

    const exchangeBtn = labelledText(
      "button",
      "btn btn-primary",
      "dashboard.amazon_exchange_button"
    );
    exchangeBtn.type = "button";
    box.appendChild(exchangeBtn);

    const status = document.createElement("span");
    status.className = "plugin-amazon-authorize-status muted";
    box.appendChild(status);

    authorizeBtn.addEventListener("click", function () {
      openConsent(authorizeBtn, status);
    });
    exchangeBtn.addEventListener("click", function () {
      submitCode(input, exchangeBtn, status);
    });
    return box;
  }

  // Re-authorize nudge, driven by the status snapshot's amazon_token row.
  // Only an age mureo recorded itself can be warned about: Amazon expires
  // refresh tokens issued on/after 2026-07-30 a year after consent, while
  // older ones have no fixed expiry — so an unknown age says nothing.
  function buildExpiringHint(status) {
    const row = status && status.amazon_token ? status.amazon_token : null;
    if (!row || row.refresh_token_expiring !== true) return null;
    const note = document.createElement("small");
    note.className = "field-hint mark-no";
    note.textContent = MUREO.t("dashboard.amazon_refresh_token_expiring", {
      days: row.refresh_token_age_days,
    });
    return note;
  }

  window.MUREO_AMAZON_OAUTH = {
    buildAuthorizeSection: buildAuthorizeSection,
    buildExpiringHint: buildExpiringHint,
  };
})();
