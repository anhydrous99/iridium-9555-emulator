"use strict";

const element = (id) => document.getElementById(id);
const numberFormat = new Intl.NumberFormat();
const keyButtons = new Map([...document.querySelectorAll("[data-key]")].map((button) => [button.dataset.key, button]));
const heldSources = new Map();
const submittedKeys = new Map();
const clientId = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
const pendingActions = new Set();
let latestState = null;
let stateRequest = null;
let keyQueue = Promise.resolve();
let keyQueueVersion = 0;
let keyEpoch = null;
let keySequence = 0;
let feedbackTimer;
let pollTimer;
let satelliteDirty = false;
let lastEventSignature = "";
let lastDisplaySignature = "";
let closed = false;

function displayText(value) {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function feedback(message, isError = false) {
  const box = element("feedback");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(feedbackTimer);
  feedbackTimer = setTimeout(() => { box.hidden = true; }, isError ? 9000 : 5000);
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(60000) });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`The engine returned an unreadable response (${response.status}).`);
  }
  if (!response.ok || result.error) {
    throw new Error(displayText(result.error || result.message || `Request failed (${response.status}).`));
  }
  return result;
}

function post(path, body, options = {}) {
  return request(path, { ...options, method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = displayText(text);
  return result;
}

function address(value) {
  if (typeof value === "number") return `0x${value.toString(16).toUpperCase().padStart(6, "0")}`;
  return displayText(value);
}

function renderProcessors(processors) {
  const container = element("processors");
  if (!Array.isArray(processors) || processors.length === 0) {
    container.replaceChildren(node("p", "empty-state", "Processor state will appear after an image is loaded."));
    return;
  }
  container.replaceChildren(...processors.map((processor) => {
    const row = node("div", "processor");
    const name = node("div");
    name.append(node("span", "processor-label", "PROCESSOR"), node("span", "processor-name", processor.image));
    const pc = node("div");
    pc.append(node("span", "processor-label", "PROGRAM COUNTER"), node("span", "processor-value", address(processor.pc)));
    const steps = node("div");
    steps.append(node("span", "processor-label", "INSTRUCTIONS"), node("span", "processor-value", numberFormat.format(processor.steps || 0)));
    row.append(name, pc, steps);
    if (processor.halt && processor.halt !== "steps" && processor.halt !== "running") {
      row.append(node("p", "processor-note processor-halt", `Stop: ${displayText(processor.halt)}`));
    }
    if (processor.milestones) {
      const milestones = Array.isArray(processor.milestones)
        ? processor.milestones.map(displayText)
        : Object.entries(processor.milestones).map(([name, value]) => `${name.replaceAll("_", " ")}: ${displayText(value)}`);
      if (milestones.length) row.append(node("p", "processor-note", milestones.join(" · ")));
    }
    if (processor.unclassified_accesses !== undefined) {
      row.append(node("p", "processor-note", `Unclassified accesses: ${numberFormat.format(processor.unclassified_accesses)}`));
    }
    if (processor.uart_tx_dropped?.some((count) => count > 0)) {
      row.append(node("p", "processor-note processor-halt", `UART TX capture lost bytes: ${processor.uart_tx_dropped.join(" / ")} (ports 0 / 1). Reset to clear.`));
    }
    return row;
  }));
}

function drawDisplay(state) {
  const preview = element("asset-toggle").checked;
  const image = preview ? state?.asset : state?.lcd;
  const dropped = !preview && state?.processors?.some((processor) => processor.image === "bc5" && processor.lcd_dropped > 0);
  const signature = JSON.stringify([preview, state?.handset?.model, state?.firmware?.sha256, state?.ui_initialized, image, dropped]);
  if (signature === lastDisplaySignature) return;
  lastDisplaySignature = signature;
  const canvas = element("lcd");
  const context = canvas.getContext("2d");
  context.fillStyle = "#a8b58e";
  context.fillRect(0, 0, 128, 128);
  element("lcd-placeholder").hidden = false;
  element("display-orientation").hidden = true;
  element("lcd-placeholder-text").textContent = "AWAITING\nFIRMWARE DISPLAY";
  const describe = (message) => {
    element("display-mode").textContent = message;
    canvas.setAttribute("aria-label", message);
  };
  if (!image) {
    describe(preview ? "No supported embedded bitmap found in this image." : state?.ui_initialized
      ? "Waiting for firmware LCD output · experimental software initialization"
      : "Live LCD unavailable · initialize application to capture firmware output");
    return;
  }
  if (!preview && (image.error || dropped || image.live !== true)) {
    element("lcd-placeholder-text").textContent = "CAPTURE\nUNAVAILABLE";
    describe(image.error ? `LCD capture unavailable · ${displayText(image.error)}` : dropped
      ? "Incomplete LCD capture · frame withheld"
      : "Live LCD unavailable · unverified display source");
    return;
  }
  const { width, height, pixels } = image;
  const dimensionsValid = preview
    ? Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0 && width <= 512 && height <= 512
    : width === 128 && height === 128;
  if (!dimensionsValid || !Array.isArray(pixels) || pixels.length !== width * height || !pixels.every((pixel) => Number.isInteger(pixel) && pixel >= 0 && pixel <= 3)) {
    describe(preview ? "The embedded image has an unsupported pixel format." : "LCD capture unavailable · invalid framebuffer");
    return;
  }
  if (!preview && image.known_pixels !== width * height) {
    element("lcd-placeholder-text").textContent = "PARTIAL\nLCD CAPTURE";
    describe("Partial LCD capture · uninitialized pixels; frame withheld");
    return;
  }
  if (!preview && image.display_on !== true) {
    element("lcd-placeholder-text").textContent = "DISPLAY OFF";
    describe("Firmware LCD is off · experimental software initialization");
    return;
  }
  const palette = [[169, 184, 145], [123, 140, 102], [77, 94, 60], [33, 48, 21]];
  const buffer = document.createElement("canvas");
  buffer.width = width;
  buffer.height = height;
  const bufferContext = buffer.getContext("2d");
  const frame = bufferContext.createImageData(width, height);
  for (let index = 0; index < pixels.length; index += 1) {
    const color = palette[pixels[index]];
    const offset = index * 4;
    frame.data[offset] = color[0];
    frame.data[offset + 1] = color[1];
    frame.data[offset + 2] = color[2];
    frame.data[offset + 3] = 255;
  }
  bufferContext.putImageData(frame, 0, 0);
  const scale = Math.min(128 / width, 128 / height);
  context.imageSmoothingEnabled = false;
  context.drawImage(buffer, Math.floor((128 - width * scale) / 2), Math.floor((128 - height * scale) / 2), Math.floor(width * scale), Math.floor(height * scale));
  element("lcd-placeholder").hidden = true;
  element("display-orientation").hidden = preview;
  if (!preview) {
    element("display-orientation").textContent = image.segment_zero_on_right
      ? `${state?.handset?.model === "9575" ? "9575" : "9555"} panel mapping · SEG127 left, COM0 top`
      : `Controller mapping · ${displayText(image.coordinates || "unspecified")}`;
  }
  describe(preview ? "Firmware asset preview — not live LCD" : "Live original firmware LCD · experimental software initialization");
}

function renderApplicationStatus(state) {
  const button = element("initialize-button");
  const initialized = state?.ui_initialized === true;
  const busy = pendingActions.has(button);
  const loaded = state?.processors?.some((processor) => processor.image === "bc5");
  button.disabled = busy || initialized || !loaded;
  button.textContent = busy ? "Initializing…" : initialized ? "Application initialized" : "Initialize application";
  const status = element("application-status");
  status.textContent = busy ? "INITIALIZING" : initialized ? "EXPERIMENTAL INITIALIZATION" : "NOT INITIALIZED";
  status.classList.toggle("initialized", initialized);
  element("key-mode").textContent = initialized
    ? "Original handler · experimental software key injection"
    : "Bench input only · application is not initialized";
}

function renderSatellite(satellite) {
  if (!satellite) return;
  const status = element("satellite-status");
  status.textContent = satellite.registered ? "REGISTERED" : satellite.visible ? "VISIBLE / UNREGISTERED" : "NO COVERAGE";
  status.classList.toggle("online", Boolean(satellite.registered));
  element("call-state").textContent = displayText(satellite.call_state || "idle").replaceAll("_", " ");
  element("scenario-time").textContent = `${numberFormat.format(satellite.time_ms || 0)} ms`;
  if (!satelliteDirty && !element("satellite-form").contains(document.activeElement)) {
    element("sat-visible").checked = Boolean(satellite.visible);
    element("sat-signal").value = satellite.signal ?? 0;
    element("signal-value").value = satellite.signal ?? 0;
    element("sat-latency").value = satellite.latency_ms ?? 600;
  }
}

function eventTime(value) {
  if (typeof value === "number") return `${numberFormat.format(value)} ms`;
  if (typeof value === "string" && value.includes("T")) {
    const date = new Date(value);
    if (Number.isFinite(date.getTime())) return date.toLocaleTimeString([], { hour12: false });
  }
  return displayText(value);
}

function renderEvents(events) {
  if (!Array.isArray(events)) return;
  const visibleEvents = events.slice(-100);
  const signature = JSON.stringify(visibleEvents);
  if (signature === lastEventSignature) return;
  lastEventSignature = signature;
  element("event-count").textContent = `${numberFormat.format(events.length)} EVENTS`;
  const table = element("events");
  if (!visibleEvents.length) {
    const row = node("tr");
    const cell = node("td", "empty-state", "Waiting for engine events.");
    cell.colSpan = 3;
    row.append(cell);
    table.replaceChildren(row);
    return;
  }
  table.replaceChildren(...visibleEvents.reverse().map((event) => {
    const row = node("tr");
    row.append(node("td", null, eventTime(event.time)), node("td", null, event.kind), node("td", null, event.message));
    return row;
  }));
}

function renderHandset(handset) {
  const extreme = handset?.model === "9575";
  const model = extreme ? "9575" : "9555";
  const name = extreme ? "Iridium 9575 Extreme" : "Iridium 9555";
  document.title = `${model}${extreme ? " Extreme" : ""} · Firmware lab`;
  element("brand").setAttribute("aria-label", `${name} firmware lab home`);
  element("brand-model").textContent = model;
  element("research-heading").textContent = `${name.toUpperCase()} · RESEARCH BENCH`;
  element("phone-model").textContent = extreme ? "EXTREME" : model;
  element("phone-bottom-model").textContent = model;
  element("footer-model").textContent = name.toUpperCase();
  element("handset").classList.toggle("extreme", extreme);
  element("extreme-key-help").hidden = !extreme;
  element("firmware-profile").textContent = `${name}${handset?.firmware_version ? ` · ${handset.firmware_version}` : ""}. Handset model is identified from the firmware image.`;
  element("firmware-input").setAttribute("aria-label", `Load original ${name} firmware image`);
  element("fidelity-description").textContent = `This is a partial ${name} hardware model. Application initialization and software key injection are explicit experimental scenarios.`;
  keyButtons.get("convenience").setAttribute("aria-label", extreme ? "Location convenience key" : "Side convenience key");
  keyButtons.get("convenience").title = extreme ? "Location convenience key (G)" : "Side convenience key (G)";
  const keys = new Set(handset?.keys || [...keyButtons.keys()].filter((key) => extreme || key !== "sos"));
  for (const [key, button] of keyButtons) {
    const available = keys.has(key) && (key !== "sos" || extreme);
    button.hidden = !available;
    button.disabled = !available;
    if (!available) {
      for (const [source, held] of heldSources) {
        if (held === key) releaseKey(source);
      }
    }
  }
}

function renderState(state) {
  if (keyEpoch !== null && state.key_epoch < keyEpoch) return;
  updateKeyEpoch(state.key_epoch);
  latestState = state;
  renderHandset(state.handset);
  const firmware = state.firmware;
  element("firmware-name").textContent = firmware?.name || "No firmware loaded";
  element("firmware-format").textContent = firmware?.format || "Load a supported original firmware image";
  const images = state.images || (firmware ? [firmware] : []);
  element("firmware-images").replaceChildren(...images.map((image) => {
    const item = node("li");
    item.append(node("strong", null, `${displayText(image.name)} (${displayText(image.image)})`),
      node("code", null, `SHA-256: ${displayText(image.sha256)}`));
    return item;
  }));
  const running = Boolean(state.running);
  const runButton = element("run-button");
  runButton.dataset.action = running ? "pause" : "run";
  runButton.replaceChildren(node("span", null, running ? "Ⅱ" : "▶"), document.createTextNode(running ? " Pause" : " Run"));
  const runtime = element("runtime-status");
  runtime.textContent = running ? "RUNNING" : "PAUSED";
  runtime.classList.toggle("running", running);
  renderApplicationStatus(state);
  renderProcessors(state.processors);
  renderSatellite(state.satellite);
  renderEvents(state.events);
  drawDisplay(state);
  if (Array.isArray(state.fidelity?.limitations)) {
    element("limitations").replaceChildren(...state.fidelity.limitations.map((limit) => node("li", null, limit)));
  }
}

async function refreshState(afterMutation = false) {
  if (afterMutation && stateRequest) await stateRequest;
  if (stateRequest) return stateRequest;
  stateRequest = request("/api/state").then((state) => {
    element("connection-dot").classList.add("connected");
    element("connection-status").textContent = "Local engine connected";
    renderState(state);
  }).catch((error) => {
    element("connection-dot").classList.remove("connected");
    element("connection-status").textContent = "Engine unavailable";
    element("connection-status").title = error.message;
  }).finally(() => { stateRequest = null; });
  return stateRequest;
}

async function poll() {
  if (closed) return;
  await refreshState();
  if (!closed) pollTimer = setTimeout(poll, latestState?.running ? 50 : 1250);
}

function resultMessage(result, fallback) {
  return displayText(result.message || result.delivery || fallback);
}

async function action(button, callback) {
  if (button.disabled) return;
  pendingActions.add(button);
  button.disabled = true;
  renderApplicationStatus(latestState);
  try {
    const result = await callback();
    updateKeyEpoch(result?.key_epoch);
    if (result?.message) feedback(displayText(result.message));
    await refreshState(true);
  } catch (error) {
    feedback(error.message, true);
  } finally {
    pendingActions.delete(button);
    button.disabled = false;
    renderApplicationStatus(latestState);
  }
}

function queueKey(key, pressed) {
  const version = keyQueueVersion;
  const event = { key, pressed, client_id: clientId, sequence: ++keySequence, epoch: keyEpoch };
  keyQueue = keyQueue.then(async () => {
    if (closed || version !== keyQueueVersion) return;
    if (pressed) submittedKeys.set(key, event);
    try {
      const result = await post("/api/key", event, { keepalive: true });
      updateKeyEpoch(result.key_epoch);
      if (version !== keyQueueVersion) return;
      if (!pressed) submittedKeys.delete(key);
      const delivery = result.delivered === true ? "Original firmware handler" : "Not delivered to firmware";
      element("key-feedback").textContent = `${key} ${pressed ? "↓" : "↑"} · ${delivery} · ${resultMessage(result, "Input recorded.")}`;
    } catch (error) {
      if (version !== keyQueueVersion) return;
      element("key-feedback").textContent = `${key}: ${error.message}`;
    }
  });
}

function pressKey(key, source) {
  const button = keyButtons.get(key);
  if (closed || keyEpoch === null || !button || button.disabled || button.hidden || heldSources.has(source)) return;
  const wasHeld = [...heldSources.values()].includes(key);
  heldSources.set(source, key);
  keyButtons.get(key).classList.add("held");
  if (!wasHeld) queueKey(key, true);
}

function releaseKey(source) {
  const key = heldSources.get(source);
  if (key === undefined) return;
  heldSources.delete(source);
  if (![...heldSources.values()].includes(key)) {
    keyButtons.get(key).classList.remove("held");
    queueKey(key, false);
  }
}

function releaseAllKeys() {
  for (const source of [...heldSources.keys()]) releaseKey(source);
  return keyQueue;
}

function cancelLocalKeys() {
  keyQueueVersion += 1;
  keyQueue = Promise.resolve();
  for (const key of heldSources.values()) keyButtons.get(key).classList.remove("held");
  heldSources.clear();
  submittedKeys.clear();
}

function updateKeyEpoch(epoch) {
  if (!Number.isSafeInteger(epoch) || epoch < 0 || (keyEpoch !== null && epoch <= keyEpoch)) return;
  if (keyEpoch !== null) cancelLocalKeys();
  keyEpoch = epoch;
}

for (const [key, button] of keyButtons) {
  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    button.focus({ preventScroll: true });
    button.setPointerCapture(event.pointerId);
    pressKey(key, `pointer:${event.pointerId}`);
  });
  for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
    button.addEventListener(eventName, (event) => releaseKey(`pointer:${event.pointerId}`));
  }
  button.addEventListener("click", (event) => {
    // Screen-reader activation has no pointer or keydown event.
    if (event.detail === 0) {
      const source = `activation:${key}`;
      pressKey(key, source);
      releaseKey(source);
    }
  });
}

const physicalKeys = { ArrowUp: "up", ArrowDown: "down", Escape: "red", c: "green", p: "power", g: "convenience", s: "sos", F1: "soft_left", F2: "soft_right", PageUp: "volume_up", PageDown: "volume_down" };
window.addEventListener("keydown", (event) => {
  if (event.target.closest("input, textarea, select, [contenteditable='true']") || event.ctrlKey || event.altKey || event.metaKey) return;
  let key;
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-key]")) key = event.target.dataset.key;
  else if (/^[0-9*#]$/.test(event.key)) key = event.key;
  else key = physicalKeys[event.key] || physicalKeys[event.key.toLowerCase()];
  if (key) {
    event.preventDefault();
    if (!event.repeat) pressKey(key, `keyboard:${event.code || event.key}`);
  }
});
window.addEventListener("keyup", (event) => releaseKey(`keyboard:${event.code || event.key}`));
window.addEventListener("blur", releaseAllKeys);
document.addEventListener("visibilitychange", () => { if (document.hidden) releaseAllKeys(); });

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => action(button, async () => {
    const payload = { action: button.dataset.action };
    if (payload.action === "reset" || payload.action === "initialize_ui") await releaseAllKeys();
    if (payload.action === "step") payload.steps = 10000;
    return post("/api/control", payload);
  }));
});

element("asset-toggle").addEventListener("change", () => {
  lastDisplaySignature = "";
  drawDisplay(latestState);
});

element("firmware-input").addEventListener("change", async (event) => {
  const input = event.currentTarget;
  const file = input.files[0];
  if (!file) return;
  if (file.size === 0 || file.size > 8 * 1024 * 1024) {
    feedback("Choose a non-empty firmware image no larger than 8 MiB.", true);
    input.value = "";
    return;
  }
  await action(input, async () => {
    const result = await request("/api/firmware", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file,
    });
    feedback(resultMessage(result, "Firmware image loaded."));
    lastDisplaySignature = "";
    return result;
  });
  input.value = "";
});

element("satellite-form").addEventListener("input", () => {
  satelliteDirty = true;
  element("signal-value").value = element("sat-signal").value;
});
element("satellite-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector("[type='submit']");
  action(button, async () => {
    const result = await post("/api/satellite", { action: "configure", visible: element("sat-visible").checked, signal: Number(element("sat-signal").value), latency_ms: Number(element("sat-latency").value) });
    satelliteDirty = false;
    return result;
  });
});

document.querySelectorAll("[data-satellite]").forEach((button) => {
  button.addEventListener("click", () => action(button, () => {
    const payload = { action: button.dataset.satellite };
    if (payload.action === "incoming_call" || payload.action === "incoming_sms") payload.number = element("remote-number").value;
    if (payload.action === "incoming_sms") payload.text = element("sms-text").value;
    if (payload.action === "advance") payload.milliseconds = 1000;
    return post("/api/satellite", payload);
  }));
});

window.addEventListener("pagehide", () => {
  closed = true;
  clearTimeout(pollTimer);
  for (const [key, event] of submittedKeys) {
    // The server cancels older presses even if this keepalive release arrives first.
    fetch("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, pressed: false, client_id: clientId, sequence: ++keySequence, epoch: event.epoch }), keepalive: true }).catch(() => {});
  }
  cancelLocalKeys();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    closed = false;
    poll();
  }
});

drawDisplay(null);
poll();
