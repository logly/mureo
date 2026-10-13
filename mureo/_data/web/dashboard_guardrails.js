// dashboard_guardrails.js — the Guardrails card: the account currency
// (#786) and every other `## Guardrails` rule (#843).
//
// The first control is a money control. The `currency` bullet in
// STRATEGY.md's `## Guardrails` tells the policy gate what unit the caps
// below it are written in, so that Meta's minor-unit `daily_budget` /
// `lifetime_budget` / `bid_amount` can be divided before the comparison.
// Getting it wrong is not cosmetic: on a EUR account with no code declared,
// `max_daily_budget_per_campaign: 250` caps the campaign at €2.50.
//
// Below it, a table of every other rule the server describes
// (`/api/strategy/guardrails`): a label and one-line description per rule,
// its current value in an input, and what STRATEGY.md says about it. Save
// sends only the rules the operator changed, so one edit writes one bullet;
// an emptied input is sent as a removal and never as `0`.
//
// Which is why this file renders from what the SERVER says the file
// contains rather than from anything it remembers, and re-renders after
// every save. The states an operator has to be able to tell apart are
// "nothing is declared" (shown in words, never as a blank cell) and
// "something is declared that mureo does not recognise" — a line that is
// in the document and being ignored, and the card says so.
//
// One workspace, one file. The card reads and writes the STRATEGY.md of
// the workspace the page is about and knows nothing about clients (#790):
// a backend with a client roster is served no card at all — the markup is
// cut server-side (`mureo/web/app_html.py`), because there the rules are
// per-client settings and this card would write the operator's own
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
  const GUARDRAILS_ENDPOINT = "/api/strategy/guardrails";
  // Meta's offset for a zero-decimal currency: its minor unit IS its
  // currency unit, so nothing is converted and the label says so.
  const WHOLE_UNITS = 1;
  // The currency has the select above; the table does not offer it twice.
  const OWN_CONTROL_KINDS = ["currency"];
  const NUMBER_KINDS = ["money", "percent", "integer_days"];
  const LIST_KINDS = ["string_set", "metric_set"];
  // Rules whose absence is not "no limit" but a documented default.
  const DEFAULTED_KINDS = ["integer_days", "metric_set"];
  // Refusals the card can name a reason for; anything else is generic.
  // Spelled out key by key so every string the card can show is greppable.
  const FIELD_ERRORS = {
    invalid_value: "dashboard.guardrails_error_invalid_value",
    out_of_range: "dashboard.guardrails_error_out_of_range",
  };

  function node(selector) {
    return document.querySelector(selector);
  }

  function setResult(text) {
    const result = node("[data-guardrails-result]");
    if (result) result.textContent = text || "";
  }

  function setFieldsResult(text) {
    const result = node("[data-guardrails-fields-result]");
    if (result) result.textContent = text || "";
  }

  function clearChildren(parent) {
    while (parent.firstChild) parent.removeChild(parent.firstChild);
  }

  function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
    return option;
  }

  function element(tag, attrs, text) {
    const el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      el.setAttribute(name, attrs[name]);
    });
    if (text != null) el.textContent = text;
    return el;
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
    clearChildren(select);
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

  async function renderCurrency() {
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

  // ----- the rules table ------------------------------------------------

  // The UI catalog first, so the names follow the language toggle; the
  // server's own label (resolved from the request) when the catalog has
  // none — app.js's t() hands the key back unchanged on a miss.
  function fieldText(field, part) {
    const key = "guardrails.field." + field.key + "." + part;
    const text = MUREO.t(key);
    return text !== key ? text : field[part] || key;
  }

  function unitText(unit) {
    if (unit === "currency") return MUREO.t("dashboard.guardrails_unit_currency");
    if (unit === "days") return MUREO.t("dashboard.guardrails_unit_days");
    return unit || "";
  }

  // What the input starts at. An unreadable line starts EMPTY: the state
  // column says it is being ignored, and leaving the input untouched
  // leaves the line alone.
  function initialValue(field) {
    if (field.value == null || !field.recognised) return "";
    if (field.kind === "bool") return field.value ? "true" : "false";
    if (Array.isArray(field.value)) return field.value.join(", ");
    return String(field.value);
  }

  function boolControl() {
    const select = element("select", {});
    addOption(select, "", MUREO.t("dashboard.guardrails_field_not_set_off"));
    addOption(select, "true", MUREO.t("dashboard.guardrails_bool_on"));
    addOption(select, "false", MUREO.t("dashboard.guardrails_bool_off"));
    return select;
  }

  function numberControl(field) {
    const input = element("input", {
      type: "number",
      step: field.kind === "integer_days" ? "1" : "any",
      inputmode: "decimal",
    });
    if (field.min != null) input.setAttribute("min", String(field.min));
    if (field.max != null) input.setAttribute("max", String(field.max));
    return input;
  }

  function textControl() {
    return element("input", {
      type: "text",
      autocomplete: "off",
      spellcheck: "false",
      placeholder: MUREO.t("dashboard.guardrails_list_placeholder"),
    });
  }

  function fieldControl(field) {
    let control;
    if (field.kind === "bool") control = boolControl();
    else if (NUMBER_KINDS.indexOf(field.kind) !== -1) control = numberControl(field);
    else control = textControl();
    const initial = initialValue(field);
    control.setAttribute("data-guardrails-field", field.key);
    control.setAttribute("data-guardrails-kind", field.kind);
    control.setAttribute("data-initial", initial);
    control.setAttribute("aria-label", fieldText(field, "label"));
    control.value = initial;
    return control;
  }

  function stateLabel(field) {
    if (field.raw == null) {
      if (field.kind === "bool") {
        return MUREO.t("dashboard.guardrails_field_not_set_off");
      }
      if (DEFAULTED_KINDS.indexOf(field.kind) !== -1) {
        return MUREO.t("dashboard.guardrails_field_not_set_default");
      }
      return MUREO.t("dashboard.guardrails_field_not_set");
    }
    return field.recognised
      ? MUREO.t("dashboard.guardrails_field_set", { raw: field.raw })
      : MUREO.t("dashboard.guardrails_field_ignored", { raw: field.raw });
  }

  function fieldRow(field) {
    const row = element("tr", { "data-guardrails-row": field.key });
    const name = element("td", { class: "dashboard-guardrails-name" });
    name.appendChild(
      element("strong", { "data-guardrails-label": "" }, fieldText(field, "label"))
    );
    name.appendChild(
      element(
        "small",
        { class: "field-hint", "data-guardrails-desc": "" },
        fieldText(field, "desc")
      )
    );
    const value = element("td", { class: "dashboard-guardrails-value" });
    value.appendChild(fieldControl(field));
    if (field.unit) {
      value.appendChild(
        element("span", { class: "dashboard-guardrails-unit" }, unitText(field.unit))
      );
    }
    let stateClass = "dashboard-guardrails-state";
    if (field.raw == null) stateClass += " is-unset";
    else if (!field.recognised) stateClass += " is-ignored";
    const state = element(
      "td",
      { class: stateClass, "data-guardrails-state": "" },
      stateLabel(field)
    );
    row.appendChild(name);
    row.appendChild(value);
    row.appendChild(state);
    return row;
  }

  function fillFields(body) {
    const rows = node("[data-guardrails-rows]");
    if (!rows) return;
    clearChildren(rows);
    (body.fields || []).forEach(function (field) {
      if (OWN_CONTROL_KINDS.indexOf(field.kind) !== -1) return;
      rows.appendChild(fieldRow(field));
    });
  }

  async function renderFields() {
    let body;
    try {
      body = await fetchJson(GUARDRAILS_ENDPOINT);
    } catch (_err) {
      body = null;
    }
    if (!body || body.status !== "ok") {
      setFieldsResult(MUREO.t("dashboard.guardrails_fields_load_failed"));
      return;
    }
    fillFields(body);
    setFieldsResult("");
  }

  async function renderGuardrails() {
    // Absent on a multi-client backend, which is served no card at all:
    // nothing to render, and no STRATEGY.md of anyone's to read.
    if (!node("[data-dashboard-guardrails]")) return;
    await Promise.all([renderCurrency(), renderFields()]);
  }

  // ----- saving the currency ---------------------------------------------

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
    // The currency side only: the rules table has its own Save, and
    // redrawing it here would throw away an edit not yet saved there.
    await renderCurrency();
    // After the re-render, so the confirmation is not wiped by the
    // unknown-code line this render clears.
    setResult(msg);
  }

  // ----- saving the rules -------------------------------------------------

  // Only what differs from what the server last said: one edit, one bullet.
  // A number input holding text the browser cannot parse reports an EMPTY
  // value; that is a typo to point at, not a request to remove the rule.
  function collectChanges() {
    const changes = { set: {}, clear: [], unreadable: null };
    const rows = node("[data-guardrails-rows]");
    if (!rows) return changes;
    rows.querySelectorAll("[data-guardrails-field]").forEach(function (control) {
      const key = control.getAttribute("data-guardrails-field");
      if (control.validity && control.validity.badInput) {
        changes.unreadable = changes.unreadable || key;
        return;
      }
      const value = String(control.value || "").trim();
      if (value === control.getAttribute("data-initial")) return;
      if (value === "") changes.clear.push(key);
      else changes.set[key] = value;
    });
    return changes;
  }

  function refusalMessage(data) {
    const key = data && data.field;
    if (!key || !Object.prototype.hasOwnProperty.call(FIELD_ERRORS, data.error)) {
      return MUREO.t("dashboard.guardrails_fields_save_failed");
    }
    const row = node('[data-guardrails-row="' + key + '"]');
    const label = row && row.querySelector("[data-guardrails-label]");
    return MUREO.t("dashboard.guardrails_fields_refused", {
      label: label ? label.textContent : key,
      reason: MUREO.t(FIELD_ERRORS[data.error]),
    });
  }

  async function postFields(button, changes) {
    button.disabled = true;
    try {
      return await MUREO.postJson(GUARDRAILS_ENDPOINT, changes);
    } catch (_err) {
      return null;
    } finally {
      button.disabled = false;
    }
  }

  async function saveFields(button) {
    const changes = collectChanges();
    if (changes.unreadable) {
      setFieldsResult(
        refusalMessage({ error: "invalid_value", field: changes.unreadable })
      );
      return;
    }
    const count = Object.keys(changes.set).length + changes.clear.length;
    if (count === 0) {
      setFieldsResult(MUREO.t("dashboard.guardrails_fields_unchanged"));
      return;
    }
    const res = await postFields(button, { set: changes.set, clear: changes.clear });
    const data = (res && res.body) || {};
    if (!res || !res.ok || data.status !== "ok") {
      // The typed values stay in place for the operator to correct.
      const msg = refusalMessage(data);
      setFieldsResult(msg);
      MUREO.toast(msg, "error");
      return;
    }
    // Drawn from the server's answer — the file as re-read after the write.
    fillFields(data);
    const msg = MUREO.t("dashboard.guardrails_fields_saved", { count: count });
    setFieldsResult(msg);
    MUREO.toast(msg, "success");
  }

  function wireGuardrails() {
    const save = node("[data-guardrails-save]");
    if (save) {
      save.addEventListener("click", function () {
        saveCurrency(save);
      });
    }
    const saveRules = node("[data-guardrails-fields-save]");
    if (saveRules) {
      saveRules.addEventListener("click", function () {
        saveFields(saveRules);
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
