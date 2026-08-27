// dashboard_reports_hero.js — the band across the top of the list screen
// (#706 step 3-b).
//
// The DOM half of reports_hero.js. One band, and everything in it is a COUNT
// OF CLIENTS: the day the host says it is, how many of the roster raised
// nothing, and the four health blocks. Not one figure about an ad account is
// drawn here — the portfolio strip under the band already states those, with
// the coverage that makes them readable.
//
// WHAT THIS FILE DOES NOT DECIDE. Not one health verdict. The counts arrive
// built (reports_hero.js, from reports_triage.js's own answers), and this file
// paints them. A band that graded the roster itself would be a fourth opinion
// beside the cards, the roster table and the filter chips.
//
// It draws nothing at all below two clients: the band answers "which of these
// do I open first?", and with one card that question is not being asked. The
// index keeps exactly the shape it had before #706 step 3-b there — that is
// the decision the staff review made explicitly, not an omission.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_REPORTS_HERO`. Loads AFTER
// dashboard_reports_state.js (whose bindings it reads at load) and BEFORE
// dashboard_reports.js, which calls it mid-render.

(function () {
  "use strict";

  // dashboard_reports_state.js's exports, bound by their original names —
  // the same block every dashboard_reports_*.js module opens with.
  const REPORTS_SHARED = window.MUREO_DASHBOARD_REPORTS_STATE;
  if (!REPORTS_SHARED) {
    throw new Error(
      "dashboard_reports_hero.js needs MUREO_DASHBOARD_REPORTS_STATE — load " +
        "dashboard_reports_state.js BEFORE dashboard_reports_hero.js"
    );
  }
  const formatNumber = REPORTS_SHARED.formatNumber;

  //: Block key → the label it carries. The EXISTING health vocabulary for the
  //: three states the triage layer produces, so the band and the filter chips
  //: directly under it call one client by one name; `idle` is the only new
  //: word, and it names the one block that is not a health verdict.
  const HERO_BLOCK_LABELS = {
    ok: "dashboard.reports_health_ok",
    watch: "dashboard.reports_health_watch",
    attention: "dashboard.reports_health_attention",
    idle: "dashboard.reports_health_idle",
  };

  // One block: the count, then what it counts. Colour never carries the
  // meaning alone — every block says its word underneath, which is also what
  // a screen reader reads.
  function buildHeroBlock(block) {
    const cell = document.createElement("div");
    cell.className = "reports-hero-block is-" + block.key;
    cell.setAttribute("role", "listitem");
    cell.setAttribute("data-reports-hero-block", block.key);
    const value = document.createElement("span");
    value.className = "reports-hero-block-count";
    value.textContent = formatNumber(block.count);
    cell.appendChild(value);
    const label = document.createElement("span");
    label.className = "reports-hero-block-label";
    label.textContent = MUREO.t(HERO_BLOCK_LABELS[block.key] || "");
    cell.appendChild(label);
    return cell;
  }

  // The fraction the band leads with: how many of the roster raised nothing.
  //
  // A count over a count, and nothing else — no percentage, no target. Both
  // halves come from the same model, so the fraction cannot state a whole
  // the blocks beside it disagree with.
  function renderHeroRatio(hero) {
    const slot = document.querySelector("[data-reports-hero-ratio]");
    if (!slot) return;
    slot.textContent = formatNumber(hero.ok) + "/" + formatNumber(hero.total);
  }

  // The four blocks, rebuilt from the model on every render. Rebuilt rather
  // than updated: a leftover block from a roster that has since shrunk is the
  // worst failure this band has, and it cannot happen if nothing survives a
  // render.
  function renderHeroBlocks(hero) {
    const wrap = document.querySelector("[data-reports-hero-blocks]");
    if (!wrap) return;
    wrap.textContent = "";
    // Defensive for the reason every renderer in this layer is: a throw
    // mid-render blanks the whole Reports view, and the band is the first
    // thing drawn on it.
    const blocks = Array.isArray(hero.blocks) ? hero.blocks : [];
    blocks.forEach(function (block) {
      if (block && block.key) wrap.appendChild(buildHeroBlock(block));
    });
  }

  // The day the HOST says it is, or nothing at all.
  //
  // Never the browser's: a band headed with the reader's date over an action
  // feed dated by the server's is the timezone bug reports_overview.js exists
  // to keep out of this screen. No date, no line — an empty slot rather than
  // a guess.
  function renderHeroDate(hero) {
    const slot = document.querySelector("[data-reports-hero-date]");
    if (!slot) return;
    slot.textContent = hero.date || "";
    slot.hidden = !hero.date;
  }

  /**
   * Draw the band, or hide it entirely.
   *
   * Hidden below two clients (`hero.show`) and emptied with it: a band left
   * on screen from a previous render would state a roster that is no longer
   * there, which is worse than no band.
   */
  function renderReportsHero(hero) {
    const band = document.querySelector("[data-reports-hero]");
    if (!band) return;
    const model = hero && typeof hero === "object" ? hero : null;
    band.hidden = !(model && model.show);
    if (band.hidden) {
      const wrap = document.querySelector("[data-reports-hero-blocks]");
      if (wrap) wrap.textContent = "";
      return;
    }
    renderHeroDate(model);
    renderHeroRatio(model);
    renderHeroBlocks(model);
  }

  const api = {
    renderReportsHero: renderReportsHero,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_REPORTS_HERO = api;
  // Node (test runner only): `module` does not exist in a browser, so
  // this branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
