// dashboard_workspace.js — the workspace's own data: demo, BYOD, native.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move.
//
// What these have in common is that they act on the workspace rather than on
// the install: seeding a demo scenario, importing a BYOD spreadsheet, picking
// a file or folder, clearing what was imported, and rendering the native
// per-platform sections that read from it. The Danger Zone's bulk clear lives
// here too — it is the same verb pointed at everything at once.
//
// `statusMark` is bound from dashboard_setup.js rather than re-implemented:
// the tick/cross a native section shows is the same one a basic-setup row
// shows, and two copies would be free to drift.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_WORKSPACE`. Loads AFTER dashboard_setup.js and
// BEFORE dashboard.js.

(function () {
  "use strict";

  // dashboard_setup.js's tick/cross mark, bound by its original name so
  // every call site below reads exactly as it did in dashboard.js. That
  // file's <script> tag comes first (see app.html), so this resolves at
  // load; the guard is the shape every module in this directory uses.
  const DASHBOARD_SETUP = window.MUREO_DASHBOARD_SETUP;
  if (!DASHBOARD_SETUP) {
    throw new Error(
      "dashboard_workspace.js needs MUREO_DASHBOARD_SETUP — load " +
        "dashboard_setup.js BEFORE dashboard_workspace.js"
    );
  }
  const statusMark = DASHBOARD_SETUP.statusMark;

  // dashboard.js owns the full-page repaint and, being the file that binds
  // every section module, loads AFTER this one. So the name is resolved when
  // a button is clicked rather than at load, which is what lets the call
  // sites below read exactly as they did when they lived in that file.
  function renderAll() {
    const api = typeof window !== "undefined" ? window.MUREO_DASHBOARD : null;
    if (!api) {
      throw new Error(
        "MUREO_DASHBOARD (dashboard.js) is missing — it must be served and " +
          "its <script> tag must come AFTER this file in app.html."
      );
    }
    return api.renderAll();
  }

  async function runBulkClear() {
    // Two-step confirmation. Either decline aborts.
    const ok1 = await MUREO.confirmAction(MUREO.t("dashboard.confirm_clear_all_1"));
    if (!ok1) return;
    const ok2 = await MUREO.confirmAction(MUREO.t("dashboard.confirm_clear_all_2"));
    if (!ok2) return;
    let res;
    try {
      // Send the client's known host so the server self-heals a stale/reset
      // session host (see handlers._resolve_host).
      res = await MUREO.postJson("/api/setup/basic/clear", {
        host: MUREO.state.status && MUREO.state.status.host,
      });
    } catch (_err) {
      MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
      return;
    }
    if (!res || !res.ok) {
      MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
      return;
    }
    await MUREO.loadStatus();
    renderAll();
    MUREO.toast(MUREO.t("dashboard.clear_all_success"), "success");
  }

  function wireBulkClearButton() {
    const btn = document.querySelector("[data-dashboard-clear-all]");
    if (!btn) return;
    btn.addEventListener("click", runBulkClear);
  }

  // ----- Demo section -------------------------------------------------

  async function loadDemoScenarios() {
    const select = document.querySelector("[data-demo-scenario]");
    if (!select) return;
    let body;
    try {
      const res = await fetch("/api/demo/scenarios");
      body = await res.json();
    } catch (_err) {
      return;
    }
    if (!body || body.status !== "ok" || !Array.isArray(body.scenarios)) {
      return;
    }
    while (select.firstChild) select.removeChild(select.firstChild);
    body.scenarios.forEach(function (sc) {
      const opt = document.createElement("option");
      opt.value = sc.name;
      // Prefer a localised title; MUREO.t returns the key verbatim when
      // missing, so an unknown scenario falls back to the API title.
      const titleKey = "demo.scenario." + sc.name;
      const localised = MUREO.t(titleKey);
      const title = localised === titleKey ? sc.title : localised;
      // Title only: sc.blurb is hardcoded English from the Python
      // scenario registry, so appending it would leave an English
      // tail on a Japanese option under locale=ja.
      opt.textContent = title;
      if (sc.default) opt.selected = true;
      select.appendChild(opt);
    });
  }

  function wireDemoCreate() {
    const btn = document.querySelector("[data-demo-create]");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const scenario = document.querySelector("[data-demo-scenario]");
      const targetNode = document.querySelector("[data-demo-target]");
      const resultNode = document.querySelector("[data-demo-result]");
      const target = targetNode ? targetNode.value.trim() : "";
      if (!target) {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.demo_target_required");
        }
        return;
      }
      if (resultNode) resultNode.textContent = MUREO.t("dashboard.demo_creating");
      let res;
      try {
        res = await MUREO.postJson("/api/demo/init", {
          scenario_name: scenario ? scenario.value : "",
          target: target,
          force: false,
          skip_import: false,
        });
      } catch (_err) {
        const msg = MUREO.t("dashboard.demo_failed", { detail: "network" });
        if (resultNode) resultNode.textContent = msg;
        // Inline result stays for scroll-anchored context; toast is the
        // scroll-resistant surface for operators scrolled to the bottom
        // of a long Dashboard (#184).
        MUREO.toast(msg, "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        const msg = MUREO.t("dashboard.demo_success", {
          path: data.created_path || target,
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "success");
      } else {
        const msg = MUREO.t("dashboard.demo_failed", {
          detail: (data && data.detail) || "error",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
      }
    });
  }

  function wireBrowseButton(buttonSelector, inputSelector, endpoint, body) {
    const btn = document.querySelector(buttonSelector);
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const input = document.querySelector(inputSelector);
      let res;
      try {
        res = await MUREO.postJson(endpoint, body);
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.picker_error"), "error");
        return;
      }
      const data = (res && res.body) || {};
      if (data.status === "ok" && data.path) {
        if (input) input.value = data.path;
      } else if (data.status === "cancelled") {
        return;
      } else {
        MUREO.toast(MUREO.t("dashboard.picker_error"), "error");
      }
    });
  }

  function wirePickers() {
    wireBrowseButton(
      "[data-demo-browse]",
      "[data-demo-target]",
      "/api/pick/directory",
      { title: MUREO.t("dashboard.browse") }
    );
    wireBrowseButton(
      "[data-byod-browse]",
      "[data-byod-file]",
      "/api/pick/file",
      { title: MUREO.t("dashboard.browse"), kind: "xlsx" }
    );
  }

  // ----- BYOD section -------------------------------------------------

  function byodModeLabel(mode) {
    if (mode === "byod") return MUREO.t("dashboard.byod_mode_byod");
    if (mode === "not_configured") {
      return MUREO.t("dashboard.byod_mode_not_configured");
    }
    return MUREO.t("dashboard.byod_mode_live");
  }

  function buildByodRemoveButton(platform) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.byod_remove");
    btn.setAttribute("data-i18n", "dashboard.byod_remove");
    btn.addEventListener("click", async function () {
      const confirmed = await MUREO.confirmAction(
        MUREO.t("dashboard.byod_confirm_remove", { platform: platform })
      );
      if (!confirmed) return;
      let res;
      try {
        res = await MUREO.postJson("/api/byod/remove", {
          google_ads: platform === "google_ads",
          meta_ads: platform === "meta_ads",
        });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"), "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status !== "error") {
        await renderByodStatus();
      } else {
        MUREO.toast(MUREO.t("dashboard.byod_remove_failed"), "error");
      }
    });
    return btn;
  }

  function appendByodRow(tbody, p) {
    const tr = document.createElement("tr");
    const platformCell = document.createElement("td");
    platformCell.textContent = p.platform;
    const modeCell = document.createElement("td");
    modeCell.textContent = byodModeLabel(p.mode);
    const detailCell = document.createElement("td");
    if (p.mode === "byod") {
      const range = p.date_range
        ? (p.date_range.start || "?") + ".." + (p.date_range.end || "?")
        : "";
      detailCell.textContent =
        (p.rows != null ? p.rows + " rows" : "") +
        (range ? " (" + range + ")" : "");
    }
    const actionCell = document.createElement("td");
    if (p.mode === "byod") {
      actionCell.appendChild(buildByodRemoveButton(p.platform));
    }
    tr.appendChild(platformCell);
    tr.appendChild(modeCell);
    tr.appendChild(detailCell);
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  }

  async function renderByodStatus() {
    const tbody = document.querySelector("[data-byod-status-body]");
    if (!tbody) return;
    let body;
    try {
      const res = await fetch("/api/byod/status");
      body = await res.json();
    } catch (_err) {
      return;
    }
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    if (!body || body.status !== "ok" || !Array.isArray(body.platforms)) {
      return;
    }
    body.platforms.forEach(function (p) {
      appendByodRow(tbody, p);
    });
  }

  function wireByodImport() {
    const btn = document.querySelector("[data-byod-import]");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const fileNode = document.querySelector("[data-byod-file]");
      const replaceNode = document.querySelector("[data-byod-replace]");
      const resultNode = document.querySelector("[data-byod-result]");
      const filePath = fileNode ? fileNode.value.trim() : "";
      if (!filePath) {
        if (resultNode) {
          resultNode.textContent = MUREO.t("dashboard.byod_file_required");
        }
        return;
      }
      if (resultNode) {
        resultNode.textContent = MUREO.t("dashboard.byod_importing");
      }
      let res;
      try {
        res = await MUREO.postJson("/api/byod/import", {
          file_path: filePath,
          replace: replaceNode ? replaceNode.checked : false,
        });
      } catch (_err) {
        const msg = MUREO.t("dashboard.byod_import_failed", {
          detail: "network",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
        return;
      }
      const data = (res && res.body) || {};
      if (res && res.ok && data.status === "ok") {
        const msg = MUREO.t("dashboard.byod_import_success");
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "success");
        await renderByodStatus();
      } else {
        const msg = MUREO.t("dashboard.byod_import_failed", {
          detail: (data && data.detail) || "error",
        });
        if (resultNode) resultNode.textContent = msg;
        MUREO.toast(msg, "error");
      }
    });
  }

  async function runByodClear() {
    const ok1 = await MUREO.confirmAction(
      MUREO.t("dashboard.byod_confirm_clear_1")
    );
    if (!ok1) return;
    const ok2 = await MUREO.confirmAction(
      MUREO.t("dashboard.byod_confirm_clear_2")
    );
    if (!ok2) return;
    let res;
    try {
      res = await MUREO.postJson("/api/byod/clear", {});
    } catch (_err) {
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"), "error");
      return;
    }
    const data = (res && res.body) || {};
    if (res && res.ok && data.status !== "error") {
      MUREO.toast(MUREO.t("dashboard.byod_clear_success"), "success");
      await renderByodStatus();
    } else {
      MUREO.toast(MUREO.t("dashboard.byod_clear_failed"), "error");
    }
  }

  function wireByodClear() {
    const btn = document.querySelector("[data-byod-clear]");
    if (!btn) return;
    btn.addEventListener("click", runByodClear);
  }

  // mureo-native platforms (mureo ships native tools for these:
  // Google Ads, Meta Ads, Search Console — there is NO native GA4, so
  // GA4 is deliberately NOT a row here; it is an official-provider-only
  // platform). Search Console has no own credentials.json section — it
  // reuses the google_ads Google OAuth (adwords + webmasters scopes),
  // so it is a status-only row (configured ⇔ the shared Google OAuth is
  // present, which the wizard's Search Console step writes) with no
  // standalone Remove (removing it would nuke the shared Google sign-in
  // / Google Ads — done from the Google Ads row instead).
  const NATIVE_SECTIONS = [
    {
      key: "google_ads",
      section: "google_ads",
      labelKey: "wizard.platforms.google_ads",
      removable: true,
      configured: function (s, present) {
        return present.google_ads === true;
      },
    },
    {
      key: "meta_ads",
      section: "meta_ads",
      labelKey: "wizard.platforms.meta_ads",
      removable: true,
      configured: function (s, present) {
        return present.meta_ads === true;
      },
    },
    {
      key: "search_console",
      labelKey: "wizard.platforms.search_console",
      removable: false,
      noteKey: "dashboard.native_sc_row_note",
      configured: function (s) {
        return Boolean(
          s && s.credentials_oauth && s.credentials_oauth.google
        );
      },
    },
    {
      // Amazon Ads reaches Amazon's official MCP through the mureo-mediated
      // bridge, so it belongs in this list for the same reason the others
      // do: mureo holds the credentials and serves the tools. ``configured``
      // reuses the backend's own usability rule (status_collector's
      // amazon_ads row is true only for a client_id PLUS either an access
      // token or the refresh/secret pair) rather than re-deriving it here.
      key: "amazon_ads",
      section: "amazon_ads",
      labelKey: "wizard.platforms.amazon_ads",
      removable: true,
      configured: function (s, present) {
        return present.amazon_ads === true;
      },
    },
  ];

  function renderNativeSection(status) {
    const list = document.querySelector("[data-dashboard-native-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const present = (status && status.credentials_present) || {};
    let any = false;
    NATIVE_SECTIONS.forEach(function (row) {
      const configured = row.configured(status, present);
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.appendChild(statusMark(configured));
      label.appendChild(document.createTextNode(" "));
      // data-i18n on an INNER span only, so a locale re-translation
      // (which overwrites the node's textContent) can't wipe the mark.
      const labelText = document.createElement("span");
      labelText.textContent = MUREO.t(row.labelKey);
      labelText.setAttribute("data-i18n", row.labelKey);
      label.appendChild(labelText);
      li.appendChild(label);
      if (configured) any = true;
      if (configured && row.removable) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-secondary";
        btn.textContent = MUREO.t("dashboard.action_remove");
        btn.setAttribute("data-i18n", "dashboard.action_remove");
        btn.addEventListener("click", async function () {
          const ok = await MUREO.confirmAction(
            MUREO.t("dashboard.confirm_remove_credentials")
          );
          if (!ok) return;
          const res = await MUREO.postJson("/api/credentials/remove", {
            section: row.section,
          });
          if (res.ok) {
            await MUREO.loadStatus();
            renderAll();
          } else {
            MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
          }
        });
        li.appendChild(btn);
      }
      // Meta-only (#579): a Meta access token expires, and Remove — which
      // throws the credentials away — was the only action on this row, so
      // deleting them first was the natural misread. The hint and the card
      // live in auth_wizards_meta.js, shared with the wizard's Meta step;
      // keyed off the row so no other credential row grows the control.
      if (configured && row.key === "meta_ads" && window.MUREO_AUTH_META) {
        const expiring = window.MUREO_AUTH_META.buildMetaExpiringHint(status);
        if (expiring) li.appendChild(expiring);
        li.appendChild(
          window.MUREO_AUTH_META.buildMetaReauthSection(async function () {
            // A saved token changes the row it was opened from: re-read the
            // snapshot so the expiry hint clears with the token that caused
            // it, instead of leaving the warning that sent the operator here.
            await MUREO.loadStatus();
            renderAll();
          })
        );
      }
      // Google Ads + Search Console share the one Google OAuth.
      if (configured && row.key === "google_ads") {
        const note = document.createElement("div");
        note.className = "dashboard-provider-hosted-note";
        note.textContent = MUREO.t("dashboard.native_sc_shared");
        note.setAttribute("data-i18n", "dashboard.native_sc_shared");
        li.appendChild(note);
      }
      // Search Console row: always explain the shared-sign-in coupling.
      if (row.noteKey) {
        const note = document.createElement("div");
        note.className = "dashboard-provider-hosted-note";
        note.textContent = MUREO.t(row.noteKey);
        note.setAttribute("data-i18n", row.noteKey);
        li.appendChild(note);
      }
      list.appendChild(li);
    });
    if (!any) {
      const none = document.createElement("li");
      none.className = "dashboard-provider-hosted-note";
      none.textContent = MUREO.t("dashboard.native_none");
      none.setAttribute("data-i18n", "dashboard.native_none");
      list.appendChild(none);
    }
  }

  const api = {
    loadDemoScenarios: loadDemoScenarios,
    renderByodStatus: renderByodStatus,
    renderNativeSection: renderNativeSection,
    wireBulkClearButton: wireBulkClearButton,
    wireDemoCreate: wireDemoCreate,
    wireByodImport: wireByodImport,
    wireByodClear: wireByodClear,
    wirePickers: wirePickers,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_WORKSPACE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
