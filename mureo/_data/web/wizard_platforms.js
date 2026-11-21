// wizard_platforms.js — which platforms the configure wizard offers. A
// platform whose only path is a provider of its own name is offered only
// while /api/status `plugin_providers` lists that provider: a bundled
// provider switched off by its MUREO_DISABLE_* gate is not registered, so
// its credential slot would have no descriptor to render (#1048). DOM-free,
// loaded BEFORE wizard.js and consumed through window.MUREO_WIZARD_PLATFORMS.

(function () {
  "use strict";

  // The platforms served only by a provider whose name IS the platform key,
  // so the key is looked up in `plugin_providers` as it is.
  const PROVIDER_SERVED_PLATFORMS = ["amazon_ads", "chatgpt_ads"];

  function isPlatformOffered(platform, pluginProviders) {
    if (PROVIDER_SERVED_PLATFORMS.indexOf(platform) === -1) return true;
    return Array.isArray(pluginProviders) && pluginProviders.indexOf(platform) !== -1;
  }

  // A new array, in the input order.
  function offeredPlatforms(platforms, pluginProviders) {
    return platforms.filter(function (platform) {
      return isPlatformOffered(platform, pluginProviders);
    });
  }

  window.MUREO_WIZARD_PLATFORMS = {
    PROVIDER_SERVED_PLATFORMS: PROVIDER_SERVED_PLATFORMS,
    isPlatformOffered: isPlatformOffered,
    offeredPlatforms: offeredPlatforms,
  };
})();
