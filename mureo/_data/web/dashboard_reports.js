// dashboard_reports.js — the Reports section's index: which clients, and what
// the roster says about them.
//
// This file used to be the whole Reports rendering layer at 2,139 lines, and
// #687 cut it in three. What stayed here is the half that decides what an
// operator is looking at rather than how one client is drawn:
//
//   - which view the section shows (index / detail / archived), and the one
//     entry point that says "the operator asked for the section" so a redraw
//     cannot eject a reader from the report they are on;
//   - the triage list: what is wrong across the roster, ranked, grouped and
//     dismissible;
//   - the portfolio row above the grid, the health filter, the platform split
//     and the "what mureo did today" feed;
//   - the period toggle, and the fetch/render cycle that ties it together.
//
// It keeps the name and the global (`window.MUREO_DASHBOARD_REPORTS`) because
// that is dashboard.js's contract: `renderReports`, `enterReportsSection` and
// `wireReportsBackButton` are what the shell binds.
//
// The other two thirds:
//
//   dashboard_reports_state.js — the reports_*.js load guard and bindings, and
//     `REPORTS_VIEW_STATE`, the six values both halves mutate. Those six were
//     `let`s in one closure, which is exactly why this file could not be cut
//     before: two `<script>` IIFEs cannot share a `let`, but they can share an
//     object.
//   dashboard_reports_cards.js — one client's card and the stored report
//     inside it. Its exports are bound below by their original names.
//
// Three functions here are called from the cards half, which loads FIRST:
// `renderReports`, `showReportsClientDetail` and `buildPlatformSlice`. That
// file resolves them per call rather than at load, so no call site in either
// half had to change.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing one
// global, loaded after dashboard_reports_cards.js and before dashboard.js.

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
  const formatNumber = REPORTS_SHARED.formatNumber;
  const orderReportsClients = REPORTS_SHARED.orderReportsClients;
  const buildReportsTriage = REPORTS_SHARED.buildReportsTriage;
  const triageMarksClient = REPORTS_SHARED.triageMarksClient;
  const triageItemText = REPORTS_SHARED.triageItemText;
  const triageItemNextStep = REPORTS_SHARED.triageItemNextStep;
  const triageItemTag = REPORTS_SHARED.triageItemTag;
  const triageClientHealth = REPORTS_SHARED.triageClientHealth;
  const triageHealthCounts = REPORTS_SHARED.triageHealthCounts;
  const triageClientBadges = REPORTS_SHARED.triageClientBadges;
  const groupReportsTriage = REPORTS_SHARED.groupReportsTriage;
  const partitionTriageGroups = REPORTS_SHARED.partitionTriageGroups;
  const dismissTriageGroup = REPORTS_SHARED.dismissTriageGroup;
  const dismissTriageItem = REPORTS_SHARED.dismissTriageItem;
  const restoreTriageDismissals = REPORTS_SHARED.restoreTriageDismissals;
  const collapseTriageGroups = REPORTS_SHARED.collapseTriageGroups;
  const REPORTS_OVERVIEW = REPORTS_SHARED.REPORTS_OVERVIEW;
  const reportsViewToShow = REPORTS_SHARED.reportsViewToShow;
  const buildReportsPortfolio = REPORTS_SHARED.buildReportsPortfolio;
  const platformColorSlot = REPORTS_SHARED.platformColorSlot;
  const buildReportsActionFeed = REPORTS_SHARED.buildReportsActionFeed;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // dashboard_reports_cards.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_CARDS = window.MUREO_DASHBOARD_REPORTS_CARDS;
  if (!REPORTS_CARDS) {
    throw new Error(
      "dashboard_reports.js needs MUREO_DASHBOARD_REPORTS_CARDS — load " +
        "dashboard_reports_cards.js BEFORE dashboard_reports.js"
    );
  }
  const archivedReportsClients = REPORTS_CARDS.archivedReportsClients;
  const buildClientCardItem = REPORTS_CARDS.buildClientCardItem;
  const buildReportCard = REPORTS_CARDS.buildReportCard;
  const fetchClientCardSummary = REPORTS_CARDS.fetchClientCardSummary;
  const fetchReportsJson = REPORTS_CARDS.fetchReportsJson;
  const renderReportsActions = REPORTS_CARDS.renderReportsActions;
  const renderReportsLatest = REPORTS_CARDS.renderReportsLatest;
  const setReportsClientArchived = REPORTS_CARDS.setReportsClientArchived;
  const visibleReportsClients = REPORTS_CARDS.visibleReportsClients;

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

  // Render the ranked findings above the client grid.
  //
  // Silence when there is nothing: no "0 alerts" banner competing for
  // attention with the cards it sits above. The list is emptied BEFORE the
  // early return so a row from a previous render cannot survive one that
  // found nothing.
  //
  // Nothing here ranks, sorts or trims: the order and the membership are
  // decided in reports_triage.js, where a test runner can execute them.
  // Defensive about its argument for the usual reason — this runs
  // mid-render, and a throw blanks the whole Reports view.
  function renderReportsTriage(built) {
    const box = document.querySelector("[data-reports-triage]");
    const list = document.querySelector("[data-reports-triage-list]");
    const heading = document.querySelector("[data-reports-triage-title]");
    if (!box || !list) return;
    const items = built && Array.isArray(built.items) ? built.items : [];
    // The count is of CLIENTS, and it is the same array the grid marks from
    // — one client raising four findings is still one card.
    const marked = built && Array.isArray(built.clients) ? built.clients : [];
    list.textContent = "";
    box.hidden = !items.length;
    if (!items.length) return;
    if (heading) {
      heading.textContent = MUREO.t("dashboard.reports_triage_title", {
        n: marked.length,
      });
    }
    // The same count again, as the panel's badge. It reads the same array as
    // the heading and the grid's marks, so there is still exactly one list.
    const badge = document.querySelector("[data-reports-triage-count]");
    if (badge) {
      badge.textContent = MUREO.t("dashboard.reports_triage_count", {
        n: marked.length,
      });
    }
    // One row per KIND, each naming the clients it covers — the grouping
    // and the dismissal filter are both the module's (reports_triage.js).
    // Neither changes `built.clients`, so the heading above and the marks
    // below still count every client that raised anything.
    reportsTriageBuilt = built;
    const split = partitionTriageGroups(groupReportsTriage(built));
    // …and only the top few of those, unless the operator asked for the
    // rest. Which rows survive the collapse is the module's decision, for
    // the same reason the ranking is: "the top four" is only defensible
    // while it means the four mureo can do most about.
    const shown = collapseTriageGroups(split.visible, reportsTriageShowAll);
    shown.rows.forEach(function (group) {
      list.appendChild(buildTriageRow(group));
    });
    renderTriageMore(shown);
    renderTriageDismissed(split.hiddenCount);
  }

  // Which rows are expanded, by kind. Dismissing one message re-renders the
  // list, and a row that snapped shut after every ✕ would make closing six
  // findings six trips through the disclosure. Reset with the list itself on
  // every index render.
  let reportsTriageOpenKinds = {};

  // Whether the alert list is showing every row it has. Reset on every index
  // render — the list opens short each time the operator arrives, which is
  // the whole point of opening short.
  let reportsTriageShowAll = false;

  // "Show all (N)". Absent when the list already fits: there is no
  // "show all (0)", the same way there is no "0 alerts" banner.
  function renderTriageMore(shown) {
    const more = document.querySelector("[data-reports-triage-more]");
    if (!more) return;
    more.hidden = !shown.collapsed;
    if (!shown.collapsed) return;
    more.textContent = MUREO.t("dashboard.reports_triage_show_all", {
      n: shown.remaining,
    });
    more.onclick = function () {
      reportsTriageShowAll = true;
      renderReportsTriage(reportsTriageBuilt);
    };
  }

  // The layer as it was last built, so closing or restoring a row can redraw
  // it without re-fetching every client's summary.
  let reportsTriageBuilt = null;

  // "N alerts hidden", with the way back.
  //
  // This is the price of the ✗ and it is not optional. Closing a row hides
  // it; it does not resolve anything, and a finding that left NO trace when
  // it was closed would be the failure mode this entire layer was built
  // against (#636, #638: the condition was true, and nothing said so). So
  // the count is always on screen while anything is hidden, it says in words
  // that hiding resolved nothing, and one button brings them all back.
  function renderTriageDismissed(hiddenCount) {
    const box = document.querySelector("[data-reports-triage-hidden]");
    if (!box) return;
    box.textContent = "";
    box.hidden = !hiddenCount;
    if (!hiddenCount) return;
    const title = document.createElement("span");
    title.className = "reports-triage-hidden-title";
    // MESSAGES, not rows. Counting rows would report "1" for six findings
    // nobody can see, which is the silence this line exists to prevent.
    title.textContent = MUREO.t("dashboard.reports_triage_hidden_title", {
      n: hiddenCount,
    });
    box.appendChild(title);
    const note = document.createElement("span");
    note.className = "reports-triage-hidden-note";
    note.textContent = MUREO.t("dashboard.reports_triage_hidden_note");
    box.appendChild(note);
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "reports-triage-restore";
    restore.textContent = MUREO.t("dashboard.reports_triage_restore");
    restore.addEventListener("click", function () {
      restoreTriageDismissals();
      renderReportsTriage(reportsTriageBuilt);
    });
    box.appendChild(restore);
  }

  // One row: one KIND of finding, the clients it covers, and — one click
  // away — what each of them says and what to run about it.
  //
  // Per kind, not per client. On the twenty-seven-client install this layer
  // was built for it rendered sixteen rows, six of them the same sentence
  // about the same unresolvable platform key under six different names. The
  // grouping is reports_triage.js's; nothing here re-orders or re-groups.
  //
  // The detail is one click away rather than always open, like the flag
  // chips' disclosure above: a list where every row states its remedy inline
  // is a wall again, and the whole point of the layer is that it can be
  // skimmed. It is never absent — an item with no next step is a bug in the
  // item, which is why the module refuses to produce one.
  //
  // The severity dot and the tag come from the module's own kind table, so
  // the colour of a row and the colour of that client's card cannot
  // disagree.
  let triageRowSeq = 0;
  function buildTriageRow(group) {
    const item = group.items[0];
    const row = document.createElement("li");
    row.className = "reports-triage-row";
    row.setAttribute("data-triage-kind", group.kind);
    row.setAttribute("data-severity", group.severity);

    const detailId = "reports-triage-detail-" + ++triageRowSeq;
    const head = document.createElement("div");
    head.className = "reports-triage-row-head";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "reports-triage-toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", detailId);

    const sig = document.createElement("span");
    sig.className = "reports-triage-sig is-" + group.severity;
    toggle.appendChild(sig);

    const tag = triageItemTag(item);
    if (tag) {
      const chip = document.createElement("span");
      chip.className = "reports-triage-tag is-" + group.severity;
      chip.textContent = tag;
      toggle.appendChild(chip);
    }

    // Who it covers, named. Registry-controlled text — textContent, never
    // markup (#533).
    const who = document.createElement("span");
    who.className = "reports-triage-client";
    who.textContent = group.clients
      .map(function (c) {
        return c.name || c.slug;
      })
      .join(MUREO.t("dashboard.reports_triage_client_separator"));
    toggle.appendChild(who);

    if (group.clients.length > 1) {
      const count = document.createElement("span");
      count.className = "reports-count-badge";
      count.textContent = MUREO.t("dashboard.reports_triage_count", {
        n: group.clients.length,
      });
      toggle.appendChild(count);
    }

    // What it says, on ONE line, clipped by the stylesheet. A row is a thing
    // to skim; the sentence wrapping to three lines was most of the height
    // an operator complained about. The full text of every item on the row
    // is in the disclosure below, and the `title` puts this one a hover
    // away — the clip never has to be the only copy.
    const summary = document.createElement("span");
    summary.className = "reports-triage-summary";
    // Writer-supplied text (a collection-failure reason out of STATE.json, a
    // registry-controlled platform key) — text, never markup.
    summary.textContent = triageItemText(item);
    summary.title = summary.textContent;
    toggle.appendChild(summary);
    head.appendChild(toggle);

    // Closing a row is every message on it — the message-level control
    // below applied to each, which is the only reading that keeps the two
    // consistent. It is a VIEW operation and says so: the count above does
    // not move, the clients' cards stay marked, and "N hidden" appears
    // under the list with the way back. See renderTriageDismissed.
    const close = document.createElement("button");
    close.type = "button";
    close.className = "reports-triage-dismiss";
    close.setAttribute(
      "aria-label",
      MUREO.t("dashboard.reports_triage_dismiss_group", {
        what: tag,
        n: group.items.length,
      })
    );
    close.textContent = "✕";
    close.addEventListener("click", function () {
      dismissTriageGroup(group);
      renderReportsTriage(reportsTriageBuilt);
    });
    head.appendChild(close);
    row.appendChild(head);

    const detail = document.createElement("div");
    detail.className = "reports-triage-detail";
    detail.id = detailId;
    const open = !!reportsTriageOpenKinds[group.kind];
    detail.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    const list = document.createElement("ul");
    list.className = "reports-triage-detail-list";
    group.items.forEach(function (item) {
      const line = document.createElement("li");
      line.className = "reports-triage-detail-row";
      const name = document.createElement("span");
      name.className = "reports-triage-client";
      name.textContent = item.name || item.slug;
      line.appendChild(name);
      const what = document.createElement("span");
      what.className = "reports-triage-what";
      // Writer-supplied text (a collection-failure reason out of STATE.json,
      // a registry-controlled platform key) is interpolated into this
      // sentence, so it is set as text and never as markup.
      what.textContent = triageItemText(item);
      line.appendChild(what);
      // …and its own ✕. A row can cover six clients, and closing the KIND
      // would take five findings the operator never read with it. The row's
      // count and the clients it names shrink as these go; the row goes
      // when the last of them does.
      const drop = document.createElement("button");
      drop.type = "button";
      drop.className = "reports-triage-dismiss";
      drop.setAttribute(
        "aria-label",
        MUREO.t("dashboard.reports_triage_dismiss", {
          client: item.name || item.slug,
          what: tag,
        })
      );
      drop.textContent = "✕";
      drop.addEventListener("click", function () {
        dismissTriageItem(item);
        renderReportsTriage(reportsTriageBuilt);
      });
      line.appendChild(drop);
      list.appendChild(line);
    });
    detail.appendChild(list);

    // What to run. One per row because every item on it is the same kind,
    // and the kind is what decides the next step.
    const next = triageItemNextStep(item);
    if (next) {
      const step = document.createElement("p");
      step.className = "reports-triage-next";
      step.textContent = next;
      detail.appendChild(step);
    }
    row.appendChild(detail);
    toggle.addEventListener("click", function () {
      const show = detail.hidden;
      detail.hidden = !show;
      reportsTriageOpenKinds[group.kind] = show;
      toggle.setAttribute("aria-expanded", show ? "true" : "false");
    });
    return row;
  }

  // ------------------------------------------------------------------
  // The portfolio strip, the health filter and the platform split
  // ------------------------------------------------------------------

  // One cell of the strip: a label, a figure, and the coverage under it.
  //
  // A figure the module could state over NO client renders as "—" with the
  // reason spelled out, never as a bare dash and never as 0. That is the
  // rule the whole Reports view is built on (#638), and a roster total is
  // the easiest place to break it: every client whose totals are withheld
  // would otherwise be summed in as nothing.
  function buildPortfolioCell(labelKey, text, note, full) {
    const cell = document.createElement("div");
    cell.className = "reports-kpi";
    const label = document.createElement("span");
    label.className = "reports-kpi-label";
    label.textContent = MUREO.t(labelKey);
    cell.appendChild(label);
    const value = document.createElement("span");
    value.className = "reports-kpi-value";
    value.textContent = text;
    cell.appendChild(value);
    // The note is ONE clipped line: four cells each carrying a wrapped
    // sentence is a strip taller than the alerts under it. The whole
    // sentence stays reachable on the cell as a title — it is the half of
    // the figure that says whose numbers are in it, so it is shortened,
    // never dropped.
    const foot = document.createElement("span");
    foot.className = "reports-kpi-note";
    foot.textContent = note;
    if (full) cell.title = full;
    cell.appendChild(foot);
    return cell;
  }

  // A money cell: the figure when at least one client stated it, and how
  // many clients that was whenever it was not all of them.
  function buildPortfolioFigureCell(labelKey, figure, total, format) {
    const stated = figure && typeof figure.stated === "number" ? figure.stated : 0;
    const value = figure ? figure.value : null;
    const params = { stated: stated, total: total };
    const short =
      value == null
        ? "dashboard.reports_portfolio_unstated_short"
        : stated < total
          ? "dashboard.reports_portfolio_coverage_short"
          : "";
    const full =
      value == null
        ? "dashboard.reports_portfolio_unstated"
        : stated < total
          ? "dashboard.reports_portfolio_coverage"
          : "";
    return buildPortfolioCell(
      labelKey,
      value != null ? format(value) : "—",
      short ? MUREO.t(short, params) : "",
      full ? MUREO.t(full, params) : ""
    );
  }

  // The strip above the alerts: what the roster spent and converted, what it
  // paid per conversion, and how many of its clients need attention.
  //
  // Rendered only for the index — a roster total sitting above one client's
  // report reads as that client's — and only when there is a roster: an
  // empty grid gets no strip rather than four dashes.
  function renderReportsPortfolio(portfolio, triage) {
    const strip = document.querySelector("[data-reports-kpis]");
    if (!strip) return;
    strip.textContent = "";
    strip.hidden = !portfolio.total;
    if (!portfolio.total) return;
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_spend",
        portfolio.spend,
        portfolio.total,
        formatNumber
      )
    );
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_conversions",
        portfolio.conversions,
        portfolio.total,
        formatNumber
      )
    );
    strip.appendChild(
      buildPortfolioFigureCell(
        "dashboard.reports_kpi_cpa",
        portfolio.cpa,
        portfolio.total,
        function (value) {
          return formatNumber(Math.round(value));
        }
      )
    );
    // The one cell that is never withheld: it counts findings mureo raised
    // itself, not figures it collected. It reads the same array as the alert
    // list's heading and the grid's marks.
    const marked = triage && Array.isArray(triage.clients) ? triage.clients : [];
    const counts = triageHealthCounts(triage, portfolio.total);
    strip.appendChild(
      buildPortfolioCell(
        "dashboard.reports_portfolio_attention",
        formatNumber(marked.length),
        MUREO.t("dashboard.reports_portfolio_health_note", {
          attention: counts.attention,
          watch: counts.watch,
        })
      )
    );
  }

  // Which health the grid is filtered to. "all" until the operator says
  // otherwise, and reset on every index render: a filter that survived a
  // re-render would leave cards missing with no visible reason.
  let reportsHealthFilter = "all";

  // Show only the cards at the selected health. The cards are hidden, never
  // removed: the grid is also the operator's own card order (#556), and
  // rebuilding it from a filtered list would reorder it.
  function applyReportsHealthFilter() {
    const wrap = document.querySelector("[data-reports-clients]");
    if (!wrap) return;
    Array.prototype.forEach.call(wrap.children, function (item) {
      const health = item.getAttribute("data-health");
      if (!health) return;
      item.hidden = reportsHealthFilter !== "all" && health !== reportsHealthFilter;
    });
    const chips = document.querySelectorAll("[data-reports-filter]");
    Array.prototype.forEach.call(chips, function (chip) {
      const active = chip.getAttribute("data-reports-filter") === reportsHealthFilter;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  // The health chips over the grid. Each carries its own count, so the
  // operator can see there are three clients needing attention without
  // clicking, and a chip whose count is zero is still rendered — a filter
  // that appears and disappears is harder to use than one that says "0".
  const REPORTS_HEALTH_FILTERS = [
    ["all", "dashboard.reports_filter_all"],
    ["attention", "dashboard.reports_health_attention"],
    ["watch", "dashboard.reports_health_watch"],
    ["ok", "dashboard.reports_health_ok"],
  ];

  function renderReportsFilters(counts) {
    const wrap = document.querySelector("[data-reports-filters]");
    if (!wrap) return;
    wrap.textContent = "";
    // Nothing to filter with one card, and nothing to filter with none.
    wrap.hidden = counts.all < 2;
    if (wrap.hidden) return;
    REPORTS_HEALTH_FILTERS.forEach(function (row) {
      const key = row[0];
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "reports-filter-chip";
      chip.setAttribute("data-reports-filter", key);
      if (key !== "all") {
        const dot = document.createElement("span");
        dot.className = "reports-filter-dot is-" + key;
        chip.appendChild(dot);
      }
      const label = document.createElement("span");
      label.textContent = MUREO.t(row[1]);
      chip.appendChild(label);
      const count = document.createElement("span");
      count.className = "reports-filter-count";
      count.textContent = formatNumber(counts[key]);
      chip.appendChild(count);
      chip.addEventListener("click", function () {
        reportsHealthFilter = key;
        applyReportsHealthFilter();
      });
      wrap.appendChild(chip);
    });
    applyReportsHealthFilter();
  }

  // One bar of a platform split: the coloured slice, sized by its share.
  //
  // The colour is chosen from the platform KEY (reports_overview.js), so the
  // same platform is the same colour on every card and in the panel — the
  // split is ranked by spend, and a colour that followed the ranking would
  // change from card to card.
  function buildPlatformSlice(row, className) {
    const slice = document.createElement("span");
    slice.className = className + " is-platform-" + platformColorSlot(row.key);
    slice.style.width = (row.share * 100).toFixed(2) + "%";
    return slice;
  }

  // The roster's spend by platform, beside the grid. Hidden entirely when no
  // client's totals could be stated — an empty panel of zero-width bars says
  // nothing, and a panel of bars drawn from withheld figures says something
  // false.
  function renderReportsPlatforms(portfolio) {
    const panel = document.querySelector("[data-reports-platforms]");
    const rows = document.querySelector("[data-reports-platform-rows]");
    const note = document.querySelector("[data-reports-platform-note]");
    if (!panel || !rows) return;
    rows.textContent = "";
    panel.hidden = !portfolio.platforms.length;
    if (panel.hidden) return;
    portfolio.platforms.forEach(function (row) {
      const line = document.createElement("div");
      line.className = "reports-platform-row";
      const name = document.createElement("span");
      name.className = "reports-platform-name";
      // Registry / plugin-controlled display name — text, never markup.
      name.textContent = row.label;
      line.appendChild(name);
      const track = document.createElement("span");
      track.className = "reports-platform-track";
      track.appendChild(buildPlatformSlice(row, "reports-platform-bar"));
      line.appendChild(track);
      const value = document.createElement("span");
      value.className = "reports-platform-value";
      value.textContent = formatNumber(Math.round(row.spend));
      line.appendChild(value);
      rows.appendChild(line);
    });
    // The panel is a sum over other people's numbers, so it says whose.
    if (note) {
      const stated = portfolio.spend.stated;
      note.textContent =
        stated < portfolio.total
          ? MUREO.t("dashboard.reports_portfolio_coverage", {
              stated: stated,
              total: portfolio.total,
            })
          : "";
      note.hidden = !note.textContent;
    }
  }

  // What mureo did today, across the roster — the rail's top panel.
  //
  // A day with nothing logged renders NO panel: the same default silence the
  // alert layer keeps, and for the same reason. "0 actions today" is a frame
  // competing for attention with the sections that do have something in it,
  // and on a rail it would push the platform split below the fold to say so.
  //
  // Nothing here decides what "today" is — reports_overview.js does, from the
  // date the SERVER stated, which a static pin could never check.
  function renderReportsActionFeed(feed) {
    const panel = document.querySelector("[data-reports-feed]");
    const list = document.querySelector("[data-reports-feed-list]");
    const count = document.querySelector("[data-reports-feed-count]");
    const more = document.querySelector("[data-reports-feed-more]");
    if (!panel || !list) return;
    list.textContent = "";
    panel.hidden = !feed.items.length;
    if (!feed.items.length) return;
    if (count) {
      count.textContent = MUREO.t("dashboard.reports_feed_count", { n: feed.total });
    }
    feed.items.forEach(function (item) {
      list.appendChild(buildReportsFeedRow(item));
    });
    if (more) {
      more.textContent = feed.remaining
        ? MUREO.t("dashboard.reports_feed_more", { n: feed.remaining })
        : "";
      more.hidden = !feed.remaining;
    }
  }

  // One line of the feed: when, for whom, what.
  //
  // The client name is a button that opens that client's report — the feed
  // says a thing happened to somebody, and "show me" is the only follow-up
  // it can offer. It is a real button so the keyboard reaches it, and it
  // sits OUTSIDE nothing: the row itself is not interactive.
  function buildReportsFeedRow(item) {
    const row = document.createElement("li");
    row.className = "reports-feed-row";

    const time = document.createElement("span");
    time.className = "reports-feed-time";
    // Sliced out of the server's own timestamp by reports_overview.js — not
    // reformatted here, which would render it in the browser's timezone.
    time.textContent = item.time;
    row.appendChild(time);

    const dot = document.createElement("span");
    dot.className = "reports-feed-dot";
    row.appendChild(dot);

    const body = document.createElement("span");
    body.className = "reports-feed-body";
    const who = document.createElement("button");
    who.type = "button";
    who.className = "reports-feed-client";
    // Registry-controlled text — textContent, never markup (#533).
    who.textContent = item.name;
    who.addEventListener("click", function () {
      REPORTS_VIEW_STATE.reportsActiveClient = item.slug;
      showReportsClientDetail(item.slug);
    });
    body.appendChild(who);
    const what = document.createElement("span");
    what.className = "reports-feed-text";
    // Writer-supplied text out of STATE.json's action log — text, not markup.
    what.textContent = item.text;
    body.appendChild(what);
    // …and clamped to two lines by the stylesheet, with the whole sentence
    // here. A real `summary` runs to several hundred characters, and one of
    // them turned this rail back into the wall of prose the index was
    // redesigned to end. Nothing is lost by it: the string is unaltered, it
    // is complete on this attribute, and the action log is rendered in full
    // on the client's own detail view. mureo's "never truncate silently"
    // rule is about a stored VALUE it would be changing; how many lines of
    // an unchanged string a 340px rail shows is a display decision, and the
    // alert rows above make the same one at one line.
    body.title = item.text;
    row.appendChild(body);
    return row;
  }

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
    reportsHealthFilter = "all";
    reportsTriageShowAll = false;
    reportsTriageOpenKinds = {};
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
    buildPlatformSlice: buildPlatformSlice,
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
