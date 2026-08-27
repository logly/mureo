// The list screen, as an operator sees it (#706 step 3-b).
//
// Run with:  node --test tests/js/*.test.js
//
// Step 3-a rebuilt the screen about ONE client; this is the one about all of
// them. What it adds is a band across the top that answers "how many of these
// are fine?" before anything is clicked, a rail that says what mureo did
// today in one line per entry, and the roster's spend by platform.
//
// THE ONE THING THIS SUITE EXISTS TO PREVENT is the band disagreeing with the
// screen under it. The health of a client has exactly one answer in the
// product — reports_triage.js's — and a band that graded the roster itself
// would be a fourth opinion beside the cards, the roster table and the filter
// chips: green in the band, red on the card, and an operator with no way to
// tell which is true. So the counts are asserted AGAINST the filter chips'
// own counts rather than against a literal.
//
// Driven against the real dashboard, the real app.html AND the real app.css,
// because half of what this feature is cannot be seen from a DOM shape: a
// band rendered but never un-hidden, an author `display` beating `[hidden]`
// so the band stays on screen for a roster of one, and a colour that resolves
// to a literal instead of a token.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { loadDashboardPage, settle, isVisible, cascade } = require("./dom_harness.js");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

// The pure modules, as the browser has them: one shared global object, each
// file publishing onto it, each reading its peers off it at call time.
globalThis.MUREO = { t: (key) => key };
globalThis.window = globalThis;
require(path.join(WEB, "reports_logic.js"));
require(path.join(WEB, "reports_format.js"));
require(path.join(WEB, "reports_display.js"));
const overview = require(path.join(WEB, "reports_overview.js"));
const hero = require(path.join(WEB, "reports_hero.js"));

const DAY = 86400000;
const ago = (d) => new Date(Date.now() - d * DAY).toISOString();
const TODAY = new Date().toISOString().slice(0, 10);

/**
 * One client's summary.
 *
 * `kind` picks what the TRIAGE LAYER makes of it, which is the only thing
 * that decides a client's health anywhere in this product:
 *   stale — its totals are withheld            -> "attention"
 *   due   — a review mureo owes is past due    -> "watch"
 *   ok    — nothing raised                     -> "ok"
 *   idle  — nothing raised and no figures AT ALL, which is the fourth block
 */
function summaryFor(slug, kind, actions) {
  const platform = {
    key: "google_ads",
    display_name: "Google Ads",
    totals: { spend: 42000, conversions: 12, cpa: 3500, clicks: 900, impressions: 40000 },
    metrics_period: "YESTERDAY",
    campaign_count: 2,
    freshness: {
      fetched_at: ago(kind === "stale" ? 11 : 0),
      stale: kind === "stale",
      stale_after_days: 2,
    },
    not_collected: null,
    daily: [],
    daily_delta: null,
  };
  return {
    client: slug,
    period: "YESTERDAY",
    periods: ["YESTERDAY"],
    non_canonical_periods: [],
    last_synced_at: ago(0),
    // The idle client is the one mureo has collected NOTHING for.
    platforms: kind === "idle" ? [] : [platform],
    platform_conflicts: [],
    recent_actions: actions || [],
    reports: {},
    observations_due: kind === "due" ? { count: 1, oldest_due: TODAY } : { count: 0 },
    display: null,
    server_today: TODAY,
  };
}

const ROSTER = [
  { slug: "alpha", name: "Alpha Trading", active: true },
  { slug: "bravo", name: "Bravo Logistics", active: true },
  { slug: "carol", name: "Carol Foods", active: true },
  { slug: "delta", name: "Delta Studio", active: true },
];

const KINDS = { alpha: "stale", bravo: "due", carol: "ok", delta: "idle" };

function rosterSummaries(actionsBySlug) {
  const out = {};
  ROSTER.forEach(function (c) {
    out[c.slug] = summaryFor(c.slug, KINDS[c.slug], (actionsBySlug || {})[c.slug]);
  });
  return out;
}

async function openIndex(options) {
  const opts = options || {};
  const clients = opts.clients || ROSTER;
  const summaries = opts.summaries || rosterSummaries(opts.actions);
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: clients, can_archive: false },
    "/api/reports/summary": (url) => {
      const m = /client=([^&]+)/.exec(url);
      const slug = m ? decodeURIComponent(m[1]) : clients[0].slug;
      return summaries[slug] || summaryFor(slug, "ok");
    },
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

/** The winning declaration for `property` on the first `sel` in the page. */
function styleOf(page, sel, property) {
  return styleOfNode(page.root.querySelector(sel), sel, property);
}

function styleOfNode(node, label, property) {
  assert.ok(node, label + " is not in the page");
  const won = cascade(node, property);
  return won ? won.value : undefined;
}

/** The band's blocks as `{key: count}`. */
function heroBlocks(page) {
  const out = {};
  page.root.querySelectorAll(".reports-hero-block").forEach(function (node) {
    const key = node.getAttribute("data-reports-hero-block");
    const value = node.querySelectorAll(".reports-hero-block-count")[0];
    out[key] = Number(value.textContent.replace(/,/g, ""));
  });
  return out;
}

/** The health filter chips' own counts, as `{key: count}`. */
function chipCounts(page) {
  const out = {};
  page.root.querySelectorAll(".reports-filter-chip").forEach(function (chip) {
    const key = chip.getAttribute("data-reports-filter");
    const value = chip.querySelectorAll(".reports-filter-count")[0];
    out[key] = Number(value.textContent.replace(/,/g, ""));
  });
  return out;
}

// ---------------------------------------------------------------------
// The model: counts of CLIENTS, from the triage layer's own answers
// ---------------------------------------------------------------------

test.describe("the band counts clients and grades none of them", function () {
  // The counts object the filter chips are built from, and the per-client
  // verdict the cards are marked with — the two inputs, passed in exactly as
  // renderReportsIndex passes them.
  function build(counts, summaries, healthOf) {
    return hero.buildReportsHero(counts, summaries, healthOf);
  }

  test.it("passes the triage layer's counts through untouched", function () {
    const model = build(
      { all: 4, attention: 1, watch: 1, ok: 2 },
      [summaryFor("a", "stale"), summaryFor("b", "due"), summaryFor("c", "ok"), summaryFor("d", "ok")],
      () => "ok"
    );
    assert.equal(model.attention, 1);
    assert.equal(model.watch, 1);
    assert.equal(model.total, 4);
  });

  test.it("splits the four blocks over the whole roster and no more", function () {
    // The blocks are a PARTITION: every client is in exactly one, so the
    // band can never state a roster the grid under it does not have.
    const model = build(
      { all: 4, attention: 1, watch: 1, ok: 2 },
      [
        summaryFor("a", "stale"),
        summaryFor("b", "due"),
        summaryFor("c", "ok"),
        summaryFor("d", "idle"),
      ],
      (i) => ["attention", "watch", "ok", "ok"][i]
    );
    assert.equal(model.ok + model.watch + model.attention + model.idle, model.total);
    assert.equal(model.idle, 1, "the client with no figures at all");
    assert.equal(model.ok, 1, "…and it is not counted as OK as well");
  });

  test.it("carves the idle block out of OK and out of nothing else", function () {
    // A client the triage layer marked keeps its mark whatever its figures
    // look like: "mureo has no figures" is not a verdict that can overrule
    // "mureo cannot state this client's totals".
    const model = build(
      { all: 2, attention: 1, watch: 0, ok: 1 },
      [summaryFor("a", "idle"), summaryFor("b", "idle")],
      (i) => (i === 0 ? "attention" : "ok")
    );
    assert.equal(model.attention, 1);
    assert.equal(model.idle, 1);
    assert.equal(model.ok, 0);
  });

  test.it("never files a client that HAS figures as not running", function () {
    const model = build(
      { all: 1, attention: 0, watch: 0, ok: 1 },
      [summaryFor("a", "ok")],
      () => "ok"
    );
    assert.equal(model.idle, 0);
    assert.equal(model.ok, 1);
  });

  test.it("keeps a withheld client's figures out of the idle block", function () {
    // A stale client HAS figures — mureo simply refuses to state them — so
    // calling it "not running" would file a data problem as an idle account.
    const stale = summaryFor("a", "stale");
    const model = build({ all: 1, attention: 0, watch: 0, ok: 1 }, [stale], () => "ok");
    assert.equal(model.idle, 0);
  });

  test.it("draws nothing at all below two clients", function () {
    const one = build({ all: 1, attention: 0, watch: 0, ok: 1 }, [summaryFor("a", "ok")], () => "ok");
    assert.equal(one.show, false);
    const two = build(
      { all: 2, attention: 0, watch: 0, ok: 2 },
      [summaryFor("a", "ok"), summaryFor("b", "ok")],
      () => "ok"
    );
    assert.equal(two.show, true);
    assert.equal(hero.REPORTS_HERO_MIN_CLIENTS, 2);
  });

  test.it("dates itself by the server and never by the browser", function () {
    const dated = build({ all: 2, ok: 2 }, [summaryFor("a", "ok"), summaryFor("b", "ok")], () => "ok");
    assert.equal(dated.date, TODAY);
    // No date stated: silence, not a guess. `statedServerDate` is
    // reports_overview.js's — one answer to "what day is it on the host".
    const undated = [summaryFor("a", "ok"), summaryFor("b", "ok")];
    undated.forEach(function (s) {
      delete s.server_today;
    });
    assert.equal(build({ all: 2, ok: 2 }, undated, () => "ok").date, null);
    assert.equal(overview.statedServerDate(undated), null);
  });

  test.it("states the four blocks in one order, stated in code", function () {
    assert.deepEqual(hero.REPORTS_HERO_BLOCKS, ["ok", "watch", "attention", "idle"]);
    const model = build({ all: 2, ok: 2 }, [summaryFor("a", "ok"), summaryFor("b", "ok")], () => "ok");
    assert.deepEqual(
      model.blocks.map(function (b) {
        return b.key;
      }),
      ["ok", "watch", "attention", "idle"]
    );
  });

  test.it("never throws on a payload it did not expect", function () {
    // This runs mid-render over a payload that may come from an older
    // daemon, and a throw here blanks the whole Reports view.
    [
      [null, null, null],
      [{ all: "many" }, "summaries", "healthOf"],
      [{ all: 2, ok: -3 }, [null, undefined], () => "ok"],
      [{}, [], undefined],
    ].forEach(function (args) {
      const model = hero.buildReportsHero(args[0], args[1], args[2]);
      assert.ok(model.total >= 0);
      assert.ok(model.ok >= 0 && model.idle >= 0);
    });
  });
});

// ---------------------------------------------------------------------
// The band on screen
// ---------------------------------------------------------------------

test.describe("the band is on the list screen", function () {
  test.it("draws the four blocks and the fraction for a roster", async function () {
    const page = await openIndex();
    const band = page.root.querySelector("[data-reports-hero]");
    assert.ok(band, "the band is in app.html");
    assert.ok(isVisible(band), "…and an operator can see it");
    const blocks = heroBlocks(page);
    assert.deepEqual(Object.keys(blocks).sort(), ["attention", "idle", "ok", "watch"]);
    // alpha stale -> attention, bravo due -> watch, carol -> ok, delta -> idle
    assert.equal(blocks.attention, 1);
    assert.equal(blocks.watch, 1);
    assert.equal(blocks.ok, 1);
    assert.equal(blocks.idle, 1);
    assert.equal(
      page.root.querySelector("[data-reports-hero-ratio]").textContent,
      "1/4"
    );
  });

  test.it("says which day it is, from the host's own clock", async function () {
    const page = await openIndex();
    const date = page.root.querySelector("[data-reports-hero-date]");
    assert.equal(date.textContent, TODAY);
    assert.ok(isVisible(date));
  });

  test.it("agrees with the filter chips, because it is the same count", async function () {
    // The whole point of the band. The chips are built from
    // `triageHealthCounts`; the band is handed that same object. `ok` splits
    // into ok + idle and into nothing else, so the two views of the roster
    // reconcile exactly.
    const page = await openIndex();
    const blocks = heroBlocks(page);
    const chips = chipCounts(page);
    assert.equal(blocks.attention, chips.attention);
    assert.equal(blocks.watch, chips.watch);
    assert.equal(blocks.ok + blocks.idle, chips.ok);
    assert.equal(blocks.ok + blocks.watch + blocks.attention + blocks.idle, chips.all);
  });

  test.it("is not drawn for a single client", async function () {
    // The staff review's decision, explicitly: one client keeps the index it
    // had. The archived row is what keeps the index reachable at all.
    const page = await openIndex({
      clients: [
        { slug: "alpha", name: "Alpha Trading", active: true },
        { slug: "gone", name: "Gone Ltd", active: true, archived: true },
      ],
      summaries: { alpha: summaryFor("alpha", "ok") },
    });
    const band = page.root.querySelector("[data-reports-hero]");
    assert.equal(band.hidden, true, "the node itself must be hidden");
    // …and app.css must not put it back: `.reports-hero` declares its own
    // `display`, which beats the UA's `[hidden] { display: none }`. That is
    // the exact defect this harness exists for.
    assert.equal(isVisible(band), false, "app.css must hide it too");
    assert.equal(page.root.querySelectorAll(".reports-hero-block").length, 0);
  });

  test.it("leaves the screen with the list it counts", async function () {
    // A roster count sitting over ONE client's report is a sentence about a
    // screen the operator has left — the same rule the portfolio strip, the
    // alert list and the rail's feed already follow.
    const page = await openIndex();
    const band = page.root.querySelector("[data-reports-hero]");
    assert.ok(isVisible(band));
    page.root.querySelector('[data-client="alpha"]').querySelectorAll("button")[0].click();
    await settle();
    assert.ok(isVisible(page.root.querySelector("[data-reports-detail]")), "on the detail");
    assert.equal(isVisible(band), false, "the band followed the operator");
  });

  test.it("carries the word beside the colour on every block", async function () {
    // Colour never carries the meaning alone on these screens.
    const page = await openIndex();
    page.root.querySelectorAll(".reports-hero-block").forEach(function (node) {
      const label = node.querySelectorAll(".reports-hero-block-label")[0];
      assert.ok(label && label.textContent.trim(), "a block with no word");
    });
  });
});

// ---------------------------------------------------------------------
// The rail: what mureo did today
// ---------------------------------------------------------------------

function action(timestamp, summary, extra) {
  return Object.assign(
    {
      timestamp: timestamp,
      action: "budget_update",
      platform: "google_ads",
      campaign_id: null,
      summary: summary,
      observation_due: null,
      display_title: null,
      display_summary: null,
    },
    extra || {}
  );
}

const LONG_LEGACY =
  "**Raised** the daily budget on Brand Search after the morning check found " +
  "the campaign capped every afternoon, and the cost per acquisition still " +
  "sitting a little under the target we agreed in April.";

test.describe("the rail says what mureo did today, one line per entry", function () {
  test.it("shows the display line the writer wrote for this row", async function () {
    const page = await openIndex({
      actions: {
        alpha: [
          action(TODAY + "T09:15:00+09:00", "a long work-journal note for the next agent", {
            display_title: "Raised the Brand Search budget",
          }),
        ],
      },
    });
    const texts = page.root.querySelectorAll(".reports-feed-text").map(function (n) {
      return n.textContent;
    });
    assert.deepEqual(texts, ["Raised the Brand Search budget"]);
  });

  test.it("strips the markdown out of an entry written before the contract", async function () {
    const page = await openIndex({
      actions: { alpha: [action(TODAY + "T09:15:00+09:00", LONG_LEGACY)] },
    });
    const text = page.root.querySelector(".reports-feed-text").textContent;
    // The reported defect: `**bold**` reaching a person as asterisks.
    assert.equal(text.indexOf("*"), -1, "asterisks reached the screen");
    assert.ok(text.startsWith("Raised the daily budget"));
    // …cut at the same 120 characters the detail view cuts it at, with the
    // whole sentence still reachable. Nothing stored is altered.
    assert.ok(text.length <= 121, "the rail is not a wall of prose: " + text.length);
    assert.ok(text.endsWith("…"));
    const body = page.root.querySelector(".reports-feed-body");
    assert.ok(body.getAttribute("title").length > text.length, "the whole line is kept");
  });

  test.it("says so in one line on a day nothing was logged", async function () {
    const page = await openIndex();
    const panel = page.root.querySelector("[data-reports-feed]");
    const empty = page.root.querySelector("[data-reports-feed-empty]");
    assert.ok(isVisible(panel), "on a roster the rail stays");
    assert.ok(isVisible(empty), "…and says the day is quiet");
    assert.equal(page.root.querySelectorAll(".reports-feed-row").length, 0);
  });

  test.it("hides the empty line the moment there is something to show", async function () {
    const page = await openIndex({
      actions: { alpha: [action(TODAY + "T09:15:00+09:00", "raised the daily budget")] },
    });
    const empty = page.root.querySelector("[data-reports-feed-empty]");
    assert.equal(isVisible(empty), false);
    assert.equal(page.root.querySelectorAll(".reports-feed-row").length, 1);
  });

  test.it("keeps the panel absent below two clients", async function () {
    // Unchanged behaviour: a single-client index is not a roster, and the
    // default there is the silence the alert layer keeps.
    const page = await openIndex({
      clients: [
        { slug: "alpha", name: "Alpha Trading", active: true },
        { slug: "gone", name: "Gone Ltd", active: true, archived: true },
      ],
      summaries: { alpha: summaryFor("alpha", "ok") },
    });
    assert.equal(isVisible(page.root.querySelector("[data-reports-feed]")), false);
  });
});

// ---------------------------------------------------------------------
// The rail: where the roster's money went
// ---------------------------------------------------------------------

test.describe("the platform bars are the stored totals and nothing else", function () {
  test.it("draws one bar per platform, summed across the roster", async function () {
    const page = await openIndex();
    const panel = page.root.querySelector("[data-reports-platforms]");
    assert.ok(isVisible(panel));
    const values = page.root.querySelectorAll(".reports-platform-value").map(function (n) {
      return n.textContent;
    });
    // carol + bravo state 42,000 each; alpha's are WITHHELD (stale) and
    // delta has none, so the bar is over the two mureo can state. A sum
    // including the withheld ones would be #638 through the back door.
    assert.deepEqual(values, ["84,000"]);
    // No currency symbol anywhere: mureo does not know the account's
    // currency, and printing one would be a claim about the money.
    values.forEach(function (v) {
      assert.match(v, /^[\d,]+$/);
    });
    assert.equal(page.root.querySelectorAll(".reports-platform-bar").length, 1);
  });
});

// ---------------------------------------------------------------------
// Token discipline
// ---------------------------------------------------------------------

test.describe("the band's colours are tokens", function () {
  const fs = require("node:fs");
  const CSS = fs.readFileSync(path.join(WEB, "app.css"), "utf-8");

  //: The band is the one surface on these screens that is dark in BOTH
  //: themes, so it has its own family rather than borrowing --surface /
  //: --ink, which invert with the theme.
  const NEW_TOKENS = [
    "--report-navy",
    "--report-navy-line",
    "--report-on-navy",
    "--report-on-navy-soft",
    "--report-navy-ok",
    "--report-navy-watch",
    "--report-navy-attention",
    "--report-navy-idle",
  ];

  test.it("defines every new token in both themes", function () {
    NEW_TOKENS.forEach(function (name) {
      const uses = CSS.split(name + ":").length - 1;
      assert.ok(uses >= 2, name + " is defined " + uses + " time(s), needs light + dark");
    });
  });

  test.it("paints the band and every block from the family", async function () {
    const page = await openIndex();
    assert.equal(styleOf(page, ".reports-hero", "background"), "var(--report-navy)");
    assert.equal(styleOf(page, ".reports-hero", "color"), "var(--report-on-navy)");
    const fills = {
      ok: "var(--report-navy-ok)",
      watch: "var(--report-navy-watch)",
      attention: "var(--report-navy-attention)",
      idle: "var(--report-navy-idle)",
    };
    Object.keys(fills).forEach(function (key) {
      const node = page.root
        .querySelectorAll(".reports-hero-block")
        .find(function (n) {
          return n.getAttribute("data-reports-hero-block") === key;
        });
      assert.equal(
        styleOfNode(node, ".reports-hero-block.is-" + key, "background"),
        fills[key],
        key + " is not painted from its token"
      );
    });
  });
});
