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

  const api = {
    REPORTS_VIEW_INDEX: REPORTS_VIEW_INDEX,
    REPORTS_VIEW_DETAIL: REPORTS_VIEW_DETAIL,
    REPORTS_ENTRY_MENU: REPORTS_ENTRY_MENU,
    REPORTS_ENTRY_RERENDER: REPORTS_ENTRY_RERENDER,
    reportsViewToShow: reportsViewToShow,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_OVERVIEW = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
