// reports_logic.js — the pure half of the Reports dashboard (#540).
//
// Everything here is a plain function over the `/api/reports/*` wire
// payload: no DOM, no fetch, no module state. It was MOVED here verbatim
// from dashboard.js so it can be executed by a test runner — the
// KPI-withholding condition (#533), the per-platform freshness
// aggregation (#535) and the conflict-kind routing decide whether an
// operator sees a money figure at all, and an inverted condition or a
// reordered branch in any of them ships silently. Static substring pins
// cannot catch that; `node --test tests/js/` can. Rendering stays in
// dashboard.js and stays pinned statically.
//
// Shipping shape is unchanged: this is a plain `<script>`-loaded file,
// no bundler, no module system, no build step. It publishes
// `window.MUREO_REPORTS_LOGIC` the same way amazon_oauth.js publishes
// `window.MUREO_AMAZON_OAUTH`, and it MUST load before dashboard.js.
// The `module.exports` tail at the bottom is inert in a browser (`module`
// is undefined there) and is what lets Node require the same bytes the
// browser gets — the test never sees a re-implementation.
//
// `MUREO.t` is read from the global at CALL time, not captured at load
// time, so this file has no load-order dependency on app.js and a test
// can supply its own `t`.

(function () {
  "use strict";

  // `platform_conflicts[].kind` — two INDEPENDENT findings, kept apart on
  // purpose. "Two keys resolve to one account" means the totals on screen
  // are double-counted right now; "unrecognised key" means that entry's
  // identity cannot be established at all and it MAY be a duplicate. The
  // operator's next move differs, so they never collapse into one warning.
  const REPORTS_CONFLICT_DUPLICATE_ACCOUNT = "duplicate_account";
  const REPORTS_CONFLICT_UNRECOGNIZED_KEY = "unrecognized_key";

  // Humanize an ISO-8601 timestamp into a coarse "N ago" string. Falls
  // back to the raw string if it cannot be parsed (never throws).
  function relativeAge(iso) {
    if (!iso) return "";
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return String(iso);
    const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (secs < 60) return MUREO.t("dashboard.reports_age_just_now");
    const mins = Math.floor(secs / 60);
    if (mins < 60) return MUREO.t("dashboard.reports_age_minutes", { n: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return MUREO.t("dashboard.reports_age_hours", { n: hours });
    const days = Math.floor(hours / 24);
    return MUREO.t("dashboard.reports_age_days", { n: days });
  }

  // ------------------------------------------------------------------
  // Conflicts (#533) + per-platform freshness (#535)
  // ------------------------------------------------------------------

  // Every conflict row of `kind` in a summary. Defensive: the key is always
  // sent, but a proxy or an older daemon may not have it.
  function reportsConflictsOfKind(summary, kind) {
    const rows =
      summary && Array.isArray(summary.platform_conflicts)
        ? summary.platform_conflicts
        : [];
    return rows.filter(function (row) {
      return row && row.kind === kind && Array.isArray(row.platform_keys);
    });
  }

  // Does this client's aggregate double-count an ad account right now?
  function reportsHasDoubleCount(summary) {
    return (
      reportsConflictsOfKind(summary, REPORTS_CONFLICT_DUPLICATE_ACCOUNT).length > 0
    );
  }

  // key → display_name from the summary's platform rows, so a conflict names
  // platforms the way the rest of the view does. Falls back to the raw key.
  function reportsPlatformLabels(summary) {
    const map = {};
    (summary && Array.isArray(summary.platforms) ? summary.platforms : []).forEach(
      function (p) {
        if (p && typeof p.key === "string") map[p.key] = p.display_name || p.key;
      }
    );
    return map;
  }

  function reportsKeyList(keys, labels) {
    return (Array.isArray(keys) ? keys : [])
      .map(function (k) {
        return (labels && labels[k]) || String(k);
      })
      .join(", ");
  }

  // A conflict as one localized sentence. Untrusted platform keys are
  // interpolated into the string and the caller sets it via textContent.
  function reportsConflictText(row, labels) {
    const keys = reportsKeyList(row.platform_keys, labels);
    if (row.kind === REPORTS_CONFLICT_DUPLICATE_ACCOUNT) {
      return MUREO.t("dashboard.reports_conflict_double_counted", { keys: keys });
    }
    // An unrecognised key is TWO findings wearing one kind (#606). The
    // condition behind it tests the key alone, so it also fires on entries
    // whose ad account is perfectly well known — including ones the
    // duplicate-account row above has just named with certainty. Only the
    // account-less shape may carry the "this may be a duplicate mureo
    // cannot see, review it by hand" clause; saying that of a known account
    // contradicts the note beside it. `=== true` on purpose: a row that
    // does not state the fact is UNKNOWN, not known, and the cautious
    // wording is the right answer there.
    return MUREO.t(
      row.account_known === true
        ? "dashboard.reports_conflict_unknown_key"
        : "dashboard.reports_conflict_unknown_key_no_account",
      { keys: keys }
    );
  }

  // What to RUN about the conflicts on this card (#636).
  //
  // A duplicated ad account is the one finding whose totals the card
  // withholds, and until #636 nothing could clear it: the repair would not
  // touch a duplicate whose two keys both resolve, so "resolve this to see
  // your totals" pointed at no command that existed. The operator names the
  // losing key (`--drop-duplicate`) and mureo honours it; mureo still never
  // picks the loser, which is why the string leaves the key a placeholder.
  //
  // Every other finding keeps the survey command — its next move is to LOOK,
  // not to delete. Defensive about its argument: this runs mid-render, and a
  // throw here blanks the Reports view.
  function reportsRepairHint(conflicts) {
    const rows = Array.isArray(conflicts) ? conflicts : [];
    const duplicated = rows.some(function (row) {
      return row && row.kind === REPORTS_CONFLICT_DUPLICATE_ACCOUNT;
    });
    return MUREO.t(
      duplicated
        ? "dashboard.reports_conflict_duplicate_repair_hint"
        : "dashboard.reports_conflict_repair_hint"
    );
  }

  // Every conflict that names `key`, so a platform card can carry its own.
  function reportsConflictsForKey(summary, key) {
    const rows =
      summary && Array.isArray(summary.platform_conflicts)
        ? summary.platform_conflicts
        : [];
    return rows.filter(function (row) {
      return (
        row && Array.isArray(row.platform_keys) && row.platform_keys.indexOf(key) >= 0
      );
    });
  }

  // A row's own freshness as {text, stale}. `stale === null` (fetched_at
  // absent or unparseable) is its own state — "unknown", not "fresh" —
  // because fetched_at is optional and writer-dependent.
  function reportsFreshnessLabel(freshness) {
    const f = freshness && typeof freshness === "object" ? freshness : null;
    if (!f || !f.fetched_at || f.stale == null) {
      return { text: MUREO.t("dashboard.reports_platform_age_unknown"), stale: false };
    }
    const ago = relativeAge(f.fetched_at);
    return {
      text: MUREO.t(
        f.stale
          ? "dashboard.reports_platform_stale"
          : "dashboard.reports_platform_updated",
        { ago: ago }
      ),
      stale: !!f.stale,
    };
  }

  // Has mureo judged THIS row's figures stale (#638)?
  //
  // `=== true` on purpose. `stale` is three-valued and `null` means unknown
  // — fetched_at was absent or unparseable — which is a state, not a
  // verdict. Documents written before the write-time stamp (#637) are full
  // of it, so treating unknown as stale would blank most cards; unknown
  // keeps the rendering it already had.
  function reportsRowIsStale(row) {
    const f =
      row && typeof row === "object" && row.freshness &&
      typeof row.freshness === "object"
        ? row.freshness
        : null;
    return !!f && f.stale === true;
  }

  // ------------------------------------------------------------------
  // Why the figures did not move (#638)
  // ------------------------------------------------------------------

  // One row's `not_collected` note, normalised, or null.
  //
  // Staleness says a figure is out of date; this says WHY it is, which is
  // the half an operator can act on. A card whose numbers had not moved for
  // eleven days looked identical whether the ad account had stopped
  // delivering or the collector had stopped running, so it was left alone
  // for eleven days.
  //
  // A note is NOT a verdict on the figures. They are the last ones that were
  // truly collected — not wrong, just older than they should be — so nothing
  // here withholds or restates a number. It only explains one.
  //
  // The reason is the payload: a note that states no reason says something
  // happened and refuses to say what, which is the non-answer this exists to
  // end, so it is dropped rather than rendered. `attempted_at` is normalised
  // to null when it is not a string — the text builder then says the time is
  // unknown instead of interpolating junk.
  function reportsNotCollectedNote(row) {
    const r = row && typeof row === "object" ? row : null;
    const note = r && r.not_collected && typeof r.not_collected === "object"
      ? r.not_collected
      : null;
    if (!note) return null;
    const reason = typeof note.reason === "string" ? note.reason.trim() : "";
    if (!reason) return null;
    const key = typeof r.key === "string" ? r.key : "";
    return {
      key: key,
      label: r.display_name || key,
      reason: reason,
      attempted_at:
        typeof note.attempted_at === "string" && note.attempted_at
          ? note.attempted_at
          : null,
    };
  }

  // Every platform of a summary that says why it was not collected.
  //
  // Unlike the freshness aggregation, a row contributing NO totals still
  // counts: "there are no figures for this platform, and here is why" is
  // precisely the sentence that was missing. Defensive about its argument —
  // this runs mid-render, and a throw blanks the Reports view.
  function reportsNotCollectedNotes(summary) {
    const rows =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    const notes = [];
    rows.forEach(function (row) {
      const note = reportsNotCollectedNote(row);
      if (note) notes.push(note);
    });
    return notes;
  }

  // A note as one localized sentence. The reason is writer-supplied text and
  // the caller sets it via textContent.
  //
  // An age mureo cannot quote is said to be unknown rather than left blank:
  // a dangling "could not be collected : …" reads as a claim about now.
  function reportsNotCollectedText(note) {
    if (!note || typeof note !== "object" || !note.reason) return "";
    const age = note.attempted_at ? relativeAge(note.attempted_at) : null;
    return MUREO.t(
      age
        ? "dashboard.reports_not_collected"
        : "dashboard.reports_not_collected_undated",
      { platform: note.label || note.key, ago: age, reason: note.reason }
    );
  }

  // The freshness of a client CARD, which shows one aggregate rather than
  // per-platform rows. Only platforms that actually carry totals count —
  // an advisory bridge contributes nothing to the sum, so its (absent)
  // fetched_at says nothing about the number on screen. Among the rest the
  // OLDEST wins, because an aggregate is only as current as its stalest
  // input, and a single unknown means the card cannot state an age at all
  // rather than letting a fresh sibling vouch for the rest.
  //
  // Three outcomes, and the text always matches the styling:
  //   • every contributor known      → "Updated N ago" / "Stale — updated N ago"
  //   • some unknown, none stale     → "Update time unknown" (not marked stale)
  //   • some unknown, one is stale   → "Stale — some update times unknown"
  // The third is the mixed case: we know something IS stale (a fresh sibling
  // must never hide it) but we cannot honestly quote an age, so the label
  // says exactly that instead of claiming "unknown" in stale-red.
  function reportsCardFreshness(summary) {
    const platforms =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    let oldest = null;
    let oldestMs = Infinity;
    let stale = false;
    let unknown = false;
    platforms.forEach(function (p) {
      if (!p || !p.totals || typeof p.totals !== "object") return;
      const f = p.freshness && typeof p.freshness === "object" ? p.freshness : null;
      if (!f || !f.fetched_at || f.stale == null) {
        unknown = true;
        return;
      }
      if (f.stale) stale = true;
      const ms = Date.parse(f.fetched_at);
      if (!Number.isNaN(ms) && ms < oldestMs) {
        oldestMs = ms;
        oldest = f;
      }
    });
    if (unknown || !oldest) {
      return {
        text: MUREO.t(
          stale
            ? "dashboard.reports_platform_stale_partial"
            : "dashboard.reports_platform_age_unknown"
        ),
        stale: stale,
      };
    }
    return reportsFreshnessLabel({
      fetched_at: oldest.fetched_at,
      stale: stale,
    });
  }

  // Sum a client's headline KPIs across its platforms. null when absent so a
  // missing metric reads as "—" rather than a misleading zero.
  //
  // Summing across genuinely different platforms is the feature. Summing two
  // keys that resolve to ONE ad account is the bug (#533) — so when the
  // summary reports that conflict, the figures are WITHHELD (null) rather
  // than shown under a warning. A number an operator triages by is worse
  // than no number when it is known to be wrong: a doubled spend reads as a
  // real outlier and gets acted on. The un-summed per-platform figures are
  // one click away in the detail view, and nothing is merged or dropped to
  // manufacture a total — the two entries hold different partial figures.
  //
  // The nulling happens HERE, not in the caller, so no future call site can
  // render the double-counted sum by forgetting to check the flag.
  // `hasFigures` reports the raw presence of data regardless, for callers
  // deciding whether another period window is worth fetching.
  //
  // A STALE contributor withholds the figures too (#638), for the same
  // reason and by the same mechanism: a rollup older than the window it
  // summarises is not that window's answer, and rendering it as the headline
  // asserts something mureo cannot back. A card once showed 25,862 cost for
  // a window whose real cost was 0 — delivery had stopped eleven days
  // earlier — with the age demoted to a badge beside it. One stale
  // contributor is enough: the aggregate is a single number, and a fresh
  // sibling cannot vouch for the part that is out of date.
  //
  // Nothing is hidden. `staleFigures` carries the very same numbers plus the
  // oldest stale contributor's `fetched_at`, so the card can restate them as
  // what they ARE ("11d ago: 25,862") instead of what they are not. It is
  // `null` when the sum is double-counted as well: that figure is wrong at
  // every age, and restating it under a softer label would put it back on
  // the card.
  function aggregateClientKpis(summary) {
    const platforms =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    let spend = 0;
    let conv = 0;
    // CTR is a RATIO, so it is summed as its two parts and divided once at
    // the end — not averaged across platforms. A client running 37,540
    // impressions on one platform and 800 on another has one click-through
    // rate, and the mean of the two platform rates is not it.
    let clicks = 0;
    let impressions = 0;
    let hasSpend = false;
    let hasConv = false;
    let hasClicks = false;
    let hasImpressions = false;
    let stale = false;
    let staleSince = null;
    let staleSinceMs = Infinity;
    platforms.forEach(function (p) {
      const t = p && typeof p.totals === "object" ? p.totals : null;
      if (!t) return;
      if (typeof t.spend === "number" && isFinite(t.spend)) {
        spend += t.spend;
        hasSpend = true;
      }
      if (typeof t.conversions === "number" && isFinite(t.conversions)) {
        conv += t.conversions;
        hasConv = true;
      }
      if (typeof t.clicks === "number" && isFinite(t.clicks)) {
        clicks += t.clicks;
        hasClicks = true;
      }
      if (typeof t.impressions === "number" && isFinite(t.impressions)) {
        impressions += t.impressions;
        hasImpressions = true;
      }
      // Only a row that CONTRIBUTES can date the aggregate — an advisory
      // bridge adds nothing to the sum, so its age says nothing about it.
      if (!reportsRowIsStale(p)) return;
      stale = true;
      const ms = Date.parse(p.freshness.fetched_at);
      if (!Number.isNaN(ms) && ms < staleSinceMs) {
        staleSinceMs = ms;
        staleSince = p.freshness.fetched_at;
      }
    });
    const doubleCounted = reportsHasDoubleCount(summary);
    const withheld = doubleCounted || stale;
    const restate = stale && !doubleCounted && (hasSpend || hasConv);
    return {
      spend: !withheld && hasSpend ? spend : null,
      conversions: !withheld && hasConv ? conv : null,
      cpa: !withheld && hasSpend && hasConv && conv > 0 ? spend / conv : null,
      // Percent, like every other CTR mureo prints. `null` — never 0 — when
      // the client carried no impressions to divide by, or when the totals
      // are withheld: a rate over an unstated denominator is not a rate.
      ctr:
        !withheld && hasClicks && hasImpressions && impressions > 0
          ? (clicks / impressions) * 100
          : null,
      hasFigures: hasSpend || hasConv,
      doubleCounted: doubleCounted,
      stale: stale,
      staleFigures: restate
        ? {
            spend: hasSpend ? spend : null,
            conversions: hasConv ? conv : null,
            cpa: hasSpend && hasConv && conv > 0 ? spend / conv : null,
            // `null` when no contributor carried a usable timestamp: mureo
            // says the age is unknown rather than inventing one.
            fetched_at: staleSince,
          }
        : null,
    };
  }

  const api = {
    REPORTS_CONFLICT_DUPLICATE_ACCOUNT: REPORTS_CONFLICT_DUPLICATE_ACCOUNT,
    REPORTS_CONFLICT_UNRECOGNIZED_KEY: REPORTS_CONFLICT_UNRECOGNIZED_KEY,
    relativeAge: relativeAge,
    reportsConflictsOfKind: reportsConflictsOfKind,
    reportsHasDoubleCount: reportsHasDoubleCount,
    reportsPlatformLabels: reportsPlatformLabels,
    reportsKeyList: reportsKeyList,
    reportsConflictText: reportsConflictText,
    reportsRepairHint: reportsRepairHint,
    reportsConflictsForKey: reportsConflictsForKey,
    reportsFreshnessLabel: reportsFreshnessLabel,
    reportsRowIsStale: reportsRowIsStale,
    reportsNotCollectedNote: reportsNotCollectedNote,
    reportsNotCollectedNotes: reportsNotCollectedNotes,
    reportsNotCollectedText: reportsNotCollectedText,
    reportsCardFreshness: reportsCardFreshness,
    aggregateClientKpis: aggregateClientKpis,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_REPORTS_LOGIC = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
