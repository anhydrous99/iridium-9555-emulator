// Measures JavaScript work only; this DOM stub does not measure layout or GPU work.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const samples = Number(process.argv[2] || 7);
assert.ok(Number.isInteger(samples) && samples >= 3);
let paints = 0;
function element() {
  return {
    dataset: {}, classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {}, append() {}, replaceChildren() {}, setAttribute() {}, contains() { return false; },
    getContext() {
      return {
        fillRect() {}, drawImage() { paints += 1; }, putImageData() {},
        createImageData(width, height) { return { data: new Uint8ClampedArray(width * height * 4) }; },
      };
    },
  };
}
const elements = new Map();
const context = vm.createContext({
  document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element, createTextNode: (textContent) => ({ textContent }),
    querySelectorAll: () => [], addEventListener() {},
  },
  window: { addEventListener() {} }, Intl, crypto: require("node:crypto").webcrypto,
  AbortSignal: { timeout() {} }, setTimeout() {}, clearTimeout() {},
  // Keep startup polling pending so it cannot mutate the benchmark fixture.
  fetch: () => new Promise(() => {}),
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../ui/app.js"), "utf8"), context);
vm.runInContext(`
  globalThis.frame = {
    firmware: { sha256: 'fixture' }, ui_initialized: true, processors: [],
    lcd: { width:128, height:128, pixels:Array.from({length:16384}, (_, i) => i % 4),
      known:Array(16384).fill(true), known_pixels:16384, display_on:true, live:true,
      version:1, error:null, palette:Array(8).fill(0), segment_zero_on_right:true }
  };
  globalThis.redraw = () => { frame.lcd.pixels[0] ^= 3; frame.lcd.version += 1; drawDisplay(frame); };
  globalThis.unchanged = () => drawDisplay(frame);
`, context);
const unchanged = vm.runInContext("unchanged", context);
const redraw = vm.runInContext("redraw", context);
function measure(callback, iterations) {
  for (let i = 0; i < 100; i += 1) callback();
  const durations = [];
  for (let n = 0; n < samples; n += 1) {
    const start = process.hrtime.bigint();
    for (let i = 0; i < iterations; i += 1) callback();
    durations.push(Number(process.hrtime.bigint() - start) / iterations / 1e6);
  }
  const ordered = [...durations].sort((a, b) => a - b);
  const middle = (samples - 1) / 2;
  return { median_ms: (ordered[Math.floor(middle)] + ordered[Math.ceil(middle)]) / 2,
    samples_ms: durations, iterations_per_sample: iterations };
}
redraw();
const before = paints;
unchanged();
assert.equal(paints, before);
redraw();
assert.equal(paints, before + 1);
console.log(JSON.stringify({ ui_unchanged: measure(unchanged, 1000), ui_redraw: measure(redraw, 100) }));
