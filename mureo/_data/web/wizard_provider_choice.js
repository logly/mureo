// wizard_provider_choice.js — the Setup wizard's connection-choice cards,
// kept separate so wizard.js stays under the 800-line budget. One card
// per platform on the provider_choice step. Google Ads and Meta Ads offer
// "official MCP" and "mureo standard"; a plugin credential provider that
// declares `serves_platform` for the platform (hydrated from /api/status
// `plugin_platforms`) is offered as a third choice, labelled with the
// provider's own localized name. Search Console has no official MCP, so it
// only gets a card when such a provider serves it: "mureo standard" (the
// Google OAuth Google Ads uses) or that provider.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_WIZARD_CHOICE`. Must load BEFORE wizard.js, which calls it at
// render time with its STATE and its Next-button refresh.

(function () {
  "use strict";

  // Platforms whose official provider is a hosted_http catalog entry AND
  // that also expose a native<->official provider_choice card (auth is
  // client-side browser OAuth on first use in Claude). Source of truth:
  // catalog.py install_kind === "hosted_http". Only meta_ads qualifies:
  // TikTok is ALSO hosted_http but is official-only (no provider_choice
  // card), so it is intentionally excluded here and handled entirely by
  // its providers_install slot. Extend this list only for a hosted
  // platform that has a native<->official choice.
  const HOSTED_PLATFORMS = ["meta_ads"];

  // A card's value is "official", "native" or a plugin provider's name;
  // the one rule for the last case, shared by wizard.js (its own STATE)
  // and auth_wizards.js (the state it is handed).
  function isPluginChoice(state, platform) {
    const c = state.providerChoice[platform];
    return Boolean(c) && c !== "native" && c !== "official";
  }

  // Search Console's "mureo standard" shares the Google Ads sign-in only
  // when Google Ads takes the built-in path; otherwise the Search Console
  // step collects a Google sign-in of its own, so the wording says so.
  function searchConsoleNative(state) {
    const shared = Boolean(state.platforms.google_ads) && !isPluginChoice(state, "google_ads");
    return {
      value: "native",
      label: MUREO.t(shared
        ? "wizard.provider_choice.search_console_native"
        : "wizard.provider_choice.search_console_native_own"),
      descKey: shared
        ? "wizard.provider_choice.search_console.native_desc"
        : "wizard.provider_choice.search_console.native_own_desc",
    };
  }

  // The radios of one card, in display order. A plugin provider's option
  // carries its `plugin_platforms` entry so the badge can read `configured`.
  function choiceOptions(platform, state) {
    const served = state.pluginPlatforms && state.pluginPlatforms[platform];
    const plugin = [];
    if (served) {
      plugin.push({
        value: served.provider_name,
        label: served.display_name,
        descKey: null,
        plugin: served,
      });
    }
    if (platform === "search_console") return [searchConsoleNative(state)].concat(plugin);
    const officialKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads_official"
      : "wizard.provider_choice.meta_ads_official";
    const nativeKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads_native"
      : "wizard.provider_choice.meta_ads_native";
    // Optional benefit/desc lines — currently only Google Ads ships
    // them. MUREO.t falls back to the key
    // itself when missing, so we render only when the lookup actually
    // resolves to a different string.
    const officialDescKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads.official_desc"
      : null;
    const nativeBenefitKey = platform === "google_ads"
      ? "wizard.provider_choice.google_ads.mureo_benefit"
      : null;
    // Official first, mureo native second, a plugin provider last.
    return [
      { value: "official", label: MUREO.t(officialKey), descKey: officialDescKey },
      { value: "native", label: MUREO.t(nativeKey), descKey: nativeBenefitKey },
    ].concat(plugin);
  }

  // "Already configured" badge: the official MCP is registered, or the
  // plugin provider's section already holds every required field.
  function alreadyConfigured(platform, opt, state) {
    if (opt.plugin) return Boolean(opt.plugin.configured);
    return opt.value === "official" &&
      Boolean(state.providerInstalled[platform + "-official"]);
  }

  // One option: radio, label, badge, desc line, hosted note.
  function appendChoiceOption(wrap, platform, opt, state, onChange) {
    const label = document.createElement("label");
    label.style.display = "block";
    if (opt.plugin) label.setAttribute("data-plugin-choice", opt.value);
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "provider-" + platform;
    radio.value = opt.value;
    radio.checked = state.providerChoice[platform] === opt.value;
    radio.addEventListener("change", function () {
      state.providerChoice[platform] = radio.value;
      onChange();
    });
    label.appendChild(radio);
    label.appendChild(document.createTextNode(" " + opt.label));
    if (alreadyConfigured(platform, opt, state)) {
      const badge = document.createElement("span");
      badge.className = "wizard-choice-already-done";
      badge.textContent = "(" + MUREO.t("wizard.step_already_done") + ")";
      label.appendChild(badge);
    }
    wrap.appendChild(label);

    // Benefit/desc line — small muted text under the radio.
    if (opt.descKey) appendChoiceDesc(wrap, opt.descKey);

    // hosted_http note — attached DIRECTLY under the OFFICIAL option
    // (never at the bottom of the card, where it read as if it
    // described the mureo-native option). Makes clear it's the
    // official/hosted choice that is set up later via Connectors.
    if (
      opt.value === "official" &&
      HOSTED_PLATFORMS.indexOf(platform) !== -1
    ) {
      appendChoiceDesc(wrap, "wizard.provider_choice.hosted_oauth_note");
    }
  }

  // A muted line under an option. Rendered only when the key resolves to
  // a string different from the key (MUREO.t echoes the key on miss).
  function appendChoiceDesc(wrap, key) {
    const translated = MUREO.t(key);
    if (translated && translated !== key) {
      const desc = document.createElement("div");
      desc.className = "wizard-choice-desc";
      desc.textContent = translated;
      wrap.appendChild(desc);
    }
  }

  function buildChoiceCard(platform, state, onChange) {
    const wrap = document.createElement("fieldset");
    wrap.style.marginTop = "16px";
    const legend = document.createElement("legend");
    legend.textContent = MUREO.t("wizard.provider_banner." + platform);
    wrap.appendChild(legend);
    choiceOptions(platform, state).forEach(function (opt) {
      appendChoiceOption(wrap, platform, opt, state, onChange);
    });
    return wrap;
  }

  const api = {
    buildChoiceCard: buildChoiceCard,
    isPluginChoice: isPluginChoice,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_WIZARD_CHOICE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
