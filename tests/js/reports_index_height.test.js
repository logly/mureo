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
/** The viewport the height estimate is quoted at. */
const VIEWPORT = 1440;
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

/**
 * A `:root` custom property's declared value.
 *
 * #691 states the type scale as tokens, so a rule now says
 * `font-size: var(--type-caption-size)` where it used to say `12px`. The
 * number is still declared in app.css — one level further up — and resolving
 * it here is what keeps this model coupled to the stylesheet rather than to a
 * literal somebody would have to remember to update in two places.
 *
 * One level only, and deliberately: a token defined in terms of another token
 * would be a scale nobody can read off the file either.
 */
function token(name) {
  const m = new RegExp("\\" + name + ":\\s*([^;]+);").exec(CSS);
  assert.ok(m, name + " is not declared in app.css");
  return m[1].trim();
}

/** The first number in a declaration, or `fallback` when it is absent. */
function px(selector, property, fallback) {
  let raw = rule(selector)[property];
  if (raw === undefined) {
    assert.notEqual(fallback, undefined, selector + " has no " + property);
    return fallback;
  }
  const ref = /^var\((--[\w-]+)\)$/.exec(raw.trim());
  if (ref) raw = token(ref[1]);
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
  const lhRaw = decl["line-height"];
  const lhRef = lhRaw && /^var\((--[\w-]+)\)$/.exec(lhRaw.trim());
  const lh = lhRaw
    ? parseFloat(lhRef ? token(lhRef[1]) : lhRaw)
    : DEFAULT_LINE_HEIGHT;
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

// The band across the top of the list screen (#706 step 3-b). It sits ABOVE
// the portfolio strip, so it is part of what has to fit one screen — a
// section left out of this model is a section that can grow for free.
//
// One grid ROW, so its height is the tallest of the three cells. The blocks
// are the tallest (two lines inside their own padded box), and that is what
// is measured; the identity and the fraction are shorter and would only make
// the estimate optimistic in the direction this file already documents.
function heroBandHeight() {
  const block =
    frame(".reports-hero-block") +
    stack(px(".reports-hero-block", "gap"), [
      line(".reports-hero-block-count"),
      line(".reports-hero-block-label"),
    ]);
  return frame(".reports-hero") + block + marginBottom(".reports-hero");
}

// The ground the two report screens sit on (#706 step 3-c) is a padded,
// bordered container around everything below, so its frame is part of the
// page's height whether or not anything inside it grew. Counted here for the
// same reason the band above is: a box left out of this model is a box that
// can grow for free.
function shellFrame() {
  return frame(".dashboard-reports");
}

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

/**
 * The shell's content width at `viewport`, from the stylesheet.
 *
 * One width for every left-nav item — a frame that changed size as the
 * operator moved between them would read as a broken layout — and it is the
 * width the widest screen needs: at the old 1180px the Reports card column
 * fitted two cards abreast, so a 27-client roster was fourteen rows of
 * scrolling. Every number here is read out of app.css, so widening or
 * narrowing the shell moves the column count below rather than silently
 * disagreeing with it.
 */
function shellContentWidth(viewport) {
  const declared = rule('.app-main:has([data-dashboard]:not([hidden]))')["max-width"];
  const m = /min\((\d+)px,\s*(\d+)vw\)/.exec(declared);
  assert.ok(m, "the reports shell width is no longer min(<px>, <vw>): " + declared);
  const width = Math.min(parseFloat(m[1]), (parseFloat(m[2]) / 100) * viewport);
  // The reports screen states its own gutter; everything is border-box.
  const pad = parseFloat(
    rule('.app-main:has([data-dashboard]:not([hidden]))').padding.split(/\s+/)[1]
  );
  return width - 2 * pad;
}

/** The card column's own width at `viewport` — nav, rail and panel removed. */
function clientColumnWidth(viewport) {
  // `flex: 0 0 208px` — the basis is the last of the three.
  const nav = parseFloat(rule(".dashboard-nav").flex.split(/\s+/).pop());
  const navGap = px(".dashboard-layout", "gap");
  const railText = rule(".reports-index-grid")["grid-template-columns"];
  const rail = parseFloat(/(\d+)px\s*$/.exec(railText)[1]);
  const gridGap = px(".reports-index-grid", "gap");
  const panelPadX = parseFloat(rule(".reports-panel").padding.split(/\s+/)[1]);
  return shellContentWidth(viewport) - nav - navGap - rail - gridGap - 2 * panelPadX - 2;
}

/** `repeat(auto-fill, minmax(<track>, 1fr))` at that width. */
function clientGridColumns(viewport) {
  const tracks = rule(".dashboard-reports-clients")["grid-template-columns"];
  const track = parseFloat(/minmax\((\d+)px/.exec(tracks)[1]);
  const cardGap = px(".dashboard-reports-clients", "gap");
  const inner = clientColumnWidth(viewport === undefined ? VIEWPORT : viewport);
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
  const top =
    shellFrame() +
    heroBandHeight() +
    portfolioStripHeight() +
    alertPanelHeight(shown, ALERT_KINDS > shown);

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

  test.it("fits three cards abreast at 1440 and four at 1920", function () {
    // The complaint this answers: at the dashboard's own 1180px the card
    // column takes two cards, so a 27-client roster is fourteen rows of
    // scrolling before the operator has read anything. The Reports screen
    // widens itself past the rest of the dashboard for exactly this, and
    // the count is derived from the stylesheet's own numbers — the shell
    // width, the gutter, the nav, the rail, the panel padding and the card
    // track — so narrowing any of them fails here rather than on a screen.
    assert.ok(
      clientGridColumns(1440) >= 3,
      "1440px gives " + clientGridColumns(1440) + " card columns, wanted 3+"
    );
    assert.ok(
      clientGridColumns(1920) >= 4,
      "1920px gives " + clientGridColumns(1920) + " card columns, wanted 4+"
    );
    // …and it does not stretch the cards on a very large monitor.
    assert.equal(clientGridColumns(3840), clientGridColumns(1920));
  });

  test.it("uses the mockup's own card track", function () {
    const tracks = rule(".dashboard-reports-clients")["grid-template-columns"];
    assert.equal(tracks, "repeat(auto-fill, minmax(230px, 1fr))");
  });

  test.it("gives every left-nav item the same frame", function () {
    // One width for the whole dashboard, not one for Reports: a frame that
    // resized as the operator moved between the left-nav items would read as
    // a broken layout. The width is still scoped away from the wizard and
    // the landing page by the same `:has()` trick as before — and a browser
    // without `:has()` falls back to the narrow shell rather than to a
    // broken one.
    assert.ok(
      CSS.includes('.app-main:has([data-dashboard]:not([hidden])) {'),
      "the dashboard width is not scoped"
    );
    assert.ok(
      !CSS.includes("data-dashboard-group=\"reports\"]:not([hidden])"),
      "one section still widens itself past the others"
    );
  });

  test.it("lets the content follow the frame", function () {
    // The width was widened for the content, so nothing may cap the content
    // back to where it was. What a section holds — lists, rows, tables —
    // stretches with the frame.
    assert.ok(
      !CSS.includes(".dashboard-section > * {"),
      "the section content is capped again"
    );
    assert.ok(!CSS.includes("--dashboard-measure"), "the measure is back");
    const table = rule(".dashboard-section table")["width"];
    assert.equal(table, "100%", "a table still hugs the left of the frame");
  });

  test.it("flows the fields instead of stretching or stranding them", function () {
    // The one thing that does not survive being stretched is a single-line
    // input. Capping it and leaving it alone on the left of an empty frame
    // is the layout this width exists to end, so the fields sit side by side
    // and the row fills.
    const label = rule(".dashboard-section label");
    assert.equal(label.display, "inline-block");
    assert.equal(label.width, "100%", "the fields do not stack on a narrow screen");
    assert.match(label["max-width"], /^\d+px$/);
    // A block of text keeps its own row.
    const wide = rule(".dashboard-section label:has(textarea)");
    assert.equal(wide.display, "block");
    assert.ok(parseFloat(wide["max-width"]) > parseFloat(label["max-width"]));
  });

  test.it("puts the platform rail beside the grid, not under it", function () {
    // If this became one column at every width the arithmetic above would be
    // wrong AND the page would be a screen taller.
    const columns = rule(".reports-index-grid")["grid-template-columns"];
    assert.match(columns, /minmax\(0, 1fr\) \d+px/);
    assert.match(CSS, /@media \(max-width: 960px\)/);
  });
});
