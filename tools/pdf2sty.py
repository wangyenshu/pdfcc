#!/usr/bin/env python3
"""pdf2sty.py - use a program from a pdfcc PDF in LaTeX documents (tex/pdfcc.sty).

    pdf2sty.py snake.pdf -o texdir                 # program name: snake
    pdf2sty.py build/fricas.pdf -o texdir --name fricas

Writes to the output directory:
    pdfcc-NAME.tex     the program's layout (sizes, buttons, help text); \\pdfccload reads it
    pdfcc-NAME.js      its JavaScript: arguments, embedded files, Emscripten code
    pdfcc.sty          the LaTeX package (copied from tex/)
    pdfcc-runtime.js   the pdfcc runtime (copied from runtime/), shared by all programs

Then in the document:  \\usepackage{pdfcc}  \\pdfccload{NAME}  ...  \\pdfccprogram
(see tex/README.md). Works for PDFs from any pdfcc version, including PDFs whose
slots were filled by inject.py (later object versions win).
"""
import argparse
import json
import os
import re
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkpdf  # noqa: E402

ROOT = os.path.dirname(HERE)


# ------------------------------------------------------------- PDF reading --
class Name(str):
    pass


class Ref:
    def __init__(self, num):
        self.num = num


TOKEN = re.compile(rb"\s*(<<|>>|\[|\]|/[^\s/<>\[\]()]*|\(|<[0-9A-Fa-f\s]*>|[-+]?[0-9.]+|true|false|null)")
REF = re.compile(rb"\s+(\d+)\s+R\b")


def parse_value(data, pos=0):
    """One PDF value at data[pos:] -> (value, end position)."""
    m = TOKEN.match(data, pos)
    if not m:
        raise ValueError(f"cannot parse PDF at {pos}: {data[pos:pos + 40]!r}")
    tok, pos = m.group(1), m.end()
    if tok == b"<<":
        d = {}
        while True:
            m = TOKEN.match(data, pos)
            if m.group(1) == b">>":
                return d, m.end()
            key, pos = parse_value(data, pos)
            d[str(key)], pos = parse_value(data, pos)
    if tok == b"[":
        a = []
        while True:
            m = TOKEN.match(data, pos)
            if m.group(1) == b"]":
                return a, m.end()
            v, pos = parse_value(data, pos)
            a.append(v)
    if tok.startswith(b"/"):
        raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda x: bytes([int(x.group(1), 16)]), tok[1:])
        return Name(raw.decode("latin-1")), pos
    if tok == b"(":
        out, depth = bytearray(), 1
        while True:
            c = data[pos]
            pos += 1
            if c == 0x5C:
                e = data[pos]
                pos += 1
                out += {0x6E: b"\n", 0x72: b"\r", 0x74: b"\t", 0x62: b"\b", 0x66: b"\f"}.get(e, bytes([e]))
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    return bytes(out), pos
                out.append(c)
            else:
                out.append(c)
    if tok.startswith(b"<"):
        return bytes.fromhex(re.sub(rb"\s", b"", tok[1:-1]).decode()), pos
    if tok in (b"true", b"false"):
        return tok == b"true", pos
    if tok == b"null":
        return None, pos
    num = float(tok) if b"." in tok else int(tok)
    m2 = REF.match(data, pos)
    if isinstance(num, int) and m2:
        return Ref(num), m2.end()
    return num, pos


def pdf_text(b):
    """PDF text string (bytes) -> str"""
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be")
    return b.decode("latin-1")


class PDF:
    """The objects of a PDF written by pdfcc's pdfwriter (later versions win)."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            self.data = data = fh.read()
        if not data.startswith(b"%PDF"):
            raise SystemExit(f"pdf2sty: {path} is not a PDF")
        self.objs = {}
        for m in re.finditer(rb"(?m)^(\d+) 0 obj\s", data):
            d, pos = parse_value(data, m.end())
            stream = None
            sm = re.compile(rb"\s*stream\r?\n").match(data, pos)
            if sm:
                raw = data[sm.end():sm.end() + d["Length"]]
                stream = zlib.decompress(raw) if d.get("Filter") == "FlateDecode" else raw
            self.objs[int(m.group(1))] = (d, stream)
        man = re.findall(rb"%PDFCC (\{[^\n]*\})\n", data)
        self.manifest = json.loads(man[-1]) if man else {}

    def get(self, v):
        while isinstance(v, Ref):
            v = self.objs[v.num][0]
        return v

    def stream(self, v):
        return self.objs[v.num][1] if isinstance(v, Ref) else None

    def info(self):
        refs = re.findall(rb"/Info (\d+) 0 R", self.data)
        return self.objs[int(refs[-1])][0] if refs else {}

    def page(self):
        for d, _ in self.objs.values():
            if d.get("Type") == "Page" and "AA" in d:
                return d
        raise SystemExit("pdf2sty: no pdfcc page (a page with an open action) in this PDF")

    def chain(self, action):
        """JavaScript of an action and its /Next actions, in order."""
        out = []
        while action is not None:
            a = self.get(action)
            js = a.get("JS")
            out.append(self.stream(js).decode("latin-1") if isinstance(js, Ref) else pdf_text(js))
            action = a.get("Next")
        return out


# ------------------------------------------------------------- extraction --
LEGACY_HEAD, LEGACY_TAIL = "try {\n", "\n} catch (e) { pdfcc.guard(function () { throw e; }); }"


def split_scripts(pdf):
    """-> (config, [file scripts], program script), for the shared form of
    pdfcc.sty: instance-independent pdfccAddFile/pdfccLoad calls."""
    scripts = pdf.chain(pdf.get(pdf.page()["AA"])["O"])
    m = re.match(r"var PDFCC_CONFIG = (\{.*?\});\n", scripts[0])
    if not m:
        raise SystemExit("pdf2sty: first action is not the pdfcc runtime")
    config = json.loads(m.group(1))
    inst = config.get("name", "pdfcc")
    files, program = [], None
    for js in scripts[1:]:
        if js.startswith(inst + ".addFile("):
            if not re.match(re.escape(inst) + r'\.addFile\("(?:[^"\\]|\\.)*", "",', js):  # empty slot
                files.append("pdfccAddFile(" + js[len(inst) + 9:])
        elif js.startswith(inst + ".load(function ("):
            program = "pdfccLoad(" + js[len(inst) + 6:]
        elif js.startswith(LEGACY_HEAD) and js.endswith(LEGACY_TAIL):  # pdfcc before named programs
            body = js[len(LEGACY_HEAD):-len(LEGACY_TAIL)]
            program = "pdfccLoad(" + mkpdf.wrap_program(body, "x")[len("x.load("):]
    if program is None:
        raise SystemExit("pdf2sty: program script not found")
    return config, files, program


def reconstruct_layout(pdf, config):
    """Layout of a PDF without one in its manifest (older pdfcc): from the
    config, the widgets and the page text."""
    page = pdf.page()
    lay = {}
    widgets = {}
    for a in pdf.get(page.get("Annots", [])):
        a = pdf.get(a)
        if a.get("Subtype") == "Widget" and "T" in a:
            widgets[pdf_text(a["T"])] = a
    pre = config.get("name", "pdfcc") + "_"

    def rect(w):
        x0, y0, x1, y1 = (float(v) for v in w["Rect"])
        return x0, y0, x1 - x0, y1 - y0

    def font_size(da):
        m = re.search(rb"([0-9.]+) Tf", da)
        return float(m.group(1)) if m else None

    if "terminal" in config:
        t = config["terminal"]
        term = {"cols": t["cols"], "rows": t["rows"]}
        w = widgets.get(t["prefix"] + "0")
        if w:
            term["font_size"] = round(font_size(w["DA"]), 2)
            if b"0.55 1 0.55 rg" in w["DA"]:
                term["theme"] = "dark"
        if "echo" in t:
            term["echo"] = t["echo"]
        lay["terminal"] = term
    if "display" in config:
        d = config["display"]
        disp = {"width": d["cols"], "height": d["rows"]}
        w = widgets.get(d["prefix"] + "0")
        if w:
            _, _, ww, hh = rect(w)
            disp["scale"] = round(ww / d["cols"], 4)
            disp["pixel_aspect"] = round(hh / (ww / d["cols"]), 4)
            if int(w.get("Ff", 0)) & (1 << 24):  # comb fields
                disp["mode"] = "quality"
        disp["dither"] = d.get("dither", True)
        disp["gamma"] = d.get("gamma", 1.0)
        lay["display"] = disp
        cells = [tuple(map(int, n.split("_")[-2:])) for n in widgets if n.startswith(pre + "grid_")]
        if cells:
            lay["click_grid"] = {"cols": max(c[0] for c in cells) + 1, "rows": max(c[1] for c in cells) + 1}
    kbd = config.get("keyboard")
    lay["keyboard"] = {"placeholder": kbd.get("placeholder", "")} if kbd else False
    buttons, btns = [], sorted((n for n in widgets if re.match(re.escape(pre) + r"btn_\d+$", n)),
                               key=lambda n: int(n.split("_")[-1]))
    if btns:
        rects = {n: rect(widgets[n]) for n in btns}
        x0 = min(r[0] for r in rects.values())
        ytop = max(r[1] + r[3] for r in rects.values())
        for n in btns:
            x, y, w, h = rects[n]
            a = widgets[n]
            js = pdf.chain(pdf.get(a["AA"])["D"])[0]
            m = re.search(r"_button\((\d+),1(,1)?\)", js)
            b = {"label": pdf_text(pdf.get(a["MK"]).get("CA", b"?")),
                 "col": round((x - x0) / mkpdf.CELL, 2), "row": round((ytop - (y + h)) / mkpdf.CELL, 2),
                 "w": round((w + 4) / mkpdf.CELL, 2), "h": round((h + 4) / mkpdf.CELL, 2)}
            b["id" if m.group(2) else "key"] = int(m.group(1))
            buttons.append(b)
    lay["buttons"] = buttons
    # page text: BT /Font size Tf gray g x y Td (text) Tj ET
    content = b"".join(pdf.stream(c) or b"" for c in
                       (page["Contents"] if isinstance(page["Contents"], list) else [page["Contents"]]))
    help_, footer = [], []
    for m in re.finditer(rb"BT /(\w+) ([0-9.]+) Tf ([0-9.]+) g [-0-9.]+ [-0-9.]+ Td \(((?:[^\\)]|\\.)*)\) Tj ET",
                         content):
        font, size, gray = m.group(1), float(m.group(2)), float(m.group(3))
        text = re.sub(rb"\\(.)", rb"\1", m.group(4)).decode("cp1252")
        if font == b"HeBo" and size == 20:
            lay["title"] = text
        elif size == 9:
            lay["subtitle"] = text
        elif size == 8 and gray > 0:
            help_.append(text)
        elif size == 8:
            footer.append(text)
    if "title" not in lay and pdf.info().get("Title"):
        title = pdf_text(pdf.info()["Title"])
        if title != "pdfcc program":
            lay["title"] = title
    if help_:
        lay["help"] = help_
    if footer:
        lay["footer"] = footer
    return lay


# -------------------------------------------------------------- TeX output --
TEX_SPECIAL = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#",
               "^": r"\textasciicircum{}", "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}",
               "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}"}


def tex_text(s):
    return "".join(TEX_SPECIAL.get(c, c) for c in s)


def pdf_hex(s):
    """PDF text string as hex (UTF-16BE with BOM): safe in any TeX token list."""
    return "FEFF" + s.encode("utf-16-be").hex().upper()


def num(v):
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def declaration(name, layout, js_file):
    out = [f"% {name}: program layout for pdfcc.sty, written by tools/pdf2sty.py",
           f"\\pdfccdeclare{{{name}}}{{", f"  js = {js_file},"]
    for key in ("title", "subtitle"):
        if layout.get(key):
            out.append(f"  {key} = {{{tex_text(layout[key])}}},")
    for key in ("help", "footer"):
        if layout.get(key):
            out.append(f"  {key} = {{" + "".join("{" + tex_text(s) + "}" for s in layout[key]) + "},")
    t = layout.get("terminal")
    if t:
        disp = layout.get("display")
        items = [f"cols={int(t.get('cols', 80))}", f"rows={int(t.get('rows', 24))}",
                 f"fontsize={num(t.get('font_size') or (7 if disp else 9))}",
                 f"theme={t.get('theme', 'light')}"]
        if "echo" in t:
            items.append(f"echo={'true' if t['echo'] else 'false'}")
        out.append("  terminal = {" + ", ".join(items) + "},")
    d = layout.get("display")
    if d:
        cols = int(d["width"])
        scale = float(d.get("scale") or max(1.2, min(8.0, 640.0 / cols)))
        items = [f"cols={cols}", f"rows={int(d['height'])}", f"scale={num(scale)}",
                 f"aspect={num(d.get('pixel_aspect', 1.0))}", f"mode={d.get('mode', 'fast')}",
                 f"dither={'true' if d.get('dither', True) else 'false'}", f"gamma={num(d.get('gamma', 1.0))}"]
        out.append("  display = {" + ", ".join(items) + "},")
        g = layout.get("click_grid")
        if g:
            out.append(f"  grid = {{cols={int(g['cols'])}, rows={int(g['rows'])}}},")
    k = layout.get("keyboard", True)
    if k:
        ph = (k.get("placeholder") if isinstance(k, dict) else None) or "Click here, then type"
        out.append(f"  keyboard = {{placeholder-hex={pdf_hex(ph)}}},")
    btns = layout.get("buttons") or []
    if isinstance(btns, str):
        btns = [b for p in btns.split("+") for b in mkpdf.PRESETS[p]]
    if btns:
        out.append("  button-list = {")
        for b in btns:
            label = str(b.get("label", b.get("key", "?")))
            code, isid = (int(b["id"]), 1) if "id" in b else (mkpdf.keycode(b["key"]), 0)
            out.append(f"    {{{pdf_hex(label)}}}{{{code}}}{{{isid}}}{{{num(b.get('col', 0))}}}"
                       f"{{{num(b.get('row', 0))}}}{{{num(b.get('w', 1))}}}{{{num(b.get('h', 1))}}}")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n"


def convert(pdf_path, outdir, name=None, copy_shared=True):
    pdf = PDF(pdf_path)
    if not name:  # the --name it was built with, else the file name
        inst = pdf.manifest.get("instance", "pdfcc")
        name = inst[6:] if inst.startswith("pdfcc_") else \
            re.sub(r"[^a-z0-9]", "", os.path.splitext(os.path.basename(pdf_path))[0].lower())
    if not re.fullmatch(r"[a-z0-9]+", name or ""):
        raise SystemExit(f"pdf2sty: program name must be lowercase letters and digits, not {name!r}")
    config, files, program = split_scripts(pdf)
    layout = pdf.manifest.get("layout") or reconstruct_layout(pdf, config)
    os.makedirs(outdir, exist_ok=True)
    js_file = f"pdfcc-{name}.js"
    with open(os.path.join(outdir, js_file), "w", encoding="ascii") as fh:
        fh.write(f"// {name}: program for pdfcc.sty, written by tools/pdf2sty.py\n")
        if config.get("args"):
            fh.write(f"pdfccArgs({json.dumps(config['args'])});\n")
        fh.writelines(f + "\n" for f in files)
        fh.write(program + "\n")
    with open(os.path.join(outdir, f"pdfcc-{name}.tex"), "w", encoding="utf-8") as fh:
        fh.write(declaration(name, layout, js_file))
    if copy_shared:
        shutil.copy(os.path.join(ROOT, "tex", "pdfcc.sty"), os.path.join(outdir, "pdfcc.sty"))
        shutil.copy(os.path.join(ROOT, "runtime", "pdfcc_runtime.js"), os.path.join(outdir, "pdfcc-runtime.js"))
    return name


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdf")
    p.add_argument("-o", "--output", default=".", help="output directory (default: current)")
    p.add_argument("--name", help="program name, lowercase letters and digits (default: the name the "
                   "PDF was built with, else its file name)")
    p.add_argument("--no-shared", action="store_true", help="do not copy pdfcc.sty and pdfcc-runtime.js")
    a = p.parse_args()
    name = convert(a.pdf, a.output, a.name, not a.no_shared)
    print(f"pdf2sty: {os.path.join(a.output, f'pdfcc-{name}.tex')} and .js")


if __name__ == "__main__":
    main()
