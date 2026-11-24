// inject.js - fill or replace the file slots of a pdfcc PDF, in the browser or Node.
// Same format as tools/inject.py: appends an incremental update with new versions of
// the slot's JavaScript stream objects, so nothing has to be recompiled.
(function (root) {
  "use strict";
  const enc = new TextEncoder();
  const latin1 = new TextDecoder("latin1");

  function readManifest(bytes) {
    const text = latin1.decode(bytes);
    const all = [...text.matchAll(/%PDFCC (\{[^\n]*\})\n/g)];
    if (!all.length) throw new Error("Not a pdfcc PDF (no manifest found).");
    const m = JSON.parse(all[all.length - 1][1]);
    const xrefs = [...text.matchAll(/startxref\s+(\d+)/g)];
    m.startxref = +xrefs[xrefs.length - 1][1];
    m.size = +/\/Size (\d+)/.exec(text.slice(text.lastIndexOf("trailer")))[1];
    return m;
  }

  function base64(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000)
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }

  async function deflate(bytes) {
    if (typeof CompressionStream === "undefined") return null;
    const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  // files: { slotName: { data: Uint8Array, path?: "/new/path" } }
  async function inject(pdfBytes, files) {
    const m = readManifest(pdfBytes);
    const slots = Object.fromEntries(m.slots.map(s => [s.name, s]));
    const parts = [pdfBytes];
    let pos = pdfBytes.length;
    if (pdfBytes[pos - 1] !== 10) { parts.push(enc.encode("\n")); pos++; }
    const offsets = {};
    for (const [name, f] of Object.entries(files)) {
      const slot = slots[name];
      if (!slot) throw new Error(`No slot named "${name}".`);
      if (f.path) slot.path = f.path;
      const extra = slot.args ? JSON.stringify(slot.args) : "null";
      const js = enc.encode(`pdfcc.addFile(${JSON.stringify(slot.path)}, "${base64(f.data)}", ${extra});`);
      const z = await deflate(js);
      const head = enc.encode(`${slot.obj} 0 obj\n<</Length ${(z || js).length}${z ? " /Filter /FlateDecode" : ""}>>\nstream\n`);
      const tail = enc.encode("\nendstream\nendobj\n");
      offsets[slot.obj] = pos;
      parts.push(head, z || js, tail);
      pos += head.length + (z || js).length + tail.length;
      slot.filled = true;
    }
    const manifest = { slots: m.slots, root: m.root, info: m.info };
    const mline = enc.encode("%PDFCC " + JSON.stringify(manifest) + "\n");
    parts.push(mline);
    pos += mline.length;
    let xref = "xref\n0 1\n0000000000 65535 f \n";
    for (const num of Object.keys(offsets).map(Number).sort((a, b) => a - b))
      xref += `${num} 1\n${String(offsets[num]).padStart(10, "0")} 00000 n \n`;
    xref += `trailer\n<</Size ${m.size} /Root ${m.root} 0 R /Prev ${m.startxref}` +
            (m.info ? ` /Info ${m.info} 0 R` : "") + `>>\nstartxref\n${pos}\n%%EOF\n`;
    parts.push(enc.encode(xref));
    return new Uint8Array(await new Blob(parts).arrayBuffer());
  }

  const api = { readManifest, inject };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.pdfccInject = api;
})(typeof window !== "undefined" ? window : globalThis);
