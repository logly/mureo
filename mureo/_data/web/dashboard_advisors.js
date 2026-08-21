// dashboard_advisors.js — the federated-advisor list and its add form.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move.
//
// An advisor is another mureo an operator delegates a question to, so the
// form is mostly about transport: the fields swap by transport kind, and the
// two textarea parsers (`parseLines`, `parseKeyValueLines`) turn what an
// operator pasted into what the API expects, tolerating the blank lines and
// stray whitespace a paste always carries.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_ADVISORS`. Must load BEFORE dashboard.js.

(function () {
  "use strict";

  // Parse a textarea of "one entry per line" into a trimmed string array,
  // dropping blank lines. Used for stdio args.
  function parseLines(text) {
    return (text || "")
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .filter(function (line) {
        return line.length > 0;
      });
  }

  // Parse a textarea of "KEY=VALUE" lines into an object. Blank lines and
  // lines without "=" are skipped. The first "=" splits key/value so a
  // value may itself contain "=".
  function parseKeyValueLines(text) {
    const out = {};
    parseLines(text).forEach(function (line) {
      const eq = line.indexOf("=");
      if (eq <= 0) return;
      const key = line.slice(0, eq).trim();
      const value = line.slice(eq + 1).trim();
      if (key) out[key] = value;
    });
    return out;
  }

  function buildAdvisorRemoveButton(name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary";
    btn.textContent = MUREO.t("dashboard.advisors_remove");
    btn.setAttribute("data-i18n", "dashboard.advisors_remove");
    btn.setAttribute("aria-label", MUREO.t("dashboard.advisors_remove"));
    btn.addEventListener("click", async function () {
      const ok = await MUREO.confirmAction(
        MUREO.t("dashboard.advisors_confirm_remove")
      );
      if (!ok) return;
      let res;
      try {
        res = await MUREO.postJson("/api/advisors/remove", { name: name });
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.advisors_remove_failed"), "error");
        return;
      }
      const body = (res && res.body) || {};
      if (res && res.ok && body.status === "ok") {
        renderAdvisorsList(body.advisors);
        MUREO.toast(MUREO.t("dashboard.advisors_removed"), "success");
      } else {
        MUREO.toast(MUREO.t("dashboard.advisors_remove_failed"), "error");
      }
    });
    return btn;
  }

  // Render the advisor rows from a list payload (or [] when absent).
  function renderAdvisorsList(advisors) {
    const list = document.querySelector("[data-dashboard-advisors-list]");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const rows = Array.isArray(advisors) ? advisors : [];
    if (rows.length === 0) {
      const empty = document.createElement("li");
      empty.className = "dashboard-provider-hosted-note";
      empty.textContent = MUREO.t("dashboard.advisors_empty");
      empty.setAttribute("data-i18n", "dashboard.advisors_empty");
      list.appendChild(empty);
      return;
    }
    rows.forEach(function (a) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      // textContent only — an advisor name / target is operator config but
      // must never be interpreted as markup.
      label.textContent =
        (a.name || "") + " — " + (a.transport || "") + " · " + (a.target || "");
      li.appendChild(label);
      li.appendChild(buildAdvisorRemoveButton(a.name || ""));
      list.appendChild(li);
    });
  }

  async function renderAdvisors() {
    const list = document.querySelector("[data-dashboard-advisors-list]");
    if (!list) return;
    let body;
    try {
      const res = await fetch("/api/advisors", { credentials: "same-origin" });
      if (!res.ok) return;
      body = await res.json();
    } catch (_err) {
      // Silent failure — the section is non-critical.
      return;
    }
    renderAdvisorsList(body && body.advisors);
  }

  // Toggle the stdio-only / remote-only field blocks based on transport.
  function syncAdvisorTransportFields(form) {
    const transport = form.querySelector("[data-advisor-transport]");
    const stdio = form.querySelector("[data-advisor-stdio-fields]");
    const remote = form.querySelector("[data-advisor-remote-fields]");
    if (!transport || !stdio || !remote) return;
    const isStdio = transport.value === "stdio";
    stdio.hidden = !isStdio;
    remote.hidden = isStdio;
  }

  // Map a failed /api/advisors/add response to the most specific toast.
  function advisorAddErrorKey(res) {
    const err = res && res.body && res.body.error;
    if (err === "duplicate_name") return "dashboard.advisors_err_duplicate_name";
    if (err === "invalid_advisor") return "dashboard.advisors_err_invalid";
    return "dashboard.advisors_add_failed";
  }

  function wireAdvisorForm() {
    const form = document.querySelector("[data-advisor-form]");
    if (!form) return;
    const transport = form.querySelector("[data-advisor-transport]");
    if (transport) {
      transport.addEventListener("change", function () {
        syncAdvisorTransportFields(form);
      });
    }
    syncAdvisorTransportFields(form);
    form.addEventListener("submit", async function (evt) {
      evt.preventDefault();
      const name = (form.querySelector("[data-advisor-name]").value || "").trim();
      const tool = (form.querySelector("[data-advisor-tool]").value || "").trim();
      if (!name) {
        MUREO.toast(MUREO.t("dashboard.advisors_name_required"), "error");
        return;
      }
      if (!tool) {
        MUREO.toast(MUREO.t("dashboard.advisors_tool_required"), "error");
        return;
      }
      const transportValue = transport ? transport.value : "stdio";
      const payload = { name: name, transport: transportValue, tool: tool };
      if (transportValue === "stdio") {
        payload.command = (
          form.querySelector("[data-advisor-command]").value || ""
        ).trim();
        payload.args = parseLines(form.querySelector("[data-advisor-args]").value);
        const env = parseKeyValueLines(
          form.querySelector("[data-advisor-env]").value
        );
        if (Object.keys(env).length > 0) payload.env = env;
      } else {
        payload.url = (form.querySelector("[data-advisor-url]").value || "").trim();
        const headers = parseKeyValueLines(
          form.querySelector("[data-advisor-headers]").value
        );
        if (Object.keys(headers).length > 0) payload.headers = headers;
      }
      let res;
      try {
        res = await MUREO.postJson("/api/advisors/add", payload);
      } catch (_err) {
        MUREO.toast(MUREO.t("dashboard.advisors_add_failed"), "error");
        return;
      }
      const body = (res && res.body) || {};
      if (res && res.ok && body.status === "ok") {
        form.reset();
        syncAdvisorTransportFields(form);
        renderAdvisorsList(body.advisors);
        MUREO.toast(MUREO.t("dashboard.advisors_added"), "success");
      } else {
        MUREO.toast(MUREO.t(advisorAddErrorKey(res)), "error");
      }
    });
  }
  const api = {
    renderAdvisors: renderAdvisors,
    wireAdvisorForm: wireAdvisorForm,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_ADVISORS = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
