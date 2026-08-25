// dashboard_reports_cards.js — one client's card in the grid.
//
// Lifted verbatim out of dashboard_reports.js (#687), then narrowed when the
// stored-report block moved to dashboard_reports_report.js. Nothing here
// changed in either move beyond the bindings at the top.
//
// What a single client contributes to the index: its KPI cells, its freshness
// and conflict and not-collected notices, its triage badges, the drag handle
// and keyboard equivalent that reorder it, and the archive control — rendered
// only when the backing registry can actually record the decision, never
// rendered-and-inert.
//
// It also owns the two fetches a card needs, which is why they live here
// rather than with the index: the card is the thing that knows it needs a
// summary.
//
// Two functions it calls belong to the index (`renderReports` and
// `showReportsClientDetail`), and that file loads LAST, so those two are
// resolved per call below. Everything else is bound at load from the modules
// ahead of it — `buildPlatformSlice` included, which is
// dashboard_reports_overview.js's and loads before this file.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_CARDS`. Loads AFTER
// dashboard_reports_report.js and BEFORE dashboard_reports_triage.js.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_cards.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_cards.js"
    );
  }
  const reportsCardFreshness = REPORTS_SHARED.reportsCardFreshness;
  const aggregateClientKpis = REPORTS_SHARED.aggregateClientKpis;
  const humanizeReportFlag = REPORTS_SHARED.humanizeReportFlag;
  const reportFlagKind = REPORTS_SHARED.reportFlagKind;
  const flagSeverityRank = REPORTS_SHARED.flagSeverityRank;
  const clientReportFlags = REPORTS_SHARED.clientReportFlags;
  const formatNumber = REPORTS_SHARED.formatNumber;
  const persistReportsOrderFromDom = REPORTS_SHARED.persistReportsOrderFromDom;
  const moveReportsCard = REPORTS_SHARED.moveReportsCard;
  const clientPlatformSplit = REPORTS_SHARED.clientPlatformSplit;
  const platformColorSlot = REPORTS_SHARED.platformColorSlot;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // dashboard_reports_report.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_REPORT = window.MUREO_DASHBOARD_REPORTS_REPORT;
  if (!R_REPORT) {
    throw new Error(
      "dashboard_reports_cards.js needs MUREO_DASHBOARD_REPORTS_REPORT — load " +
        "dashboard_reports_report.js BEFORE dashboard_reports_cards.js"
    );
  }
  const buildStaleFiguresElement = R_REPORT.buildStaleFiguresElement;
  const staleAggregateFiguresText = R_REPORT.staleAggregateFiguresText;
  const clientKpiCell = R_REPORT.clientKpiCell;

  // dashboard_reports_overview.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const R_OVERVIEW = window.MUREO_DASHBOARD_REPORTS_OVERVIEW;
  if (!R_OVERVIEW) {
    throw new Error(
      "dashboard_reports_cards.js needs MUREO_DASHBOARD_REPORTS_OVERVIEW — load " +
        "dashboard_reports_overview.js BEFORE dashboard_reports_cards.js"
    );
  }
  const buildPlatformSlice = R_OVERVIEW.buildPlatformSlice;

  // Defined in dashboard_reports.js, which loads AFTER this file, so each name is
  // resolved when a card is clicked rather than at load. That is what
  // keeps the call sites below reading as they always did.
  function indexPeer() {
    const api = typeof window !== "undefined" ? window.MUREO_DASHBOARD_REPORTS : null;
    if (!api) {
      throw new Error(
        "MUREO_DASHBOARD_REPORTS (dashboard_reports.js) is missing — its <script> tag " +
          "must come AFTER dashboard_reports_cards.js in app.html."
      );
    }
    return api;
  }

  function renderReports(entry) {
    return indexPeer().renderReports(entry);
  }

  function showReportsClientDetail(slug) {
    return indexPeer().showReportsClientDetail(slug);
  }

  const REPORTS_CLIENT_FLAG_CAP = 3; // chips per card before collapsing to +N

  // Fetch JSON defensively — null on any failure / non-object body.
  async function fetchReportsJson(url) {
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return null;
      const body = await res.json();
      return body && typeof body === "object" ? body : null;
    } catch (_err) {
      return null;
    }
  }

  // Fetch a client's summary for its overview card. Honours the period toggle,
  // and when the selected window has no totals (a period-bucketed client whose
  // passthrough rollup is blank) falls back to the first window with data.
  async function fetchClientCardSummary(slug) {
    function summaryUrl(period) {
      const params = [];
      if (slug) params.push("client=" + encodeURIComponent(slug));
      if (period) params.push("period=" + encodeURIComponent(period));
      return (
        "/api/reports/summary" + (params.length ? "?" + params.join("&") : "")
      );
    }
    let summary =
      (await fetchReportsJson(summaryUrl(REPORTS_VIEW_STATE.reportsPeriod))) || {};
    const kpis = aggregateClientKpis(summary);
    const periods = Array.isArray(summary.periods)
      ? summary.periods.filter(function (p) {
          return typeof p === "string" && p;
        })
      : [];
    // `hasFigures`, not the rendered values: a conflicted client HAS data,
    // it is just withheld, and re-fetching another window would not fix that
    // (the conflict is a property of the document, not of the window).
    if (!kpis.hasFigures && periods.length) {
      const fallback =
        periods.indexOf(REPORTS_VIEW_STATE.reportsPeriod) === -1 ? periods[0] : null;
      if (fallback) {
        const alt = await fetchReportsJson(summaryUrl(fallback));
        if (alt) summary = alt;
      }
    }
    return summary;
  }

  // The card being dragged, held as the NODE (never as a slug fed back into
  // a selector — a client slug is registry-controlled text).
  let reportsDragNode = null;

  function wireReportsCardDrag(item, wrap) {
    item.draggable = true;
    item.addEventListener("dragstart", function (ev) {
      reportsDragNode = item;
      item.classList.add("is-dragging");
      if (ev.dataTransfer) {
        ev.dataTransfer.effectAllowed = "move";
        // Some browsers cancel a drag that carries no payload.
        try {
          const slug = item.getAttribute("data-client") || "";
          ev.dataTransfer.setData("text/plain", slug);
        } catch (_e) {
          /* payload optional */
        }
      }
    });
    item.addEventListener("dragend", function () {
      reportsDragNode = null;
      item.classList.remove("is-dragging");
    });
    item.addEventListener("dragover", function (ev) {
      if (!reportsDragNode || reportsDragNode === item) return;
      ev.preventDefault();
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
    });
    item.addEventListener("drop", function (ev) {
      if (!reportsDragNode || reportsDragNode === item) return;
      ev.preventDefault();
      const items = Array.prototype.slice.call(wrap.children);
      const from = items.indexOf(reportsDragNode);
      const to = items.indexOf(item);
      if (from === -1 || to === -1) return;
      if (from < to) wrap.insertBefore(reportsDragNode, item.nextSibling);
      else wrap.insertBefore(reportsDragNode, item);
      persistReportsOrderFromDom(wrap);
    });
  }

  // The drag handle. It is a real button so it is reachable by keyboard, and
  // the arrow keys move the card — a reorder control that only a mouse can
  // work excludes operators who do not use one. Both paths end in
  // moveReportsCard, so mouse and keyboard can never drift apart.
  function buildReportsDragHandle(item, name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reports-client-drag";
    btn.setAttribute("data-reports-drag-handle", "");
    btn.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_reorder_handle", { name: name })
    );
    btn.title = MUREO.t("dashboard.reports_reorder_hint");
    btn.textContent = "⠿";
    btn.addEventListener("keydown", function (ev) {
      let delta = 0;
      if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") delta = -1;
      else if (ev.key === "ArrowDown" || ev.key === "ArrowRight") delta = 1;
      if (!delta) return;
      ev.preventDefault();
      moveReportsCard(item, delta);
      btn.focus();
    });
    return btn;
  }

  // --------------------------------------------------------------------
  // Archiving (server-side — see mureo/web/reports.py)
  // --------------------------------------------------------------------
  function isArchivedClient(c) {
    return !!(c && c.archived);
  }

  function visibleReportsClients() {
    return REPORTS_VIEW_STATE.reportsClients.filter(function (c) {
      return !isArchivedClient(c);
    });
  }

  function archivedReportsClients() {
    return REPORTS_VIEW_STATE.reportsClients.filter(isArchivedClient);
  }

  // Relay the decision to the client registry. Archiving is NOT a view
  // preference: while it is set, that client's figures are never collected,
  // so a browser-local flag could not reach the process that does the
  // collecting. On success the whole view is re-rendered from the server's
  // answer rather than from an optimistic local edit.
  async function setReportsClientArchived(slug, archived) {
    let res = null;
    try {
      res = await MUREO.postJson("/api/reports/clients/archive", {
        slug: slug,
        archived: archived,
      });
    } catch (_err) {
      res = null;
    }
    if (!res || !res.ok || !res.body || res.body.status === "error") {
      MUREO.toast(MUREO.t("dashboard.reports_archive_failed"), "error");
      return;
    }
    REPORTS_VIEW_STATE.reportsView = "index";
    renderReports();
  }

  function buildReportsArchiveButton(slug, name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reports-client-archive";
    btn.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_archive_label", { name: name })
    );
    btn.textContent = MUREO.t("dashboard.reports_archive_action");
    btn.addEventListener("click", async function () {
      // The confirmation states the real consequence — figures stop being
      // collected and the gap is never backfilled — not "hide from view".
      const ok = await MUREO.confirmAction(
        MUREO.t("dashboard.reports_archive_confirm", { name: name })
      );
      if (!ok) return;
      await setReportsClientArchived(slug, true);
    });
    return btn;
  }

  // One grid cell: the card button plus its controls. The controls live
  // OUTSIDE the card because the card IS a button, and a button may not nest
  // interactive children.
  function buildClientCardItem(client, summary, wrap, triaged, health, badges) {
    const slug = client && client.slug ? client.slug : "";
    const name = (client && (client.name || client.slug)) || "";
    const item = document.createElement("div");
    // `is-triaged` says the card is marked; `is-<health>` says how loudly.
    // The same pairing the roster row carries, and for the same reason: the
    // attribute below is what the filter selects on, the class is what the
    // stylesheet colours on.
    item.className =
      "reports-client-card-item" +
      (triaged ? " is-triaged is-" + (health || "ok") : "");
    item.setAttribute("role", "listitem");
    item.setAttribute("data-client", slug);
    // The health the filter chips above the grid select on. It comes from
    // the triage layer's own findings, so a card the alerts call urgent can
    // never be filtered away as a healthy one.
    item.setAttribute("data-health", health || "ok");
    // The other half of the triage layer above the grid (#651): if the layer
    // says three clients need attention, exactly three cards are marked.
    // Both read the same list, so they cannot drift. A class alone would be
    // colour-only, and the grid is a list of buttons an operator may reach
    // by keyboard, so the mark carries text too.
    //
    // WHICH severity it names is the client's own (#697). `triaged` only
    // answers "is this client on the list at all", which is true at watch as
    // well as at attention, so a fixed "needs attention" string put an urgent
    // word — and the alert colour — on clients the layer had merely asked to
    // watch, while the badge two lines below said "watch" on the same card.
    // Reusing the badge's own strings is what keeps the two agreeing.
    if (triaged) {
      const mark = document.createElement("span");
      const severity = health || "ok";
      mark.className = "reports-client-card-mark is-" + severity;
      mark.textContent = MUREO.t("dashboard.reports_health_" + severity);
      item.appendChild(mark);
    }
    item.appendChild(buildClientCard(client, summary, health, badges));

    const tools = document.createElement("div");
    tools.className = "reports-client-tools";
    tools.appendChild(buildReportsDragHandle(item, name));
    // No registry, no archive control: an OSS-only single-workspace install
    // has nowhere to record the decision, and must be completely unaffected.
    if (REPORTS_VIEW_STATE.reportsCanArchive && slug) {
      tools.appendChild(buildReportsArchiveButton(slug, name));
    }
    item.appendChild(tools);

    wireReportsCardDrag(item, wrap);
    return item;
  }

  // One card: who the client is, what state mureo is in about them, and the
  // window's headline figures. A SUMMARY — deliberately not an explanation.
  //
  // It used to carry the full sentences too: which platform key could not be
  // resolved, why a collection failed, and the repair command to run. On a
  // twenty-seven-client grid that put three red paragraphs inside a 230px
  // card, and every one of them was already on screen in the alert list
  // directly above it. Two renderings of one finding is not twice the
  // signal; it is a wall with the summary buried in it.
  //
  // What did NOT move is the state. A card whose figures mureo will not
  // state still says so — the "—" and a short badge next to it ("Figures 29
  // days old"), because a bare dash reads as zero and #638 is the incident
  // where exactly that happened. The explanation and the way out live in the
  // alert row above (grouped, one per kind) and on the client's own detail
  // view, which is where the per-platform conflict note and its repair hint
  // have always been rendered.
  function buildClientCard(client, summary, health, badges) {
    const slug = client && client.slug ? client.slug : "";
    const card = document.createElement("button");
    card.type = "button";
    // The health is a class AND the status tag below, never colour alone:
    // the grid is a list of buttons an operator may reach by keyboard.
    card.className = "reports-client-card is-health-" + (health || "ok");
    card.setAttribute("data-client", slug);

    const head = document.createElement("div");
    head.className = "reports-client-card-head";
    const name = document.createElement("span");
    name.className = "reports-client-card-name";
    name.textContent = (client && (client.name || client.slug)) || "";
    head.appendChild(name);
    const status = document.createElement("span");
    status.className = "reports-client-card-status is-" + (health || "ok");
    status.textContent = MUREO.t("dashboard.reports_health_" + (health || "ok"));
    head.appendChild(status);
    // Per-platform freshness, NOT the document-level last_synced_at (#535):
    // that is re-stamped on any platform write, so a card whose numbers are
    // months old read as just-synced whenever a sibling platform synced.
    const cardFresh = reportsCardFreshness(summary);
    const fresh = document.createElement("span");
    fresh.className =
      "reports-client-card-fresh" + (cardFresh.stale ? " is-stale" : "");
    fresh.textContent = cardFresh.text;
    card.appendChild(head);
    // Freshness on its own line, under the name: in the head it competed
    // with the name and the status pill for a 230px row, and the casualty
    // was the name — a five-character Japanese client name was being broken
    // across two lines.
    card.appendChild(fresh);

    const badgeRow = document.createElement("div");
    badgeRow.className = "reports-client-card-badges";

    // A conflicted card still carries its modifier class, so it can never be
    // skimmed as an ordinary one — but the sentence explaining the conflict
    // is the alert row's job now, and the repair command is the detail
    // view's. Both are one click from here and neither is duplicated.
    const conflicts =
      summary && Array.isArray(summary.platform_conflicts)
        ? summary.platform_conflicts
        : [];
    if (conflicts.length) card.classList.add("is-conflicted");

    // The state, as badges: one per kind, short, no command and no prose.
    // These are what keeps the "—" below from reading as zero.
    (Array.isArray(badges) ? badges : []).forEach(function (badge) {
      const el = document.createElement("span");
      el.className = "reports-client-card-badge is-" + badge.severity;
      el.textContent = badge.text;
      badgeRow.appendChild(el);
    });
    if (badgeRow.childNodes.length) card.appendChild(badgeRow);

    const kpis = aggregateClientKpis(summary);
    const krow = document.createElement("div");
    krow.className = "reports-client-card-kpis";
    krow.appendChild(
      clientKpiCell(
        "dashboard.reports_kpi_spend",
        // "—" (not 0) when absent — a no-data client must not read as zero
        // spend in this at-a-glance triage view.
        kpis.spend != null ? formatNumber(kpis.spend) : "—"
      )
    );
    if (kpis.conversions != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_conversions",
          formatNumber(kpis.conversions)
        )
      );
    }
    if (kpis.cpa != null) {
      krow.appendChild(
        clientKpiCell(
          "dashboard.reports_kpi_cpa",
          formatNumber(Math.round(kpis.cpa))
        )
      );
    }
    card.appendChild(krow);
    // …and the withheld figures restated below the cells, so the operator
    // keeps every number they had before, correctly labelled.
    if (kpis.staleFigures) {
      card.appendChild(
        buildStaleFiguresElement(
          "reports-client-card-stale-figures",
          kpis.staleFigures.fetched_at,
          staleAggregateFiguresText(kpis.staleFigures)
        )
      );
    }

    // Where this client's spend went, as one bar. It is drawn only from the
    // rows mureo is willing to state (reports_overview.js returns nothing
    // for a withheld or stale client): the bar is the same claim as the
    // number above it, and drawing shares of figures the card refuses to
    // print would restate them in a shape that looks like a picture.
    const split = clientPlatformSplit(summary);
    if (split.length) {
      const bar = document.createElement("div");
      bar.className = "reports-client-split";
      split.forEach(function (row) {
        bar.appendChild(buildPlatformSlice(row, "reports-client-split-slice"));
      });
      card.appendChild(bar);
      const legend = document.createElement("div");
      legend.className = "reports-client-split-legend";
      split.forEach(function (row) {
        const entry = document.createElement("span");
        entry.className = "reports-client-split-entry";
        const dot = document.createElement("i");
        dot.className = "reports-client-split-dot is-platform-" + platformColorSlot(row.key);
        entry.appendChild(dot);
        const label = document.createElement("span");
        // Registry / plugin-controlled display name — text, never markup.
        label.textContent = row.label;
        entry.appendChild(label);
        legend.appendChild(entry);
      });
      card.appendChild(legend);
    }

    const flags = clientReportFlags(summary)
      .slice()
      .sort(function (a, b) {
        return flagSeverityRank(a) - flagSeverityRank(b);
      });
    if (flags.length) {
      const chips = document.createElement("div");
      chips.className = "reports-client-card-flags";
      flags.slice(0, REPORTS_CLIENT_FLAG_CAP).forEach(function (flag) {
        const chip = document.createElement("span");
        chip.className = "report-chip " + reportFlagKind(flag);
        chip.textContent = humanizeReportFlag(flag);
        chips.appendChild(chip);
      });
      const overflow = flags.length - REPORTS_CLIENT_FLAG_CAP;
      if (overflow > 0) {
        const more = document.createElement("span");
        more.className = "report-chip reports-client-flag-more";
        more.textContent = "+" + overflow;
        chips.appendChild(more);
      }
      card.appendChild(chips);
    }

    card.addEventListener("click", function () {
      REPORTS_VIEW_STATE.reportsActiveClient = slug;
      showReportsClientDetail(slug);
    });
    return card;
  }



  const api = {
    fetchReportsJson: fetchReportsJson,
    fetchClientCardSummary: fetchClientCardSummary,
    visibleReportsClients: visibleReportsClients,
    archivedReportsClients: archivedReportsClients,
    setReportsClientArchived: setReportsClientArchived,
    buildClientCardItem: buildClientCardItem,
    buildClientCard: buildClientCard,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_CARDS = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
