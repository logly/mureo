// The basic-setup skills row tells a stale set from an absent one (#728).
//
// Run with:  node --test tests/js/*.test.js
//
// Presence was the whole check: every shipped SKILL.md existed, so the row
// drew ✓ — on an install whose deployed copies came from a mureo five minor
// versions back, because `pip install -U mureo` never rewrites them. The
// status payload now carries the three states, and this pins what the row
// does with the middle one: not-ok, the two versions named, and the exact
// command that fixes it — for the host the operator is actually running.
//
// MUREO.t here returns the KEY (plus its interpolated params), so these
// assertions are about which string was chosen and what was put into it,
// never about English wording. The wording itself is pinned in
// tests/test_web_assets_stale_skills.py, in both locales.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage } = require("./dom_harness.js");

function renderBasic(status) {
  const page = loadDashboardPage({});
  page.sandbox.MUREO.state.status = status;
  page.sandbox.MUREO_DASHBOARD_SETUP.renderBasicSection(status);
  const rows = page.root
    .querySelector("[data-dashboard-basic-list]")
    .querySelectorAll("li");
  const row = rows.find(
    (li) => li.querySelector('[data-basic-install="skills"]') !== null
  );
  assert.ok(row, "the skills row must render");
  return row;
}

function skillsStatus(extra) {
  return Object.assign(
    {
      host: "claude-code",
      setup_parts: {
        mureo_mcp: true,
        auth_hook: true,
        skills: false,
        skills_state: "stale",
        skills_expected_version: "0.17.2",
        skills_installed_version: "0.10.39",
      },
    },
    extra || {}
  );
}

function note(row) {
  return row.querySelector(".dashboard-skills-stale-note");
}

test.describe("stale workflow skills read as not-ok, with the fix", function () {
  test.it("marks a stale set ✗, not ✓", function () {
    const row = renderBasic(skillsStatus());
    assert.equal(row.querySelector(".mark-no").textContent, "✗");
    assert.equal(row.querySelector(".mark-ok"), null);
  });

  test.it("names both versions in the note", function () {
    const row = renderBasic(skillsStatus());
    assert.match(
      note(row).textContent,
      /dashboard\.skills_stale_note\|installed=0\.10\.39,expected=0\.17\.2/
    );
  });

  test.it("shows the exact re-install command for the running host", function () {
    const row = renderBasic(skillsStatus());
    assert.equal(
      note(row).querySelector("code").textContent,
      "mureo setup claude-code --skip-auth"
    );
  });

  test.it("uses the codex command under codex", function () {
    const row = renderBasic(skillsStatus({ host: "codex" }));
    assert.equal(
      note(row).querySelector("code").textContent,
      "mureo setup codex --skip-auth"
    );
  });

  test.it("sends Desktop to the claude-code command", function () {
    // Claude Desktop deploys into the same ~/.claude/skills, and there is no
    // `mureo setup claude-desktop` subcommand to send anyone to.
    const row = renderBasic(skillsStatus({ host: "claude-desktop" }));
    assert.equal(
      note(row).querySelector("code").textContent,
      "mureo setup claude-code --skip-auth"
    );
  });

  test.it("says so when the copies record no version at all", function () {
    const status = skillsStatus();
    status.setup_parts.skills_installed_version = null;
    const row = renderBasic(status);
    assert.match(
      note(row).textContent,
      /dashboard\.skills_stale_note_unknown\|expected=0\.17\.2/
    );
  });

  test.it("keeps the re-install button, labelled as a re-install", function () {
    // The files ARE there — the button overwrites them, which is exactly the
    // remedy, so calling it "Install" would misdescribe what it does.
    const row = renderBasic(skillsStatus());
    const btn = row.querySelector('[data-basic-install="skills"]');
    assert.equal(btn.textContent, "dashboard.basic_reinstall");
  });

  test.it("leaves a current set alone", function () {
    const status = skillsStatus();
    status.setup_parts.skills = true;
    status.setup_parts.skills_state = "current";
    status.setup_parts.skills_installed_version = "0.17.2";
    const row = renderBasic(status);
    assert.equal(row.querySelector(".mark-ok").textContent, "✓");
    assert.equal(note(row), null);
  });

  test.it("says nothing extra about a set that was never installed", function () {
    // ``missing`` keeps the plain ✗ it always had: there is no version to
    // name, and "re-install to update them" is the wrong sentence for it.
    const status = skillsStatus();
    status.setup_parts.skills_state = "missing";
    status.setup_parts.skills_installed_version = null;
    const row = renderBasic(status);
    assert.equal(row.querySelector(".mark-no").textContent, "✗");
    assert.equal(note(row), null);
  });

  test.it("survives a status payload from an older server", function () {
    // A dashboard held open across an upgrade polls a server that may not
    // send the new fields yet; the row must still draw its boolean.
    const row = renderBasic({
      host: "claude-code",
      setup_parts: { mureo_mcp: true, auth_hook: true, skills: true },
    });
    assert.equal(row.querySelector(".mark-ok").textContent, "✓");
    assert.equal(note(row), null);
  });
});
