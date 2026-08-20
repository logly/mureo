// reports_overview.js — the Reports index view's own decisions.
//
// Two things live here, and both are about the view an operator lands on
// rather than about any one client:
//
//   1. WHICH VIEW the Reports section shows. The reported bug was that the
//      left menu could not get back to the client list: `renderReports()`
//      restored the detail view whenever the selected client was still
//      alive, and the menu re-entered through that same function. The fix
//      is not "always show the index" — the same function re-renders the
//      section on a period switch and on every status refresh, and one that
//      ejected a reader from the detail they were on would be the same bug
//      pointing the other way. What separates the two cases is WHY the
//      render happened, so the caller states it.
//
//   2. THE PORTFOLIO FIGURES above the grid: what the whole roster spent,
//      converted and paid per conversion, and how that spend splits by
//      platform. Every one is a sum over OTHER clients' numbers, which is
//      the easiest place in the product to hide one mureo cannot vouch for:
//      a client whose totals are withheld (#636, #638) would contribute a
//      silent zero and nothing on screen would say so. So a figure here is
//      never just a number — it carries how many clients it was stated
//      over, and it is null rather than 0 when that count is zero.
//
//   3. WHAT MUREO DID TODAY, across the roster. Every client's summary
//      already carries `recent_actions`, and the index fetches all of them
//      in parallel to draw the cards, so the feed costs no request. What the
//      browser cannot do by itself is decide what "today" IS: an action-log
//      `timestamp` is stamped server-side from `server_now` — the HOST's
//      local wall clock — so a browser drawing the boundary with its own
//      clock would list nine hours of yesterday's work as today's for an
//      operator in London reading a Tokyo host. The summary states
//      `server_today`, and the comparison below is between two strings that
//      came from that one clock. No timezone arithmetic happens anywhere.
//
// Not one new fact about an ad account is computed here. Whether a given
// client's totals may be stated at all is reports_logic.js's decision
// (`aggregateClientKpis`), read off the page at call time exactly as
// reports_triage.js reads it — deciding it again here is how a layer and
// the grid it summarises start disagreeing.
//
// Everything here is a plain function: no DOM, no fetch, no module state,
// so `node --test tests/js/` can execute it. A static grep pin cannot catch
// an inverted condition, and every condition below decides what an operator
// is looking at.
//
// Shipping shape is the one every other module in this directory has: a
// plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_REPORTS_OVERVIEW`, loaded before dashboard.js. The
// `module.exports` tail is inert in a browser (`module` is undefined there)
// and is what lets Node require the same bytes the browser gets.

(function () {
  "use strict";

  // The two views the Reports section has. An Agency install has both; a
  // single-workspace (OSS) install has only the detail, because there is no
  // second client to list.
  const REPORTS_VIEW_INDEX = "index";
  const REPORTS_VIEW_DETAIL = "detail";

  // Why a render is happening. The caller knows; nothing about the state
  // afterwards can tell the two apart, which is exactly why the bug was
  // possible at all.
  //
  //   menu     — the operator asked for the Reports section from the left
  //              menu. That is a request for the list, every time.
  //   rerender — the section is already open and is being redrawn: a period
  //              switch, a status refresh, an archive that succeeded. The
  //              operator did not ask to go anywhere.
  const REPORTS_ENTRY_MENU = "menu";
  const REPORTS_ENTRY_RERENDER = "rerender";

  /**
   * The view to show, from why the render happened and what exists.
   *
   * `state`: {entry, currentView, hasIndex, selectionAlive}.
   *
   * Defensive about every argument for the usual reason — this decides a
   * render, and a throw here blanks the whole Reports view. An unrecognised
   * state resolves to the index, the view that is always safe to show.
   */
  function reportsViewToShow(state) {
    const s = state && typeof state === "object" ? state : {};
    // No index exists on a single-workspace install, so nothing — not even
    // the menu — can route to one.
    if (!s.hasIndex) return REPORTS_VIEW_DETAIL;
    // The menu is a request for the list. It outranks a live selection:
    // that is the whole bug.
    if (s.entry === REPORTS_ENTRY_MENU) return REPORTS_VIEW_INDEX;
    // Any other entry is a redraw of what is already on screen. The detail
    // survives it only while its client does — archiving the client on
    // screen returns the operator to the grid rather than leaving them on a
    // report for a client mureo no longer collects.
    if (s.currentView === REPORTS_VIEW_DETAIL && s.selectionAlive) {
      return REPORTS_VIEW_DETAIL;
    }
    return REPORTS_VIEW_INDEX;
  }

  // ------------------------------------------------------------------
  // The portfolio figures above the grid
  // ------------------------------------------------------------------

  // reports_logic.js's decisions — read off the page at call time, for the
  // same reason reports_triage.js does: whether a client's totals may be
  // stated is ONE answer, and this file must not hold a second one.
  function logic() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_LOGIC : null;
    if (!api) {
      throw new Error(
        "reports_overview.js needs MUREO_REPORTS_LOGIC — load reports_logic.js " +
          "BEFORE reports_overview.js"
      );
    }
    return api;
  }

  // reports_format.js's display vocabulary — read off the page at call
  // time, exactly as reports_logic.js is. The feed asks it for one thing:
  // how to render an action NAME when the entry carried no summary of its
  // own, so `budget_update` reaches the operator as "Budget update" rather
  // than as a wire token.
  function format() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_FORMAT : null;
    if (!api) {
      throw new Error(
        "reports_overview.js needs MUREO_REPORTS_FORMAT — load " +
          "reports_format.js BEFORE reports_overview.js"
      );
    }
    return api;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  // A cross-client figure and the coverage that makes it readable.
  //
  // `value` is null — never 0 — when no client stated it. The distinction is
  // the whole point: "nothing was spent" and "mureo cannot say what was
  // spent" are different answers, and #638 was the second rendered as the
  // first.
  function figure(sum, stated) {
    return { value: stated > 0 ? sum : null, stated: stated };
  }

  // The rows of one client's summary that carry a spend mureo may state.
  //
  // Empty when the client's totals are withheld: the bar would be drawn
  // from exactly the rows the card refuses to add up, and drawing their
  // shares is the same claim as printing their sum.
  function statedPlatformRows(summary) {
    const L = logic();
    const kpis = L.aggregateClientKpis(summary);
    if (kpis.spend == null) return [];
    const rows = summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    return rows.filter(function (row) {
      return row && row.totals && isNumber(row.totals.spend);
    });
  }

  // [{key, label, spend, share}] ranked by spend, largest first.
  //
  // `share` is of the spend IN THIS SPLIT, so the slices always add to one.
  // A total of zero returns nothing at all rather than equal slices of no
  // money, and a platform that stated no spend is absent rather than shown
  // at 0% — an empty slice reads as "this platform ran and spent nothing",
  // which is not what a missing figure means.
  function splitBySpend(rows) {
    const totals = {};
    const order = [];
    rows.forEach(function (row) {
      const key = String(row.key == null ? "" : row.key);
      if (!(key in totals)) {
        totals[key] = { key: key, label: row.display_name || key, spend: 0 };
        order.push(key);
      }
      totals[key].spend += row.totals.spend;
    });
    const sum = order.reduce(function (acc, key) {
      return acc + totals[key].spend;
    }, 0);
    if (!(sum > 0)) return [];
    return order
      .map(function (key) {
        return {
          key: totals[key].key,
          label: totals[key].label,
          spend: totals[key].spend,
          share: totals[key].spend / sum,
        };
      })
      .sort(function (a, b) {
        return b.spend - a.spend;
      });
  }

  // How many colours the platform split has to work with. The palette
  // itself is CSS (`.is-platform-0` … ); this is only how many of them
  // there are, because the slot has to be chosen from the key.
  const REPORTS_PLATFORM_COLOR_SLOTS = 6;

  /**
   * The colour slot a platform key always gets, anywhere it is drawn.
   *
   * From the KEY and not from the row's position: the split is ranked by
   * spend, so a position-based colour would give the same platform a
   * different colour on every card and turn the legend into the only way to
   * read the bar. Any stable function of the key would do; this one is a
   * sum of its code points, which needs no table to maintain.
   */
  function platformColorSlot(key) {
    const text = key == null ? "" : String(key);
    let acc = 0;
    for (let i = 0; i < text.length; i++) {
      acc = (acc + text.charCodeAt(i)) % REPORTS_PLATFORM_COLOR_SLOTS;
    }
    return acc;
  }

  /** One client's own platform split, for its card in the grid. */
  function clientPlatformSplit(summary) {
    return splitBySpend(statedPlatformRows(summary));
  }

  /**
   * The whole roster's figures, for the strip above the grid.
   *
   * `clients` and `summaries` are positionally paired, exactly as
   * renderReportsIndex holds them. Returns {total, spend, conversions, cpa,
   * platforms} — each figure with its own `stated` count, because each is
   * stated over a different set of clients: a client may state its spend and
   * not its conversions, and a CPA needs both from the SAME client (spend
   * from one set over conversions from another is not a cost per anything).
   *
   * Defensive about every argument: this runs mid-render over a payload that
   * may come from an older daemon, and a throw here blanks the Reports view.
   */
  function buildReportsPortfolio(clients, summaries) {
    const rows = Array.isArray(clients) ? clients : [];
    const bodies = Array.isArray(summaries) ? summaries : [];
    const L = logic();
    let spend = 0;
    let spendStated = 0;
    let conversions = 0;
    let conversionsStated = 0;
    let pairedSpend = 0;
    let pairedConversions = 0;
    let pairedStated = 0;
    let platformRows = [];
    rows.forEach(function (_client, index) {
      const summary = bodies[index];
      const kpis = L.aggregateClientKpis(summary);
      if (kpis.spend != null) {
        spend += kpis.spend;
        spendStated += 1;
      }
      if (kpis.conversions != null) {
        conversions += kpis.conversions;
        conversionsStated += 1;
      }
      if (kpis.spend != null && kpis.conversions != null && kpis.conversions > 0) {
        pairedSpend += kpis.spend;
        pairedConversions += kpis.conversions;
        pairedStated += 1;
      }
      platformRows = platformRows.concat(statedPlatformRows(summary));
    });
    return {
      total: rows.length,
      spend: figure(spend, spendStated),
      conversions: figure(conversions, conversionsStated),
      cpa: figure(
        pairedConversions > 0 ? pairedSpend / pairedConversions : 0,
        pairedStated
      ),
      platforms: splitBySpend(platformRows),
    };
  }

  // ------------------------------------------------------------------
  // What mureo did today
  // ------------------------------------------------------------------

  // How many rows the feed shows. It sits in a 340px rail beside the grid,
  // so it is a glance at today rather than the log — the rest is counted,
  // and the whole history is on each client's own detail view.
  const REPORTS_ACTION_FEED_CAP = 6;

  // A `YYYY-MM-DD` the server actually stated, or null.
  //
  // Null is the answer for an older daemon, a proxy that dropped the key,
  // and a single-workspace install (which is never sent it) — and it makes
  // the whole feed empty rather than dated by the browser's clock. Silence
  // is the only safe degradation here: a feed headed "today" listing
  // yesterday is worse than no feed.
  function statedServerDate(summaries) {
    const rows = Array.isArray(summaries) ? summaries : [];
    for (let i = 0; i < rows.length; i++) {
      const value = rows[i] && rows[i].server_today;
      if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return value;
      }
    }
    return null;
  }

  // The date and the clock time an entry's timestamp CARRIES, sliced out of
  // the string rather than parsed.
  //
  // Deliberately not `new Date(ts)`: parsing yields an instant, and turning
  // an instant back into a date or a wall-clock time needs a timezone the
  // browser would have to supply. The string already holds the server's
  // answer — `server_now_iso()` writes the host's local time with its offset
  // — so reading it is both simpler and the only correct thing.
  function stampParts(timestamp) {
    if (typeof timestamp !== "string") return null;
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(timestamp);
    return m ? { date: m[1], time: m[2] } : null;
  }

  // What an action-log row SAYS, in one sentence.
  //
  // The writer's own summary when there is one; failing that the action's
  // name, humanized. An entry with neither is dropped rather than rendered
  // as a blank line with a timestamp beside it.
  function actionText(row) {
    const summary = row && typeof row.summary === "string" ? row.summary.trim() : "";
    if (summary) return summary;
    return format().humanizeFlagWords(row && row.action);
  }

  /**
   * Today's logged actions across the whole roster, newest first.
   *
   * `clients` and `summaries` are positionally paired, exactly as
   * renderReportsIndex holds them. Returns {items, total, remaining} — items
   * capped at REPORTS_ACTION_FEED_CAP, `total` every action that qualified,
   * and `remaining` the ones the cap held back.
   *
   * "Today" is the server's date (see `statedServerDate`), never the
   * browser's. Sorting is on the timestamp STRING: every one of them was
   * written by the same clock in the same format, so lexical order is
   * chronological order and no instant has to be constructed.
   *
   * Defensive about every argument: this runs mid-render over a payload that
   * may come from an older daemon, and a throw here blanks the Reports view.
   */
  function buildReportsActionFeed(clients, summaries) {
    const rows = Array.isArray(clients) ? clients : [];
    const bodies = Array.isArray(summaries) ? summaries : [];
    const today = statedServerDate(bodies);
    if (!today) return { items: [], total: 0, remaining: 0 };
    const items = [];
    rows.forEach(function (client, index) {
      const summary = bodies[index];
      const actions =
        summary && Array.isArray(summary.recent_actions) ? summary.recent_actions : [];
      actions.forEach(function (row) {
        if (!row || typeof row !== "object") return;
        const stamp = stampParts(row.timestamp);
        if (!stamp || stamp.date !== today) return;
        const text = actionText(row);
        if (!text) return;
        items.push({
          index: index,
          slug: (client && client.slug) || "",
          name: (client && (client.name || client.slug)) || "",
          time: stamp.time,
          timestamp: row.timestamp,
          text: text,
        });
      });
    });
    // Newest first. Ties keep the roster's order, which is the operator's
    // own card order — the same tie-break the triage layer uses.
    items.sort(function (a, b) {
      if (a.timestamp === b.timestamp) return a.index - b.index;
      return a.timestamp < b.timestamp ? 1 : -1;
    });
    return {
      items: items.slice(0, REPORTS_ACTION_FEED_CAP),
      total: items.length,
      remaining: Math.max(0, items.length - REPORTS_ACTION_FEED_CAP),
    };
  }

  const api = {
    REPORTS_VIEW_INDEX: REPORTS_VIEW_INDEX,
    REPORTS_VIEW_DETAIL: REPORTS_VIEW_DETAIL,
    REPORTS_ENTRY_MENU: REPORTS_ENTRY_MENU,
    REPORTS_ENTRY_RERENDER: REPORTS_ENTRY_RERENDER,
    reportsViewToShow: reportsViewToShow,
    buildReportsPortfolio: buildReportsPortfolio,
    clientPlatformSplit: clientPlatformSplit,
    REPORTS_PLATFORM_COLOR_SLOTS: REPORTS_PLATFORM_COLOR_SLOTS,
    platformColorSlot: platformColorSlot,
    REPORTS_ACTION_FEED_CAP: REPORTS_ACTION_FEED_CAP,
    buildReportsActionFeed: buildReportsActionFeed,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_OVERVIEW = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
