#!/usr/bin/env python3
"""Check a PDF made with tex/pdfcc.sty: fields, widgets and page-open actions.

    texcheck.py doc.pdf hello:1,2 snake:2      # program: pages (1-based) that show it

Needs qpdf (to undo object streams). Prints one line per problem; exit status 1 if any.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from pdf2sty import Ref, parse_value, pdf_text  # noqa: E402


def load(path):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "q.pdf")
        subprocess.run(["qpdf", "--qdf", "--object-streams=disable", path, out], check=False,
                       stderr=subprocess.DEVNULL)
        with open(out, "rb") as fh:
            data = fh.read()
    objs = {}
    for m in re.finditer(rb"(?m)^(\d+) 0 obj\n", data):
        v, pos = parse_value(data, m.end())
        objs[int(m.group(1))] = (v, pos)

    def get(v):
        return objs[v.num][0] if isinstance(v, Ref) else v
    streams = {}
    for num, (v, pos) in objs.items():
        sm = re.compile(rb"\s*stream\r?\n").match(data, pos)
        if sm and isinstance(v, dict):
            streams[num] = data[sm.end():sm.end() + int(get(v["Length"]))]
    return objs, get, streams


def js_of(action, get, streams):
    js = get(action).get("JS")
    return streams[js.num].decode("latin-1") if isinstance(js, Ref) else pdf_text(js)


def main():
    path, specs = sys.argv[1], sys.argv[2:]
    want = {p: {int(x) for x in pages.split(",")} for p, pages in (s.split(":") for s in specs)}
    objs, get, streams = load(path)
    problems = []
    catalog = next(v for v, _ in objs.values() if isinstance(v, dict) and v.get("Type") == "Catalog")
    form = get(catalog["AcroForm"])
    fields = {pdf_text(get(f)["T"]): f.num for f in get(form["Fields"])}
    fonts = get(get(form["DR"])["Font"])
    for f in ("Helv", "Cour", "CoBo"):
        if f not in fonts:
            problems.append(f"AcroForm /DR has no /{f}")
    pages = []
    node = get(catalog["Pages"])

    def walk(n):
        for k in get(n["Kids"]):
            d = get(k)
            if d.get("Type") == "Page":
                pages.append(d)
            else:
                walk(d)
    walk(node)
    for i, page in enumerate(pages, 1):
        shown = set()
        for a in get(page.get("Annots", [])):
            a = get(a)
            if a.get("Subtype") != "Widget":
                continue
            parent = a.get("Parent")
            name = pdf_text(get(parent)["T"]) if parent else pdf_text(a.get("T", b""))
            m = re.match(r"pdfcc_([a-z0-9]+)_", name)
            if not m:
                continue
            shown.add(m.group(1))
            if parent is not None and parent.num not in fields.values():
                problems.append(f"page {i}: parent field {name} not in /Fields")
        started = set()
        if "AA" in page:
            action = get(page["AA"])["O"]
            while action is not None:
                m = re.match(r"pdfcc_([a-z0-9]+)\.start\(", js_of(action, get, streams))
                if m:
                    started.add(m.group(1))
                action = get(action).get("Next")
        for prog, ps in want.items():
            if (i in ps) != (prog in shown):
                problems.append(f"page {i}: program {prog} {'missing' if i in ps else 'unexpected'}")
            if i in ps and prog not in started:
                problems.append(f"page {i}: open action does not start {prog}")
    for prog in want:
        for kind in ("tty_0", "kbd", "px_0"):
            name = f"pdfcc_{prog}_{kind}"
            if any(n.startswith(f"pdfcc_{prog}_{kind[:3]}") for n in fields) and name not in fields:
                problems.append(f"field {name} missing")
    for p in problems:
        print(f"{path}: {p}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
