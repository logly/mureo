// reports_sparkline.js — seven days of one metric, as a line (#691 phase 4).
//
// WHAT IT DRAWS. `daily` from #690: up to seven day-grain buckets, ascending,
// WITH THEIR GAPS INTACT. A day the collector missed is simply absent from
// the list — nothing zero-fills it, because "not collected" and "collected,
// and the answer was zero" are different facts and an invented zero reads as
// a day the account stopped spending.
//
// So this file's whole difficulty is the x axis. Plotting the buckets at
// even intervals would quietly repair every gap: a Monday and the Thursday
// before it would sit one step apart and the line between them would look
// like an ordinary day-over-day move. Points are therefore placed by DATE,
// and a run of days that are not calendar-adjacent is drawn as a break in
// the line rather than a segment across it. A gap you can see is the point.
//
// WHAT IT REFUSES. Fewer than two plottable days draws nothing at all — not
// an empty frame, not a flat line. A single point is not a trend, and a box
// reserved for a chart that never arrives is a promise the data has not
// kept. Callers append whatever this returns and get `null` when there is
// nothing honest to show, so an install whose daily history has not started
// accumulating simply has no sparklines rather than a row of empty boxes.
//
// NO PERCENTAGES ANYWHERE. #690 carries absolute differences only; a
// percentage needs a rule for a zero baseline, and this layer does not get
// to invent one.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_REPORTS_SPARKLINE`. It depends on nothing but the DOM, so it
// may load anywhere before its callers.

(function () {
  "use strict";

  //: The drawing box, in user units. The viewBox scales to whatever width
  //: CSS gives it; only the ASPECT is fixed here. 28 high because that is
  //: what a KPI card can carry under its figure without the card growing a
  //: line — the chart is an annotation on the number, not a second figure.
  const WIDTH = 72;
  const HEIGHT = 28;
  //: Half the stroke, so the extremes are not clipped by the viewBox edge.
  const PAD = 2;
  const SVG_NS = "http://www.w3.org/2000/svg";

  //: Below this many plottable points there is no line to draw.
  const MIN_POINTS = 2;

  const MS_PER_DAY = 86400000;

  /** `YYYY-MM-DD` → day number, or null if it is not a real date. */
  function dayNumber(text) {
    if (typeof text !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const ms = Date.parse(text + "T00:00:00Z");
    if (isNaN(ms)) return null;
    // Round-trip: Date.parse accepts 2026-02-30 and silently rolls it into
    // March, which would put a point at a date nobody collected.
    const back = new Date(ms).toISOString().slice(0, 10);
    return back === text ? Math.round(ms / MS_PER_DAY) : null;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  /**
   * The plottable points of `series` for `key`: `[{day, value}]`, ascending.
   *
   * A bucket contributes only when it has a real date AND states this metric
   * as a number. Everything else is left out rather than defaulted, which is
   * what makes the gaps below real gaps.
   */
  function points(series, key) {
    if (!Array.isArray(series)) return [];
    const out = [];
    series.forEach(function (bucket) {
      if (!bucket || typeof bucket !== "object") return;
      const day = dayNumber(bucket.date);
      if (day === null) return;
      const totals = bucket.totals;
      const value = totals && typeof totals === "object" ? totals[key] : undefined;
      if (!isNumber(value)) return;
      out.push({ day: day, value: value });
    });
    out.sort(function (a, b) {
      return a.day - b.day;
    });
    return out;
  }

  /**
   * `points` split into runs of calendar-adjacent days.
   *
   * Each run becomes its own polyline, so a missing day is a hole in the
   * chart instead of a straight segment pretending to be one day's move.
   */
  function runs(pts) {
    const out = [];
    let current = [];
    pts.forEach(function (point, i) {
      if (i > 0 && point.day - pts[i - 1].day !== 1) {
        out.push(current);
        current = [];
      }
      current.push(point);
    });
    if (current.length) out.push(current);
    return out;
  }

  function svgEl(name) {
    return document.createElementNS(SVG_NS, name);
  }

  /**
   * A sparkline for `key` over `series`, or `null` when there is none to draw.
   *
   * `null` rather than an empty element on purpose: the caller appends what
   * it gets, and an empty `<svg>` still occupies its box. See the file
   * header — the default state of this feature is "no history yet".
   */
  function buildSparkline(series, key) {
    const pts = points(series, key);
    if (pts.length < MIN_POINTS) return null;

    const first = pts[0].day;
    const span = pts[pts.length - 1].day - first;
    let low = pts[0].value;
    let high = pts[0].value;
    pts.forEach(function (p) {
      if (p.value < low) low = p.value;
      if (p.value > high) high = p.value;
    });
    const range = high - low;

    // A flat week is a real answer, so it draws — down the middle, because
    // pinning it to the top or bottom of the box would read as an extreme.
    const y = function (value) {
      if (range === 0) return HEIGHT / 2;
      const t = (value - low) / range;
      return HEIGHT - PAD - t * (HEIGHT - PAD * 2);
    };
    // span === 0 cannot happen at two or more points (days are distinct and
    // sorted), but dividing by it would be silent if it ever did.
    const x = function (day) {
      if (span === 0) return WIDTH / 2;
      return PAD + ((day - first) / span) * (WIDTH - PAD * 2);
    };

    const svg = svgEl("svg");
    svg.setAttribute("class", "sparkline");
    svg.setAttribute("viewBox", "0 0 " + WIDTH + " " + HEIGHT);
    svg.setAttribute("preserveAspectRatio", "none");
    // Decorative: every figure this annotates is already stated in text
    // beside it, so a screen reader announcing a polyline would be repeating
    // the number in a form nobody can use.
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");

    runs(pts).forEach(function (run) {
      if (run.length === 1) {
        // An isolated day — both neighbours missing. It is a real
        // measurement, so it is shown as a dot; a one-point polyline paints
        // nothing at all and would hide it.
        const dot = svgEl("circle");
        dot.setAttribute("class", "sparkline-gap-point");
        dot.setAttribute("cx", x(run[0].day));
        dot.setAttribute("cy", y(run[0].value));
        dot.setAttribute("r", 1.2);
        svg.appendChild(dot);
        return;
      }
      const line = svgEl("polyline");
      line.setAttribute("class", "sparkline-line");
      line.setAttribute(
        "points",
        run
          .map(function (p) {
            return x(p.day) + "," + y(p.value);
          })
          .join(" ")
      );
      svg.appendChild(line);
    });

    // Where the series ends, which is the value stated next to the chart.
    const last = pts[pts.length - 1];
    const head = svgEl("circle");
    head.setAttribute("class", "sparkline-head");
    head.setAttribute("cx", x(last.day));
    head.setAttribute("cy", y(last.value));
    head.setAttribute("r", 2);
    svg.appendChild(head);
    return svg;
  }

  const api = {
    WIDTH: WIDTH,
    HEIGHT: HEIGHT,
    MIN_POINTS: MIN_POINTS,
    dayNumber: dayNumber,
    points: points,
    runs: runs,
    buildSparkline: buildSparkline,
  };

  if (typeof window !== "undefined") window.MUREO_REPORTS_SPARKLINE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
