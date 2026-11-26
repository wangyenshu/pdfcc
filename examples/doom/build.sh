#!/bin/bash
# Build doom.pdf (with an IWAD inside) and doom_nowad.pdf (empty IWAD slot, fill
# it later with tools/inject.py). Usage: ./build.sh [path/to/doom1.wad]
# Without an argument, Freedoom (a free Doom-compatible IWAD) is downloaded.
set -e
cd "$(dirname "$0")"
PDFCC=../../bin/pdfcc

# doomgeneric sources, as used by doompdf (GPLv2)
if [ ! -d doomgeneric ]; then
  git clone --depth 1 https://github.com/ading2210/doompdf.git .doompdf
  mv .doompdf/doomgeneric doomgeneric && rm -rf .doompdf
fi

# doomgeneric's I_Error() ends in an endless loop, which would freeze the PDF
# viewer. Make it exit() instead (pdfcc then stops the program and shows the error).
perl -0pi -e 's/#else\n    while \(true\)\n    \{\n    \}\n#endif/#else\n    exit(-1); \/* pdfcc: was an endless loop *\/\n#endif/' doomgeneric/i_system.c

IWAD="$1"
if [ -z "$IWAD" ]; then
  IWAD=freedoom1.wad
  if [ ! -f "$IWAD" ]; then
    curl -L -o freedoom.zip https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip
    unzip -j -o freedoom.zip freedoom-0.13.0/freedoom1.wad && rm freedoom.zip
  fi
fi

SRC="dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop d_main d_mode d_net
 f_finale f_wipe g_game hu_lib hu_stuff info i_cdmus i_endoom i_joystick i_scale i_sound i_system
 i_timer memio m_argv m_bbox m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng
 p_doors p_enemy p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg p_setup
 p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data r_draw r_main r_plane r_segs r_sky
 r_things sha1 sounds statdump st_lib st_stuff s_sound tables v_video wi_stuff w_checksum w_file
 w_main w_wad z_zone w_file_stdc i_input i_video doomgeneric"
FILES=()
for f in $SRC; do FILES+=("doomgeneric/$f.c"); done
FLAGS=(-O3 -Idoomgeneric -Wno-absolute-value --memory 64)

$PDFCC "${FLAGS[@]}" "${FILES[@]}" doomgeneric_pdfcc.c -o doom.pdf --layout layout.json --file "$IWAD:/doom1.wad"
$PDFCC "${FLAGS[@]}" "${FILES[@]}" doomgeneric_pdfcc.c -o doom_nowad.pdf --layout layout.json --slot iwad:/doom1.wad
