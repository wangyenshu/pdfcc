#!/bin/bash
# Lua 5.4 interpreter (lua.c, unmodified) as a PDF. Its REPL reads stdin with
# fgets(), so it is built with --async (needs ../../setup.sh --async).
set -e
cd "$(dirname "$0")"
[ -d lua ] || git clone --depth 1 --branch v5.4.6 https://github.com/lua/lua.git lua
../../bin/pdfcc lua/onelua.c --async -O2 -o lua.pdf \
  --title "Lua 5.4 in a PDF" \
  --subtitle "The unmodified Lua interpreter (lua.c), compiled with pdfcc --async." \
  --terminal 80x26 --dark --help-line "Click the box, type Lua, press Enter."
