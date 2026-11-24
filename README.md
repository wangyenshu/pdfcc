# pdfcc

Compiles C/C++ programs into PDF files that run in Chromium's PDF viewer (PDFium). Based on
[doompdf](https://github.com/ading2210/doompdf), which does this for Doom only.

```
bin/pdfcc hello.c -o hello.pdf
bin/pdfcc game.c -o game.pdf --display 160x100 --buttons arrows
bin/pdfcc main.c libfoo.a -o foo.pdf --memory 128    # prebuilt archives
bin/pdfcc prog.c --async -o prog.pdf                 # blocking stdin, sleep()
```

The output is one self-contained PDF. Tested in Chrome 153 (Linux).

## Setup

Linux, Python 3, git, Node.

```
./setup.sh           # Emscripten 1.39.20-fastcomp -> ./emsdk
./setup.sh --async   # also Emscripten 4.0.12 -> ./emsdk-upstream
```

| toolchain | output | required for |
|---|---|---|
| `fastcomp` (default) | asm.js | |
| `upstream` (`--toolchain upstream`) | wasm2js | `--async`, recent C/C++, ECL |

PDF viewers have no WebAssembly. Both outputs are plain JavaScript.

## Examples

| directory | shows | build |
|---|---|---|
| `examples/hello` | terminal, line input | `examples/build_all.sh` |
| `examples/mandelbrot` | display (`quality` mode), buttons | 〃 |
| `examples/snake` | `emscripten_set_main_loop`, palette framebuffer | 〃 |
| `examples/life` | click grid | 〃 |
| `examples/blocking` | unmodified blocking C (`fgets`, `scanf`, `sleep`) | 〃 (upstream toolchain) |
| `examples/lua` | Lua 5.4 interpreter, unmodified | `examples/lua/build.sh` |
| `examples/ecl` | ECL Common Lisp, built with its own build system | `examples/ecl/build.sh` (~20 min) |
| `examples/doom` | doomgeneric; empty-WAD variant | `examples/doom/build.sh [wad]` |

## Program structure

One of:

1. `pdf_run(frame, ms)`: `frame` is called every `ms` ms; `main` returns after setting it up.
2. `emscripten_set_main_loop`, as in other Emscripten programs.
3. `--async`: blocking code. `fgets`/`scanf`/`getchar`/`read` on stdin wait for input;
   `sleep`/`usleep`/`nanosleep` yield. Uses Asyncify: larger and slower code.

```c
#include "pdfcc.h"
static unsigned char fb[160 * 100];
static void frame(void) {
    pdf_event ev;
    while (pdf_poll_event(&ev))
        if (ev.type == PDF_EV_KEYDOWN && ev.key == PDF_KEY_LEFT) { /* ... */ }
    pdf_present(fb, 160, 100, PDF_GRAY8);
}
int main(void) { pdf_run(frame, 16); return 0; }
```

## Large programs

Build the project with its own build system and the same Emscripten, then link with pdfcc:

```
eval "$(bin/pdfcc --env --toolchain upstream)"   # emcc, emconfigure, emmake on PATH
emconfigure ./configure --host=wasm32-unknown-emscripten ...
emmake make
bin/pdfcc --toolchain upstream main.c -Iinclude lib/*.a -o prog.pdf \
    --memory 128 --memory-growth --stack 4096
```

`.o`/`.a` inputs and `-l`/`-L` flags are used for linking only. Programs that block on stdin
need `--async`, or a front end that feeds input from `pdf_run`.

`examples/ecl/build.sh` follows this pattern. It builds ECL with its own autoconf build, as in
ECL's INSTALL, but at `-O2` instead of `-O0`. It then links `libecl.a`, `libeclgc.a` and
`libeclgmp.a` with `repl.c`, which embeds ECL: `cl_boot`, then evaluate each typed form.
Result: 7.9 MB of JavaScript, 1.6 MB PDF, boot in 4.8 s in Chrome.

Constraints:

- C functions become JavaScript functions, so deep recursion is limited by V8's call stack,
  usually before the C stack is full. ECL's interpreter reaches it after about 530 nested
  calls (measured in Chrome and Node). The frame callback is then abandoned with
  `RangeError`, and the program stops. If the program registered
  `pdf_on_stack_overflow(handler)`, the C stack pointer is restored instead, and the handler
  resets the program's own state. The ECL front end does this.
- PDFium runs JavaScript without a JIT: about 40× slower than Node for the same code.
- `main` runs after the page is painted; loading the program's JavaScript happens before.

## C API (`runtime/pdfcc.h`)

| function | |
|---|---|
| `pdf_run(fn, ms)`, `pdf_stop()` | frame callback |
| `pdf_on_stack_overflow(fn)` | recover from a JavaScript stack overflow in the frame callback |
| `pdf_now()`, `pdf_ticks()` | ms since start |
| `pdf_sleep(ms)`, `pdf_yield()` | sleep/yield (`--async`; no-ops otherwise) |
| `pdf_display_width()`, `pdf_display_height()` | display size |
| `pdf_present(px, w, h, fmt)` | draw; `PDF_RGBA32`, `PDF_BGRA32`, `PDF_GRAY8`, `PDF_INDEX8`, `PDF_RGB565`; resampled to the display |
| `pdf_set_palette(rgb, n)` | palette for `PDF_INDEX8` |
| `pdf_poll_event(&ev)` | `KEYDOWN`/`KEYUP` (`ev.key`), `CLICK`/`RELEASE` (`ev.x`, `ev.y`), `LINE`, `BUTTON` (`ev.key` = id) |
| `pdf_key_down(key)` | key state |
| `pdf_read_line(buf, n)` | next typed line, or -1 |
| `pdf_term_*` | terminal size, clear, cursor, rows, echo |
| `pdf_alert`, `pdf_set_field`, `pdf_get_field`, `pdf_eval` | dialog, form fields, JavaScript |

Keys: ASCII, `PDF_KEY_UP/DOWN/LEFT/RIGHT/SHIFT/CTRL/ALT`, `PDF_KEY_F1`+n. stdout and stderr go
to the terminal (`\r \b \t`, ANSI cursor movement and erase). Embedded files: `fopen`.

## Page layout

Flags, or a JSON file passed with `--layout` (flags override it):

```json
{
  "title": "Snake", "subtitle": "...",
  "display":  {"width": 128, "height": 80, "scale": 4.0, "pixel_aspect": 1.0,
               "mode": "fast", "dither": true, "gamma": 1.0},
  "terminal": {"cols": 52, "rows": 6, "font_size": 7, "theme": "light", "echo": false},
  "keyboard": {"placeholder": "Click here, then type"},
  "buttons":  [{"label": "^", "key": "UP", "col": 1, "row": 0},
               {"label": "step", "id": 2, "col": 0, "row": 2, "w": 2}],
  "click_grid": {"cols": 32, "rows": 20},
  "help": ["..."], "footer": ["..."], "args": ["-v"],
  "files": [{"src": "level1.txt", "path": "/data/level1.txt"}],
  "slots": [{"name": "pwad", "path": "/pwad.wad", "args": ["-file", "/pwad.wad"]}]
}
```

Layout flags: `--title`, `--subtitle`, `--display WxH`, `--scale`, `--quality`,
`--terminal CxR`, `--no-terminal`, `--dark`, `--no-keyboard`, `--buttons arrows|gamepad|JSON`,
`--click-grid CxR`, `--help-line`, `--arg`, `--file SRC[:/PATH]`, `--slot NAME[:/PATH[:ARGS]]`.
Build flags: `--toolchain`, `--async`, `--memory MB`, `--memory-growth`, `--stack KB`,
`--keep-js`, `--env`. Other arguments go to emcc. With `-o x.js` only the JavaScript is
written; `tools/mkpdf.py x.js -o x.pdf` packages it.

Display modes, full 240×150 redraw in Chrome:

| mode | fields | darkest level | redraw |
|---|---|---|---|
| `fast` (default) | plain text, Courier-Bold | 99/255 | ~80 ms |
| `quality` | comb, glyphs at 1.7× cell width | 31/255 | ~190 ms |

## Files and slots

Each `--file` and `--slot` is a separate JavaScript stream in the PDF. A slot is empty until
filled; its `args` are added to `argv` only when it is filled. To fill or replace one:

```
tools/inject.py doom_nowad.pdf --list
tools/inject.py doom_nowad.pdf -o doom.pdf --file iwad=doom1.wad
```

`web/index.html` does the same in a browser. Both append an incremental PDF update.

## Implementation

- Display: one read-only text field per row, one character per pixel. Glyphs come from a
  brightness ramp measured in Chrome (`tests/measure_ramp.py`), with 4×4 ordered dithering.
  Only changed rows are rewritten.
- Terminal: one field per row. Keyboard: a multiline field whose keystroke action reports
  each change. Buttons: push buttons with mouse-down/up actions.
- JavaScript: the page-open action runs a chain of Flate-compressed streams: runtime, files,
  program, start.
- Runtime (`runtime/pdfcc_runtime.js`, `runtime/pdfcc.c`): `setTimeout`/`setInterval`/
  `performance` on top of `app.setTimeOut`; stdin/stdout devices; base64 file loading;
  error reporting to the terminal. The PDF global `print` (the document's print method) is
  not used as `console.log`.

## Testing

- `tests/pdfsim.mjs`: runs a PDF in Node against a mock of the PDF JavaScript API and prints
  the terminal (and the display with `--display`). Input: `--type` (keystrokes), `--paste`
  (one change), `--press`, `--click`, `--wait`.
- `tests/run_tests.sh`: checks the built examples with pdfsim.
- `tests/chrome.mjs`: drives Chrome's PDF viewer (`cd tests && npm install`).
- `tests/measure_ramp.py fast|quality`: re-measures the display ramps.

## Limitations

- Tested only in Chrome. doompdf reports that its PDFs work only in Chromium-based browsers;
  pdfcc uses the same viewer features.
- Grayscale only. No sound. No mouse position; use buttons or the click grid.
- Keyboard input requires focus on the keyboard box. Arrow keys move the box's caret and are
  not delivered. A typed key is reported as a press and a release one frame later.
- PDFium returns numeric-looking field values as numbers.

## License

GPL v2, as doompdf. The Doom example uses doompdf's doomgeneric (GPL v2). Lua (MIT), ECL
(LGPL 2.1+) and Freedoom (BSD) are downloaded by the build scripts.
