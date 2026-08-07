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
    return MUREO.t("dashboard.reports_conflict_unknown_key", { keys: keys });
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
  function aggregateClientKpis(summary) {
    const platforms =
      summary && Array.isArray(summary.platforms) ? summary.platforms : [];
    let spend = 0;
    let conv = 0;
    let hasSpend = false;
    let hasConv = false;
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
    });
    const doubleCounted = reportsHasDoubleCount(summary);
    return {
      spend: !doubleCounted && hasSpend ? spend : null,
      conversions: !doubleCounted && hasConv ? conv : null,
      cpa:
        !doubleCounted && hasSpend && hasConv && conv > 0 ? spend / conv : null,
      hasFigures: hasSpend || hasConv,
      doubleCounted: doubleCounted,
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
    reportsConflictsForKey: reportsConflictsForKey,
    reportsFreshnessLabel: reportsFreshnessLabel,
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
