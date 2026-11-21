// Which platforms the configure wizard offers (#1048).
//
// Amazon Ads and ChatGPT Ads have no path but the bundled provider of the
// same name. When that provider is switched off it is not registered, the
// server has no descriptor for it, and /api/status `plugin_providers` does
// not list it: the wizard must not offer the platform, or its credential
// slot has nothing to render and the run still reports the platform set up.

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadWizardPage } = require("./dom_harness");

function platformsModule() {
  return loadWizardPage({}).sandbox.MUREO_WIZARD_PLATFORMS;
}

const ALL = [
  "google_ads",
  "meta_ads",
  "search_console",
  "ga4",
  "tiktok_ads",
  "amazon_ads",
  "chatgpt_ads",
];

test.describe("PROVIDER_SERVED_PLATFORMS", () => {
  test("names the platforms served only by a provider of the same name", () => {
    const mod = platformsModule();
    assert.deepEqual(Array.from(mod.PROVIDER_SERVED_PLATFORMS), [
      "amazon_ads",
      "chatgpt_ads",
    ]);
  });
});

test.describe("isPlatformOffered", () => {
  test("a built-in platform is always offered", () => {
    const mod = platformsModule();
    ["google_ads", "meta_ads", "search_console", "ga4", "tiktok_ads"].forEach(
      function (p) {
        assert.equal(mod.isPlatformOffered(p, []), true, p);
        assert.equal(mod.isPlatformOffered(p, undefined), true, p);
      }
    );
  });

  test("a provider-served platform is offered only when its provider is listed", () => {
    const mod = platformsModule();
    assert.equal(mod.isPlatformOffered("amazon_ads", ["amazon_ads"]), true);
    assert.equal(mod.isPlatformOffered("amazon_ads", ["chatgpt_ads"]), false);
    assert.equal(mod.isPlatformOffered("chatgpt_ads", ["chatgpt_ads"]), true);
    assert.equal(
      mod.isPlatformOffered("chatgpt_ads", ["amazon_ads", "acme_ads_context"]),
      false
    );
  });

  test("a missing or empty provider list offers no provider-served platform", () => {
    const mod = platformsModule();
    assert.equal(mod.isPlatformOffered("amazon_ads", undefined), false);
    assert.equal(mod.isPlatformOffered("chatgpt_ads", null), false);
    assert.equal(mod.isPlatformOffered("chatgpt_ads", []), false);
  });
});

test.describe("offeredPlatforms", () => {
  test("keeps every platform when both providers are listed", () => {
    const mod = platformsModule();
    const offered = mod.offeredPlatforms(ALL, ["amazon_ads", "chatgpt_ads"]);
    assert.deepEqual(Array.from(offered), ALL);
  });

  test("drops an unlisted provider-served platform, keeping the order", () => {
    const mod = platformsModule();
    const offered = mod.offeredPlatforms(ALL, ["amazon_ads"]);
    assert.deepEqual(Array.from(offered), [
      "google_ads",
      "meta_ads",
      "search_console",
      "ga4",
      "tiktok_ads",
      "amazon_ads",
    ]);
  });

  test("a missing provider list leaves only the built-in platforms", () => {
    const mod = platformsModule();
    assert.deepEqual(Array.from(mod.offeredPlatforms(ALL, undefined)), ALL.slice(0, 5));
  });

  test("returns a new array and leaves the input untouched", () => {
    const mod = platformsModule();
    const input = ALL.slice();
    const offered = mod.offeredPlatforms(input, ["amazon_ads", "chatgpt_ads"]);
    assert.notEqual(offered, input);
    assert.deepEqual(input, ALL);
    mod.offeredPlatforms(input, []);
    assert.deepEqual(input, ALL);
  });
});
