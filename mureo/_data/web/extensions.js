// Renders third-party web extensions discovered by the configure
// server (see ``mureo.web.extensions``) as additional dashboard tabs.
//
// Each extension with a non-null ``view`` becomes:
//   * one ``<li><a data-dashboard-nav="ext-<name>">…</a></li>`` appended
//     to the dashboard nav, sitting after the built-in tabs
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

  const _populated = new Set();
  let _extensions = [];
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
    nav.appendChild(li);

    const group = document.createElement("div");
    group.className = "dashboard-group";
    group.setAttribute("data-dashboard-group", _navItemId(extension.name));
    group.hidden = true;
    pane.appendChild(group);
  }

  async function init() {
    if (_initialised) return;
    _initialised = true;
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
    _extensions = payload.filter(function (item) {
      return item && item.view; // skip headless / route-only extensions
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

  window.MUREO = window.MUREO || {};
  window.MUREO.extensions = {
    init: init,
  };
})();
