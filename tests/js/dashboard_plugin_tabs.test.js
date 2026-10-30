// The dashboard's Connection credentials section shows one tab per provider
// (#954).
//
// Run with:  node --test tests/js/*.test.js
//
// Stacked collapsed cards made an operator open each provider in turn to
// find the one they came for. The section now renders a tab strip and one
// panel per provider, only the chosen panel visible. The choice is module
// state, so a re-render (an OAuth consent completing re-renders the whole
// section) keeps the operator on the provider they picked.
//
// Driven against the real dashboard_plugins.js and app.css. The harness's
// MUREO.t returns the key it was given.

const test = require("node:test");
const assert = require("node:assert/strict");

const { cascade, loadDashboardPage, settle } = require("./dom_harness.js");

function plugin(name, label, fieldKey) {
  return {
    provider_name: name,
    display_name: label,
    fields: [{ key: fieldKey, display_name: fieldKey, secret: false }],
  };
}

const THREE = [
  plugin("alpha", "Alpha Ads", "alpha_id"),
  plugin("beta", "Beta Ads", "beta_id"),
  plugin("gamma", "Gamma Ads", "gamma_id"),
];

/** Render the section for `plugins`; the page and its list container. */
async function renderSection(plugins) {
  const page = loadDashboardPage({ "/api/credentials/plugins": { plugins: plugins } });
  await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
  await settle();
  const list = page.root.querySelector("[data-dashboard-plugin-credentials-list]");
  return { page: page, list: list };
}

function tabs(list) {
  return list.querySelectorAll('[role="tab"]');
}

function panels(list) {
  return list.querySelectorAll('[role="tabpanel"]');
}

/** The provider_name of every tab marked active, in strip order. */
function activeTabs(list) {
  return tabs(list)
    .filter(function (tab) {
      return tab.classList.contains("is-active");
    })
    .map(function (tab) {
      return tab.getAttribute("data-plugin-tab");
    });
}

/**
 * The provider_name of every panel an operator would see. Read through the
 * real cascade: the card rule gives a panel `display: block`, which beats
 * the UA `[hidden]` rule, so a `hidden` attribute alone proves nothing.
 */
function shownPanels(list) {
  return panels(list)
    .filter(function (panel) {
      const display = cascade(panel, "display");
      return !(display && display.value === "none");
    })
    .map(function (panel) {
      return panel.getAttribute("data-plugin-panel");
    });
}

function assertActive(list, name) {
  assert.deepEqual(activeTabs(list), [name]);
  assert.deepEqual(shownPanels(list), [name]);
  tabs(list).forEach(function (tab) {
    const on = tab.getAttribute("data-plugin-tab") === name;
    assert.equal(tab.getAttribute("aria-selected"), on ? "true" : "false");
    assert.equal(tab.getAttribute("tabindex"), on ? "0" : "-1");
  });
}

function pressKey(list, key) {
  const strip = list.querySelector('[role="tablist"]');
  strip.dispatchEvent({ type: "keydown", key: key });
}

test.describe("Connection credentials tabs", function () {
  test.it("renders one tab and one panel per provider, the first active", async function () {
    const { list } = await renderSection(THREE);
    const strip = list.querySelector('[role="tablist"]');
    assert.ok(strip, "no tablist rendered");
    assert.equal(strip.getAttribute("aria-label"), "dashboard.plugin_credentials_title");
    assert.deepEqual(
      tabs(list).map(function (tab) {
        return tab.textContent;
      }),
      ["Alpha Ads", "Beta Ads", "Gamma Ads"]
    );
    assertActive(list, "alpha");
    THREE.forEach(function (p) {
      const panel = list.querySelector('[data-plugin-panel="' + p.provider_name + '"]');
      assert.ok(panel, "no panel for " + p.provider_name);
      const tab = list.querySelector('[data-plugin-tab="' + p.provider_name + '"]');
      assert.equal(tab.getAttribute("aria-controls"), panel.id);
      assert.equal(panel.getAttribute("aria-labelledby"), tab.id);
      const fieldKey = p.fields[0].key;
      const input = panel.querySelectorAll("input").find(function (el) {
        return el.name === fieldKey;
      });
      assert.ok(input, p.provider_name + "'s panel lacks its form");
    });
  });

  test.it("a click switches the active tab and the visible panel", async function () {
    const { list } = await renderSection(THREE);
    tabs(list)[1].click();
    assertActive(list, "beta");
  });

  test.it("keeps the chosen tab across a re-render", async function () {
    const { page, list } = await renderSection(THREE);
    tabs(list)[1].click();
    await page.sandbox.MUREO_DASHBOARD_PLUGINS.renderPluginCredentials();
    await settle();
    assert.equal(tabs(list).length, 3, "the re-render appended a second strip");
    assertActive(list, "beta");
  });

  test.it("moves with the arrow keys, wrapping, and jumps with Home / End", async function () {
    const { list } = await renderSection(THREE);
    const focused = [];
    tabs(list).forEach(function (tab) {
      tab.focus = function () {
        focused.push(tab.getAttribute("data-plugin-tab"));
      };
    });
    pressKey(list, "End");
    assertActive(list, "gamma");
    pressKey(list, "ArrowRight");
    assertActive(list, "alpha");
    pressKey(list, "ArrowLeft");
    assertActive(list, "gamma");
    pressKey(list, "Home");
    assertActive(list, "alpha");
    pressKey(list, "ArrowRight");
    assertActive(list, "beta");
    assert.deepEqual(focused, ["gamma", "alpha", "gamma", "alpha", "beta"]);
    pressKey(list, "Enter");
    assertActive(list, "beta");
  });

  test.it("still titles a single provider with its tab", async function () {
    const { list } = await renderSection([plugin("solo", "Solo Ads", "solo_id")]);
    assert.equal(tabs(list).length, 1);
    assert.equal(tabs(list)[0].textContent, "Solo Ads");
    assertActive(list, "solo");
  });

  test.it("shows the empty state and no tablist without providers", async function () {
    const { list } = await renderSection([]);
    assert.equal(list.querySelector('[role="tablist"]'), null);
    const empty = list.querySelector("p");
    assert.ok(empty, "no empty-state paragraph");
    assert.ok(empty.classList.contains("muted"));
    assert.equal(empty.textContent, "dashboard.plugin_credentials_empty");
  });

  test.it("derives element ids from a provider name with unsafe characters", async function () {
    const { list } = await renderSection([plugin("odd name:1", "Odd", "odd_id")]);
    const tab = tabs(list)[0];
    assert.equal(tab.id, "plugin-tab-odd-name-1");
    assert.equal(tab.getAttribute("aria-controls"), "plugin-panel-odd-name-1");
    assert.equal(tab.getAttribute("data-plugin-tab"), "odd name:1");
  });
});
