#!/usr/bin/env python3
"""inject.py - put files into a pdfcc PDF without recompiling it.

    inject.py doom_nowad.pdf --list
    inject.py doom_nowad.pdf -o doom.pdf --file iwad=freedoom1.wad
    inject.py doom_nowad.pdf -o doom2.pdf --file iwad=doom2.wad:/doom2.wad --file pwad=mymap.wad

Each embedded file and slot is a JavaScript stream object listed in the PDF's
manifest comment. The new data is appended as an incremental update (new object
versions, xref section, trailer); the original bytes are unchanged. web/inject.js
does the same in a browser.
"""
import argparse
import base64
import json
import os
import re
import sys
import zlib


def read_manifest(data):
    found = re.findall(rb"%PDFCC (\{[^\n]*\})\n", data)
    if not found:
        sys.exit("inject: not a pdfcc PDF (no manifest)")
    return json.loads(found[-1])


def inject(data, files, manifest):
    """files: {slot name: (bytes, path or None)} -> new PDF bytes"""
    startxref = int(re.findall(rb"startxref\s+(\d+)", data)[-1])
    size = int(re.search(rb"/Size (\d+)", data[data.rindex(b"trailer"):]).group(1))
    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"
    offsets = {}
    slots = {s["name"]: s for s in manifest["slots"]}
    for name, (content, path) in files.items():
        if name not in slots:
            sys.exit(f"inject: no slot named {name!r} (have: {', '.join(slots)})")
        slot = slots[name]
        if path:
            slot["path"] = path
        extra = json.dumps(slot["args"]) if slot.get("args") else "null"
        js = f"pdfcc.addFile({json.dumps(slot['path'])}, \"{base64.b64encode(content).decode()}\", {extra});"
        stream = zlib.compress(js.encode("ascii"), 9)
        offsets[slot["obj"]] = len(out)
        out += f"{slot['obj']} 0 obj\n<</Length {len(stream)} /Filter /FlateDecode>>\nstream\n".encode()
        out += stream + b"\nendstream\nendobj\n"
        slot["filled"] = True
    out += b"%PDFCC " + json.dumps(manifest).encode() + b"\n"
    xref = len(out)
    out += b"xref\n0 1\n0000000000 65535 f \n"
    for num in sorted(offsets):
        out += f"{num} 1\n{offsets[num]:010d} 00000 n \n".encode()
    trailer = f"<</Size {size} /Root {manifest['root']} 0 R /Prev {startxref}"
    if manifest.get("info"):
        trailer += f" /Info {manifest['info']} 0 R"
    out += f"trailer\n{trailer}>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdf")
    p.add_argument("-o", "--output")
    p.add_argument("--list", action="store_true", help="show the file slots")
    p.add_argument("--file", action="append", default=[], metavar="SLOT=FILE[:/PATH]")
    a = p.parse_args()
    with open(a.pdf, "rb") as fh:
        data = fh.read()
    manifest = read_manifest(data)
    if a.list or not a.file:
        for s in manifest["slots"]:
            args = " (adds args: " + " ".join(s["args"]) + ")" if s.get("args") else ""
            print(f"{s['name']:12} {s['path']:24} {'filled' if s['filled'] else 'empty'}{args}")
        return
    if not a.output:
        sys.exit("inject: -o OUTPUT is required")
    files = {}
    for spec in a.file:
        name, _, rest = spec.partition("=")
        src, _, path = rest.partition(":")
        with open(src, "rb") as fh:
            files[name] = (fh.read(), path or None)
    with open(a.output, "wb") as fh:
        fh.write(inject(data, files, manifest))
    print(f"{a.output}: {os.path.getsize(a.output) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
