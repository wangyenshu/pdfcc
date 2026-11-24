#!/bin/bash
# ECL (Embeddable Common Lisp) as a PDF, built with ECL's own build system.
# Needs ./setup.sh --async (Emscripten 4.x), gcc and make. Steps 1-2 run once.
set -e
cd "$(dirname "$0")"
HERE=$PWD
PDFCC=$HERE/../../bin/pdfcc
V=26.5.5
[ -f ecl-$V.tgz ] || curl -LO https://ecl.common-lisp.dev/static/files/release/ecl-$V.tgz

# 1. Native ECL of the same version; it compiles ECL's Lisp sources to C during step 2.
if [ ! -x host/bin/ecl ]; then
  rm -rf build-host && mkdir build-host && tar xzf ecl-$V.tgz -C build-host
  (cd build-host/ecl-$V && ./configure --prefix="$HERE/host" && make -j"$(nproc)" && make install)
fi

# 2. ECL for Emscripten, as in ECL's INSTALL ("Cross-compile for the WASM platform"),
#    except -O2 instead of -O0 (JS 7.9 MB instead of 30 MB, boot 4.8 s instead of 11.7 s
#    in Chrome). --spill-pointers, which lets the GC find pointers held in locals, runs
#    after the optimisations.
if [ ! -f target/libecl.a ]; then
  rm -rf build-target && mkdir build-target && tar xzf ecl-$V.tgz -C build-target
  cd build-target/ecl-$V
  sed -i 's/VARIADIC_DISPATCH -O0"/VARIADIC_DISPATCH -O2"/' src/configure
  eval "$("$PDFCC" --env --toolchain upstream)"
  export ECL_TO_RUN=$HERE/host/bin/ecl
  CFLAGS=-O2 emconfigure ./configure --host=wasm32-unknown-emscripten \
    --build="$(sh src/config.guess)" \
    --with-cross-config="$PWD/src/util/wasm32-unknown-emscripten.cross_config" \
    --prefix="$HERE/target" --disable-shared --with-tcp=no --with-cmp=no
  emmake make -j"$(nproc)"
  emmake make install
  cd "$HERE"
fi

# 3. Link libecl with the REPL front end (repl.c).
"$PDFCC" --toolchain upstream repl.c -Itarget target/libecl.a target/libeclgc.a target/libeclgmp.a \
  -O2 -sBINARYEN_EXTRA_PASSES=--spill-pointers --stack 1024 --memory 128 --memory-growth \
  -o ecl.pdf --title "ECL" --terminal 90x28 --dark \
  --subtitle "Embeddable Common Lisp $V, built with its own build system and linked with pdfcc."
