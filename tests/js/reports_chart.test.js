// The daily chart's arithmetic (#706 step 3-a).
//
// Run with:  node --test tests/js/*.test.js
//
// reports_sparkline.js established the rule this file extends: a day nobody
// collected is a GAP, not a zero. #690 refused to zero-fill for that reason,
// and the whole risk of adding a week/month switch is that summing days
// smuggles the zero back in one level up — four collected days presented as a
// week is a smaller number wearing a bigger label.
//
// So the arithmetic is driven directly here rather than inferred from a
// rendered <svg>: whether a bucket knows it is incomplete is the load-bearing
// fact, and it is invisible in the DOM until something chooses to draw it.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");
const chart = require(path.join(WEB, "reports_chart.js"));

/** A `daily` bucket as the wire carries it. */
function day(date, value) {
  return { date: date, totals: { conversions: value } };
}

test.describe("reading the stored days", function () {
  test.it("keeps only buckets with a real date and a real number", function () {
    const days = chart.days(
      [
        day("2026-08-03", 5),
        day("2026-02-30", 9), // a date that does not exist
        day("nonsense", 9),
        { date: "2026-08-05", totals: { conversions: "12" } }, // a string
        { date: "2026-08-06" }, // no totals
        day("2026-08-07", 7),
      ],
      "conversions"
    );
    assert.deepEqual(
      days.map(function (d) {
        return d.date;
      }),
      ["2026-08-03", "2026-08-07"]
    );
  });

  test.it("sorts ascending whatever order the wire used", function () {
    const days = chart.days([day("2026-08-07", 7), day("2026-08-03", 5)], "conversions");
    assert.deepEqual(
      days.map(function (d) {
        return d.value;
      }),
      [5, 7]
    );
  });
});

test.describe("day grain", function () {
  test.it("is one bucket per stored day, all complete", function () {
    const days = chart.days([day("2026-08-03", 5), day("2026-08-04", 6)], "conversions");
    const buckets = chart.buckets(days, "day");
    assert.equal(buckets.length, 2);
    assert.ok(buckets.every(function (b) {
      return b.complete;
    }));
  });

  test.it("breaks the line where a day is missing", function () {
    const days = chart.days(
      [day("2026-08-03", 5), day("2026-08-04", 6), day("2026-08-06", 7)],
      "conversions"
    );
    const runs = chart.runs(chart.buckets(days, "day"));
    // Two runs, not one line sloping across the hole: plotting the buckets
    // at even intervals would quietly repair every gap.
    assert.deepEqual(
      runs.map(function (r) {
        return r.length;
      }),
      [2, 1]
    );
  });
});

test.describe("week grain", function () {
  test.it("sums the days it has and says how many that was", function () {
    // 2026-08-03 is a Monday; four days of one ISO week.
    const days = chart.days(
      [
        day("2026-08-03", 1),
        day("2026-08-04", 2),
        day("2026-08-05", 3),
        day("2026-08-06", 4),
      ],
      "conversions"
    );
    const buckets = chart.buckets(days, "week");
    assert.equal(buckets.length, 1);
    assert.equal(buckets[0].value, 10);
    assert.equal(buckets[0].days, 4);
    assert.equal(buckets[0].expected, 7);
    // The load-bearing bit: four days is NOT a week's total, and the bucket
    // knows it. A caller that ignored this would print a partial week as a
    // whole one — the zero-fill #690 refused, one level up.
    assert.equal(buckets[0].complete, false);
    assert.equal(chart.incomplete(buckets).length, 1);
  });

  test.it("marks a full week complete", function () {
    const days = chart.days(
      ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
        "2026-08-08", "2026-08-09"].map(function (d, i) {
        return day(d, i + 1);
      }),
      "conversions"
    );
    const buckets = chart.buckets(days, "week");
    assert.equal(buckets.length, 1);
    assert.equal(buckets[0].complete, true);
    assert.equal(chart.incomplete(buckets).length, 0);
  });

  test.it("splits days across the Monday boundary", function () {
    // Sunday 2026-08-09 and Monday 2026-08-10 are different ISO weeks.
    const days = chart.days([day("2026-08-09", 1), day("2026-08-10", 2)], "conversions");
    assert.equal(chart.buckets(days, "week").length, 2);
  });

  test.it("breaks the line across a week nobody collected", function () {
    const days = chart.days([day("2026-08-03", 1), day("2026-08-17", 2)], "conversions");
    const buckets = chart.buckets(days, "week");
    assert.equal(buckets.length, 2);
    // The week between them has no bucket at all, and the line breaks rather
    // than sloping through a fortnight as though it were one step.
    assert.deepEqual(
      chart.runs(buckets).map(function (r) {
        return r.length;
      }),
      [1, 1]
    );
  });
});

test.describe("month grain", function () {
  test.it("uses the month's real length as the denominator", function () {
    const days = chart.days([day("2026-02-01", 1), day("2026-02-02", 2)], "conversions");
    const buckets = chart.buckets(days, "month");
    assert.equal(buckets[0].key, "2026-02");
    assert.equal(buckets[0].expected, 28, "2026 is not a leap year");
    assert.equal(buckets[0].complete, false);
  });

  test.it("keeps months apart", function () {
    const days = chart.days([day("2026-07-31", 1), day("2026-08-01", 2)], "conversions");
    const buckets = chart.buckets(days, "month");
    assert.deepEqual(
      buckets.map(function (b) {
        return b.key;
      }),
      ["2026-07", "2026-08"]
    );
  });
});

test.describe("what it refuses to draw", function () {
  test.it("draws nothing at fewer than two buckets", function () {
    // One point is not a trend, and the caller hides the whole section — no
    // empty frame promising a chart the data has not earned.
    assert.equal(chart.buildChart([]), null);
    assert.equal(
      chart.buildChart(chart.buckets(chart.days([day("2026-08-03", 5)], "conversions"), "day")),
      null
    );
  });
});
