// app.js — mureo configure UI bootstrapper.
// Boots the i18n catalog + CSRF token + dispatches a single
// `mureo:ready` event that the per-section scripts (landing.js,
// wizard.js, dashboard.js) listen for.

(function () {
  "use strict";

  const STATE = {
    locale: "en",
    csrfToken: "",
    catalog: { en: {}, ja: {} },
    status: null,
  };

  function format(template, params) {
    if (!template || !params) return template || "";
    return template.replace(/\{(\w+)\}/g, function (_, key) {
      return key in params ? params[key] : "{" + key + "}";
    });
  }

  function t(key, params) {
    const translations = STATE.catalog[STATE.locale] || {};
    const fallback = STATE.catalog.en || {};
    const template = translations[key] != null ? translations[key] : fallback[key];
    return format(template != null ? template : key, params);
  }

  function applyTranslations(root) {
    const target = root || document;
    const nodes = target.querySelectorAll("[data-i18n]");
    nodes.forEach(function (node) {
      const key = node.getAttribute("data-i18n");
      const translated = t(key);
      if (translated && translated !== key) {
        node.textContent = translated;
      }
    });
  }

  var LOCALE_KEY = "mureo.locale";

  // A toggle click: the page switches at once, then the backend session
  // and the status snapshot follow before listeners re-render.
  function setLocale(locale) {
    if (locale !== "en" && locale !== "ja") return;
    applyLocale(locale);
    // The status snapshot carries names the server resolves in the session
    // locale (a plugin provider's `plugin_platforms` entry), so listeners
    // re-render only once the backend has the new locale and the snapshot
    // has been re-read. Both requests are best-effort: the event fires even
    // when either fails, so the page still re-renders.
    postLocale(locale)
      .catch(function () {})
      .then(loadStatus)
      .catch(function () {})
      .then(function () {
        document.dispatchEvent(
          new CustomEvent("mureo:locale_changed", { detail: { locale: locale } })
        );
      });
  }

  // The synchronous half of a locale switch: state, storage and the DOM.
  function applyLocale(locale) {
    STATE.locale = locale;
    // Persist so the choice survives a page reload — notably the
    // OAuth round-trip (Google/Meta consent navigates away and the
    // configure page reloads on return). Without this, boot() forced
    // "en" and the completion screen rendered in English even when
    // the user had selected Japanese. Best-effort: ignore storage
    // errors (private mode / disabled storage).
    try {
      window.localStorage.setItem(LOCALE_KEY, locale);
    } catch (_e) {
      /* storage unavailable — fall back to in-memory only */
    }
    applyTranslations(document);
    document.documentElement.lang = locale;
    document
      .querySelectorAll("[data-lang-toggle]")
      .forEach(function (btn) {
        btn.setAttribute(
          "aria-pressed",
          btn.getAttribute("data-lang-toggle") === locale ? "true" : "false"
        );
      });
  }

  // The persisted language (survives the OAuth reload); "en" when unset
  // or storage is unavailable.
  function readSavedLocale() {
    try {
      var stored = window.localStorage.getItem(LOCALE_KEY);
      if (stored === "en" || stored === "ja") return stored;
    } catch (_e) {
      /* storage unavailable — default en */
    }
    return "en";
  }

  function postLocale(locale) {
    return fetch("/api/locale", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": STATE.csrfToken,
      },
      body: JSON.stringify({ locale: locale }),
    });
  }

  async function loadI18n() {
    try {
      const res = await fetch("/static/i18n.json");
      const data = await res.json();
      STATE.catalog = data;
    } catch (err) {
      console.error("i18n load failed", err);
    }
  }

  async function loadCsrf() {
    try {
      const res = await fetch("/api/csrf");
      const data = await res.json();
      STATE.csrfToken = data.csrf_token || "";
    } catch (err) {
      console.error("csrf load failed", err);
    }
  }

  async function loadStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      STATE.status = data;
      return data;
    } catch (err) {
      console.error("status load failed", err);
      return null;
    }
  }

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": STATE.csrfToken,
      },
      body: JSON.stringify(payload || {}),
    });
    const body = await res.json().catch(function () {
      return null;
    });
    return { ok: res.ok, status: res.status, body: body };
  }

  // #864: the one reading of a postJson result. The configure API answers a
  // refused or failed request with an HTTP error and ``{"error": <code>,
  // "detail"?}``; a success is 2xx with the route's own body. ``ok`` is true
  // only for a 2xx JSON object — the caller then compares ``body.status``
  // against the statuses it handles. Otherwise ``code`` is ``body.error``,
  // then ``body.detail``, else null (no response, or not JSON).
  function postOutcome(res) {
    const body = res && res.body && typeof res.body === "object" ? res.body : null;
    if (res && res.ok && body) return { ok: true, code: null, body: body };
    return { ok: false, code: (body && (body.error || body.detail)) || null, body: body };
  }

  // #891: the multi-step routes (basic setup, clear-all) answer with one
  // entry per step — the 200 body, or ``steps`` of the 500 they send when
  // every step failed. An entry with a ``status`` is a step; an object
  // without one (``providers``) holds one step per key. A basic step is
  // named by its wizard label, a provider by its id; a code with no message
  // here is shown as the code.
  const STEP_NAME_KEYS = {
    mureo_mcp: "wizard.basic.mureo_mcp",
    auth_hook: "wizard.basic.auth_hook",
    skills: "wizard.basic.skills",
  };
  const STEP_ERROR_KEYS = {
    internal_error: "app.step_err_internal_error",
    unknown_provider: "app.step_err_unknown_provider",
  };

  // The failed steps of ``steps``, as ``[{step, code}]``.
  function stepFailures(steps) {
    const isObject = function (value) {
      return Boolean(value) && typeof value === "object" && !Array.isArray(value);
    };
    if (!isObject(steps)) return [];
    const failures = [];
    const read = function (name, entry) {
      if (isObject(entry) && entry.status === "error") {
        failures.push({ step: name, code: entry.error || null });
      }
    };
    Object.keys(steps).forEach(function (name) {
      const entry = steps[name];
      if (!isObject(entry) || "status" in entry) return read(name, entry);
      Object.keys(entry).forEach(function (inner) {
        read(inner, entry[inner]);
      });
    });
    return failures;
  }

  // One failed step as "<step>: <message>", or "<step>" when it has no code.
  function stepFailureText(failure) {
    const nameKey = STEP_NAME_KEYS[failure.step];
    const name = nameKey ? t(nameKey) : failure.step;
    if (!failure.code) return name;
    const codeKey = STEP_ERROR_KEYS[failure.code];
    return name + ": " + (codeKey ? t(codeKey) : failure.code);
  }

  function toast(message, kind) {
    // ``kind`` is optional and accepts ``"info"`` (default), ``"success"``,
    // or ``"error"`` — translated to a ``is-<kind>`` CSS class so app.css
    // can color-code the pill. Existing single-arg callers stay valid;
    // the absence of ``is-error`` / ``is-success`` falls through to the
    // default dark-pill style. See issue #184.
    const node = document.querySelector("[data-toast]");
    if (!node) return;
    node.textContent = message;
    node.classList.remove("is-info", "is-success", "is-error");
    const safeKind =
      kind === "success" || kind === "error" || kind === "info" ? kind : "info";
    node.classList.add("is-" + safeKind);
    node.hidden = false;
    setTimeout(function () {
      node.hidden = true;
    }, 3500);
  }

  function confirmAction(message) {
    return new Promise(function (resolve) {
      const dialog = document.querySelector("[data-confirm-dialog]");
      if (!dialog || typeof dialog.showModal !== "function") {
        resolve(window.confirm(message));
        return;
      }
      const textNode = dialog.querySelector("[data-confirm-text]");
      if (textNode) textNode.textContent = message;
      const okBtn = dialog.querySelector("[data-confirm-ok]");
      const cancelBtn = dialog.querySelector("[data-confirm-cancel]");
      const handleOk = function () {
        cleanup();
        resolve(true);
      };
      const handleCancel = function () {
        cleanup();
        resolve(false);
      };
      const cleanup = function () {
        dialog.close();
        okBtn.removeEventListener("click", handleOk);
        cancelBtn.removeEventListener("click", handleCancel);
      };
      okBtn.addEventListener("click", handleOk);
      cancelBtn.addEventListener("click", handleCancel);
      dialog.showModal();
    });
  }

  function wireLangToggles() {
    document
      .querySelectorAll("[data-lang-toggle]")
      .forEach(function (btn) {
        btn.addEventListener("click", function () {
          setLocale(btn.getAttribute("data-lang-toggle"));
        });
      });
  }

  function wireDashboardLink() {
    const link = document.querySelector("[data-nav-dashboard]");
    if (link) {
      link.addEventListener("click", function () {
        navigateToDashboard();
      });
    }
  }

  function navigateToDashboard() {
    location.hash = "#dashboard";
  }

  function navigateToWizard() {
    location.hash = "";
  }

  function isDashboardRoute() {
    return location.hash === "#dashboard";
  }

  function setBaseRoute() {
    document.dispatchEvent(
      new CustomEvent("mureo:route_changed", {
        detail: { route: isDashboardRoute() ? "dashboard" : "wizard" },
      })
    );
  }

  async function boot() {
    await Promise.all([loadI18n(), loadCsrf()]);
    // The backend session gets the saved locale before the first status
    // load, so the snapshot's server-resolved names already match the page.
    // No mureo:locale_changed at boot: mureo:ready carries the first render.
    var savedLocale = readSavedLocale();
    await postLocale(savedLocale).catch(function () {});
    await loadStatus();
    wireLangToggles();
    wireDashboardLink();
    applyLocale(savedLocale);
    document.dispatchEvent(
      new CustomEvent("mureo:ready", { detail: { state: STATE } })
    );
    setBaseRoute();
  }

  window.addEventListener("hashchange", setBaseRoute);

  window.MUREO = {
    state: STATE,
    t: t,
    applyTranslations: applyTranslations,
    setLocale: setLocale,
    postJson: postJson,
    postOutcome: postOutcome,
    stepFailures: stepFailures,
    stepFailureText: stepFailureText,
    loadStatus: loadStatus,
    toast: toast,
    confirmAction: confirmAction,
    navigateToDashboard: navigateToDashboard,
    navigateToWizard: navigateToWizard,
    isDashboardRoute: isDashboardRoute,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
