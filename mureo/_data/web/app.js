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

  function setLocale(locale) {
    if (locale !== "en" && locale !== "ja") return;
    STATE.locale = locale;
    // Persist so the choice survives a page reload — notably the
    // OAuth round-trip (Google/Meta consent navigates away and the
    // configure page reloads on return). Without this, boot() forced
    // "en" and the completion screen rendered in English even when
    // the user had selected 日本語. Best-effort: ignore storage errors
    // (private mode / disabled storage).
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
    // Propagate to backend (best-effort).
    fetch("/api/locale", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": STATE.csrfToken,
      },
      body: JSON.stringify({ locale: locale }),
    }).catch(function () {});
    document.dispatchEvent(
      new CustomEvent("mureo:locale_changed", { detail: { locale: locale } })
    );
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

  function toast(message) {
    const node = document.querySelector("[data-toast]");
    if (!node) return;
    node.textContent = message;
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
    await loadStatus();
    wireLangToggles();
    wireDashboardLink();
    // Restore the persisted language (survives the OAuth reload);
    // default to "en" when unset or storage is unavailable.
    var savedLocale = "en";
    try {
      var stored = window.localStorage.getItem(LOCALE_KEY);
      if (stored === "en" || stored === "ja") savedLocale = stored;
    } catch (_e) {
      /* storage unavailable — default en */
    }
    setLocale(savedLocale);
    applyTranslations(document);
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
