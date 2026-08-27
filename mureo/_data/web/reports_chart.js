// reports_chart.js — the daily chart (#706 step 3-a).
//
// reports_sparkline.js drew seven days at 72×28 as an annotation on a KPI.
// This is the same data at full size with a granularity switch, and it
// extends that file's rules rather than inventing new ones — most
// importantly the one that whole file exists for: **a day nobody collected
// is a gap, not a zero.** Plotting buckets at even intervals would quietly
// repair every gap, so points are placed by DATE and a run of days that are
// not calendar-adjacent is drawn as a break in the line.
//
// WHAT THE GRANULARITY SWITCH COSTS. Day is the stored grain. Week and month
// are SUMS of stored days, and a sum over a period that is missing days is
// not that period's total — it is the total of the days that were collected,
// which is a smaller number wearing a bigger label. #690 refused to
// zero-fill for exactly this reason, and summing would smuggle the zero back
// in one level up. So a bucket says how many of its days it actually holds
// (`days` / `expected`), the renderer marks an incomplete one, and nothing
// anywhere presents a partial week as a whole one.
//
// A month bucket for the CURRENT month is incomplete by definition — the
// month is still being spent into — and is marked like any other bucket
// missing days. Nothing special-cases "today": the rule is arithmetic over
// what is stored, and a partial period is a partial period however it got
// that way.
//
// WHAT IT REFUSES. Fewer than two plottable buckets draws nothing — the
// caller hides the whole section, frame and all. One point is not a trend.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_REPORTS_CHART`. Depends only on the DOM.

(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  //: The drawing box in user units; the viewBox scales to the CSS width, so
  //: only the aspect is fixed. Taller than the sparkline because this one is
  //: the section rather than an annotation on a figure.
  const WIDTH = 640;
  const HEIGHT = 220;
  //: Room for the stroke, the fill's baseline and the value dots.
  const PAD_X = 8;
  const PAD_TOP = 12;
  const PAD_BOTTOM = 12;

  //: Below this many buckets there is no line, and the caller draws no
  //: section — the sparkline's rule at full size.
  const MIN_POINTS = 2;

  //: The metrics the switch offers, in the order the mockup lists them.
  //: Deliberately not every canonical metric: these are the three an operator
  //: watches a trend of. Spend has its own place in the funnel row above.
  const METRICS = ["conversions", "clicks", "impressions"];

  //: The grains, coarsest last. `day` is what is stored; the other two are
  //: sums over it (see the header).
  const GRAINS = ["day", "week", "month"];

  const MS_PER_DAY = 86400000;

  /** `YYYY-MM-DD` → day number, or null. Same rule as reports_sparkline. */
  function dayNumber(text) {
    if (typeof text !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const ms = Date.parse(text + "T00:00:00Z");
    if (isNaN(ms)) return null;
    // Date.parse rolls 2026-02-30 into March, which would put a point on a
    // date nobody collected.
    const back = new Date(ms).toISOString().slice(0, 10);
    return back === text ? Math.round(ms / MS_PER_DAY) : null;
  }

  /** Day number → `YYYY-MM-DD`. */
  function dayText(day) {
    return new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  /**
   * The plottable days of `series` for `key`: `[{day, date, value}]`,
   * ascending.
   *
   * A bucket contributes only when it has a real date AND states this metric
   * as a number — everything else is left out rather than defaulted, which is
   * what makes the gaps real.
   */
  function days(series, key) {
    if (!Array.isArray(series)) return [];
    const out = [];
    series.forEach(function (bucket) {
      if (!bucket || typeof bucket !== "object") return;
      const day = dayNumber(bucket.date);
      if (day === null) return;
      const totals = bucket.totals;
      const value = totals && typeof totals === "object" ? totals[key] : undefined;
      if (!isNumber(value)) return;
      out.push({ day: day, date: bucket.date, value: value });
    });
    out.sort(function (a, b) {
      return a.day - b.day;
    });
    return out;
  }

  /** ISO week key `YYYY-Www` for a day number, and that week's Monday. */
  function weekKey(day) {
    // Day 0 (1970-01-01) was a Thursday, so +3 lands the week's Monday on a
    // multiple of 7. Doing the arithmetic on day numbers keeps this free of
    // any local timezone, which a Date-based weekday would not be.
    const monday = day - ((((day + 3) % 7) + 7) % 7);
    return { key: "W" + monday, start: monday, span: 7 };
  }

  /** Month key `YYYY-MM` for a day number, plus its first day and length. */
  function monthKey(day) {
    const d = new Date(day * MS_PER_DAY);
    const year = d.getUTCFullYear();
    const month = d.getUTCMonth();
    const first = Math.round(Date.UTC(year, month, 1) / MS_PER_DAY);
    const next = Math.round(Date.UTC(year, month + 1, 1) / MS_PER_DAY);
    return {
      key: String(year) + "-" + String(month + 1).padStart(2, "0"),
      start: first,
      span: next - first,
    };
  }

  /**
   * `days` folded to `grain`: `[{key, start, span, value, days, expected,
   * complete, label}]`, ascending.
   *
   * `day` returns each stored day as its own single-day bucket, so every
   * grain has one shape and the renderer has one code path.
   *
   * `days` counts the stored days that landed in the bucket and `expected` is
   * how many the period has, so `complete` is the honest answer to "is this
   * that period's total?". A caller that ignored it would present four
   * collected days as a week.
   */
  function buckets(dayList, grain) {
    if (grain === "day") {
      return dayList.map(function (d) {
        return {
          key: d.date,
          start: d.day,
          span: 1,
          value: d.value,
          days: 1,
          expected: 1,
          complete: true,
          label: d.date,
        };
      });
    }
    const keyOf = grain === "week" ? weekKey : monthKey;
    const order = [];
    const byKey = {};
    dayList.forEach(function (d) {
      const info = keyOf(d.day);
      if (!byKey[info.key]) {
        byKey[info.key] = {
          key: info.key,
          start: info.start,
          span: info.span,
          value: 0,
          days: 0,
          expected: info.span,
          complete: false,
          label: grain === "week" ? dayText(info.start) : info.key,
        };
        order.push(info.key);
      }
      const bucket = byKey[info.key];
      bucket.value += d.value;
      bucket.days += 1;
    });
    return order.map(function (key) {
      const bucket = byKey[key];
      bucket.complete = bucket.days === bucket.expected;
      return bucket;
    });
  }

  /**
   * `buckets` split into runs of ADJACENT buckets.
   *
   * Adjacency is by position on the calendar, not by index: two stored days a
   * week apart are two runs, and the hole between them is drawn as a hole.
   * At week and month grain the same rule applies to whole periods — a month
   * with no collected day at all is absent from the list, and the line breaks
   * across it rather than sloping through it.
   */
  function runs(list) {
    const out = [];
    let current = [];
    list.forEach(function (bucket, i) {
      if (i > 0 && bucket.start !== list[i - 1].start + list[i - 1].span) {
        out.push(current);
        current = [];
      }
      current.push(bucket);
    });
    if (current.length) out.push(current);
    return out;
  }

  /** Every bucket that is missing at least one of its days. */
  function incomplete(list) {
    return list.filter(function (bucket) {
      return !bucket.complete;
    });
  }

  function svgEl(name) {
    return document.createElementNS(SVG_NS, name);
  }

  /**
   * The chart for `list`, or `null` when there are fewer than two buckets.
   *
   * `null` and not an empty frame: the caller hides the section entirely, so
   * an install whose day-grain history has not started accumulating shows no
   * chart rather than an empty box promising one.
   *
   * The y axis starts at ZERO rather than at the series minimum. A sparkline
   * annotating a figure can afford to show shape alone; a chart this size is
   * read as magnitude, and a baseline at the minimum turns a 3% dip into a
   * cliff. The area fill under the line only makes sense against zero too.
   */
  function buildChart(list) {
    if (!Array.isArray(list) || list.length < MIN_POINTS) return null;

    const first = list[0].start;
    const last = list[list.length - 1];
    const span = last.start + last.span - first;
    let high = 0;
    list.forEach(function (b) {
      if (b.value > high) high = b.value;
    });

    const x = function (bucket) {
      // The MIDDLE of the period, which is where its total belongs: a week's
      // sum is not an event that happened on the Monday.
      const mid = bucket.start + bucket.span / 2 - first;
      if (span === 0) return WIDTH / 2;
      return PAD_X + (mid / span) * (WIDTH - PAD_X * 2);
    };
    const y = function (value) {
      const usable = HEIGHT - PAD_TOP - PAD_BOTTOM;
      if (high <= 0) return HEIGHT - PAD_BOTTOM;
      return HEIGHT - PAD_BOTTOM - (value / high) * usable;
    };

    const svg = svgEl("svg");
    svg.setAttribute("class", "reports-chart-svg");
    svg.setAttribute("viewBox", "0 0 " + WIDTH + " " + HEIGHT);
    svg.setAttribute("preserveAspectRatio", "none");
    // Decorative: every figure it plots is also in the table and the funnel
    // above, and a screen reader announcing a polyline repeats a number in a
    // form nobody can use.
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");

    // Baseline, so the fill has a visible floor at zero rather than melting
    // into the card.
    const base = svgEl("line");
    base.setAttribute("class", "reports-chart-base");
    base.setAttribute("x1", PAD_X);
    base.setAttribute("x2", WIDTH - PAD_X);
    base.setAttribute("y1", HEIGHT - PAD_BOTTOM);
    base.setAttribute("y2", HEIGHT - PAD_BOTTOM);
    svg.appendChild(base);

    runs(list).forEach(function (run) {
      if (run.length === 1) {
        // An isolated period — both neighbours uncollected. A real
        // measurement, so it is a dot; a one-point polyline paints nothing.
        const dot = svgEl("circle");
        dot.setAttribute("class", "reports-chart-point");
        dot.setAttribute("cx", x(run[0]));
        dot.setAttribute("cy", y(run[0].value));
        dot.setAttribute("r", 3);
        svg.appendChild(dot);
        return;
      }
      const coords = run.map(function (b) {
        return x(b) + "," + y(b.value);
      });
      const area = svgEl("polygon");
      area.setAttribute("class", "reports-chart-area");
      area.setAttribute(
        "points",
        x(run[0]) +
          "," +
          (HEIGHT - PAD_BOTTOM) +
          " " +
          coords.join(" ") +
          " " +
          x(run[run.length - 1]) +
          "," +
          (HEIGHT - PAD_BOTTOM)
      );
      svg.appendChild(area);
      const line = svgEl("polyline");
      line.setAttribute("class", "reports-chart-line");
      line.setAttribute("points", coords.join(" "));
      svg.appendChild(line);
    });

    // A dot on every bucket, and an incomplete one is drawn hollow — the same
    // fact the note under the chart states, at the point it is about.
    list.forEach(function (bucket) {
      const dot = svgEl("circle");
      dot.setAttribute(
        "class",
        "reports-chart-dot" + (bucket.complete ? "" : " is-partial")
      );
      dot.setAttribute("cx", x(bucket));
      dot.setAttribute("cy", y(bucket.value));
      dot.setAttribute("r", 2.5);
      svg.appendChild(dot);
    });
    return svg;
  }

  const api = {
    WIDTH: WIDTH,
    HEIGHT: HEIGHT,
    MIN_POINTS: MIN_POINTS,
    METRICS: METRICS,
    GRAINS: GRAINS,
    dayNumber: dayNumber,
    dayText: dayText,
    days: days,
    weekKey: weekKey,
    monthKey: monthKey,
    buckets: buckets,
    runs: runs,
    incomplete: incomplete,
    buildChart: buildChart,
  };

  if (typeof window !== "undefined") window.MUREO_REPORTS_CHART = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
