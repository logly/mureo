// reports_triage.js — the multi-client triage layer's decisions (#651).
//
// The Reports client grid is a flat wall of cards, and everything mureo
// knows about a client that is WRONG is rendered inside that client's own
// card at the same visual weight as everything that is fine. Two field
// incidents were on screen the whole time they cost money: a double-counted
// ad account (#636) and an eleven-day-old figure presented as the selected
// window's spend (#638). Neither was a missing signal. Both were unsurfaced
// ones. This module is the surfacing — aggregation and ranking of facts
// mureo already computes, and not one new fact about an ad account.
//
// Four decisions live here, and each is one an inverted condition would
// ship silently past a static grep pin:
//
//   1. WHICH findings a client raises, from its own summary payload.
//   2. THE ORDER. `REPORTS_TRIAGE_KINDS` is the ranking — the array's index
//      IS the rank — so it is stated in code and never left to render
//      order. A conflict that withholds a client's totals outranks a stale
//      figure, which outranks an observation that is merely overdue.
//   3. WHAT TO RUN about each. An item with no next step is a bug in the
//      item, not a display detail: #636 was reported precisely because the
//      dashboard said "resolve this" and no command existed that could.
//   4. WHICH CLIENTS are marked. The heading's count and the marked cards
//      read one array, so they cannot disagree.
//
// What is NOT here: any number. A client whose totals are withheld raises
// an ITEM saying mureo cannot state them — never a blank, a dash or a zero,
// which is the one thing #638 established the view must never do.
//
// Shipping shape is unchanged: a plain `<script>`-loaded file publishing
// one global, `window.MUREO_REPORTS_TRIAGE`, and it MUST load before
// dashboard.js. The `module.exports` tail at the bottom is inert in a
// browser (`module` is undefined there) and is what lets Node require the
// same bytes the browser gets — the test never sees a re-implementation.
//
// `MUREO.t` and `window.MUREO_REPORTS_LOGIC` are both read from the global
// at CALL time, not captured at load time, so this file has no load-order
// dependency beyond the `<script>` order app.html already pins, and a test
// can supply its own.

(function () {
  "use strict";

  // The ranking, most actionable first. Index === rank.
  //
  // The order is an argument about what mureo can do something about, not
  // about severity in the abstract:
  //
  //   totals_double_counted — the client's totals are withheld RIGHT NOW,
  //     and one command clears it once the operator has chosen a key.
  //   totals_stale — the totals are withheld too, but the fix is to collect
  //     again; nothing about the document is wrong.
  //   not_collected — a collection failed and said why. It has not aged the
  //     figures out yet, and that is the cheapest moment to fix it.
  //   unrecognized_key — an entry mureo cannot resolve to a platform. It
  //     withholds nothing; it is a thing to LOOK at.
  //   observation_due — a change mureo made is past its review date. Owed,
  //     but nothing on screen is wrong because of it.
  //
  // The two conflict kinds sit at opposite ends deliberately: they are two
  // independent findings the whole stack keeps apart (see reports_logic.js),
  // and an operator's next move differs.
  const REPORTS_TRIAGE_KINDS = [
    "totals_double_counted",
    "totals_stale",
    "not_collected",
    "unrecognized_key",
    "observation_due",
  ];

  // Kind → the i18n key naming what to RUN. Every kind in the table above
  // must appear here; `triageItemNextStep` is what the JS suite asserts it
  // on, and an item with no next step is a bug in the item.
  //
  // The two conflict kinds reuse the repair vocabulary the client card
  // already renders rather than forking it, so `mureo repair platform-key`
  // is spelled out in exactly one place in the product.
  const REPORTS_TRIAGE_NEXT_STEPS = {
    totals_double_counted: "dashboard.reports_conflict_duplicate_repair_hint",
    totals_stale: "dashboard.reports_triage_next_collect",
    not_collected: "dashboard.reports_triage_next_not_collected",
    unrecognized_key: "dashboard.reports_conflict_repair_hint",
    observation_due: "dashboard.reports_triage_next_observations",
  };

  // reports_logic.js's decisions — read off the page at call time. Its
  // answers (is this sum double-counted? is this row stale? does this row
  // say why it was not collected?) are the same ones the cards below use;
  // deciding them again here is how a layer and the grid it summarises
  // start disagreeing.
  function logic() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_LOGIC : null;
    if (!api) {
      throw new Error(
        "reports_triage.js needs MUREO_REPORTS_LOGIC — load reports_logic.js " +
          "BEFORE reports_triage.js"
      );
    }
    return api;
  }

  function triageRank(kind) {
    return REPORTS_TRIAGE_KINDS.indexOf(kind);
  }

  function item(kind, client, index, extra) {
    const row = {
      kind: kind,
      rank: triageRank(kind),
      index: index,
      slug: (client && client.slug) || "",
      name: (client && (client.name || client.slug)) || "",
    };
    Object.keys(extra || {}).forEach(function (k) {
      row[k] = extra[k];
    });
    return row;
  }

  // The oldest `fetched_at` among the rows mureo has judged stale, or null.
  //
  // Taken from the stale rows themselves rather than from
  // `aggregateClientKpis().staleFigures`, which is deliberately null when
  // the sum is ALSO double-counted (that figure is wrong at every age, so
  // the card must not restate it). The age is not the figure, and a client
  // that is both must still be able to say how old its numbers are.
  // Null when no stale row carries a readable timestamp — mureo then says
  // the age is unknown rather than inventing one.
  function oldestStaleFetchedAt(summary) {
    const rows = summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    let oldest = null;
    let oldestMs = Infinity;
    rows.forEach(function (row) {
      if (!logic().reportsRowIsStale(row)) return;
      const at = row.freshness.fetched_at;
      const ms = Date.parse(at);
      if (!Number.isNaN(ms) && ms < oldestMs) {
        oldestMs = ms;
        oldest = at;
      }
    });
    return oldest;
  }

  // The server's count of logged changes past their review date, or null.
  //
  // `null` for an absent key is load-bearing: the summary carries this only
  // where the Agency seam supplies clients (see mureo/web/reports.py), and
  // an older daemon or a proxy may not send it at all. Absent is "mureo did
  // not say", never zero. The count is refused unless it is a real number —
  // the browser cannot recompute it (`recent_actions` is capped and carries
  // none of the fields that CLOSE an observation), so a value it cannot
  // trust is one it must not restate.
  function observationsDue(summary) {
    const due =
      summary && summary.observations_due && typeof summary.observations_due === "object"
        ? summary.observations_due
        : null;
    if (!due) return null;
    const count = due.count;
    if (typeof count !== "number" || !isFinite(count) || count <= 0) return null;
    return {
      count: count,
      oldest_due: typeof due.oldest_due === "string" && due.oldest_due
        ? due.oldest_due
        : null,
    };
  }

  // Every finding one client raises, unranked (buildReportsTriage ranks).
  //
  // Defensive about every argument: this runs mid-render over a payload
  // that may come from an older daemon, and a throw here blanks the whole
  // Reports view.
  function triageItemsForClient(client, summary, index) {
    const L = logic();
    const items = [];
    const kpis = L.aggregateClientKpis(summary);

    // Withheld totals — the two independent reasons, never merged. Both
    // say the same thing to the operator ("mureo cannot state this
    // client's figures") and nothing else about them is alike: one is a
    // document to repair, the other a collection to re-run.
    if (kpis.doubleCounted) {
      const rows = L.reportsConflictsOfKind(
        summary,
        L.REPORTS_CONFLICT_DUPLICATE_ACCOUNT
      );
      const labels = L.reportsPlatformLabels(summary);
      rows.forEach(function (row) {
        items.push(
          item("totals_double_counted", client, index, {
            keys: L.reportsKeyList(row.platform_keys, labels),
          })
        );
      });
    }
    if (kpis.stale) {
      items.push(
        item("totals_stale", client, index, {
          fetched_at: oldestStaleFetchedAt(summary),
        })
      );
    }

    // Why the figures did not move — one item per platform that says so.
    // A note is dropped by reports_logic.js when it states no reason, which
    // is the non-answer this field exists to end.
    L.reportsNotCollectedNotes(summary).forEach(function (note) {
      items.push(item("not_collected", client, index, { note: note }));
    });

    // An entry mureo cannot resolve to a platform. It withholds nothing, so
    // it ranks below the collection problems — but it is still the operator
    // looking at a card that cannot be fully checked for a duplicate.
    L.reportsConflictsOfKind(summary, L.REPORTS_CONFLICT_UNRECOGNIZED_KEY).forEach(
      function (row) {
        const labels = L.reportsPlatformLabels(summary);
        items.push(
          item("unrecognized_key", client, index, {
            keys: L.reportsKeyList(row.platform_keys, labels),
          })
        );
      }
    );

    const due = observationsDue(summary);
    if (due) {
      items.push(
        item("observation_due", client, index, {
          count: due.count,
          oldest_due: due.oldest_due,
        })
      );
    }
    return items;
  }

  // The whole layer for one render of the client grid.
  //
  // `clients` and `summaries` are positionally paired, exactly as
  // renderReportsIndex holds them. Returns:
  //
  //   items   — every finding, ranked: by kind first (the table above),
  //             then by the operator's own card order, so two clients with
  //             the same finding stay in the order they chose.
  //   clients — one entry per client with at least one item, in that same
  //             ranked order. This is the ONE list the heading counts and
  //             the grid marks from, which is what keeps "3 clients need
  //             attention" from sitting above two marked cards.
  //
  // Clients are identified by POSITION, not slug: a slug comes from a
  // third-party client registry and may be blank or repeated, and two cards
  // collapsing into one mark would desync the count from the grid.
  function buildReportsTriage(clients, summaries) {
    const rows = Array.isArray(clients) ? clients : [];
    const bodies = Array.isArray(summaries) ? summaries : [];
    let items = [];
    rows.forEach(function (client, index) {
      items = items.concat(triageItemsForClient(client, bodies[index], index));
    });
    items.sort(function (a, b) {
      return a.rank - b.rank || a.index - b.index;
    });
    const seen = {};
    const marked = [];
    items.forEach(function (row) {
      if (seen[row.index]) return;
      seen[row.index] = true;
      marked.push({ index: row.index, slug: row.slug, name: row.name });
    });
    return { items: items, clients: marked };
  }

  // Does the card at grid position `index` carry a finding?
  function triageMarksClient(built, index) {
    const rows = built && Array.isArray(built.clients) ? built.clients : [];
    return rows.some(function (row) {
      return row.index === index;
    });
  }

  // One item as one localized sentence. Untrusted text (a platform key, a
  // collection-failure reason) is interpolated into the string and the
  // caller sets it via textContent.
  //
  // The two withholding kinds say mureo CANNOT STATE the figures. That is
  // the whole point of the layer: #638 established that mureo does not
  // present a number it cannot vouch for, so "we cannot say" has to be a
  // first-class thing the operator reads — never an empty cell that reads
  // as zero, or as fine.
  function triageItemText(row) {
    if (!row || typeof row !== "object") return "";
    const L = logic();
    switch (row.kind) {
      case "totals_double_counted":
        return MUREO.t("dashboard.reports_triage_double_counted", {
          keys: row.keys,
        });
      case "totals_stale":
        // An age mureo cannot quote is said to be unquotable rather than
        // left blank: a dangling "collected " reads as a claim about now.
        return row.fetched_at
          ? MUREO.t("dashboard.reports_triage_stale", {
              ago: L.relativeAge(row.fetched_at),
            })
          : MUREO.t("dashboard.reports_triage_stale_undated");
      case "not_collected":
        return MUREO.t("dashboard.reports_triage_not_collected", {
          platform: (row.note && (row.note.label || row.note.key)) || "",
          reason: (row.note && row.note.reason) || "",
        });
      case "unrecognized_key":
        return MUREO.t("dashboard.reports_triage_unknown_key", { keys: row.keys });
      case "observation_due":
        return MUREO.t("dashboard.reports_triage_observation_due", {
          n: row.count,
          date: row.oldest_due,
        });
      default:
        return "";
    }
  }

  // What to RUN about this item, as one localized sentence.
  //
  // "" only for an item this module did not produce — every kind in
  // REPORTS_TRIAGE_KINDS has an entry, and the JS suite asserts it for each
  // one rather than for a sample.
  function triageItemNextStep(row) {
    const key = row && typeof row === "object" ? REPORTS_TRIAGE_NEXT_STEPS[row.kind] : null;
    return key ? MUREO.t(key) : "";
  }

  const api = {
    REPORTS_TRIAGE_KINDS: REPORTS_TRIAGE_KINDS,
    triageRank: triageRank,
    triageItemsForClient: triageItemsForClient,
    buildReportsTriage: buildReportsTriage,
    triageMarksClient: triageMarksClient,
    triageItemText: triageItemText,
    triageItemNextStep: triageItemNextStep,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_TRIAGE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
