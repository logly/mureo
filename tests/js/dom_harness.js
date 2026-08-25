// A DOM small enough to read, real enough to catch a rendering bug.
//
// NOT a test — a helper the interaction tests require. `node --test
// tests/js/*.test.js` does not pick it up.
//
// Why this exists: the client-grid health filter shipped green. Every test
// it had asserted that `applyReportsHealthFilter` set `hidden` on the right
// card items, and it did — but `.reports-client-card-item` declares
// `display: flex`, an AUTHOR rule, which beats the user-agent's
// `[hidden] { display: none }`. Every card stayed on screen. No pin over
// dashboard.js could have seen it, because the JS was right; the failure was
// the two files disagreeing.
//
// So this harness models the one piece of cascade that decides it:
//
//   • the UA sheet's `[hidden] { display: none }`, which any author `display`
//     overrides;
//   • an author `.cls[hidden] { display: none }`, which wins back because it
//     is more specific.
//
// `isVisible()` reads those out of the real app.css. It is deliberately not a
// CSS engine — it knows about `display` and about nothing else — and that is
// the whole of what "did the filter actually hide anything?" turns on.
//
// The rest is the minimum needed to evaluate the real dashboard.js against
// the real app.html: a tag-soup parser, elements with the handful of DOM
// APIs that file uses (the selectors it passes are all `[attr]`,
// `[attr="v"]`, `.class` or a tag name — see the grep in the test), and
// events that bubble.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

// ---------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------

const VOID_TAGS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr",
]);

class TextNode {
  constructor(text) {
    this.nodeType = 3;
    this.data = text;
    this.parentNode = null;
  }
  get textContent() {
    return this.data;
  }
}

class Element {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.attributes = new Map();
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    this._listeners = new Map();
    const el = this;
    this.classList = {
      add(...names) {
        const set = el._classSet();
        names.forEach((n) => n && set.add(n));
        el._writeClasses(set);
      },
      remove(...names) {
        const set = el._classSet();
        names.forEach((n) => set.delete(n));
        el._writeClasses(set);
      },
      contains(name) {
        return el._classSet().has(name);
      },
      toggle(name, force) {
        const on = force === undefined ? !el._classSet().has(name) : !!force;
        if (on) el.classList.add(name);
        else el.classList.remove(name);
        return on;
      },
    };
  }

  _classSet() {
    return new Set(String(this.getAttribute("class") || "").split(/\s+/).filter(Boolean));
  }

  _writeClasses(set) {
    this.setAttribute("class", Array.from(set).join(" "));
  }

  // --- attributes ---
  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }
  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  hasAttribute(name) {
    return this.attributes.has(name);
  }

  // `el.dataset.foo` <-> the `data-foo` attribute, as in a browser.
  get dataset() {
    const el = this;
    return new Proxy(
      {},
      {
        get(_t, key) {
          return el.getAttribute("data-" + dashed(String(key)));
        },
        set(_t, key, value) {
          el.setAttribute("data-" + dashed(String(key)), value);
          return true;
        },
        has(_t, key) {
          return el.hasAttribute("data-" + dashed(String(key)));
        },
      }
    );
  }

  get className() {
    return this.getAttribute("class") || "";
  }
  set className(value) {
    this.setAttribute("class", value);
  }

  // `hidden` is a reflected boolean attribute, exactly as in a browser —
  // which is what makes the CSS question below a real one.
  get hidden() {
    return this.hasAttribute("hidden");
  }
  set hidden(value) {
    if (value) this.setAttribute("hidden", "");
    else this.removeAttribute("hidden");
  }

  get id() {
    return this.getAttribute("id") || "";
  }
  set id(value) {
    this.setAttribute("id", value);
  }
  get title() {
    return this.getAttribute("title") || "";
  }
  set title(value) {
    this.setAttribute("title", value);
  }
  get type() {
    return this.getAttribute("type") || "";
  }
  set type(value) {
    this.setAttribute("type", value);
  }
  get value() {
    return this.getAttribute("value") || "";
  }
  set value(v) {
    this.setAttribute("value", v);
  }

  // --- tree ---
  get children() {
    return this.childNodes.filter((n) => n.nodeType === 1);
  }
  appendChild(node) {
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }
  insertBefore(node, ref) {
    if (!ref) return this.appendChild(node);
    if (node.parentNode) node.parentNode.removeChild(node);
    const at = this.childNodes.indexOf(ref);
    node.parentNode = this;
    this.childNodes.splice(at === -1 ? this.childNodes.length : at, 0, node);
    return node;
  }
  removeChild(node) {
    const at = this.childNodes.indexOf(node);
    if (at !== -1) this.childNodes.splice(at, 1);
    node.parentNode = null;
    return node;
  }
  get firstChild() {
    return this.childNodes[0] || null;
  }
  get nextSibling() {
    if (!this.parentNode) return null;
    const kids = this.parentNode.childNodes;
    return kids[kids.indexOf(this) + 1] || null;
  }

  get textContent() {
    return this.childNodes.map((n) => n.textContent).join("");
  }
  set textContent(text) {
    this.childNodes.forEach((n) => (n.parentNode = null));
    this.childNodes = [];
    if (text !== "" && text != null) this.appendChild(new TextNode(String(text)));
  }

  // --- queries ---
  matches(selector) {
    return matchesSelector(this, selector);
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => {
      node.children.forEach((child) => {
        if (matchesSelector(child, selector)) out.push(child);
        walk(child);
      });
    };
    walk(this);
    return out;
  }

  // --- events ---
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this._listeners.get(type) || [];
    const at = list.indexOf(fn);
    if (at !== -1) list.splice(at, 1);
  }
  dispatchEvent(event) {
    let node = this;
    const evt = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, event);
    while (node) {
      (node._listeners.get(evt.type) || []).slice().forEach((fn) => fn.call(node, evt));
      node = node.parentNode;
    }
    return true;
  }
  click() {
    return this.dispatchEvent({ type: "click" });
  }
  focus() {}
}

/** `fooBar` -> `foo-bar`, the dataset naming rule. */
function dashed(key) {
  return key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}

/** `[attr]`, `[attr="v"]`, `.class`, `tag` — the shapes dashboard.js uses. */
function matchesSelector(el, selector) {
  const s = String(selector).trim();
  let m = /^\[([A-Za-z0-9_-]+)(?:=["']?([^"'\]]*)["']?)?\]$/.exec(s);
  if (m) {
    if (!el.hasAttribute(m[1])) return false;
    return m[2] === undefined || el.getAttribute(m[1]) === m[2];
  }
  m = /^\.([A-Za-z0-9_-]+)$/.exec(s);
  if (m) return el.classList.contains(m[1]);
  m = /^([A-Za-z][A-Za-z0-9]*)$/.exec(s);
  if (m) return el.tagName === m[1].toUpperCase();
  throw new Error("dom_harness: unsupported selector " + s);
}

// ---------------------------------------------------------------------
// The parser
// ---------------------------------------------------------------------

function parseHtml(html) {
  const root = new Element("root");
  const stack = [root];
  let i = 0;
  const source = html.replace(/<!DOCTYPE[^>]*>/i, "");
  while (i < source.length) {
    const lt = source.indexOf("<", i);
    if (lt === -1) break;
    if (lt > i) {
      const text = source.slice(i, lt);
      if (text.trim()) stack[stack.length - 1].appendChild(new TextNode(text));
    }
    if (source.startsWith("<!--", lt)) {
      i = source.indexOf("-->", lt) + 3;
      continue;
    }
    const gt = findTagEnd(source, lt);
    const raw = source.slice(lt + 1, gt).trim();
    i = gt + 1;
    if (raw.startsWith("/")) {
      const name = raw.slice(1).trim().toLowerCase();
      for (let d = stack.length - 1; d > 0; d--) {
        if (stack[d].tagName === name.toUpperCase()) {
          stack.length = d;
          break;
        }
      }
      continue;
    }
    const selfClosing = raw.endsWith("/");
    const body = selfClosing ? raw.slice(0, -1) : raw;
    const name = (/^[A-Za-z0-9]+/.exec(body) || ["div"])[0].toLowerCase();
    const el = new Element(name);
    parseAttributes(body.slice(name.length), el);
    stack[stack.length - 1].appendChild(el);
    if (!selfClosing && !VOID_TAGS.has(name)) stack.push(el);
  }
  return root;
}

/** The `>` that closes this tag, skipping any inside a quoted value. */
function findTagEnd(source, from) {
  let quote = null;
  for (let i = from + 1; i < source.length; i++) {
    const c = source[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (c === ">") {
      return i;
    }
  }
  return source.length;
}

function parseAttributes(text, el) {
  const re = /([A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let m;
  while ((m = re.exec(text))) {
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4];
    el.setAttribute(m[1], value === undefined ? "" : value);
  }
}

// ---------------------------------------------------------------------
// The one piece of CSS that decides whether a render is visible
// ---------------------------------------------------------------------

const CSS = fs
  .readFileSync(path.join(WEB, "app.css"), "utf-8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

/** class -> the `display` its own rule declares (or undefined). */
const DISPLAY_BY_CLASS = new Map();
/** class -> the `display` its `[hidden]` rule declares (or undefined). */
const HIDDEN_DISPLAY_BY_CLASS = new Map();

for (const [, selectors, body] of CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const m = /(?:^|;)\s*display\s*:\s*([^;]+)/.exec(body);
  if (!m) continue;
  const display = m[1].trim();
  selectors.split(",").forEach((raw) => {
    const sel = raw.trim();
    let hit = /^\.([A-Za-z0-9_-]+)$/.exec(sel);
    if (hit) {
      DISPLAY_BY_CLASS.set(hit[1], display);
      return;
    }
    hit = /^\.([A-Za-z0-9_-]+)\[hidden\]$/.exec(sel);
    if (hit) HIDDEN_DISPLAY_BY_CLASS.set(hit[1], display);
  });
}

/**
 * The `display` this element computes to, by the rules that matter here.
 *
 *   hidden + an author `.cls[hidden]` rule  -> that rule (i.e. `none`)
 *   hidden + an author `.cls { display: X }` -> X. The author sheet beats
 *       the UA sheet's `[hidden] { display: none }`, so the element is
 *       STILL ON SCREEN. This is the bug the harness exists to catch.
 *   hidden + no author display              -> none (the UA rule applies)
 *   not hidden                              -> whatever the author says
 */
function computedDisplay(el) {
  const classes = Array.from(el._classSet());
  if (el.hidden) {
    for (const c of classes) {
      if (HIDDEN_DISPLAY_BY_CLASS.has(c)) return HIDDEN_DISPLAY_BY_CLASS.get(c);
    }
    for (const c of classes) {
      const d = DISPLAY_BY_CLASS.get(c);
      if (d && d !== "none") return d;
    }
    return "none";
  }
  for (const c of classes) {
    if (DISPLAY_BY_CLASS.get(c) === "none") return "none";
  }
  return "block";
}

// ---------------------------------------------------------------------
// A real cascade, for the properties a layout depends on
// ---------------------------------------------------------------------

/**
 * Every rule in app.css, as `{ selector, declarations, order }`.
 *
 * `DISPLAY_BY_CLASS` above only understands a bare `.cls` selector, which is
 * enough for "is this hidden" and is NOT enough for anything else: it cannot
 * see `.dashboard-section li`, so it cannot see that a two-part selector
 * OUTRANKS a one-class rule and takes the property away from it.
 *
 * That is not hypothetical. `.report-action` (0,1,0) declared
 * `flex-direction: column`, and `.dashboard-section li` (0,1,1) supplied
 * `align-items: center` — which on a column centres every child. The rendered
 * screen was centred text; the stylesheet contained no `text-align: center`
 * anywhere near it; and a test asserting "no rule declares centring" passed
 * happily while the bug was on screen.
 */
const RULES = [];
{
  let order = 0;
  for (const [, selectors, body] of CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    // Skip at-rule preambles (@media ... {) — the harness models one theme.
    if (/@/.test(selectors)) continue;
    const declarations = {};
    for (const part of body.split(";")) {
      const i = part.indexOf(":");
      if (i === -1) continue;
      declarations[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
    for (const raw of selectors.split(",")) {
      RULES.push({ selector: raw.trim(), declarations, order: order++ });
    }
  }
}

/** (ids, classes/attrs/pseudo-classes, types) — CSS specificity. */
function specificity(selector) {
  const bare = selector.replace(/::[a-z-]+/g, "");
  const ids = (bare.match(/#[\w-]+/g) || []).length;
  const classes = (bare.match(/\.[\w-]+|\[[^\]]+\]|:[a-z-]+(\([^)]*\))?/g) || [])
    .length;
  const types = (bare.match(/(^|[\s>+~])[a-z]+[\w-]*/gi) || []).length;
  return ids * 10000 + classes * 100 + types;
}

/** Does one compound (`li.report-action:last-child`) match this element? */
function matchesCompound(el, compound) {
  const classes = el._classSet ? el._classSet() : new Set();
  const parts = compound.match(/[.#\[:]?[^.#\[:]+/g) || [];
  for (const part of parts) {
    if (part.startsWith(".")) {
      if (!classes.has(part.slice(1))) return false;
    } else if (part.startsWith("[")) {
      const name = part.slice(1, -1).split("=")[0].trim();
      if (el.getAttribute(name) === null) return false;
    } else if (part.startsWith(":")) {
      // Structural pseudo-classes are not modelled; treat as matching so a
      // rule is never wrongly discarded (this errs toward reporting MORE
      // competing rules, which is the safe direction for a guard).
      continue;
    } else if (part.startsWith("#")) {
      return false;
    } else if (!/^[a-z]+$/i.test(part)) {
      return false;
    } else if (el.tagName !== part.toUpperCase()) {
      return false;
    }
  }
  return true;
}

/**
 * Does `selector` match `el`? Descendant and child combinators.
 *
 * Sibling combinators are still skipped, and that skip is a KNOWN
 * UNSOUNDNESS rather than caution: a rule this function refuses to match is
 * dropped from the cascade entirely, so `cascade()` can hand back a rule that
 * the browser would have overruled. Child combinators were in that hole until
 * #697 — `.reports-client-card-item.is-triaged > .reports-client-card` is the
 * rule that colours a client's card, and no cascade assertion could see it.
 */
function selectorMatches(el, selector) {
  if (/[+~]/.test(selector)) return false; // not modelled; skip rather than guess
  const compounds = selector
    .replace(/::[a-z-]+/g, "")
    .trim()
    .split(/\s*(>)\s*|\s+/)
    .filter(Boolean);
  if (!matchesCompound(el, compounds[compounds.length - 1])) return false;
  let node = el.parentNode;
  for (let i = compounds.length - 2; i >= 0; i--) {
    // A ">" is not a compound of its own: it tightens the step that follows
    // it (reading right to left, the one already consumed) to the immediate
    // parent, so the ancestor walk below may not skip past a non-match.
    if (compounds[i] === ">") continue;
    const strict = compounds[i + 1] === ">";
    let found = false;
    while (node && node.nodeType === 1) {
      if (matchesCompound(node, compounds[i])) {
        found = true;
        node = node.parentNode;
        break;
      }
      if (strict) return false;
      node = node.parentNode;
    }
    if (!found) return false;
  }
  return true;
}

/**
 * What `property` computes to on `el`, by specificity then source order.
 *
 * Returns `{ value, selector }` so a failure can name the rule that won —
 * which is the whole difficulty when one is losing a cascade it did not know
 * it was in. `undefined` when nothing declares it.
 */
function cascade(el, property) {
  let best = null;
  for (const rule of RULES) {
    const value = rule.declarations[property];
    if (value === undefined) continue;
    if (/::/.test(rule.selector)) continue; // pseudo-elements are not this element
    if (!selectorMatches(el, rule.selector)) continue;
    const rank = specificity(rule.selector);
    if (!best || rank > best.rank || (rank === best.rank && rule.order > best.order)) {
      best = { rank, order: rule.order, value, selector: rule.selector };
    }
  }
  return best ? { value: best.value, selector: best.selector } : undefined;
}

/** Would an operator see this element, given app.css? */
function isVisible(el) {
  let node = el;
  while (node && node.nodeType === 1 && node.tagName !== "ROOT") {
    if (computedDisplay(node) === "none") return false;
    node = node.parentNode;
  }
  return true;
}

// ---------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------

/**
 * Evaluate the real reports modules + dashboard.js against the real
 * app.html, in a context shaped like a browser.
 *
 * `routes` maps a URL prefix to the JSON its endpoint answers with;
 * anything unlisted answers `{}`, because most of what renderAll() asks
 * for is not what an interaction test is about.
 */
function loadDashboardPage(routes) {
  const html = fs.readFileSync(path.join(WEB, "app.html"), "utf-8");
  const root = parseHtml(html);
  const body = root.querySelector("body") || root;

  const document = {
    documentElement: root,
    body: body,
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => new TextNode(text),
    querySelector: (s) => root.querySelector(s),
    querySelectorAll: (s) => root.querySelectorAll(s),
    addEventListener: (t, f) => root.addEventListener(t, f),
    dispatchEvent: (e) => root.dispatchEvent(e),
  };

  const requests = [];
  function respond(url) {
    requests.push(url);
    const key = Object.keys(routes || {}).find((prefix) => url.startsWith(prefix));
    const payload = key ? routes[key] : {};
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(typeof payload === "function" ? payload(url) : payload),
    });
  }

  const store = new Map();
  const sandbox = {
    document: document,
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    fetch: (url) => respond(String(url)),
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    // MUREO.t returns the key it was handed, with any interpolated params
    // appended — so an assertion is about WHICH string was chosen and what
    // was put in it, never about English wording.
    MUREO: {
      t: (key, params) => {
        const entries = Object.entries(params || {});
        return entries.length
          ? key + "|" + entries.map(([k, v]) => k + "=" + v).join(",")
          : key;
      },
      state: { status: {} },
      isDashboardRoute: () => true,
      loadStatus: () => Promise.resolve({}),
      postJson: () => Promise.resolve({ ok: true, body: {} }),
      toast: () => {},
      confirmAction: () => Promise.resolve(true),
      navigateToWizard: () => {},
      extensions: { init: () => {} },
    },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  const context = vm.createContext(sandbox);

  for (const file of [
    "reports_logic.js",
    "reports_format.js",
    "reports_order.js",
    "reports_triage.js",
    "reports_overview.js",
    "dashboard_setup.js",
    "dashboard_workspace.js",
    "dashboard_about.js",
    "dashboard_advisors.js",
    "dashboard_reports_state.js",
    "dashboard_reports_report.js",
    "dashboard_reports_overview.js",
    "dashboard_reports_cards.js",
    "dashboard_reports_triage.js",
    "dashboard_reports.js",
    "dashboard_creative.js",
    "dashboard_plugins.js",
    "dashboard.js",
  ]) {
    new vm.Script(fs.readFileSync(path.join(WEB, file), "utf-8"), {
      filename: file,
    }).runInContext(context);
  }

  return { root, document, sandbox, requests, localStore: store };
}

/** Let every queued promise and timer callback run. */
async function settle(ticks = 12) {
  for (let i = 0; i < ticks; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

module.exports = {
  cascade,
  specificity,
  Element,
  TextNode,
  parseHtml,
  computedDisplay,
  isVisible,
  loadDashboardPage,
  settle,
  DISPLAY_BY_CLASS,
  HIDDEN_DISPLAY_BY_CLASS,
};
