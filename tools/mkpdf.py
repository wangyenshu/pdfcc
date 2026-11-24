#!/usr/bin/env python3
"""mkpdf.py - package Emscripten output (asm.js or wasm2js) as a PDF.

    mkpdf.py program.js -o out.pdf [--layout layout.json] [options]

The page is built from a layout (JSON file and/or command-line options):

    {
      "title": "My program",            "subtitle": "one line under the title",
      "display":  {"width": 160, "height": 100, "scale": 3, "pixel_aspect": 1.0,
                   "mode": "fast"|"quality", "dither": true, "gamma": 1.0},
      "terminal": {"cols": 80, "rows": 24, "font_size": 8, "theme": "light"|"dark",
                   "echo": true},
      "keyboard": true | false | {"placeholder": "Click here, then type"},
      "buttons":  "arrows" | "gamepad" | [{"label": "^", "key": "UP", "col": 1, "row": 0,
                                           "w": 1, "h": 1}, {"label": "Go", "id": 7, ...}],
      "click_grid": {"cols": 8, "rows": 8},
      "help": ["lines shown under the controls"], "footer": ["lines at the bottom"],
      "args": ["argv", "for", "main"],
      "files": [{"src": "local/file", "path": "/in/the/fs"}],
      "slots": [{"name": "iwad", "path": "/doom1.wad", "args": []}]
    }

Each file is base64 in its own JavaScript action; tools/inject.py can replace it or
fill an empty slot later.
"""
import argparse
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdfwriter import PDF, Name, Stream, content_string  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_JS = os.path.join(HERE, "..", "runtime", "pdfcc_runtime.js")

# Glyph ramps for the display, light -> dark, with the mean brightness each glyph
# produces in Chrome's PDF renderer (measured from screenshots at 100%
# zoom with tests/measure_ramp.py). Both use Courier-Bold, so every glyph has the same width.
#  fast:    plain text fields, glyph advance = pixel width. ~80 ms per 240x150 frame.
#  quality: comb fields (one cell per character) with glyphs drawn 1.7x larger than
#           the cell, so they overlap into near-solid black. ~3x the contrast,
#           but PDFium needs ~2.4x longer to redraw them.
RAMP_FAST = [[" ", 255], ["_", 245], [".", 241], [",", 235], [":", 226], [";", 217], ["~", 215],
             ["\"", 210], ["!", 201], ["*", 195], [")", 187], ["=", 180], ["j", 174], ["r", 166],
             ["t", 159], ["z", 153], ["I", 146], ["%", 140], ["C", 133], ["d", 126], ["U", 119],
             ["K", 114], ["W", 106], ["B", 99]]
RAMP_QUALITY = [[" ", 255], ["'", 235], ["\"", 216], [",", 215], [".", 212], [";", 206], [":", 204],
                ["-", 187], ["^", 178], ["!", 168], ["~", 154], ["(", 148], ["T", 140], ["7", 127],
                ["l", 123], ["i", 108], ["F", 99], ["2", 88], ["q", 80], ["#", 69], ["V", 60],
                ["w", 49], ["K", 39], ["W", 31]]
GLYPH_SCALE = 1.7

KEYS = {"UP": 0x100, "DOWN": 0x101, "LEFT": 0x102, "RIGHT": 0x103, "SHIFT": 0x104,
        "CTRL": 0x105, "ALT": 0x106, "ENTER": 13, "RETURN": 13, "ESC": 27, "ESCAPE": 27,
        "SPACE": 32, "TAB": 9, "BACKSPACE": 8}
KEYS.update({f"F{i}": 0x10F + i for i in range(1, 13)})

PRESETS = {
    "arrows": [{"label": "^", "key": "UP", "col": 1, "row": 0},
               {"label": "<", "key": "LEFT", "col": 0, "row": 1},
               {"label": "v", "key": "DOWN", "col": 1, "row": 1},
               {"label": ">", "key": "RIGHT", "col": 2, "row": 1}],
}
PRESETS["gamepad"] = PRESETS["arrows"] + [
    {"label": "A", "key": "z", "col": 4, "row": 1}, {"label": "B", "key": "x", "col": 5, "row": 1},
    {"label": "start", "key": "ENTER", "col": 4, "row": 0, "w": 2}]

M = 18          # page margin (pt)
CELL = 34       # button grid cell (pt)
GAP = 12


def keycode(k):
    if isinstance(k, int):
        return k
    if k.upper() in KEYS:
        return KEYS[k.upper()]
    if len(k) == 1:
        return ord(k)
    raise ValueError(f"unknown key name {k!r}")


def js_escape(m):
    """\\u escape for one non-ASCII character (surrogate pair above U+FFFF)."""
    c = ord(m.group(0))
    if c < 0x10000:
        return f"\\u{c:04x}"
    c -= 0x10000
    return f"\\u{0xD800 + (c >> 10):04x}\\u{0xDC00 + (c & 0x3FF):04x}"


def text_width(s, size):
    return len(s) * size * 0.5


def build(js_code, spec, out_path):
    pdf = PDF()
    page = pdf.reserve()
    fonts = {k: pdf.add({"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name(v),
                         "Encoding": Name("WinAnsiEncoding")})
             for k, v in [("Helv", "Helvetica"), ("HeBo", "Helvetica-Bold"),
                          ("Cour", "Courier"), ("CoBo", "Courier-Bold")]}
    fields, content, config = [], [], {"args": spec.get("args", [])}

    def js_action(code, nxt=None):
        code = re.sub(r"[^\x00-\x7f]", js_escape, code)
        stream = pdf.add(Stream(code.encode("ascii")))
        d = {"Type": Name("Action"), "S": Name("JavaScript"), "JS": stream}
        if nxt is not None:
            d["Next"] = nxt
        return pdf.add(d), stream

    def widget(name, rect, ft, **kw):
        x, y, w, h = rect
        d = {"Type": Name("Annot"), "Subtype": Name("Widget"), "FT": Name(ft), "T": name,
             "Rect": [round(x, 3), round(y, 3), round(x + w, 3), round(y + h, 3)],
             "F": 4, "P": page, "BS": {"W": 0}}
        d.update(kw)
        fields.append(pdf.add(d))

    # ----------------------------------------------------------- measure --
    disp = spec.get("display")
    term = spec.get("terminal")
    kbd = spec.get("keyboard", True)
    buttons = spec.get("buttons") or []
    if isinstance(buttons, str):
        buttons = [b for p in buttons.split("+") for b in PRESETS[p]]
    help_lines = spec.get("help", [])
    footer = spec.get("footer", [])

    if disp:
        cols, rows = int(disp["width"]), int(disp["height"])
        pw = float(disp.get("scale") or max(1.2, min(8.0, 640.0 / cols)))
        ph = pw * float(disp.get("pixel_aspect", 1.0))
        DW, DH = cols * pw, rows * ph
    if term:
        tcols, trows = int(term.get("cols", 80)), int(term.get("rows", 24))
        tfs = float(term.get("font_size") or (7 if disp else 9))
        tlh = tfs * 1.2
        TW, TH = tcols * tfs * 0.6 + 12, trows * tlh + 8
    gcols = max([b.get("col", 0) + b.get("w", 1) for b in buttons] or [0])
    grows = max([b.get("row", 0) + b.get("h", 1) for b in buttons] or [0])
    BW, BH = gcols * CELL, grows * CELL
    KW, KH = (max(190.0, BW), 34.0) if kbd else (0.0, 0.0)
    CW = max([KW, BW] + [text_width(s, 8) for s in help_lines] + [0])
    CH = (KH + 8 if kbd else 0) + (BH + 8 if buttons else 0) + 11 * len(help_lines)
    has_controls = CW > 0

    inner = max([480.0] + ([DW] if disp else []) + ([TW] if term else []) +
                [text_width(s, 8) for s in footer] + [CW])
    # terminal and controls side by side unless that would make a display page wider
    side_by_side = bool(term and has_controls and (not disp or TW + GAP + CW <= inner))
    if side_by_side:
        inner = max(inner, TW + GAP + CW)
    W = inner + 2 * M

    # ------------------------------------------------------------ place --
    # positions are computed top-down (y from the top of the page) and flipped later
    placed = []   # (kind, args, rect-top-down)
    y = M
    if spec.get("title"):
        placed.append(("text", (spec["title"], 20, "HeBo"), (M, y + 18)))
        y += 26
    if spec.get("subtitle"):
        placed.append(("text", (spec["subtitle"], 9, "Helv"), (M, y + 9)))
        y += 15
    if disp:
        dx = M + (inner - DW) / 2
        placed.append(("display", (cols, rows, pw, ph), (dx, y, DW, DH)))
        y += DH + GAP
    if term or has_controls:
        if term and has_controls and side_by_side:
            placed.append(("terminal", None, (M, y, TW, TH)))
            placed.append(("controls", None, (M + TW + GAP, y, CW, CH)))
            y += max(TH, CH) + GAP
        else:
            if term:
                placed.append(("terminal", None, (M, y, TW, TH)))
                y += TH + GAP
            if has_controls:
                placed.append(("controls", None, (M, y, CW, CH)))
                y += CH + GAP
    for s in footer:
        placed.append(("text", (s, 8, "Helv"), (M, y + 8)))
        y += 11
    H = y + M - GAP / 2

    def flip(x, ytop, w, h):  # top-down rect -> PDF rect (x, y, w, h)
        return (x, H - ytop - h, w, h)

    # ------------------------------------------------------------- emit --
    for kind, args, r in placed:
        if kind == "text":
            s, size, font = args
            content.append(f"BT /{font} {size} Tf 0 g {r[0]:.2f} {H - r[1]:.2f} Td {content_string(s)} Tj ET")
        elif kind == "display":
            cols, rows, pw, ph = args
            x, ytop, w, h = r
            fx, fy, _, _ = flip(x, ytop, w, h)
            content.append(f"0.8 G 0.5 w {fx - 1:.2f} {fy - 1:.2f} {w + 2:.2f} {h + 2:.2f} re S")
            mode = disp.get("mode", "fast")
            if mode not in ("fast", "quality"):
                raise ValueError(f"display mode must be 'fast' or 'quality', not {mode!r}")
            comb = mode == "quality"
            fs = pw / 0.6 * (GLYPH_SCALE if comb else 0.995)
            for row in range(rows):
                extra = {"MaxLen": cols, "Ff": 1 | (1 << 24)} if comb else {"Ff": 1}
                widget(f"pdfcc_px_{row}", flip(x, ytop + row * ph, w, ph), "Tx", V="",
                       DA=f"/CoBo {fs:.3f} Tf 0 g", **extra)
            config["display"] = {"cols": cols, "rows": rows, "prefix": "pdfcc_px_",
                                 "ramp": RAMP_QUALITY if comb else RAMP_FAST,
                                 "dither": disp.get("dither", True), "gamma": disp.get("gamma", 1.0)}
            grid = spec.get("click_grid")
            if grid:
                # all cells share two actions; the cell is read from the field name
                gc, gr = int(grid["cols"]), int(grid["rows"])
                grid_aa = {"D": js_action("pdfcc._gridClick(event, 1)")[0],
                           "U": js_action("pdfcc._gridClick(event, 0)")[0]}
                for gy in range(gr):
                    for gx in range(gc):
                        cr = flip(x + gx * w / gc, ytop + gy * h / gr, w / gc, h / gr)
                        widget(f"pdfcc_grid_{gx}_{gy}", cr, "Btn", Ff=65536, MK={}, AA=grid_aa)
        elif kind == "terminal":
            x, ytop, w, h = r
            dark = term.get("theme", "light") == "dark"
            fx, fy, _, _ = flip(x, ytop, w, h)
            bg, fg = ("0.08 g", "0.55 1 0.55 rg") if dark else ("0.965 g", "0.1 g")
            content.append(f"{bg} {fx:.2f} {fy:.2f} {w:.2f} {h:.2f} re f")
            for row in range(trows):
                widget(f"pdfcc_tty_{row}", flip(x + 4, ytop + 4 + row * tlh, w - 8, tlh), "Tx",
                       V="", Ff=1, DA=f"/Cour {tfs:.2f} Tf {fg}")
            config["terminal"] = {"cols": tcols, "rows": trows, "prefix": "pdfcc_tty_"}
            if "echo" in term:
                config["terminal"]["echo"] = bool(term["echo"])
        elif kind == "controls":
            x, ytop, w, h = r
            cy = ytop
            if kbd:
                ph_text = (kbd.get("placeholder") if isinstance(kbd, dict) else None) or \
                    "Click here, then type"
                kr = flip(x, cy, KW, KH)
                content.append(f"0.6 G 0.75 w {kr[0]:.2f} {kr[1]:.2f} {kr[2]:.2f} {kr[3]:.2f} re S")
                widget("pdfcc_kbd", kr, "Tx", V=ph_text, Ff=4096, DA="/Helv 9 Tf 0.35 g",
                       AA={"K": js_action("pdfcc._key(event)")[0],
                           "Fo": js_action("pdfcc._kbdFocus(true)")[0],
                           "Bl": js_action("pdfcc._kbdFocus(false)")[0]})
                config["keyboard"] = {"field": "pdfcc_kbd", "placeholder": ph_text}
                cy += KH + 8
            for i, b in enumerate(buttons):
                bx = x + b.get("col", 0) * CELL
                by = cy + b.get("row", 0) * CELL
                bw = b.get("w", 1) * CELL - 4
                bh = b.get("h", 1) * CELL - 4
                if "id" in b:
                    down, up = f"pdfcc._button({int(b['id'])},1,1)", f"pdfcc._button({int(b['id'])},0,1)"
                else:
                    code = keycode(b["key"])
                    down, up = f"pdfcc._button({code},1)", f"pdfcc._button({code},0)"
                widget(f"pdfcc_btn_{i}", flip(bx, by, bw, bh), "Btn", Ff=65536,
                       DA="/Helv 10 Tf 0 g", MK={"BG": [0.9], "CA": str(b.get("label", b.get("key", "?")))},
                       AA={"D": js_action(down)[0], "U": js_action(up)[0]})
            if buttons:
                cy += BH + 8
            for s in help_lines:
                content.append(f"BT /Helv 8 Tf 0.25 g {x:.2f} {H - cy - 8:.2f} Td {content_string(s)} Tj ET")
                cy += 11

    # ------------------------------------------------------- javascript --
    # runtime -> one action per file/slot -> program -> start
    start, _ = js_action("pdfcc.start();")
    program, _ = js_action("try {\n" + js_code + "\n} catch (e) { pdfcc.guard(function () { throw e; }); }",
                           nxt=start)
    chain = program
    slots_manifest = []
    entries = [("file", f) for f in spec.get("files", [])] + [("slot", s) for s in spec.get("slots", [])]
    for kind, f in reversed(entries):
        extra = json.dumps(f.get("args")) if f.get("args") else "null"
        if kind == "file":
            with open(f["src"], "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
        else:
            b64 = f.get("default", "")
        chain, stream = js_action(f"pdfcc.addFile({json.dumps(f['path'])}, \"{b64}\", {extra});", nxt=chain)
        slots_manifest.insert(0, {"name": f.get("name") or os.path.basename(f["path"]), "path": f["path"],
                                  "args": f.get("args"), "obj": stream.num, "filled": bool(b64)})
    with open(RUNTIME_JS) as fh:
        runtime_js = fh.read()
    first, _ = js_action("var PDFCC_CONFIG = " + json.dumps(config) + ";\n" + runtime_js, nxt=chain)

    pdf.set(page, {"Type": Name("Page"), "MediaBox": [0, 0, round(W, 2), round(H, 2)],
                   "Resources": {"Font": fonts}, "Annots": fields, "AA": {"O": first},
                   "Contents": pdf.add(Stream("\n".join(content)))})
    pages = pdf.add({"Type": Name("Pages"), "Kids": [page], "Count": 1})
    pdf.objects[page.num]["Parent"] = pages
    acro = pdf.add({"Fields": fields, "DR": {"Font": fonts}, "DA": "/Helv 0 Tf 0 g"})
    root = pdf.add({"Type": Name("Catalog"), "Pages": pages, "AcroForm": acro})
    info = pdf.add({"Title": spec.get("title", "pdfcc program"), "Producer": "pdfcc"})
    manifest = {"slots": slots_manifest, "root": root.num, "info": info.num}
    data = pdf.to_bytes(root, info=info, comment="PDFCC " + json.dumps(manifest))
    with open(out_path, "wb") as fh:
        fh.write(data)
    return {"width": W, "height": H, "bytes": len(data), "fields": len(fields)}


def parse_size(s):
    a, b = s.lower().split("x")
    return int(a), int(b)


def apply_cli(spec, a):
    """Merge command-line options into a layout spec (CLI wins)."""
    if a.title:
        spec["title"] = a.title
    if a.subtitle:
        spec["subtitle"] = a.subtitle
    if a.display:
        w, h = parse_size(a.display)
        spec["display"] = dict(spec.get("display") or {}, width=w, height=h)
    if a.scale and spec.get("display"):
        spec["display"]["scale"] = a.scale
    if a.quality and spec.get("display"):
        spec["display"]["mode"] = "quality"
    if a.terminal:
        c, r = parse_size(a.terminal)
        spec["terminal"] = dict(spec.get("terminal") or {}, cols=c, rows=r)
    if a.no_terminal:
        spec.pop("terminal", None)
    if a.dark and spec.get("terminal"):
        spec["terminal"]["theme"] = "dark"
    if a.no_keyboard:
        spec["keyboard"] = False
    if a.buttons:
        spec["buttons"] = json.loads(a.buttons) if a.buttons.startswith("[") else a.buttons
    if a.click_grid:
        c, r = parse_size(a.click_grid)
        spec["click_grid"] = {"cols": c, "rows": r}
    for h in a.help or []:
        spec.setdefault("help", []).append(h)
    if a.arg:
        spec["args"] = spec.get("args", []) + a.arg
    for f in a.file or []:
        src, _, dest = f.partition(":")
        spec.setdefault("files", []).append({"src": src, "path": dest or "/" + os.path.basename(src)})
    for s in a.slot or []:
        parts = s.split(":")
        slot = {"name": parts[0], "path": parts[1] if len(parts) > 1 else "/" + parts[0]}
        if len(parts) > 2 and parts[2]:
            slot["args"] = parts[2].split(",")
        spec.setdefault("slots", []).append(slot)
    if "display" not in spec and "terminal" not in spec:
        spec["terminal"] = {"cols": 80, "rows": 24}
    return spec


def add_cli_options(p):
    g = p.add_argument_group("page layout (override --layout)")
    g.add_argument("--layout", help="layout JSON file")
    g.add_argument("--title")
    g.add_argument("--subtitle")
    g.add_argument("--display", metavar="WxH", help="add a framebuffer display, e.g. 160x100")
    g.add_argument("--scale", type=float, help="display pixel size in points")
    g.add_argument("--quality", action="store_true",
                   help="higher-contrast display, ~2.4x slower to redraw (good for still images)")
    g.add_argument("--terminal", metavar="COLSxROWS", help="terminal size (default 80x24 if no display)")
    g.add_argument("--no-terminal", action="store_true")
    g.add_argument("--dark", action="store_true", help="dark terminal theme")
    g.add_argument("--no-keyboard", action="store_true")
    g.add_argument("--buttons", help="'arrows', 'gamepad', 'arrows+...' or a JSON list")
    g.add_argument("--click-grid", metavar="COLSxROWS", help="clickable cells over the display")
    g.add_argument("--help-line", dest="help", action="append", help="help text line (repeatable)")
    g.add_argument("--arg", action="append", help="argument passed to main() (repeatable)")
    g.add_argument("--file", action="append", metavar="SRC[:/PATH]", help="embed a file (repeatable)")
    g.add_argument("--slot", action="append", metavar="NAME[:/PATH[:ARG,ARG]]",
                   help="empty file slot, filled later with tools/inject.py; ARGs are added to argv "
                        "only when the slot is filled")


def load_spec(a):
    spec = {}
    if a.layout:
        with open(a.layout) as fh:
            spec = json.load(fh)
        base = os.path.dirname(os.path.abspath(a.layout))
        for f in spec.get("files", []):
            if not os.path.isabs(f["src"]):
                f["src"] = os.path.join(base, f["src"])
    return apply_cli(spec, a)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("js", help="Emscripten output (.js, built with pdfcc flags)")
    p.add_argument("-o", "--output", required=True)
    add_cli_options(p)
    a = p.parse_args()
    with open(a.js) as fh:
        js = fh.read()
    info = build(js, load_spec(a), a.output)
    print(f"{a.output}: {info['bytes'] / 1e6:.2f} MB, page {info['width']:.0f}x{info['height']:.0f}pt, "
          f"{info['fields']} fields")


if __name__ == "__main__":
    main()
