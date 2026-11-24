/*
 * pdfcc.h - I/O for C programs running in a PDF viewer (PDFium/Chromium).
 *
 * output  stdout/stderr go to the terminal (VT100 subset); pdf_present()
 *         draws a grayscale image into the display.
 * input   events from the keyboard box, buttons and click grid; typed lines
 *         (pdf_read_line, or stdin).
 * time    no blocking main loop: use pdf_run() or emscripten_set_main_loop().
 *         With `pdfcc --async`, sleep() and blocking stdin reads also work.
 * files   files embedded with `pdfcc --file` are opened with fopen().
 */
#ifndef PDFCC_H
#define PDFCC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------- loop -- */

/* Call `frame` repeatedly, every `interval_ms` milliseconds (0 = as fast as
 * the viewer allows). Returns immediately: return from main() afterwards and
 * the program keeps running. Calling it again replaces the callback.
 * emscripten_set_main_loop() also works. */
void pdf_run(void (*frame)(void), int interval_ms);
void pdf_stop(void);

/* If a frame callback overflows the JavaScript call stack (deep recursion: C
 * functions run as JavaScript functions), the C stack pointer is restored and
 * `handler` is called; the loop keeps running. The handler must reset any state
 * left inconsistent by the abandoned frames. Without a handler the program stops. */
void pdf_on_stack_overflow(void (*handler)(void));

/* Milliseconds since the program started. */
double pdf_now(void);
uint32_t pdf_ticks(void);

/* With `pdfcc --async`: really sleep / yield to the viewer (lets the screen
 * update and input arrive). Without --async these return immediately. */
void pdf_sleep(int ms);
void pdf_yield(void);

/* ------------------------------------------------------------- display -- */

enum {
    PDF_RGBA32 = 0,  /* bytes R,G,B,A                                       */
    PDF_BGRA32 = 1,  /* bytes B,G,R,A (= uint32 0xAARRGGBB on little endian) */
    PDF_GRAY8  = 2,  /* one byte per pixel, 0 = black                       */
    PDF_INDEX8 = 3,  /* one byte per pixel, index into pdf_set_palette()    */
    PDF_RGB565 = 4   /* uint16 per pixel                                    */
};

/* Size of the display in the PDF (in its "pixels"), 0 if the layout has none. */
int pdf_display_width(void);
int pdf_display_height(void);

/* Show an image. Any size works: it is resampled to the display size, turned
 * to grayscale and dithered. Only rows that changed are redrawn. */
void pdf_present(const void *pixels, int width, int height, int format);
void pdf_set_palette(const uint8_t *rgb, int count); /* for PDF_INDEX8 */

/* ------------------------------------------------------------ terminal -- */
/* stdout and stderr go here. Supports \n \r \b \t and ANSI/VT100 escapes for
 * cursor movement and clearing (ESC[H, ESC[2J, ESC[K, ESC[r;cH, ...). */

int  pdf_term_cols(void);
int  pdf_term_rows(void);
void pdf_term_clear(void);
void pdf_term_goto(int row, int col);
void pdf_term_set_row(int row, const char *text); /* overwrite one row */
void pdf_term_echo(int on); /* echo typed text (line editing) - default: on
                               when the layout has no display */

/* --------------------------------------------------------------- input -- */

/* Key codes: printable ASCII as-is, plus: */
#define PDF_KEY_BACKSPACE 8
#define PDF_KEY_TAB       9
#define PDF_KEY_ENTER     13
#define PDF_KEY_ESCAPE    27
#define PDF_KEY_SPACE     32
#define PDF_KEY_UP        0x100
#define PDF_KEY_DOWN      0x101
#define PDF_KEY_LEFT      0x102
#define PDF_KEY_RIGHT     0x103
#define PDF_KEY_SHIFT     0x104
#define PDF_KEY_CTRL      0x105
#define PDF_KEY_ALT       0x106
#define PDF_KEY_F1        0x110 /* ... PDF_KEY_F1 + 11 = F12 */

enum {
    PDF_EV_KEYDOWN = 1, /* key: code                                        */
    PDF_EV_KEYUP   = 2, /* key: code (typed keys are released one frame on) */
    PDF_EV_CLICK   = 3, /* x, y: cell of the click grid that was pressed    */
    PDF_EV_RELEASE = 4, /* x, y: cell released                              */
    PDF_EV_LINE    = 5, /* a line was entered: read it with pdf_read_line() */
    PDF_EV_BUTTON  = 6  /* key: id of a layout button that has "id" not "key" */
};

typedef struct {
    int type;
    int key;
    int x, y;
} pdf_event;

/* Next pending input event; returns 0 when there is none. */
int pdf_poll_event(pdf_event *ev);
/* 1 while a key is held (on-screen button held, or typed key this frame). */
int pdf_key_down(int key);
/* Next line typed by the user, without the newline, NUL-terminated. Longer
 * lines are truncated to size-1 bytes (at a UTF-8 character boundary).
 * Non-blocking: returns the number of bytes stored, or -1 if no line is ready. */
int pdf_read_line(char *buf, int size);

/* ---------------------------------------------------------------- misc -- */

void pdf_alert(const char *message);                  /* viewer dialog box  */
void pdf_set_field(const char *name, const char *value); /* any form field  */
/* Value of a form field as UTF-8, truncated to size-1 bytes; returns the
 * number of bytes stored, or -1 if there is no such field. */
int  pdf_get_field(const char *name, char *buf, int size);
/* Run a snippet of JavaScript in the viewer (e.g. app.beep(0)). */
void pdf_eval(const char *js);

#ifdef __cplusplus
}
#endif
#endif
