// dashboard_setup.js — the Setup section: what is installed and configured.
//
// Lifted verbatim out of dashboard.js (#678), which had reached 4,624 lines
// and ~40 render functions with no way to tell which belonged to which of
// the eight left-nav sections. Nothing here changed in the move.
//
// One question, asked five ways: what does this machine have set up right
// now? The host it runs under, the basic-setup parts, the installed MCP
// providers (including the hosted ones whose auth happens in the browser),
// the environment variables, and the Creative Studio keys.
//
// Every renderer is idempotent — it clears its container before rebuilding —
// because renderAll() runs it again on every status refresh and on every
// locale change. A renderer that appended would double the page.
//
// Shipping shape is the one every module in this directory has: a plain
// `<script>`-loaded file publishing ONE global, `window.MUREO_DASHBOARD_SETUP`.
// It must load BEFORE dashboard.js, which binds it, and before
// dashboard_workspace.js, which reuses `statusMark`.

(function () {
  "use strict";

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

  // Official provider ids whose catalog entry is a hosted_http server
  // (auth is client-side browser OAuth on first use in Claude). Source
  // of truth: catalog.py install_kind === "hosted_http": meta-ads-official
  // and tiktok-ads-official. Extend when a new hosted provider is added.
  const HOSTED_PROVIDER_IDS = ["meta-ads-official", "tiktok-ads-official"];

  // Per-hosted-provider setup note key, selected by the running host.
  // Meta is connector-only (its endpoint has no OAuth dynamic client
  // registration); TikTok DOES support DCR, so on Claude Code it is
  // registered directly with `claude mcp add` rather than a claude.ai
  // connector — hence a distinct note set. Missing/unknown host falls
  // back to the claude-code key.
  const HOSTED_NOTE_KEYS = {
    "meta-ads-official": {
      "claude-code": "dashboard.provider_hosted_oauth_note",
      "claude-desktop": "dashboard.provider_desktop_connectors_note",
      codex: "dashboard.provider_codex_hosted_na_note",
    },
    "tiktok-ads-official": {
      "claude-code": "dashboard.provider_tiktok_oauth_note",
      "claude-desktop": "dashboard.provider_tiktok_desktop_note",
      codex: "dashboard.provider_tiktok_codex_note",
    },
  };

  // Official provider id → the mureo-native platform it overlaps. Drives
  // the per-platform native↔official tool toggle. GA4 is intentionally
  // ABSENT: mureo has no native GA4 tools (official-only), so there is
  // nothing to toggle between for it.
  const PROVIDER_PLATFORM = {
    "google-ads-official": "google_ads",
    "meta-ads-official": "meta_ads",
  };

  // Creative Studio image-provider API keys (Setup tab). Each env-var name
  // binds to the ``creative_studio`` credentials section via env_var_writer's
  // allow-list, so this section reuses the generic single-field write
  // (POST /api/credentials/env-var) and the section remove
  // (POST /api/credentials/remove) — no dedicated backend route. Labels are
  // proper nouns (identical EN/JA); the hint prose is localized per key.
  const CREATIVE_STUDIO_KEYS = [
    {
      name: "OPENAI_API_KEY",
      labelKey: "dashboard.creative_studio_openai_label",
      hintKey: "dashboard.creative_studio_openai_hint",
    },
    {
      name: "GEMINI_API_KEY",
      labelKey: "dashboard.creative_studio_gemini_label",
      hintKey: "dashboard.creative_studio_gemini_hint",
    },
    {
      name: "FAL_KEY",
      labelKey: "dashboard.creative_studio_fal_label",
      hintKey: "dashboard.creative_studio_fal_hint",
    },
  ];

  // Membership lookup for de-duping these names out of the generic advanced
  // env list — they now have their own first-class Creative Studio section.
  const CREATIVE_STUDIO_ENV_NAMES = CREATIVE_STUDIO_KEYS.reduce(function (
    acc,
    key
  ) {
    acc[key.name] = true;
    return acc;
  },
  {});

  // Same de-duping treatment for Amazon Ads: every AMAZON_ADS_* name binds
  // to the ``amazon_ads`` credentials section (env_var_writer's allow-list),
  // which is exactly what the first-class Amazon card in the plugin
  // credentials section already edits — with proper labels, hints and
  // secret masking. Listing them AGAIN in the generic advanced form would
  // give the operator a second, worse way to write the same fields. The
  // allow-list entries still exist for the WRITE path (the wizard and this
  // card both persist through it) and for the status snapshot.
  const AMAZON_ENV_NAMES = {
    AMAZON_ADS_CLIENT_ID: true,
    AMAZON_ADS_ACCESS_TOKEN: true,
    AMAZON_ADS_REFRESH_TOKEN: true,
    AMAZON_ADS_CLIENT_SECRET: true,
    AMAZON_ADS_REGION: true,
    AMAZON_ADS_ACCOUNT_MODE: true,
    AMAZON_ADS_PROFILE_ID: true,
    AMAZON_ADS_ACCOUNT_ID: true,
    AMAZON_ADS_MANAGER_ACCOUNT_ID: true,
  };

  // Colored ✓ / ✗ status mark as its own element (kept separate from any
  // data-i18n text node so a locale re-translation can't wipe it).
  function statusMark(ok) {
    const m = document.createElement("span");
    m.className = ok ? "mark-ok" : "mark-no";
    m.textContent = ok ? "✓" : "✗";
    return m;
  }

  // Basic-setup row definitions. Keyed entries map a status part to its
  // label, per-row remove endpoint, confirmation key, and button label.
  // Kept as a module-local constant so renderBasicSection stays small.
  const BASIC_ROWS = [
    {
      // No `installUrl` on purpose: #222 makes the bare `mureo` MCP entry
      // harmful for multi-account backends (per-client `mureo-<slug>`
      // entries are the correct wiring), so this row intentionally has no
      // per-row (re)install button — restore it via the wizard instead.
      key: "mureo_mcp",
      labelKey: "wizard.basic.mureo_mcp",
      removeUrl: "/api/setup/mcp/remove",
      confirmKey: "dashboard.confirm_remove_mcp",
      actionKey: "dashboard.action_remove_mcp",
    },
    {
      key: "auth_hook",
      labelKey: "wizard.basic.auth_hook",
      removeUrl: "/api/setup/hook/remove",
      installUrl: "/api/setup/hook/install",
      confirmKey: "dashboard.confirm_remove_hook",
      actionKey: "dashboard.action_remove_hook",
    },
    {
      key: "skills",
      labelKey: "wizard.basic.skills",
      removeUrl: "/api/setup/skills/remove",
      installUrl: "/api/setup/skills/install",
      confirmKey: "dashboard.confirm_remove_skills",
      actionKey: "dashboard.action_remove_skills",
    },
  ];

  // The command that re-copies the deployed workflow skills, per host (#728).
  // Claude Desktop has no `mureo setup claude-desktop` subcommand and needs
  // none: it reads the same ~/.claude/skills Claude Code does, so the
  // claude-code install is its install too.
  const SKILLS_SETUP_COMMAND = {
    "claude-code": "mureo setup claude-code --skip-auth",
    "claude-desktop": "mureo setup claude-code --skip-auth",
    codex: "mureo setup codex --skip-auth",
  };

  // Skills left behind by an older mureo keep running — wrongly — against
  // tools that moved on, and presence alone drew them ✓ for months (#728).
  // Returns the sub-note for that state: which version is on disk, which one
  // this package ships, and the one command that fixes it. Null in every
  // other state — `missing` keeps its plain ✗, having no version to name and
  // no "update them" to ask for.
  //
  // Deliberately NOT a `data-i18n` node: the text carries interpolated
  // versions and a `<code>` child, both of which a locale re-translation
  // (which rewrites textContent) would destroy. renderAll() rebuilds this
  // section on every locale change, which is what keeps it translated.
  function buildStaleSkillsNote(status) {
    const parts = (status && status.setup_parts) || {};
    if (parts.skills_state !== "stale") return null;
    const installed = parts.skills_installed_version;
    const expected = parts.skills_expected_version || "";
    const note = document.createElement("div");
    note.className =
      "dashboard-provider-hosted-note dashboard-skills-stale-note";
    note.appendChild(
      document.createTextNode(
        (installed
          ? MUREO.t("dashboard.skills_stale_note", {
              installed: installed,
              expected: expected,
            })
          : MUREO.t("dashboard.skills_stale_note_unknown", {
              expected: expected,
            })) + " "
      )
    );
    const command = document.createElement("code");
    command.textContent =
      SKILLS_SETUP_COMMAND[(status && status.host) || "claude-code"] ||
      SKILLS_SETUP_COMMAND["claude-code"];
    note.appendChild(command);
    return note;
  }

  function renderHostSection(status) {
    const node = document.querySelector("[data-dashboard-host-value]");
    if (!node || !status) return;
    // Show the friendly host name (same labels as the wizard host
    // selector), not the raw "claude-desktop" / "claude-code" id.
    const hostKey =
      status.host === "claude-desktop"
        ? "wizard.host.claude_desktop"
        : status.host === "claude-code"
        ? "wizard.host.claude_code"
        : status.host === "codex"
        ? "wizard.host.codex"
        : null;
    if (hostKey) {
      node.textContent = MUREO.t(hostKey);
      node.setAttribute("data-i18n", hostKey);
    } else {
      node.textContent = status.host || "";
      node.removeAttribute("data-i18n");
    }
  }

  function buildBasicRemoveButton(row) {
    // Returns a button element wired to call `row.removeUrl` after a
    // single confirm. Toast (not throw) on failure.
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t(row.actionKey);
    btn.setAttribute("data-i18n", row.actionKey);
    btn.setAttribute("data-basic-remove", row.key);
    btn.addEventListener("click", async function () {
      const confirmed = await MUREO.confirmAction(MUREO.t(row.confirmKey));
      if (!confirmed) return;
      let res;
      try {
        // Send the client's known host so the server self-heals a session
        // whose host reset to the claude-code default after a daemon restart
        // (see handlers._resolve_host); otherwise the removal could target
        // the wrong host's config.
        res = await MUREO.postJson(row.removeUrl, {
          host: MUREO.state.status && MUREO.state.status.host,
        });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
        return;
      }
      // The route always answers HTTP 200; a swallowed failure surfaces as
      // an ``error`` envelope, so gate on the parsed body too (mirrors the
      // advisors/byod handlers) — otherwise a failed remove looks like it
      // succeeded.
      if (!res || !res.ok || !res.body || res.body.status === "error") {
        MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
        return;
      }
      await MUREO.loadStatus();
      renderAll();
    });
    return btn;
  }

  function buildBasicInstallButton(row, installed) {
    // Returns a button that (re)installs `row` via `row.installUrl` so the
    // operator can restore a removed part without re-running the wizard.
    // Non-destructive, so no confirm — toast (not throw) on failure. The
    // label is "Reinstall" when the part is present (idempotent refresh)
    // and "Install" when it was removed.
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    const actionKey = installed
      ? "dashboard.basic_reinstall"
      : "dashboard.basic_install";
    btn.textContent = MUREO.t(actionKey);
    btn.setAttribute("data-i18n", actionKey);
    btn.setAttribute("data-basic-install", row.key);
    btn.addEventListener("click", async function () {
      let res;
      try {
        // Send the client's known host so the server targets the operator's
        // actual host (see handlers._resolve_host), symmetric with remove.
        res = await MUREO.postJson(row.installUrl, {
          host: MUREO.state.status && MUREO.state.status.host,
        });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.install_failed"), "error");
        return;
      }
      // Same 200-envelope caveat as the remove button: a swallowed install
      // failure comes back as an ``error`` envelope over HTTP 200, so a bare
      // ``res.ok`` check would show a green "installed" mark on failure.
      if (!res || !res.ok || !res.body || res.body.status === "error") {
        MUREO.toast(MUREO.t("dashboard.install_failed"), "error");
        return;
      }
      // #400: toast the success/noop outcomes too — on an already-installed
      // row nothing else on screen changes, so a silent success is
      // indistinguishable from a dead button. ``noop`` means the server
      // decided nothing needed to change; its ``detail`` says why.
      if (res.body.status === "noop") {
        if (res.body.detail === "unsupported_on_desktop") {
          // Currently unreachable via the UI: the hook row's button is
          // suppressed on claude-desktop (hookUnsupported below), the only
          // host where the server returns this detail. Kept to match the
          // backend contract in case the row-gating ever changes.
          MUREO.toast(MUREO.t("dashboard.install_unsupported_desktop"), "info");
        } else {
          MUREO.toast(MUREO.t("dashboard.install_already"), "info");
        }
      } else if (res.body.status === "ok") {
        MUREO.toast(MUREO.t("dashboard.install_done"), "success");
      } else {
        // Unrecognized status — surface it rather than mislabeling as
        // success; the whole point of #400 is toast accuracy.
        MUREO.toast(MUREO.t("dashboard.install_failed"), "error");
      }
      await MUREO.loadStatus();
      renderAll();
    });
    return btn;
  }

  function renderBasicSection(status) {
    const list = document.querySelector("[data-dashboard-basic-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const parts = (status && status.setup_parts) || {};
    // #222: a multi-account backend never registers the bare `mureo` MCP
    // entry (per-client `mureo-<slug>` entries are the correct wiring), so
    // the MCP row must not render here either.
    const suppressMcp = Boolean(status && status.multi_account_auth);
    BASIC_ROWS.forEach(function (row) {
      if (suppressMcp && row.key === "mureo_mcp") return;
      const li = document.createElement("li");
      const installed = parts[row.key] === true;
      // #728: a stale skill set is not installed for the ✓/✗ purposes above
      // — it does not do what the row claims — but its files ARE on disk, so
      // the row keeps both controls it had, and the install button keeps
      // saying "Reinstall" for the overwrite that is the remedy here.
      const stale = row.key === "skills" && parts.skills_state === "stale";
      const onDisk = installed || stale;
      const labelSpan = document.createElement("span");
      let labelText = MUREO.t(row.labelKey);
      // The credential-guard hook has no surface on Claude Desktop, so
      // annotate it inline rather than implying it can be installed.
      const hookUnsupported =
        row.key === "auth_hook" &&
        status &&
        status.host === "claude-desktop";
      if (hookUnsupported) {
        labelText += " " + MUREO.t("wizard.basic.auth_hook_desktop_na");
      }
      labelSpan.appendChild(statusMark(installed));
      labelSpan.appendChild(document.createTextNode(" " + labelText));
      li.appendChild(labelSpan);
      if (onDisk) {
        li.appendChild(buildBasicRemoveButton(row));
      }
      // Per-row (re)install button, shown in both states so a removed part
      // can be restored without re-running the wizard. Suppressed for the
      // auth hook on Claude Desktop, where install is a no-op.
      if (row.installUrl && !hookUnsupported) {
        li.appendChild(buildBasicInstallButton(row, onDisk));
      }
      const staleNote = stale ? buildStaleSkillsNote(status) : null;
      if (staleNote) li.appendChild(staleNote);
      list.appendChild(li);
    });
  }

  // Connected-state for hosted_http providers (account-level Connectors
  // mureo never writes to the config file, so providers_installed always
  // reports them ✗). Lazily fetched once from /api/providers/hosted-status
  // and cached; null = not fetched yet.
  let hostedConnected = null;
  let hostedFetchInFlight = false;

  function renderProvidersSection(status) {
    const list = document.querySelector("[data-dashboard-providers-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const providers = (status && status.providers_installed) || {};
    let anyNotInstalled = false;
    let needHostedProbe = false;
    [
      "google-ads-official",
      "meta-ads-official",
      "ga4-official",
      "tiktok-ads-official",
    ].forEach(function (pid) {
      const li = document.createElement("li");
      // Tag the row with its provider id so CSS can apply a
      // platform-tinted left-accent stripe (Google blue / Meta blue /
      // GA4 orange). The data attribute is also a stable hook for
      // future per-platform UI (icons, links, etc.). See #183 review.
      li.dataset.platform = pid;
      const isHosted = HOSTED_PROVIDER_IDS.indexOf(pid) !== -1;
      // Hosted providers are "installed" ⇔ their account-level Connector
      // is Connected (mureo never registers them in the config file).
      let installed;
      if (isHosted) {
        installed = Boolean(hostedConnected && hostedConnected[pid] === true);
        if (hostedConnected === null) needHostedProbe = true;
      } else {
        installed = providers[pid];
        if (!installed) anyNotInstalled = true;
      }
      const labelSpan = document.createElement("span");
      labelSpan.appendChild(statusMark(installed));
      labelSpan.appendChild(document.createTextNode(" " + pid));
      li.appendChild(labelSpan);
      // No Remove for hosted here: a hosted MCP's lifecycle (the
      // ~/.claude.json http entry + its `/mcp` OAuth) is managed via
      // the wizard / `claude mcp remove`, not this dashboard row. Only
      // file-registered (pipx) providers get a Remove button.
      if (installed && !isHosted) {
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "btn btn-secondary";
        removeBtn.textContent = MUREO.t("dashboard.action_remove");
        removeBtn.setAttribute("data-i18n", "dashboard.action_remove");
        removeBtn.addEventListener("click", async function () {
          const res = await MUREO.postJson("/api/providers/remove", {
            provider_id: pid,
          });
          if (res.ok) {
            await MUREO.loadStatus();
            renderAll();
          } else {
            MUREO.toast(MUREO.t("app.toast_operation_failed"), "error");
          }
        });
        li.appendChild(removeBtn);
      }

      // hosted_http note(s) live INSIDE the provider's own <li> so
      // they read as part of the same provider row (Meta or TikTok) —
      // not as separate bordered list items. Guarded so a missing
      // translation never echoes the key.
      if (HOSTED_PROVIDER_IDS.indexOf(pid) !== -1) {
        function appendNote(key) {
          const text = MUREO.t(key);
          if (!text || text === key) return;
          const note = document.createElement("div");
          note.className = "dashboard-provider-hosted-note";
          note.textContent = text;
          note.setAttribute("data-i18n", key);
          li.appendChild(note);
        }
        // The setup note is provider- and host-specific (see
        // HOSTED_NOTE_KEYS): Meta is connector-only on every host; TikTok
        // registers directly on Claude Code (DCR) but still needs the
        // Connectors flow on Desktop.
        const noteKeys = HOSTED_NOTE_KEYS[pid];
        if (noteKeys) {
          const host = (status && status.host) || "claude-code";
          appendNote(noteKeys[host] || noteKeys["claude-code"]);
        }
      }

      // Per-platform native↔official tool toggle. Only meaningful when
      // the mureo MCP itself is configured (otherwise there are no
      // native tools to step aside). Server enforces the no-strand
      // guard; the UI just reflects state and surfaces the reason.
      const platform = PROVIDER_PLATFORM[pid];
      if (platform && providers.mureo) {
        const md = (status && status.mureo_disable) || {};
        const preferred = md[platform] === true;
        const tg = document.createElement("div");
        tg.className = "dashboard-provider-hosted-note dashboard-tooluse";
        const stateKey = preferred
          ? "dashboard.tooluse_state_official"
          : "dashboard.tooluse_state_native";
        const stateSpan = document.createElement("span");
        stateSpan.textContent =
          MUREO.t("dashboard.tooluse_label") + " " + MUREO.t(stateKey);
        tg.appendChild(stateSpan);
        const toKey = preferred
          ? "dashboard.tooluse_use_native"
          : "dashboard.tooluse_use_official";
        const tBtn = document.createElement("button");
        tBtn.type = "button";
        tBtn.className = "btn btn-secondary";
        tBtn.textContent = MUREO.t(toKey);
        tBtn.setAttribute("data-i18n", toKey);
        tBtn.addEventListener("click", async function () {
          const res = await MUREO.postJson(
            "/api/providers/native-toggle",
            { platform: platform, prefer_official: !preferred }
          );
          const body = res && res.body;
          if (res.ok && body && (body.status === "ok" || body.status === "noop")) {
            MUREO.toast(MUREO.t("dashboard.tooluse_restart_note"), "success");
            await MUREO.loadStatus();
            renderAll();
            return;
          }
          const detail = body && body.detail;
          const errKey =
            detail === "provider_not_installed"
              ? "dashboard.tooluse_err_provider_not_installed"
              : detail === "connector_not_connected"
              ? "dashboard.tooluse_err_connector_not_connected"
              : detail === "no_mureo_block"
              ? "dashboard.tooluse_err_no_mureo_block"
              : "dashboard.tooluse_err_generic";
          MUREO.toast(MUREO.t(errKey), "error");
        });
        tg.appendChild(tBtn);
        li.appendChild(tg);
      }
      list.appendChild(li);
    });
    if (anyNotInstalled) {
      const note = document.createElement("li");
      note.className = "dashboard-provider-add-note";
      note.textContent = MUREO.t("dashboard.provider_add_via_wizard");
      note.setAttribute("data-i18n", "dashboard.provider_add_via_wizard");
      list.appendChild(note);
    }

    // Probe the hosted connectors' Connected state once, then re-render
    // so a finished account-level Connector flips ✗ → ✓ without a manual
    // page reload. Cached + in-flight guarded so this never loops.
    if (needHostedProbe && !hostedFetchInFlight) {
      hostedFetchInFlight = true;
      MUREO.postJson("/api/providers/hosted-status", {})
        .then(function (res) {
          hostedConnected =
            (res && res.body && res.body.hosted_connected) || {};
        })
        .catch(function () {
          hostedConnected = {}; // best-effort: leave rows as ✗
        })
        .then(function () {
          hostedFetchInFlight = false;
          renderProvidersSection(MUREO.state && MUREO.state.status);
        });
    }
  }

  function wireEnvForm() {
    const form = document.querySelector("[data-env-form]");
    if (!form) return;
    form.addEventListener("submit", async function (evt) {
      evt.preventDefault();
      const name = form.querySelector("[data-env-name]").value;
      const value = form.querySelector('[name="env_value"]').value;
      if (!name || !value) return;
      const res = await MUREO.postJson("/api/credentials/env-var", {
        name: name,
        value: value,
      });
      if (res.ok) {
        form.querySelector('[name="env_value"]').value = "";
        MUREO.toast(MUREO.t("app.toast_saved"), "success");
        // Refresh to surface the freshly-saved value preview.
        await MUREO.loadStatus();
        renderEnvVarsSection(MUREO.state.status);
      } else {
        MUREO.toast(MUREO.t("app.toast_save_failed"), "error");
      }
    });
  }

  function renderEnvVarsSection(status) {
    // Renders one row per known env var: <name> <masked-or-full-preview>.
    // Secret-named vars arrive already masked from status_collector —
    // this function does NOT mask, and the raw value is never available
    // to the browser. Unset vars get a localised "(not set)" placeholder.
    const list = document.querySelector("[data-dashboard-env-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const envVars = (status && status.env_vars) || {};
    const names = Object.keys(envVars)
      .filter(function (name) {
        // Creative Studio keys and Amazon Ads fields have their own
        // first-class cards — don't list them a second time in the generic
        // advanced list.
        return !CREATIVE_STUDIO_ENV_NAMES[name] && !AMAZON_ENV_NAMES[name];
      })
      .sort();
    names.forEach(function (name) {
      const entry = envVars[name] || {};
      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.className = "dashboard-env-name";
      nameSpan.textContent = name;
      const valueSpan = document.createElement("span");
      valueSpan.className = "dashboard-env-value";
      if (entry.set && entry.value_preview != null) {
        valueSpan.textContent = entry.value_preview;
      } else {
        valueSpan.classList.add("dashboard-env-unset");
        valueSpan.textContent = MUREO.t("dashboard.env_value_unset");
      }
      li.appendChild(nameSpan);
      li.appendChild(valueSpan);
      list.appendChild(li);
    });
  }

  // Creative Studio image-provider keys: one masked input per provider with
  // a ✓/✗ configured mark + localized hint, one Save (persists every
  // non-blank field), and a Remove for the whole creative_studio section
  // (shown only once a key is stored). A stored key never round-trips to the
  // browser — a configured field shows the leave-blank-to-keep placeholder.
  function renderCreativeStudioSection(status) {
    const list = document.querySelector(
      "[data-dashboard-creative-studio-list]"
    );
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const envVars = (status && status.env_vars) || {};

    const form = document.createElement("form");
    form.className = "creative-studio-form";
    const inputs = [];
    let anyConfigured = false;

    CREATIVE_STUDIO_KEYS.forEach(function (key) {
      const entry = envVars[key.name] || {};
      const configured = entry.set === true;
      if (configured) anyConfigured = true;

      const label = document.createElement("label");
      const head = document.createElement("span");
      head.className = "creative-studio-key-head";
      head.appendChild(statusMark(configured));
      head.appendChild(document.createTextNode(" "));
      // data-i18n on an INNER span only, so a locale re-translation (which
      // overwrites textContent) can't wipe the ✓/✗ mark.
      const labelText = document.createElement("span");
      labelText.textContent = MUREO.t(key.labelKey);
      labelText.setAttribute("data-i18n", key.labelKey);
      head.appendChild(labelText);
      label.appendChild(head);

      const input = document.createElement("input");
      input.type = "password";
      input.name = key.name;
      // ``new-password`` defeats browser autofill of saved site passwords
      // into the key field (``off`` is ignored on password inputs).
      input.autocomplete = "new-password";
      input.placeholder = configured
        ? MUREO.t("dashboard.plugin_credentials_secret_placeholder")
        : MUREO.t("dashboard.creative_studio_key_placeholder");
      label.appendChild(input);
      inputs.push({ input: input, name: key.name });

      const hint = document.createElement("small");
      hint.className = "field-hint";
      hint.textContent = MUREO.t(key.hintKey);
      hint.setAttribute("data-i18n", key.hintKey);
      label.appendChild(hint);

      form.appendChild(label);
    });

    const save = document.createElement("button");
    save.type = "submit";
    save.className = "btn btn-primary";
    save.textContent = MUREO.t("dashboard.creative_studio_save");
    save.setAttribute("data-i18n", "dashboard.creative_studio_save");
    form.appendChild(save);

    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      saveCreativeStudioKeys(inputs);
    });
    list.appendChild(form);

    if (anyConfigured) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-secondary";
      remove.textContent = MUREO.t("dashboard.action_remove");
      remove.setAttribute("data-i18n", "dashboard.action_remove");
      remove.addEventListener("click", async function () {
        const ok = await MUREO.confirmAction(
          MUREO.t("dashboard.confirm_remove_credentials")
        );
        if (!ok) return;
        const res = await MUREO.postJson("/api/credentials/remove", {
          section: "creative_studio",
        });
        if (res.ok) {
          await MUREO.loadStatus();
          renderAll();
        } else {
          MUREO.toast(MUREO.t("dashboard.remove_failed"), "error");
        }
      });
      list.appendChild(remove);
    }
  }

  // Persist every non-blank Creative Studio key via the shared single-field
  // env-var write (the endpoint takes one name/value per call). Blank inputs
  // are skipped — leave-blank-to-keep. Awaits all writes, then refreshes so
  // the ✓/✗ marks + placeholders reflect the new stored state.
  async function saveCreativeStudioKeys(inputs) {
    const pending = inputs.filter(function (item) {
      return item.input.value !== "";
    });
    if (pending.length === 0) return;
    let ok = true;
    for (let i = 0; i < pending.length; i += 1) {
      const item = pending[i];
      let res;
      try {
        res = await MUREO.postJson("/api/credentials/env-var", {
          name: item.name,
          value: item.input.value,
        });
      } catch (_err) {
        res = null;
      }
      if (!res || !res.ok) ok = false;
    }
    if (ok) {
      MUREO.toast(MUREO.t("app.toast_saved"), "success");
    } else {
      MUREO.toast(MUREO.t("app.toast_save_failed"), "error");
    }
    await MUREO.loadStatus();
    renderCreativeStudioSection(MUREO.state.status);
  }

  function wireRerunWizardButton() {
    const btn = document.querySelector("[data-dashboard-rerun-wizard]");
    if (!btn) return;
    btn.addEventListener("click", function () {
      MUREO.navigateToWizard();
      document.dispatchEvent(
        new CustomEvent("mureo:wizard_start", { detail: {} })
      );
    });
  }

  const api = {
    statusMark: statusMark,
    renderHostSection: renderHostSection,
    renderBasicSection: renderBasicSection,
    renderProvidersSection: renderProvidersSection,
    renderEnvVarsSection: renderEnvVarsSection,
    renderCreativeStudioSection: renderCreativeStudioSection,
    wireEnvForm: wireEnvForm,
    wireRerunWizardButton: wireRerunWizardButton,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_SETUP = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
