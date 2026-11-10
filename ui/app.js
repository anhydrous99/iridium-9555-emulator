"use strict";

const element = (id) => document.getElementById(id);
const numberFormat = new Intl.NumberFormat();
const keyButtons = new Map([...document.querySelectorAll("[data-key]")].map((button) => [button.dataset.key, button]));
const heldSources = new Map();
const submittedKeys = new Map();
const pendingReleases = new Map();
const clientId = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
const pendingActions = new Set();
let latestState = null;
let stateRequest = null;
let keyQueue = Promise.resolve();
let keyQueueVersion = 0;
let keyEpoch = null;
let sessionId = null;
let keySequence = 0;
let feedbackTimer;
let pollTimer;
let pollVersion = 0;
let satelliteDirty = false;
let gpsDirty = false;
let simDirty = false;
let lastEventSignature = "";
let lastDisplaySignature = "";
let lastTranscriptSignature = "";
let lastScenarioSignature = "";
let keyProcessing = false;
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

function haltedProcessors(state) {
  return (state?.processors || []).filter((processor) => processor.active !== false && processor.halt && !["steps", "running", "ready"].includes(processor.halt));
}

function handsetImagesLoaded(state) {
  return ["bc5", "avr"].every((image) => state?.processors?.some((processor) => processor.image === image));
}

function renderTranscript(state, preview) {
  const lcd = state?.lcd;
  const captureValid = lcd?.live === true && lcd.display_on === true && !lcd.error && lcd.width === 128 && lcd.height === 128
    && Array.isArray(lcd.pixels) && lcd.pixels.length === 128 * 128 && lcd.pixels.every((pixel) => Number.isInteger(pixel) && pixel >= 0 && pixel <= 3)
    && lcd.known_pixels === 128 * 128 && !state?.processors?.some((cpu) => cpu.image === "bc5" && cpu.lcd_dropped > 0);
  const transcript = !preview && captureValid ? lcd.accessibility : null;
  const lines = Array.isArray(transcript?.lines) ? transcript.lines.filter((line) => typeof line.text === "string" && line.text) : [];
  const status = preview ? "Embedded asset preview. This is not the handset's current screen."
    : !captureValid ? "Screen text unavailable: no complete, active firmware LCD capture."
    : !lines.length ? "Screen text unknown: no text could be recognized from this firmware frame."
    : transcript.complete === true ? "Recognized screen text." : "Partial screen text: unrecognized content may be missing.";
  const detail = transcript?.status ? ` ${displayText(transcript.status)}` : "";
  const signature = JSON.stringify([status, detail, lines]);
  if (signature === lastTranscriptSignature) return;
  lastTranscriptSignature = signature;
  element("lcd-transcript-status").textContent = status + detail;
  element("lcd-transcript-lines").replaceChildren(...lines.map((line) => node("li", line.selected ? "selected" : null, `${line.selected ? "Selected: " : ""}${line.text}`)));
  element("lcd-announcement").textContent = [status + detail, ...lines.map((line) => `${line.selected ? "Selected: " : ""}${line.text}`)].join("\n");
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
    if (processor.active === false) row.append(node("p", "processor-note", "Not executing in this mode."));
    if (haltedProcessors({ processors: [processor] }).length) {
      const message = processor.halt === "worker-failed"
        ? `${processor.worker_error || "Worker exited"}. Its in-memory data is unavailable. Use Clear experiment to reload the supplied images.`
        : processor.halt;
      row.append(node("p", "processor-note processor-halt", `Stop: ${displayText(message)}`));
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
  renderTranscript(state, preview);
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
      ? "Waiting for firmware LCD output"
      : "Live LCD unavailable · power on the handset to capture firmware output");
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
    describe("Firmware LCD is off");
    return;
  }
  const contrast = !preview && Number.isFinite(image.contrast_ratio) ? Math.max(0, Math.min(1, image.contrast_ratio)) : null;
  const brightness = !preview && image.backlight_on === false ? 0.72 : 1;
  const palette = [[169, 184, 145], [123, 140, 102], [77, 94, 60], [33, 48, 21]].map((color) =>
    color.map((channel, index) => Math.round((contrast === null ? channel
      : [169, 184, 145][index] + (channel - [169, 184, 145][index]) * contrast) * brightness)));
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
  describe(preview ? "Firmware asset preview — not live LCD" : `Live original firmware LCD · emulated serial controller${contrast === null ? "" : ` · approximate contrast ${Math.round(contrast * 100)}% (not physically calibrated)`}${typeof image.backlight_on === "boolean" ? ` · backlight ${image.backlight_on ? "on" : "off"} (approximate brightness)` : ""}`);
}

function renderApplicationStatus(state) {
  const button = element("initialize-button");
  const initialized = state?.ui_initialized === true;
  const busy = pendingActions.has(button);
  const loaded = handsetImagesLoaded(state);
  const halted = haltedProcessors(state);
  const workerFailed = halted.some((cpu) => cpu.halt === "worker-failed");
  button.disabled = busy || initialized || !loaded;
  button.textContent = busy ? "Powering on…" : initialized ? halted.length ? "Handset halted" : "Handset powered on" : "Power on handset";
  const status = element("application-status");
  status.textContent = busy ? "POWERING ON" : halted.length ? "FIRMWARE HALTED" : initialized ? "POWERED ON" : "NOT POWERED ON";
  status.classList.toggle("initialized", initialized && !halted.length);
  const alert = element("halt-alert");
  alert.hidden = !halted.length;
  const recovery = workerFailed ? "A worker exited and its in-memory changes cannot be recovered. Clear experiment reloads the supplied images."
    : "Restart handset keeps saved flash data; unsaved edits may be lost. If this happens again, this firmware path may not be supported by the emulator.";
  const haltMessage = halted.length ? `Firmware stopped: ${halted.map((cpu) => `${displayText(cpu.image).toUpperCase()} · ${displayText(cpu.worker_error || cpu.halt)}`).join("; ")}. The handset may not respond. ${recovery}` : "";
  if (alert.textContent !== haltMessage) alert.textContent = haltMessage;
  element("key-mode").textContent = keyProcessing && !state?.running ? "Processing key in paused firmware…" : halted.length ? workerFailed ? "Worker exited · clear the experiment to reload" : "Firmware halted · restart the handset to continue" : initialized
    ? "GPIO keypad matrix · AVR power input"
    : loaded ? "Press Power or Power on handset to start" : "Load BC5 and AVR firmware to power on";
}

function renderSatellite(satellite) {
  if (!satellite) return;
  const status = element("satellite-status");
  const connected = satellite.firmware_connected === true;
  status.textContent = `${connected ? "" : "SANDBOX · "}${satellite.registered ? "REGISTERED" : satellite.registering ? "REGISTERING" : satellite.visible ? "UNREGISTERED" : "NO COVERAGE"}`;
  status.classList.toggle("online", Boolean(satellite.registered));
  element("scenario-disclosure").textContent = connected ? "Local satellite scenario connected to the emulated firmware. No live satellite transmission."
    : "Offline network sandbox. Registration, calls and SMS below affect this panel only; they are not delivered to the handset firmware.";
  element("call-state").textContent = `${displayText(satellite.call_state || "idle").replaceAll("_", " ")}${satellite.number ? ` · ${satellite.number}` : ""}`;
  element("scenario-progress").textContent = satellite.registering
    ? `Registration pending · configured delay ${numberFormat.format(satellite.latency_ms || 0)} ms. Use Advance 1 s until the scenario clock reaches delivery time.`
    : `Registration delay: ${numberFormat.format(satellite.latency_ms || 0)} ms. Choose Register, then Advance 1 s while registration is pending. Calls and SMS appear below when received.`;
  const messages = Array.isArray(satellite.messages) ? satellite.messages : [];
  const signature = JSON.stringify([satellite.number, satellite.call_state, messages]);
  if (signature !== lastScenarioSignature) {
    lastScenarioSignature = signature;
    element("scenario-callers").replaceChildren(node("li", null, satellite.number ? `${satellite.number} · ${displayText(satellite.call_state)}` : "No active caller."));
    element("scenario-messages").replaceChildren(...(messages.length ? messages.map((message) => {
      const item = node("li");
      item.append(node("strong", null, `${displayText(message.number)} · ${numberFormat.format(message.time_ms || 0)} ms`), node("p", null, message.text));
      return item;
    }) : [node("li", "empty-history", "No SMS received in the scenario.")]));
  }
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
  element("fidelity-description").textContent = `Firmware-derived ${name} hardware emulation for testing original and modified firmware.`;
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
  if (typeof state.session_id === "string" && state.session_id !== sessionId) {
    cancelLocalKeys();
    sessionId = state.session_id;
    keyEpoch = null;
  }
  if (keyEpoch !== null && state.key_epoch < keyEpoch) return;
  updateKeyEpoch(state.key_epoch);
  latestState = state;
  renderHandset(state.handset);
  renderFixtures(state);
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
  runtime.textContent = haltedProcessors(state).length ? "HALTED" : running ? "RUNNING" : keyProcessing ? "PROCESSING KEY" : "PAUSED";
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

function renderFixtures(state) {
  const mode = state.mode === "training" ? "training" : "research";
  const selector = element("emulation-mode");
  if (!pendingActions.has(selector)) selector.value = mode;
  element("mode-description").textContent = pendingActions.has(selector) ? "Switching mode and restarting the handset… Saved flash data is retained."
    : mode === "training"
    ? "Offline training supplies synthetic calls and messages. No real network or voice audio. Switching modes restarts the handset; saved data is kept, unsaved edits may be lost."
    : "Firmware research runs the original modem. Unsupported hardware paths can halt. Switching modes restarts the handset; saved data is kept, unsaved edits may be lost.";
  const capabilities = state.capabilities;
  const capabilityLabels = { calls: "Offline calls", sms: "Offline SMS", voice_audio: "Audio", backlight: "Backlight", gps: "Synthetic GPS", sim: "Synthetic SIM" };
  const entries = Array.isArray(capabilities) ? capabilities : capabilities && typeof capabilities === "object"
    ? Object.entries(capabilities).map(([name, value]) => name === "contrast" ? "Approximate display contrast"
      : `${capabilityLabels[name] || name.replaceAll("_", " ")}: ${value === true ? "available" : value === false ? "unavailable" : displayText(value)}`) : capabilities ? [capabilities] : [];
  element("mode-capabilities").replaceChildren(...entries.map((entry) => node("li", null, displayText(entry))));
  element("output-capabilities").textContent = `${capabilities?.voice_audio === true ? "Audio output is available." : "Audio output is unavailable in this browser."} ${capabilities?.backlight === true ? "Approximate backlight brightness follows the handset's output." : "Backlight output is unavailable."}`;
  if (!simDirty && !pendingActions.has(element("sim-apply"))) element("sim-present").checked = state.fixtures?.sim?.present !== false;
  element("sim-description").textContent = (mode === "training"
    ? "The training SIM supports local demo calls, messages and contacts. "
    : "Research SIM supplies storage only and can show a blocked-card status. Use Offline training for a ready demo SIM and calls. ")
    + "Applying SIM state restarts the handset; saved flash data is retained, unsaved edits may be lost.";
  const gps = state.fixtures?.gps;
  element("gps-form").hidden = state.handset?.model !== "9575";
  if (!gpsDirty && gps && !element("gps-form").contains(document.activeElement)) {
    element("gps-enabled").checked = gps.enabled === true;
    for (const name of ["latitude", "longitude", "altitude"]) if (gps[name] !== undefined) element(`gps-${name}`).value = gps[name];
  }
  updateGpsInputs();
}

function updateGpsInputs() {
  const enabled = element("gps-enabled").checked;
  for (const name of ["latitude", "longitude", "altitude"]) {
    element(`gps-${name}`).disabled = !enabled;
    element(`gps-${name}`).required = enabled;
  }
}

async function refreshState(afterMutation = false) {
  if (afterMutation && stateRequest) await stateRequest;
  if (stateRequest) return stateRequest;
  const requestedSession = sessionId;
  stateRequest = request("/api/state").then((state) => {
    if (sessionId !== requestedSession) return;
    element("connection-dot").classList.add("connected");
    element("connection-status").textContent = "Local engine connected";
    renderState(state);
    for (const pending of pendingReleases.values()) {
      if (!closed && pending.retry) {
        pending.retry = false;
        submitKey(pending.event, true);
      }
    }
  }).catch((error) => {
    element("connection-dot").classList.remove("connected");
    element("connection-status").textContent = "Engine unavailable";
    element("connection-status").title = error.message;
  }).finally(() => { stateRequest = null; });
  return stateRequest;
}

async function poll() {
  if (closed) return;
  const version = pollVersion;
  await refreshState();
  if (!closed && version === pollVersion) pollTimer = setTimeout(poll, latestState?.running ? 50 : 1250);
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
    if (result?.session_id === sessionId) updateKeyEpoch(result?.key_epoch);
    if (result?.message) feedback(displayText(result.message));
    await refreshState(true);
  } catch (error) {
    feedback(error.message, true);
  } finally {
    pendingActions.delete(button);
    button.disabled = false;
    renderApplicationStatus(latestState);
    renderFixtures(latestState || {});
  }
}

function queueKey(key, pressed) {
  const event = { key, pressed, ...(!pressed ? { settle: true } : {}), client_id: clientId, sequence: ++keySequence, epoch: keyEpoch, session_id: sessionId };
  if (pressed) pendingReleases.delete(key);
  else pendingReleases.set(key, { event, retry: false });
  submitKey(event);
}

function submitKey(event, retry = false) {
  const { key, pressed } = event;
  const version = keyQueueVersion;
  keyQueue = keyQueue.then(async () => {
    if (closed || version !== keyQueueVersion || (retry && pendingReleases.get(key)?.event !== event)) return;
    if (pressed) submittedKeys.set(key, event);
    keyProcessing = true;
    renderApplicationStatus(latestState);
    if (!latestState?.running) element("runtime-status").textContent = "PROCESSING KEY";
    try {
      const result = await post("/api/key", event, { keepalive: true });
      if (version !== keyQueueVersion) return;
      if (result.session_id !== sessionId) {
        cancelLocalKeys();
        keyEpoch = null;
        await refreshState(true);
        return;
      }
      updateKeyEpoch(result.key_epoch);
      if (version !== keyQueueVersion) return;
      if (!pressed) submittedKeys.delete(key);
      if (pendingReleases.get(key)?.event === event) pendingReleases.delete(key);
      const delivery = result.delivered === true ? "Original firmware handler" : "Not delivered to firmware";
      element("key-feedback").textContent = `${key} ${pressed ? "↓" : "↑"} · ${delivery} · ${resultMessage(result, "Input recorded.")}`;
      return true;
    } catch (error) {
      if (version !== keyQueueVersion) return;
      const pending = pendingReleases.get(key);
      if (pending?.event === event) pending.retry = true;
      element("key-feedback").textContent = `${key}: ${error.message}`;
      return false;
    } finally {
      if (version === keyQueueVersion) {
        keyProcessing = false;
        renderApplicationStatus(latestState);
        element("runtime-status").textContent = haltedProcessors(latestState).length ? "HALTED" : latestState?.running ? "RUNNING" : "PAUSED";
      }
    }
  });
  const queued = keyQueue;
  // Refresh after settled releases, without delaying queued key delivery on a GET.
  void queued.then((delivered) => {
    if (!pressed && delivered && queued === keyQueue && !closed && version === keyQueueVersion) return refreshState(true);
  });
}

function pressKey(key, source) {
  const button = keyButtons.get(key);
  if (closed || keyEpoch === null || !button || button.disabled || button.hidden || heldSources.has(source)) return;
  if (key === "power" && latestState?.ui_initialized !== true && handsetImagesLoaded(latestState)) {
    return action(element("initialize-button"), async () => {
      await releaseAllKeys();
      return post("/api/control", { action: "initialize_ui" });
    });
  }
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
  keyProcessing = false;
  keyQueue = Promise.resolve();
  for (const key of heldSources.values()) keyButtons.get(key).classList.remove("held");
  heldSources.clear();
  submittedKeys.clear();
  pendingReleases.clear();
}

function updateKeyEpoch(epoch, session = sessionId) {
  if (session !== sessionId) return;
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
  button.addEventListener("click", () => {
    if (button.dataset.action === "reset" && !window.confirm("Clear this experiment? This reloads the original firmware and erases saved contacts, changed settings, message drafts, and other changes made in this session. Use Restart handset to keep saved flash data.")) return;
    return action(button, async () => {
      const payload = { action: button.dataset.action };
      if (["reset", "restart", "initialize_ui"].includes(payload.action)) await releaseAllKeys();
      if (payload.action === "step") payload.steps = 10000;
      return post("/api/control", payload);
    });
  });
});

element("asset-toggle").addEventListener("change", () => {
  lastDisplaySignature = "";
  drawDisplay(latestState);
});

element("emulation-mode").addEventListener("change", () => action(element("emulation-mode"), async () => {
  const mode = element("emulation-mode").value;
  await releaseAllKeys();
  return post("/api/control", { action: "mode", mode });
}));

element("sim-present").addEventListener("change", () => { simDirty = true; });
element("sim-apply").addEventListener("click", () => action(element("sim-apply"), async () => {
  await releaseAllKeys();
  const result = await post("/api/fixtures", { action: "sim", present: element("sim-present").checked });
  simDirty = false;
  return result;
}));

element("gps-form").addEventListener("input", () => { gpsDirty = true; updateGpsInputs(); });
element("gps-form").addEventListener("submit", (event) => {
  event.preventDefault();
  return action(element("gps-apply"), async () => {
    const payload = { action: "gps", enabled: element("gps-enabled").checked };
    if (payload.enabled) {
      for (const name of ["latitude", "longitude", "altitude"]) {
        const value = String(element(`gps-${name}`).value).trim();
        payload[name] = value === "" ? NaN : Number(value);
        if (!Number.isFinite(payload[name])) throw new Error(`Enter a finite GPS ${name}.`);
      }
      if (Math.abs(payload.latitude) > 90 || Math.abs(payload.longitude) > 180) throw new Error("GPS latitude must be between −90 and 90; longitude between −180 and 180.");
    }
    const result = await post("/api/fixtures", payload);
    gpsDirty = false;
    return result;
  });
});

async function firmwareBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}

element("firmware-input").addEventListener("change", async (event) => {
  const input = event.currentTarget;
  const files = Array.from(input.files || []);
  if (!files.length) return;
  if (files.length > 4 || files.some((file) => file.size === 0 || file.size > 8 * 1024 * 1024)) {
    feedback("Choose one to four non-empty firmware images, each no larger than 8 MiB, with one image per processor.", true);
    input.value = "";
    return;
  }
  if (latestState?.processors?.some((processor) => processor.image === "bc5") && !window.confirm("Replace firmware? A BC5 image or handset model change clears saved contacts, changed settings, and message drafts from this experiment. Auxiliary images preserve BC5 flash. Continue with the selected images?")) {
    input.value = "";
    return;
  }
  await action(input, async () => {
    const file = files[0];
    const result = files.length === 1 ? await request("/api/firmware", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file,
    }) : await post("/api/firmware-bundle", { images: await Promise.all(files.map(async (image) => ({ name: image.name, data: await firmwareBase64(image) }))) });
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
    if (payload.action === "incoming_call" || payload.action === "incoming_sms") {
      payload.number = element("remote-number").value.trim();
      if (!payload.number || payload.number.length > 24) throw new Error("Enter a remote number between 1 and 24 characters.");
    }
    if (payload.action === "incoming_sms") payload.text = element("sms-text").value;
    if (payload.action === "advance") payload.milliseconds = 1000;
    return post("/api/satellite", payload);
  }));
});

window.addEventListener("pagehide", () => {
  closed = true;
  pollVersion += 1;
  clearTimeout(pollTimer);
  const releases = new Map(submittedKeys);
  for (const [key, pending] of pendingReleases) releases.set(key, pending.event);
  cancelLocalKeys();
  for (const [key, previous] of releases) {
    // The server cancels older presses even if this keepalive release arrives first.
    const event = { key, pressed: false, settle: true, client_id: clientId, sequence: ++keySequence, epoch: previous.epoch, session_id: previous.session_id };
    const pending = { event, retry: true };
    pendingReleases.set(key, pending);
    post("/api/key", event, { keepalive: true }).then((result) => {
      if (pendingReleases.get(key) === pending && result.session_id === event.session_id && result.key_epoch === event.epoch) {
        pendingReleases.delete(key);
      }
    }).catch(() => {});
  }
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    closed = false;
    poll();
  }
});

drawDisplay(null);
poll();
