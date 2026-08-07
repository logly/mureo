// reports_order.js — the Reports index card order (#556).
//
// One concern: the order the operator arranged the client grid in — where it
// is stored, how it is applied to the server's rows, and the two ways it
// changes. MOVED here verbatim from dashboard.js.
//
// This is not the DOM-free half of the split (reports_logic.js is) and does
// not pretend to be: the grid itself is the single source of truth for the
// order, so persistReportsOrderFromDom and moveReportsCard read and reorder
// real element nodes. What they never do is go LOOKING for them — every node
// is handed in by the caller, nothing here touches `document`, nothing here
// creates an element or registers a listener. That is what makes the rules
// executable: a fake node carrying `children` and `insertBefore` is enough to
// prove that a corrupt stored order degrades to the server's, that a client
// the operator has never placed lands LAST rather than displacing the top of
// the grid, and that a move off either end is a no-op.
//
// What stayed in dashboard.js, and why — the reasons differ, so they are not
// collapsed into one:
//
//   buildReportsDragHandle, wireReportsCardDrag, buildReportsArchiveButton
//     create elements and register listeners. They need a document.
//   setReportsClientArchived POSTs and re-renders. Archiving is server state,
//     not a browser-local view preference — the process that stops collecting
//     a client's figures cannot see a flag in someone's browser.
//   isArchivedClient, visibleReportsClients, archivedReportsClients read the
//     module-level `reportsClients` cache. The last two would have to take it
//     as a parameter to move, which is a signature change, not a move — and
//     isArchivedClient alone is a three-line predicate that does not earn a
//     seam of its own.
//
// `window.localStorage` is read at CALL time, inside a try/catch: storage can
// be disabled or hold someone else's corrupt value, and an unusable order
// must degrade to the server's order rather than to an empty grid.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing one
// global, `window.MUREO_REPORTS_ORDER`, and it MUST load before dashboard.js.
// The `module.exports` tail is inert in a browser and is what lets Node
// require the same bytes the browser gets.

(function () {
  "use strict";

  // --------------------------------------------------------------------
  // Index card order (per operator, in this browser)
  //
  // The order is PURELY visual: losing it breaks nothing, and two operators
  // sharing one install reasonably want different orders. So it is
  // localStorage, not server state — server state would impose one
  // operator's arrangement on everyone. Archiving is the opposite kind of
  // decision and is deliberately NOT stored here (see
  // setReportsClientArchived in dashboard.js).
  // --------------------------------------------------------------------
  const REPORTS_ORDER_KEY = "mureo.reports.client_order";

  // The stored order, or [] on ANY problem (storage disabled, corrupt JSON,
  // a non-array body, non-string members). An unusable order must degrade to
  // the server's order — never to an empty grid.
  function readReportsOrder() {
    try {
      const raw = window.localStorage.getItem(REPORTS_ORDER_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (s) {
        return typeof s === "string" && s;
      });
    } catch (_e) {
      return []; // storage unavailable or corrupt — fall back to server order
    }
  }

  function writeReportsOrder(slugs) {
    try {
      window.localStorage.setItem(REPORTS_ORDER_KEY, JSON.stringify(slugs));
    } catch (_e) {
      /* storage unavailable — the order stays for this render only */
    }
  }

  // Apply the stored order to `rows`. Stored slugs that no longer exist are
  // simply never matched, so they cost nothing; clients the stored order has
  // never seen keep their server order and are appended LAST.
  //
  // Last, not first: the grid is curated on purpose, and a client the
  // operator has never placed must not displace the top of it on every
  // onboarding. Its position is defined and findable, and one drag fixes it.
  function orderReportsClients(rows) {
    const order = readReportsOrder();
    const placed = [];
    const fresh = [];
    rows.forEach(function (c) {
      const slug = c && c.slug ? c.slug : "";
      if (slug && order.indexOf(slug) !== -1) placed.push(c);
      else fresh.push(c);
    });
    placed.sort(function (a, b) {
      return order.indexOf(a.slug) - order.indexOf(b.slug);
    });
    return placed.concat(fresh);
  }

  // Persist the grid's CURRENT DOM order. The DOM is the single source of
  // truth for both the drop handler and the keyboard path, so the two can
  // never disagree. Only the cards on screen are recorded: an archived
  // client leaves the stored order and returns as an unplaced (last) card
  // when it is restored.
  function persistReportsOrderFromDom(wrap) {
    const slugs = [];
    Array.prototype.forEach.call(wrap.children, function (node) {
      const slug = node.getAttribute ? node.getAttribute("data-client") : null;
      if (slug) slugs.push(slug);
    });
    writeReportsOrder(slugs);
  }

  // Move one card `delta` slots and persist. Moving the existing node (rather
  // than re-rendering the grid) keeps focus on the control the operator is
  // holding, so repeated arrow presses just work.
  function moveReportsCard(node, delta) {
    const wrap = node.parentNode;
    if (!wrap) return;
    const items = Array.prototype.slice.call(wrap.children);
    const from = items.indexOf(node);
    const to = from + delta;
    if (from === -1 || to < 0 || to >= items.length) return;
    if (delta < 0) wrap.insertBefore(node, items[to]);
    else wrap.insertBefore(node, items[to].nextSibling);
    persistReportsOrderFromDom(wrap);
  }

  const api = {
    REPORTS_ORDER_KEY: REPORTS_ORDER_KEY,
    readReportsOrder: readReportsOrder,
    writeReportsOrder: writeReportsOrder,
    orderReportsClients: orderReportsClients,
    persistReportsOrderFromDom: persistReportsOrderFromDom,
    moveReportsCard: moveReportsCard,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_ORDER = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
