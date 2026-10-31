// connector_url_row.js — the endpoint-plus-copy-button row shared by the
// hosted-MCP cards: Meta's connector setup steps (auth_wizards_meta.js) and
// the TikTok card of the providers-install step (wizard_install_slots.js).
// Loaded before both; they read window.MUREO_CONNECTOR_ROW at call time.

(function () {
  "use strict";

  // Endpoint + copy button — handy for the Desktop custom-connector
  // dialog or to confirm the URL for `claude mcp add`. The button reads
  // "copied" for 1.5 s after a successful clipboard write; when the
  // clipboard is unavailable or refuses, the URL is shown as a toast.
  function buildEndpointCopyRow(url) {
    const urlRow = document.createElement("div");
    urlRow.className = "connector-url-row";
    const code = document.createElement("code");
    code.textContent = url;
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn btn-secondary connector-copy-btn";
    copyBtn.textContent = MUREO.t("connector.copy");
    copyBtn.setAttribute("data-i18n", "connector.copy");
    copyBtn.addEventListener("click", function () {
      const done = function () {
        copyBtn.textContent = MUREO.t("connector.copied");
        setTimeout(function () {
          copyBtn.textContent = MUREO.t("connector.copy");
        }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard
          .writeText(url)
          .then(done, function () {
            MUREO.toast(url);
          });
      } else {
        MUREO.toast(url);
      }
    });
    urlRow.appendChild(code);
    urlRow.appendChild(copyBtn);
    return urlRow;
  }

  window.MUREO_CONNECTOR_ROW = {
    buildEndpointCopyRow: buildEndpointCopyRow,
  };
})();
