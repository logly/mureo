// dashboard_about.js — the About tab: version, updates, upgrade, restart.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move.
//
// The one part of the configure UI that changes the install rather than
// describing it, which is why so much of it is about NOT running twice:
// `upgradeInProgress`, `restartInProgress` and `updatePollActive` are three
// separate latches, each guarding an operation that is not idempotent, and
// the update poll carries its own deadline so a restart that never comes
// back cannot leave a spinner running forever.
//
// The red nav badge is the push half: an operator who never opens this tab
// still learns that an update is waiting, because renderUpdates() attaches
// the indicator to the About nav item itself.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_ABOUT`. Must load BEFORE dashboard.js.

(function () {
  "use strict";

  // #229 — About tab: mureo version + every installed package that
  // contributes to mureo's plugin entry-point groups. Read-only; the
  // server payload carries only distribution names and versions.
  // Silent failure like renderByodStatus — the section is non-critical.
  async function renderAbout() {
    // Wire the (static) restart control first — it is independent of the
    // /api/about payload, so it must be armed even if that fetch fails below.
    wireRestartButton();
    const versionNode = document.querySelector(
      "[data-dashboard-about-version]"
    );
    const tbody = document.querySelector("[data-about-packages-body]");
    if (!versionNode || !tbody) return;
    let body;
    try {
      const res = await fetch("/api/about");
      if (!res.ok) return;
      body = await res.json();
    } catch (_err) {
      return;
    }
    const mureoVersion =
      body && body.mureo && body.mureo.version ? body.mureo.version : "";
    versionNode.textContent = mureoVersion
      ? MUREO.t("dashboard.about_version", { version: mureoVersion })
      : "";
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    if (!body || !Array.isArray(body.packages)) return;
    body.packages.forEach(function (pkg) {
      const tr = document.createElement("tr");
      const nameCell = document.createElement("td");
      nameCell.textContent = pkg && pkg.name ? pkg.name : "";
      const versionCell = document.createElement("td");
      versionCell.textContent = pkg && pkg.version ? pkg.version : "";
      tr.appendChild(nameCell);
      tr.appendChild(versionCell);
      tbody.appendChild(tr);
    });
  }

  // #239 — background update check. Runs on dashboard load WITHOUT
  // blocking render: the menu shows immediately, and only once pip
  // reports ≥1 outdated mureo/plugin does the About nav item gain a red
  // indicator and the About tab populate its update area. Silent failure
  // like renderAbout — a degraded/errored check simply shows nothing.

  // Append a red "update available" badge to the About nav item (once).
  function setAboutNavBadge() {
    const navItem = document.querySelector('[data-dashboard-nav="about"]');
    if (!navItem) return;
    if (navItem.querySelector(".nav-badge-update")) return;
    const badge = document.createElement("span");
    badge.className = "nav-badge-update";
    badge.setAttribute("data-i18n", "dashboard.about_update_badge");
    badge.setAttribute("aria-label", MUREO.t("dashboard.about_update_badge"));
    badge.title = MUREO.t("dashboard.about_update_badge");
    badge.textContent = "●";
    navItem.appendChild(badge);
  }

  // Remove the red "update available" badge from the About nav item (if any).
  // Called when a check reports up-to-date and after a successful upgrade, so
  // the indicator never lingers once there is nothing left to update.
  function removeAboutNavBadge() {
    const navItem = document.querySelector('[data-dashboard-nav="about"]');
    if (!navItem) return;
    const badge = navItem.querySelector(".nav-badge-update");
    if (badge) navItem.removeChild(badge);
  }

  // Render one "name: installed → latest" list item (outdated → red).
  // textContent only — never innerHTML — so package names can't inject markup.
  function buildUpdateRow(pkg) {
    const li = document.createElement("li");
    li.className = "about-update-outdated";
    li.textContent = MUREO.t("dashboard.about_update_row", {
      name: pkg && pkg.name ? pkg.name : "",
      installed: pkg && pkg.installed ? pkg.installed : "",
      latest: pkg && pkg.latest ? pkg.latest : "",
    });
    return li;
  }

  // POST /api/upgrade (CSRF via MUREO.postJson). ONE click on "Update all"
  // runs the upgrade directly — no second confirm step. The server derives
  // the package list itself, so we send an empty body. Progress, success, and
  // failure all surface in the SAME summary line that showed "Updates are
  // available." so the operator sees the outcome where they were looking.
  let upgradeInProgress = false;
  async function runUpgrade() {
    if (upgradeInProgress) return;
    const button = document.querySelector("[data-about-update-button]");
    const summary = document.querySelector("[data-about-updates-summary]");
    const list = document.querySelector("[data-about-updates-list]");
    upgradeInProgress = true;
    if (button) button.disabled = true;
    if (summary) setSummary(summary, "dashboard.about_update_running");
    let res;
    try {
      res = await MUREO.postJson("/api/upgrade", {});
    } catch (_err) {
      res = null;
    }
    const ok = res && res.ok && res.body && res.body.status === "ok";
    if (!ok) {
      if (summary) setSummary(summary, "dashboard.about_update_failed");
      if (button) button.disabled = false;
      upgradeInProgress = false;
      return;
    }
    // Success: the on-disk version is now upgraded. Drop the outdated list,
    // the "Update all" button, and the nav badge.
    if (list) {
      while (list.firstChild) list.removeChild(list.firstChild);
    }
    if (button) {
      button.hidden = true;
      button.disabled = false;
    }
    removeAboutNavBadge();
    if (res.body.restarting) {
      // Always-on service: the daemon is restarting itself on the new code.
      // Show "restarting…", wait for it to come back, then reload so both the
      // UI and the running code are the new version — the operator does
      // nothing.
      if (summary) setSummary(summary, "dashboard.about_update_restarting");
      upgradeInProgress = false;
      pollServiceRestartThenReload(summary);
      return;
    }
    // Interactive mode (no supervisor): keep the manual "restart" prompt and
    // refresh the displayed (on-disk) version — the running process keeps the
    // old code until the operator restarts, which the message tells them.
    if (summary) setSummary(summary, "dashboard.about_update_done_restart");
    renderAbout();
    upgradeInProgress = false;
  }

  // Poll /api/ping until the daemon has clearly RESTARTED, then reload onto the
  // new version. "Clearly restarted" = the reported version changed, OR we saw
  // the server go DOWN and then come back UP (covers a plugin-only upgrade where
  // the mureo version is unchanged). Gating on those signals — rather than the
  // first 200 — avoids reloading onto the OLD process, which can still answer
  // briefly while it shuts down. Falls back to the manual prompt after 60s.
  async function pollServiceRestartThenReload(summary, timeoutKey) {
    let oldVersion = null;
    try {
      const r = await fetch("/api/ping", { cache: "no-store" });
      if (r && r.ok) {
        const b = await r.json().catch(function () {
          return null;
        });
        oldVersion = b && b.version ? b.version : null;
      }
    } catch (_e) {
      // Already down — fine, we'll detect the come-back-up below.
    }
    let sawDown = false;
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      await sleep(1500);
      try {
        const res = await fetch("/api/ping", { cache: "no-store" });
        if (res && res.ok) {
          const body = await res.json().catch(function () {
            return null;
          });
          const version = body && body.version ? body.version : null;
          const versionChanged = oldVersion && version && version !== oldVersion;
          if (versionChanged || sawDown) {
            location.reload();
            return;
          }
        } else {
          sawDown = true;
        }
      } catch (_e) {
        sawDown = true; // down mid-restart — a restart is happening
      }
    }
    if (summary) {
      setSummary(summary, timeoutKey || "dashboard.about_update_done_restart");
    }
  }

  // Wire the "Update all" button to upgrade DIRECTLY on click (one step — no
  // confirm panel). Idempotent (onclick, not addEventListener) so repeated
  // renders never stack handlers.
  function wireUpgradeButton() {
    const button = document.querySelector("[data-about-update-button]");
    if (!button) return;
    button.onclick = function () {
      runUpgrade();
    };
  }

  function setSummary(node, key) {
    node.textContent = MUREO.t(key);
    node.setAttribute("data-i18n", key);
  }

  // Apply an /api/updates envelope to the About update area, handling every
  // status: checking (a check is in flight), error (couldn't check), and ok
  // (up-to-date vs updates available). Extracted so the passive render and the
  // manual "check now" poll share one code path.
  function applyUpdatesBody(body) {
    const summary = document.querySelector("[data-about-updates-summary]");
    const list = document.querySelector("[data-about-updates-list]");
    const button = document.querySelector("[data-about-update-button]");
    if (!summary || !list || !button) return;
    if (!body || !body.status) return;
    if (body.status === "checking") {
      setSummary(summary, "dashboard.about_update_checking");
      return;
    }
    if (body.status !== "ok") {
      setSummary(summary, "dashboard.about_update_check_failed");
      button.hidden = true;
      return;
    }
    const outdated = Array.isArray(body.packages) ? body.packages : [];
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!body.any_update || outdated.length === 0) {
      setSummary(summary, "dashboard.about_up_to_date");
      button.hidden = true;
      // Up to date now — clear any stale "update available" nav badge.
      removeAboutNavBadge();
      return;
    }
    setSummary(summary, "dashboard.about_update_available");
    outdated.forEach(function (pkg) {
      list.appendChild(buildUpdateRow(pkg));
    });
    button.hidden = false;
    setAboutNavBadge();
    wireUpgradeButton();
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  // Wire the always-visible "check for updates" button. Idempotent (onclick,
  // not addEventListener) so repeated renders never stack handlers.
  function wireCheckButton() {
    const btn = document.querySelector("[data-about-check-button]");
    if (!btn) return;
    btn.onclick = function () {
      runCheckNow();
    };
  }

  // POST /api/restart, then reuse the upgrade flow's poll-then-reload: the
  // server is going down (managed service → supervisor relaunch; interactive
  // `mureo configure` → self-reexec), so we wait for /api/ping to come back
  // and reload onto the fresh process. The button stays disabled meanwhile;
  // it is only re-enabled if the server never returns within the deadline.
  let restartInProgress = false;
  async function runRestart() {
    if (restartInProgress) return;
    const button = document.querySelector("[data-about-restart-button]");
    const status = document.querySelector("[data-about-restart-status]");
    restartInProgress = true;
    if (button) button.disabled = true;
    if (status) setSummary(status, "dashboard.about_restarting");
    let res;
    try {
      res = await MUREO.postJson("/api/restart", {});
    } catch (_err) {
      res = null;
    }
    const ok = res && res.ok && res.body && res.body.status === "ok";
    if (!ok) {
      if (status) setSummary(status, "dashboard.about_restart_failed");
      if (button) button.disabled = false;
      restartInProgress = false;
      return;
    }
    // Reuse the upgrade poll. A plain restart keeps the same version, so the
    // reload fires on the "server went down then came back" signal rather than
    // a version change — reliable here because a full supervisor relaunch or
    // os.execv cold-start takes seconds (Python re-import), comfortably longer
    // than the poll interval. Success ends in location.reload(); this await
    // returns only if the server never came back within the deadline.
    await pollServiceRestartThenReload(status, "dashboard.about_restart_failed");
    if (button) button.disabled = false;
    restartInProgress = false;
  }

  // Wire the "Restart configure" button. Idempotent (onclick, not
  // addEventListener) so repeated About renders never stack handlers.
  function wireRestartButton() {
    const btn = document.querySelector("[data-about-restart-button]");
    if (!btn) return;
    btn.onclick = function () {
      runRestart();
    };
  }

  // Poll GET /api/updates until the status settles (no longer "checking") or
  // the deadline passes, then apply the result. The check runs server-side on
  // a background thread and can take up to the pip timeout, so the deadline
  // comfortably exceeds it. ``updatePollActive`` coalesces callers so the
  // passive load (when the first fetch is still mid-check) and the manual
  // "check now" button share ONE poll instead of stacking two — and a double
  // renderAll() (#223) cannot start a second loop.
  // Poll cadence for the background update check. The server runs pip on a
  // worker thread (bounded by its own ~60s pip timeout), so a 75s deadline
  // comfortably outlasts it; 1.5s between polls keeps the UI responsive
  // without hammering the endpoint.
  const UPDATE_POLL_DEADLINE_MS = 75000;
  const UPDATE_POLL_INTERVAL_MS = 1500;
  let updatePollActive = false;
  async function pollUpdatesUntilSettled() {
    if (updatePollActive) return;
    updatePollActive = true;
    const summary = document.querySelector("[data-about-updates-summary]");
    try {
      if (summary) setSummary(summary, "dashboard.about_update_checking");
      let body = null;
      const deadline = Date.now() + UPDATE_POLL_DEADLINE_MS;
      while (Date.now() < deadline) {
        await sleep(UPDATE_POLL_INTERVAL_MS);
        try {
          const res = await fetch("/api/updates");
          body = res.ok ? await res.json() : null;
        } catch (_e) {
          body = null;
        }
        if (body && body.status && body.status !== "checking") break;
      }
      if (!body || body.status === "checking") {
        // Poll exhausted without the check settling — don't leave a stuck
        // "Checking…"; surface that it couldn't complete.
        if (summary) setSummary(summary, "dashboard.about_update_check_failed");
      } else {
        applyUpdatesBody(body);
      }
    } finally {
      // Always clear the guard — even if a render/DOM op throws — so the
      // feature can never wedge itself permanently.
      updatePollActive = false;
    }
  }

  // POST /api/updates/refresh to drop the cache and start a fresh pip check,
  // then poll until the status settles.
  async function runCheckNow() {
    if (updatePollActive) return;
    const btn = document.querySelector("[data-about-check-button]");
    if (btn) btn.disabled = true;
    try {
      try {
        await MUREO.postJson("/api/updates/refresh", {});
      } catch (_err) {
        // Even if the trigger POST fails, poll the cache: a periodic refresh
        // may already be in flight.
      }
      await pollUpdatesUntilSettled();
    } finally {
      // Re-enable the button no matter how the poll ends.
      if (btn) btn.disabled = false;
    }
  }

  async function renderUpdates() {
    const area = document.querySelector("[data-about-updates]");
    if (!area) return;
    // Always reveal the area so the "check for updates" button is available,
    // even when everything is up to date or the last check errored / was cold.
    area.hidden = false;
    wireCheckButton();
    let body = null;
    try {
      const res = await fetch("/api/updates");
      body = res.ok ? await res.json() : null;
    } catch (_err) {
      body = null;
    }
    // A cold/stale cache answers "checking" while the background pip check
    // runs (the server starts it on this very fetch). The passive load must
    // then poll until it settles — otherwise the summary is stuck on
    // "Checking…" forever, since only the manual button used to poll. Fire it
    // without awaiting so renderAll() is not blocked; it repaints the DOM when
    // the check completes.
    if (body && body.status === "checking") {
      pollUpdatesUntilSettled();
      return;
    }
    applyUpdatesBody(body);
  }

  // ----- Advanced: External advisor MCP -------------------------------

  const api = {
    renderAbout: renderAbout,
    renderUpdates: renderUpdates,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_ABOUT = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
