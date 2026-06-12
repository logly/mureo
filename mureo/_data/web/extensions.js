// Renders third-party web extensions discovered by the configure
// server (see ``mureo.web.extensions``) as additional dashboard tabs.
//
// Each extension with a non-null ``view`` becomes:
//   * one ``<li><a data-dashboard-nav="ext-<name>">…</a></li>`` inserted
//     into the dashboard nav after the built-in tabs but BEFORE the
//     "About mureo" item, which always stays the last tab
//   * one ``<div class="dashboard-group" data-dashboard-group="ext-<name>"
//     hidden></div>`` appended to the dashboard pane, populated lazily
//     on first selection
//
// Lazy load: scripts / styles / html_fragment are injected the first
// time the user clicks the extension's tab. The CSP only permits
// ``script-src 'self'`` / ``style-src 'self'``; every asset URL is
// ``/static/ext/<name>/<filename>`` (same origin) so the loads pass.

(function () {
  "use strict";

  // Built-in dashboard tab keys an extension may hide via
  // ``hidden_builtin_tabs`` (#189). Mirrors BUILTIN_DASHBOARD_TABS in
  // ``mureo/web/extensions.py`` — the server already validates, but a
  // client-side allowlist keeps a malformed payload from hiding an
  // arbitrary node (e.g. another extension's tab).
  const BUILTIN_TABS = ["setup", "demo", "byod", "danger"];

  const _populated = new Set();
  // Every discovered extension (including headless / route-only ones —
  // they may still hide built-in tabs); ``_extensions`` keeps the
  // view-bearing subset that gets a nav tab rendered.
  let _allExtensions = [];
  let _extensions = [];
  // One-shot guard for the replaces_landing redirect — the jump to the
  // dashboard must happen on first load only, never again on later
  // init() calls (the operator may legitimately navigate back to the
  // wizard route afterwards).
  let _landingRedirected = false;
  // Single source of truth for "init() has already run". Set
  // synchronously at the top of init() so concurrent show() calls
  // collapse to one /api/extensions fetch even before the first
  // response resolves, and so the no-extensions case (_extensions
  // stays []) does not re-fetch on every dashboard open.
  // Exception paths intentionally leave this true: a failed discovery
  // requires a full page reload (not a silent retry) so the operator
  // can investigate the root cause via the console.warn diagnostics.
  let _initialised = false;

  function _currentLocale() {
    // ``document.documentElement.lang`` is the source of truth (set by
    // ``app.js#setLocale``). Falls back to "en" before app.js has run
    // and for the rare case where the attribute is removed.
    return document.documentElement.lang || "en";
  }

  function _resolveDisplayName(extension, locale) {
    // Lookup priority mirrors the convention documented in
    // ``docs/plugin-authoring.md`` §13: localized label for the active
    // locale, then the English entry as a portable default, then the
    // legacy ``display_name`` string. Extensions that do not ship a
    // ``display_name_i18n`` map keep the legacy behaviour exactly.
    const i18n = extension.display_name_i18n || {};
    return i18n[locale] || i18n.en || extension.display_name;
  }

  function _navList() {
    return document.querySelector(".dashboard-nav ul");
  }

  function _pane() {
    return document.querySelector(".dashboard-pane");
  }

  function _navItemId(name) {
    return "ext-" + name;
  }

  function _scriptId(name, filename) {
    return "ext-script-" + name + "-" + filename;
  }

  function _styleId(name, filename) {
    return "ext-style-" + name + "-" + filename;
  }

  function _injectStyles(name, filenames) {
    filenames.forEach(function (fn) {
      const id = _styleId(name, fn);
      if (document.getElementById(id)) return;
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/static/ext/" + name + "/" + fn;
      link.id = id;
      document.head.appendChild(link);
    });
  }

  function _injectScripts(name, filenames) {
    filenames.forEach(function (fn) {
      const id = _scriptId(name, fn);
      if (document.getElementById(id)) return;
      const script = document.createElement("script");
      script.src = "/static/ext/" + name + "/" + fn;
      script.id = id;
      script.defer = true;
      document.body.appendChild(script);
    });
  }

  function _populate(extension) {
    if (_populated.has(extension.name)) return;
    const group = document.querySelector(
      '[data-dashboard-group="' + _navItemId(extension.name) + '"]',
    );
    if (!group || !extension.view) return;
    // innerHTML is fine here: the server has already rejected
    // inline script / style / event handlers; the CSP refuses any
    // that slip through. The renderer's job is only to attach the
    // approved fragment to the DOM.
    group.innerHTML = extension.view.html_fragment;
    _injectStyles(extension.name, extension.view.styles || []);
    _injectScripts(extension.name, extension.view.scripts || []);
    _populated.add(extension.name);
  }

  function _onTabClick(extension) {
    return function (evt) {
      evt.preventDefault();
      _populate(extension);
      _selectGroup(_navItemId(extension.name));
    };
  }

  function _selectGroup(name) {
    // Mirror dashboard.js#selectNavGroup so extension tabs use the
    // same visibility + aria-current contract as the built-ins.
    const groups = document.querySelectorAll("[data-dashboard-group]");
    groups.forEach(function (g) {
      g.hidden = g.getAttribute("data-dashboard-group") !== name;
    });
    const items = document.querySelectorAll("[data-dashboard-nav]");
    items.forEach(function (item) {
      const active = item.getAttribute("data-dashboard-nav") === name;
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });
    const rerun = document.querySelector("[data-dashboard-rerun-wizard]");
    if (rerun) {
      rerun.style.display = name === "setup" ? "" : "none";
    }
  }

  function _renderNavItem(extension) {
    const nav = _navList();
    const pane = _pane();
    if (!nav || !pane) return;
    if (nav.querySelector('[data-dashboard-nav="' + _navItemId(extension.name) + '"]')) {
      return;
    }

    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = "#";
    a.className = "dashboard-nav-item";
    a.setAttribute("data-dashboard-nav", _navItemId(extension.name));
    a.setAttribute("role", "button");
    a.setAttribute("tabindex", "0");
    a.textContent = _resolveDisplayName(extension, _currentLocale());
    const onActivate = _onTabClick(extension);
    a.addEventListener("click", onActivate);
    a.addEventListener("keydown", function (evt) {
      if (evt.key === "Enter" || evt.key === " " || evt.key === "Spacebar") {
        onActivate(evt);
      }
    });
    li.appendChild(a);
    // Keep "About mureo" pinned as the last tab: extension tabs slot in
    // before it, however many plugins register one.
    const aboutAnchor = nav.querySelector('[data-dashboard-nav="about"]');
    const aboutItem = aboutAnchor ? aboutAnchor.closest("li") : null;
    if (aboutItem) {
      nav.insertBefore(li, aboutItem);
    } else {
      nav.appendChild(li);
    }

    const group = document.createElement("div");
    group.className = "dashboard-group";
    group.setAttribute("data-dashboard-group", _navItemId(extension.name));
    group.hidden = true;
    pane.appendChild(group);
  }

  function _hiddenTabKeys() {
    // Union of every installed extension's hidden_builtin_tabs,
    // filtered through the client-side allowlist. Includes headless
    // extensions: hiding a tab does not require shipping a view.
    const keys = new Set();
    _allExtensions.forEach(function (extension) {
      (extension.hidden_builtin_tabs || []).forEach(function (key) {
        if (BUILTIN_TABS.indexOf(key) !== -1) keys.add(key);
      });
    });
    return keys;
  }

  function _landingReplacer() {
    // The server guarantees at most one entry carries the flag
    // (first-discovered wins) and that it ships a view.
    return _extensions.find(function (e) {
      return e.replaces_landing === true;
    });
  }

  function _applyOverrides() {
    // #189 — hide built-in tabs superseded by full-surface plugins.
    // Runs on every init() call (dashboard.js re-selects the built-in
    // default on each show, so the override must be re-asserted).
    const hidden = _hiddenTabKeys();
    hidden.forEach(function (key) {
      const navItem = document.querySelector(
        '[data-dashboard-nav="' + key + '"]',
      );
      if (navItem && navItem.parentElement &&
          navItem.parentElement.tagName === "LI") {
        navItem.parentElement.hidden = true;
      }
      const group = document.querySelector(
        '[data-dashboard-group="' + key + '"]',
      );
      if (group) group.hidden = true;
    });

    const replacer = _landingReplacer();
    if (replacer) {
      const landing = document.querySelector("[data-landing]");
      if (landing) landing.hidden = true;
    }

    // Default-selection fallback: dashboard.js selects "setup" on every
    // show. If the selected tab is one we just hid, hand the selection
    // to the landing-owning extension (or the first extension tab) so
    // the operator never faces a pane with no corresponding nav item.
    const current = document.querySelector(
      '[data-dashboard-nav][aria-current="page"]',
    );
    const currentKey = current && current.getAttribute("data-dashboard-nav");
    if (currentKey && hidden.has(currentKey)) {
      const target = replacer || _extensions[0];
      if (target) {
        _populate(target);
        _selectGroup(_navItemId(target.name));
      } else {
        // Headless extension hid the default tab but shipped no view
        // of its own — fall back to the first still-visible built-in
        // tab so the pane is never orphaned. (All-hidden + no
        // extension view is a degenerate config; nothing to select.)
        const builtinFallback = BUILTIN_TABS.find(function (key) {
          return !hidden.has(key);
        });
        if (builtinFallback) _selectGroup(builtinFallback);
      }
    }

    // First-load handoff: when a plugin owns the landing and the page
    // opened on the wizard route, jump straight to the dashboard so
    // the plugin's view is what the operator lands on (#189). One-shot
    // — later navigation back to the wizard route is respected.
    if (
      replacer &&
      !_landingRedirected &&
      window.MUREO &&
      typeof MUREO.isDashboardRoute === "function" &&
      !MUREO.isDashboardRoute()
    ) {
      _landingRedirected = true;
      MUREO.navigateToDashboard();
    }
  }

  async function init() {
    if (!_initialised) {
      _initialised = true;
      await _fetchAndRender();
    }
    _applyOverrides();
  }

  async function _fetchAndRender() {
    let res;
    try {
      res = await fetch("/api/extensions");
    } catch (err) {
      console.warn("[mureo] /api/extensions fetch failed", err);
      return;
    }
    if (!res || !res.ok) {
      console.warn(
        "[mureo] /api/extensions returned non-OK",
        res && res.status,
      );
      return;
    }
    let payload;
    try {
      payload = await res.json();
    } catch (err) {
      console.warn("[mureo] /api/extensions returned invalid JSON", err);
      return;
    }
    if (!Array.isArray(payload)) {
      console.warn(
        "[mureo] /api/extensions returned non-array payload",
        payload,
      );
      return;
    }
    _allExtensions = payload.filter(Boolean);
    _extensions = _allExtensions.filter(function (item) {
      return item.view; // tabs are only rendered for view-bearing extensions
    });
    _extensions.forEach(_renderNavItem);
  }

  function _onLocaleChanged(evt) {
    // Walk every nav <a> we previously rendered and update its label
    // for the new locale. Resolved via _resolveDisplayName so the
    // fallback chain (locale → en → display_name) stays consistent
    // with the initial render path.
    const locale = (evt && evt.detail && evt.detail.locale) || _currentLocale();
    _extensions.forEach(function (extension) {
      const a = document.querySelector(
        '[data-dashboard-nav="' + _navItemId(extension.name) + '"]',
      );
      if (a) {
        a.textContent = _resolveDisplayName(extension, locale);
      }
    });
  }

  // Registered at module-eval time so a locale change that happens
  // before ``init()`` finishes still triggers a re-render on the next
  // matching event — ``_extensions`` is simply empty until init()
  // populates it, so the listener is harmless until then.
  document.addEventListener("mureo:locale_changed", _onLocaleChanged);

  // #189 — run discovery at app boot, not only on first dashboard
  // show. Without this, replaces_landing could never take effect on
  // first load: the landing route never calls dashboard.js#show(), so
  // init() would never fetch and the built-in landing would win.
  // init() is idempotent (one fetch per page load) so the later call
  // from dashboard.js#show() stays cheap.
  document.addEventListener("mureo:ready", function () {
    init();
  });

  window.MUREO = window.MUREO || {};
  window.MUREO.extensions = {
    init: init,
  };
})();
