// pdfsim.mjs - run a pdfcc PDF in Node against a mock of the PDF JavaScript API
// (app timers, getField, keystroke and mouse actions). Prints the terminal, and the
// display as ASCII with --display. It does not render the PDF; use tests/chrome.mjs
// for that.
//
//   node tests/pdfsim.mjs hello.pdf --type "50\n" --wait 500   (--paste: one change)
//   node tests/pdfsim.mjs hello.pdf --until "guess:" --type "50\n" --until "too"
//   node tests/pdfsim.mjs mandel.pdf --wait 2000 --display
//   node tests/pdfsim.mjs game.pdf --press "^" --wait 300 --click 3,4
import fs from "node:fs";
import vm from "node:vm";
import zlib from "node:zlib";

const args = process.argv.slice(2);
const file = args.shift();
const steps = [];
let showDisplay = false, quiet = false;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--type" || a === "--paste")
    steps.push([a.slice(2), args[++i].replace(/\\n/g, "\n").replace(/\\r/g, "\r").replace(/\\b/g, "\b")]);
  else if (a === "--wait") steps.push(["wait", +args[++i]]);
  else if (a === "--until") steps.push(["until", args[++i]]);
  else if (a === "--press") steps.push(["press", args[++i]]);
  else if (a === "--click") steps.push(["click", args[++i]]);
  else if (a === "--display") showDisplay = true;
  else if (a === "--quiet") quiet = true;
  else throw new Error("unknown option " + a);
}
if (!steps.some(s => s[0] === "wait" || s[0] === "until")) steps.push(["wait", 300]);

// ---- minimal parser for pdfcc's own PDFs (later object versions win) ----
const buf = fs.readFileSync(file);
const text = buf.toString("latin1");
const objs = {};
const re = /(\d+) 0 obj\n/g;
let m;
while ((m = re.exec(text))) {
  const start = m.index + m[0].length, num = +m[1];
  const end = text.indexOf("\nendobj", start);
  let body = text.slice(start, end), stream = null;
  const si = body.indexOf("\nstream\n");
  if (si >= 0) {
    const len = +/\/Length (\d+)/.exec(body)[1];
    const raw = buf.subarray(start + si + 8, start + si + 8 + len);
    stream = /FlateDecode/.test(body.slice(0, si)) ? zlib.inflateSync(raw) : raw;
    body = body.slice(0, si);
  }
  objs[num] = { body, stream };
  re.lastIndex = end;
}
const ref = (body, key) => { const r = new RegExp("/" + key + " (\\d+) 0 R").exec(body); return r ? +r[1] : null; };
const jsOf = num => objs[ref(objs[num].body, "JS")].stream.toString("latin1");
function chain(num) { const out = []; while (num) { out.push(jsOf(num)); num = ref(objs[num].body, "Next"); } return out; }
const fields = {};
for (const o of Object.values(objs)) {
  const t = /\/T \(([^)]*)\)/.exec(o.body);
  if (!t || !/\/Subtype \/Widget/.test(o.body)) continue;
  const aa = {};
  for (const k of ["K", "D", "U", "Fo", "Bl"]) { const r = new RegExp("/" + k + " (\\d+) 0 R").exec(o.body); if (r) aa[k] = +r[1]; }
  const ca = /\/CA \(([^)]*)\)/.exec(o.body);
  fields[t[1]] = { name: t[1], value: "", aa, caption: ca && ca[1] };
}
const pageObj = Object.values(objs).find(o => /\/Type \/Page\b/.test(o.body));
const openAction = +/\/AA <<\/O (\d+) 0 R/.exec(pageObj.body)[1];

// ---- mock viewer API, in a separate context (no Node globals: process, setTimeout...) ----
const out = console.log.bind(console);
const run = (code, filename) => vm.runInContext(code, ctx, filename ? { filename } : undefined);
const sandbox = {
  app: {
    viewerType: "pdfsim",
    setInterval: (expr, ms) => setInterval(() => run(expr), Math.max(1, ms)),
    setTimeOut: (expr, ms) => setTimeout(() => run(expr), Math.max(1, ms)),
    clearInterval: h => clearInterval(h), clearTimeOut: h => clearTimeout(h),
    alert: msg => out("[alert] " + msg), beep() {},
  },
  getField: name => fields[name] || null,
  print: () => { throw new Error("Document.print() was called"); },
  console: { log() {}, warn() {}, error() {} },
};
const ctx = vm.createContext(sandbox);
function runAction(num, event) {
  sandbox.event = event || {};
  for (const js of chain(num)) run(js);
}

for (const js of chain(openAction)) run(js, file);

// ---- input helpers ----
const kbd = fields.pdfcc_kbd;
function type(str) {
  if (!kbd) throw new Error("this PDF has no keyboard field");
  if (kbd.aa.Fo) runAction(kbd.aa.Fo);
  for (const ch of str) {
    const v = kbd.value, n = v.length;
    const ev = ch === "\n" ? { change: "", selStart: n, selEnd: n } :
               ch === "\b" ? { change: "", selStart: n - 1, selEnd: n } : { change: ch, selStart: n, selEnd: n };
    runAction(kbd.aa.K, Object.assign(ev, { value: v, willCommit: false }));
    kbd.value = ch === "\b" ? v.slice(0, -1) : v + (ch === "\n" ? "\r\n" : ch);
  }
}
function paste(str) { // the whole text as one keystroke event, like a paste
  if (kbd.aa.Fo) runAction(kbd.aa.Fo);
  const v = kbd.value, n = v.length;
  runAction(kbd.aa.K, { change: str, selStart: n, selEnd: n, value: v, willCommit: false });
  kbd.value = v + str;
}
function press(label) {
  const f = Object.values(fields).find(f => f.caption === label);
  if (!f) throw new Error("no button labelled " + label);
  runAction(f.aa.D, { targetName: f.name }); runAction(f.aa.U, { targetName: f.name });
}
function click(xy) {
  const [x, y] = xy.split(",");
  const f = fields[`pdfcc_grid_${x}_${y}`];
  runAction(f.aa.D, { targetName: f.name }); runAction(f.aa.U, { targetName: f.name });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const terminalText = () => Object.keys(fields).filter(n => n.startsWith("pdfcc_tty_"))
  .sort((a, b) => +a.split("_")[2] - +b.split("_")[2]).map(n => fields[n].value).join("\n");
async function until(text, timeout = 30000) { // wait for the terminal to show text
  for (const t0 = Date.now(); !terminalText().includes(text) && Date.now() - t0 < timeout;) await sleep(25);
}
for (const [kind, v] of steps) {
  if (kind === "type") type(v);
  else if (kind === "paste") paste(v);
  else if (kind === "press") press(v);
  else if (kind === "click") click(v);
  else if (kind === "until") await until(v);
  else await sleep(v);
}

// ---- output ----
const rows = Object.keys(fields).filter(n => n.startsWith("pdfcc_tty_"))
  .sort((a, b) => +a.split("_")[2] - +b.split("_")[2]).map(n => fields[n].value);
while (rows.length && !rows[rows.length - 1].trim()) rows.pop();
if (!quiet) out(rows.join("\n"));
if (showDisplay && sandbox.pdfcc.display) {
  const D = sandbox.pdfcc.display, shades = " .:-=+*#%@";
  const lumOf = {}; D.ramp.forEach(([c, l]) => (lumOf[c] = l));
  const sx = Math.max(1, Math.ceil(D.cols / 100)), sy = sx * 2;
  for (let y = 0; y < D.rows; y += sy) {
    let line = "";
    for (let x = 0; x < D.cols; x += sx) {
      let s = 0, n = 0;
      for (let dy = 0; dy < sy && y + dy < D.rows; dy++)
        for (let dx = 0; dx < sx; dx++) { const c = (fields[D.prefix + (y + dy)].value || "")[x + dx]; s += lumOf[c] ?? 255; n++; }
      line += shades[Math.min(9, Math.floor((255 - s / n) / 25.6))];
    }
    out(line);
  }
}
process.exit(0);
