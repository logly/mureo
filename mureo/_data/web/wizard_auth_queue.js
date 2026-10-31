// wizard_auth_queue.js — which slots the configure wizard's auth step
// shows, and in what order: the Google OAuth slot shared by Google Ads and
// Search Console, Meta, GA4, Amazon Ads, and a plugin provider chosen for a
// built-in platform. Also the "already stored" checks the step uses to
// explain a skipped slot. DOM-free queue construction, separate from the
// DOM-driven step rendering in auth_wizards.js. Loaded BEFORE it and
// consumed through window.MUREO_AUTH_QUEUE; the plugin-choice rule is read
// off window.MUREO_WIZARD_CHOICE at call time.

(function () {
  "use strict";

  function googleHasOauthOnDisk(state) {
    // True iff /api/status reported credentials_oauth.google. The
    // adwords + webmasters scopes share a single refresh token (see
    // mureo.auth_setup._GOOGLE_SCOPES), so any prior Google OAuth
    // satisfies both Google Ads and Search Console requirements.
    return Boolean(
      state.existing && state.existing.google && state.existing.google.has_oauth
    );
  }

  function googleOauthSlotNeeded(state) {
    // A saved Google OAuth is reused rather than re-collected, unless the
    // operator pressed "Re-authorize Google" on the auth step (which sets
    // reauthorizeGoogle for this wizard run only).
    return !googleHasOauthOnDisk(state) || Boolean(state.reauthorizeGoogle);
  }

  // The store already holds a complete (usable) ``ga4`` section (an ADC
  // file path + project id, possibly written by a credential provider's
  // ``on_oauth_persisted`` hook), so the input slot is skipped. Edits go
  // through the dashboard env-var rows. ga4SavedByGoogleOauth is the
  // run-local flag the auth step sets when the Google authorization just
  // saved the section; wizard.js keeps reading existing.ga4.configured for
  // the step list, so the flag cannot drop the auth step mid-run.
  function ga4CredentialsOnDisk(state) {
    return (
      Boolean(state.existing && state.existing.ga4 && state.existing.ga4.configured) ||
      Boolean(state.ga4SavedByGoogleOauth)
    );
  }

  // The one plugin-choice rule lives in wizard_provider_choice.js (loaded
  // first) and is read at call time; auth_wizards.js reaches it through
  // this export.
  function isPluginChoice(state, platform) {
    return window.MUREO_WIZARD_CHOICE.isPluginChoice(state, platform);
  }

  // The chosen provider's section holds every required field already
  // (/api/status `plugin_platforms`), so its slot is skipped.
  function pluginConfigured(state, platform) {
    const served = state.pluginPlatforms && state.pluginPlatforms[platform];
    return Boolean(served && served.configured);
  }

  function pushGoogleSlots(queue, state) {
    const scPlugin = isPluginChoice(state, "search_console");
    if (isPluginChoice(state, "google_ads")) {
      if (state.platforms.google_ads && !pluginConfigured(state, "google_ads"))
        queue.push({ key: "google_ads", pluginProvider: state.providerChoice.google_ads });
    } else if (state.platforms.google_ads && googleOauthSlotNeeded(state)) {
      // Native AND official Google Ads both need the same Google OAuth
      // client + refresh token (the legacy Developer Token is optional).
      // The official upstream MCP cannot read credentials.json, so we
      // still collect them here and inject them as env into its MCP
      // block at install time. When /api/status reports
      // credentials_oauth.google the saved token already satisfies both,
      // so the slot is skipped — see googleOauthSlotNeeded. A plugin
      // provider's choice replaces this slot with the provider's own.
      queue.push({ key: "google_ads", oauthProvider: "google" });
    }
    if (state.platforms.search_console && scPlugin && !pluginConfigured(state, "search_console"))
      queue.push({ key: "search_console", pluginProvider: state.providerChoice.search_console });
    // SC standalone — own Google OAuth slot, shared only when Google Ads takes it.
    if (
      state.platforms.search_console && !scPlugin &&
      (!state.platforms.google_ads || isPluginChoice(state, "google_ads")) &&
      googleOauthSlotNeeded(state)
    ) {
      queue.push({ key: "search_console", oauthProvider: "google" });
    }
  }

  function buildAuthQueue(state) {
    const queue = [];
    pushGoogleSlots(queue, state);
    if (state.platforms.meta_ads && isPluginChoice(state, "meta_ads")) {
      if (!pluginConfigured(state, "meta_ads"))
        queue.push({ key: "meta_ads", pluginProvider: state.providerChoice.meta_ads });
    } else if (state.platforms.meta_ads && state.providerChoice.meta_ads === "native") {
      queue.push({ key: "meta_ads", oauthProvider: "meta" });
    }
    // NOTE: official Meta (hosted_http) is intentionally NOT queued for
    // OAuth here. Its OAuth is the MCP HTTP-transport handshake performed
    // by Claude itself on first connect (RFC 9728) — configure cannot and
    // must not do it. The provider-choice "next page" (providers_install
    // step) shows the manual setup instructions instead.
    if (state.platforms.ga4 && !ga4CredentialsOnDisk(state)) {
      // Offered under every backend; skipped only when the store already
      // holds the ``ga4`` section (see ga4CredentialsOnDisk). The server
      // writes it to the backend-resolved credentials path like any other
      // env var. Each input carries the credentials.json-backed env var
      // NAME it persists to (POSTed to /api/credentials/env-var on Done)
      // plus a localized label key. GA4-official reads these env vars at
      // launch, so they MUST be saved here — collecting without
      // persisting silently leaves the official MCP unauthenticated.
      queue.push({
        key: "ga4",
        inputs: [
          {
            name: "GOOGLE_APPLICATION_CREDENTIALS",
            labelKey: "wizard.auth.ga4_sa_path",
          },
          {
            name: "GOOGLE_PROJECT_ID",
            labelKey: "wizard.auth.ga4_project_id",
          },
        ],
      });
    }
    if (state.platforms.amazon_ads) {
      // Amazon has no OAuth dance and no separate provider install: mureo
      // brokers Amazon's official MCP itself, reading the ``amazon_ads``
      // credentials section. The slot therefore renders the SAME declarative
      // field list the dashboard's Amazon card uses — fetched from
      // /api/credentials/plugins, which derives it from the bridge's
      // ``account_credential_fields``. Nothing about the fields is copied
      // into this file, so the wizard cannot drift from the loader.
      queue.push({ key: "amazon_ads", pluginProvider: "amazon_ads" });
    }
    return queue;
  }

  window.MUREO_AUTH_QUEUE = {
    buildAuthQueue: buildAuthQueue,
    googleHasOauthOnDisk: googleHasOauthOnDisk,
    ga4CredentialsOnDisk: ga4CredentialsOnDisk,
    isPluginChoice: isPluginChoice,
    pluginConfigured: pluginConfigured,
  };
})();
