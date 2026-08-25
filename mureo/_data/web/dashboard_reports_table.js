// dashboard_reports_table.js — the agency roster as a dense table (#691).
//
// A card grid answers "how is this client doing?" one client at a time. Past
// a handful of clients the question changes to "which of these do I open
// first?", and a grid answers that badly: the figures sit in different places
// on every card, so comparing two of them is a search rather than a glance.
// A table puts one metric in one column, which is the whole of what it is
// for.
//
// WHO GETS IT. Two or more visible clients — the agency seam's own answer,
// read off the roster this file is handed rather than re-derived. A
// single-workspace OSS install never reaches the index at all, and a roster
// that is down to one visible client keeps the cards: a one-row table is a
// worse card.
//
// The cards stay, as a toggle, and the choice is remembered per browser. It
// is a preference about how somebody reads, not a fact about the data, so it
// belongs in localStorage and not on the wire.
//
// WHAT THIS FILE DOES NOT DECIDE. Not one health verdict and not one figure.
// Which clients are in trouble is reports_triage.js's ranking, handed in as
// `health` per row; every number comes from the same `aggregateClientKpis`
// the cards use. A table that re-derived either would be a second opinion on
// screen at the same time as the first.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_TABLE`. Loads AFTER
// dashboard_reports_state.js and BEFORE dashboard_reports.js, which calls it.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so
  // every call site below reads exactly as it does elsewhere.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_table.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_table.js"
    );
  }
  const relativeAge = REPORTS_SHARED.relativeAge;
  const formatKpi = REPORTS_SHARED.formatKpi;
  const formatNumber = REPORTS_SHARED.formatNumber;
  const aggregateClientKpis = REPORTS_SHARED.aggregateClientKpis;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // dashboard_reports_overview.js owns `hidden` on every roster row —
  // both views' — so the table asks it to re-apply rather than keeping a
  // second copy of the rule. Its <script> tag comes first.
  const REPORTS_OVERVIEW_UI = window.MUREO_DASHBOARD_REPORTS_OVERVIEW;
  if (!REPORTS_OVERVIEW_UI) {
    throw new Error(
      "dashboard_reports_table.js needs MUREO_DASHBOARD_REPORTS_OVERVIEW — " +
        "load dashboard_reports_overview.js BEFORE dashboard_reports_table.js"
    );
  }
  const applyReportsHealthFilter = REPORTS_OVERVIEW_UI.applyReportsHealthFilter;

  // Opening a client is dashboard_reports.js's, and that file loads AFTER
  // this one, so the name is resolved when a row is clicked rather than at
  // load — the pattern every backwards edge in this family uses.
  function showReportsClientDetail(slug) {
    const api = typeof window !== "undefined" ? window.MUREO_DASHBOARD_REPORTS : null;
    if (!api) {
      throw new Error(
        "MUREO_DASHBOARD_REPORTS (dashboard_reports.js) is missing — its " +
          "<script> tag must come AFTER dashboard_reports_table.js."
      );
    }
    return api.showReportsClientDetail(slug);
  }

  // Below this many visible clients the grid is the better view, so the
  // toggle is not offered and the table is not built. Two, because the
  // comparison a table exists for needs two things to compare.
  const ROSTER_TABLE_MIN = 2;

  //: Where the operator's choice of view is remembered. Per browser, like the
  //: alert list's dismissals — it is a preference about reading, not a fact
  //: about the workspace, so it never goes on the wire.
  const ROSTER_VIEW_KEY = "mureo.reports.roster_view";

  // Status first, and this order is the argument the table makes: the rows
  // an operator must act on are the rows they should see without scrolling.
  const HEALTH_RANK = { attention: 0, watch: 1, ok: 2 };

  // Above this ratio a client's CPA is not merely over target, it is over by
  // enough to read as a finding. Below it the bar still shows the overshoot;
  // this only decides when the figure itself turns red.
  const CPA_RATIO_ALERT = 1.2;

  /** The view the operator last chose, or null when they never have. */
  function readRosterView() {
    try {
      const raw = window.localStorage.getItem(ROSTER_VIEW_KEY);
      return raw === "table" || raw === "cards" ? raw : null;
    } catch (_e) {
      return null; // storage unavailable — fall back to the default
    }
  }

  function writeRosterView(view) {
    try {
      window.localStorage.setItem(ROSTER_VIEW_KEY, view);
    } catch (_e) {
      // A browser that refuses storage still gets the toggle, it just does
      // not remember it. Never throw out of a click handler.
    }
  }

  /**
   * Which view this roster should open on.
   *
   * The stored choice wins when there is one AND the table is available at
   * all — a remembered "table" must not resurrect a table for a roster that
   * has shrunk to one client.
   */
  function rosterViewFor(count) {
    if (count < ROSTER_TABLE_MIN) return "cards";
    return readRosterView() || "table";
  }

  /**
   * One row's worth of figures, from the same aggregate the cards use.
   *
   * `null` for a figure means mureo will not state it, which is not the same
   * as zero and is rendered as neither. `cpaRatio` is null unless the client
   * carries BOTH a CPA and a target to compare it against.
   */
  function rosterRow(client, summary, health) {
    const kpis = aggregateClientKpis(summary) || {};
    const totals = kpis.hasFigures ? kpis : {};
    const cpa = num(totals.cpa);
    const target = targetCpaOf(summary);
    return {
      slug: (client && client.slug) || "",
      name: (client && (client.name || client.slug)) || "",
      health: health || "ok",
      spend: num(totals.spend),
      cpa: cpa,
      conversions: num(totals.conversions),
      ctr: num(totals.ctr),
      updated: (summary && summary.last_synced_at) || null,
      targetCpa: target,
      cpaRatio: cpa !== null && target ? cpa / target : null,
      // A CPA needs a conversion to divide by. Zero conversions is not a CPA
      // of zero and not a missing figure either — it is a division that
      // cannot be done, and the row says so in words.
      cpaUnavailable: cpa === null && totals.conversions === 0,
    };
  }

  function num(value) {
    return typeof value === "number" && isFinite(value) ? value : null;
  }

  /**
   * The client's target CPA, or null.
   *
   * NOTHING on the reports wire carries one today — no field on the summary,
   * and STRATEGY.md's guardrails do not reach any web payload. So this reads
   * the one place a target could appear and returns null for every real
   * install, which is why the ratio column is omitted rather than drawn
   * empty (see buildRosterTable).
   *
   * It is written this way, rather than left out, because the column is in
   * the approved design and the ONLY thing missing is the datum. When a
   * target does reach the summary this lights up with no further work — and
   * until then nothing invents one.
   */
  function targetCpaOf(summary) {
    const goals = summary && summary.goals;
    const target = goals && goals.target_cpa;
    return typeof target === "number" && isFinite(target) && target > 0
      ? target
      : null;
  }

  /** The comparator for one column, or the status default. */
  function compareRows(a, b, key, dir) {
    const sign = dir === "desc" ? -1 : 1;
    if (key === "status") {
      const rank = HEALTH_RANK[a.health] - HEALTH_RANK[b.health];
      // Within a status group, the biggest spender first — the client whose
      // money is most at stake is the one to look at first.
      if (rank !== 0) return rank * sign;
      return (b.spend || 0) - (a.spend || 0);
    }
    if (key === "name") return a.name.localeCompare(b.name) * sign;
    if (key === "updated") {
      return (Date.parse(a.updated || "") || 0) > (Date.parse(b.updated || "") || 0)
        ? sign
        : -sign;
    }
    // Numeric columns. A figure mureo will not state sorts last in both
    // directions: "unknown" is not a small number, and letting it float to
    // the top of an ascending sort would put the least informative rows
    // where the most urgent ones belong.
    const av = a[key];
    const bv = b[key];
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return (av - bv) * sign;
  }

  function sortRows(rows, sort) {
    const copy = rows.slice();
    copy.sort(function (a, b) {
      return compareRows(a, b, sort.key, sort.dir);
    });
    return copy;
  }

  // Column definitions: the key sorted on, its label, and whether it is a
  // figure (right-aligned, tabular).
  const COLUMNS = [
    { key: "status", label: "dashboard.reports_col_client", numeric: false },
    { key: "spend", label: "dashboard.reports_kpi_spend", numeric: true },
    { key: "cpa", label: "dashboard.reports_kpi_cpa", numeric: true },
    { key: "cpaRatio", label: "dashboard.reports_col_cpa_ratio", numeric: true },
    { key: "conversions", label: "dashboard.reports_kpi_conversions", numeric: true },
    { key: "ctr", label: "dashboard.reports_kpi_ctr", numeric: true },
    { key: "updated", label: "dashboard.reports_col_updated", numeric: true },
  ];

  function cell(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  /** The CPA-vs-target cell: a bar with the target marked, and the ratio. */
  function buildRatioCell(row) {
    const td = cell("td", "roster-ratio-cell");
    const wrap = cell("div", "roster-ratio");
    if (row.cpaRatio === null) {
      // No target, or no CPA to compare. Either way there is no ratio, and a
      // bar drawn without one would be a claim about a target nobody set.
      // Plain "—": the reason a CPA is missing is stated once, on the CPA
      // cell, and repeating it here would say it twice on the same row.
      wrap.appendChild(cell("b", "roster-ratio-value is-void", "—"));
      td.appendChild(wrap);
      return td;
    }
    const pct = Math.round(row.cpaRatio * 100);
    const tone = pct >= CPA_RATIO_ALERT * 100 ? "is-alert" : pct > 100 ? "is-watch" : "is-ok";
    const track = cell("div", "roster-ratio-track");
    const fill = cell("div", "roster-ratio-fill " + tone);
    // The bar is scaled so the target sits at two thirds of the track, which
    // leaves room to SEE an overshoot rather than pinning every over-target
    // client at 100% width.
    fill.style.width = Math.min(100, (row.cpaRatio / 1.5) * 100) + "%";
    const mark = cell("div", "roster-ratio-target");
    mark.style.left = (100 / 1.5) + "%";
    track.appendChild(fill);
    track.appendChild(mark);
    wrap.appendChild(track);
    wrap.appendChild(cell("b", "roster-ratio-value " + tone, pct + "%"));
    td.appendChild(wrap);
    return td;
  }

  function buildRow(row, withRatio) {
    const tr = document.createElement("tr");
    tr.className = "roster-row is-" + row.health;
    // The same hook the card grid carries, so ONE filter implementation
    // drives both views (#665's discipline: the thing that hides a row is
    // `hidden`, and nothing may give it a display that outranks it).
    tr.setAttribute("data-health", row.health);
    tr.setAttribute("data-client-name", row.name);

    const nameCell = cell("td", "roster-client");
    nameCell.appendChild(cell("span", "roster-dot is-" + row.health));
    nameCell.appendChild(cell("span", "roster-name", row.name));
    tr.appendChild(nameCell);

    tr.appendChild(
      cell("td", "roster-num", row.spend === null ? "—" : formatKpi("spend", row.spend))
    );
    // Two different absences share the "—" glyph and must not be read as the
    // same thing: a withheld CPA (we do not trust the numbers behind it) and
    // one that cannot be divided at all (spend, but zero conversions). The
    // second gets "算出不可" underneath so the row says which it is.
    //
    // This caption used to hang off the CPA-vs-target cell, a column that is
    // dropped whenever no client has a target — which is every install today,
    // so it never actually reached a screen. It belongs here, on the column
    // that always renders.
    const cpaCell = cell(
      "td",
      "roster-num roster-cpa",
      row.cpa === null ? "—" : formatKpi("cpa", Math.round(row.cpa))
    );
    if (row.cpaUnavailable) {
      cpaCell.appendChild(
        cell("small", "roster-note", MUREO.t("dashboard.reports_cpa_unavailable"))
      );
    }
    tr.appendChild(cpaCell);
    if (withRatio) tr.appendChild(buildRatioCell(row));
    tr.appendChild(
      cell(
        "td",
        "roster-num",
        row.conversions === null ? "—" : formatNumber(row.conversions)
      )
    );
    tr.appendChild(
      cell("td", "roster-num", row.ctr === null ? "—" : formatKpi("ctr", row.ctr))
    );
    tr.appendChild(
      cell("td", "roster-updated", row.updated ? relativeAge(row.updated) : "—")
    );

    const go = cell("td", "roster-go");
    const link = document.createElement("button");
    link.type = "button";
    link.className = "roster-go-link";
    link.setAttribute("data-reports-open-client", row.slug);
    link.textContent = MUREO.t("dashboard.reports_detail_link");
    // The same two steps a card click takes, so a client opened from the
    // table and one opened from the grid land in the same place.
    link.addEventListener("click", function () {
      REPORTS_VIEW_STATE.reportsActiveClient = row.slug;
      showReportsClientDetail(row.slug);
    });
    go.appendChild(link);
    tr.appendChild(go);
    return tr;
  }

  /**
   * The totals row.
   *
   * Spend and conversions are sums. CPA is the WEIGHTED average — total spend
   * over total conversions — and not the mean of the per-client CPAs, which
   * would let a client spending ¥12,000 pull the roster figure as hard as one
   * spending ¥128,000.
   *
   * The ratio and CTR columns are "—" on purpose: a roster has no single
   * target to be a ratio against, and averaging CTRs across clients with
   * different impression volumes states a number nobody measured.
   */
  function buildTotals(rows, withRatio, filtered) {
    const tr = document.createElement("tr");
    tr.className = "roster-total";
    let spend = 0;
    let conversions = 0;
    let anySpend = false;
    let anyConv = false;
    let stated = 0;
    rows.forEach(function (r) {
      if (r.spend !== null) {
        spend += r.spend;
        anySpend = true;
      }
      if (r.conversions !== null) {
        conversions += r.conversions;
        anyConv = true;
      }
      // A client mureo will not state figures for adds nothing to any sum
      // above. Counting the ones that DO is what lets the label below say so.
      if (r.spend !== null || r.conversions !== null) stated += 1;
    });
    // Under a filter or a search the row sums what is ON SCREEN, and says so.
    // A total that kept counting the whole roster while two rows were visible
    // is not wrong so much as unreadable: the operator cannot tell which
    // question it answers, and the one they are asking is about the rows they
    // just narrowed to.
    //
    // And when some of those rows are withheld, the label says how many
    // actually contributed. "3 clients" over a figure built from one is the
    // reading the withholding discipline exists to prevent: the point of
    // refusing to state a client's figures is lost if the roster total then
    // presents the remainder as though it covered everybody. Naming the
    // contributing count discloses the gap instead of hiding it.
    //
    // Only when there IS a gap. With every visible client stating figures the
    // count would repeat the number beside it, and a label that restates
    // itself is one an operator stops reading.
    const complete = stated === rows.length;
    const key =
      (filtered
        ? "dashboard.reports_roster_total_shown"
        : "dashboard.reports_roster_total") + (complete ? "" : "_stated");
    // Only the params the chosen string actually interpolates: handing a
    // formatter a value its template ignores is a claim that it matters.
    const params = complete
      ? { n: rows.length }
      : { n: rows.length, stated: stated };
    tr.appendChild(cell("td", "roster-total-label", MUREO.t(key, params)));
    tr.appendChild(
      cell("td", "roster-num", anySpend ? formatKpi("spend", spend) : "—")
    );
    tr.appendChild(
      cell(
        "td",
        "roster-num",
        anySpend && anyConv && conversions > 0
          ? formatKpi("cpa", Math.round(spend / conversions))
          : "—"
      )
    );
    if (withRatio) tr.appendChild(cell("td", "roster-num", "—"));
    tr.appendChild(
      cell("td", "roster-num", anyConv ? formatNumber(conversions) : "—")
    );
    tr.appendChild(cell("td", "roster-num", "—"));
    tr.appendChild(cell("td", "roster-updated", ""));
    tr.appendChild(cell("td", "roster-go", ""));
    return tr;
  }

  function buildHead(sort, withRatio, onSort) {
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    COLUMNS.forEach(function (col) {
      if (col.key === "cpaRatio" && !withRatio) return;
      const th = document.createElement("th");
      th.scope = "col";
      th.className = "roster-head" + (col.numeric ? " roster-num" : "");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "roster-sort";
      button.setAttribute("data-reports-sort", col.key);
      button.appendChild(cell("span", null, MUREO.t(col.label)));
      const active = sort.key === col.key;
      if (active) {
        th.classList.add("is-sorted");
        // The arrow is a character, so the sorted column and its direction
        // survive without the colour that also marks it.
        button.appendChild(
          cell("span", "roster-sort-arrow", sort.dir === "desc" ? "▼" : "▲")
        );
      }
      th.setAttribute("aria-sort", active ? (sort.dir === "desc" ? "descending" : "ascending") : "none");
      button.addEventListener("click", function () {
        onSort(col.key);
      });
      th.appendChild(button);
      tr.appendChild(th);
    });
    const last = document.createElement("th");
    last.scope = "col";
    last.className = "roster-head roster-go";
    last.appendChild(cell("span", "sr-only", MUREO.t("dashboard.reports_col_detail")));
    tr.appendChild(last);
    thead.appendChild(tr);
    return thead;
  }

  /**
   * Build the roster table into `host`, or empty it when the table is not the
   * right view for this roster.
   *
   * Returns true when a table was drawn, so the caller knows whether to show
   * the card grid instead.
   */
  function buildRosterTable(host, clients, summaries, healthOf, sort, onSort) {
    host.textContent = "";
    const rows = clients.map(function (c, i) {
      return rosterRow(c, summaries[i], healthOf(i));
    });
    // The ratio column appears only when at least one client has a target to
    // be measured against. No client does today — nothing on the reports wire
    // carries a target CPA — so this omits the column rather than drawing one
    // that is "—" the whole way down, which would advertise a comparison
    // mureo cannot make. See targetCpaOf.
    const withRatio = rows.some(function (r) {
      return r.targetCpa !== null;
    });
    const table = document.createElement("table");
    table.className = "roster";
    table.appendChild(buildHead(sort, withRatio, onSort));
    const tbody = document.createElement("tbody");
    const ordered = sortRows(rows, sort);
    ordered.forEach(function (row) {
      tbody.appendChild(buildRow(row, withRatio));
    });
    table.appendChild(tbody);
    const tfoot = document.createElement("tfoot");
    tfoot.appendChild(buildTotals(ordered, withRatio, false));
    table.appendChild(tfoot);
    host.appendChild(table);
    // What refreshTotals needs to re-add the visible rows later. `ordered`
    // and `tbody.children` are the same sequence, so which row a <tr> stands
    // for is its position — no lookup by name, which two clients could share.
    drawn = { rows: ordered, withRatio: withRatio, tbody: tbody, tfoot: tfoot };
    return true;
  }

  /**
   * Re-total over the rows still on screen.
   *
   * Called by the filter, which owns `hidden` on these rows and is the only
   * thing that knows a row went away. The totals cannot subscribe to that
   * themselves without keeping a second copy of the filter rule, which is
   * the split-ownership shape #665 is about.
   */
  function refreshTotals() {
    if (!drawn || !drawn.tfoot.parentNode) return;
    const visible = drawn.rows.filter(function (_row, i) {
      const tr = drawn.tbody.children[i];
      return tr && !tr.hidden;
    });
    const filtered = visible.length !== drawn.rows.length;
    drawn.tfoot.textContent = "";
    drawn.tfoot.appendChild(buildTotals(visible, drawn.withRatio, filtered));
  }


  // ------------------------------------------------------------------
  // Which view is on screen, and the toolbar over it
  // ------------------------------------------------------------------

  const SORT_LABELS = {
    status: "dashboard.reports_col_client",
    spend: "dashboard.reports_kpi_spend",
    cpa: "dashboard.reports_kpi_cpa",
    cpaRatio: "dashboard.reports_col_cpa_ratio",
    conversions: "dashboard.reports_kpi_conversions",
    ctr: "dashboard.reports_kpi_ctr",
    updated: "dashboard.reports_col_updated",
  };

  // The roster the last index render built, kept so a re-sort or a view
  // switch can redraw without re-fetching every client's summary.
  let roster = null;
  let sort = { key: "status", dir: "asc" };
  //: The table as last drawn — its row objects in render order, plus the
  //: <tbody>/<tfoot> they were drawn into. Null whenever the cards are the
  //: view on screen, which is what refreshTotals checks before doing work.
  let drawn = null;

  /** Remember the roster and draw whichever view it should open on. */
  function renderRoster(clients, summaries, healthOf) {
    roster = { clients: clients, summaries: summaries, healthOf: healthOf };
    sort = { key: "status", dir: "asc" };
    REPORTS_VIEW_STATE.reportsRosterView = rosterViewFor(clients.length);
    const search = document.querySelector("[data-reports-client-search]");
    // A search left over from a previous render would hide rows with no
    // visible reason — the same rule the health filter resets under.
    if (search) search.value = "";
    drawRoster();
  }

  /** Draw the current view, then re-apply the filters over its rows. */
  function drawRoster() {
    const tools = document.querySelector("[data-reports-roster-tools]");
    const host = document.querySelector("[data-reports-roster-table]");
    const grid = document.querySelector("[data-reports-clients]");
    if (!roster || !host || !grid) return;

    const offered = roster.clients.length >= ROSTER_TABLE_MIN;
    const view = offered ? REPORTS_VIEW_STATE.reportsRosterView : "cards";
    if (tools) tools.hidden = !offered;

    if (view === "table") {
      buildRosterTable(host, roster.clients, roster.summaries, roster.healthOf, sort, onSort);
      host.hidden = false;
      grid.hidden = true;
    } else {
      host.textContent = "";
      host.hidden = true;
      grid.hidden = false;
      drawn = null;
    }
    drawToolbar(offered, view);
    // The table's rows are new nodes on every draw, so a filter or a search
    // the operator set before the switch has to be re-applied to them.
    applyReportsHealthFilter();
  }

  //: Marks the static toolbar controls whose listener is already attached.
  //: They live in app.html rather than being rebuilt per draw, so binding
  //: them on every draw would stack handlers and one click would switch the
  //: view once per render that had happened.
  const wired = new Set();

  function wireOnce(el, type, handler) {
    if (!el || wired.has(el)) return;
    wired.add(el);
    el.addEventListener(type, handler);
  }

  function drawToolbar(offered, view) {
    if (!offered) return;
    const buttons = document.querySelectorAll("[data-reports-view]");
    Array.prototype.forEach.call(buttons, function (b) {
      const active = b.getAttribute("data-reports-view") === view;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
      wireOnce(b, "click", function () {
        setRosterView(b.getAttribute("data-reports-view"));
      });
    });
    const sortedBy = document.querySelector("[data-reports-sorted-by]");
    if (sortedBy) {
      // Only the table has an order worth stating. The grid keeps the
      // operator's own drag order, which is a choice and not a sort.
      sortedBy.hidden = view !== "table";
      sortedBy.textContent =
        sort.key === "status"
          ? MUREO.t("dashboard.reports_sorted_by_status")
          : MUREO.t("dashboard.reports_sorted_by", {
              col: MUREO.t(SORT_LABELS[sort.key] || sort.key),
            });
    }
    const search = document.querySelector("[data-reports-client-search]");
    // The placeholder is this field's only visible label, and app.js's
    // `data-i18n` sweep only replaces text nodes — it has no placeholder
    // mechanism — so it is set here, on every draw, which is also what makes
    // it follow a locale change.
    if (search) {
      search.setAttribute(
        "placeholder",
        MUREO.t("dashboard.reports_search_clients")
      );
    }
    wireOnce(search, "input", applyReportsHealthFilter);
  }

  /** A header click: the same column flips, a new column starts fresh. */
  function onSort(key) {
    sort =
      sort.key === key
        ? { key: key, dir: sort.dir === "asc" ? "desc" : "asc" }
        : { key: key, dir: key === "status" ? "asc" : "desc" };
    drawRoster();
  }

  function setRosterView(view) {
    REPORTS_VIEW_STATE.reportsRosterView = view;
    writeRosterView(view);
    drawRoster();
  }

  const api = {
    ROSTER_TABLE_MIN: ROSTER_TABLE_MIN,
    ROSTER_VIEW_KEY: ROSTER_VIEW_KEY,
    readRosterView: readRosterView,
    writeRosterView: writeRosterView,
    rosterViewFor: rosterViewFor,
    rosterRow: rosterRow,
    sortRows: sortRows,
    compareRows: compareRows,
    buildRosterTable: buildRosterTable,
    renderRoster: renderRoster,
    setRosterView: setRosterView,
    refreshTotals: refreshTotals,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_TABLE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
