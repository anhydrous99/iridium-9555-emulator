"use strict";

// Input and rendering checks without a browser or third-party DOM implementation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");

class Element {
  constructor() {
    this.listeners = new Map();
    this.dataset = {};
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.classes = new Set();
    this.attributes = new Map();
    this.classList = {
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
      toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  contains() { return false; }
  closest() { return null; }
  matches() { return false; }
  focus() {}
  setPointerCapture() {}
  getContext() {
    return {
      fillRect: () => { this.clears = (this.clears || 0) + 1; },
      drawImage: (source) => { this.draws = (this.draws || 0) + 1; this.frame = source.frame; },
      putImageData: (frame) => { this.frame = frame; },
      createImageData: (width, height) => ({ data: new Uint8ClampedArray(width * height * 4) }),
    };
  }
}

async function fixture(keyResponse) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const buttons = [...html.matchAll(/data-key="([^"]+)"/g)].map((match) => {
    const button = new Element();
    button.dataset.key = match[1];
    return button;
  });
  const actions = [...html.matchAll(/<button\b([^>]+)>/g)].flatMap((match) => {
    const operation = match[1].match(/data-action="([^"]+)"/);
    if (!operation) return [];
    const id = match[1].match(/id="([^"]+)"/);
    const button = id ? elements.get(id[1]) : new Element();
    button.dataset.action = operation[1];
    return [button];
  });
  const window = new Element();
  const document = new Element();
  document.getElementById = (id) => {
    assert.ok(elements.has(id), `Missing HTML element ${id}`);
    return elements.get(id);
  };
  document.querySelectorAll = (selector) => selector === "[data-key]" ? buttons : selector === "[data-action]" ? actions : [];
  document.createElement = () => new Element();
  document.createTextNode = (textContent) => ({ textContent });
  document.activeElement = null;
  const calls = [];
  const requests = [];
  const context = vm.createContext({
    document, window, Intl, AbortSignal: { timeout: () => undefined },
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options = {}) => {
      if (url === "/api/state") return { ok: true, json: async () => ({ firmware: null, processors: [], satellite: null, events: [], running: false }) };
      const body = JSON.parse(options.body);
      calls.push({ url, body });
      requests.push(options);
      const response = keyResponse ? await keyResponse(body) : null;
      const result = response || { message: "Recorded; wiring unresolved", delivered: false };
      return { ok: true, json: async () => url === "/api/key"
        ? { generation: body.generation + (body.pressed ? 0 : 1), ...result } : result };
    },
  });
  vm.runInContext(source, context);
  await vm.runInContext("refreshState()", context);
  return { context, calls, requests, window, elements, buttons, run: (code) => vm.runInContext(code, context) };
}

test("markup has one of every physical handset control and unique IDs", () => {
  const keys = [...html.matchAll(/data-key="([^"]+)"/g)].map((match) => match[1]);
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(ids.length, new Set(ids).size);
  assert.equal(keys.length, new Set(keys).size);
  assert.deepEqual(new Set(keys), new Set([...
    "0123456789*#", "soft_left", "soft_right", "up", "down", "green", "red", "power", "volume_up", "volume_down", "convenience", "sos"]));
});

test("firmware handset metadata selects the Extreme identity and physical controls", async () => {
  const app = await fixture();
  const sos = app.buttons.find((button) => button.dataset.key === "sos");
  assert.equal(app.elements.get("brand-model").textContent, "9555");
  assert.equal(sos.hidden, true);
  assert.equal(sos.disabled, true);
  app.run("renderState({handset:{model:'9575',name:'Iridium 9575 Extreme',firmware_version:'HL25003'}})");
  assert.equal(app.run("document.title"), "9575 Extreme · Firmware lab");
  assert.equal(app.elements.get("brand-model").textContent, "9575");
  assert.equal(app.elements.get("phone-model").textContent, "EXTREME");
  assert.equal(app.elements.get("phone-bottom-model").textContent, "9575");
  assert.match(app.elements.get("research-heading").textContent, /9575 EXTREME/);
  assert.match(app.elements.get("firmware-profile").textContent, /HL25003/);
  assert.match(app.elements.get("fidelity-description").textContent, /partial Iridium 9575 Extreme/);
  assert.match(app.elements.get("firmware-input").attributes.get("aria-label"), /9575 Extreme/);
  assert.ok(app.elements.get("handset").classes.has("extreme"));
  assert.equal(app.elements.get("extreme-key-help").hidden, false);
  assert.equal(sos.hidden, false);
  assert.equal(sos.disabled, false);
  assert.equal(app.buttons.find((button) => button.dataset.key === "convenience").attributes.get("aria-label"), "Location convenience key");
  app.run("renderState({handset:{model:'9555',firmware_version:'HT25003'}})");
  assert.equal(app.elements.get("phone-model").textContent, "9555");
  assert.equal(app.elements.get("handset").classes.has("extreme"), false);
  assert.equal(app.elements.get("extreme-key-help").hidden, true);
  assert.equal(sos.hidden, true);
});

test("SOS keyboard events respect handset controls and report actual firmware delivery", async () => {
  const app = await fixture();
  const down = app.window.listeners.get("keydown");
  const up = app.window.listeners.get("keyup");
  const press = () => down({ key: "s", code: "KeyS", target: new Element(), preventDefault() {} });
  press();
  up({ key: "s", code: "KeyS" });
  await app.run("keyQueue");
  assert.equal(app.calls.length, 0, "9555 must not submit the Extreme-only SOS key");
  app.run("renderState({handset:{model:'9575',keys:['sos','power']}})");
  press();
  up({ key: "s", code: "KeyS" });
  app.run("pressKey('1','pointer:1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    { key: "sos", pressed: true, generation: 0 }, { key: "sos", pressed: false, generation: 0 },
  ]);
  assert.match(app.elements.get("key-feedback").textContent, /Not delivered to firmware/);
});

test("switching handset releases a held key that is absent from the replacement model", async () => {
  const app = await fixture();
  app.run("renderState({handset:{model:'9575'}}); pressKey('sos','pointer:1')");
  await app.run("keyQueue");
  app.run("renderState({handset:{model:'9555'}}); releaseKey('pointer:1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.pressed), [true, false]);
  assert.equal(app.buttons.find((button) => button.dataset.key === "sos").classes.has("held"), false);
});

test("keyboard and pointer ownership prevent premature key release", async () => {
  const app = await fixture();
  app.run("pressKey('2', 'pointer:1'); pressKey('2', 'keyboard:Digit2'); releaseKey('pointer:1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [{ key: "2", pressed: true, generation: 0 }]);
  assert.ok(app.buttons.find((button) => button.dataset.key === "2").classes.has("held"));
  app.run("releaseKey('keyboard:Digit2')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    { key: "2", pressed: true, generation: 0 }, { key: "2", pressed: false, generation: 0 },
  ]);
});

test("network key releases cannot overtake a delayed press", async () => {
  let finishPress;
  const app = await fixture((body) => body.pressed ? new Promise((resolve) => { finishPress = resolve; }) : undefined);
  app.run("pressKey('power', 'pointer:1'); releaseKey('pointer:1')");
  await Promise.resolve();
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].body.pressed, true);
  finishPress();
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.pressed), [true, false]);
});

test("pagehide cancels queued presses and immediately releases an in-flight press", async () => {
  let finishPress;
  const app = await fixture((body) => body.pressed && !finishPress
    ? new Promise((resolve) => { finishPress = resolve; }) : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.run("pressKey('2', 'keyboard:Digit2')");
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.map((call) => call.body), [
    { key: "1", pressed: true, generation: 0 },
    { key: "1", pressed: false, generation: 0 },
  ], "Cleanup is sent before the pending press promise settles");
  assert.ok(app.requests.every((options) => options.keepalive === true));
  assert.ok(app.buttons.every((button) => !button.classes.has("held")));
  // Restoring the page must not revive the old queued press.
  app.window.listeners.get("pageshow")({ persisted: true });
  finishPress();
  await app.run("keyQueue");
  assert.equal(app.calls.length, 2);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.slice(2).map((call) => call.body), [
    { key: "1", pressed: true, generation: 1 },
    { key: "1", pressed: false, generation: 1 },
  ]);
});

test("pagehide releases submitted keys even after blur cleared their local owners", async () => {
  let finishPress;
  const app = await fixture((body) => body.pressed && !finishPress
    ? new Promise((resolve) => { finishPress = resolve; }) : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.window.listeners.get("blur")();
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.map((call) => call.body.pressed), [true, false]);
  assert.equal(app.requests[1].keepalive, true);
  finishPress();
  await app.run("keyQueue");
  assert.equal(app.calls.length, 2);
});

test("key generations follow server state and never regress on an older poll", async () => {
  const app = await fixture();
  app.run("renderState({key_generations:{'1':7}}); renderState({key_generations:{'1':6}})");
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.generation), [7, 7]);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.slice(2).map((call) => call.body.generation), [8, 8]);
});

test("serial capture loss is visible in the processor row", async () => {
  const app = await fixture();
  app.run("renderProcessors([{image:'avr',uart_tx_dropped:[45,0]}])");
  const row = app.elements.get("processors").children[0];
  assert.ok(row.children.some((child) => /UART.*45/.test(child.textContent)));
});

test("lost window focus releases all keys exactly once", async () => {
  const app = await fixture();
  app.run("pressKey('1', 'keyboard:Digit1'); pressKey('up', 'pointer:7')");
  await app.window.listeners.get("blur")();
  app.run("releaseKey('keyboard:Digit1'); releaseKey('pointer:7')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    { key: "1", pressed: true, generation: 0 }, { key: "up", pressed: true, generation: 0 },
    { key: "1", pressed: false, generation: 0 }, { key: "up", pressed: false, generation: 0 },
  ]);
});

test("shifted number key uses the physical code for release; forms keep their typing", async () => {
  const app = await fixture();
  const target = new Element();
  const down = app.window.listeners.get("keydown");
  const up = app.window.listeners.get("keyup");
  down({ key: "*", code: "Digit8", target, preventDefault() {} });
  up({ key: "8", code: "Digit8" });
  target.closest = () => target;
  down({ key: "5", code: "Digit5", target, preventDefault() { assert.fail("Form input was intercepted"); } });
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    { key: "*", pressed: true, generation: 0 }, { key: "*", pressed: false, generation: 0 },
  ]);
});

test("asset rendering remains explicitly separate from live firmware output", async () => {
  const app = await fixture();
  app.elements.get("asset-toggle").checked = true;
  app.run("drawDisplay({firmware:{sha256:'abc'},asset:{width:1,height:1,pixels:[0]}})");
  assert.equal(app.elements.get("display-mode").textContent, "Firmware asset preview — not live LCD");
  app.elements.get("asset-toggle").checked = false;
  app.run("drawDisplay({firmware:{sha256:'abc'},asset:{width:1,height:1,pixels:[0]}})");
  assert.match(app.elements.get("display-mode").textContent, /Live LCD unavailable/);
  assert.equal(app.elements.get("lcd-placeholder").hidden, false);
});

function liveState() {
  return {
    ui_initialized: true,
    firmware: { sha256: "same-source-image" },
    processors: [{ image: "bc5", lcd_dropped: 0 }],
    lcd: { width: 128, height: 128, pixels: Array(128 * 128).fill(0), known_pixels: 128 * 128, display_on: true, error: null, live: true, segment_zero_on_right: true, coordinates: "SEG127 left, COM0 top" },
    asset: { width: 2, height: 1, pixels: [3, 1] },
  };
}

test("live polling paints successive frames at 50 ms without overlapping requests", async () => {
  const app = await fixture();
  const timers = [];
  const responses = [];
  let requests = 0;
  app.context.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
  app.context.fetch = async (url) => {
    assert.equal(url, "/api/state");
    requests += 1;
    return { ok: true, json: () => new Promise((resolve) => responses.push(resolve)) };
  };

  const polling = app.run("poll()");
  const sharedRefresh = app.run("refreshState()");
  await new Promise(setImmediate);
  assert.equal(requests, 1, "An action refresh shares the pending poll request");
  assert.equal(timers.length, 0, "A slow response cannot start another poll");
  const first = liveState();
  first.running = true;
  first.lcd.pixels[0] = 3;
  responses.shift()(first);
  await Promise.all([polling, sharedRefresh]);
  assert.equal(app.elements.get("lcd").draws, 1);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 50);

  const nextPoll = timers.shift().callback();
  const nextRefresh = app.run("refreshState()");
  await new Promise(setImmediate);
  assert.equal(requests, 2);
  assert.equal(timers.length, 0);
  const second = liveState();
  second.running = false;
  second.lcd.pixels[1] = 3;
  responses.shift()(second);
  await Promise.all([nextPoll, nextRefresh]);
  assert.equal(app.elements.get("lcd").draws, 2, "Each received animation frame is painted");
  assert.deepEqual(Array.from(app.elements.get("lcd").frame.data.slice(0, 8)),
    [169, 184, 145, 255, 33, 48, 21, 255]);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 1250, "Paused sessions keep the slower polling interval");
});

test("live LCD follows changing firmware pixels and stays distinct from asset preview", async () => {
  const app = await fixture();
  const canvas = app.elements.get("lcd");
  app.context.frame = liveState();
  app.run("drawDisplay(frame)");
  assert.match(app.elements.get("display-mode").textContent, /Live original firmware LCD.*experimental/);
  assert.equal(app.elements.get("display-orientation").hidden, false);
  assert.equal(app.elements.get("display-orientation").textContent, "9555 panel mapping · SEG127 left, COM0 top");
  assert.equal(canvas.draws, 1);
  app.context.frame.lcd.pixels[0] = 3;
  app.run("drawDisplay(frame)");
  assert.equal(canvas.draws, 2, "Pixel changes redraw even when the input SHA is unchanged");
  assert.deepEqual(Array.from(canvas.frame.data.slice(0, 8)), [33, 48, 21, 255, 169, 184, 145, 255], "The browser preserves already projected handset pixels");
  app.elements.get("asset-toggle").checked = true;
  app.run("drawDisplay(frame)");
  assert.equal(app.elements.get("display-mode").textContent, "Firmware asset preview — not live LCD");
  assert.equal(app.elements.get("display-orientation").hidden, true);
  assert.deepEqual(Array.from(canvas.frame.data), [33, 48, 21, 255, 123, 140, 102, 255], "Asset pixels keep their original order independently of handset wiring");
});

test("live LCD paints all four shades with opaque alpha", async () => {
  const app = await fixture();
  app.context.frame = liveState();
  app.context.frame.lcd.pixels.splice(0, 4, 0, 1, 2, 3);
  app.run("drawDisplay(frame)");
  assert.deepEqual(Array.from(app.elements.get("lcd").frame.data.slice(0, 16)), [
    169, 184, 145, 255, 123, 140, 102, 255, 77, 94, 60, 255, 33, 48, 21, 255,
  ]);
});

test("incomplete, faulty, off, and unverified captures never present a live frame", async () => {
  const app = await fixture();
  const canvas = app.elements.get("lcd");
  for (const [change, expected] of [
    [(state) => { state.lcd.error = "Unknown LCD command"; }, /LCD capture unavailable/],
    [(state) => { state.processors[0].lcd_dropped = 1; }, /Incomplete LCD capture/],
    [(state) => { state.lcd.known_pixels = 0; }, /Partial LCD capture/],
    [(state) => { delete state.lcd.known_pixels; }, /Partial LCD capture/],
    [(state) => { state.lcd.display_on = false; }, /Firmware LCD is off/],
    [(state) => { state.lcd.live = false; }, /unverified display source/],
    [(state) => { state.lcd.pixels[0] = 9; }, /invalid framebuffer/],
  ]) {
    app.context.frame = liveState();
    app.run("drawDisplay(frame)");
    const previousDraws = canvas.draws;
    const previousClears = canvas.clears;
    change(app.context.frame);
    app.run("drawDisplay(frame)");
    assert.equal(canvas.draws, previousDraws, "Rejected capture must not be painted");
    assert.ok(canvas.clears > previousClears, "The previous live frame must be cleared");
    assert.match(app.elements.get("display-mode").textContent, expected);
    assert.equal(app.elements.get("lcd-placeholder").hidden, false);
  }
});

test("application initialization is explicit and the button respects loaded and initialized state", async () => {
  const app = await fixture();
  const button = app.elements.get("initialize-button");
  assert.equal(button.disabled, true, "No BC5 image is loaded");
  app.run("renderApplicationStatus({processors:[{image:'bc5'}],ui_initialized:false})");
  assert.equal(button.disabled, false);
  assert.equal(app.calls.length, 0, "Rendering must not initialize firmware");
  await button.listeners.get("click")();
  assert.deepEqual(app.calls, [{ url: "/api/control", body: { action: "initialize_ui" } }]);
  app.run("renderApplicationStatus({processors:[{image:'bc5'}],ui_initialized:true})");
  assert.equal(button.disabled, true);
  assert.match(app.elements.get("application-status").textContent, /EXPERIMENTAL/);
  await button.listeners.get("click")();
  assert.equal(app.calls.length, 1, "Already initialized application is not invoked again");
});

test("key feedback reports the backend's actual delivery result", async () => {
  const app = await fixture((body) => ({ delivered: body.pressed, message: "Measured result" }));
  app.run("pressKey('2', 'pointer:1')");
  await app.run("keyQueue");
  assert.match(app.elements.get("key-feedback").textContent, /Original firmware handler/);
  app.run("releaseKey('pointer:1')");
  await app.run("keyQueue");
  assert.match(app.elements.get("key-feedback").textContent, /Not delivered to firmware/);
});
