// dashboard_reports_chart.js — the daily-trend section (#706 step 3-a).
//
// Split out of dashboard_reports_detail.js to keep both files inside the
// repo's size budget, and it is the natural seam: this is the one part of
// the detail screen with STATE of its own — which metric, which granularity
// — and therefore its own redraw loop. Everything else on that screen is a
// pure function of the summary.
//
// The arithmetic (what a bucket is, which days it holds, where the line
// breaks) is reports_chart.js, where the JS suite drives it directly. This
// file is only the section around it: the two tab strips, the svg, and the
// note that says when a week or a month is missing days.
//
// A CHART THAT CANNOT BE DRAWN HAS NO SECTION. Fewer than two buckets hides
// the frame, the tabs and all — tabs above an empty box offer to re-slice
// data that does not exist, and a reserved frame is a promise the history
// has not kept. That is the DEFAULT state of a fresh install, so it is the
// one the layout has to look right in.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_CHART`. Loads AFTER reports_chart.js and
// BEFORE dashboard_reports_detail.js.

(function () {
  "use strict";

  const CHART = window.MUREO_REPORTS_CHART;
  if (!CHART) {
    throw new Error(
      "dashboard_reports_chart.js needs MUREO_REPORTS_CHART — load " +
        "reports_chart.js BEFORE dashboard_reports_chart.js"
    );
  }

  function el(tag, className, textContent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textContent != null) node.textContent = textContent;
    return node;
  }

  //: Which metric and which grain the chart is showing. Module state rather
  //: than a re-read of the DOM, so a re-render for another reason (a period
  //: switch, a status poll) does not silently reset the operator's choice.
  const CHART_STATE = { metric: "conversions", grain: "day" };

  function renderChartTabs(wrap, values, active, labelFor, onPick) {
    wrap.textContent = "";
    values.forEach(function (value) {
      const btn = el(
        "button",
        "reports-chart-tab" + (value === active ? " is-active" : ""),
        labelFor(value)
      );
      btn.type = "button";
      btn.setAttribute("data-chart-option", value);
      btn.setAttribute("aria-pressed", value === active ? "true" : "false");
      btn.addEventListener("click", function () {
        onPick(value);
      });
      wrap.appendChild(btn);
    });
  }

  /**
   * The chart section, or `false` when there is nothing honest to draw.
   *
   * Fewer than two buckets hides the SECTION, not just the svg — the tabs
   * would otherwise sit above an empty box, offering to re-slice data that
   * does not exist. That is the default state of a fresh install.
   *
   * A grain whose buckets are missing days states so under the chart. #690
   * refused to zero-fill a day nobody collected; summing days into a week
   * would smuggle that zero back one level up, so a partial week is marked
   * rather than presented as a whole one.
   */
  function renderChart(platform, redraw) {
    const block = document.querySelector("[data-reports-chart]");
    const body = document.querySelector("[data-reports-chart-body]");
    const metricTabs = document.querySelector("[data-reports-chart-metrics]");
    const grainTabs = document.querySelector("[data-reports-chart-grains]");
    const note = document.querySelector("[data-reports-chart-note]");
    if (!block || !body) return false;
    body.textContent = "";
    if (note) note.textContent = "";
    // Cleared up front: a metric with no history must not keep the previous
    // metric's ticks sitting beside an empty plot.
    ["[data-reports-chart-yaxis]", "[data-reports-chart-xaxis]"].forEach(function (
      sel
    ) {
      const axis = document.querySelector(sel);
      if (axis) axis.textContent = "";
    });

    const dayList = CHART.days(platform && platform.daily, CHART_STATE.metric);
    const buckets = CHART.buckets(dayList, CHART_STATE.grain);
    if (buckets.length < CHART.MIN_POINTS) {
      // The metric the operator picked may have no history while another
      // does, so the section stays visible with a note IF any metric can be
      // drawn at all — otherwise it goes entirely.
      const anyDrawable = CHART.METRICS.some(function (key) {
        return CHART.days(platform && platform.daily, key).length >= CHART.MIN_POINTS;
      });
      if (!anyDrawable) {
        block.hidden = true;
        return false;
      }
      block.hidden = false;
      if (metricTabs) {
        renderChartTabs(
          metricTabs,
          CHART.METRICS,
          CHART_STATE.metric,
          function (key) {
            return MUREO.t("dashboard.reports_kpi_" + key);
          },
          function (key) {
            CHART_STATE.metric = key;
            redraw();
          }
        );
      }
      if (grainTabs) {
        renderChartTabs(
          grainTabs,
          CHART.GRAINS,
          CHART_STATE.grain,
          function (grain) {
            return MUREO.t("dashboard.reports_grain_" + grain);
          },
          function (grain) {
            CHART_STATE.grain = grain;
            redraw();
          }
        );
      }
      if (note) note.textContent = MUREO.t("dashboard.reports_chart_no_metric");
      return true;
    }

    block.hidden = false;
    if (metricTabs) {
      renderChartTabs(
        metricTabs,
        CHART.METRICS,
        CHART_STATE.metric,
        function (key) {
          return MUREO.t("dashboard.reports_kpi_" + key);
        },
        function (key) {
          CHART_STATE.metric = key;
          redraw();
        }
      );
    }
    if (grainTabs) {
      renderChartTabs(
        grainTabs,
        CHART.GRAINS,
        CHART_STATE.grain,
        function (grain) {
          return MUREO.t("dashboard.reports_grain_" + grain);
        },
        function (grain) {
          CHART_STATE.grain = grain;
          redraw();
        }
      );
    }
    const svg = CHART.buildChart(buckets);
    if (svg) body.appendChild(svg);
    renderAxes(buckets);
    if (note) {
      const partial = CHART.incomplete(buckets);
      note.textContent = partial.length
        ? MUREO.t("dashboard.reports_chart_partial", { n: partial.length })
        : "";
    }
    return true;
  }

  /**
   * The two axes, as text beside and under the plot.
   *
   * Deliberately the ENDPOINTS only — the y scale's top and its zero, and
   * the first and last period on the x — rather than a full set of ticks.
   * The chart is read for shape and magnitude, and a grid of numbers under a
   * 220px plot competes with the funnel above it for the same attention.
   *
   * The y axis is labelled 0 to the series maximum because that is the scale
   * `buildChart` actually draws: it starts at zero rather than at the series
   * minimum, so a 3% dip is a 3% dip and the area fill has a floor that
   * means something.
   */
  function renderAxes(buckets) {
    const yAxis = document.querySelector("[data-reports-chart-yaxis]");
    const xAxis = document.querySelector("[data-reports-chart-xaxis]");
    if (yAxis) {
      yAxis.textContent = "";
      let high = 0;
      buckets.forEach(function (b) {
        if (b.value > high) high = b.value;
      });
      yAxis.appendChild(el("span", "reports-chart-tick", formatTick(high)));
      yAxis.appendChild(el("span", "reports-chart-tick", "0"));
    }
    if (xAxis) {
      xAxis.textContent = "";
      if (buckets.length) {
        xAxis.appendChild(
          el("span", "reports-chart-tick", axisLabel(buckets[0].label))
        );
        xAxis.appendChild(
          el(
            "span",
            "reports-chart-tick",
            axisLabel(buckets[buckets.length - 1].label)
          )
        );
      }
    }
  }

  /** A bucket's label as an axis tick: `2026-08-01` → `8/01`, `2026-08` → `8月`. */
  function axisLabel(label) {
    const day = /^\d{4}-(\d{2})-(\d{2})$/.exec(label);
    if (day) return String(Number(day[1])) + "/" + day[2];
    const month = /^\d{4}-(\d{2})$/.exec(label);
    if (month) return MUREO.t("dashboard.reports_chart_month", { n: Number(month[1]) });
    return label;
  }

  /** A y tick. Integers stay integers; a fraction keeps one decimal. */
  function formatTick(value) {
    if (typeof value !== "number" || !isFinite(value)) return "";
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }

  const api = {
    CHART_STATE: CHART_STATE,
    renderAxes: renderAxes,
    axisLabel: axisLabel,
    renderChartTabs: renderChartTabs,
    renderChart: renderChart,
  };

  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_CHART = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
