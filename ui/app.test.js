"use strict";

// Input and rendering checks without a browser or third-party DOM implementation.
const assert = require("node:assert/strict");
const crypto = require("node:crypto").webcrypto;
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

function emptyState() {
  return { firmware: null, images: [], processors: [], satellite: null, events: [], running: false,
    key_epoch: 0, session_id: "a".repeat(32) };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

async function fixture(keyResponse, stateResponse) {
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
  const stateCalls = [];
  const context = vm.createContext({
    document, window, Intl, crypto, AbortSignal: { timeout: () => undefined },
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options = {}) => {
      if (url === "/api/state") {
        stateCalls.push(url);
        const state = stateResponse ? await stateResponse() : emptyState();
        return { ok: true, json: async () => state };
      }
      const body = url === "/api/firmware" ? options.body : JSON.parse(options.body);
      calls.push({ url, body });
      requests.push(options);
      const response = keyResponse ? await keyResponse(body, url) : null;
      const result = response || { message: "Recorded; wiring unresolved", delivered: false };
      return { ok: true, json: async () => url === "/api/key"
        ? { key_epoch: body.epoch, session_id: body.session_id, ...result }
        : { session_id: "a".repeat(32), ...result } };
    },
  });
  vm.runInContext(source, context);
  await vm.runInContext("refreshState()", context);
  return { context, calls, requests, stateCalls, window, document, elements, buttons, run: (code) => vm.runInContext(code, context) };
}

function keyEvent(app, key, pressed, sequence, epoch = 0, session = app.run("sessionId")) {
  return { key, pressed, client_id: app.run("clientId"), sequence, epoch, session_id: session };
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
  assert.match(app.elements.get("fidelity-description").textContent, /Firmware-derived Iridium 9575 Extreme/);
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
    keyEvent(app, "sos", true, 1), keyEvent(app, "sos", false, 2),
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
  assert.deepEqual(app.calls.map((call) => call.body), [keyEvent(app, "2", true, 1)]);
  assert.ok(app.buttons.find((button) => button.dataset.key === "2").classes.has("held"));
  app.run("releaseKey('keyboard:Digit2')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    keyEvent(app, "2", true, 1), keyEvent(app, "2", false, 2),
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

test("reconnection retries a failed release once without replaying the press", async () => {
  let held = false;
  let releases = 0;
  const retry = deferred();
  const app = await fixture(async (event) => {
    if (!event.pressed) {
      if (++releases === 1) throw new Error("Network failure");
      await retry.promise;
    }
    held = event.pressed;
  });
  app.run("pressKey('power', 'keyboard:KeyP'); releaseKey('keyboard:KeyP')");
  await app.run("keyQueue");
  assert.equal(held, true);
  assert.equal(app.run("heldSources.size"), 0);
  await app.run("refreshState()");
  await app.run("refreshState()");
  assert.equal(app.calls.length, 3, "Polling cannot enqueue another retry while one is pending");
  assert.deepEqual(app.calls[2].body, app.calls[1].body, "Retry the same release sequence and session");
  retry.resolve();
  await app.run("keyQueue");
  assert.equal(held, false);
  assert.equal(app.run("submittedKeys.size + pendingReleases.size"), 0);
  await app.run("refreshState()");
  assert.equal(app.calls.length, 3, "An acknowledged release is not retried");
});

test("a failed release retry cannot cancel a newer press of the same key", async () => {
  let held = false;
  const nextPress = deferred();
  const app = await fixture(async (event) => {
    if (!event.pressed && event.sequence === 2) throw new Error("Network failure");
    if (event.sequence === 3) await nextPress.promise;
    held = event.pressed;
  });
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  // Queue the new press before a poll schedules the retry of the older release.
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("refreshState()");
  nextPress.resolve();
  await app.run("keyQueue");
  assert.equal(held, true);
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 3]);
  assert.equal(app.run("submittedKeys.get('1').sequence"), 3);
  app.run("releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.equal(held, false);
});

test("pagehide cancels queued presses and immediately releases an in-flight press", async () => {
  let finishPress;
  const app = await fixture((body) => body.pressed && !finishPress
    ? new Promise((resolve) => { finishPress = resolve; }) : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.run("pressKey('2', 'keyboard:Digit2')");
  const oldQueue = app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.map((call) => call.body), [
    keyEvent(app, "1", true, 1),
    keyEvent(app, "1", false, 3),
  ], "Cleanup is sent before the pending press promise settles");
  assert.ok(app.requests.every((options) => options.keepalive === true));
  assert.ok(app.buttons.every((button) => !button.classes.has("held")));
  // Restoring the page must not revive the old queued press.
  app.window.listeners.get("pageshow")({ persisted: true });
  finishPress();
  await oldQueue;
  assert.equal(app.calls.length, 2);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.slice(2).map((call) => call.body), [
    keyEvent(app, "1", true, 4),
    keyEvent(app, "1", false, 5),
  ]);
});

test("pagehide releases submitted keys even after blur cleared their local owners", async () => {
  let finishPress;
  const app = await fixture((body) => body.pressed && !finishPress
    ? new Promise((resolve) => { finishPress = resolve; }) : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.window.listeners.get("blur")();
  const oldQueue = app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.map((call) => call.body.pressed), [true, false]);
  assert.equal(app.requests[1].keepalive, true);
  finishPress();
  await oldQueue;
  assert.equal(app.calls.length, 2);
});

test("pagehide cleanup keeps the submitted epoch and a newer sequence", async () => {
  const press = deferred();
  const app = await fixture((body) => body.pressed ? press.promise : undefined);
  app.run("renderState({key_epoch:7}); pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.window.listeners.get("blur")();
  const oldQueue = app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.map((call) => call.body), [
    keyEvent(app, "1", true, 1, 7), keyEvent(app, "1", false, 3, 7),
  ]);
  press.resolve();
  await oldQueue;
});

test("returning from pagehide retries cleanup lost while the page was offline", async () => {
  let connected = true;
  let held = false;
  let state = emptyState();
  const app = await fixture((event) => {
    if (!connected) throw new Error("Network failure");
    held = event.pressed;
  }, () => state);
  app.run("pressKey('power', 'keyboard:KeyP')");
  await app.run("keyQueue");
  const oldPoll = deferred();
  state = oldPoll.promise;
  const pending = app.run("refreshState()");
  connected = false;
  app.window.listeners.get("pagehide")();
  await new Promise(setImmediate);
  assert.equal(held, true);
  state = emptyState();
  oldPoll.resolve(state);
  await pending;
  assert.equal(app.run("pendingReleases.size"), 1, "A late hidden-page poll must retain failed cleanup");
  connected = true;
  app.window.listeners.get("pageshow")({ persisted: true });
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.equal(held, false);
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 2]);
});

test("an epoch advance cancels old queued and submitted keys without waiting or reviving them", async () => {
  const press = deferred();
  const app = await fixture((body) => body.sequence === 1 ? press.promise : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await Promise.resolve();
  app.run("pressKey('2', 'keyboard:Digit2'); releaseKey('keyboard:Digit1')");
  const oldQueue = app.run("keyQueue");
  app.run("renderState({key_epoch:1}); renderState({key_epoch:0})");
  assert.equal(app.run("keyEpoch"), 1, "An older poll cannot regress the epoch");
  assert.ok(app.buttons.every((button) => !button.classes.has("held")));
  assert.equal(app.run("heldSources.size + submittedKeys.size"), 0);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body), [
    keyEvent(app, "1", true, 1), keyEvent(app, "1", true, 4, 1),
  ], "A fresh press uses the new epoch while the old response is still pending");
  press.resolve({ key_epoch: 0 });
  await oldQueue;
  assert.equal(app.calls.length, 2, "Old queued events stay cancelled after the delayed response arrives");
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.at(-1).body, keyEvent(app, "1", false, 5, 1), "The old response cannot remove the fresh held press");
});

test("a stale key response advances the epoch and cancels the queued tap without resubmitting", async () => {
  const app = await fixture(() => ({ key_epoch: 1, delivered: false, message: "Stale key epoch ignored" }));
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1'); pressKey('2', 'keyboard:Digit2')");
  const queued = app.run("keyQueue");
  await queued;
  assert.deepEqual(app.calls.map((call) => call.body), [keyEvent(app, "1", true, 1)]);
  assert.equal(app.run("keyEpoch"), 1);
  assert.equal(app.run("heldSources.size + submittedKeys.size"), 0);
  assert.ok(app.buttons.every((button) => !button.classes.has("held")));
});

test("server restart replaces equal or lower epochs without reviving old key requests", async () => {
  for (const epoch of [0, 7]) {
    let state = { ...emptyState(), key_epoch: epoch, handset: { model: "9575" }, firmware: { name: "old session" } };
    const press = deferred();
    const app = await fixture((event) => event.sequence === 1 ? press.promise : undefined, () => state);
    app.run("pressKey('1', 'keyboard:Digit1')");
    await Promise.resolve();
    app.run("pressKey('2', 'keyboard:Digit2')");
    const oldQueue = app.run("keyQueue");
    state = { ...emptyState(), session_id: "b".repeat(32), handset: { model: "9555" }, firmware: { name: "new session" } };
    await app.run("refreshState()");
    assert.equal(app.run("sessionId"), state.session_id);
    assert.equal(app.run("keyEpoch"), 0);
    assert.equal(app.elements.get("firmware-name").textContent, "new session");
    assert.equal(app.elements.get("brand-model").textContent, "9555");
    assert.equal(app.run("heldSources.size + submittedKeys.size + pendingReleases.size"), 0);
    app.run("pressKey('1', 'keyboard:Digit1')");
    await app.run("keyQueue");
    press.resolve({ session_id: "a".repeat(32), key_epoch: 99 });
    await oldQueue;
    assert.equal(app.run("keyEpoch"), 0, "An old response cannot overwrite the new session's epoch");
    assert.deepEqual(app.calls.map((call) => call.body), [
      keyEvent(app, "1", true, 1, epoch, "a".repeat(32)), keyEvent(app, "1", true, 3, 0, state.session_id),
    ]);
    app.run("releaseKey('keyboard:Digit1')");
    await app.run("keyQueue");
    assert.deepEqual(app.calls.at(-1).body, keyEvent(app, "1", false, 4, 0, state.session_id));
  }
});

test("old control and state replies cannot restore a replaced server session", async () => {
  const mutation = deferred();
  const oldPoll = deferred();
  let state = emptyState();
  const app = await fixture((body, url) => url === "/api/control" ? mutation.promise : undefined, () => state);
  const action = app.run("action(element('run-button'), () => post('/api/control', {action:'run'}))");
  state = oldPoll.promise;
  const pending = app.run("refreshState()");
  const replacement = { ...emptyState(), session_id: "b".repeat(32), firmware: { name: "new session" } };
  app.context.replacement = replacement;
  app.run("renderState(replacement)");
  state = replacement;
  oldPoll.resolve({ ...emptyState(), key_epoch: 99, firmware: { name: "old session" } });
  await pending;
  mutation.resolve({ session_id: "a".repeat(32), key_epoch: 100 });
  await action;
  assert.equal(app.run("sessionId"), replacement.session_id);
  assert.equal(app.run("keyEpoch"), 0);
  assert.equal(app.elements.get("firmware-name").textContent, "new session");
});

test("a session change discards failed releases instead of sending them to the replacement", async () => {
  let state = emptyState();
  const app = await fixture((event) => {
    if (!event.pressed) throw new Error("Network failure");
  }, () => state);
  app.run("pressKey('power', 'keyboard:KeyP'); releaseKey('keyboard:KeyP')");
  await app.run("keyQueue");
  assert.equal(app.run("pendingReleases.size"), 1);
  state = { ...emptyState(), session_id: "b".repeat(32) };
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.equal(app.calls.length, 2);
  assert.equal(app.run("pendingReleases.size"), 0);
});

test("pages have independent IDs and sequences regardless of other clients' generations", async () => {
  const app = await fixture();
  app.run("renderState({key_generations:{'1':7},key_epoch:0})");
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  const fresh = await fixture(undefined, () => ({ ...emptyState(), key_generations: { 1: 999 } }));
  assert.notEqual(app.run("clientId"), fresh.run("clientId"));
  fresh.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await fresh.run("keyQueue");
  assert.deepEqual(fresh.calls.map((call) => call.body), [keyEvent(fresh, "1", true, 1), keyEvent(fresh, "1", false, 2)]);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 3, 4]);
  assert.ok([...app.calls, ...fresh.calls].every((call) => !("generation" in call.body)));
});

test("actions wait for a state request issued after a delayed older poll", async () => {
  let nextState;
  const app = await fixture(undefined, () => nextState ? nextState() : emptyState());
  const old = deferred();
  const fresh = deferred();
  nextState = () => old.promise;
  const poll = app.run("refreshState()");
  const getCount = app.stateCalls.length;
  let completed = false;
  const mutation = app.run("action(element('run-button'), () => post('/api/control', {action:'run'}))").then(() => { completed = true; });
  await new Promise(setImmediate);
  assert.equal(app.calls.at(-1).url, "/api/control");
  assert.equal(app.stateCalls.length, getCount, "The action waits for the older GET before requesting another");
  assert.equal(app.elements.get("run-button").disabled, true);
  nextState = () => fresh.promise;
  old.resolve(emptyState());
  await poll;
  await new Promise(setImmediate);
  assert.equal(app.stateCalls.length, getCount + 1, "The old poll is followed by a new GET");
  assert.equal(completed, false, "The action cannot finish on the older state");
  assert.equal(app.elements.get("run-button").disabled, true);
  fresh.resolve({ ...emptyState(), running: true });
  await mutation;
  assert.equal(completed, true);
  assert.equal(app.elements.get("run-button").disabled, false);
  assert.equal(app.elements.get("runtime-status").textContent, "RUNNING");
  assert.equal(app.elements.get("run-button").dataset.action, "pause");
});

test("all loaded image identities update when an auxiliary processor image changes", async () => {
  const app = await fixture();
  const images = ["bc5", "avr", "trx", "ptt"].map((image) => ({ image, name: `${image}.bin`, sha256: image.repeat(64).slice(0, 64) }));
  const initial = { ...emptyState(), firmware: images[0], images, processors: images.map(({ image }) => ({ image })) };
  app.context.state = initial;
  app.run("renderState(state)");
  const list = app.elements.get("firmware-images");
  assert.match(html, /<ul[^>]+id="firmware-images"[^>]+aria-label="Loaded firmware images"/);
  assert.equal(list.children.length, 4);
  for (const [index, item] of list.children.entries()) {
    assert.equal(item.children[0].textContent, `${images[index].name} (${images[index].image})`);
    assert.equal(item.children[1].textContent, `SHA-256: ${images[index].sha256}`);
  }
  const updated = { ...images[1], name: "avr-patched.bin", sha256: "f".repeat(64) };
  app.context.state = { ...initial, images: images.map((image) => image.image === "avr" ? updated : image) };
  app.run("renderState(state)");
  assert.equal(app.elements.get("firmware-name").textContent, "bc5.bin");
  assert.equal(list.children[1].children[0].textContent, "avr-patched.bin (avr)");
  assert.equal(list.children[1].children[1].textContent, `SHA-256: ${updated.sha256}`);
  assert.equal(list.children[0].children[1].textContent, `SHA-256: ${images[0].sha256}`);
});

test("an auxiliary upload preserves local held keys until an epoch actually changes", async () => {
  const app = await fixture((body, url) => url === "/api/firmware" ? { message: "Loaded avr.bin", key_epoch: 0 } : undefined);
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  const input = app.elements.get("firmware-input");
  input.files = [{ name: "avr.bin", size: 8678 }];
  await input.listeners.get("change")({ currentTarget: input });
  assert.deepEqual(app.calls.filter((call) => call.url === "/api/key").map((call) => call.body), [keyEvent(app, "1", true, 1)]);
  assert.ok(app.buttons.find((button) => button.dataset.key === "1").classes.has("held"));
  app.run("releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.at(-1).body, keyEvent(app, "1", false, 2));
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
    keyEvent(app, "1", true, 1), keyEvent(app, "up", true, 2),
    keyEvent(app, "1", false, 3), keyEvent(app, "up", false, 4),
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
    keyEvent(app, "*", true, 1), keyEvent(app, "*", false, 2),
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
  assert.match(app.elements.get("display-mode").textContent, /Live original firmware LCD.*emulated serial controller/);
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
  assert.equal(button.disabled, true, "AVR firmware supplies the physical power endpoint");
  app.run("renderApplicationStatus({processors:[{image:'bc5'},{image:'avr'}],ui_initialized:false})");
  assert.equal(button.disabled, false);
  assert.equal(app.calls.length, 0, "Rendering must not initialize firmware");
  await button.listeners.get("click")();
  assert.deepEqual(app.calls, [{ url: "/api/control", body: { action: "initialize_ui" } }]);
  app.run("renderApplicationStatus({processors:[{image:'bc5'}],ui_initialized:true})");
  assert.equal(button.disabled, true);
  assert.match(app.elements.get("application-status").textContent, /POWERED ON/);
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

test("worker failures explain how to recover in the processor row", async () => {
  const app = await fixture();
  app.run("renderProcessors([{image:'avr',halt:'worker-failed',worker_error:'CPU worker timed out and was stopped'}])");
  const row = app.elements.get("processors").children[0];
  assert.ok(row.children.some((child) => child.textContent === "Stop: CPU worker timed out and was stopped. Reset to restart."));
});

test("failed releases retry after a successful poll without repeating delivered edges", async () => {
  for (const lostResponse of [false, true]) {
    let held = false;
    let sequence = 0;
    let fail = true;
    const edges = [];
    const app = await fixture((body) => {
      const failed = !body.pressed && fail;
      if (failed) fail = false;
      if ((!failed || lostResponse) && body.sequence > sequence) {
        sequence = body.sequence;
        if (held !== body.pressed) edges.push(body.pressed);
        held = body.pressed;
      }
      if (failed) throw new Error("Connection lost");
      return { delivered: true };
    });
    app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
    await app.run("keyQueue");
    assert.equal(app.run("pendingReleases.size"), 1);
    await app.run("refreshState()");
    await app.run("keyQueue");
    await app.run("refreshState()");
    assert.equal(held, false);
    assert.deepEqual(edges, [true, false]);
    assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 2]);
    assert.equal(app.run("pendingReleases.size + submittedKeys.size"), 0);
  }
});

test("a failed old release cannot retry over a newer held press", async () => {
  const release = deferred();
  const app = await fixture((body) => body.sequence === 2 ? release.promise : undefined);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await new Promise(setImmediate);
  app.run("pressKey('1', 'keyboard:Digit1')");
  release.reject(new Error("Connection lost"));
  await app.run("keyQueue");
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 3]);
  assert.equal(app.run("pendingReleases.size"), 0);
  assert.equal(app.run("submittedKeys.get('1').sequence"), 3);
  assert.ok(app.buttons.find((button) => button.dataset.key === "1").classes.has("held"));
});

test("a queued release retry is cancelled when a newer key event supersedes it", async () => {
  const otherPress = deferred();
  const app = await fixture((body) => {
    if (body.sequence === 2) throw new Error("Connection lost");
    if (body.sequence === 3) return otherPress.promise;
  });
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  app.run("pressKey('2', 'keyboard:Digit2')");
  await app.run("refreshState()");
  app.run("pressKey('1', 'keyboard:Digit1')");
  otherPress.resolve();
  await app.run("keyQueue");
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 3, 4]);
  assert.equal(app.run("submittedKeys.get('1').sequence"), 4);
});

test("server restart accepts a lower epoch and ignores delayed replies from the old session", async () => {
  let state = { ...emptyState(), key_epoch: 7, handset: { model: "9575" }, running: true };
  const press = deferred();
  const app = await fixture((body) => body.sequence === 1 ? press.promise : undefined, () => state);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await Promise.resolve();
  const oldQueue = app.run("keyQueue");
  state = { ...emptyState(), session_id: "b".repeat(32) };
  await app.run("refreshState()");
  assert.equal(app.run("keyEpoch"), 0);
  assert.equal(app.run("pendingReleases.size + submittedKeys.size + heldSources.size"), 0);
  assert.equal(app.elements.get("brand-model").textContent, "9555");
  assert.equal(app.elements.get("runtime-status").textContent, "PAUSED");
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  press.resolve({ key_epoch: 99, session_id: "a".repeat(32) });
  await oldQueue;
  assert.equal(app.run("keyEpoch"), 0);
  assert.equal(app.run("sessionId"), "b".repeat(32));
  assert.equal(app.calls.length, 2, "Old queued releases stay cancelled");
  assert.deepEqual(app.calls.at(-1).body, keyEvent(app, "1", true, 3));
  app.window.listeners.get("pagehide")();
  assert.deepEqual(app.calls.at(-1).body, keyEvent(app, "1", false, 4));
});

test("server restart with the same epoch cancels failed release retries", async () => {
  let state = emptyState();
  const app = await fixture((body) => {
    if (!body.pressed) throw new Error("Connection lost");
  }, () => state);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  state = { ...emptyState(), session_id: "b".repeat(32) };
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.equal(app.calls.length, 2);
  assert.equal(app.run("pendingReleases.size"), 0);
  assert.equal(app.run("sessionId"), "b".repeat(32));
});

test("a response from a restarted server refreshes identity before sending more keys", async () => {
  let state = { ...emptyState(), key_epoch: 7 };
  const app = await fixture(() => {
    state = { ...emptyState(), session_id: "b".repeat(32) };
    return { session_id: "b".repeat(32), key_epoch: 0 };
  }, () => state);
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  await app.run("refreshState()");
  assert.equal(app.run("sessionId"), "b".repeat(32));
  assert.equal(app.run("keyEpoch"), 0);
  assert.equal(app.calls.length, 1);
});

test("an old action response cannot advance the replacement server's epoch", async () => {
  let state = emptyState();
  const response = deferred();
  const app = await fixture(() => response.promise, () => state);
  const action = app.run("action(element('run-button'), () => post('/api/control', {action:'run'}))");
  state = { ...emptyState(), session_id: "b".repeat(32) };
  await app.run("refreshState()");
  response.resolve({ session_id: "a".repeat(32), key_epoch: 99 });
  await action;
  assert.equal(app.run("sessionId"), "b".repeat(32));
  assert.equal(app.run("keyEpoch"), 0);
});

test("cached page restoration retries offline cleanup across repeated navigation", async () => {
  let online = true;
  let held = false;
  const app = await fixture((body) => {
    if (!online) throw new Error("Offline");
    held = body.pressed;
    return { delivered: true };
  });
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  online = false;
  app.run("releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  await new Promise(setImmediate);
  assert.equal(app.run("heldSources.size + submittedKeys.size"), 0);
  assert.equal(app.run("pendingReleases.size"), 1);
  app.window.listeners.get("pageshow")({ persisted: true });
  await app.run("refreshState()");
  await app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  await new Promise(setImmediate);
  assert.equal(held, true);
  assert.equal(app.run("pendingReleases.size"), 1);
  online = true;
  app.window.listeners.get("pageshow")({ persisted: true });
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.equal(held, false);
  assert.equal(app.run("pendingReleases.size"), 0);
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 3, 3, 4, 4]);
});

test("late pagehide cleanup acknowledgement cannot remove a newer failed release", async () => {
  const cleanup = deferred();
  const app = await fixture((body) => {
    if (body.sequence === 2) return cleanup.promise;
    if (body.sequence === 4) throw new Error("Connection lost");
  });
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  app.window.listeners.get("pagehide")();
  app.window.listeners.get("pageshow")({ persisted: true });
  app.run("pressKey('1', 'keyboard:Digit1'); releaseKey('keyboard:Digit1')");
  await app.run("keyQueue");
  cleanup.resolve({ delivered: true });
  await new Promise(setImmediate);
  assert.equal(app.run("pendingReleases.get('1').event.sequence"), 4);
  assert.equal(app.run("pendingReleases.get('1').retry"), true);
});

test("restoring a page during an outstanding state request keeps one polling loop", async () => {
  let nextState;
  const app = await fixture(undefined, () => nextState || emptyState());
  const state = deferred();
  nextState = state.promise;
  const timers = [];
  app.context.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
  const oldPoll = app.run("poll()");
  const requests = app.stateCalls.length;
  app.window.listeners.get("pagehide")();
  app.window.listeners.get("pageshow")({ persisted: true });
  state.resolve(emptyState());
  await oldPoll;
  await new Promise(setImmediate);
  assert.equal(app.stateCalls.length, requests, "Restoration shares the outstanding request");
  assert.equal(timers.length, 1, "Only the restored page schedules a new poll");
  assert.equal(timers[0].delay, 1250);
});

test("a state response received while hidden preserves failed cleanup for restoration", async () => {
  let nextState;
  let online = true;
  let held = false;
  const app = await fixture((body) => {
    if (!online) throw new Error("Offline");
    held = body.pressed;
  }, () => nextState || emptyState());
  app.run("pressKey('1', 'keyboard:Digit1')");
  await app.run("keyQueue");
  const state = deferred();
  nextState = state.promise;
  const polling = app.run("refreshState()");
  online = false;
  app.window.listeners.get("pagehide")();
  await new Promise(setImmediate);
  state.resolve(emptyState());
  await polling;
  await app.run("keyQueue");
  assert.equal(app.run("pendingReleases.get('1').retry"), true);
  online = true;
  nextState = null;
  app.window.listeners.get("pageshow")({ persisted: true });
  await app.run("refreshState()");
  await app.run("keyQueue");
  assert.equal(held, false);
  assert.equal(app.run("pendingReleases.size"), 0);
  assert.deepEqual(app.calls.map((call) => call.body.sequence), [1, 2, 2]);
});
