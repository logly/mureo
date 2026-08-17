// Behavioural tests for the "why the figures did not move" note in
// mureo/_data/web/reports_logic.js (#638).
//
// Run with:  node --test tests/js/*.test.js
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/reports_logic.js, no build step and no copy.
//
// The story, and why this is a separate decision from staleness: a card
// showed figures that had not moved for eleven days. #639 stopped mureo
// stating them as the selected window's answer — the cells read "—" and the
// numbers are restated with their age. That tells an operator the card is
// out of date. It does not tell them WHY, and without that there is nothing
// to do about it: a stopped ad account and a stopped collector produce the
// identical card. `platforms[].not_collected` is the missing half, and this
// file pins what the card is allowed to say about it.
//
// i18n: MUREO.t is stubbed to return the key it was handed and to record
// the interpolated params, so assertions are on WHICH string was chosen
// (and with what age / reason), not on English wording.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

/** Every MUREO.t(key, params) the code under test made, most recent last. */
const calls = [];

globalThis.MUREO = {
  t: function (key, params) {
    calls.push({ key: key, params: params || {} });
    return key;
  },
};

const logic = require(path.join(WEB, "reports_logic.js"));

test.beforeEach(function () {
  calls.length = 0;
});

/** Params of the most recent MUREO.t call for `key` (null if never called). */
function paramsFor(key) {
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    if (calls[i].key === key) return calls[i].params;
  }
  return null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** An ISO timestamp `ms` in the past, relative to now. */
function ago(ms) {
  return new Date(Date.now() - ms).toISOString();
}

const REASON = "the Meta access token expired";

function row(key, notCollected) {
  return {
    key: key,
    display_name: key.replace("_", " "),
    totals: { spend: 1 },
    freshness: { fetched_at: ago(DAY_MS), stale: false },
    not_collected: notCollected,
  };
}

test.describe("reportsNotCollectedNote", function () {
  test.it("reads the note off a row that carries one", function () {
    const note = logic.reportsNotCollectedNote(
      row("meta_ads", { attempted_at: ago(2 * DAY_MS), reason: REASON })
    );
    assert.equal(note.reason, REASON);
    assert.equal(note.key, "meta_ads");
    assert.equal(note.label, "meta ads");
    assert.equal(typeof note.attempted_at, "string");
  });

  test.it("falls back to the raw key when the row has no label", function () {
    const note = logic.reportsNotCollectedNote({
      key: "plugin:acme-ads",
      not_collected: { reason: REASON },
    });
    assert.equal(note.label, "plugin:acme-ads");
  });

  test.it("is null for a row with no note — the unchanged case", function () {
    // The overwhelming majority of rows. Nothing about their rendering may
    // depend on a field they do not have.
    const rows = [
      row("google_ads", null),
      row("google_ads", undefined),
      { key: "google_ads" },
      null,
      undefined,
      "nonsense",
      {},
    ];
    rows.forEach(function (r) {
      assert.equal(logic.reportsNotCollectedNote(r), null);
    });
  });

  test.it("is null when the note states no reason", function () {
    // A note that says something happened and refuses to say what is the
    // non-answer this field exists to end, so it is not rendered at all.
    const notes = [{}, { attempted_at: ago(DAY_MS) }, { reason: "   " }, { reason: 7 }];
    notes.forEach(function (n) {
      assert.equal(logic.reportsNotCollectedNote(row("google_ads", n)), null);
    });
  });

  test.it("treats an unusable attempted_at as no age rather than junk", function () {
    const note = logic.reportsNotCollectedNote(
      row("google_ads", { attempted_at: 12345, reason: REASON })
    );
    assert.equal(note.attempted_at, null);
    assert.equal(note.reason, REASON);
  });
});

test.describe("reportsNotCollectedNotes", function () {
  test.it("collects one note per platform that carries one", function () {
    const notes = logic.reportsNotCollectedNotes({
      platforms: [
        row("google_ads", null),
        row("meta_ads", { attempted_at: ago(DAY_MS), reason: REASON }),
        row("tiktok_ads", { reason: "the sync did not run" }),
      ],
    });
    assert.deepEqual(
      notes.map(function (n) {
        return n.key;
      }),
      ["meta_ads", "tiktok_ads"]
    );
  });

  test.it("is empty for a summary with none — nothing new renders", function () {
    for (const summary of [null, undefined, {}, { platforms: [] }, "nonsense"]) {
      assert.deepEqual(logic.reportsNotCollectedNotes(summary), []);
    }
  });

  test.it("reports a platform that contributes no totals at all", function () {
    // The opposite of the staleness rule, on purpose. A platform with no
    // figures cannot date an aggregate — but "there are no figures, and here
    // is why" is exactly the sentence an operator is missing.
    const notes = logic.reportsNotCollectedNotes({
      platforms: [{ key: "meta_ads", totals: null, not_collected: { reason: REASON } }],
    });
    assert.equal(notes.length, 1);
    assert.equal(notes[0].reason, REASON);
  });
});

test.describe("reportsNotCollectedText", function () {
  test.it("says which platform, how long ago, and why", function () {
    const note = logic.reportsNotCollectedNote(
      row("meta_ads", { attempted_at: ago(3 * DAY_MS), reason: REASON })
    );
    assert.equal(logic.reportsNotCollectedText(note), "dashboard.reports_not_collected");
    const params = paramsFor("dashboard.reports_not_collected");
    assert.equal(params.platform, "meta ads");
    assert.equal(params.reason, REASON);
    assert.equal(params.ago, "dashboard.reports_age_days");
    assert.equal(paramsFor("dashboard.reports_age_days").n, 3);
  });

  test.it("says so plainly when it cannot quote a time", function () {
    // A dangling "could not be collected : …" would read as a claim about
    // now. The undated string states the same fact without inventing one.
    const note = logic.reportsNotCollectedNote(row("meta_ads", { reason: REASON }));
    assert.equal(
      logic.reportsNotCollectedText(note),
      "dashboard.reports_not_collected_undated"
    );
    assert.equal(
      paramsFor("dashboard.reports_not_collected_undated").reason,
      REASON
    );
  });

  test.it("returns an empty string for no note rather than throwing", function () {
    // It runs mid-render; a throw here blanks the whole Reports view.
    for (const bad of [null, undefined, {}, "nonsense"]) {
      assert.equal(logic.reportsNotCollectedText(bad), "");
    }
  });
});

test.describe("the note is independent of the figures", function () {
  test.it("does not change the aggregate in any way", function () {
    // It explains the numbers; it never restates or withholds them. A note
    // is NOT evidence that the stored figures are wrong — they are the last
    // ones truly collected — so withholding on it would hide good data.
    const withNote = logic.aggregateClientKpis({
      platforms: [
        {
          key: "google_ads",
          totals: { spend: 1000, conversions: 40 },
          freshness: { fetched_at: ago(60 * 60 * 1000), stale: false },
          not_collected: { attempted_at: ago(DAY_MS), reason: REASON },
        },
      ],
    });
    assert.equal(withNote.spend, 1000);
    assert.equal(withNote.conversions, 40);
    assert.equal(withNote.stale, false);
    assert.equal(withNote.staleFigures, null);
  });

  test.it("stands beside a stale verdict without consuming it", function () {
    // The two answer different questions — "how old is this?" and "why is it
    // not newer?" — and a card in this state shows both.
    const summary = {
      platforms: [
        {
          key: "meta_ads",
          display_name: "Meta Ads",
          totals: { spend: 25862, conversions: 2 },
          freshness: { fetched_at: ago(11 * DAY_MS), stale: true },
          not_collected: { attempted_at: ago(DAY_MS), reason: REASON },
        },
      ],
    };
    const kpis = logic.aggregateClientKpis(summary);
    assert.equal(kpis.spend, null);
    assert.equal(kpis.staleFigures.spend, 25862);
    assert.equal(logic.reportsNotCollectedNotes(summary).length, 1);
  });
});
