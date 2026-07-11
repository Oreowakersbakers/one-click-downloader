const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");

function source(name) {
  return fs.readFileSync(path.join(ROOT, "extension", name), "utf8");
}

function flushTasks() {
  return new Promise((resolve) => setImmediate(resolve));
}

function makeNode() {
  const node = {
    children: [],
    className: "",
    disabled: false,
    listeners: {},
    style: {},
    title: "",
    value: "",
    addEventListener(type, listener) {
      this.listeners[type] = listener;
    },
    append(...children) {
      this.children.push(...children);
    },
  };
  let text = "";
  Object.defineProperty(node, "textContent", {
    get: () => text,
    set(value) {
      text = value;
      if (value === "") node.children = [];
    },
  });
  return node;
}

test("content script rejects synthetic clicks and exposes real buttons", async () => {
  const attributes = {};
  const calls = [];
  const button = makeNode();
  button.classList = { add() {}, contains() { return false; }, remove() {} };
  button.contains = () => false;
  button.isConnected = false;
  button.setAttribute = (name, value) => { attributes[name] = value; };

  const context = {
    URL,
    addEventListener() {},
    chrome: { runtime: { sendMessage: async (message) => calls.push(message) } },
    document: {
      activeElement: null,
      addEventListener() {},
      body: { appendChild() { button.isConnected = true; } },
      createElement: () => button,
      elementsFromPoint: () => [],
    },
    innerHeight: 800,
    innerWidth: 1200,
    location: { href: "https://example.com/video", hostname: "example.com" },
    requestAnimationFrame: () => 1,
    setTimeout() {},
  };

  vm.runInNewContext(source("content.js"), context);

  assert.equal(attributes.role, "group");
  assert.equal(button.tabIndex, 0);
  assert.doesNotMatch(button.innerHTML, /ocdl-choices[^>]+aria-hidden/);

  await button.listeners.click({
    isTrusted: false,
    preventDefault() {},
    stopPropagation() {},
    target: { closest: () => ({ dataset: { fmt: "video" } }) },
  });
  assert.deepEqual(calls, []);
  assert.match(source("content.css"), /:focus-within/);
  assert.match(source("content.js"), /addEventListener\("focusin"/);
});

test("options connection test uses an authenticated request", async () => {
  const elements = Object.fromEntries(
    ["token", "port", "status", "save", "test"].map((id) => [id, makeNode()]),
  );
  const messages = [];
  const saved = [];
  const context = {
    chrome: {
      runtime: {
        sendMessage: async (message) => {
          messages.push(message);
          return { ok: false, error: "bad or missing token" };
        },
      },
      storage: {
        // Nothing in local yet: the page must fall back to values an older
        // version saved in sync, and save into local (never back into sync,
        // which would leak this machine's token to other Chrome profiles).
        local: {
          get: async () => ({}),
          set: async (values) => saved.push(values),
        },
        sync: {
          get: async () => ({ token: "wrong-token", port: 53117 }),
        },
      },
    },
    document: { getElementById: (id) => elements[id] },
  };

  vm.runInNewContext(source("options.js"), context);
  await flushTasks();
  assert.equal(elements.token.value, "wrong-token"); // migrated from sync
  await elements.test.listeners.click();

  // Objects created inside vm have a different prototype, so compare the
  // observable message fields rather than cross-realm object identity.
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, "status");
  assert.equal(elements.status.className, "err");
  assert.equal(elements.status.textContent, "bad or missing token");
  assert.equal(saved.length, 1);
  assert.deepEqual({ ...saved[0] }, { token: "wrong-token", port: 53117 });
});

test("options rejects an out-of-range port without saving", async () => {
  const elements = Object.fromEntries(
    ["token", "port", "status", "save", "test"].map((id) => [id, makeNode()]),
  );
  const saved = [];
  const context = {
    chrome: {
      runtime: { sendMessage: async () => ({ ok: true }) },
      storage: {
        local: {
          get: async () => ({ token: "tok", port: 53117 }),
          set: async (values) => saved.push(values),
        },
        sync: { get: async () => ({}) },
      },
    },
    document: { getElementById: (id) => elements[id] },
  };

  vm.runInNewContext(source("options.js"), context);
  await flushTasks();

  elements.port.value = "99999";
  await elements.save.listeners.click();
  assert.deepEqual(saved, []);
  assert.equal(elements.status.className, "err");
  assert.match(elements.status.textContent, /1 and 65535/);
});

test("failed cancellation is retryable after status refresh", async () => {
  const ids = [
    "dot", "statusText", "url", "msg", "go", "openOptions",
    "downloads", "jobs",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, makeNode()]));
  const job = {
    id: 7,
    percent: 25,
    status: "running",
    title: "Example",
    url: "https://example.com/video",
  };
  const context = {
    URL,
    chrome: {
      runtime: {
        openOptionsPage() {},
        sendMessage: async (message) => {
          if (message.type === "ping") return { ok: true };
          if (message.type === "status") return { ok: true, jobs: [job] };
          if (message.type === "cancel") return { ok: false, error: "temporary" };
          throw new Error(`unexpected message: ${message.type}`);
        },
      },
    },
    document: {
      createElement: makeNode,
      getElementById: (id) => elements[id],
    },
    setInterval() {},
  };

  vm.runInNewContext(source("popup.js"), context);
  await flushTasks();

  const firstCancel = elements.jobs.children[0].children[0].children[1];
  assert.equal(firstCancel.textContent, "Cancel");
  await firstCancel.listeners.click();
  await flushTasks();

  const retryCancel = elements.jobs.children[0].children[0].children[1];
  assert.equal(retryCancel.textContent, "Cancel");
  assert.equal(retryCancel.disabled, false);
});
