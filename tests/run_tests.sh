#!/bin/bash
# Smoke tests: run the built examples in the Node simulator (tests/pdfsim.mjs) and
# check their output. Build them first with examples/build_all.sh. Each check waits
# for output with --until (30 s timeout), so results do not depend on machine speed.
cd "$(dirname "$0")/.." || exit 1
OUT=examples/out
SIM=(node tests/pdfsim.mjs)
pass=0; fail=0

check() { # name, expected text, command...
  local name="$1" want="$2"; shift 2
  if [ ! -f "$OUT/$name.pdf" ]; then echo "skip  $name (not built)"; return; fi
  local got; got=$("$@" 2>&1)
  if grep -qF -- "$want" <<<"$got"; then echo "ok    $name"; pass=$((pass+1));
  else echo "FAIL  $name: expected '$want'"; echo "$got" | sed 's/^/      /' | head -20; fail=$((fail+1)); fi
}

ECL_BOOT=(--until "Booted")
check hello "50 is too" "${SIM[@]}" "$OUT"/hello.pdf --until "guess:" --type "50\n" --until "50 is too"
check hello "is not a number" "${SIM[@]}" "$OUT"/hello.pdf --until "guess:" --type "abc\n" --until "not a number"
check mandelbrot "compute" "${SIM[@]}" "$OUT"/mandelbrot.pdf --until "compute"
check mandelbrot "%%%%%%%%%%" "${SIM[@]}" "$OUT"/mandelbrot.pdf --until "compute" --display
check mandelbrot "width 2.00e+00" "${SIM[@]}" "$OUT"/mandelbrot.pdf --until "compute" --press "+" --until "width 2.00e+00"
check snake "New game" "${SIM[@]}" "$OUT"/snake.pdf --until "New game"
check life "running" "${SIM[@]}" "$OUT"/life.pdf --until "Game of Life" --click 5,5 --press "run / pause" --until "running"
check blocking "2 + 40 = 42" "${SIM[@]}" "$OUT"/blocking.pdf --until "name?" --type "Ada\n" --until "numbers" --type "2 40\n" --until "= 42"
check blocking "2 + 40 = 42" "${SIM[@]}" "$OUT"/blocking.pdf --until "name?" --paste 'Ada\r\n2 40\r\n' --until "= 42"
check lua "PDF     42" "${SIM[@]}" "$OUT"/lua.pdf --until "> " --type 'print(("pdf"):upper(), 6*7)\n' --until "PDF "
check ecl "(1 4 9)" "${SIM[@]}" "$OUT"/ecl.pdf "${ECL_BOOT[@]}" --type '(mapcar (lambda (x) (* x x)) (quote (1 2 3)))\n' --until "(1 4 9)"
# stack overflow recovery: *v* is unbound back to 1, and evaluation continues
check ecl "(1 2)" "${SIM[@]}" "$OUT"/ecl.pdf "${ECL_BOOT[@]}" --type '(defun d (n) (if (= n 0) 0 (1+ (d (1- n)))))\n' \
  --type '(defvar *v* 1)\n' --type '(let ((*v* 2)) (d 100000))\n' --until "Stack overflow" --type '(list *v* (+ 1 1))\n' --until "(1 2)"
# a line longer than the 4 KB read buffer is truncated, not over-read
check ecl "(1 2)" "${SIM[@]}" "$OUT"/ecl.pdf "${ECL_BOOT[@]}" --type "(list 1 2)$(printf '%6000s' '')\n" --until "(1 2)"
check ecl "(2 8364)" "${SIM[@]}" "$OUT"/ecl.pdf "${ECL_BOOT[@]}" --type '(list (length "é€") (char-code (char "€" 0)))\n' --until "(2 "
check doom_nowad "No IWAD in this PDF" "${SIM[@]}" "$OUT"/doom_nowad.pdf --until "No IWAD"

# inject.py round trip: fill an empty slot, then list it
if [ -f "$OUT/doom_nowad.pdf" ]; then
  echo "hello" > /tmp/pdfcc_slot_test.txt
  python3 tools/inject.py "$OUT"/doom_nowad.pdf -o /tmp/pdfcc_injected.pdf --file pwad=/tmp/pdfcc_slot_test.txt >/dev/null
  if python3 tools/inject.py /tmp/pdfcc_injected.pdf --list | grep -q "pwad.*filled"; then
    echo "ok    inject"; pass=$((pass+1)); else echo "FAIL  inject"; fail=$((fail+1)); fi
fi
echo "$pass passed, $fail failed"
[ $fail = 0 ]
