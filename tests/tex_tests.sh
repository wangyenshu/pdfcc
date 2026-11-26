#!/bin/bash
# Build the LaTeX documents in tests/tex/ with every installed engine and check them with
# tests/texcheck.py. Needs the examples built (examples/build_all.sh) and qpdf.
cd "$(dirname "$0")/.." || exit 1
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
for p in hello snake life; do
  [ -f examples/out/$p.pdf ] || { echo "skip: examples/out/$p.pdf not built"; exit 0; }
  python3 tools/pdf2sty.py -o "$OUT" examples/out/$p.pdf >/dev/null || exit 1
done
cp tests/tex/*.tex "$OUT"/
pass=0; fail=0
check() { # engine, document, program:pages...
  local engine=$1 doc=$2; shift 2
  if ! command -v "$engine" >/dev/null; then echo "skip  $engine"; return; fi
  if ! ( cd "$OUT" && "$engine" -interaction=nonstopmode -halt-on-error "$doc.tex" >/dev/null 2>&1 &&
         "$engine" -interaction=nonstopmode -halt-on-error "$doc.tex" >/dev/null 2>&1 ); then
    echo "FAIL  $engine $doc: LaTeX error"; grep -A3 '^!' "$OUT/$doc.log" | head -8 | sed 's/^/      /'
    fail=$((fail+1)); return
  fi
  if python3 tests/texcheck.py "$OUT/$doc.pdf" "$@"; then echo "ok    $engine $doc"; pass=$((pass+1));
  else echo "FAIL  $engine $doc"; fail=$((fail+1)); fi
}
for e in pdflatex xelatex lualatex; do
  check $e two snake:1,2 hello:2
  check $e beamer hello:2,3,4 life:5
  check $e meta hello:1,2 second:2
done
echo "$pass passed, $fail failed"
[ $fail = 0 ]
