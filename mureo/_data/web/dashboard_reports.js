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
//   dashboard_reports_report.js   — one stored report, rendered.
//   dashboard_reports_changes.js  — the detail view's tier (2): what moved
//     since yesterday, and what is wrong. About ONE client's two adjacent
//     days, which is the question this file does not ask (#715).
//   dashboard_reports_overview.js — the roster row above the grid, and
//     `buildPlatformSlice`, which the cards module binds from it at load.
//   dashboard_reports_cards.js    — one client's card in the grid.
//   dashboard_reports_triage.js   — the alert list.
//
// What the index SAYS — the alert layer, the per-client health, the health
// split, the band and the portfolio figures — is composed by reports_index.js
// (`buildReportsIndexModel`), once per render and before a node is drawn, so
// this file is left with putting the answer on screen (#715).
//
// Two functions here are called from modules that load FIRST: the cards
// module calls `renderReports` and `showReportsClientDetail`, and the overview
// module calls `showReportsClientDetail`. Both resolve them per call rather
// than at load, so no call site anywhere in the layer had to change.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing one
// global, loaded last of the six and before dashboard.js.

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
  const triageMarksClient = REPORTS_SHARED.triageMarksClient;
  const triageClientBadges = REPORTS_SHARED.triageClientBadges;
  const REPORTS_OVERVIEW = REPORTS_SHARED.REPORTS_OVERVIEW;
  const reportsViewToShow = REPORTS_SHARED.reportsViewToShow;
  const buildReportsActionFeed = REPORTS_SHARED.buildReportsActionFeed;
  const latestReport = REPORTS_SHARED.latestReport;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // reports_index.js — the index screen's whole model, built once per render
  // (#715). Read here rather than through dashboard_reports_state.js because
  // it composes the OTHER pure modules and so must load after all of them.
  const R_INDEX = window.MUREO_REPORTS_INDEX;
  if (!R_INDEX) {
    throw new Error(
      "dashboard_reports.js needs MUREO_REPORTS_INDEX — load " +
        "reports_index.js BEFORE dashboard_reports.js"
    );
  }
  const buildReportsIndexModel = R_INDEX.buildReportsIndexModel;

  // dashboard_reports_table.js — the Agency roster's table view and the
  // toolbar that switches between it and the cards.
  const REPORTS_TABLE = window.MUREO_DASHBOARD_REPORTS_TABLE;
  if (!REPORTS_TABLE) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_TABLE — load " +
        "dashboard_reports_table.js BEFORE dashboard_reports.js"
    );
  }

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
  const renderReportsLatest = R_REPORT.renderReportsLatest;

  // dashboard_reports_changes.js — the detail view's tier (2).
  const R_CHANGES = window.MUREO_DASHBOARD_REPORTS_CHANGES;
  if (!R_CHANGES) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_CHANGES — load " +
        "dashboard_reports_changes.js BEFORE dashboard_reports.js"
    );
  }
  const renderReportsChanges = R_CHANGES.renderReportsChanges;

  // The contract-driven detail screen (#706 step 3-a).
  const R_DETAIL = window.MUREO_DASHBOARD_REPORTS_DETAIL;
  if (!R_DETAIL) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_DETAIL — load " +
        "dashboard_reports_detail.js BEFORE dashboard_reports.js"
    );
  }
  // Drawn by the detail module for BOTH screens: shortening a row is a
  // property of the ENTRY (no display line), not of the client.
  const renderReportsActions = R_DETAIL.renderActions;

  // dashboard_reports_overview.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_OVERVIEW = window.MUREO_DASHBOARD_REPORTS_OVERVIEW;
  if (!R_OVERVIEW) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_OVERVIEW — load " +
        "dashboard_reports_overview.js BEFORE dashboard_reports.js"
    );
  }
  // The band across the top of the list screen (#706 step 3-b).
  const R_HERO = window.MUREO_DASHBOARD_REPORTS_HERO;
  if (!R_HERO) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_HERO — load " +
        "dashboard_reports_hero.js BEFORE dashboard_reports.js"
    );
  }
  const renderReportsHero = R_HERO.renderReportsHero;

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
    // …and the band above it (#706 step 3-b), for exactly that reason: it
    // counts the ROSTER, and "18/21 raised nothing" sitting over one client's
    // report is a sentence about a screen the operator has left.
    const heroBand = document.querySelector("[data-reports-hero]");
    if (heroBand && view !== "index") heroBand.hidden = true;
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
  //
  // What the screen SAYS is composed first and once — reports_index.js turns
  // the rows and their summaries into one model, and everything below draws
  // from it, so the band, the alert list, the chips, the cards and the roster
  // table are five views of one answer rather than five answers. This is the
  // multi-client view, which is the only place the Agency seam produces — a
  // single workspace opens the detail view directly and never reaches here.
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
    const model = buildReportsIndexModel(rows, summaries);
    renderReportsIndexBands(rows, summaries, model);
    renderReportsIndexGrid(wrap, rows, summaries, model);
    renderReportsArchived();
    renderReportsPeriodToggle(reportsPeriodUnion(summaries));
  }

  // Everything above and beside the grid, in the order an operator reads it.
  // Every one of these is a statement about the WHOLE roster, and every one
  // is drawn from the model this render built — none of them re-reads a
  // summary or re-grades a client.
  function renderReportsIndexBands(rows, summaries, model) {
    // The band across the top: the roster's health at a glance.
    renderReportsHero(model.hero);
    // The roster's own figures, above the alerts — from the same summaries
    // the cards below are built from, and stating over how many clients each
    // of them holds.
    renderReportsPortfolio(model.portfolio, model.triage);
    // Triage before the cards (#651): which clients need attention today,
    // ranked, with what to run about each. The same array the grid's marks
    // come from, so the count above and the marks below are one list.
    renderReportsTriage(model.triage);
    // The rail: what mureo did today, then where the money went. Both are
    // built from the summaries already in hand — no extra request.
    renderReportsActionFeed(buildReportsActionFeed(rows, summaries), model.hero.show);
    renderReportsPlatforms(model.portfolio);
  }

  // The grid itself: one card per client, the roster table built from the
  // same rows, and the chrome that counts them. `model.healthByIndex` is the
  // verdict this render already reached for each client — asking for it again
  // per card and again per roster row was four scans of one answer (#715).
  function renderReportsIndexGrid(wrap, rows, summaries, model) {
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
          triageMarksClient(model.triage, i),
          model.healthByIndex[i],
          triageClientBadges(model.triage, i)
        )
      );
    });
    // Both views are built from the roster already in hand; which one is
    // SHOWN is the table module's decision, and it remembers the operator's.
    REPORTS_TABLE.renderRoster(rows, summaries, function (i) {
      return model.healthByIndex[i];
    });
    const countBadge = document.querySelector("[data-reports-clients-count]");
    if (countBadge) {
      countBadge.textContent = MUREO.t("dashboard.reports_clients_count", {
        n: rows.length,
      });
    }
    renderReportsFilters(model.healthCounts);
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
  }

  // The windows the period toggle offers: the union of every window any
  // client on the grid advertises, in the order first seen.
  function reportsPeriodUnion(summaries) {
    const union = [];
    summaries.forEach(function (s) {
      (s && Array.isArray(s.periods) ? s.periods : []).forEach(function (p) {
        if (typeof p === "string" && p && union.indexOf(p) === -1) union.push(p);
      });
    });
    return union;
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
    moveReportsMeta("detail");
    const nameEl = document.querySelector("[data-reports-detail-client]");
    if (nameEl) {
      const c = REPORTS_VIEW_STATE.reportsClients.find(function (r) {
        return r && r.slug === slug;
      });
      nameEl.textContent = c ? c.name || c.slug || "" : "";
    }
    // A platform key belongs to the client it was chosen on: carried across,
    // the SELECT would disagree with what pickPlatform fell back to.
    if (REPORTS_VIEW_STATE.reportsActiveClient !== (slug || null)) {
      REPORTS_VIEW_STATE.reportsPlatformKey = null;
    }
    // Bump the generation so any in-flight render is dropped, then load.
    REPORTS_VIEW_STATE.reportsRenderSeq++;
    renderReportsSummary(slug || null);
  }

  /**
   * Put the period tabs + sync time where the current view wants them.
   *
   * ONE node, moved — never a second copy. The index wants them in the
   * shared head beside "Reports"; the detail view wants them on its own
   * toolbar, at the right of the platform picker, which is where the staff
   * mockup puts them and where the capture found them missing. Two nodes
   * carrying `data-reports-period` would make querySelector return whichever
   * came first in the document, which is #691's defect exactly — a hook
   * silently serving two masters.
   */
  function moveReportsMeta(view) {
    const meta = document.querySelector("[data-reports-meta]");
    const slot =
      view === "detail"
        ? document.querySelector("[data-reports-detail-meta-slot]")
        : document.querySelector("[data-reports-head-meta-slot]");
    if (!meta || !slot || meta.parentNode === slot) return;
    slot.appendChild(meta);
  }

  // Render the period toggle from the summary's `periods` union. Buttons are
  // recreated on every render, so their click handlers never accumulate.
  //
  // ONE window is not the same answer on both views, and conflating them was
  // #706's capture defect — the node was in the detail toolbar with `hidden`
  // still set, so the symptom pointed at the move rather than at this rule.
  // On the INDEX a lone window is nothing to switch, so the control stays
  // hidden (unchanged). On the DETAIL view it is the window the funnel, the
  // chart and the breakdown tables are all describing, and hiding it left
  // every figure unlabelled — so it renders as one INERT chip: a statement
  // of the window, not an offer to change it.
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
    if (list.length === 0) {
      wrap.hidden = true;
      return;
    }
    const detail = REPORTS_VIEW_STATE.reportsView === "detail";
    if (list.length < 2 && !detail) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    if (list.length < 2) {
      // A statement, not a control: `<span>`, no handler, and no
      // `aria-pressed` — a toggle of one would announce a choice that does
      // not exist.
      const solo = document.createElement("span");
      solo.className = "reports-period-solo";
      solo.setAttribute("data-period", list[0]);
      solo.textContent = reportsPeriodLabel(list[0]);
      if (!isCanonicalReportsPeriod(list[0])) {
        solo.classList.add("is-adhoc");
        solo.title = MUREO.t("dashboard.reports_period_adhoc");
      }
      wrap.appendChild(solo);
      return;
    }
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
      renderReportsChanges([], null);
      renderReportsPlatformTier([]);
      // Clears every contract section too: a failed client switch must not
      // leave the PREVIOUS client's screen up.
      R_DETAIL.renderReportsDetail(null, {});
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

    // #706 step 3-a: a contract gets the screen it was built for, no
    // contract gets the three tiers that shipped before it. Both are
    // complete screens, and renderReportsDetail is the one place that
    // decides which.
    // The log FIRST: a row's shape is decided by the entry, not by the
    // contract, so it must not sit downstream of the screen that is.
    renderReportsActions(summary.recent_actions);
    const drewContract = R_DETAIL.renderReportsDetail(summary, {
      platformKey: REPORTS_VIEW_STATE.reportsPlatformKey,
      onPlatform: function (key) {
        REPORTS_VIEW_STATE.reportsPlatformKey = key;
        renderReportsSummary(client);
      },
    });
    if (!drewContract) {
      // The three tiers, in the order an operator reads them (#691): what the
      // report concluded, what moved since yesterday, then everything.
      renderReportsLatest(summary.reports);
      renderReportsChanges(platforms, latestReport(summary.reports));
      renderReportsPlatformTier(platforms);
    }
  }

  // Tier (3)'s frame: shown whenever there is at least one platform card in
  // it, with the count the heading states. The cards themselves are appended
  // by renderReportsSummary — this only owns the section around them.
  function renderReportsPlatformTier(platforms) {
    // `data-reports-platform-tier`, NOT `data-reports-platforms`: that one is
    // the INDEX rail's "Spend by platform" aside (see
    // dashboard_reports_overview.js). Reusing it meant querySelector returned
    // the rail, this tier was never un-hidden, and the rail was being toggled
    // by a function that knows nothing about it.
    const block = document.querySelector("[data-reports-platform-tier]");
    const count = document.querySelector("[data-reports-platform-count]");
    if (!block) return;
    const rows = Array.isArray(platforms) ? platforms : [];
    block.hidden = rows.length === 0;
    if (count) {
      count.textContent = rows.length
        ? MUREO.t("dashboard.reports_platform_count", { n: rows.length })
        : "";
    }
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
    // The head owns them again the moment the index is what is on screen.
    moveReportsMeta(REPORTS_VIEW_STATE.reportsView);
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
