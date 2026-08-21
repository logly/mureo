// dashboard_creative.js — the Creative Studio run gallery.
//
// Lifted verbatim out of dashboard.js (#678). Nothing here changed in the
// move.
//
// Renders the image runs Creative Studio has produced for the selected
// client. `creativeRenderSeq` is the same monotonic-generation guard the
// plugin credentials card uses (#223): the render is async, renderAll() runs
// it twice during init, and without the guard both calls append.
//
// Every id that rides in an image URL — client, run, file — is
// `encodeURIComponent`-ed, so a hostile-looking name cannot break out of the
// query component.
//
// Shipping shape: a plain `<script>`-loaded file publishing ONE global,
// `window.MUREO_DASHBOARD_CREATIVE`. Must load BEFORE dashboard.js.

(function () {
  "use strict";

  // ------------------------------------------------------------------
  // Creative Studio gallery (#409): read-only browse of generated runs.
  // Clients come from the same picker source as Reports; runs and images
  // are fetched per selected client. Monotonic seq guard mirrors #223 so
  // interleaved renders can never double-append.
  // ------------------------------------------------------------------
  let creativeClient = null;
  let creativeRenderSeq = 0;

  function creativeImageUrl(client, runId, file) {
    return (
      "/api/creative/image?client=" +
      encodeURIComponent(client || "") +
      "&run=" +
      encodeURIComponent(runId) +
      "&file=" +
      encodeURIComponent(file)
    );
  }

  function buildCreativeRunCard(run) {
    const card = document.createElement("div");
    card.className = "creative-run-card";
    const head = document.createElement("div");
    head.className = "creative-run-head";
    const title = document.createElement("strong");
    title.textContent = run.run_id;
    head.appendChild(title);
    const meta = document.createElement("span");
    meta.className = "muted";
    const parts = [];
    if (run.created_at) parts.push(run.created_at);
    if (run.provider) parts.push(run.provider);
    if (run.template) parts.push(run.template);
    meta.textContent = parts.join(" · ");
    head.appendChild(meta);
    card.appendChild(head);
    if (run.prompt) {
      const prompt = document.createElement("p");
      prompt.className = "muted creative-run-prompt";
      prompt.textContent = run.prompt;
      card.appendChild(prompt);
    }
    const grid = document.createElement("div");
    grid.className = "creative-run-grid";
    (run.images || []).forEach(function (file) {
      const url = creativeImageUrl(creativeClient, run.run_id, file);
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      const img = document.createElement("img");
      img.className = "creative-thumb";
      img.loading = "lazy";
      img.src = url;
      img.alt = file;
      link.appendChild(img);
      grid.appendChild(link);
    });
    card.appendChild(grid);
    return card;
  }

  async function renderCreativeGallery() {
    const runsBox = document.querySelector("[data-creative-runs]");
    const clientsBox = document.querySelector("[data-creative-clients]");
    const emptyBox = document.querySelector("[data-creative-empty]");
    if (!runsBox) return;
    const seq = ++creativeRenderSeq;

    let clients = [];
    try {
      const res = await fetch("/api/creative/clients");
      const body = await res.json();
      clients = Array.isArray(body.clients) ? body.clients : [];
    } catch (_e) {
      clients = [];
    }
    if (seq !== creativeRenderSeq) return;
    const known = clients.some(function (c) {
      return c.slug === creativeClient;
    });
    if (!known) creativeClient = null;
    if (!creativeClient && clients.length) {
      const active = clients.find(function (c) {
        return c.active;
      });
      creativeClient = (active || clients[0]).slug;
    }
    if (clientsBox) {
      clientsBox.textContent = "";
      clientsBox.hidden = clients.length < 2;
      clients.forEach(function (c) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className =
          "btn btn-secondary creative-client-btn" +
          (c.slug === creativeClient ? " is-selected" : "");
        btn.textContent = c.name || c.slug;
        btn.addEventListener("click", function () {
          creativeClient = c.slug;
          renderCreativeGallery();
        });
        clientsBox.appendChild(btn);
      });
    }

    let runs = [];
    try {
      const res = await fetch(
        "/api/creative/runs?client=" + encodeURIComponent(creativeClient || "")
      );
      const body = await res.json();
      runs = Array.isArray(body.runs) ? body.runs : [];
    } catch (_e) {
      runs = [];
    }
    if (seq !== creativeRenderSeq) return;
    runsBox.textContent = "";
    if (emptyBox) emptyBox.hidden = runs.length !== 0;
    runs.forEach(function (run) {
      runsBox.appendChild(buildCreativeRunCard(run));
    });
  }

  const api = {
    renderCreativeGallery: renderCreativeGallery,
  };

  // Browser: the global the `<script>` tag exists to publish.
  if (typeof window !== "undefined") window.MUREO_DASHBOARD_CREATIVE = api;
  // Node (test runner only): `module` does not exist in a browser, so this
  // branch is dead code there and adds no runtime module system.
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})();
