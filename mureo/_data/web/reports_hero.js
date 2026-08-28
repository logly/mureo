// reports_hero.js — what the list screen says before anything is clicked
// (#706 step 3-b).
//
// Step 3-a rebuilt the screen about ONE client. This is the one about all of
// them, and the question it has to answer in a glance is not "what did the
// roster spend" — the strip under the band already answers that — but "how
// many of these are fine, and how many are not".
//
// ONE ANSWER TO THAT QUESTION, NOT A SECOND ONE. The health of a client is
// decided by reports_triage.js and by nothing else: `triageClientHealth` per
// client, `triageHealthCounts` over the grid, both run once per render by
// reports_index.js. The band is handed those counts rather than recomputing
// them, because the cards below it, the roster table beside it and the filter
// chips above it are all painted from the same answer, and a band that graded
// the roster itself would be a fourth opinion that agrees today and drifts
// next release.
//
// THE FOURTH BLOCK. The triage vocabulary has three states — attention,
// watch, ok — and the staff mockup's band has four: the last one is the
// client mureo is not running yet. That is not a health verdict and it is not
// derived from one: it is the client whose RECEIVED summary carries no figure
// at all (`aggregateClientKpis(...).hasFigures` — reports_logic.js's answer,
// the same one the cards use to decide whether to print a number). Received:
// a summary mureo failed to fetch says nothing about that client's ads and is
// never counted here (see `isIdle`). It is carved out of the OK bucket only,
// so a client the triage layer marked is never shown as idle, and the four
// blocks always add up to the roster.
//
// NOTHING HERE IS A NEW FACT ABOUT AN AD ACCOUNT. No delta, no ratio the
// stored numbers do not already state: the band counts clients, and the
// fraction it leads with is a count over a count.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_REPORTS_HERO`. `MUREO_REPORTS_LOGIC` and
// `MUREO_REPORTS_OVERVIEW` are read off the page at CALL time, exactly as
// reports_overview.js reads reports_logic.js, so this file has no load-order
// dependency beyond the `<script>` order app.html already pins.

(function () {
  "use strict";

  //: How many clients the band is FOR. One client is not a roster: the
  //: mockup's band answers "which of these do I open first?", and with a
  //: single card the answer is on screen already. Below this the index keeps
  //: exactly the shape it had before #706 step 3-b.
  const REPORTS_HERO_MIN_CLIENTS = 2;

  //: The four blocks, in the order the band draws them: the calm end first,
  //: the work in the middle, the client mureo is not running yet last. The
  //: array IS the order, so it is stated here rather than left to whichever
  //: loop the renderer happens to write.
  const REPORTS_HERO_BLOCKS = ["ok", "watch", "attention", "idle"];

  // reports_logic.js's decisions — read off the page at call time, for the
  // reason reports_overview.js gives: whether a client has any figures at
  // all is ONE answer, and this file must not hold a second one.
  function logic() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_LOGIC : null;
    if (!api) {
      throw new Error(
        "reports_hero.js needs MUREO_REPORTS_LOGIC — load reports_logic.js " +
          "BEFORE reports_hero.js"
      );
    }
    return api;
  }

  // reports_overview.js's answer to "what day is it on the HOST", which is
  // the only day this band may print. Same call-time read, same reason: a
  // second implementation of "today" is how a screen ends up dating itself
  // by the reader's timezone.
  function overview() {
    const api = typeof window !== "undefined" ? window.MUREO_REPORTS_OVERVIEW : null;
    if (!api) {
      throw new Error(
        "reports_hero.js needs MUREO_REPORTS_OVERVIEW — load " +
          "reports_overview.js BEFORE reports_hero.js"
      );
    }
    return api;
  }

  function count(value) {
    return typeof value === "number" && isFinite(value) && value > 0
      ? Math.floor(value)
      : 0;
  }

  /**
   * Has mureo collected any figure at all for this client?
   *
   * `hasFigures` is reports_logic.js's raw-presence answer, and raw presence
   * is deliberately what this asks: a client whose totals are WITHHELD (stale,
   * double-counted) has figures — mureo simply refuses to state them — and
   * calling that "not running" would file a data problem as an idle account.
   * Such a client is on the triage list anyway, and its block is that.
   */
  function hasFigures(summary) {
    const kpis = logic().aggregateClientKpis(summary);
    return !!(kpis && kpis.hasFigures);
  }

  /**
   * Is this client one mureo is not running yet?
   *
   * TWO CONDITIONS, AND THE FIRST ONE IS THE POINT: a summary was actually
   * RECEIVED, and it states no figures. `fetchClientCardSummary` yields
   * `null` when the request failed, and a failed request is not evidence
   * about an ad account — it is the absence of evidence. Printing "not
   * running yet" about a client mureo could not reach is a falsehood on
   * screen, and while the daemon restarts it is a falsehood about the whole
   * roster at once.
   *
   * So a null lands in the OK block, which is where the filter chips have
   * always counted it: the band and the chips are one answer, and the
   * alternative — routing unreachable clients to "needs attention" — turns
   * the screen red during an outage, which is the same lie the other way up.
   * Quiet degradation is the answer until the screen learns to SAY that a
   * fetch failed.
   */
  function isIdle(summary) {
    if (!summary || typeof summary !== "object") return false;
    return !hasFigures(summary);
  }

  /**
   * The band's model: `{show, total, ok, watch, attention, idle, blocks, date}`.
   *
   * `counts` is the render's health split — `model.healthCounts`, the SAME
   * object the filter chips and the portfolio strip are built from — and
   * `healthOf(i)` reads `model.healthByIndex`, the same verdict the card and
   * the roster row are painted with. Both are passed in rather than derived
   * here so the band cannot disagree with the grid under it, and both are
   * reports_index.js's, built once per render (#715).
   *
   * `summaries` is positional with the grid, exactly as renderReportsIndex
   * holds it, and is read for two things only: which OK clients have no
   * figures, and what day the server says it is.
   *
   * Defensive about every argument: this runs mid-render over a payload that
   * may come from an older daemon, and a throw here blanks the Reports view.
   */
  function buildReportsHero(counts, summaries, healthOf) {
    const c = counts && typeof counts === "object" ? counts : {};
    const bodies = Array.isArray(summaries) ? summaries : [];
    const health = typeof healthOf === "function" ? healthOf : null;
    const total = count(c.all);
    let idle = 0;
    for (let i = 0; i < total; i++) {
      // Carved out of OK and out of nothing else: a marked client's block is
      // the mark, whatever its figures look like.
      if (health && health(i) !== "ok") continue;
      if (isIdle(bodies[i])) idle += 1;
    }
    const model = {
      show: total >= REPORTS_HERO_MIN_CLIENTS,
      total: total,
      ok: Math.max(0, count(c.ok) - idle),
      watch: count(c.watch),
      attention: count(c.attention),
      idle: idle,
      date: overview().statedServerDate(bodies),
    };
    model.blocks = REPORTS_HERO_BLOCKS.map(function (key) {
      return { key: key, count: model[key] };
    });
    return model;
  }

  const api = {
    REPORTS_HERO_MIN_CLIENTS: REPORTS_HERO_MIN_CLIENTS,
    REPORTS_HERO_BLOCKS: REPORTS_HERO_BLOCKS,
    buildReportsHero: buildReportsHero,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_HERO = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
