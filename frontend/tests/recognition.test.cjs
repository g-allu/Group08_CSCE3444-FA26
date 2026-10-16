// Exercise the frontend with fake camera/network/DOM adapters; no camera required.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../script.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));
const recognized = letter => ({ status: "recognized", letter, confidence: 0.9 });
const response = (body, status = 200) => ({ ok: status < 400, json: async () => body });

function setup({ getUserMedia, predict } = {}) {
  const elements = new Map();
  const events = {};
  const timers = new Map();
  const requests = [];
  let timerId = 0;
  let now = 0;
  let nextResult = recognized("A");
  let stopCount = 0;
  const track = { onended: null, stop() { stopCount += 1; } };
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const canvas = {
    getContext: () => ({ drawImage() {} }),
    toBlob: callback => callback(new Blob(["frame"], { type: "image/jpeg" }))
  };
  const document = {
    getElementById(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          textContent: "", disabled: false, style: {}, handlers: {},
          addEventListener(event, callback) { this.handlers[event] = callback; },
          async click() { if (!this.disabled) { await this.handlers.click(); await flush(); } }
        });
      }
      return elements.get(id);
    },
    createElement: () => canvas
  };
  Object.assign(document.getElementById("camera"), {
    videoWidth: 1280, videoHeight: 720, readyState: 2, play: async () => {}
  });
  vm.runInNewContext(source, {
    document, navigator: { mediaDevices: { getUserMedia: getUserMedia || (async () => stream) } },
    window: { addEventListener: (event, callback) => { events[event] = callback; } },
    performance: { now: () => now }, Blob, FormData, AbortController, console,
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, due: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    async fetch(url, options) {
      if (url === "/api/health") { return response({ ready: true }); }
      requests.push(options);
      return predict ? predict(options, requests.length) : response(nextResult);
    }
  });
  return {
    element: id => document.getElementById(id), events, requests, stream,
    stopped: () => stopCount,
    setResult: value => { nextResult = value; },
    async advance() {
      await flush();
      const [id, timer] = [...timers.entries()].sort((a, b) => a[1].due - b[1].due)[0] || [];
      assert.ok(timer, "Expected scheduled work");
      timers.delete(id);
      now = timer.due;
      await timer.callback();
      await flush();
    },
    timers
  };
}

test("stable letters, repeated Add Letter, and Clear Transcript while recognition continues", async () => {
  const ui = setup();
  await ui.element("startCamera").click();
  assert.equal(ui.element("addLetter").disabled, true);
  await ui.advance();
  assert.equal(ui.element("detectedLetter").textContent, "A");
  assert.equal(ui.element("addLetter").disabled, false);
  await ui.element("addLetter").click();
  await ui.element("addLetter").click();
  assert.equal(ui.element("transcript").textContent, "AA");
  await ui.element("clearText").click();
  assert.equal(ui.element("transcript").textContent, "No translation yet");
  assert.equal(ui.element("clearText").disabled, true);
  assert.equal(ui.element("stopCamera").disabled, false);
  ui.events.pagehide();
  assert.equal(ui.stopped(), 1);
  assert.equal(ui.timers.size, 0);
});

test("uncertainty and changed letters immediately disable Add Letter", async () => {
  const ui = setup();
  await ui.element("startCamera").click();
  await ui.advance();
  ui.setResult({ status: "no_hand", letter: null, confidence: null });
  await ui.advance();
  assert.equal(ui.element("addLetter").disabled, true);
  assert.match(ui.element("recognitionStatus").textContent, /one hand/);
  ui.setResult(recognized("B"));
  await ui.advance();
  assert.equal(ui.element("addLetter").disabled, true);
  await ui.advance();
  assert.equal(ui.element("detectedLetter").textContent, "B");
  ui.setResult(recognized("C"));
  await ui.advance();
  assert.equal(ui.element("addLetter").disabled, true);
  ui.events.pagehide();
});

test("backend error clears accepted letter, preserves text, and recovers", async () => {
  let failed = false;
  const ui = setup({ predict: async () => failed
    ? response({ error: "Model unavailable" }, 503) : response(recognized("A")) });
  await ui.element("startCamera").click();
  await ui.advance();
  await ui.element("addLetter").click();
  failed = true;
  await ui.advance();
  assert.equal(ui.element("addLetter").disabled, true);
  assert.equal(ui.element("transcript").textContent, "A");
  assert.match(ui.element("errorMessage").textContent, /Model unavailable/);
  failed = false;
  await ui.advance();
  await ui.advance();
  assert.equal(ui.element("addLetter").disabled, false);
  assert.equal(ui.element("errorMessage").textContent, "");
  await ui.element("stopCamera").click();
  assert.equal(ui.element("transcript").textContent, "A");
});

test("one request in flight; late responses after stop/restart are ignored", async () => {
  const pending = [];
  const ui = setup({ predict: options => new Promise(resolve => pending.push({ resolve, options })) });
  await ui.element("startCamera").click();
  assert.equal(ui.requests.length, 1);
  await flush();
  assert.equal(ui.requests.length, 1);
  await ui.element("stopCamera").click();
  assert.equal(pending[0].options.signal.aborted, true);
  await ui.element("startCamera").click();
  pending[0].resolve(response(recognized("Y")));
  await flush();
  assert.equal(ui.element("addLetter").disabled, true);
  pending[1].resolve(response(recognized("B")));
  await flush();
  assert.equal(ui.element("addLetter").disabled, true);
  const advancing = ui.advance();
  await flush();
  pending[2].resolve(response(recognized("B")));
  await advancing;
  assert.equal(ui.element("detectedLetter").textContent, "B");
  ui.events.pagehide();
});

test("request timeout aborts inference and offers retry", async () => {
  const ui = setup({ predict: ({ signal }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }) });
  await ui.element("startCamera").click();
  await ui.advance();
  assert.equal(ui.requests[0].signal.aborted, true);
  assert.equal(ui.element("addLetter").disabled, true);
  assert.match(ui.element("errorMessage").textContent, /timed out/);
  ui.events.pagehide();
});

test("camera permission denial and late permission after cancellation", async () => {
  const denied = setup({ getUserMedia: async () => { throw new DOMException("Denied", "NotAllowedError"); } });
  await denied.element("startCamera").click();
  assert.match(denied.element("errorMessage").textContent, /permission denied/);
  assert.equal(denied.element("startCamera").disabled, false);
  assert.equal(denied.requests.length, 0);

  let grant;
  const ui = setup({ getUserMedia: () => new Promise(resolve => { grant = resolve; }) });
  const starting = ui.element("startCamera").click();
  await flush();
  await ui.element("stopCamera").click();
  grant(ui.stream);
  await starting;
  assert.equal(ui.stopped(), 1);
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.element("startCamera").disabled, false);
});
