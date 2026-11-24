#!/bin/bash
# Installs the Emscripten toolchains used by bin/pdfcc (tested on Linux x86-64).
#
#   ./setup.sh          Emscripten 1.39.20-fastcomp -> ./emsdk (asm.js output; default)
#   ./setup.sh --async  also Emscripten 4.0.12 -> ./emsdk-upstream (wasm2js output;
#                       required for --async and --toolchain upstream)
set -e
cd "$(dirname "$0")"
chmod +x bin/pdfcc tools/*.py examples/*.sh examples/*/build.sh tests/*.sh 2>/dev/null || true

if [ ! -d emsdk ]; then
  git clone https://github.com/emscripten-core/emsdk.git --branch 1.39.20 emsdk
fi
./emsdk/emsdk install 1.39.20-fastcomp
./emsdk/emsdk activate 1.39.20-fastcomp

if [ "$1" = "--async" ]; then
  if [ ! -d emsdk-upstream ]; then
    git clone https://github.com/emscripten-core/emsdk.git emsdk-upstream
  fi
  ./emsdk-upstream/emsdk install 4.0.12
  ./emsdk-upstream/emsdk activate 4.0.12
fi

echo
echo "Done. Try:  bin/pdfcc examples/hello/hello.c -o hello.pdf"
