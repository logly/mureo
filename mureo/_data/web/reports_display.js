// reports_display.js — reading the display contract (#706 step 3-a).
//
// Steps 1 and 2 built a small, write-guarded surface and taught the nine
// report-writing skills to fill it. This is the read model: the questions the
// detail view asks of `summary.display`, kept out of the renderer so the JS
// suite can execute them against data rather than infer them from a rendered
// tree.
//
// WHY A CONTRACT AT ALL. The dashboard used to render the agent's own prose
// — STATE.json is working memory, written for the next AI decision — and what
// an operator got was walls of jargon, thirty-row value dumps with sentences
// in numeric columns, and action logs showing raw `**` on screen. So the
// screen reads this section and nothing else, and everything on it arrived
// bounded.
//
// THE ONE RULE THIS FILE KEEPS. **A section with no data is not drawn.**
// Not an empty frame, not a zero, not a dash in a table nobody filled — the
// same discipline reports_sparkline.js keeps for a chart with one point. A
// box reserved for content that never arrives is a promise the data has not
// kept, and on this screen most boxes are empty most of the time: a fresh
// install has no contract at all, and a client whose last run wrote only a
// nav line has exactly one.
//
// BACKWARD COMPATIBILITY IS A FIRST-CLASS STATE, not a fallback. Every
// client on every install predates this contract, and stays that way until a
// skill writes one. `hasDisplay` is what the renderer switches on, and both
// answers are supported paths — the legacy three-tier detail view is not
// deprecated, it is what a client without a contract correctly shows.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_REPORTS_DISPLAY`. Reads one other module at call time,
// `MUREO_REPORTS_FORMAT` — see `format()` — and holds no copy of it.

(function () {
  "use strict";

  //: Chip tone → the class the CSS colours it with. The vocabulary is the
  //: server's (`HIGHLIGHT_TONES`), and it is closed on write, so a tone
  //: outside this map cannot arrive through `mureo_state_display_set`. It
  //: still might arrive from a hand-edited STATE.json — the read side is
  //: tolerant by design — so an unknown tone falls back to the neutral class
  //: rather than being dropped: the operator wrote the text, and losing it to
  //: tidy a vocabulary is the trade #659 refuses.
  const TONE_CLASS = {
    good: "is-good",
    watch: "is-watch",
    bad: "is-bad",
  };

  //: Breakdown row `state` → its class. Same closed vocabulary
  //: (`BREAKDOWN_STATES`), same tolerance. `no_data` is a real state — too
  //: little delivery to judge — and is deliberately distinct from a row that
  //: states no state at all.
  const STATE_CLASS = {
    target_met: "is-good",
    improving: "is-improving",
    watch: "is-watch",
    // Amber, not red: red on these screens means "act now" and nothing
    // else. A row trending the wrong way is a warning, and it has its own
    // class so the name and the colour cannot drift apart.
    worsening: "is-worsening",
    no_data: "is-none",
  };

  //: How much of a LEGACY action-log summary is shown before "read more".
  //: Matches ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS, so an old entry occupies
  //: the same space as a new one and the list does not visibly change shape
  //: as entries gain display lines. Nothing is truncated in storage — this is
  //: a display decision about an unchanged string, which mureo's
  //: never-truncate rule (about stored VALUES) does not cover.
  const LEGACY_SUMMARY_CHARS = 120;

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function text(value) {
    return typeof value === "string" && value.trim() ? value : null;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  // reports_format.js's number vocabulary — read off the page at CALL time,
  // the way reports_overview.js and reports_triage.js read their
  // dependencies. Call time and not load time because this file is also
  // evaluated on its own (browser_contract.test.js proves each asset stands
  // up alone), and because the page's <script> order is the only thing that
  // guarantees the other module is there at all.
  //
  // Asking it rather than repeating it is the point. "How does this screen
  // print a number" is ONE question, and #606/#609 are what a second answer
  // costs: two roundings of the same figure, drifting apart in review.
  function format() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_FORMAT : null;
    if (!api) {
      throw new Error(
        "reports_display.js needs MUREO_REPORTS_FORMAT — load " +
          "reports_format.js BEFORE reports_display.js"
      );
    }
    return api;
  }

  /** The contract object, or `null` when this client has none. */
  function displayOf(summary) {
    const display = summary && summary.display;
    return isObject(display) ? display : null;
  }

  /**
   * Does this client have a display contract at all?
   *
   * The renderer's top-level switch. `false` is not an error state and not a
   * degraded one: it is every client that predates #706 and every client
   * whose skills have not run since, and it renders the detail view that
   * shipped before this — which is still correct, just longer.
   */
  function hasDisplay(summary) {
    return displayOf(summary) !== null;
  }

  /** The one operator line, or `null` — the banner is hidden without it. */
  function navMessage(summary) {
    const display = displayOf(summary);
    return display ? text(display.nav_message) : null;
  }

  /**
   * The highlight chips: `[{tone, text, kind}]`, at most what was written.
   *
   * An entry with no text is dropped — there is no chip to draw — but its
   * tone is never invented and an unknown one keeps its text under the
   * neutral class.
   */
  function highlights(summary) {
    const display = displayOf(summary);
    const rows = display && Array.isArray(display.highlights) ? display.highlights : [];
    const out = [];
    rows.forEach(function (row) {
      if (!isObject(row)) return;
      const body = text(row.text);
      if (!body) return;
      const tone = text(row.tone);
      out.push({
        tone: tone,
        text: body,
        kind: (tone && TONE_CLASS[tone]) || "is-none",
      });
    });
    return out;
  }

  /**
   * One breakdown table's rows, shaped for the renderer, or `[]`.
   *
   * `level` is `"campaigns"` or `"adgroups"`. Figures come through as they
   * are: a row with no `mcpa` keeps `null` and the cell renders as an em
   * dash, because a campaign with no conversions has no cost per acquisition
   * and `0` would state a perfect one.
   */
  function breakdownRows(summary, level) {
    const display = displayOf(summary);
    const section = display && isObject(display.breakdown) ? display.breakdown : null;
    const rows = section && Array.isArray(section[level]) ? section[level] : [];
    const out = [];
    rows.forEach(function (row) {
      if (!isObject(row)) return;
      const name = text(row.name);
      if (!name) return;
      const state = text(row.state);
      out.push({
        name: name,
        spend: isNumber(row.spend) ? row.spend : null,
        mcpa: isNumber(row.mcpa) ? row.mcpa : null,
        target_cpa: isNumber(row.target_cpa) ? row.target_cpa : null,
        state: state,
        stateKind: (state && STATE_CLASS[state]) || "is-none",
        note: text(row.note),
      });
    });
    return out;
  }

  /**
   * `{label, value}` chips, or `[]`.
   *
   * A value the contract stated as a NUMBER is printed the way every other
   * figure on this screen is printed — `formatNumber`, i.e. thousands
   * grouping and no currency symbol, because the wire carries raw numbers
   * and no platform's currency. A stated CPA of 3855 read `3855` next to a
   * breakdown table printing `3,855` for the same kind of figure (#734).
   *
   * Grouping only: `toLocaleString` keeps a fractional part, so a stated
   * ROAS of 3.4 is still `3.4` and nothing is rounded away here. Rounding
   * is the breakdown table's own decision about its own columns, and a
   * stated value has no column to fit.
   *
   * A value stated as a STRING passes through untouched. `"3.4x"` is the
   * operator's own text, unit and all, and the contract's promise is that
   * what was written is what is shown.
   */
  function statedValues(summary) {
    const display = displayOf(summary);
    const rows =
      display && Array.isArray(display.stated_values) ? display.stated_values : [];
    const out = [];
    rows.forEach(function (row) {
      if (!isObject(row)) return;
      const label = text(row.label);
      if (!label) return;
      const value = row.value;
      if (!isNumber(value) && !text(value)) return;
      out.push({
        label: label,
        value: isNumber(value) ? format().formatNumber(value) : String(value),
      });
    });
    return out;
  }

  /** `YYYY-MM` of an ISO-ish date string, or `null`. */
  function monthOf(value) {
    const raw = text(value);
    if (!raw) return null;
    const match = /^(\d{4})-(\d{2})/.exec(raw);
    return match ? match[1] + "-" + match[2] : null;
  }

  /**
   * The proposals panel's three answers.
   *
   * `{open, doneThisMonth, doneTotal}` — the open ones to show as cards, and
   * two counts. Split rather than one list because they answer different
   * questions: what is still owed, and how much has been carried out (this
   * month, and at all).
   *
   * "This month" is taken from `now`, which the caller supplies — normally
   * the summary's own `server_today`. The browser's clock is deliberately not
   * consulted: an action-log day boundary drawn in the reader's timezone
   * lists yesterday's work as today's for anyone outside the host's zone, and
   * the same is true of a month boundary. With no `now` the monthly count is
   * `null` rather than 0, because "none this month" and "mureo does not know
   * what month it is" are different statements.
   *
   * A proposal with no `status` counts as open: `proposed` is the default
   * the contract documents, and an unstated status is not evidence of
   * completion.
   */
  function proposalGroups(summary, now) {
    const display = displayOf(summary);
    const rows = display && Array.isArray(display.proposals) ? display.proposals : [];
    const month = monthOf(now);
    const open = [];
    let doneTotal = 0;
    let doneThisMonth = 0;
    rows.forEach(function (row) {
      if (!isObject(row)) return;
      const title = text(row.title);
      if (!title) return;
      const entry = {
        title: title,
        body: text(row.body),
        date: text(row.date),
        status: text(row.status),
      };
      if (entry.status === "done") {
        doneTotal += 1;
        if (month && monthOf(entry.date) === month) doneThisMonth += 1;
        return;
      }
      open.push(entry);
    });
    return {
      open: open,
      doneTotal: doneTotal,
      doneThisMonth: month ? doneThisMonth : null,
    };
  }

  /**
   * Who wrote this screen and when: `{source, generatedAt}`, or `null`.
   *
   * The contract is replaced whole by whoever writes it last, so this is the
   * one question the content cannot answer about itself — a card whose weekly
   * proposals were replaced by the evening's daily-check still says who last
   * spoke. `null` when the contract predates the attribution fields, which
   * every contract written before #706's review round does.
   */
  function attribution(summary) {
    const display = displayOf(summary);
    if (!display) return null;
    const source = text(display.source);
    const generatedAt = text(display.generated_at);
    if (!source && !generatedAt) return null;
    return { source: source, generatedAt: generatedAt };
  }

  /**
   * A stored string with its markdown emphasis removed.
   *
   * The reported defect, verbatim: work-journal action logs showing raw `**`
   * on screen. The summaries were written for the next AGENT, which reads
   * markdown; a person gets asterisks. Only the emphasis markers go —
   * `**bold**`, `__bold__`, `*em*`, `_em_`, and a leading `#` heading run —
   * because anything more ambitious would start editing an operator's text.
   *
   * Applied ONLY on the legacy path. A `display_summary` is written as plain
   * text by instruction and arrives clean; running this over it would be this
   * layer quietly repairing a contract the write side already guarantees.
   */
  function stripEmphasis(value) {
    const raw = text(value);
    if (!raw) return null;
    return raw
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/__(.+?)__/g, "$1")
      .replace(/(^|[\s(])\*(\S(?:.*?\S)?)\*(?=[\s).,;:!?]|$)/g, "$1$2")
      .replace(/(^|[\s(])_(\S(?:.*?\S)?)_(?=[\s).,;:!?]|$)/g, "$1$2")
      .replace(/^#{1,6}\s+/gm, "")
      .trim();
  }

  /**
   * What one action-log row shows: `{title, summary, truncated, full}`.
   *
   * Two shapes, and which one an entry gets is decided by the ENTRY, not by
   * the client:
   *
   * - **It carries a display line** (#706). That line is shown and nothing
   *   else — it was written for this row, under bounds that make it fit. The
   *   stored `summary` is not shown at all here; it is the work journal, and
   *   the drill-down is where it belongs.
   * - **It predates the display line.** Its `summary` is the only text there
   *   is, so it is shown — emphasis stripped, and cut to
   *   :data:`LEGACY_SUMMARY_CHARS` with the whole string kept on `full` so
   *   the row can offer to open it. Nothing is lost, and nothing on screen is
   *   a wall.
   *
   * `title` falls back to `null` rather than to the action name: the renderer
   * already draws the action name on its own line, and repeating it as a
   * title would make every legacy row look like it had a display line.
   */
  function actionLine(action) {
    if (!isObject(action)) return { title: null, summary: null, truncated: false, full: null };
    const title = text(action.display_title);
    const short = text(action.display_summary);
    if (title || short) {
      return { title: title, summary: short, truncated: false, full: null };
    }
    const legacy = stripEmphasis(action.summary);
    if (!legacy) return { title: null, summary: null, truncated: false, full: null };
    if (legacy.length <= LEGACY_SUMMARY_CHARS) {
      return { title: null, summary: legacy, truncated: false, full: null };
    }
    return {
      title: null,
      summary: legacy.slice(0, LEGACY_SUMMARY_CHARS).trimEnd() + "…",
      truncated: true,
      full: legacy,
    };
  }

  const api = {
    TONE_CLASS: TONE_CLASS,
    STATE_CLASS: STATE_CLASS,
    LEGACY_SUMMARY_CHARS: LEGACY_SUMMARY_CHARS,
    hasDisplay: hasDisplay,
    navMessage: navMessage,
    highlights: highlights,
    breakdownRows: breakdownRows,
    statedValues: statedValues,
    proposalGroups: proposalGroups,
    attribution: attribution,
    stripEmphasis: stripEmphasis,
    actionLine: actionLine,
  };

  if (typeof window !== "undefined") window.MUREO_REPORTS_DISPLAY = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
