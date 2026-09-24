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

  // Which fact a stale verdict was taken on (#798): the freshness block's
  // `judged_on`, named once here for every surface that reads it. The SERVER
  // decides it (mureo/web/report_freshness.py) and the screen never
  // re-derives it — a second copy of "was the coverage date parseable?"
  // would drift from the one that actually reached the verdict.
  const REPORTS_STALE_BASIS_PERIOD_END = "period_end";
  const REPORTS_STALE_BASIS_FETCHED_AT = "fetched_at";

  // The rollup totals keys that are NOT metrics: the window, the write time
  // and the covered date (#798). Anything that lists a rollup's figures
  // skips these — a date rendered as a metric reads as a number nobody
  // measured.
  const REPORTS_NON_METRIC_TOTALS_KEYS = Object.freeze([
    "period",
    "fetched_at",
    "period_end",
  ]);

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

  // An age for `iso`, or "" when it is not a timestamp. Unlike relativeAge
  // this never falls back to the raw string: a line that already names the
  // covered date says the update time is unknown rather than printing
  // whatever the writer put in `fetched_at` (#798).
  function reportsQuotableAge(iso) {
    if (typeof iso !== "string" || !iso) return "";
    return Number.isNaN(Date.parse(iso)) ? "" : relativeAge(iso);
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

  // A row's own freshness as {text, stale}. `stale === null` (neither date
  // could be interpreted) is its own state — "unknown", not "fresh" —
  // because both fields are optional and writer-dependent.
  //
  // TWO facts, never blended (#798): `period_end` is the last day the
  // figures COVER and `fetched_at` is when they were written. A card saying
  // only the second read as the first — "Updated 14h ago" over the day
  // before yesterday's numbers — which is the whole of #798. So when the
  // server judged the row on its covered date the line names it, beside the
  // update time where that can be quoted; when it judged on the write time
  // the wording is exactly what it was.
  //
  // `stale` still comes from the server and outranks both: this picks the
  // sentence, it does not reach a verdict.
  function reportsFreshnessLabel(freshness) {
    const f = freshness && typeof freshness === "object" ? freshness : null;
    const basis = f && f.stale != null ? reportsStaleBasis(f) : null;
    if (!basis) {
      return { text: MUREO.t("dashboard.reports_platform_age_unknown"), stale: false };
    }
    const stale = !!f.stale;
    if (basis.kind === REPORTS_STALE_BASIS_PERIOD_END) {
      return reportsCoveredLabel(basis.date, f.fetched_at, stale);
    }
    return {
      text: MUREO.t(
        stale ? "dashboard.reports_platform_stale" : "dashboard.reports_platform_updated",
        { ago: relativeAge(basis.at) }
      ),
      stale: stale,
    };
  }

  // The line for figures judged on their covered date. The date alone
  // decided the verdict, so it is stated whether or not the write time can
  // be quoted — a missing or unparseable `fetched_at` makes the update time
  // "unknown", never the whole line, and never a raw string on screen.
  function reportsCoveredLabel(date, fetchedAt, stale) {
    const ago = reportsQuotableAge(fetchedAt);
    let key;
    if (ago) {
      key = stale
        ? "dashboard.reports_platform_covered_stale"
        : "dashboard.reports_platform_covered_updated";
    } else {
      key = stale
        ? "dashboard.reports_platform_covered_stale_age_unknown"
        : "dashboard.reports_platform_covered_age_unknown";
    }
    return {
      text: MUREO.t(key, ago ? { date: date, ago: ago } : { date: date }),
      stale: stale,
    };
  }

  // Which fact a verdict was taken on, and its value (#798):
  //   { kind: REPORTS_STALE_BASIS_PERIOD_END, date }  — the covered day
  //   { kind: REPORTS_STALE_BASIS_FETCHED_AT, at }    — the write time
  //   null                                            — neither is usable
  //
  // Reads anything carrying `{judged_on, period_end, fetched_at}`: a
  // platform's freshness block, a triage row, a card's restated figures.
  // Only `judged_on` selects the coverage date — the server relays an
  // uninterpretable `period_end` verbatim and `judged_on` is how it says the
  // value decided nothing — so the date is returned exactly as sent, never
  // trimmed or reformatted into one nobody wrote. A payload with no
  // `judged_on` (an older daemon) is read the way it always was: on
  // `fetched_at`.
  function reportsStaleBasis(stated) {
    const s = stated && typeof stated === "object" ? stated : null;
    if (!s) return null;
    if (s.judged_on === REPORTS_STALE_BASIS_PERIOD_END) {
      return typeof s.period_end === "string" && s.period_end
        ? { kind: REPORTS_STALE_BASIS_PERIOD_END, date: s.period_end }
        : null;
    }
    return typeof s.fetched_at === "string" && s.fetched_at
      ? { kind: REPORTS_STALE_BASIS_FETCHED_AT, at: s.fetched_at }
      : null;
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
  //
  // The covered date (#798): when EVERY contributor was judged on its
  // covered day, the card states the EARLIEST one — a sum only covers as far
  // as its shortest-covering input — with the oldest update time beside it
  // where every contributor's can be quoted. One contributor judged on its
  // write time means no single day describes the card, and it reads exactly
  // as it did before #798.
  function reportsCardFreshness(summary) {
    const platforms =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    const seen = reportsCardFreshnessInputs(platforms);
    if (!seen.unknown && seen.any && seen.allCovered) {
      const quotable = !seen.missingAt && !seen.badAt;
      return reportsCoveredLabel(
        seen.covered,
        quotable ? seen.oldestAt : null,
        seen.stale
      );
    }
    if (seen.unknown || seen.missingAt || !seen.oldestAt) {
      return {
        text: MUREO.t(
          seen.stale
            ? "dashboard.reports_platform_stale_partial"
            : "dashboard.reports_platform_age_unknown"
        ),
        stale: seen.stale,
      };
    }
    return reportsFreshnessLabel({ fetched_at: seen.oldestAt, stale: seen.stale });
  }

  // One pass over a card's contributors for reportsCardFreshness: which
  // could not be judged at all, whether every one was judged on its covered
  // day (and the earliest such day), and the oldest parseable write time —
  // plus whether any write time was missing (`missingAt`) or present but
  // unparseable (`badAt`), which the two wordings treat differently.
  function reportsCardFreshnessInputs(platforms) {
    const seen = {
      any: false, unknown: false, stale: false, allCovered: true, covered: "",
      oldestAt: null, missingAt: false, badAt: false,
    };
    let oldestMs = Infinity;
    platforms.forEach(function (p) {
      if (!p || !p.totals || typeof p.totals !== "object") return;
      const f = p.freshness && typeof p.freshness === "object" ? p.freshness : null;
      const basis = f && f.stale != null ? reportsStaleBasis(f) : null;
      if (!basis) {
        seen.unknown = true;
        return;
      }
      seen.any = true;
      if (f.stale) seen.stale = true;
      // String comparison: the server only judges on a date it parsed as
      // YYYY-MM-DD, and that shape sorts correctly as text.
      if (basis.kind !== REPORTS_STALE_BASIS_PERIOD_END) seen.allCovered = false;
      else if (!seen.covered || basis.date < seen.covered) seen.covered = basis.date;
      if (typeof f.fetched_at !== "string" || !f.fetched_at) {
        seen.missingAt = true;
        return;
      }
      const ms = Date.parse(f.fetched_at);
      if (Number.isNaN(ms)) seen.badAt = true;
      else if (ms < oldestMs) {
        oldestMs = ms;
        seen.oldestAt = f.fetched_at;
      }
    });
    return seen;
  }

  // What a client's WITHHELD figures are stated against (#798), as
  // `{judged_on, period_end, fetched_at}` — the same shape a freshness block
  // carries, so reportsStaleBasis reads it too — or null when no row is
  // stale. Only stale rows count: they are the reason the figures are
  // withheld, and a fresh sibling says nothing about them.
  //
  // The EARLIEST covered day when every stale row was judged on its covered
  // day; otherwise the verdict stands on a write time somewhere, and the
  // oldest write time is what is quoted, exactly as before #798.
  // `fetched_at` is the oldest parseable write time among the stale rows in
  // both cases (null when none is), because the note under the cells quotes
  // when the figures were collected either way.
  function reportsAggregateStaleFacts(rows) {
    let any = false;
    let allCovered = true;
    let covered = "";
    let oldest = null;
    let oldestMs = Infinity;
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      if (!reportsRowIsStale(row)) return;
      any = true;
      const f = row.freshness;
      const basis = reportsStaleBasis(f);
      if (!basis || basis.kind !== REPORTS_STALE_BASIS_PERIOD_END) allCovered = false;
      else if (!covered || basis.date < covered) covered = basis.date;
      const ms = typeof f.fetched_at === "string" ? Date.parse(f.fetched_at) : NaN;
      if (!Number.isNaN(ms) && ms < oldestMs) {
        oldestMs = ms;
        oldest = f.fetched_at;
      }
    });
    if (!any) return null;
    return {
      judged_on: allCovered ? REPORTS_STALE_BASIS_PERIOD_END : REPORTS_STALE_BASIS_FETCHED_AT,
      period_end: allCovered ? covered : null,
      fetched_at: oldest,
    };
  }

  // The withheld figures restated as what they ARE (#638), as one sentence.
  // `stated` is `{judged_on, period_end, fetched_at}` — a platform's
  // freshness block or a card's restated figures.
  //
  // Judged on the covered day, the sentence names that day and says when the
  // figures were collected, or that the collection time is unknown (#798).
  // Judged on the write time, it reads exactly as before: "Last collected
  // N ago", or unknown when no time can be quoted.
  function reportsStaleFiguresText(stated, figuresText) {
    const s = stated && typeof stated === "object" ? stated : {};
    const basis = reportsStaleBasis(s);
    if (basis && basis.kind === REPORTS_STALE_BASIS_PERIOD_END) {
      const ago = reportsQuotableAge(s.fetched_at);
      return MUREO.t(
        ago
          ? "dashboard.reports_stale_figures_to"
          : "dashboard.reports_stale_figures_to_unknown",
        ago
          ? { date: basis.date, ago: ago, figures: figuresText }
          : { date: basis.date, figures: figuresText }
      );
    }
    const age = s.fetched_at ? relativeAge(s.fetched_at) : null;
    return MUREO.t(
      age
        ? "dashboard.reports_stale_last_collected"
        : "dashboard.reports_stale_last_collected_unknown",
      { ago: age, figures: figuresText }
    );
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
  // oldest stale contributor's `fetched_at` (and, since #798, the covered
  // day the verdict was taken on), so the card can restate them as what they
  // ARE ("11d ago: 25,862") instead of what they are not. It is
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
    const staleRows = [];
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
      staleRows.push(p);
    });
    const facts = reportsAggregateStaleFacts(staleRows);
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
            fetched_at: facts ? facts.fetched_at : null,
            // What the verdict was taken on (#798), so the note under the
            // cells can name the covered day — see reportsAggregateStaleFacts.
            period_end: facts ? facts.period_end : null,
            judged_on: facts ? facts.judged_on : null,
          }
        : null,
    };
  }

  const api = {
    REPORTS_CONFLICT_DUPLICATE_ACCOUNT: REPORTS_CONFLICT_DUPLICATE_ACCOUNT,
    REPORTS_CONFLICT_UNRECOGNIZED_KEY: REPORTS_CONFLICT_UNRECOGNIZED_KEY,
    REPORTS_STALE_BASIS_PERIOD_END: REPORTS_STALE_BASIS_PERIOD_END,
    REPORTS_STALE_BASIS_FETCHED_AT: REPORTS_STALE_BASIS_FETCHED_AT,
    REPORTS_NON_METRIC_TOTALS_KEYS: REPORTS_NON_METRIC_TOTALS_KEYS,
    relativeAge: relativeAge,
    reportsQuotableAge: reportsQuotableAge,
    reportsConflictsOfKind: reportsConflictsOfKind,
    reportsHasDoubleCount: reportsHasDoubleCount,
    reportsPlatformLabels: reportsPlatformLabels,
    reportsKeyList: reportsKeyList,
    reportsConflictText: reportsConflictText,
    reportsRepairHint: reportsRepairHint,
    reportsConflictsForKey: reportsConflictsForKey,
    reportsFreshnessLabel: reportsFreshnessLabel,
    reportsStaleBasis: reportsStaleBasis,
    reportsAggregateStaleFacts: reportsAggregateStaleFacts,
    reportsStaleFiguresText: reportsStaleFiguresText,
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
