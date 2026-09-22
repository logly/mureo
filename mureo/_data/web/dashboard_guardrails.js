// dashboard_guardrails.js — the Guardrails card: the account currency (#786).
//
// One control, and it is a money control. The `currency` bullet in
// STRATEGY.md's `## Guardrails` tells the policy gate what unit the caps
// below it are written in, so that Meta's minor-unit `daily_budget` /
// `lifetime_budget` / `bid_amount` can be divided before the comparison.
// Getting it wrong is not cosmetic: on a EUR account with no code declared,
// `max_daily_budget_per_campaign: 250` caps the campaign at €2.50.
//
// Which is why this file renders from what the SERVER says the file
// contains rather than from anything it remembers, and re-renders after
// every save. The two states an operator has to be able to tell apart are
// "nothing is declared" (the first option, which is a real and valid
// choice) and "something is declared that mureo does not recognise" — the
// second one is a line that is in the document and being ignored, and the
// result row says so rather than quietly showing the first option.
//
// One workspace, one file. The card reads and writes the STRATEGY.md of
// the workspace the page is about and knows nothing about clients (#790):
// a backend with a client roster is served no card at all — the markup is
// cut server-side (`mureo/web/app_html.py`), because there the currency is
// a per-client setting and this card would write the operator's own
// ambient workspace, which is no client's file. So the render and the wire
// below are guarded on the card being PRESENT: on a page served without
// it this module does nothing whatsoever — no fetch, no listener.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_GUARDRAILS`. Loads AFTER dashboard_workspace.js
// and BEFORE dashboard.js.

(function () {
  "use strict";

  const CURRENCY_ENDPOINT = "/api/strategy/currency";
  // Meta's offset for a zero-decimal currency: its minor unit IS its
  // currency unit, so nothing is converted and the label says so.
  const WHOLE_UNITS = 1;

  function node(selector) {
    return document.querySelector(selector);
  }

  function setResult(text) {
    const result = node("[data-guardrails-result]");
    if (result) result.textContent = text || "";
  }

  function clearOptions(select) {
    while (select.firstChild) select.removeChild(select.firstChild);
  }

  function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
    return option;
  }

  async function fetchJson(url) {
    const res = await fetch(url);
    return await res.json();
  }

  // ----- the currency select ------------------------------------------

  function optionLabel(option) {
    return option.minor_units === WHOLE_UNITS
      ? option.code + " " + MUREO.t("dashboard.guardrails_zero_decimal")
      : option.code;
  }

  function fillCurrencies(body) {
    const select = node("[data-guardrails-currency]");
    if (!select) return;
    clearOptions(select);
    addOption(select, "", MUREO.t("dashboard.guardrails_not_set"));
    (body.options || []).forEach(function (option) {
      addOption(select, option.code, optionLabel(option));
    });
    select.value = body.currency || "";
  }

  function showPath(body) {
    const hint = node("[data-guardrails-path]");
    if (!hint) return;
    hint.textContent = body.path
      ? MUREO.t("dashboard.guardrails_path", { path: body.path })
      : "";
  }

  async function renderGuardrails() {
    // Absent on a multi-client backend, which is served no card at all:
    // nothing to render, and no STRATEGY.md of anyone's to read.
    const select = node("[data-guardrails-currency]");
    if (!select) return;
    let body;
    try {
      body = await fetchJson(CURRENCY_ENDPOINT);
    } catch (_err) {
      body = null;
    }
    if (!body || body.status !== "ok") {
      setResult(MUREO.t("dashboard.guardrails_load_failed"));
      return;
    }
    fillCurrencies(body);
    showPath(body);
    // A declared code mureo cannot map has no divisor, so the gate drops it
    // and compares Meta's amounts as minor units. Say it plainly.
    setResult(
      body.raw_value && !body.currency
        ? MUREO.t("dashboard.guardrails_unknown_code", { code: body.raw_value })
        : ""
    );
  }

  // ----- saving ---------------------------------------------------------

  async function saveCurrency(button) {
    const select = node("[data-guardrails-currency]");
    if (!select) return;
    const code = select.value;
    // The request writes to a file; a second click must not race the first.
    button.disabled = true;
    let res;
    try {
      res = await MUREO.postJson(CURRENCY_ENDPOINT, { currency: code });
    } catch (_err) {
      res = null;
    } finally {
      button.disabled = false;
    }
    const data = (res && res.body) || {};
    if (!res || !res.ok || data.status !== "ok") {
      setResult(MUREO.t("dashboard.guardrails_save_failed"));
      MUREO.toast(MUREO.t("dashboard.guardrails_save_failed"), "error");
      return;
    }
    const msg = code
      ? MUREO.t("dashboard.guardrails_saved", { code: code })
      : MUREO.t("dashboard.guardrails_cleared");
    MUREO.toast(msg, "success");
    await renderGuardrails();
    // After the re-render, so the confirmation is not wiped by the
    // unknown-code line this render clears.
    setResult(msg);
  }

  function wireGuardrails() {
    const save = node("[data-guardrails-save]");
    if (save) {
      save.addEventListener("click", function () {
        saveCurrency(save);
      });
    }
  }

  const api = {
    renderGuardrails: renderGuardrails,
    wireGuardrails: wireGuardrails,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_GUARDRAILS = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
