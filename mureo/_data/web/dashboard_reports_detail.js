// dashboard_reports_detail.js — the contract-driven detail view (#706 step 3-a).
//
// One client's screen, built from `summary.display` instead of from the
// agent's prose. The order down the page IS the argument, and it is the
// staff mockup's: what to do today, then the funnel, then the trend, then
// what mureo proposes, then the tables, then the values the report stated,
// then the log. Numbers and charts first; every piece of text on it arrived
// bounded.
//
// TWO SCREENS, ONE FILE. A client with a contract gets everything below; a
// client without one gets the three-tier view that shipped before this, and
// that is not a fallback or a deprecation — it is every client on every
// install until a skill writes a contract, and it stays correct. The switch
// is `hasDisplay`, made once, in renderReportsDetail.
//
// NOTHING HERE INVENTS A FIGURE. The funnel is derived from the canonical
// totals (that is why #706 kept it OUT of the contract — no agent writes it,
// so no agent can state it wrongly), and a metric the totals do not carry
// renders as an em dash rather than as a zero. The chart is the stored
// day-grain history with its gaps intact. Everything else is the contract,
// printed as written.
//
// AND NOTHING DRAWS AN EMPTY FRAME. Every section below hides itself when it
// has nothing — no zero rows, no "0 proposals", no chart box waiting for
// history. On this screen that is the COMMON case, not the edge one.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_DETAIL`. Loads AFTER
// dashboard_reports_report.js and BEFORE dashboard_reports.js.

(function () {
  "use strict";

  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  const DISPLAY = window.MUREO_REPORTS_DISPLAY;
  const DETAIL_CHART = window.MUREO_DASHBOARD_REPORTS_CHART;
  if (!REPORTS_SHARED || !DISPLAY || !DETAIL_CHART) {
    throw new Error(
      "dashboard_reports_detail.js needs MUREO_DASHBOARD_REPORTS_STATE, " +
        "MUREO_REPORTS_DISPLAY and MUREO_DASHBOARD_REPORTS_CHART — load " +
        "dashboard_reports_state.js, reports_display.js and " +
        "dashboard_reports_chart.js BEFORE dashboard_reports_detail.js"
    );
  }
  const relativeAge = REPORTS_SHARED.relativeAge;
  const formatNumber = REPORTS_SHARED.formatNumber;
  const formatKpi = REPORTS_SHARED.formatKpi;
  const latestReport = REPORTS_SHARED.latestReport;

  //: What a figure mureo cannot state looks like. One character, one place —
  //: a zero here would be a measurement nobody made.
  const NO_VALUE = "—";

  //: The funnel, left to right, with the secondary figure each step carries.
  //: The chain is the shape of the account: money buys impressions, some are
  //: clicked, some convert. Each secondary is the RATE between that step and
  //: the spend above it, which is the number an operator acts on.
  const FUNNEL = [
    // `sub: "delta"` — spend has no ratio to state, so its secondary figure
    // is how it moved against the day before. Read out of the stored days
    // rather than back-calculated (see deltaEndpoints), and painted blue
    // rather than red or green: a rise in spend is neither good nor bad
    // without a target nobody has put on the wire.
    { key: "spend", label: "dashboard.reports_kpi_spend", sub: "delta" },
    { key: "impressions", label: "dashboard.reports_kpi_impressions", sub: "cpm" },
    { key: "clicks", label: "dashboard.reports_kpi_clicks", sub: "cpc" },
    { key: "conversions", label: "dashboard.reports_kpi_conversions", sub: "cpa" },
  ];

  //: How many open proposals the panel shows before collapsing to a count.
  //: The panel answers "what is still owed", and a list of twelve is not an
  //: answer to that.
  const PROPOSAL_CAP = 4;

  function el(tag, className, textContent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textContent != null) node.textContent = textContent;
    return node;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function totalsOf(platform) {
    const totals = platform && platform.totals;
    return totals && typeof totals === "object" ? totals : {};
  }

  // --------------------------------------------------------------------
  // Platform selection
  // --------------------------------------------------------------------

  /**
   * The platform whose figures the funnel and the chart describe.
   *
   * ONE platform, never a sum. Adding two platforms' impressions is
   * arithmetic nobody asked for, and their CPAs cannot be added at all — the
   * same reason #533 withholds a client total whose rows must not be added.
   * So the screen states which platform it is showing and offers a switch.
   *
   * The remembered choice wins when the client still has it; otherwise the
   * first platform does, because a selector pointing at a platform this
   * client does not have would render an empty screen with no way out.
   */
  function pickPlatform(platforms, preferred) {
    const rows = Array.isArray(platforms) ? platforms : [];
    if (rows.length === 0) return null;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i].key === preferred) return rows[i];
    }
    return rows[0];
  }

  /**
   * The platform switch, or nothing when there is no choice to offer.
   *
   * A `<select>` rather than the period toggle's buttons: a client can carry
   * a dozen platforms and a dozen buttons is a second navigation bar.
   */
  function renderPlatformPicker(platforms, selected, onPick) {
    const wrap = document.querySelector("[data-reports-detail-platform]");
    if (!wrap) return;
    wrap.textContent = "";
    const rows = Array.isArray(platforms) ? platforms : [];
    // One platform is not a choice; the funnel below already names it.
    if (rows.length < 2) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    const label = el("span", "sr-only", MUREO.t("dashboard.reports_platform_pick"));
    const select = el("select", "reports-platform-select");
    select.setAttribute("aria-label", MUREO.t("dashboard.reports_platform_pick"));
    rows.forEach(function (p) {
      if (!p || typeof p !== "object") return;
      const option = document.createElement("option");
      option.value = p.key || "";
      option.textContent = p.display_name || p.key || "";
      if (selected && p.key === selected.key) option.selected = true;
      select.appendChild(option);
    });
    select.addEventListener("change", function () {
      onPick(select.value);
    });
    wrap.appendChild(label);
    wrap.appendChild(select);
  }

  // --------------------------------------------------------------------
  // (0) Who this screen is about
  // --------------------------------------------------------------------

  //: Highlight tone → the health the badge states. The three-level
  //: vocabulary the client index already uses, and its labels
  //: (`dashboard.reports_health_*`), so one client is not "watch" on the
  //: grid and something else on its own page.
  const HEALTH_BY_TONE = { bad: "attention", watch: "watch", good: "ok" };
  const HEALTH_RANK = ["attention", "watch", "ok"];

  /**
   * The client's health, from the contract's own highlights, or `null`.
   *
   * Read off the highlights rather than recomputed, because the skill that
   * wrote them already graded every finding — deriving a second verdict here
   * would let the badge disagree with the chips directly under it. The worst
   * tone present wins, which is how the index ranks a client too.
   *
   * `null` without a contract: there is nothing to grade, and a badge
   * asserting "nothing raised" over a screen mureo has no verdict for would
   * be worse than no badge.
   */
  function clientHealth(summary) {
    const chips = DISPLAY.highlights(summary);
    if (!DISPLAY.hasDisplay(summary) || chips.length === 0) return null;
    let worst = HEALTH_RANK.length - 1;
    chips.forEach(function (chip) {
      const rank = HEALTH_RANK.indexOf(HEALTH_BY_TONE[chip.tone]);
      if (rank !== -1 && rank < worst) worst = rank;
    });
    return HEALTH_RANK[worst];
  }

  /** Draw the health badge beside the client's name, or hide it. */
  function renderHealthBadge(summary) {
    const badge = document.querySelector("[data-reports-detail-health]");
    if (!badge) return;
    const health = clientHealth(summary);
    if (!health) {
      badge.hidden = true;
      badge.textContent = "";
      return;
    }
    badge.hidden = false;
    badge.className = "reports-detail-health is-" + health;
    badge.textContent = MUREO.t("dashboard.reports_health_" + health);
  }

  // --------------------------------------------------------------------
  // (1) The navigation banner
  // --------------------------------------------------------------------

  /**
   * The one operator-facing line, plus who wrote the screen and when.
   *
   * Hidden ENTIRELY when the contract states no `nav_message` — a banner
   * with no line in it is a coloured bar that says nothing, which is worse
   * than no bar. The attribution rides in the same band because it is about
   * the same thing: this is one skill's answer, at one moment.
   */
  function renderNavBanner(summary) {
    const band = document.querySelector("[data-reports-nav]");
    const textSlot = document.querySelector("[data-reports-nav-text]");
    const bySlot = document.querySelector("[data-reports-nav-by]");
    if (!band || !textSlot) return;
    const message = DISPLAY.navMessage(summary);
    if (!message) {
      band.hidden = true;
      textSlot.textContent = "";
      if (bySlot) bySlot.textContent = "";
      return;
    }
    band.hidden = false;
    textSlot.textContent = message;
    if (!bySlot) return;
    bySlot.textContent = attributionText(summary) || "";
  }

  /**
   * "daily-check updated this 3 hours ago", or `null`.
   *
   * The contract is replaced whole by whoever writes it last, so this is the
   * one question its content cannot answer about itself. A contract written
   * before the attribution fields existed has neither, and says nothing
   * rather than guessing.
   */
  function attributionText(summary) {
    const info = DISPLAY.attribution(summary);
    if (!info) return null;
    if (info.source && info.generatedAt) {
      return MUREO.t("dashboard.reports_display_by", {
        source: info.source,
        ago: relativeAge(info.generatedAt),
      });
    }
    if (info.source) {
      return MUREO.t("dashboard.reports_display_by_unknown_time", {
        source: info.source,
      });
    }
    return MUREO.t("dashboard.reports_display_at", {
      ago: relativeAge(info.generatedAt),
    });
  }

  // --------------------------------------------------------------------
  // (2) The KPI funnel
  // --------------------------------------------------------------------

  /**
   * How spend moved against the day before, or `null`.
   *
   * Taken from `daily_delta` — which the server states ONLY when two
   * calendar-adjacent days are stored (#690), so a gap is never rendered as
   * a day-over-day move. Absolute, never a percentage: a percentage needs a
   * rule for a zero baseline and #690 deliberately carries none, so
   * inventing one here would be this layer making up the very thing the
   * server refused to.
   */
  function spendDelta(platform) {
    const delta = platform && platform.daily_delta;
    const metrics = delta && typeof delta === "object" ? delta.metrics : null;
    const moved = metrics && typeof metrics === "object" ? metrics.spend : undefined;
    return isNumber(moved) && moved !== 0 ? moved : null;
  }

  /** CPM / CPC / CPA from the canonical totals, or `null`. */
  function secondaryValue(totals, kind) {
    const spend = totals.spend;
    if (!isNumber(spend)) return null;
    if (kind === "cpm") {
      return isNumber(totals.impressions) && totals.impressions > 0
        ? (spend / totals.impressions) * 1000
        : null;
    }
    if (kind === "cpc") {
      return isNumber(totals.clicks) && totals.clicks > 0
        ? spend / totals.clicks
        : null;
    }
    if (kind === "cpa") {
      // A stated CPA wins over a derived one: the collector computed it from
      // the platform's own conversion definition, which this layer cannot
      // see. Dividing anyway would print a different number from the one the
      // platform card shows for the same window.
      if (isNumber(totals.cpa)) return totals.cpa;
      return isNumber(totals.conversions) && totals.conversions > 0
        ? spend / totals.conversions
        : null;
    }
    return null;
  }

  /**
   * The four funnel cards, or `false` when the platform states nothing.
   *
   * Derived here rather than written by an agent — that is exactly why #706
   * kept the funnel out of the contract. A step the totals do not carry
   * shows an em dash: the chain is the shape of the account and dropping a
   * link would hide that a stage was never measured.
   */
  function renderFunnel(platform) {
    const block = document.querySelector("[data-reports-funnel]");
    const body = document.querySelector("[data-reports-funnel-body]");
    if (!block || !body) return false;
    body.textContent = "";
    const totals = totalsOf(platform);
    const stated = FUNNEL.filter(function (step) {
      return isNumber(totals[step.key]);
    });
    if (stated.length === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    FUNNEL.forEach(function (step, index) {
      if (index > 0) {
        const arrow = el("span", "reports-funnel-arrow", "\u276F");
        arrow.setAttribute("aria-hidden", "true");
        body.appendChild(arrow);
      }
      const card = el("div", "reports-funnel-card");
      card.appendChild(el("span", "reports-funnel-label", MUREO.t(step.label)));
      const value = isNumber(totals[step.key])
        ? formatKpi(step.key, totals[step.key])
        : NO_VALUE;
      card.appendChild(el("span", "reports-funnel-value", value));
      if (step.sub === "delta") {
        const moved = spendDelta(platform);
        if (moved !== null) {
          card.appendChild(
            el(
              "span",
              "reports-funnel-delta",
              (moved > 0 ? "\u2191 +" : "\u2193 ") +
                formatNumber(Math.round(Math.abs(moved) * (moved > 0 ? 1 : -1)))
            )
          );
        }
      } else if (step.sub) {
        const sub = secondaryValue(totals, step.sub);
        const subEl = el("span", "reports-funnel-sub");
        subEl.appendChild(
          el(
            "span",
            "reports-funnel-sub-label",
            MUREO.t("dashboard.reports_rate_" + step.sub)
          )
        );
        subEl.appendChild(
          el(
            "span",
            "reports-funnel-sub-value",
            sub === null ? NO_VALUE : formatNumber(Math.round(sub))
          )
        );
        card.appendChild(subEl);
      }
      body.appendChild(card);
    });
    return true;
  }

  // --------------------------------------------------------------------
  // (4) Proposals
  // --------------------------------------------------------------------

  /**
   * `2026-08-26` → `08/26`, and anything else through unchanged.
   *
   * Only a full ISO date is shortened. The contract imposes no format on
   * this field (mureo displays it and never parses it), so a writer's
   * `last week` stays exactly as written rather than being mangled by a
   * rule that was not meant for it.
   */
  function shortDate(value) {
    const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(value);
    return match ? match[1] + "/" + match[2] : value;
  }

  /** The proposals panel, or `false` when the contract states none. */
  function renderProposals(summary) {
    const block = document.querySelector("[data-reports-proposals]");
    const list = document.querySelector("[data-reports-proposals-list]");
    const count = document.querySelector("[data-reports-proposals-count]");
    if (!block || !list) return false;
    list.textContent = "";
    if (count) count.textContent = "";
    const groups = DISPLAY.proposalGroups(summary, summary && summary.server_today);
    if (groups.open.length === 0 && groups.doneTotal === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    if (count) {
      // Two counts, and the monthly one is omitted rather than zeroed when
      // mureo does not know what month it is (no `server_today`) — "none this
      // month" and "no idea what month this is" are different statements.
      //
      // Built as nodes rather than as one string so the FIGURES can carry
      // the emphasis the mockup gives them while their captions stay quiet.
      count.textContent = "";
      const template =
        groups.doneThisMonth === null
          ? MUREO.t("dashboard.reports_proposals_done_total", { total: "\u0000" })
          : MUREO.t("dashboard.reports_proposals_done", {
              month: "\u0000",
              total: "\u0001",
            });
      const figures = groups.doneThisMonth === null
        ? [String(groups.doneTotal)]
        : [String(groups.doneThisMonth), String(groups.doneTotal)];
      template.split(/([\u0000\u0001])/).forEach(function (part) {
        if (part === "\u0000") count.appendChild(el("b", null, figures[0]));
        else if (part === "\u0001") count.appendChild(el("b", null, figures[1]));
        else if (part) count.appendChild(document.createTextNode(part));
      });
    }
    groups.open.slice(0, PROPOSAL_CAP).forEach(function (entry) {
      const li = el("li", "reports-proposal");
      const head = el("div", "reports-proposal-head");
      head.appendChild(el("p", "reports-proposal-title", entry.title));
      if (entry.date) {
        // Short in the corner, whole on the attribute. `2026-08-26` wrapped
        // onto two lines against the card's right edge in the capture, and a
        // card whose date is taller than its title reads as a date with a
        // note attached. Nothing is altered: the stored value is what the
        // title carries, and the shortening is a display decision about an
        // unchanged string.
        const date = el("span", "reports-proposal-date", shortDate(entry.date));
        date.title = entry.date;
        head.appendChild(date);
      }
      li.appendChild(head);
      if (entry.body) li.appendChild(el("p", "reports-proposal-body", entry.body));
      list.appendChild(li);
    });
    if (groups.open.length > PROPOSAL_CAP) {
      const more = el(
        "li",
        "reports-proposal-more",
        MUREO.t("dashboard.reports_proposals_more", {
          n: groups.open.length - PROPOSAL_CAP,
        })
      );
      list.appendChild(more);
    }
    return true;
  }

  // --------------------------------------------------------------------
  // (5) Breakdown tables
  // --------------------------------------------------------------------

  function breakdownCell(value, kind) {
    const td = el("td", "reports-breakdown-num");
    td.textContent = value === null ? NO_VALUE : formatKpi(kind, Math.round(value));
    return td;
  }

  /** One breakdown table, or `false` when the contract holds no rows. */
  function renderBreakdown(summary, level, blockAttr, bodyAttr) {
    const block = document.querySelector("[" + blockAttr + "]");
    const body = document.querySelector("[" + bodyAttr + "]");
    if (!block || !body) return false;
    body.textContent = "";
    const rows = DISPLAY.breakdownRows(summary, level);
    if (rows.length === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    rows.forEach(function (row) {
      const tr = el("tr", "reports-breakdown-row");
      const th = el("th", "reports-breakdown-name", row.name);
      th.scope = "row";
      tr.appendChild(th);
      tr.appendChild(breakdownCell(row.spend, "spend"));
      tr.appendChild(breakdownCell(row.mcpa, "cpa"));
      tr.appendChild(breakdownCell(row.target_cpa, "cpa"));
      const stateCell = el("td", "reports-breakdown-state");
      if (row.state) {
        // A state outside the closed vocabulary keeps its own word rather
        // than rendering as the untranslated i18n key. It cannot arrive
        // through the write tool, but a hand-edited STATE.json is read
        // tolerantly by design, and `dashboard.reports_state_xyz` on screen
        // would be worse than the operator's own text.
        const known = Object.prototype.hasOwnProperty.call(
          DISPLAY.STATE_CLASS,
          row.state
        );
        stateCell.appendChild(
          el(
            "span",
            "reports-state-badge " + row.stateKind,
            known ? MUREO.t("dashboard.reports_state_" + row.state) : row.state
          )
        );
      } else {
        stateCell.textContent = NO_VALUE;
      }
      tr.appendChild(stateCell);
      tr.appendChild(el("td", "reports-breakdown-note", row.note || ""));
      body.appendChild(tr);
    });
    return true;
  }

  // --------------------------------------------------------------------
  // (6) Stated values and highlights
  // --------------------------------------------------------------------

  /**
   * The chip row of what the report stated, or `false`.
   *
   * Chips, not the label/value TABLE the legacy path draws
   * (`reportSecondaryStats`). The table exists because a free-form report can
   * state anything, so the reader has to re-parse where each label ends; a
   * contract's stated values arrived bounded — a caption of at most 24
   * characters and a figure — so they fit the shape the mockup draws. The two
   * are mutually exclusive by design; see renderReportsDetail.
   */
  function renderStatedValues(summary) {
    const block = document.querySelector("[data-reports-stated]");
    const body = document.querySelector("[data-reports-stated-body]");
    if (!block || !body) return false;
    body.textContent = "";
    const rows = DISPLAY.statedValues(summary);
    if (rows.length === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    rows.forEach(function (row) {
      const chip = el("div", "reports-stated-chip");
      chip.appendChild(el("span", "reports-stated-label", row.label));
      chip.appendChild(el("span", "reports-stated-value", row.value));
      body.appendChild(chip);
    });
    return true;
  }

  /** The highlight chips, or `false`. */
  function renderHighlights(summary) {
    const block = document.querySelector("[data-reports-highlights]");
    if (!block) return false;
    block.textContent = "";
    const rows = DISPLAY.highlights(summary);
    if (rows.length === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    rows.forEach(function (row) {
      block.appendChild(el("span", "reports-highlight " + row.kind, row.text));
    });
    return true;
  }

  // --------------------------------------------------------------------
  // (7) The report body, behind a disclosure
  // --------------------------------------------------------------------

  /**
   * The narrative, moved off the screen and into a drill-down.
   *
   * It used to be tier (1), the first thing on the page and up to 400
   * characters of it. The prose is not deleted — it is the agent's judgement
   * and an operator may well want it — but it is opened deliberately rather
   * than rendered at everyone by default. That is the whole of what #706
   * changes about it.
   */
  function renderReportBody(summary) {
    const block = document.querySelector("[data-reports-prose]");
    const body = document.querySelector("[data-reports-prose-body]");
    if (!block || !body) return false;
    body.textContent = "";
    const report = latestReport(summary && summary.reports);
    const narrative = report && report.narrative;
    if (!narrative) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    body.appendChild(el("p", "report-latest-narrative", String(narrative)));
    if (report.generated_at) {
      body.appendChild(
        el(
          "p",
          "report-latest-generated",
          MUREO.t("dashboard.reports_generated", {
            ago: relativeAge(report.generated_at),
          })
        )
      );
    }
    return true;
  }

  // --------------------------------------------------------------------
  // (8) The action log
  // --------------------------------------------------------------------

  /**
   * The recent actions, one short row each.
   *
   * An entry with a display line shows that and nothing more. An entry
   * without one — every entry written before #706 — shows its summary with
   * the markdown emphasis stripped and the tail behind a disclosure, because
   * a several-hundred-character work-journal note rendered whole is the wall
   * this redesign exists to end. Nothing stored is altered: the full text is
   * one click away, and the entry itself is untouched.
   */
  function renderActions(actions) {
    const block = document.querySelector("[data-reports-actions]");
    const list = document.querySelector("[data-reports-actions-list]");
    if (!block || !list) return false;
    list.textContent = "";
    const rows = Array.isArray(actions) ? actions : [];
    if (rows.length === 0) {
      block.hidden = true;
      return false;
    }
    block.hidden = false;
    rows.forEach(function (action) {
      const li = el("li", "report-action");
      const top = el("div", "report-action-top");
      if (action && action.timestamp) {
        top.appendChild(
          el("span", "report-action-time", relativeAge(action.timestamp))
        );
      }
      const line = DISPLAY.actionLine(action);
      top.appendChild(
        el(
          "span",
          "report-action-name",
          line.title || REPORTS_SHARED.humanizeFlagWords((action && action.action) || "")
        )
      );
      if (action && action.platform) {
        top.appendChild(el("span", "report-action-platform", action.platform));
      }
      li.appendChild(top);
      if (line.summary) {
        li.appendChild(el("p", "report-action-summary", line.summary));
      }
      if (line.truncated) {
        const more = el("details", "report-action-more");
        more.appendChild(
          el("summary", null, MUREO.t("dashboard.reports_action_read_more"))
        );
        more.appendChild(el("p", "report-action-full", line.full));
        li.appendChild(more);
      }
      if (action && action.observation_due) {
        const meta = el("div", "report-action-meta");
        meta.appendChild(
          el(
            "span",
            null,
            MUREO.t("dashboard.reports_observation_due", {
              date: String(action.observation_due),
            })
          )
        );
        li.appendChild(meta);
      }
      list.appendChild(li);
    });
    return true;
  }

  // --------------------------------------------------------------------
  // Assembly
  // --------------------------------------------------------------------

  //: Every section this file owns, so the legacy path can hide all of them in
  //: one pass. Listed once: a section added above and forgotten here would
  //: stay on screen from a previous client's render, which is the worst
  //: possible failure on a per-client screen.
  const CONTRACT_SECTIONS = [
    "data-reports-nav",
    "data-reports-funnel",
    "data-reports-chart",
    "data-reports-proposals",
    "data-reports-breakdown-campaigns",
    "data-reports-breakdown-adgroups",
    "data-reports-stated",
    "data-reports-highlights",
    "data-reports-prose",
  ];

  //: The legacy tiers, hidden when a contract takes over. Same reasoning.
  const LEGACY_SECTIONS = [
    "data-reports-latest",
    "data-reports-changes",
    "data-reports-platform-tier",
  ];

  function hideAll(attrs) {
    attrs.forEach(function (attr) {
      const node = document.querySelector("[" + attr + "]");
      if (node) node.hidden = true;
    });
  }

  /**
   * Draw one client's detail screen.
   *
   * Returns `true` when the contract path ran, so the caller knows whether
   * to render the legacy tiers. Both are complete screens; neither is a
   * partial render of the other.
   *
   * `context` carries what this file cannot ask for itself: the selected
   * platform key, and the callbacks that re-enter the render when the
   * operator switches platform or chart option.
   */
  function renderReportsDetail(summary, context) {
    const ctx = context || {};
    if (!DISPLAY.hasDisplay(summary)) {
      hideAll(CONTRACT_SECTIONS);
      renderHealthBadge(summary);
      const picker = document.querySelector("[data-reports-detail-platform]");
      if (picker) {
        picker.hidden = true;
        picker.textContent = "";
      }
      return false;
    }
    hideAll(LEGACY_SECTIONS);

    const platforms = Array.isArray(summary.platforms) ? summary.platforms : [];
    const platform = pickPlatform(platforms, ctx.platformKey);
    renderPlatformPicker(platforms, platform, ctx.onPlatform || function () {});
    renderHealthBadge(summary);
    renderNavBanner(summary);
    renderFunnel(platform);
    // The chart owns its own redraw loop: a metric or granularity tab is a
    // re-slice of data already in hand, never a re-fetch, so the loop closes
    // here rather than in the caller.
    const redrawChart = function () {
      DETAIL_CHART.renderChart(platform, redrawChart);
    };
    redrawChart();
    renderProposals(summary);
    renderBreakdown(
      summary,
      "campaigns",
      "data-reports-breakdown-campaigns",
      "data-reports-breakdown-campaigns-body"
    );
    renderBreakdown(
      summary,
      "adgroups",
      "data-reports-breakdown-adgroups",
      "data-reports-breakdown-adgroups-body"
    );
    renderStatedValues(summary);
    renderHighlights(summary);
    renderReportBody(summary);
    return true;
  }

  const api = {
    NO_VALUE: NO_VALUE,
    // Re-exported so a caller reaches ONE module for the whole screen; the
    // chart section itself lives in dashboard_reports_chart.js.
    renderChart: DETAIL_CHART.renderChart,
    CHART_STATE: DETAIL_CHART.CHART_STATE,
    FUNNEL: FUNNEL,
    PROPOSAL_CAP: PROPOSAL_CAP,
    CONTRACT_SECTIONS: CONTRACT_SECTIONS,
    LEGACY_SECTIONS: LEGACY_SECTIONS,
    clientHealth: clientHealth,
    renderHealthBadge: renderHealthBadge,
    pickPlatform: pickPlatform,
    spendDelta: spendDelta,
    shortDate: shortDate,
    secondaryValue: secondaryValue,
    attributionText: attributionText,
    renderNavBanner: renderNavBanner,
    renderFunnel: renderFunnel,
    renderProposals: renderProposals,
    renderBreakdown: renderBreakdown,
    renderStatedValues: renderStatedValues,
    renderHighlights: renderHighlights,
    renderReportBody: renderReportBody,
    renderActions: renderActions,
    renderReportsDetail: renderReportsDetail,
  };

  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_DETAIL = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
