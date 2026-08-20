// A height budget for the Reports index.
//
// Run with:  node --test tests/js/*.test.js
//
// WHAT THIS IS, EXACTLY: arithmetic over the box metrics app.css declares —
// padding, gap, margin, border, font-size — for a modelled 10-client roster
// raising 6 kinds of finding. It is NOT a browser measurement. There is no
// runner in this repo that lays anything out (jsdom would not help: it
// reports every offsetHeight as 0), so the honest thing to call the numbers
// below is an ESTIMATE, and the honest thing to do with it is to keep it
// coupled to the stylesheet rather than to a screenshot somebody took once.
//
// Every metric is READ OUT OF app.css. That is the whole point: a change
// that puts 12px of padding back on the alert rows, or unclips a KPI note so
// it wraps to two lines, moves these numbers and fails this test. A number
// hard-coded here would drift away from the stylesheet the first time
// anybody touched it, and then it would be measuring nothing at all.
//
// The assumptions the arithmetic makes, all of them optimistic-but-stated:
//
//   • one line per text node, at line-height 1.4 unless the rule says
//     otherwise. Anything that wraps in a real browser makes the real page
//     TALLER than this, so the budget is a floor on the problem, not a
//     ceiling on it;
//   • a 1280px content column — the width the mockup is drawn at — so the
//     card grid is 3 columns and 10 clients are 4 rows;
//   • every card carries the full set of optional blocks (badges, restated
//     stale figures, the platform split and its legend, flag chips). A real
//     roster has fewer; this is the worst case.
//
// The budgets come from the brief: the top of the page (portfolio strip +
// the alert list as it OPENS, collapsed) has to fit one screen, and the
// whole index has to stay inside about two.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");
// Comments are stripped first: several of the rules below carry one, and
// a comment containing a colon parses as a declaration otherwise.
const CSS = fs
  .readFileSync(path.join(WEB, "app.css"), "utf-8")
  .replace(/\/\*[\s\S]*?\*\//g, "");
const TRIAGE = require(path.join(WEB, "reports_triage.js"));

/** The budgets, in CSS pixels. */
const TOP_BUDGET = 900; // portfolio strip + the collapsed alert list
const TOTAL_BUDGET = 2200; // the whole index at 10 clients

/** The modelled roster. */
const CLIENTS = 10;
const ALERT_KINDS = 6; // more than mureo defines, so the collapse is exercised
const CONTENT_WIDTH = 1280;
const DEFAULT_LINE_HEIGHT = 1.4;

/** The declarations of one rule, as a map. Throws if the rule is gone. */
function rule(selector) {
  const at = CSS.indexOf(selector + " {");
  assert.notEqual(at, -1, selector + " is not in app.css");
  const body = CSS.slice(at + selector.length + 2, CSS.indexOf("}", at));
  const out = {};
  body.split(";").forEach(function (line) {
    const i = line.indexOf(":");
    if (i === -1) return;
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  return out;
}

/** The first number in a declaration, or `fallback` when it is absent. */
function px(selector, property, fallback) {
  const raw = rule(selector)[property];
  if (raw === undefined) {
    assert.notEqual(fallback, undefined, selector + " has no " + property);
    return fallback;
  }
  const m = /(-?[\d.]+)/.exec(raw);
  assert.ok(m, selector + " " + property + " is not a length: " + raw);
  return parseFloat(m[1]);
}

/** Vertical padding + border of a box. */
function frame(selector) {
  const decl = rule(selector);
  const pad = decl.padding ? decl.padding.split(/\s+/) : ["0"];
  const vertical = parseFloat(pad[0]) || 0;
  const border = decl.border && !/^0/.test(decl.border) ? 1 : 0;
  return 2 * vertical + 2 * border;
}

/** One line of text at `selector`'s font-size. */
function line(selector, fallbackSize) {
  const decl = rule(selector);
  const size = px(selector, "font-size", fallbackSize);
  const lh = decl["line-height"] ? parseFloat(decl["line-height"]) : DEFAULT_LINE_HEIGHT;
  return Math.round(size * (lh > 3 ? 1 : lh));
}

/** The sum of `parts`, plus `gap` between each pair. */
function stack(gap, parts) {
  return parts.reduce(function (a, b) {
    return a + b;
  }, 0) + gap * Math.max(0, parts.length - 1);
}

// ---------------------------------------------------------------------
// The pieces
// ---------------------------------------------------------------------

function portfolioStripHeight() {
  const cell =
    frame(".reports-kpi") +
    stack(px(".reports-kpi", "gap"), [
      line(".reports-kpi-label"),
      line(".reports-kpi-value"),
      // One CLIPPED line — the rule reserves exactly that much.
      Math.round(px(".reports-kpi-note", "min-height") * px(".reports-kpi-note", "font-size")),
    ]);
  // Four cells across, so the strip is one cell tall.
  return cell + px(".reports-kpis", "margin", 0) * 0 + marginBottom(".reports-kpis");
}

function marginBottom(selector) {
  const margin = rule(selector).margin;
  if (!margin) return 0;
  const parts = margin.split(/\s+/).map(parseFloat);
  // `margin: 0 0 12px` → bottom is the third value; `margin: 0` → 0.
  return parts.length >= 3 ? parts[2] : 0;
}

function alertRowHeight() {
  // One line: the dot, the tag, the client names and the clipped sentence
  // are all on it (`.reports-triage-toggle` is `flex-wrap: nowrap`).
  const toggle = rule(".reports-triage-toggle");
  assert.equal(toggle["flex-wrap"], "nowrap", "the alert row wraps again");
  const summary = rule(".reports-triage-summary");
  assert.equal(summary["text-overflow"], "ellipsis", "the sentence is not clipped");
  return frame(".reports-triage-row") + line(".reports-triage-tag");
}

function alertPanelHeight(rowsShown, hasMore) {
  const rows =
    rowsShown * alertRowHeight() +
    Math.max(0, rowsShown - 1) * px(".reports-triage-row", "margin-bottom", 0);
  const more = hasMore
    ? line(".reports-triage-more") + px(".reports-triage-more", "margin-top", 0)
    : 0;
  return (
    frame(".reports-triage") +
    line(".reports-triage-title") +
    px(".reports-panel-head", "margin-bottom") +
    rows +
    more
  );
}

function clientCardHeight() {
  const gap = px(".reports-client-card", "gap");
  const kpiCell = stack(1, [line(".reports-client-kpi-value"), line(".reports-client-kpi-label")]);
  const card =
    frame(".reports-client-card") +
    stack(gap, [
      line(".reports-client-card-name"), // head: name + status pill
      line(".reports-client-card-fresh"),
      line(".reports-client-card-badge"), // the state badges
      kpiCell,
      line(".reports-client-card-stale-figures"),
      px(".reports-client-split", "height"),
      line(".reports-client-split-legend"),
      line(".report-chip") + 2 * px(".report-chip", "padding") + 2, // flag chips
    ]);
  // The card sits in an item with its reorder / archive controls under it.
  return (
    card +
    px(".reports-client-card-item", "gap") +
    line(".reports-client-drag")
  );
}

function clientGridColumns() {
  // `.reports-index-grid` is `minmax(0, 1fr) 340px` with a gap; the panel
  // then takes its own horizontal padding off that.
  const railText = rule(".reports-index-grid")["grid-template-columns"];
  const rail = parseFloat(/(\d+)px\s*$/.exec(railText)[1]);
  const gridGap = px(".reports-index-grid", "gap");
  const panelPadX = parseFloat(rule(".reports-panel").padding.split(/\s+/)[1]);
  const inner = CONTENT_WIDTH - rail - gridGap - 2 * panelPadX - 2;
  const track = 220; // minmax(220px, 1fr) — the declared minimum
  const cardGap = px(".dashboard-reports-clients", "gap");
  return Math.max(1, Math.floor((inner + cardGap) / (track + cardGap)));
}

function clientPanelHeight() {
  const columns = clientGridColumns();
  const rows = Math.ceil(CLIENTS / columns);
  const chip = line(".reports-filter-chip") + 2 * px(".reports-filter-chip", "padding") + 2;
  return (
    frame(".reports-panel") +
    line(".reports-panel-head h3") +
    px(".reports-panel-head", "margin-bottom") +
    chip +
    px(".reports-filters", "margin-bottom") +
    rows * clientCardHeight() +
    Math.max(0, rows - 1) * px(".dashboard-reports-clients", "gap")
  );
}

/**
 * The rail beside the main column: what mureo did today, then the platform
 * split. Modelled only to CHECK it — the estimate below takes the main
 * column's height as the page's, which is only true while the rail is
 * shorter than it.
 */
function railHeight() {
  const feedRows = TRIAGE_FEED_ROWS;
  const feed =
    frame(".reports-panel") +
    line(".reports-panel-head h3") +
    px(".reports-panel-head", "margin-bottom") +
    feedRows * FEED_CLAMP_LINES * line(".reports-feed-row") +
    Math.max(0, feedRows - 1) * px(".reports-feed", "gap");
  const platforms =
    frame(".reports-panel") +
    line(".reports-panel-head h3") +
    px(".reports-panel-head", "margin-bottom") +
    3 * (px(".reports-platform-track", "height") + px(".reports-platform-row", "margin-bottom"));
  return feed + px(".reports-index-rail", "gap") + platforms;
}

/**
 * How many lines a feed row is allowed to take. Read from the stylesheet,
 * because a clamp raised to three lines makes the rail half again as tall.
 */
const FEED_CLAMP_LINES = px(".reports-feed-body", "-webkit-line-clamp");

/** A full feed — the cap, which is the tallest the panel gets. */
const TRIAGE_FEED_ROWS = require(path.join(WEB, "reports_overview.js"))
  .REPORTS_ACTION_FEED_CAP;

// ---------------------------------------------------------------------
// The budgets
// ---------------------------------------------------------------------

test.describe("the Reports index fits a screen an operator can read", function () {
  const shown = Math.min(ALERT_KINDS, TRIAGE.REPORTS_TRIAGE_COLLAPSED_ROWS);
  const top = portfolioStripHeight() + alertPanelHeight(shown, ALERT_KINDS > shown);

  test.it("keeps the strip and the open alert list inside one screen", function () {
    assert.ok(
      top <= TOP_BUDGET,
      "portfolio strip + collapsed alert list is ~" + top + "px (budget " + TOP_BUDGET + ")"
    );
  });

  test.it("keeps the whole index inside two", function () {
    // The main column decides the height: the platform rail is beside it,
    // not under it, which is what the two-column shell is for.
    const total =
      top +
      px(".reports-index-main", "gap") +
      clientPanelHeight();
    assert.ok(
      total <= TOTAL_BUDGET,
      "the index at " +
        CLIENTS +
        " clients is ~" +
        total +
        "px (budget " +
        TOTAL_BUDGET +
        ")"
    );
  });

  test.it("reports the estimate, so a regression is readable in the log", function () {
    const total = top + px(".reports-index-main", "gap") + clientPanelHeight();
    console.log(
      "      estimated index height at " +
        CLIENTS +
        " clients: top (strip + open alerts) ~" +
        top +
        "px, whole index ~" +
        total +
        "px"
    );
    assert.ok(total > 0);
  });

  test.it("keeps the rail shorter than the column the estimate measures", function () {
    // The estimate above takes the main column as the page's height. That is
    // only true while the rail — the action feed plus the platform split —
    // is the shorter of the two.
    const main = top + px(".reports-index-main", "gap") + clientPanelHeight();
    const rail = railHeight();
    assert.ok(
      rail < main,
      "the rail (~" + rail + "px) is taller than the main column (~" + main + "px)"
    );
  });

  test.it("puts the platform rail beside the grid, not under it", function () {
    // If this became one column at every width the arithmetic above would be
    // wrong AND the page would be a screen taller.
    const columns = rule(".reports-index-grid")["grid-template-columns"];
    assert.match(columns, /minmax\(0, 1fr\) \d+px/);
    assert.match(CSS, /@media \(max-width: 960px\)/);
  });
});
