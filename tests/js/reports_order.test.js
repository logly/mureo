// Behavioural tests for mureo/_data/web/reports_order.js (#556).
//
// Run with:  node --test tests/js/
//
// These EXECUTE the shipped bytes — `require` loads the same file the
// browser gets over /static/reports_order.js, no build step and no copy.
//
// Until #556 the ordering rules were guarded only by the substring pins in
// tests/test_web_assets_reports_order_and_archive.py, whose own docstring
// says it "cannot prove that a drag actually reorders the grid, that a
// corrupt stored order really degrades to the server order". It can now:
// the module never goes LOOKING for a node — every node is handed in — so a
// fake grid of ~20 lines drives the real code.
//
// What is being pinned:
//
//   • an unusable stored order (storage off, corrupt JSON, wrong type, junk
//     members) degrades to the SERVER's order, never to an empty grid;
//   • a client the operator has never placed lands LAST, keeping its server
//     order — it must not displace the top of a curated grid on every
//     onboarding;
//   • the DOM is the single source of truth for what gets persisted, so the
//     keyboard path and the drop handler cannot disagree;
//   • a move off either end of the grid is a no-op, not a wrap-around and
//     not an exception that leaves the arrow key dead.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const WEB = path.join(__dirname, "..", "..", "mureo", "_data", "web");

const KEY = "mureo.reports.client_order";

/** A localStorage that can be corrupt, or disabled the way Safari's is. */
const storage = { items: {}, disabled: false };

// Assigned BEFORE the require: in a browser `window` is the global, and the
// module reads window.localStorage at CALL time.
globalThis.window = {
  localStorage: {
    getItem: function (key) {
      if (storage.disabled) throw new Error("storage is disabled");
      return Object.prototype.hasOwnProperty.call(storage.items, key)
        ? storage.items[key]
        : null;
    },
    setItem: function (key, value) {
      if (storage.disabled) throw new Error("storage is disabled");
      storage.items[key] = value;
    },
  },
};

const order = require(path.join(WEB, "reports_order.js"));

test.beforeEach(function () {
  storage.items = {};
  storage.disabled = false;
});

/** The stored slugs, parsed — i.e. what a later page load would read back. */
function stored() {
  return storage.items[KEY] === undefined ? undefined : JSON.parse(storage.items[KEY]);
}

/**
 * A stand-in for the client grid: an element with `children`, whose members
 * carry `data-client` and a live `nextSibling`, and a DOM-shaped
 * `insertBefore` (a null reference appends, and re-inserting a node that is
 * already a child moves it).
 */
function grid(slugs) {
  const wrap = {
    children: [],
    insertBefore: function (node, ref) {
      const at = wrap.children.indexOf(node);
      if (at !== -1) wrap.children.splice(at, 1);
      const to = ref === null ? -1 : wrap.children.indexOf(ref);
      if (to === -1) wrap.children.push(node);
      else wrap.children.splice(to, 0, node);
      return node;
    },
  };
  slugs.forEach(function (slug) {
    const node = {
      parentNode: wrap,
      getAttribute: function (name) {
        return name === "data-client" ? slug : null;
      },
    };
    Object.defineProperty(node, "nextSibling", {
      get: function () {
        const i = wrap.children.indexOf(node);
        return i >= 0 && i + 1 < wrap.children.length ? wrap.children[i + 1] : null;
      },
    });
    wrap.children.push(node);
  });
  return wrap;
}

/** The slugs currently on screen, in grid order. */
function slugsOf(wrap) {
  return wrap.children.map(function (n) {
    return n.getAttribute("data-client");
  });
}

const client = function (slug) {
  return { slug: slug, name: slug };
};

// ---------------------------------------------------------------------------
// Reading the stored order
// ---------------------------------------------------------------------------

test.describe("readReportsOrder", function () {
  test.it("returns what was stored", function () {
    storage.items[KEY] = JSON.stringify(["b", "a"]);
    assert.deepEqual(order.readReportsOrder(), ["b", "a"]);
  });

  test.it("is empty when nothing was ever stored", function () {
    assert.deepEqual(order.readReportsOrder(), []);
  });

  test.it("degrades to empty — never throws — on anything unusable", function () {
    // Every one of these reaches the grid as "use the server's order".
    for (const raw of ["{not json", '"a string"', "42", "null", '{"a":1}']) {
      storage.items[KEY] = raw;
      assert.deepEqual(order.readReportsOrder(), [], raw);
    }
  });

  test.it("drops junk members rather than the whole order", function () {
    storage.items[KEY] = JSON.stringify(["a", 7, null, "", "b", { slug: "c" }]);
    assert.deepEqual(order.readReportsOrder(), ["a", "b"]);
  });

  test.it("survives storage being disabled outright", function () {
    storage.disabled = true;
    assert.deepEqual(order.readReportsOrder(), []);
  });
});

test.describe("writeReportsOrder", function () {
  test.it("persists under the documented key", function () {
    order.writeReportsOrder(["a", "b"]);
    assert.equal(order.REPORTS_ORDER_KEY, KEY);
    assert.deepEqual(stored(), ["a", "b"]);
  });

  test.it("swallows a disabled storage so the render still completes", function () {
    storage.disabled = true;
    assert.doesNotThrow(function () {
      order.writeReportsOrder(["a"]);
    });
  });
});

// ---------------------------------------------------------------------------
// Applying it to the server's rows
// ---------------------------------------------------------------------------

test.describe("orderReportsClients", function () {
  test.it("applies the operator's order to the server's rows", function () {
    storage.items[KEY] = JSON.stringify(["c", "a", "b"]);
    const rows = [client("a"), client("b"), client("c")];
    assert.deepEqual(
      order.orderReportsClients(rows).map(function (c) {
        return c.slug;
      }),
      ["c", "a", "b"]
    );
  });

  test.it("appends a never-placed client LAST, in server order", function () {
    // Last, not first: a curated grid must not be displaced at the top on
    // every onboarding. The position is defined and findable, and one drag
    // fixes it.
    storage.items[KEY] = JSON.stringify(["c", "a"]);
    const rows = [client("a"), client("new1"), client("c"), client("new2")];
    assert.deepEqual(
      order.orderReportsClients(rows).map(function (c) {
        return c.slug;
      }),
      ["c", "a", "new1", "new2"]
    );
  });

  test.it("costs nothing for a stored client that no longer exists", function () {
    storage.items[KEY] = JSON.stringify(["gone", "b", "also_gone", "a"]);
    const rows = [client("a"), client("b")];
    assert.deepEqual(
      order.orderReportsClients(rows).map(function (c) {
        return c.slug;
      }),
      ["b", "a"]
    );
  });

  test.it("keeps the server order when there is nothing stored", function () {
    const rows = [client("a"), client("b"), client("c")];
    assert.deepEqual(order.orderReportsClients(rows), rows);
  });

  test.it("keeps the server order when storage is unusable", function () {
    // The failure that must NOT happen: an empty grid.
    storage.disabled = true;
    const rows = [client("a"), client("b")];
    assert.deepEqual(
      order.orderReportsClients(rows).map(function (c) {
        return c.slug;
      }),
      ["a", "b"]
    );
  });

  test.it("does not mutate the array it was handed", function () {
    storage.items[KEY] = JSON.stringify(["b", "a"]);
    const rows = [client("a"), client("b")];
    order.orderReportsClients(rows);
    assert.deepEqual(
      rows.map(function (c) {
        return c.slug;
      }),
      ["a", "b"]
    );
  });

  test.it("tolerates a row with no slug", function () {
    storage.items[KEY] = JSON.stringify(["b"]);
    const rows = [client("a"), null, client("b")];
    const out = order.orderReportsClients(rows);
    assert.equal(out.length, 3);
    assert.equal(out[0].slug, "b");
  });
});

// ---------------------------------------------------------------------------
// The two ways the order changes
// ---------------------------------------------------------------------------

test.describe("persistReportsOrderFromDom", function () {
  test.it("records the grid itself, not a shadow list", function () {
    const wrap = grid(["a", "b", "c"]);
    order.persistReportsOrderFromDom(wrap);
    assert.deepEqual(stored(), ["a", "b", "c"]);
  });

  test.it("records only cards that name a client", function () {
    // An archived client leaves the stored order and comes back as an
    // unplaced (last) card when it is restored.
    const wrap = grid(["a", "b"]);
    wrap.children.splice(1, 0, { getAttribute: function () { return null; } });
    order.persistReportsOrderFromDom(wrap);
    assert.deepEqual(stored(), ["a", "b"]);
  });
});

test.describe("moveReportsCard", function () {
  test.it("moves a card down one slot and persists the result", function () {
    const wrap = grid(["a", "b", "c"]);
    order.moveReportsCard(wrap.children[0], 1);
    assert.deepEqual(slugsOf(wrap), ["b", "a", "c"]);
    assert.deepEqual(stored(), ["b", "a", "c"]);
  });

  test.it("moves a card up one slot", function () {
    const wrap = grid(["a", "b", "c"]);
    order.moveReportsCard(wrap.children[2], -1);
    assert.deepEqual(slugsOf(wrap), ["a", "c", "b"]);
    assert.deepEqual(stored(), ["a", "c", "b"]);
  });

  test.it("moves to either end without wrapping around", function () {
    const wrap = grid(["a", "b", "c"]);
    order.moveReportsCard(wrap.children[2], -2);
    assert.deepEqual(slugsOf(wrap), ["c", "a", "b"]);
    order.moveReportsCard(wrap.children[0], 2);
    assert.deepEqual(slugsOf(wrap), ["a", "b", "c"]);
  });

  test.it("is a no-op off either end — and persists nothing", function () {
    // Holding the arrow key at the top of the grid must not wrap the card
    // round to the bottom, and must not rewrite the stored order either.
    const wrap = grid(["a", "b"]);
    order.moveReportsCard(wrap.children[0], -1);
    assert.deepEqual(slugsOf(wrap), ["a", "b"]);
    order.moveReportsCard(wrap.children[1], 1);
    assert.deepEqual(slugsOf(wrap), ["a", "b"]);
    assert.equal(stored(), undefined, "an out-of-range move still wrote");
  });

  test.it("is a no-op for a card that is not in a grid", function () {
    assert.doesNotThrow(function () {
      order.moveReportsCard({ parentNode: null }, 1);
    });
    assert.equal(stored(), undefined);
  });

  test.it("keeps the grid and the stored order in step over many moves", function () {
    const wrap = grid(["a", "b", "c", "d"]);
    order.moveReportsCard(wrap.children[3], -1);
    order.moveReportsCard(wrap.children[0], 1);
    order.moveReportsCard(wrap.children[3], -3);
    assert.deepEqual(stored(), slugsOf(wrap));
    assert.deepEqual(slugsOf(wrap), ["c", "b", "a", "d"]);
  });
});
