// dashboard_reports.js — the Reports section's index: which clients, and what
// the roster says about them.
//
// This file was the whole Reports rendering layer at 2,139 lines. #687 cut it
// to five, and what stayed here is the half that decides what an operator is
// looking at rather than how any one client is drawn:
//
//   - which view the section shows (index / detail / archived), and the one
//     entry point that says "the operator asked for the section", so a redraw
//     cannot eject a reader from the report they are on;
//   - the portfolio row above the grid, the health filter, the platform split
//     and the "what mureo did today" feed — every one a sum over OTHER
//     clients' numbers, and so the easiest place to hide one mureo cannot
//     vouch for;
//   - the period toggle, and the fetch/render cycle that ties it together.
//
// It keeps the name and the global (`window.MUREO_DASHBOARD_REPORTS`) because
// that is dashboard.js's contract: `renderReports`, `enterReportsSection` and
// `wireReportsBackButton` are what the shell binds.
//
// The rest of the layer, in load order:
//
//   dashboard_reports_state.js  — the reports_*.js guard and bindings, and
//     `REPORTS_VIEW_STATE`, the ten values the view mutates. Those ten were
//     `let`s in one closure, which is exactly why this file could not be cut
//     before: two `<script>` IIFEs cannot share a `let`, but they can share
//     an object.
//   dashboard_reports_report.js — one stored report, rendered.
//   dashboard_reports_cards.js  — one client's card in the grid.
//   dashboard_reports_triage.js — the alert list.
//
// Two functions here are called from the cards module, which loads FIRST:
// `showReportsClientDetail` and `buildPlatformSlice`, plus `renderReports`
// itself. That file resolves them per call rather than at load, so no call
// site in either half had to change.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing one
// global, loaded last of the five and before dashboard.js.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports.js"
    );
  }
  const relativeAge = REPORTS_SHARED.relativeAge;
  const reportsPeriodLabel = REPORTS_SHARED.reportsPeriodLabel;
  const isCanonicalReportsPeriod = REPORTS_SHARED.isCanonicalReportsPeriod;
  const orderReportsClients = REPORTS_SHARED.orderReportsClients;
  const buildReportsTriage = REPORTS_SHARED.buildReportsTriage;
  const triageMarksClient = REPORTS_SHARED.triageMarksClient;
  const triageClientHealth = REPORTS_SHARED.triageClientHealth;
  const triageHealthCounts = REPORTS_SHARED.triageHealthCounts;
  const triageClientBadges = REPORTS_SHARED.triageClientBadges;
  const REPORTS_OVERVIEW = REPORTS_SHARED.REPORTS_OVERVIEW;
  const reportsViewToShow = REPORTS_SHARED.reportsViewToShow;
  const buildReportsPortfolio = REPORTS_SHARED.buildReportsPortfolio;
  const buildReportsActionFeed = REPORTS_SHARED.buildReportsActionFeed;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // dashboard_reports_report.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_REPORT = window.MUREO_DASHBOARD_REPORTS_REPORT;
  if (!R_REPORT) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_REPORT — load " +
        "dashboard_reports_report.js BEFORE dashboard_reports.js"
    );
  }
  const buildReportCard = R_REPORT.buildReportCard;
  const renderReportsActions = R_REPORT.renderReportsActions;
  const renderReportsLatest = R_REPORT.renderReportsLatest;

  // dashboard_reports_overview.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_OVERVIEW = window.MUREO_DASHBOARD_REPORTS_OVERVIEW;
  if (!R_OVERVIEW) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_OVERVIEW — load " +
        "dashboard_reports_overview.js BEFORE dashboard_reports.js"
    );
  }
  const renderReportsActionFeed = R_OVERVIEW.renderReportsActionFeed;
  const renderReportsFilters = R_OVERVIEW.renderReportsFilters;
  const renderReportsPlatforms = R_OVERVIEW.renderReportsPlatforms;
  const renderReportsPortfolio = R_OVERVIEW.renderReportsPortfolio;

  // dashboard_reports_cards.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_CARDS = window.MUREO_DASHBOARD_REPORTS_CARDS;
  if (!R_CARDS) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_CARDS — load " +
        "dashboard_reports_cards.js BEFORE dashboard_reports.js"
    );
  }
  const archivedReportsClients = R_CARDS.archivedReportsClients;
  const buildClientCardItem = R_CARDS.buildClientCardItem;
  const fetchClientCardSummary = R_CARDS.fetchClientCardSummary;
  const fetchReportsJson = R_CARDS.fetchReportsJson;
  const setReportsClientArchived = R_CARDS.setReportsClientArchived;
  const visibleReportsClients = R_CARDS.visibleReportsClients;

  // dashboard_reports_triage.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_TRIAGE = window.MUREO_DASHBOARD_REPORTS_TRIAGE;
  if (!R_TRIAGE) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_TRIAGE — load " +
        "dashboard_reports_triage.js BEFORE dashboard_reports.js"
    );
  }
  const renderReportsTriage = R_TRIAGE.renderReportsTriage;

  // Default slug for a client list: the first active client, else the first.
  function defaultClientSlug(rows) {
    if (!rows.length) return null;
    const active = rows.find(function (c) {
      return c && c.active;
    });
    return ((active || rows[0]) || {}).slug || null;
  }

  // Toggle the index (client grid) vs detail (one client) views, and the
  // detail's back bar (only meaningful when there is an index to return to).
  function setReportsView(view) {
    REPORTS_VIEW_STATE.reportsView = view;
    const index = document.querySelector("[data-reports-clients]");
    const detail = document.querySelector("[data-reports-detail]");
    const back = document.querySelector("[data-reports-back]");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (index) index.hidden = view !== "index";
    if (detail) detail.hidden = view !== "detail";
    // The two-column index shell (client portfolio + spend by platform).
    const shell = document.querySelector("[data-reports-index-grid]");
    if (shell) shell.hidden = view !== "index";
    // The archived list belongs to the index; renderReportsIndex un-hides it
    // again when there is something to list.
    const archived = document.querySelector("[data-reports-archived]");
    if (archived && view !== "index") archived.hidden = true;
    // So does the triage layer, and for a stronger reason: it states
    // findings ABOUT the grid, so left behind over a detail view it would be
    // describing clients that are no longer on screen. The portfolio strip
    // is the same claim in numbers — a roster total sitting above one
    // client's report reads as that client's.
    const triageBox = document.querySelector("[data-reports-triage]");
    if (triageBox && view !== "index") triageBox.hidden = true;
    const kpiStrip = document.querySelector("[data-reports-kpis]");
    if (kpiStrip && view !== "index") kpiStrip.hidden = true;
    // …and the rail's "what mureo did today", which is the roster's day and
    // not the day of whichever client a detail view is showing.
    const feed = document.querySelector("[data-reports-feed]");
    if (feed && view !== "index") feed.hidden = true;
    // The back link (under the "Reports" heading) and the client-name heading
    // appear only in a multi-client detail view — an OSS single client has no
    // index to go back to and no sibling to disambiguate.
    const showClientChrome =
      view === "detail" && REPORTS_VIEW_STATE.reportsClients.length > 1;
    if (back) back.hidden = !showClientChrome;
    if (nameEl) nameEl.hidden = !showClientChrome;
  }

  // ------------------------------------------------------------------
  // Triage layer (#651) — the index view's "what do I touch today?"
  // ------------------------------------------------------------------

  // INDEX view: a card per client (KPIs + flags for the selected window).
  // Fetches each client's summary in parallel; a period toggle built from the
  // union of windows lets the operator triage by Yesterday / Last 30 days.
  async function renderReportsIndex(seq) {
    const wrap = document.querySelector("[data-reports-clients]");
    if (!wrap) return;
    // Archived clients are off the grid entirely (and no summary is fetched
    // for them), then the operator's own order is applied.
    const rows = orderReportsClients(visibleReportsClients());
    const summaries = await Promise.all(
      rows.map(function (c) {
        return fetchClientCardSummary(c && c.slug ? c.slug : "");
      })
    );
    // superseded by a newer render
    if (seq !== REPORTS_VIEW_STATE.reportsRenderSeq) return;
    // Commit the view switch only once the data is ready — switching before
    // the await would expose an empty index grid if this render is superseded.
    setReportsView("index");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (freshness) freshness.textContent = "";
    // Triage before the cards (#651): which of these clients needs attention
    // today, ranked, with what to run about each. Built ONCE and handed to
    // both the layer and the grid, so the count above and the marks below
    // are the same list. This is the multi-client view, which is the only
    // place the Agency seam produces — a single workspace opens the detail
    // view directly and never reaches this function.
    const triage = buildReportsTriage(rows, summaries);
    // The roster's own figures, above the alerts — built from the same
    // summaries the cards below are built from, and stating over how many
    // clients each of them holds.
    const portfolio = buildReportsPortfolio(rows, summaries);
    renderReportsPortfolio(portfolio, triage);
    renderReportsTriage(triage);
    // The rail: what mureo did today, then where the money went. Both are
    // built from the summaries already in hand — no extra request.
    renderReportsActionFeed(buildReportsActionFeed(rows, summaries));
    renderReportsPlatforms(portfolio);
    wrap.textContent = "";
    // A filter left over from a previous render would hide cards with no
    // visible reason, so every index render starts on "all" — and the alert
    // list starts short again for the same reason it opens short at all.
    REPORTS_VIEW_STATE.reportsHealthFilter = "all";
    REPORTS_VIEW_STATE.reportsTriageShowAll = false;
    REPORTS_VIEW_STATE.reportsTriageOpenKinds = {};
    rows.forEach(function (c, i) {
      wrap.appendChild(
        buildClientCardItem(
          c,
          summaries[i],
          wrap,
          triageMarksClient(triage, i),
          triageClientHealth(triage, i),
          triageClientBadges(triage, i)
        )
      );
    });
    const countBadge = document.querySelector("[data-reports-clients-count]");
    if (countBadge) {
      countBadge.textContent = MUREO.t("dashboard.reports_clients_count", {
        n: rows.length,
      });
    }
    renderReportsFilters(triageHealthCounts(triage, rows.length));
    if (!rows.length) {
      // Every client archived: say so, and leave the disclosure below as the
      // way back — an empty grid with no explanation reads as a broken view.
      const note = document.createElement("p");
      note.className = "reports-clients-empty";
      // The grid is role="list"; keep its children listitems so the message
      // is announced rather than dropped as an out-of-structure child.
      note.setAttribute("role", "listitem");
      note.textContent = MUREO.t("dashboard.reports_all_archived");
      wrap.appendChild(note);
    }
    renderReportsArchived();
    // Period toggle from the union of windows any client advertises.
    const union = [];
    summaries.forEach(function (s) {
      (s && Array.isArray(s.periods) ? s.periods : []).forEach(function (p) {
        if (typeof p === "string" && p && union.indexOf(p) === -1) union.push(p);
      });
    });
    renderReportsPeriodToggle(union);
  }

  // The archived-clients disclosure under the index. Un-archiving has to be
  // reachable from THIS screen: if the only way back were editing the client
  // registry by hand, archiving would be a trap. It does not need to be
  // prominent, so it is a collapsed <details> that appears only when there is
  // something in it.
  function renderReportsArchived() {
    const box = document.querySelector("[data-reports-archived]");
    const list = document.querySelector("[data-reports-archived-list]");
    const summary = document.querySelector("[data-reports-archived-summary]");
    if (!box || !list) return;
    const rows = archivedReportsClients();
    box.hidden = !rows.length;
    list.textContent = "";
    if (!rows.length) return;
    if (summary) {
      summary.textContent = MUREO.t("dashboard.reports_archived_title", {
        n: rows.length,
      });
    }
    rows.forEach(function (c) {
      const slug = c && c.slug ? c.slug : "";
      const name = (c && (c.name || c.slug)) || "";
      const row = document.createElement("li");
      row.className = "reports-archived-row";
      const label = document.createElement("span");
      label.className = "reports-archived-name";
      // Registry-controlled text — textContent, never innerHTML (#533).
      label.textContent = name;
      row.appendChild(label);
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "reports-archived-restore";
      restore.setAttribute(
        "aria-label",
        MUREO.t("dashboard.reports_archive_restore_label", { name: name })
      );
      restore.textContent = MUREO.t("dashboard.reports_archive_restore");
      // No confirmation: restoring resumes collection, which is the safe
      // direction. It still cannot recover the period that was missed.
      restore.addEventListener("click", function () {
        setReportsClientArchived(slug, false);
      });
      row.appendChild(restore);
      list.appendChild(row);
    });
  }

  // DETAIL view: one client's full report (per-platform KPIs, latest report,
  // recent activity, period toggle). Sets the back bar + client name.
  function showReportsClientDetail(slug) {
    setReportsView("detail");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (nameEl) {
      const c = REPORTS_VIEW_STATE.reportsClients.find(function (r) {
        return r && r.slug === slug;
      });
      nameEl.textContent = c ? c.name || c.slug || "" : "";
    }
    // Bump the generation so any in-flight render is dropped, then load.
    REPORTS_VIEW_STATE.reportsRenderSeq++;
    renderReportsSummary(slug || null);
  }

  // Render the period toggle from the summary's `periods` union. Shown only
  // when there is a real choice (>= 2 windows); a single-window account has
  // nothing to switch, so the toggle stays hidden. Buttons are recreated on
  // every render, so their click handlers never accumulate.
  //
  // A window mureo does not define still gets a button — those are figures
  // an agent really collected, under a name no view expects (#659) — but it
  // is marked `is-adhoc` and carries the explanation, so the tab an agent
  // invented is not mistaken for one mureo keeps up to date.
  function renderReportsPeriodToggle(periods) {
    const wrap = document.querySelector("[data-reports-period]");
    if (!wrap) return;
    const list = Array.isArray(periods)
      ? periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    wrap.textContent = "";
    if (list.length < 2) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    list.forEach(function (token) {
      const active = token === REPORTS_VIEW_STATE.reportsPeriod;
      const adhoc = !isCanonicalReportsPeriod(token);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "reports-period-btn" +
        (active ? " is-active" : "") +
        (adhoc ? " is-adhoc" : "");
      btn.setAttribute("data-period", token);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.textContent = reportsPeriodLabel(token);
      if (adhoc) {
        // Named, not hidden and not silently kept: the operator is told what
        // this tab is so they can decide what to do with it.
        const hint = MUREO.t("dashboard.reports_period_adhoc");
        btn.title = hint;
        btn.setAttribute("aria-label", token + " — " + hint);
      }
      btn.addEventListener("click", function () {
        if (token === REPORTS_VIEW_STATE.reportsPeriod) return;
        REPORTS_VIEW_STATE.reportsPeriod = token;
        // Re-render the CURRENT view for the new window: the index re-fetches
        // every client's card, the detail re-fetches the selected client.
        // renderReports() preserves the active view + client via state.
        renderReports();
      });
      wrap.appendChild(btn);
    });
  }

  // Fetch + render the summary for a given client (or the default one).
  async function renderReportsSummary(client) {
    const seq = REPORTS_VIEW_STATE.reportsRenderSeq;
    // NB: reportsActiveClient is set only after the stale-render guards below,
    // so a superseded call can never reset it to a no-longer-shown client
    // (which would make the period toggle re-fetch the wrong one).
    const cards = document.querySelector("[data-reports-cards]");
    const empty = document.querySelector("[data-reports-empty]");
    const freshness = document.querySelector("[data-reports-freshness]");
    if (!cards) return;

    let summary;
    try {
      const params = [];
      if (client) params.push("client=" + encodeURIComponent(client));
      if (REPORTS_VIEW_STATE.reportsPeriod) {
        params.push("period=" + encodeURIComponent(REPORTS_VIEW_STATE.reportsPeriod));
      }
      const url =
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "");
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      summary = await res.json();
    } catch (_err) {
      // Fetch/parse failed. Clear any prior render so a failed client switch
      // never leaves a different client's numbers on screen — degrade to the
      // empty state rather than stale data.
      if (seq !== REPORTS_VIEW_STATE.reportsRenderSeq) return;
      REPORTS_VIEW_STATE.reportsActiveClient = client || null;
      cards.textContent = "";
      if (freshness) freshness.textContent = "";
      renderReportsPeriodToggle([]);
      renderReportsLatest(null);
      renderReportsActions(null);
      if (empty) empty.hidden = false;
      return;
    }
    // Superseded by a newer render.
    if (seq !== REPORTS_VIEW_STATE.reportsRenderSeq) return;
    REPORTS_VIEW_STATE.reportsActiveClient = client || null;
    // A 200 whose body is not a JSON object (null / string / number from a
    // misbehaving backend or proxy) must not crash the render — coerce to an
    // empty summary so the guarded accessors below fall back to the empty state.
    if (!summary || typeof summary !== "object") summary = {};

    // Reconcile the selected window against the windows that actually carry
    // data. When the preferred window (YESTERDAY) has nothing yet, fall back
    // to the first available and re-fetch ONCE — the corrected period is
    // guaranteed to be in `available`, so the re-entry can't loop.
    const available = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    if (
      available.length &&
      available.indexOf(REPORTS_VIEW_STATE.reportsPeriod) === -1
    ) {
      REPORTS_VIEW_STATE.reportsPeriod =
        available.indexOf("YESTERDAY") !== -1 ? "YESTERDAY" : available[0];
      return renderReportsSummary(client);
    }
    renderReportsPeriodToggle(available);

    cards.textContent = "";

    const platforms = Array.isArray(summary.platforms) ? summary.platforms : [];
    if (freshness) {
      // Document-level, and labelled as such ("Synced N ago"). Per-platform
      // freshness lives on each card's footer — see buildReportCardFoot.
      freshness.textContent = summary.last_synced_at
        ? MUREO.t("dashboard.reports_synced", {
            ago: relativeAge(summary.last_synced_at),
          })
        : "";
    }

    if (platforms.length === 0) {
      if (empty) empty.hidden = false;
    } else {
      if (empty) empty.hidden = true;
      platforms.forEach(function (p) {
        cards.appendChild(buildReportCard(p, summary));
      });
    }

    renderReportsLatest(summary.reports);
    renderReportsActions(summary.recent_actions);
  }

  // Entry point: fetch the client list, then show the right view. Re-runnable
  // (tab open, locale / period change, navigation).
  //
  // `entry` says WHY this render is happening, and it is the whole routing
  // input the state cannot supply: the left menu asking for the section is a
  // request for the client list, while a period switch or a status refresh
  // is a redraw of whatever the operator is already reading. Both arrive
  // here, and before this argument existed the second's rule ("keep the
  // detail while its client is alive") also governed the first — so the menu
  // could not get back to the list at all. The rule itself lives in
  // reports_overview.js, where the JS suite executes it.
  //
  // The routing decision counts the WHOLE registry, archived rows included.
  // Counting only the visible ones would drop an operator who archived down
  // to one client into that client's detail view — and the index is the only
  // place an archived client can be restored from, so the feature would trap
  // them. A registry that has ever held more than one client keeps its index.
  async function renderReports(entry) {
    const cards = document.querySelector("[data-reports-cards]");
    if (!cards) return;
    const seq = ++REPORTS_VIEW_STATE.reportsRenderSeq;
    const body = await fetchReportsJson("/api/reports/clients");
    if (seq !== REPORTS_VIEW_STATE.reportsRenderSeq) return;
    REPORTS_VIEW_STATE.reportsClients =
      body && Array.isArray(body.clients) ? body.clients : [];
    REPORTS_VIEW_STATE.reportsCanArchive = !!(body && body.can_archive);

    // An archived client is not a live selection: archiving the one on screen
    // returns the operator to the index rather than leaving them on a detail
    // view for a client that is no longer being collected.
    const hasIndex =
      REPORTS_VIEW_STATE.reportsClients.length > 1 ||
      archivedReportsClients().length > 0;
    const view = reportsViewToShow({
      entry: entry,
      currentView: REPORTS_VIEW_STATE.reportsView,
      hasIndex: hasIndex,
      selectionAlive:
        REPORTS_VIEW_STATE.reportsActiveClient &&
        visibleReportsClients().some(function (c) {
          return c && c.slug === REPORTS_VIEW_STATE.reportsActiveClient;
        }),
    });
    if (view === "index") {
      await renderReportsIndex(seq);
      return;
    }
    // OSS single workspace: no index page — the detail IS the section, so
    // the client is resolved here rather than carried across renders.
    if (!hasIndex) {
      REPORTS_VIEW_STATE.reportsActiveClient = defaultClientSlug(
        REPORTS_VIEW_STATE.reportsClients
      );
    }
    // showReportsClientDetail() sets the view + syncs the DOM.
    showReportsClientDetail(REPORTS_VIEW_STATE.reportsActiveClient);
  }

  // Entering the Reports section from the left menu. Always the client list
  // — see renderReports() above. Exported to selectNavGroup(), the one place
  // that knows the operator clicked the menu item.
  function enterReportsSection() {
    renderReports(REPORTS_OVERVIEW.REPORTS_ENTRY_MENU);
  }

  // Wire the back-to-index button once. Re-fetches the client list (a fresh
  // sync may have changed it) and shows the index.
  function wireReportsBackButton() {
    const back = document.querySelector("[data-reports-back]");
    if (!back) return;
    back.addEventListener("click", function () {
      REPORTS_VIEW_STATE.reportsView = "index";
      renderReports();
    });
  }



  const api = {
    renderReports: renderReports,
    enterReportsSection: enterReportsSection,
    wireReportsBackButton: wireReportsBackButton,
    showReportsClientDetail: showReportsClientDetail,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
