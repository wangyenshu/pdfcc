# pdfcc.sty

Puts programs compiled by pdfcc into LaTeX documents. Engines: pdfLaTeX, XeLaTeX or
LuaLaTeX, from TeX Live 2023 on. As with pdfcc's own PDFs, the programs run only in
Chromium's PDF viewer.

## Files

```
tools/pdf2sty.py snake.pdf -o doc/          # any PDF made by pdfcc
bin/pdfcc snake.c -o doc/snake.pdf --latex  # or when building
```

Both write `pdfcc-NAME.tex` (layout), `pdfcc-NAME.js` (program and embedded files),
`pdfcc.sty` and `pdfcc-runtime.js` into the directory. NAME is the name the PDF was built
with (`--name`), or else its file name; `pdf2sty.py --name` sets another one. Keep the
files next to the document or in `TEXINPUTS`. Programs in one document must share the same
`pdfcc-runtime.js`, so write all of them with the same pdfcc version.

## Commands

```latex
\usepackage{pdfcc}
\pdfccload{snake}                                    % preamble or body
\pdfccload[name=calc, terminal={rows=30}]{fricas}    % a second instance gets its own name

\pdfccprogram[program=snake]       % all components, arranged as on pdfcc's page
\pdfccterminal  \pdfccdisplay  \pdfcckeyboard  \pdfccbuttons
\pdfccbutton[key=UP]{Up}  \pdfccbutton[id=7]{Go}
\pdfcctitle  \pdfccsubtitle  \pdfcchelp  \pdfccfooter   % the program's text
```

Each component is a box, so it can go anywhere a box can: a figure, minipage, tabular cell,
Beamer column or TikZ node. The terminal can sit in one place and the keyboard in another.
`program=NAME` picks the instance; without it, the component uses the last one loaded. A
component wider than `\linewidth` is scaled down to fit.

## Options

| option | in | meaning |
|---|---|---|
| `name=ID` | `\pdfccload` | instance name: lowercase letters and digits (default: the program name) |
| `args={a,b}` | `\pdfccload` | `argv` for `main` (default: the program's own) |
| `pages=auto\|all` | `\pdfccload` | pages whose opening loads the program: those that show it (default), or all pages |
| `load=each\|first` | `\pdfccload` | `first`: only the first page that shows the program loads it, and the other pages show a note until then (use for large programs shown on many pages) |
| `terminal={cols, rows, echo}` | `\pdfccload` | terminal size; whether typed text is echoed |
| `display={cols, rows, mode, dither, gamma}` | `\pdfccload` | `mode=fast\|quality`, as in pdfcc |
| `grid={cols, rows}` | `\pdfccload` | click grid over the display |
| `keyboard={placeholder=text}` | `\pdfccload` | |
| `terminal={fontsize, width, theme, background, color}` | any | `theme=light\|dark`; colors are LaTeX color expressions such as `blue!10` |
| `display={scale, width, aspect, frame}` | any | `scale` is the pixel size; `frame=false` drops the frame |
| `keyboard={width, height, fontsize}` | any | |
| `buttons={cell, fontsize}` | any | size of one grid cell (default 34bp) |
| `terminal=false`, `display=false`, `keyboard=false`, `buttons=false`, `grid=false` | placement | leave the component out (`\pdfccprogram`) |
| `show={title, subtitle, help, footer}` | `\pdfccprogram` | the program text to include (default: `help`) |
| `controls=auto\|right\|below` | `\pdfccprogram` | where keyboard, buttons and help go relative to the terminal |
| `scale=F` | placement | fixed scale factor, no fitting |
| `width=L` | placement | the width to fit into (`\pdfccprogram`), or the component's own width (single components) |
| `fit=false` | placement | do not scale down to `\linewidth` |
| `fontsize`, `height` | placement | for single components; same as the group option |
| `key=K`, `id=N` | `\pdfccbutton` | `K`: `UP`, `DOWN`, `LEFT`, `RIGHT`, `SHIFT`, `CTRL`, `ALT`, `ENTER`, `ESC`, `SPACE`, `TAB`, `BACKSPACE`, `F1`–`F12`, one character or a key code; `N`: an id for `pdf_poll_event` (`PDF_EVENT_BUTTON`) |

"any" means `\pdfccload` (the default for that instance) or a placement. Sizes are bp, or
any TeX length (`fontsize=7pt`, `width=\linewidth`).

## Behaviour

- Each instance has its own JavaScript object (`pdfcc_NAME`), its own form fields
  (`pdfcc_NAME_*`) and its own copy of the Emscripten code, so instances do not interfere.
- A component can be placed more than once, on one page or across pages (Beamer overlays).
  Every placement shows the same terminal or display and feeds the same program.
- Material that is typeset but never shipped out, such as tabularx trial runs or measuring
  boxes, leaves nothing in the PDF.
- A program loads when the first page that shows it is opened. Every other page that
  shows it parses the program's script once more when it is first opened, and then skips
  it. `load=first` avoids those extra parses.
- LuaLaTeX finds these pages while it ships them out, so one run is enough. pdfLaTeX and
  XeLaTeX read them from the `.aux` file of the previous run. Until a program is listed
  there, every page loads it. If the pages change, the log asks for a rerun.
- hyperref forms and `\DocumentMetadata` work too: pdfcc adds its fields to the existing
  AcroForm.

## Limits

- Components do not follow `\scalebox`, `\resizebox` or rotation, because annotation
  rectangles are not transformed. Use `scale=` or `width=` instead.
- Text and colors in the fields use the PDF base fonts Courier and Helvetica (WinAnsi),
  not the document's fonts.
- In Chrome 153, scrolling a focused form field out of view crashed the PDF viewer, with
  any form field (hyperref's as well). This only affects documents that scroll. Click
  outside the keyboard box before you scroll away.
