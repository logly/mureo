// dashboard_reports_triage.js — the alert list, rendered.
//
// Split out of dashboard_reports.js (#687). Nothing here changed in the move
// beyond the bindings at the top.
//
// The DOM half of reports_triage.js, and the split between the two is the
// point: that module decides WHICH findings a client raises, in what order,
// and what to run about each; this one only draws what it is told. A
// condition inverted here would change what an operator sees without any of
// the JS suite's executable assertions noticing, so there are none here to
// invert — every ranking, grouping, collapsing and dismissal decision is
// asked for, never re-derived.
//
// What it does own is how the list BEHAVES: it opens short (so a wall of
// findings is not the first thing on the screen), rows stay open across a
// dismissal (so closing six findings is not six trips through the
// disclosure), and a dismissed row is counted rather than vanished, with the
// way back stated. That state lives on `REPORTS_VIEW_STATE` with the rest of
// the view's, which is what let this file separate from the index at all.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_TRIAGE`. Loads AFTER
// dashboard_reports_cards.js and BEFORE dashboard_reports.js.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names so every call
  // site below reads exactly as it did when this was one file.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_triage.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_triage.js"
    );
  }
  const triageItemText = REPORTS_SHARED.triageItemText;
  const triageItemNextStep = REPORTS_SHARED.triageItemNextStep;
  const triageItemTag = REPORTS_SHARED.triageItemTag;
  const groupReportsTriage = REPORTS_SHARED.groupReportsTriage;
  const partitionTriageGroups = REPORTS_SHARED.partitionTriageGroups;
  const dismissTriageGroup = REPORTS_SHARED.dismissTriageGroup;
  const dismissTriageItem = REPORTS_SHARED.dismissTriageItem;
  const restoreTriageDismissals = REPORTS_SHARED.restoreTriageDismissals;
  const collapseTriageGroups = REPORTS_SHARED.collapseTriageGroups;
  const REPORTS_VIEW_STATE = REPORTS_SHARED.REPORTS_VIEW_STATE;

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
    REPORTS_VIEW_STATE.reportsTriageBuilt = built;
    const split = partitionTriageGroups(groupReportsTriage(built));
    // …and only the top few of those, unless the operator asked for the
    // rest. Which rows survive the collapse is the module's decision, for
    // the same reason the ranking is: "the top four" is only defensible
    // while it means the four mureo can do most about.
    const shown = collapseTriageGroups(
      split.visible,
      REPORTS_VIEW_STATE.reportsTriageShowAll
    );
    shown.rows.forEach(function (group) {
      list.appendChild(buildTriageRow(group));
    });
    renderTriageMore(shown);
    renderTriageDismissed(split.hiddenCount);
  }

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
      REPORTS_VIEW_STATE.reportsTriageShowAll = true;
      renderReportsTriage(REPORTS_VIEW_STATE.reportsTriageBuilt);
    };
  }

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
      renderReportsTriage(REPORTS_VIEW_STATE.reportsTriageBuilt);
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
      renderReportsTriage(REPORTS_VIEW_STATE.reportsTriageBuilt);
    });
    head.appendChild(close);
    row.appendChild(head);

    const detail = document.createElement("div");
    detail.className = "reports-triage-detail";
    detail.id = detailId;
    const open = !!REPORTS_VIEW_STATE.reportsTriageOpenKinds[group.kind];
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
        renderReportsTriage(REPORTS_VIEW_STATE.reportsTriageBuilt);
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
      REPORTS_VIEW_STATE.reportsTriageOpenKinds[group.kind] = show;
      toggle.setAttribute("aria-expanded", show ? "true" : "false");
    });
    return row;
  }

  // ------------------------------------------------------------------
  // The portfolio strip, the health filter and the platform split
  // ------------------------------------------------------------------


  const api = {
    renderReportsTriage: renderReportsTriage,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_TRIAGE = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
