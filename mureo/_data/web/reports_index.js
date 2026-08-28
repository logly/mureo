// reports_index.js — everything the list screen IS, before a node is drawn
// (#715).
//
// The index view is five claims about a roster — the alert layer, the health
// split, the band across the top, how many of these mureo could not check at
// all (#714), and the portfolio strip — and every one of them is a reading of
// the SAME two arrays: the clients the grid is about, and the summaries
// already fetched for them. This file composes them together, once, so
// `renderReportsIndex` is left with what it is for: putting the result on
// screen.
//
// ONE HEALTH VERDICT PER CLIENT, COMPUTED ONCE. `triageClientHealth` is an
// O(items) scan of the alert layer, and the index used to run it five times
// per client per render — inside the health counts, inside the band's
// `healthOf` closure, on each card, again on each roster row, and once more
// inside the portfolio strip's own `triageHealthCounts`. Five scans that can
// only ever agree, because the function is pure; the multiplier was the whole
// cost. `healthByIndex` is that answer, in grid order, and every consumer is
// handed the array — or, for the strip and the chips, the counts built from
// it. Nothing downstream of this file scans the layer for a health again.
//
// It is NOT a second opinion. The verdict is still reports_triage.js's and
// nothing here grades a client: `triageClientHealth` decides each entry and
// `triageHealthCounts` still counts them, handed the array it would otherwise
// rebuild. One decision function, called once per client.
//
// Everything here is a plain function: no DOM, no fetch, no module state, so
// `node --test tests/js/*.test.js` can execute it.
//
// Shipping shape is the one every other module in this directory has: a plain
// `<script>`-loaded file publishing ONE global, `window.MUREO_REPORTS_INDEX`,
// loaded before dashboard.js. `MUREO_REPORTS_TRIAGE`, `MUREO_REPORTS_OVERVIEW`
// and `MUREO_REPORTS_HERO` are read off the page at CALL time, exactly as
// reports_hero.js reads reports_overview.js, so this file has no load-order
// dependency beyond the `<script>` order app.html already pins.

(function () {
  "use strict";

  // reports_triage.js's answers — read off the page at call time, for the
  // reason reports_hero.js gives: the health of a client is decided in ONE
  // place, and this file must not hold a second copy of it.
  function triage() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_TRIAGE : null;
    if (!api) {
      throw new Error(
        "reports_index.js needs MUREO_REPORTS_TRIAGE — load reports_triage.js " +
          "BEFORE reports_index.js"
      );
    }
    return api;
  }

  // reports_overview.js's portfolio figures, on the same terms.
  function overview() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_OVERVIEW : null;
    if (!api) {
      throw new Error(
        "reports_index.js needs MUREO_REPORTS_OVERVIEW — load " +
          "reports_overview.js BEFORE reports_index.js"
      );
    }
    return api;
  }

  // reports_hero.js's band model, on the same terms.
  function hero() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_HERO : null;
    if (!api) {
      throw new Error(
        "reports_index.js needs MUREO_REPORTS_HERO — load reports_hero.js " +
          "BEFORE reports_index.js"
      );
    }
    return api;
  }

  //: A summary mureo RECEIVED is an object. `null` is what
  //: `fetchClientCardSummary` yields for a request that FAILED — a non-2xx, a
  //: network error, a body that was not JSON, the daemon mid-restart — and
  //: #713 stopped that null being collapsed into `{}` precisely so the two
  //: stay distinguishable this far up. A received summary that states no
  //: figures is a different fact, and the band's fourth block is where it is
  //: already said.
  function wasReceived(summary) {
    return !!summary && typeof summary === "object";
  }

  /**
   * How many of the roster mureo could not check just now, and whether to
   * say so (#714).
   *
   * A NOTE, NOT A HEALTH STATE, and deliberately not a fifth block. Every
   * verdict this screen has would be false about a client whose summary never
   * arrived: "not running" states something about its ads that nobody
   * checked, "needs attention" turns the whole roster red the moment the
   * daemon restarts, and "nothing raised" claims a check that did not happen.
   * So those clients stay exactly where they were before this line existed —
   * in the OK bucket — the four blocks remain a partition of the roster
   * (ok + watch + attention + idle == total), and the triage layer is not
   * consulted at all. What changes is only that the failure stops being
   * invisible.
   *
   * `show` is the BAND's own answer to "is this a roster?", not a second
   * threshold: below two clients there is no list for the line to sit above,
   * and that install has never had one.
   */
  function unreachableSummaries(clients, bodies, band) {
    let count = 0;
    clients.forEach(function (_client, i) {
      if (!wasReceived(bodies[i])) count += 1;
    });
    return { count: count, show: count > 0 && !!(band && band.show) };
  }

  /**
   * The index screen's model:
   * `{triage, healthByIndex, healthCounts, hero, unreachable, portfolio}`.
   *
   * `rows` is the client list in GRID ORDER (archived clients already
   * dropped, the operator's own order already applied), and `summaries` is
   * positional with it — the array `renderReportsIndex` holds, one fetched
   * card summary per client, `null` where the request failed.
   *
   * Built ONCE per render and handed whole to the renderers, so the band
   * above the grid, the portfolio strip, the alert list, the filter chips,
   * the cards and the roster table are six views of one answer rather than
   * six answers.
   *
   * Defensive about both arguments: this runs mid-render over payloads that
   * may come from an older daemon, and a throw here blanks the Reports view.
   */
  function buildReportsIndexModel(rows, summaries) {
    const clients = Array.isArray(rows) ? rows : [];
    const bodies = Array.isArray(summaries) ? summaries : [];
    const layer = triage();
    // Which of these clients needs attention today, ranked, with what to run
    // about each. Built once and handed to both the alert list and the grid,
    // so the count above and the marks below are the same list.
    const built = layer.buildReportsTriage(clients, bodies);
    // The per-client verdict, in grid order — the ONE scan of the layer this
    // render performs. Everything painted by health reads this array.
    const healthByIndex = clients.map(function (_client, i) {
      return layer.triageClientHealth(built, i);
    });
    // How the grid splits by health — ONE object, handed to the band above
    // the screen and to the filter chips over the cards. Two calls would be
    // two answers the moment either caller learned to pass something
    // different (#706 step 3-b).
    const healthCounts = layer.triageHealthCounts(built, clients.length, healthByIndex);
    // The band across the top: the roster's health at a glance, and nothing
    // it grades itself — the counts and the per-client verdict both come from
    // the triage layer the cards below are marked from. It draws nothing at
    // all below two clients, which is also the answer the line under it asks
    // for rather than deciding again.
    const band = hero().buildReportsHero(healthCounts, bodies, function (i) {
      return healthByIndex[i];
    });
    return {
      triage: built,
      healthByIndex: healthByIndex,
      healthCounts: healthCounts,
      hero: band,
      // The line under the band: how many of these mureo could not check just
      // now (#714). Counted off the summaries, never off the health — see
      // unreachableSummaries for why it is not one of the band's blocks.
      unreachable: unreachableSummaries(clients, bodies, band),
      // The roster's own figures, above the alerts — built from the same
      // summaries the cards below are built from, and stating over how many
      // clients each of them holds.
      portfolio: overview().buildReportsPortfolio(clients, bodies),
    };
  }

  const api = {
    buildReportsIndexModel: buildReportsIndexModel,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_INDEX = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
