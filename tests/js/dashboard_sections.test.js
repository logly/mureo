// Every left-nav item opens, and the wider shell did not break any of them.
//
// Run with:  node --test tests/js/*.test.js
//
// The dashboard's frame was widened for all of it, not for Reports alone: a
// shell that resized as the operator moved between the left-nav items would
// read as a broken layout. And it was widened FOR the content, so the
// content follows it — the lists, rows and tables that make up these screens
// take the width they are given. The one thing that does not survive being
// stretched is a single-line field, and the answer there is not to cap it
// and leave it alone on the left of an empty frame (the very layout this
// width exists to end) but to let the fields flow side by side.
//
// This drives the real dashboard.js against the real app.html and clicks
// every nav item, which is the part that had no coverage at all: the health
// filter shipped broken because nothing here ever clicked anything.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadDashboardPage, settle, isVisible } = require("./dom_harness.js");


async function openDashboard() {
  const page = loadDashboardPage({
    "/api/reports/clients": { clients: [], can_archive: false },
    "/api/reports/summary": {},
  });
  page.document.dispatchEvent({ type: "mureo:ready" });
  await settle();
  return page;
}

function navNames(page) {
  return page.root
    .querySelectorAll("[data-dashboard-nav]")
    .map((el) => el.getAttribute("data-dashboard-nav"));
}

test.describe("every left-nav item opens its section", function () {
  test.it("has a group for every nav item and a nav item for every group", async function () {
    const page = await openDashboard();
    const groups = page.root
      .querySelectorAll("[data-dashboard-group]")
      .map((el) => el.getAttribute("data-dashboard-group"));
    assert.deepEqual(navNames(page).slice().sort(), groups.slice().sort());
  });

  test.it("shows exactly the section that was clicked", async function () {
    const page = await openDashboard();
    for (const name of navNames(page)) {
      const nav = page.root
        .querySelectorAll("[data-dashboard-nav]")
        .find((el) => el.getAttribute("data-dashboard-nav") === name);
      nav.click();
      await settle();
      const shown = page.root
        .querySelectorAll("[data-dashboard-group]")
        .filter(isVisible)
        .map((el) => el.getAttribute("data-dashboard-group"));
      assert.deepEqual(shown, [name], "clicking " + name + " showed " + shown.join(", "));
    }
  });

  test.it("renders content into every section", async function () {
    // Not a screenshot, but it does catch a section that throws on the way
    // in or whose container the markup no longer has.
    const page = await openDashboard();
    for (const name of navNames(page)) {
      const group = page.root
        .querySelectorAll("[data-dashboard-group]")
        .find((el) => el.getAttribute("data-dashboard-group") === name);
      const sections = group.querySelectorAll(".dashboard-section");
      assert.ok(sections.length > 0, name + " has no .dashboard-section");
      sections.forEach(function (section) {
        assert.ok(section.children.length > 0, name + " has an empty section");
      });
    }
  });
});

test.describe("the wider frame is used by what is in it", function () {
  const fs = require("node:fs");
  const path = require("node:path");
  const css = fs.readFileSync(
    path.join(__dirname, "..", "..", "mureo", "_data", "web", "app.css"),
    "utf-8"
  );

  test.it("caps nothing back to the old width", async function () {
    // The frame was widened FOR the content. A rule that capped every
    // section's children would have made the change invisible everywhere
    // except Reports, which is what the first attempt at this did.
    assert.ok(!css.includes(".dashboard-section > * {"), "the content is capped");
    assert.ok(!css.includes("--dashboard-measure"), "the measure is back");
  });

  test.it("gives every section something that stretches", async function () {
    // Lists, tables and rows have no width of their own, so they take the
    // frame's. This asserts each section actually contains one of them
    // rather than being a lone narrow column on the left.
    const page = await openDashboard();
    const STRETCHY = ["UL", "TABLE", "P", "DIV", "DETAILS", "FORM"];
    for (const name of navNames(page)) {
      const group = page.root
        .querySelectorAll("[data-dashboard-group]")
        .find((el) => el.getAttribute("data-dashboard-group") === name);
      const kinds = new Set();
      group.querySelectorAll(".dashboard-section").forEach(function (section) {
        section.children.forEach((c) => kinds.add(c.tagName));
      });
      assert.ok(
        STRETCHY.some((tag) => kinds.has(tag)),
        name + " has nothing in it that follows the width: " + Array.from(kinds)
      );
    }
  });

  test.it("keeps a name/value table readable instead of stretching it", async function () {
    // The exception to "content follows the frame", and the reason it is one:
    // the About table's two columns exist to associate a package with its
    // version, and at 1600px the two sit half a metre apart. The BYOD status
    // table next to it keeps the full width — its columns are a platform, a
    // mode and a free-text detail, which is a different job.
    const about = css.slice(css.indexOf(".dashboard-about-table {"));
    const body = about.slice(0, about.indexOf("}"));
    assert.match(body, /width:\s*auto/);
    assert.match(body, /max-width:\s*\d+px/);
    assert.ok(
      !css.includes(".dashboard-byod-table {"),
      "the BYOD table grew a width of its own — it should follow the frame"
    );
  });

  test.it("keeps a hidden field block hidden now that it has a display", async function () {
    // `.advisor-fields` is swapped by transport with `hidden`, and anything
    // that gives it an explicit `display` re-opens the exact hole the health
    // filter fell through. This is the check, not a comment about it.
    const { DISPLAY_BY_CLASS, HIDDEN_DISPLAY_BY_CLASS } = require("./dom_harness.js");
    const display = DISPLAY_BY_CLASS.get("advisor-fields");
    if (display && display !== "none") {
      assert.equal(
        HIDDEN_DISPLAY_BY_CLASS.get("advisor-fields"),
        "none",
        ".advisor-fields declares a display and cannot be hidden any more"
      );
    }
  });
});
