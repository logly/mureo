// Seven days of one metric, as a line (#691 phase 4).
//
// Run with:  node --test tests/js/*.test.js
//
// Two halves, guarded differently:
//
//   - the AXIS — where a point goes, and where the line breaks — is arithmetic
//     and is driven directly through the module. A gap rendered as an ordinary
//     segment is the failure this feature exists to avoid, and it is invisible
//     in a screenshot: the line looks perfectly plausible, it is simply about
//     days that were never collected.
//   - the SCREEN — whether anything is drawn at all, and whether a card
//     without history still looks right — goes through the real dashboard
//     against the real app.css, because "no history yet" is the DEFAULT state
//     of this feature and an empty frame is the way it breaks.
//
// The four states the spec names are covered in both halves: (a) no history,
// (b) two days, (c) seven days, (d) a week with a day missing.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { loadDashboardPage, settle, isVisible, cascade } = require("./dom_harness.js");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");
// The axis half is pure arithmetic and is required directly. The DRAWING
// half needs a document to build SVG into, so it comes from an evaluated
// page — the same bytes, reached the way the browser reaches them.
const spark = require(path.join(WEB, "reports_sparkline.js"));
const drawing = () =>
  loadDashboardPage({}).sandbox.MUREO_REPORTS_SPARKLINE;

const TODAY = new Date().toISOString().slice(0, 10);
const DAY = 86400000;

/** `n` days before today, as YYYY-MM-DD. */
const dayBefore = (n) =>
  new Date(Date.parse(TODAY + "T00:00:00Z") - n * DAY).toISOString().slice(0, 10);

/** A `daily` series from `[daysAgo, spend]` pairs, ascending. */
const series = (pairs) =>
  pairs
    .slice()
    .sort((a, b) => b[0] - a[0])
    .map(([ago, spend]) => ({
      date: dayBefore(ago),
      totals: { spend: spend, conversions: Math.round(spend / 1000) },
    }));

const WEEK = series([
  [6, 10000], [5, 12000], [4, 9000], [3, 14000], [2, 11000], [1, 15000], [0, 13000],
]);
const TWO_DAYS = series([[1, 10000], [0, 12000]]);
// Day 3 never collected — the list simply does not contain it.
const GAPPED = series([[6, 10000], [5, 12000], [4, 9000], [2, 11000], [1, 15000], [0, 13000]]);

// ---------------------------------------------------------------------
// The axis
// ---------------------------------------------------------------------

test.describe("where the points go", function () {
  test.it("refuses a date that is not one", function () {
    // Date.parse happily accepts 2026-02-30 and rolls it into March, which
    // would put a point on a day nobody collected.
    assert.equal(spark.dayNumber("2026-02-30"), null);
    assert.equal(spark.dayNumber("2026-13-01"), null);
    assert.equal(spark.dayNumber("last tuesday"), null);
    assert.equal(spark.dayNumber(""), null);
    assert.equal(spark.dayNumber(null), null);
    assert.ok(typeof spark.dayNumber("2026-02-28") === "number");
    // Adjacent days are adjacent numbers — the property `runs` depends on.
    assert.equal(spark.dayNumber("2026-03-01") - spark.dayNumber("2026-02-28"), 1);
  });

  test.it("keeps only the days that state the metric as a number", function () {
    const mixed = [
      { date: dayBefore(3), totals: { spend: 100 } },
      { date: dayBefore(2), totals: { spend: null } },
      { date: dayBefore(1), totals: {} },
      { date: dayBefore(0), totals: { spend: 400 } },
      { date: "not-a-date", totals: { spend: 999 } },
      null,
      { date: dayBefore(5) },
    ];
    assert.deepEqual(
      spark.points(mixed, "spend").map((p) => p.value),
      [100, 400],
      "a missing or non-numeric day was defaulted rather than dropped"
    );
  });

  test.it("splits a week into runs of calendar-adjacent days", function () {
    // THE POINT OF THE FEATURE. Six stored buckets, but day 3 is missing, so
    // they are not six consecutive days and must not be drawn as one line.
    const runs = spark.runs(spark.points(GAPPED, "spend"));
    assert.equal(runs.length, 2, "the gap was drawn straight through");
    assert.deepEqual(runs.map((r) => r.length), [3, 3]);

    // An unbroken week is one run.
    assert.equal(spark.runs(spark.points(WEEK, "spend")).length, 1);
  });

  test.it("places a point by its date, not by its position in the list", function () {
    // The other half of the same bug: even with the line broken, plotting by
    // index would put the two sides of a three-day gap one step apart and
    // compress the week into something that never happened.
    const pts = spark.points(GAPPED, "spend");
    const days = pts.map((p) => p.day - pts[0].day);
    assert.deepEqual(days, [0, 1, 2, 4, 5, 6], "days are not on a date axis");
  });
});

test.describe("what it draws", function () {
  const polylines = (svg) =>
    svg.children.filter((c) => c.tagName === "POLYLINE");

  let build;
  test.beforeEach(function () {
    build = drawing().buildSparkline;
  });

  test.it("draws nothing at all without at least two days", function () {
    // Not an empty frame: a box reserved for a chart that never arrives is a
    // promise the data has not kept, and this is the state every install is
    // in until daily-check has run twice.
    assert.equal(build([], "spend"), null);
    assert.equal(build(series([[0, 1000]]), "spend"), null);
    assert.equal(build(null, "spend"), null);
    assert.equal(build(undefined, "spend"), null);
    // Seven days, but none of them state THIS metric.
    assert.equal(build(WEEK, "ctr"), null);
  });

  test.it("draws one line for two days and one for an unbroken week", function () {
    assert.equal(polylines(build(TWO_DAYS, "spend")).length, 1);
    assert.equal(polylines(build(WEEK, "spend")).length, 1);
    assert.equal(
      polylines(build(WEEK, "spend"))[0]
        .getAttribute("points")
        .split(" ").length,
      7
    );
  });

  test.it("breaks the line where a day is missing", function () {
    const svg = build(GAPPED, "spend");
    const lines = polylines(svg);
    assert.equal(lines.length, 2, "the gap was bridged");
    // And the break is a real hole, not a zero-width seam: the last x of the
    // first run and the first x of the second are more than one step apart.
    const xs = (line) =>
      line.getAttribute("points").split(" ").map((p) => Number(p.split(",")[0]));
    const before = xs(lines[0]);
    const after = xs(lines[1]);
    const step = before[1] - before[0];
    assert.ok(
      after[0] - before[before.length - 1] > step * 1.5,
      "the missing day left no visible gap"
    );
  });

  test.it("marks the newest day, and only it", function () {
    const svg = build(WEEK, "spend");
    const heads = svg.children.filter(
      (c) => c.getAttribute("class") === "sparkline-head"
    );
    assert.equal(heads.length, 1);
    const line = polylines(svg)[0];
    const last = line.getAttribute("points").split(" ").pop();
    assert.equal(
      heads[0].getAttribute("cx") + "," + heads[0].getAttribute("cy"),
      last,
      "the accent is not on the last point"
    );
  });

  test.it("shows an isolated day as a dot rather than losing it", function () {
    // Both neighbours missing. A one-point polyline paints nothing, so
    // without this the day would be collected, real, and invisible.
    const lonely = series([[6, 5000], [3, 9000], [1, 7000], [0, 8000]]);
    const svg = build(lonely, "spend");
    const dots = svg.children.filter(
      (c) => c.getAttribute("class") === "sparkline-gap-point"
    );
    assert.equal(dots.length, 2, "an isolated measurement was dropped");
  });

  test.it("draws a flat week down the middle instead of at an edge", function () {
    const flat = series([[2, 8000], [1, 8000], [0, 8000]]);
    const ys = polylines(build(flat, "spend"))[0]
      .getAttribute("points")
      .split(" ")
      .map((p) => Number(p.split(",")[1]));
    ys.forEach((y) => assert.equal(y, spark.HEIGHT / 2));
  });

  test.it("stays inside its box", function () {
    const svg = build(WEEK, "spend");
    assert.equal(svg.getAttribute("viewBox"), "0 0 " + spark.WIDTH + " " + spark.HEIGHT);
    polylines(svg)[0]
      .getAttribute("points")
      .split(" ")
      .forEach(function (pair) {
        const [x, y] = pair.split(",").map(Number);
        assert.ok(x >= 0 && x <= spark.WIDTH, "x out of the box: " + x);
        assert.ok(y >= 0 && y <= spark.HEIGHT, "y out of the box: " + y);
      });
  });

  test.it("says nothing to a screen reader", function () {
    // Every figure it annotates is stated in text beside it, so announcing
    // the polyline would repeat the number in a form nobody can use.
    const svg = build(WEEK, "spend");
    assert.equal(svg.getAttribute("aria-hidden"), "true");
  });
});

// ---------------------------------------------------------------------
// On the screen
// ---------------------------------------------------------------------

const TODAY_ISO = new Date().toISOString();

function platformWith(daily, delta) {
  return {
    key: "google_ads",
    display_name: "Google Ads",
    totals: { spend: 13000, conversions: 13, cpa: 1000, ctr: 2.2, clicks: 400, impressions: 18000 },
    metrics_period: "YESTERDAY",
    campaign_count: 3,
    freshness: { fetched_at: TODAY_ISO, stale: false },
    not_collected: null,
    daily: daily || [],
    daily_delta: delta || null,
  };
}

async function openDetail(platform) {
  const page = loadDashboardPage({
    "/api/reports/clients": {
      clients: [{ slug: "alpha", name: "Alpha", active: true }],
      can_archive: false,
    },
    "/api/reports/summary": () => ({
      client: "alpha",
      period: "YESTERDAY",
      periods: ["YESTERDAY"],
      non_canonical_periods: [],
      last_synced_at: TODAY_ISO,
      platforms: [platform],
      platform_conflicts: [],
      recent_actions: [],
      reports: {},
      observations_due: { count: 0, oldest_due: null },
      server_today: TODAY,
    }),
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  page.root.querySelector('[data-dashboard-nav="reports"]').click();
  await settle();
  return page;
}

const sparks = (page) => page.root.querySelectorAll(".sparkline");
const deltas = (page) => page.root.querySelectorAll(".report-delta");

test.describe("the platform card in each of the four states", function () {
  test.it("(a) no history: no chart, no delta, and no hole where they were", async function () {
    // The state every install starts in, and the one the layout has to look
    // right in. Nothing is drawn — not a frame, not a dash, not a spacer.
    const page = await openDetail(platformWith([], null));
    const card = page.root.querySelector(".report-card");
    assert.ok(card, "the card did not render at all");
    assert.equal(sparks(page).length, 0, "an empty chart was reserved");
    assert.equal(deltas(page).length, 0, "a delta was drawn without one");
    // The card still says everything it said before this feature existed.
    assert.ok(page.root.querySelector(".report-card-headline-value"));
    assert.match(card.textContent, /13,000/);
  });

  test.it("(b) two days: a chart and, with a delta on the wire, a delta", async function () {
    const page = await openDetail(
      platformWith(TWO_DAYS, {
        from: dayBefore(1),
        to: dayBefore(0),
        metrics: { spend: 2000, cpa: -150 },
      })
    );
    assert.ok(sparks(page).length >= 1, "two days drew no chart");
    const spendDelta = page.root
      .querySelector(".report-card-headline")
      .querySelector(".report-delta");
    assert.ok(spendDelta, "no delta on the spend cell");
    assert.match(spendDelta.textContent, /↑/);
    assert.match(spendDelta.textContent, /2,000/);
  });

  test.it("(c) seven days: the chart is on the cell whose figure it explains", async function () {
    const page = await openDetail(platformWith(WEEK, null));
    const headline = page.root.querySelector(".report-card-headline");
    assert.equal(
      headline.querySelectorAll(".sparkline").length,
      1,
      "the spend cell has no spend chart"
    );
    // And it is visible, resolved against the real app.css rather than
    // assumed from the DOM.
    assert.ok(isVisible(headline.querySelector(".sparkline")));
  });

  test.it("(d) a week with a day missing: the chart is broken, not bridged", async function () {
    const page = await openDetail(platformWith(GAPPED, null));
    const svg = page.root
      .querySelector(".report-card-headline")
      .querySelector(".sparkline");
    assert.ok(svg, "no chart for a gapped week");
    assert.equal(
      svg.children.filter((c) => c.tagName === "POLYLINE").length,
      2,
      "the missing day was drawn through"
    );
  });

  test.it("withholds the chart from a row whose figures are withheld", async function () {
    // A stale row states no figures (#638). A chart of the days behind them
    // would be the same claim in a shape that is harder to argue with.
    const stale = platformWith(WEEK, {
      from: dayBefore(1),
      to: dayBefore(0),
      metrics: { spend: 2000 },
    });
    stale.freshness = { fetched_at: dayBefore(11) + "T00:00:00Z", stale: true };
    const page = await openDetail(stale);
    assert.match(page.root.querySelector(".report-card").textContent, /—/);
    const head = page.root.querySelector(".report-card-headline");
    assert.equal(
      head ? head.querySelectorAll(".sparkline").length : 0,
      0,
      "a withheld figure was given a trend line"
    );
  });
});

test.describe("the chart is an annotation, not a second figure", function () {
  test.it("is small enough not to grow the cell", async function () {
    // 28px, resolved from the real stylesheet: a chart that grew the KPI
    // cell would push the card's own figures apart.
    const page = await openDetail(platformWith(WEEK, null));
    const height = cascade(page.root.querySelector(".sparkline"), "height");
    assert.ok(height, "nothing sizes the chart");
    assert.equal(height.value, "28px", "won by: " + height.selector);
  });

  test.it("does not stretch its stroke when the box is scaled", async function () {
    // preserveAspectRatio="none" scales x and y independently, which without
    // this makes a narrow chart's line visibly fatter than a wide one's.
    const page = await openDetail(platformWith(WEEK, null));
    const line = page.root.querySelector(".sparkline-line");
    const effect = cascade(line, "vector-effect");
    assert.ok(effect, "nothing pins the stroke scaling");
    assert.equal(effect.value, "non-scaling-stroke");
  });
});

test.describe("a delta only where one was measured", function () {
  test.it("says nothing when the server declined to compare", async function () {
    // `daily_delta: null` is #690 refusing — fewer than two days, a calendar
    // gap, or no shared metric. All three mean the comparison cannot honestly
    // be made, so there is nothing to render and nothing is rendered.
    const page = await openDetail(platformWith(WEEK, null));
    assert.equal(deltas(page).length, 0, "a delta was invented from a null");
  });

  test.it("states an absolute difference and never a percentage", async function () {
    // #690 carries absolute differences only; a percentage needs a rule for a
    // zero baseline that nothing in the product has chosen.
    const page = await openDetail(
      platformWith(WEEK, {
        from: dayBefore(1),
        to: dayBefore(0),
        metrics: { spend: 2000, cpa: -150 },
      })
    );
    const text = page.root
      .querySelector(".report-card-headline")
      .querySelector(".report-delta").textContent;
    assert.match(text, /2,000/);
    assert.ok(!/%/.test(text), "a percentage reached the delta: " + text);
  });

  test.it("colours only the axes where a direction means something", async function () {
    // The #694 finding: every delta arrived red, including a spend rise, and
    // a colour that is always on says nothing. Spend is volume — up is
    // neither good nor bad without a target nobody has put on the wire.
    const page = await openDetail(
      platformWith(WEEK, {
        from: dayBefore(1),
        to: dayBefore(0),
        metrics: { spend: 2000, cpa: -150 },
      })
    );
    const spend = page.root
      .querySelector(".report-card-headline")
      .querySelector(".report-delta");
    const cpa = page.root
      .querySelector(".report-card-second")
      .querySelector(".report-delta");
    assert.ok(spend.classList.contains("is-flat"), "a spend rise was given a verdict");
    // CPA falling is good news, and is the one axis where that is unambiguous.
    assert.ok(cpa.classList.contains("is-good"), "a CPA fall was not good news");
    const tone = cascade(cpa.querySelector(".report-delta-move"), "color");
    assert.match(tone.value, /--status-ok/, "won by: " + tone.selector);
  });

  test.it("carries the direction as a character, not as colour alone", async function () {
    const page = await openDetail(
      platformWith(WEEK, {
        from: dayBefore(1),
        to: dayBefore(0),
        metrics: { spend: -500 },
      })
    );
    assert.match(
      page.root
        .querySelector(".report-card-headline")
        .querySelector(".report-delta").textContent,
      /↓/
    );
  });
});

// ---------------------------------------------------------------------
// The roster table stays a table
// ---------------------------------------------------------------------

test.describe("the roster carries neither, and that is the decision", function () {
  // NOT a row-height compromise — a data one. #690's history is PER PLATFORM,
  // and a roster row is per CLIENT. Giving a row a trend would mean summing
  // `daily`/`daily_delta` across a client's platforms, and the moment one of
  // them has a day the other does not, that sum is a number nobody measured
  // presented as the client's own. It is the same line `aggregateClientKpis`
  // already holds for the window rollup, one level down.
  //
  // The 44px row is the second reason and would have been survivable alone;
  // this one is not, so the column stays as it is and this pins it.

  async function openRoster(daily) {
    const clients = [
      { slug: "alpha", name: "Alpha", active: true },
      { slug: "bravo", name: "Bravo", active: true },
    ];
    const page = loadDashboardPage({
      "/api/reports/clients": { clients: clients, can_archive: false },
      "/api/reports/summary": (url) => {
        const m = /client=([^&]+)/.exec(url);
        const slug = m ? decodeURIComponent(m[1]) : "alpha";
        return {
          client: slug,
          period: "YESTERDAY",
          periods: ["YESTERDAY"],
          non_canonical_periods: [],
          last_synced_at: TODAY_ISO,
          platforms: [
            platformWith(daily, {
              from: dayBefore(1),
              to: dayBefore(0),
              metrics: { spend: 2000, cpa: -150 },
            }),
          ],
          platform_conflicts: [],
          recent_actions: [],
          reports: {},
          observations_due: { count: 0, oldest_due: null },
          server_today: TODAY,
        };
      },
    });
    page.document.dispatchEvent({ type: "mureo:ready" });
    await settle();
    page.root.querySelector('[data-dashboard-nav="reports"]').click();
    await settle();
    return page;
  }

  test.it("draws no chart and no delta in a row, even with a full week behind it", async function () {
    const page = await openRoster(WEEK);
    const rows = page.root.querySelectorAll(".roster-row");
    assert.ok(rows.length >= 2, "the table did not render");
    rows.forEach(function (row) {
      assert.equal(row.querySelectorAll(".sparkline").length, 0);
      assert.equal(row.querySelectorAll(".report-delta").length, 0);
    });
  });

  test.it("keeps the row at the height the density depends on", async function () {
    const page = await openRoster(WEEK);
    const height = cascade(page.root.querySelector(".roster-row"), "height");
    assert.ok(height, "nothing sets a row height");
    assert.equal(height.value, "44px", "won by: " + height.selector);
  });
});
