#!/bin/bash
# Build the examples into examples/out/. --all also builds Lua, ECL and Doom
# (downloads; ECL takes ~20 min). blocking, Lua and ECL need ./setup.sh --async.
set -e
cd "$(dirname "$0")"
PDFCC=../bin/pdfcc
mkdir -p out

$PDFCC hello/hello.c -o out/hello.pdf --title "Hello, PDF" --terminal 72x20
$PDFCC mandelbrot/mandelbrot.c -O3 -o out/mandelbrot.pdf --layout mandelbrot/layout.json
$PDFCC snake/snake.c -o out/snake.pdf --layout snake/layout.json
$PDFCC life/life.c -o out/life.pdf --layout life/layout.json

if [ -x ../emsdk-upstream/upstream/emscripten/emcc ] || [ -n "$PDFCC_EMCC_UPSTREAM" ]; then
  $PDFCC blocking/blocking.c --async -o out/blocking.pdf --title "Plain blocking C" \
    --subtitle "fgets, sleep and scanf - no pdfcc API at all, built with --async." --terminal 64x16
  if [ "$1" = "--all" ]; then
    lua/build.sh && cp lua/lua.pdf out/
    ecl/build.sh && cp ecl/ecl.pdf out/
  fi
else
  echo "skipping async examples (run ./setup.sh --async)"
fi
if [ "$1" = "--all" ]; then
  doom/build.sh && cp doom/doom.pdf doom/doom_nowad.pdf out/
fi
ls -la out
