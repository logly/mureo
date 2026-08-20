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

  // Kind → how the finding reads on the client's own card, and the short
  // label the alert row carries.
  //
  // The severity line is the one reports_logic.js already draws and #638
  // established: does this finding mean a number on that card is NOT the
  // selected window's answer? The two withholding kinds say mureo cannot
  // state the figures at all, so the card is red. The other three are real
  // work — a collection that failed, an entry that resolves to nothing, a
  // review that is owed — but nothing on screen is wrong because of them,
  // so they are amber. Nothing here is a fourth opinion about the payload:
  // the grid's colour and the alert list read one table, which is what
  // stops a card the alert list calls urgent from being coloured green.
  //
  // Every kind in REPORTS_TRIAGE_KINDS must appear in both tables; the JS
  // suite asserts it for each rather than for a sample.
  const REPORTS_TRIAGE_SEVERITIES = {
    totals_double_counted: "attention",
    totals_stale: "attention",
    not_collected: "watch",
    unrecognized_key: "watch",
    observation_due: "watch",
  };

  const REPORTS_TRIAGE_TAGS = {
    totals_double_counted: "dashboard.reports_triage_tag_double_counted",
    totals_stale: "dashboard.reports_triage_tag_stale",
    not_collected: "dashboard.reports_triage_tag_not_collected",
    unrecognized_key: "dashboard.reports_triage_tag_unknown_key",
    observation_due: "dashboard.reports_triage_tag_observation_due",
  };

  // Where a dismissal is remembered, and how many are kept.
  //
  // localStorage, like the card order (reports_order.js) and for the same
  // reason: closing a row is one operator's view preference in one browser,
  // and it resolves NOTHING. Server state would impose it on everyone and
  // would look far too much like the finding having been dealt with.
  //
  // The list is written on every dismissal and nothing expires it, so it is
  // capped: a fingerprint changes whenever the row's content does (see
  // triageGroupKey), which means a long-lived install would otherwise
  // accumulate one dead key per day per finding.
  const REPORTS_TRIAGE_DISMISS_KEY = "mureo.reports.triage.dismissed";
  const REPORTS_TRIAGE_DISMISS_CAP = 100;

  // How many rows the list opens with.
  //
  // Grouping cut a real 27-client install from sixteen rows to six, and six
  // rows of alerts above ten client cards is still two screens before the
  // operator has read anything — the complaint that produced this number.
  // Four is what fits above the fold beside the cards it triages.
  //
  // Showing "the top four" is only defensible because the ranking is stated
  // in code (REPORTS_TRIAGE_KINDS): the rows that survive the collapse are
  // the ones mureo can do the most about, not the ones that happened to
  // render first.
  const REPORTS_TRIAGE_COLLAPSED_ROWS = 4;

  // A client's health, worst first. "ok" is the absence of findings — it is
  // never a claim that the client is performing well, only that mureo has
  // nothing to raise about the state of its data.
  const REPORTS_HEALTH_RANKS = ["attention", "watch", "ok"];

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

  // How this finding reads on the card: "attention" or "watch".
  //
  // An item this module did not produce is "watch" rather than a throw or a
  // blank — it renders as work to look at, which is the safe read for a
  // finding whose meaning is unknown.
  function triageItemSeverity(row) {
    const kind = row && typeof row === "object" ? row.kind : null;
    return REPORTS_TRIAGE_SEVERITIES[kind] || "watch";
  }

  // The short label the alert row carries next to the client's name. "" for
  // a kind this module did not produce — an invented tag would name a
  // finding that does not exist.
  function triageItemTag(row) {
    const key = row && typeof row === "object" ? REPORTS_TRIAGE_TAGS[row.kind] : null;
    return key ? MUREO.t(key) : "";
  }

  // The health of the card at grid position `index`: the WORST severity it
  // raised, or "ok" when it raised nothing.
  //
  // Worst, not last or first: a client that is both double-counted and
  // merely overdue is not amber. By position for the same reason
  // triageMarksClient is — a slug may be blank or repeated.
  function triageClientHealth(built, index) {
    const rows = built && Array.isArray(built.items) ? built.items : [];
    let worst = REPORTS_HEALTH_RANKS.length - 1;
    rows.forEach(function (row) {
      if (!row || row.index !== index) return;
      const rank = REPORTS_HEALTH_RANKS.indexOf(triageItemSeverity(row));
      if (rank !== -1 && rank < worst) worst = rank;
    });
    return REPORTS_HEALTH_RANKS[worst];
  }

  // How many of the `total` cards on the grid sit at each health.
  //
  // Over the WHOLE grid, not over the findings: these counts sit on the
  // filter chips above the cards, and a client that raised nothing is still
  // a card the "ok" chip has to show.
  function triageHealthCounts(built, total) {
    const count = typeof total === "number" && total > 0 ? Math.floor(total) : 0;
    const counts = { all: count, attention: 0, watch: 0, ok: 0 };
    for (let i = 0; i < count; i++) {
      counts[triageClientHealth(built, i)] += 1;
    }
    return counts;
  }

  // ------------------------------------------------------------------
  // What a CARD says about its own findings
  // ------------------------------------------------------------------

  // One short badge for a finding, for the client card in the grid.
  //
  // A badge is the STATE, never the explanation: no sentence, no command,
  // nothing the alert list above the grid already says. It exists because
  // the card renders "—" where a figure would be, and "—" on its own reads
  // as zero — which #638 established is the one thing this view must never
  // let happen. "Figures 29 days old" is not a warning; it is what the dash
  // means.
  //
  // The stale badge carries the age for exactly that reason. Where mureo
  // cannot quote an age it falls back to the plain tag rather than inventing
  // one, the same position triageItemText takes.
  function triageItemBadge(row) {
    const kind = row && typeof row === "object" ? row.kind : null;
    if (kind === "totals_stale" && row.fetched_at) {
      return MUREO.t("dashboard.reports_triage_tag_stale_aged", {
        ago: logic().relativeAge(row.fetched_at),
      });
    }
    return triageItemTag(row);
  }

  // Every badge the card at grid position `index` carries: one per KIND, in
  // the ranking's order. Deduplicated because a client with two
  // duplicate-account conflicts has one state, not two.
  function triageClientBadges(built, index) {
    const rows = built && Array.isArray(built.items) ? built.items : [];
    const seen = {};
    const out = [];
    rows.forEach(function (row) {
      if (!row || row.index !== index || seen[row.kind]) return;
      seen[row.kind] = true;
      out.push({
        kind: row.kind,
        severity: triageItemSeverity(row),
        text: triageItemBadge(row),
      });
    });
    return out;
  }

  // ------------------------------------------------------------------
  // One row per kind (grouping)
  // ------------------------------------------------------------------

  // The layer's items as one row per KIND, each naming the clients it
  // covers.
  //
  // On a twenty-seven-client install the ungrouped layer rendered sixteen
  // rows, six of them the same sentence about the same unresolvable platform
  // key under six different client names. A list that repeats itself is a
  // wall again, which is the failure this layer exists to end.
  //
  // Grouping is a DISPLAY aggregation and nothing else. It changes no
  // client's finding, drops no client, and does not reorder: the groups come
  // out in the ranking's order because `built.items` is already in it, and a
  // group's clients keep the operator's own card order for the same reason.
  // The union of the groups' clients is exactly `built.clients` — the set
  // the heading counts and the grid marks — and the JS suite asserts it.
  function groupReportsTriage(built) {
    const rows = built && Array.isArray(built.items) ? built.items : [];
    const byKind = {};
    const order = [];
    rows.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      let group = byKind[row.kind];
      if (!group) {
        group = {
          kind: row.kind,
          rank: triageRank(row.kind),
          severity: triageItemSeverity(row),
          items: [],
          clients: [],
        };
        byKind[row.kind] = group;
        order.push(row.kind);
      }
      group.items.push(row);
      // One client once per row, however many findings of this kind it
      // raised — by POSITION, for the same reason triageMarksClient is: a
      // slug is registry-controlled and may be blank or repeated.
      const known = group.clients.some(function (c) {
        return c.index === row.index;
      });
      if (!known) {
        group.clients.push({ index: row.index, slug: row.slug, name: row.name });
      }
    });
    return order.map(function (kind) {
      return byKind[kind];
    });
  }

  /**
   * The rows to render, and how many are held back.
   *
   * Collapsing is a display budget and touches nothing else: the heading's
   * count, the KPI cell and the marked cards are all over EVERY finding,
   * whether its row is on screen or not. A list that already fits is not
   * collapsed at all — there is no "show all (0)".
   */
  function collapseTriageGroups(groups, showAll) {
    const rows = Array.isArray(groups) ? groups : [];
    if (showAll || rows.length <= REPORTS_TRIAGE_COLLAPSED_ROWS) {
      return { rows: rows, remaining: 0, collapsed: false };
    }
    return {
      rows: rows.slice(0, REPORTS_TRIAGE_COLLAPSED_ROWS),
      remaining: rows.length - REPORTS_TRIAGE_COLLAPSED_ROWS,
      collapsed: true,
    };
  }

  // ------------------------------------------------------------------
  // Dismissing a row (a view operation — it resolves nothing)
  // ------------------------------------------------------------------

  // What a finding SAYS, as a string, so a dismissal can be keyed to it.
  //
  // This is the whole safety property of the feature. An operator closes a
  // row; the condition behind it is still true, and #636 and #638 both cost
  // money precisely because something true was not on screen. So the key is
  // a fingerprint of the row's CONTENT: when the content changes the row is
  // a different row and comes back on its own, with nobody having to
  // remember to look for it.
  //
  // Per kind, what "changed" means:
  //
  //   totals_stale        — the AGE in whole days. A figure that was eleven
  //                         days old when it was dismissed and is now
  //                         twenty-nine is a worse fact, so it is a new row.
  //                         An unquotable age is its own value; it does not
  //                         collapse into "0 days".
  //   not_collected       — the platform and the reason it gave. A different
  //                         failure is a different finding.
  //   the two conflict kinds — the platform keys involved.
  //   observation_due     — how many are due and how long the oldest has
  //                         been.
  //
  // Plus the client it belongs to, always: a row that grows to cover a
  // seventh client is not the row that was dismissed.
  function triageItemFingerprint(row) {
    if (!row || typeof row !== "object") return "";
    const who = String(row.slug || row.name || "");
    let what = "";
    switch (row.kind) {
      case "totals_stale": {
        const ms = row.fetched_at ? Date.parse(row.fetched_at) : NaN;
        what = Number.isNaN(ms)
          ? "undated"
          : String(Math.floor((Date.now() - ms) / 86400000));
        break;
      }
      case "not_collected":
        what =
          String((row.note && (row.note.key || row.note.label)) || "") +
          "\u0002" +
          String((row.note && row.note.reason) || "");
        break;
      case "totals_double_counted":
      case "unrecognized_key":
        what = String(row.keys || "");
        break;
      case "observation_due":
        what = String(row.count) + "\u0002" + String(row.oldest_due || "");
        break;
      default:
        what = "";
    }
    return who + "\u0002" + what;
  }

  /** The identity a dismissed row is remembered under. */
  function triageGroupKey(group) {
    if (!group || typeof group !== "object") return "";
    const items = Array.isArray(group.items) ? group.items : [];
    return (
      String(group.kind || "") +
      "\u0000" +
      items.map(triageItemFingerprint).join("\u0001")
    );
  }

  // The dismissed keys, or [] on ANY problem (storage disabled, corrupt
  // JSON, a non-array body). Degrading to "nothing is dismissed" is the only
  // safe direction: the other one silences the layer on a browser whose
  // storage is unavailable.
  function readDismissedTriage() {
    try {
      const raw = window.localStorage.getItem(REPORTS_TRIAGE_DISMISS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (k) {
        return typeof k === "string" && k;
      });
    } catch (_e) {
      return []; // storage unavailable or corrupt — hide nothing
    }
  }

  function writeDismissedTriage(keys) {
    try {
      window.localStorage.setItem(
        REPORTS_TRIAGE_DISMISS_KEY,
        JSON.stringify(keys.slice(-REPORTS_TRIAGE_DISMISS_CAP))
      );
    } catch (_e) {
      /* storage unavailable — the row is closed for this render only */
    }
  }

  /** Remember one row as dismissed. Never throws. */
  function dismissTriageGroup(group) {
    const key = triageGroupKey(group);
    if (!key) return;
    const keys = readDismissedTriage().filter(function (k) {
      return k !== key;
    });
    keys.push(key);
    writeDismissedTriage(keys);
  }

  /** Bring every hidden row back. */
  function restoreTriageDismissals() {
    writeDismissedTriage([]);
  }

  /**
   * Split grouped rows into the ones to render and the ones to count as
   * hidden.
   *
   * `hidden` is returned rather than dropped because the count has to reach
   * the screen: a dismissal that left no trace would be a finding removed in
   * silence, which is the failure mode this whole layer was built against.
   * Nothing here touches `built.clients` — the heading's count, the KPI cell
   * and the grid's marks stay true whatever is closed.
   */
  function partitionTriageGroups(groups) {
    const rows = Array.isArray(groups) ? groups : [];
    const dismissed = readDismissedTriage();
    const visible = [];
    const hidden = [];
    rows.forEach(function (group) {
      if (dismissed.indexOf(triageGroupKey(group)) === -1) visible.push(group);
      else hidden.push(group);
    });
    return { visible: visible, hidden: hidden };
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
    triageItemSeverity: triageItemSeverity,
    triageItemTag: triageItemTag,
    triageClientHealth: triageClientHealth,
    triageHealthCounts: triageHealthCounts,
    triageItemBadge: triageItemBadge,
    triageClientBadges: triageClientBadges,
    groupReportsTriage: groupReportsTriage,
    triageItemFingerprint: triageItemFingerprint,
    triageGroupKey: triageGroupKey,
    readDismissedTriage: readDismissedTriage,
    dismissTriageGroup: dismissTriageGroup,
    restoreTriageDismissals: restoreTriageDismissals,
    partitionTriageGroups: partitionTriageGroups,
    REPORTS_TRIAGE_DISMISS_CAP: REPORTS_TRIAGE_DISMISS_CAP,
    REPORTS_TRIAGE_COLLAPSED_ROWS: REPORTS_TRIAGE_COLLAPSED_ROWS,
    collapseTriageGroups: collapseTriageGroups,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_TRIAGE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
