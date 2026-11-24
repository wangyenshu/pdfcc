"""Tiny dependency-free PDF object writer used by mkpdf.py.

Only what pdfcc needs: dicts, arrays, names, strings, numbers, indirect
references and (optionally Flate-compressed) streams.
"""
import zlib


class Name(str):
    """A PDF name object, written as /Name."""


class Ref:
    def __init__(self, num):
        self.num = num

    def __repr__(self):
        return f"Ref({self.num})"


class Stream:
    def __init__(self, data, d=None, compress=True):
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.dict = dict(d or {})
        self.data = data
        self.compress = compress


def _name(n):
    out = []
    for ch in n:
        if ch.isalnum() or ch in "_-.+":
            out.append(ch)
        else:
            out.append(f"#{ord(ch):02X}")
    return "/" + "".join(out)


def _string(s):
    try:
        b = s.encode("latin-1")
        if any(c > 126 for c in b):
            raise UnicodeEncodeError("x", "", 0, 1, "")
    except UnicodeEncodeError:
        return "<" + ("\ufeff" + s).encode("utf-16-be").hex().upper() + ">"
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    s = s.replace("\r", "\\r").replace("\n", "\\n")
    return "(" + s + ")"


def content_string(s):
    """String operand for text shown with a WinAnsi (cp1252) font in a content
    stream. Characters outside cp1252 become '?'."""
    out = []
    for b in s.encode("cp1252", errors="replace"):
        c = chr(b)
        if c in "\\()":
            out.append("\\" + c)
        elif 32 <= b < 127:
            out.append(c)
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def serialize(o):
    if isinstance(o, Name):
        return _name(o)
    if isinstance(o, Ref):
        return f"{o.num} 0 R"
    if isinstance(o, bool):
        return "true" if o else "false"
    if o is None:
        return "null"
    if isinstance(o, int):
        return str(o)
    if isinstance(o, float):
        s = f"{o:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    if isinstance(o, str):
        return _string(o)
    if isinstance(o, (list, tuple)):
        return "[" + " ".join(serialize(x) for x in o) + "]"
    if isinstance(o, dict):
        return "<<" + " ".join(f"{_name(k)} {serialize(v)}" for k, v in o.items()) + ">>"
    raise TypeError(f"cannot serialize {type(o)}")


class PDF:
    def __init__(self):
        self.objects = [None]  # 1-based

    def reserve(self):
        self.objects.append(None)
        return Ref(len(self.objects) - 1)

    def set(self, ref, obj):
        self.objects[ref.num] = obj
        return ref

    def add(self, obj):
        return self.set(self.reserve(), obj)

    def to_bytes(self, root, info=None, comment=None):
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * len(self.objects)
        for num in range(1, len(self.objects)):
            obj = self.objects[num]
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode()
            if isinstance(obj, Stream):
                d = dict(obj.dict)
                data = obj.data
                if obj.compress:
                    data = zlib.compress(data, 9)
                    d["Filter"] = Name("FlateDecode")
                d["Length"] = len(data)
                out += serialize(d).encode("latin-1") + b"\nstream\n" + data + b"\nendstream"
            else:
                out += serialize(obj).encode("latin-1")
            out += b"\nendobj\n"
        if comment:  # e.g. a machine-readable manifest; comments are legal between objects
            out += b"%" + comment.replace("\n", " ").encode("latin-1") + b"\n"
        xref = len(out)
        out += f"xref\n0 {len(self.objects)}\n0000000000 65535 f \n".encode()
        for num in range(1, len(self.objects)):
            out += f"{offsets[num]:010d} 00000 n \n".encode()
        trailer = {"Size": len(self.objects), "Root": root}
        if info:
            trailer["Info"] = info
        out += f"trailer\n{serialize(trailer)}\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
