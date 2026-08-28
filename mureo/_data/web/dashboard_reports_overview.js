// dashboard_reports_overview.js — what the whole roster says, above the grid.
//
// Split out of dashboard_reports.js (#687). Nothing here changed in the move
// beyond the bindings at the top.
//
// The DOM half of reports_overview.js. Four blocks, and they share one
// property that makes them worth keeping together: every figure on this row
// is a sum over OTHER clients' numbers, which is the easiest place in the
// product to hide one mureo cannot vouch for.
//
//   - the portfolio cells: what the roster spent, converted, and paid per
//     conversion. A figure here is never just a number — it carries how many
//     clients it was stated over, and it is absent rather than 0 when that
//     count is zero (#636, #638).
//   - the health filter chips, which count every card including the ones they
//     hide, so the counts do not change as the operator filters.
//   - the platform split bar, coloured by platform KEY rather than by
//     position, so a colour means the same thing on every card.
//   - the action feed, whose "today" comes from the host's clock via
//     `server_today` and never from the browser's.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_OVERVIEW`. Loads AFTER
// dashboard_reports_report.js and BEFORE dashboard_reports_cards.js, which
// binds `buildPlatformSlice` from it.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_overview.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_overview.js"
    );
  }
  const formatNumber = REPORTS_SHARED.formatNumber;
  const platformColorSlot = REPORTS_SHARED.platformColorSlot;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

  // Defined in dashboard_reports.js, which loads AFTER this file, so each name is
  // resolved when a card is clicked rather than at load. That is what
  // keeps the call sites below reading as they always did.
  function indexPeer() {
    const api = typeof window !== "undefined" ? window.MUREO_DASHBOARD_REPORTS : null;
    if (!api) {
      throw new Error(
        "MUREO_DASHBOARD_REPORTS (dashboard_reports.js) is missing — its <script> tag " +
          "must come AFTER dashboard_reports_overview.js in app.html."
      );
    }
    return api;
  }

  function showReportsClientDetail(slug) {
    return indexPeer().showReportsClientDetail(slug);
  }

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
  //
  // `counts` is the render's health split, handed in rather than rebuilt
  // here (#715). This strip used to call `triageHealthCounts` itself, which
  // re-scanned the whole alert layer once per client for an object the index
  // already held — and, worse, made "the band, the chips and the strip are
  // one answer" a claim about two objects that merely agreed.
  function renderReportsPortfolio(portfolio, triage, counts) {
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
    // Defensive about the argument, not a fallback that recomputes it: a
    // second count here is exactly what this change removed, so a missing
    // one prints zeros rather than quietly reintroducing a second answer.
    const split = counts && typeof counts === "object" ? counts : {};
    strip.appendChild(
      buildPortfolioCell(
        "dashboard.reports_portfolio_attention",
        formatNumber(marked.length),
        MUREO.t("dashboard.reports_portfolio_health_note", {
          attention: split.attention || 0,
          watch: split.watch || 0,
        })
      )
    );
  }

  /**
   * The line under the band: mureo could not check n of these clients (#714).
   *
   * WHAT IT IS NOT. Not a health state, not a fifth block, and not red. The
   * three status colours are reserved for what a client's ADS are doing —
   * "anything that is merely informational stays neutral", which app.css
   * states as a rule at the tokens themselves, and a fourth colour would make
   * the first three mean less. This line says nothing about an ad account: it
   * says mureo's own request did not come back, which is a fact about mureo.
   *
   * Painting it as any verdict lies in one direction or another — "not
   * running" about an account nobody checked, "needs attention" turning the
   * whole roster red the moment the daemon restarts, "nothing raised"
   * claiming a check that did not happen. So the clients keep the bucket they
   * had and this sentence is added beside them.
   *
   * NO EMPTY FRAME. When every summary arrived there is no line, no border
   * and no reserved height — an empty box on a screen that is fine would be a
   * permanent hint that something might not be. The text is cleared as well
   * as hidden, so a line drawn while the daemon was down cannot survive into
   * the render where it came back.
   */
  function renderReportsUnreachable(unreachable) {
    const note = document.querySelector("[data-reports-unreachable]");
    if (!note) return;
    const state =
      unreachable && typeof unreachable === "object" ? unreachable : {};
    const count =
      typeof state.count === "number" && state.count > 0
        ? Math.floor(state.count)
        : 0;
    note.textContent = "";
    note.hidden = !(state.show && count);
    if (note.hidden) return;
    note.textContent = MUREO.t("dashboard.reports_unreachable", { n: count });
  }

  // Show only the cards at the selected health. The cards are hidden, never
  // removed: the grid is also the operator's own card order (#556), and
  // rebuilding it from a filtered list would reorder it.
  function applyReportsHealthFilter() {
    // Every roster row, in WHICHEVER view is on screen: the card grid's items
    // and the table's rows both carry `data-health`, so one implementation
    // hides both (#691 phase 3). Two would drift the moment one of them
    // learned about a state the other did not.
    //
    // It also applies the client-name search, and that is deliberate rather
    // than lazy: `hidden` on these rows has exactly one owner. Two functions
    // both writing it would each undo the other's work depending on which ran
    // last, which is the bug shape #665 is about.
    const rows = document.querySelectorAll("[data-health]");
    const search = document.querySelector("[data-reports-client-search]");
    const query =
      search && search.value ? String(search.value).trim().toLowerCase() : "";
    // Counted over the rows the SEARCH can act on — the ones carrying a name
    // hook. Both views' rows are in the DOM at once (the cards are built
    // whether or not they are the view on screen), and the card grid carries
    // no name, so counting those would mean an emptied search never looked
    // empty.
    let searchable = 0;
    let shown = 0;
    Array.prototype.forEach.call(rows, function (item) {
      const health = item.getAttribute("data-health");
      if (!health) return;
      const name = (item.getAttribute("data-client-name") || "").toLowerCase();
      const wrongHealth =
        REPORTS_VIEW_STATE.reportsHealthFilter !== "all" &&
        health !== REPORTS_VIEW_STATE.reportsHealthFilter;
      const missed = query && name && name.indexOf(query) === -1;
      item.hidden = wrongHealth || !!missed;
      if (!name) return;
      searchable += 1;
      if (!item.hidden) shown += 1;
    });
    const empty = document.querySelector("[data-reports-search-empty]");
    if (empty) empty.hidden = !(query && searchable > 0 && shown === 0);
    // The table's totals row sums what is on screen, so the thing that just
    // changed what is on screen has to say so. Resolved at call time:
    // dashboard_reports_table.js loads AFTER this file, and this is the same
    // backwards edge every other pair in the family uses.
    const table =
      typeof window !== "undefined" ? window.MUREO_DASHBOARD_REPORTS_TABLE : null;
    if (table) table.refreshTotals();
    const chips = document.querySelectorAll("[data-reports-filter]");
    Array.prototype.forEach.call(chips, function (chip) {
      const active =
        chip.getAttribute("data-reports-filter") ===
        REPORTS_VIEW_STATE.reportsHealthFilter;
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
        REPORTS_VIEW_STATE.reportsHealthFilter = key;
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
  // ON A ROSTER (`rostered`, two clients or more) the panel is always there,
  // and a day with nothing logged says so in one line. That is the one place
  // the list screen keeps a frame over no data, and it is deliberate: on a
  // roster the rail is where an operator looks to see mureo working, and an
  // absent panel and a quiet day are indistinguishable from each other —
  // "did nothing happen, or is this broken?" is the question the line
  // answers. It is one line, so it costs the platform split nothing.
  //
  // BELOW THAT the behaviour is unchanged: no panel at all. A single-client
  // index (every client but one archived) is not a roster, and the same
  // default silence the alert layer keeps applies.
  //
  // Nothing here decides what "today" is — reports_overview.js does, from the
  // date the SERVER stated, which a static pin could never check.
  function renderReportsActionFeed(feed, rostered) {
    const panel = document.querySelector("[data-reports-feed]");
    const list = document.querySelector("[data-reports-feed-list]");
    const count = document.querySelector("[data-reports-feed-count]");
    const more = document.querySelector("[data-reports-feed-more]");
    const empty = document.querySelector("[data-reports-feed-empty]");
    if (!panel || !list) return;
    list.textContent = "";
    panel.hidden = !feed.items.length && !rostered;
    if (empty) empty.hidden = !!feed.items.length;
    if (!feed.items.length) {
      if (count) count.textContent = "";
      if (more) {
        more.textContent = "";
        more.hidden = true;
      }
      return;
    }
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
    // ONE line, and which one is the ENTRY's decision (#706 step 3-b): the
    // display line where the writer wrote one for a row exactly like this,
    // and the work-journal summary with its markdown emphasis stripped where
    // it predates the contract.
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
    // …and the WHOLE line on the attribute, uncut: `item.text` is what fits
    // the rail, `item.full` is what was written.
    body.title = item.full || item.text;
    row.appendChild(body);
    return row;
  }


  const api = {
    buildPlatformSlice: buildPlatformSlice,
    renderReportsPortfolio: renderReportsPortfolio,
    renderReportsUnreachable: renderReportsUnreachable,
    renderReportsFilters: renderReportsFilters,
    applyReportsHealthFilter: applyReportsHealthFilter,
    renderReportsPlatforms: renderReportsPlatforms,
    renderReportsActionFeed: renderReportsActionFeed,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_OVERVIEW = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
