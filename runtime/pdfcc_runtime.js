// pdfcc_runtime.js - runs inside the PDF viewer's JavaScript engine, before the
// Emscripten output. It connects Emscripten's I/O to the form fields that
// mkpdf.py (or tex/pdfcc.sty) laid out. Config comes from PDFCC_CONFIG.
// Everything public lives on one global object, named by C.name ("pdfcc"
// unless the program was built with --name), because PDF timers and field
// actions can only call global expressions. Several programs can run in one
// document: each has its own object, fields (C.*.prefix) and Emscripten code,
// which P.load runs in a function scope of its own.
//
// Action order: PDFCC_CONFIG, this script, files (addFile), program (load),
// start. pdfcc.sty runs that sequence on every page that shows the program;
// after the first time, each step returns at once (only start and this
// script's first lines run).
/* global console */
(function () {
  var C = PDFCC_CONFIG;
  var NAME = C.name || "pdfcc";
  var old = globalThis[NAME];
  if (old && old.config) { globalThis.pdfccCurrent = old; return; } // already set up
  var P = { config: C, name: NAME, files: [], args: (C.args || []).slice(), keyState: {}, echo: false };
  var t0 = Date.now();
  globalThis[NAME] = P;
  // Instance-independent entry points for program and file scripts that are
  // shared by several instances (pdfcc.sty): they act on the instance whose
  // config ran last.
  globalThis.pdfccCurrent = P;
  globalThis.pdfccLoad = function (body) { globalThis.pdfccCurrent.load(body); };
  globalThis.pdfccAddFile = function (path, b64, extraArgs) { globalThis.pdfccCurrent.addFile(path, b64, extraArgs); };
  globalThis.pdfccArgs = function (args) { globalThis.pdfccCurrent.defaultArgs(args); };

  // The program's own variables (heap views, FS, exports). P.load replaces these
  // with functions that read them in the program's scope; these read globals.
  var X = {
    heapU8: function () { return HEAPU8; },
    heap32: function () { return HEAP32; },
    fs: function () { return typeof FS !== "undefined" ? FS : undefined; },
    stackSave: function () { return typeof stackSave === "function" ? stackSave() : null; },
    stackRestore: function (sp) { stackRestore(sp); },
    tick: function () { _pdfcc_tick(); },
    overflow: function () { _pdfcc_stack_overflow(); },
    callMain: function (args) {
      if (typeof callMain === "function") callMain(args); else P.Module.callMain(args);
    }
  };

  // ---------------------------------------------------------- polyfills --
  // PDF JavaScript has app.setTimeOut/app.setInterval (taking code strings,
  // minimum 1 ms) but no setTimeout, performance or a safe console. Emscripten
  // needs them for emscripten_set_main_loop, emscripten_sleep and timing.
  var timers = {}, nextTimer = 1;
  P._fire = function (id) {
    var t = timers[id];
    if (!t) return;
    if (!t.repeat) delete timers[id];
    P.guard(function () { t.fn.apply(null, t.args); });
    P.flush();
  };
  function addTimer(fn, ms, args, repeat) {
    var id = nextTimer++;
    if (typeof fn !== "function") { var src = String(fn); fn = function () { eval(src); }; }
    timers[id] = { fn: fn, args: args, repeat: repeat };
    var expr = NAME + "._fire(" + id + ")";
    ms = Math.max(1, ms | 0);
    timers[id].h = repeat ? app.setInterval(expr, ms) : app.setTimeOut(expr, ms);
    return id;
  }
  function clearTimer(id) {
    var t = timers[id];
    if (!t) return;
    try { if (t.repeat) app.clearInterval(t.h); else app.clearTimeOut(t.h); } catch { /* already fired */ }
    delete timers[id];
  }
  // Each program gets these through P.load; the globals are for code outside
  // (with several programs, they belong to the last one loaded).
  P.setTimeout = function (fn, ms) { return addTimer(fn, ms, [].slice.call(arguments, 2), false); };
  P.setInterval = function (fn, ms) { return addTimer(fn, ms, [].slice.call(arguments, 2), true); };
  P.clearTimeout = P.clearInterval = clearTimer;
  globalThis.setTimeout = P.setTimeout;
  globalThis.setInterval = P.setInterval;
  globalThis.clearTimeout = globalThis.clearInterval = clearTimer;
  if (typeof performance === "undefined")
    globalThis.performance = { now: function () { return Date.now() - t0; } };
  P.now = function () { return Date.now() - t0; };
  // In PDF JS the global `print` is Document.print() (opens the print
  // dialog!) and Emscripten's shell setup wires console.log to it. We point
  // console at the terminal instead (again after the Emscripten code ran).
  P.log = function () { P.termWrite([].join.call(arguments, " ") + "\n"); };
  P.console = {};
  P.fixConsole = function () {
    var c = { log: P.log, info: P.log, warn: P.log, error: P.log, debug: function () {} }, k;
    for (k in c) P.console[k] = c[k];
    try { globalThis.console = P.console; } catch { /* read-only global */ }
    try { if (typeof console === "object") for (k in c) console[k] = c[k]; } catch { /* frozen */ }
  };
  P.fixConsole();

  // ----------------------------------------------------------- terminal --
  // A small VT100-ish terminal drawn into one text field per row.
  var T = C.terminal ? {
    cols: C.terminal.cols, rows: C.terminal.rows, prefix: C.terminal.prefix,
    lines: [], dirty: [], cx: 0, cy: 0, esc: null, utf8: 0, utf8n: 0
  } : null;
  P.term = T;
  if (T) {
    for (var r = 0; r < T.rows; r++) { T.lines.push(blankLine()); T.dirty.push(true); }
    P.echo = C.terminal.echo !== undefined ? !!C.terminal.echo : !C.display;
  }
  function blankLine() { var a = new Array(T.cols); for (var i = 0; i < T.cols; i++) a[i] = " "; return a; }
  function scroll() { T.lines.shift(); T.lines.push(blankLine()); for (var r = 0; r < T.rows; r++) T.dirty[r] = true; }
  function newline() { T.cx = 0; if (++T.cy >= T.rows) { T.cy = T.rows - 1; scroll(); } }
  function putc(ch) {
    if (T.cx >= T.cols) newline();
    T.lines[T.cy][T.cx++] = ch;
    T.dirty[T.cy] = true;
  }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function csi(seq) { // seq: parameters + final byte, e.g. "2J", "10;5H"
    var fin = seq.charAt(seq.length - 1), body = seq.slice(0, -1).replace(/^\?/, "");
    var ps = body === "" ? [] : body.split(";").map(function (x) { return parseInt(x, 10) || 0; });
    var n = ps[0] || 1, r, c;
    switch (fin) {
      case "A": T.cy = clamp(T.cy - n, 0, T.rows - 1); break;
      case "B": T.cy = clamp(T.cy + n, 0, T.rows - 1); break;
      case "C": T.cx = clamp(T.cx + n, 0, T.cols - 1); break;
      case "D": T.cx = clamp(T.cx - n, 0, T.cols - 1); break;
      case "G": T.cx = clamp(n - 1, 0, T.cols - 1); break;
      case "d": T.cy = clamp(n - 1, 0, T.rows - 1); break;
      case "H": case "f":
        T.cy = clamp((ps[0] || 1) - 1, 0, T.rows - 1); T.cx = clamp((ps[1] || 1) - 1, 0, T.cols - 1); break;
      case "J":
        var mode = ps[0] || 0;
        for (r = 0; r < T.rows; r++) {
          if (mode === 0 && r < T.cy || mode === 1 && r > T.cy) continue;
          for (c = 0; c < T.cols; c++) {
            if (r === T.cy && (mode === 0 && c < T.cx || mode === 1 && c > T.cx)) continue;
            T.lines[r][c] = " ";
          }
          T.dirty[r] = true;
        }
        if (mode === 2) { T.cx = 0; T.cy = 0; }
        break;
      case "K":
        var m = ps[0] || 0;
        for (c = 0; c < T.cols; c++)
          if (m === 2 || m === 0 && c >= T.cx || m === 1 && c <= T.cx) T.lines[T.cy][c] = " ";
        T.dirty[T.cy] = true;
        break;
      default: break; // colors (m), modes (h/l) etc. are ignored
    }
  }
  function termChar(ch) {
    if (T.esc !== null) {
      if (T.esc === "(") { T.esc = null; return; }             // ESC ( X: charset, ignored
      if (T.esc === "") { if (ch === "(" || ch === ")") T.esc = "("; else if (ch !== "[") T.esc = null;
                          if (ch !== "[") return; }             // other ESC x: ignored
      T.esc += ch;
      if (T.esc.length > 1 && /[@-~]/.test(ch)) { csi(T.esc.slice(1)); T.esc = null; }
      else if (T.esc.length > 24) T.esc = null;
      return;
    }
    switch (ch) {
      case "\n": newline(); break;
      case "\r": T.cx = 0; break;
      case "\b": if (T.cx > 0) T.cx--; break;
      case "\t": do putc(" "); while (T.cx % 8 && T.cx < T.cols); break;
      case "\x1b": T.esc = ""; break;
      case "\x07": break;
      default: if (ch >= " ") putc(ch);
    }
  }
  // Byte-level entry point (stdout/stderr), with UTF-8 decoding.
  P.termByte = function (b) {
    if (!T) return;
    if (b < 0) b += 256;
    if (T.utf8n) {
      T.utf8 = (T.utf8 << 6) | (b & 63);
      if (--T.utf8n === 0) termChar(T.utf8 < 256 ? String.fromCharCode(T.utf8) : "?");
      return;
    }
    if (b >= 0xf0) { T.utf8 = b & 7; T.utf8n = 3; }
    else if (b >= 0xe0) { T.utf8 = b & 15; T.utf8n = 2; }
    else if (b >= 0xc0) { T.utf8 = b & 31; T.utf8n = 1; }
    else termChar(String.fromCharCode(b));
  };
  P.termWrite = function (s) {
    if (!T) return;
    for (var i = 0; i < s.length; i++) termChar(s.charAt(i));
  };
  P.termClear = function () { termChar("\x1b"); termChar("["); termChar("2"); termChar("J"); };
  P.termGoto = function (r, c) { T.cy = clamp(r, 0, T.rows - 1); T.cx = clamp(c, 0, T.cols - 1); };
  P.termSetRow = function (r, s) {
    if (!T || r < 0 || r >= T.rows) return;
    var line = blankLine();
    for (var i = 0; i < s.length && i < T.cols; i++) line[i] = s.charAt(i);
    T.lines[r] = line; T.dirty[r] = true;
  };
  var lastCursorRow = -1;
  P.flush = function () { // repaint dirty terminal rows
    if (!T) return;
    var showCursor = P.echo && T.esc === null;
    if (lastCursorRow !== T.cy) { if (lastCursorRow >= 0) T.dirty[lastCursorRow] = true; T.dirty[T.cy] = true; }
    for (var r = 0; r < T.rows; r++) {
      if (!T.dirty[r]) continue;
      var line = T.lines[r];
      if (showCursor && r === T.cy) { line = line.slice(); if (T.cx < T.cols) line[T.cx] = "_"; }
      setField(T.prefix + r, line.join("").replace(/\s+$/, ""));
      T.dirty[r] = false;
    }
    lastCursorRow = showCursor ? T.cy : -1;
  };

  var fieldCache = {};
  function setField(name, value) {
    var f = fieldCache[name] || (fieldCache[name] = getField(name));
    if (f) f.value = value;
  }
  P.setField = setField;

  // ------------------------------------------------------------ display --
  // One text field per pixel row; each character is one pixel and its glyph
  // sets the shade. Ramps: glyphs light -> dark, with the mean brightness each
  // produces in Chrome's PDF renderer (measured with tests/measure_ramp.py).
  // Both use Courier-Bold, so every glyph has the same width.
  //  fast:    plain text fields, glyph advance = pixel width. ~80 ms per 240x150 frame.
  //  quality: comb fields (one cell per character) with glyphs drawn 1.7x larger than
  //           the cell, so they overlap into near-solid black. ~3x the contrast,
  //           but PDFium needs ~2.4x longer to redraw them.
  var RAMPS = {
    fast: [[" ", 255], ["_", 245], [".", 241], [",", 235], [":", 226], [";", 217], ["~", 215],
           ["\"", 210], ["!", 201], ["*", 195], [")", 187], ["=", 180], ["j", 174], ["r", 166],
           ["t", 159], ["z", 153], ["I", 146], ["%", 140], ["C", 133], ["d", 126], ["U", 119],
           ["K", 114], ["W", 106], ["B", 99]],
    quality: [[" ", 255], ["'", 235], ["\"", 216], [",", 215], [".", 212], [";", 206], [":", 204],
              ["-", 187], ["^", 178], ["!", 168], ["~", 154], ["(", 148], ["T", 140], ["7", 127],
              ["l", 123], ["i", 108], ["F", 99], ["2", 88], ["q", 80], ["#", 69], ["V", 60],
              ["w", 49], ["K", 39], ["W", 31]]
  };
  var D = C.display ? {
    cols: C.display.cols, rows: C.display.rows, prefix: C.display.prefix,
    ramp: C.display.ramp || RAMPS[C.display.mode === "quality" ? "quality" : "fast"],
    dither: C.display.dither !== false,
    prev: [], lum: new Uint8Array(C.display.cols * C.display.rows), pal: new Uint8Array(256)
  } : null;
  P.display = D;
  if (D) {
    // lookup: input luminance (0..255) -> ramp index + dither fraction (0..16)
    D.tblIdx = new Uint8Array(256); D.tblFrac = new Uint8Array(256);
    var lums = D.ramp.map(function (e) { return e[1]; });
    var lo = lums[lums.length - 1], hi = lums[0], gamma = C.display.gamma || 1;
    for (var v = 0; v < 256; v++) {
      var t = lo + (hi - lo) * Math.pow(v / 255, gamma), i = 0;
      while (i < lums.length - 2 && lums[i + 1] >= t) i++;
      D.tblIdx[v] = i;
      D.tblFrac[v] = Math.round(clamp((lums[i] - t) / (lums[i] - lums[i + 1]), 0, 1) * 16);
    }
    D.chars = D.ramp.map(function (e) { return e[0]; });
    for (var p = 0; p < 256; p++) D.pal[p] = p;
    // ordered dithering (4x4 Bayer) thresholds 0..15
    D.bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  }
  P.setPalette = function (ptr, n) {
    for (var i = 0; i < n && i < 256; i++) {
      var H8 = X.heapU8(), r = H8[ptr + i * 3], g = H8[ptr + i * 3 + 1], b = H8[ptr + i * 3 + 2];
      D.pal[i] = (r * 77 + g * 150 + b * 29) >> 8;
    }
  };
  // Convert any pixel format to the display's luminance grid (nearest neighbour).
  P.present = function (ptr, w, h, fmt) {
    if (!D) return;
    var cols = D.cols, rows = D.rows, lum = D.lum, H8 = X.heapU8(), pal = D.pal;
    var xs = new Int32Array(cols);
    for (var x = 0; x < cols; x++) xs[x] = Math.floor((x + 0.5) * w / cols);
    for (var y = 0; y < rows; y++) {
      var sy = Math.floor((y + 0.5) * h / rows), o = y * cols;
      if (fmt === 0 || fmt === 1) {
        var base = ptr + sy * w * 4, ri = fmt === 0 ? 0 : 2, bi = 2 - ri;
        for (x = 0; x < cols; x++) {
          var q = base + xs[x] * 4;
          lum[o + x] = (H8[q + ri] * 77 + H8[q + 1] * 150 + H8[q + bi] * 29) >> 8;
        }
      } else if (fmt === 2) {
        for (x = 0; x < cols; x++) lum[o + x] = H8[ptr + sy * w + xs[x]];
      } else if (fmt === 3) {
        for (x = 0; x < cols; x++) lum[o + x] = pal[H8[ptr + sy * w + xs[x]]];
      } else if (fmt === 4) {
        for (x = 0; x < cols; x++) {
          var a = ptr + (sy * w + xs[x]) * 2, px = H8[a] | (H8[a + 1] << 8);
          lum[o + x] = (((px >> 11) & 31) * 627 + ((px >> 5) & 63) * 599 + (px & 31) * 237) >> 8;
        }
      }
    }
    P.presentLum(lum);
  };
  P.presentLum = function (lum) {
    var cols = D.cols, rows = D.rows, chars = D.chars, ti = D.tblIdx, tf = D.tblFrac;
    var bayer = D.bayer, row = new Array(cols);
    for (var y = 0; y < rows; y++) {
      var o = y * cols, by = (y & 3) * 4;
      for (var x = 0; x < cols; x++) {
        var v = lum[o + x];
        row[x] = chars[ti[v] + (D.dither ? (tf[v] > bayer[by + (x & 3)] ? 1 : 0) : (tf[v] >= 8 ? 1 : 0))];
      }
      var s = row.join("");
      if (s !== D.prev[y]) { D.prev[y] = s; setField(D.prefix + y, s); }
    }
  };

  // -------------------------------------------------------------- input --
  // Events: [type, key, x, y, frame]. Typed keys get a KEYUP one frame later
  // so programs that sample key state still see them.
  var events = [], frame = 0;
  P.frame = function () { return frame; };
  function pushEvent(type, key, x, y, delay) {
    if (events.length > 512) events.splice(0, 256);
    events.push([type, key, x | 0, y | 0, frame + (delay || 0)]);
    if (!delay) {
      if (type === 1) P.keyState[key] = 1; else if (type === 2) P.keyState[key] = 0;
    }
  }
  P.pollEvent = function (ptr) {
    if (!events.length || events[0][4] > frame) return 0;
    var e = events.shift(), H32 = X.heap32();
    H32[ptr >> 2] = e[0]; H32[(ptr >> 2) + 1] = e[1];
    H32[(ptr >> 2) + 2] = e[2]; H32[(ptr >> 2) + 3] = e[3];
    return 1;
  };
  P.frameEnd = function () {
    frame++;
    for (var i = 0; i < events.length; i++)
      if (events[i][4] === frame && events[i][0] === 2) P.keyState[events[i][1]] = 0;
    P.flush();
  };
  function utf8bytes(s) {
    var b = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0xd800 && c < 0xdc00 && i + 1 < s.length) { // surrogate pair
        var d = s.charCodeAt(i + 1);
        if (d >= 0xdc00 && d < 0xe000) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) b.push(c);
      else if (c < 0x800) b.push(0xc0 | c >> 6, 0x80 | c & 63);
      else if (c < 0x10000) b.push(0xe0 | c >> 12, 0x80 | c >> 6 & 63, 0x80 | c & 63);
      else b.push(0xf0 | c >> 18, 0x80 | c >> 12 & 63, 0x80 | c >> 6 & 63, 0x80 | c & 63);
    }
    return b;
  }
  // Entered lines, as UTF-8 bytes ending in "\n". stdin reads them byte by byte
  // (inPos = bytes of lines[0] already read); pdf_read_line takes the rest of lines[0].
  var lines = [], inPos = 0, inEof = false, lineBuf = [];
  var MAX_LINES = 256, MAX_LINE = 8192;
  function enterLine(s) {
    if (lines.length >= MAX_LINES) { lines.shift(); inPos = 0; }
    lines.push(utf8bytes(s + "\n"));
    pushEvent(5, 0, 0, 0, 0);
  }
  // A key typed into the keyboard field (code: char code or PDF_KEY_*).
  P.typed = function (code) {
    pushEvent(1, code, 0, 0, 0);
    pushEvent(2, code, 0, 0, 1);
    if (code === 8) {
      if (lineBuf.length) { lineBuf.pop(); if (P.echo && T) { termChar("\b"); putc(" "); termChar("\b"); } }
    } else if (code === 13) {
      if (P.echo && T) newline();
      enterLine(lineBuf.join(""));
      lineBuf = [];
    } else if (code === 4) { // Ctrl-D: end the current line, or end of input if it is empty
      if (lineBuf.length) { enterLine(lineBuf.join("")); lineBuf = []; } else inEof = true;
    } else if (code >= 32 && code < 0x100) {
      addText(String.fromCharCode(code));
    }
    P.flush();
  };
  function addText(ch) { // to the line being typed
    if (lineBuf.length >= MAX_LINE) return;
    lineBuf.push(ch);
    if (P.echo && T) termChar(ch);
  }
  // K (keystroke) action of the multiline keyboard field. Enter arrives as an
  // empty change with no selection; Backspace as an empty change replacing a
  // selection of one character. Pasted text arrives as one change.
  var kbdSetting = 0;    // time of our own last change to the field's value
  function setKbd(v) { kbdSetting = Date.now(); setField(C.keyboard.field, v); }
  P._key = function (ev) {
    if (ev.willCommit) return;
    // setting the value ourselves (on focus) can fire a stray empty keystroke
    if (ev.change === "" && ev.selStart === ev.selEnd && Date.now() - kbdSetting < 100 &&
        String(ev.value) === "") return;
    var ch = String(ev.change);
    P.guard(function () {
      if (ch === "") P.typed(ev.selEnd > ev.selStart ? 8 : 13);
      else for (var i = 0; i < ch.length; i++) {
        var c = ch.charCodeAt(i);
        if (c === 10 && i > 0 && ch.charCodeAt(i - 1) === 13) continue; // CR LF
        if (c >= 0x100) { addText(ch.charAt(i)); P.flush(); continue; } // text only: codes
        P.typed(c === 10 || c === 13 ? 13 : c);                        // >= 0x100 are PDF_KEY_*
      }
    });
  };
  P._kbdFocus = function (on) { // focus/blur actions: placeholder only while unfocused
    setKbd(on ? "" : C.keyboard.placeholder || "");
  };
  P._button = function (code, down, isId) {
    P.guard(function () {
      if (isId) { if (down) pushEvent(6, code, 0, 0, 0); }
      else pushEvent(down ? 1 : 2, code, 0, 0, 0);
    });
  };
  P._gridClick = function (ev, down) { // field names are pdfcc_grid_<x>_<y>
    var name = String(ev.targetName || (ev.target && ev.target.name) || "");
    var m = /_(\d+)_(\d+)$/.exec(name);
    if (m) P._click(+m[1], +m[2], down);
  };
  P._click = function (x, y, down) {
    P.guard(function () { pushEvent(down ? 3 : 4, 0, x, y, 0); });
  };
  // pdf_read_line: copy the next line (or its unread rest) without "\n", NUL
  // terminated; truncated to size-1 bytes at a character boundary. Returns the
  // number of bytes stored, or -1 if no line is ready.
  P.readLine = function (ptr, size) {
    if (!lines.length || size < 1) return -1;
    var b = lines.shift(), start = inPos, end = b.length - 1, n = Math.min(end - start, size - 1);
    inPos = 0;
    while (n > 0 && start + n < end && (b[start + n] & 0xc0) === 0x80) n--;
    var H8 = X.heapU8();
    for (var i = 0; i < n; i++) H8[ptr + i] = b[start + i];
    H8[ptr + n] = 0;
    return n;
  };
  // stdin device: a byte, undefined = no data yet (EAGAIN), null = end of input
  function stdinChar() {
    if (!lines.length) { if (inEof) { inEof = false; return null; } return undefined; }
    var b = lines[0], c = b[inPos++];
    if (inPos >= b.length) { lines.shift(); inPos = 0; }
    return c;
  }

  // -------------------------------------------------------------- files --
  var B64 = new Uint8Array(128);
  (function () {
    var abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (var i = 0; i < 64; i++) B64[abc.charCodeAt(i)] = i;
    B64[45] = 62; B64[95] = 63; // url-safe variants
  })();
  P.b64decode = function (s) {
    var n = s.length;
    while (n && s.charCodeAt(n - 1) === 61) n--;
    var out = new Uint8Array((n * 3) >> 2), j = 0, i = 0;
    for (; i + 4 <= n; i += 4) {
      var v = (B64[s.charCodeAt(i)] << 18) | (B64[s.charCodeAt(i + 1)] << 12) |
              (B64[s.charCodeAt(i + 2)] << 6) | B64[s.charCodeAt(i + 3)];
      out[j++] = v >> 16; out[j++] = (v >> 8) & 255; out[j++] = v & 255;
    }
    if (n - i === 2) out[j] = (B64[s.charCodeAt(i)] << 2) | (B64[s.charCodeAt(i + 1)] >> 4);
    else if (n - i === 3) {
      var w = (B64[s.charCodeAt(i)] << 10) | (B64[s.charCodeAt(i + 1)] << 4) | (B64[s.charCodeAt(i + 2)] >> 2);
      out[j] = w >> 8; out[j + 1] = w & 255;
    }
    return out;
  };
  // Called by the file actions that follow this script. Empty data = an
  // unfilled slot (see tools/inject.py), which is skipped.
  P.addFile = function (path, b64, extraArgs) {
    if (!b64 || P.loaded) return;
    P.files.push({ path: path, b64: b64 });
    if (extraArgs) P.args = P.args.concat(extraArgs);
  };
  function writeFiles() {
    var FS = X.fs();
    P.files.forEach(function (f) {
      var slash = f.path.lastIndexOf("/");
      if (slash > 0) try { FS.mkdirTree(f.path.slice(0, slash)); } catch { /* exists */ }
      FS.writeFile(f.path, P.b64decode(f.b64));
      f.b64 = null;
    });
  }

  // ---------------------------------------------------------- lifecycle --
  var loop = null;
  P.startLoop = function (ms) {
    P.stopLoop();
    loop = app.setInterval(NAME + "._tick()", Math.max(0, ms | 0));
  };
  P.stopLoop = function () { if (loop) { try { app.clearInterval(loop); } catch { /* gone */ } loop = null; } };
  P._tick = function () {
    var sp = X.stackSave();
    try { X.tick(); }
    catch (e) {
      if (P.recoverOverflow && e instanceof RangeError && /call stack/i.test(e.message) && sp !== null) {
        X.stackRestore(sp); // the abandoned C frames never popped their stack space
        P.guard(function () { X.overflow(); });
      } else P.guard(function () { throw e; });
    }
    P.frameEnd();
  };
  P.exited = false;
  P.guard = function (fn) {
    try { fn(); }
    catch (e) {
      if (e && e.name === "ExitStatus") {
        P.exited = true; P.stopLoop();
        if (e.status) P.termWrite("\n[program exited with status " + e.status + "]\n");
      } else if (e === "unwind" || e === "SimulateInfiniteLoop") {
        // emscripten_set_main_loop(..., 1): main() "returns" into the loop
      } else {
        P.stopLoop();
        var msg = "pdfcc: " + (e && e.stack ? e.stack : e);
        if (T) P.termWrite("\n" + msg + "\n"); else app.alert(msg);
      }
    }
    P.flush();
  };

  // Emscripten Module configuration
  // Placeholder of the keyboard field: from the config (mkpdf.py) or the
  // field's initial value (pdfcc.sty).
  if (C.keyboard && C.keyboard.placeholder === undefined) {
    try { var kf = getField(C.keyboard.field); C.keyboard.placeholder = kf ? String(kf.value) : ""; }
    catch { C.keyboard.placeholder = ""; }
  }

  P.Module = {
    noInitialRun: true,
    print: function (s) { P.termWrite(s + "\n"); },
    printErr: function (s) { P.termWrite(s + "\n"); },
    stdin: stdinChar,
    stdout: P.termByte,
    stderr: P.termByte,
    preRun: [writeFiles],
    onRuntimeInitialized: function () { P.ready = true; if (P.wantStart) app.setTimeOut(NAME + "._go()", 50); },
    preMainLoop: function () {},
    postMainLoop: function () { P.frameEnd(); },
    onAbort: function (what) { P.termWrite("\n[abort] " + what + "\n"); P.flush(); }
  };
  if (NAME === "pdfcc") globalThis.Module = P.Module; // for code that expects the usual global

  // Runs the Emscripten output, which mkpdf.py wraps as
  //   NAME.load(function (pdfcc, Module, setTimeout, ..., print, printErr) { ... });
  // Inside, `pdfcc` is this object and the timers and console are this program's.
  // print is undefined there: in PDF JS the global print() opens the print dialog.
  // The wrapper's first statement passes the program's variables to bind().
  P.load = function (body) {
    if (P.loaded) return;
    P.loaded = true;
    try {
      body.call(globalThis, P, P.Module, P.setTimeout, P.setInterval, P.clearTimeout, P.clearInterval,
                P.console);
    } catch (e) { P.guard(function () { throw e; }); }
  };
  P.bind = function (x) { for (var k in x) X[k] = x[k]; };
  // argv from the program script, unless the config has its own
  P.defaultArgs = function (args) {
    if (!P.loaded && !C.args) P.args = args.concat(P.args);
  };

  // Called by the last action, after the Emscripten code. Starts main() as
  // soon as the runtime is ready (immediately with fastcomp/asm.js).
  // main() is started from a timer so the viewer paints the page first.
  var starting = false; // "Starting..." shown (only on an untouched terminal)
  // loadPage: set by pdfcc.sty (load=first) on pages that do not load the program
  P.start = function (loadPage) {
    if (!P.loaded) {
      if (loadPage && T && !P.hinted) {
        P.hinted = true;
        P.termWrite("[The program starts when page " + loadPage + " is shown.]\n");
        P.flush();
      }
      return;
    }
    if (P.wantStart) return;
    P.wantStart = true;
    if (P.hinted) { P.hinted = false; P.termClear(); }
    if (T && T.cx === 0 && T.cy === 0 && !T.lines[0].join("").trim()) {
      starting = true; P.termSetRow(0, "Starting..."); T.cx = 11; P.flush();
    }
    if (P.ready || P.Module.calledRun || !X.fs()) // (no FS: plain JS program)
      app.setTimeOut(NAME + "._go()", 50);
  };
  P._go = function () {
    if (P.started) return;
    P.started = true;
    if (starting) { P.termSetRow(0, ""); T.cx = 0; }
    P.fixConsole();
    if (C.keyboard) setField(C.keyboard.field, C.keyboard.placeholder || "");
    P.guard(function () { X.callMain(P.args); });
    P.flush();
  };
})();
