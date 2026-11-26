#!/usr/bin/env python3
"""Measure how dark each glyph renders in Chrome's PDF viewer, to build the display
ramps in runtime/pdfcc_runtime.js (RAMPS.fast / RAMPS.quality).

    python3 tests/measure_ramp.py fast      # or: quality
Needs Chrome + tests/chrome.mjs (puppeteer-core) + Pillow/numpy. Each printable ASCII
character fills a band of display rows using the exact field setup mkpdf uses; a
screenshot gives each band's mean brightness at 100% zoom.
"""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mkpdf  # noqa: E402
import numpy as np
from PIL import Image

mode = sys.argv[1] if len(sys.argv) > 1 else "fast"
chars = [chr(c) for c in range(32, 127)]
COLS, BAND, PER = 160, 3, 48
rows = BAND * PER
js = """function callMain() {
  // note: never read field values back - PDFium returns numeric-looking text as a Number
  var C = %s, D = pdfcc.display, rows = [];
  for (var y = 0; y < D.rows; y++) rows.push(["", ""]);
  for (var i = 0; i < C.length; i++) {
    var col = Math.floor(i / %d), idx = i %% %d, piece = "";
    for (var k = 0; k < %d; k++) piece += C[i];
    for (var r = 0; r < %d; r++) rows[idx * %d + r][col] = piece;
  }
  for (var y2 = 0; y2 < D.rows; y2++) getField(D.prefix + y2).value = rows[y2][0] + rows[y2][1];
}""" % (json.dumps(chars), PER, PER, COLS // 2, BAND, BAND)
spec = {"display": {"width": COLS, "height": rows, "scale": 356 / 160, "pixel_aspect": 2 / 2.225,
                    "mode": mode, "dither": False}, "keyboard": False,
        "terminal": {"cols": 60, "rows": 4}}
pdf, png = f"/tmp/ramp_{mode}.pdf", f"/tmp/ramp_{mode}.png"
mkpdf.build(js, spec, pdf)
here = os.path.dirname(os.path.abspath(__file__))
subprocess.run(["node", os.path.join(here, "chrome.mjs"), pdf,
                json.dumps([{"wait": 3500}, {"shot": png}])], check=True,
               env=dict(os.environ, WIN="1400,1000"))
img = np.asarray(Image.open(png).convert("L")).astype(float)
# calibrate from the display's frame (mkpdf draws it in 0.8 gray, 1pt outside the display)
frame = np.abs(img - 204) < 12
cols = np.where(frame[:, 320:].sum(axis=0) > 200)[0] + 320
rows_ = np.where(frame[:, 320:].sum(axis=1) > 200)[0]
x0, y0 = cols.min() + 4 / 3, rows_.min() + 4 / 3
s = 4 / 3
pw, ph = 356 / 160, 2.0
res = []
for i, c in enumerate(chars):
    col, idx = divmod(i, PER)
    ya, yb = y0 + (idx * BAND * ph + 0.5) * s, y0 + ((idx + 1) * BAND * ph - 0.5) * s
    xa, xb = x0 + (col * 80 * pw + 4) * s, x0 + ((col + 1) * 80 * pw - 4) * s
    res.append((round(float(img[int(ya):int(yb), int(xa):int(xb)].mean())), c))
res.sort(reverse=True)
print(" ".join(f"{c}:{m}" for m, c in res))

# pick evenly spaced, strictly darker glyphs -> paste into runtime/pdfcc_runtime.js
N = int(sys.argv[2]) if len(sys.argv) > 2 else 24
hi, lo = res[0][0], res[-1][0]
ramp, last = [], 256
for k in range(N):
    target = hi - (hi - lo) * k / (N - 1)
    cands = [(abs(m - target), m, c) for m, c in res if m < last and c not in [r[0] for r in ramp]]
    if not cands:
        break
    _, m, c = min(cands)
    ramp.append([c, m])
    last = m
print("%s: %s" % (mode, json.dumps(ramp)))
