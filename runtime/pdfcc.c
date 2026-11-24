/* pdfcc.c - C side of the pdfcc runtime. Thin wrappers around pdfcc_runtime.js. */
#include <emscripten.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "pdfcc.h"

/* entry points called from pdfcc_runtime.js */
void pdfcc_tick(void);
void pdfcc_stack_overflow(void);

static void (*frame_fn)(void);

static void (*overflow_fn)(void);

/* Called by the JS runtime from app.setInterval. */
EMSCRIPTEN_KEEPALIVE void pdfcc_tick(void) {
    if (frame_fn) frame_fn();
}

/* Called by the JS runtime after a JavaScript stack overflow in pdfcc_tick. */
EMSCRIPTEN_KEEPALIVE void pdfcc_stack_overflow(void) {
    if (overflow_fn) overflow_fn();
}

void pdf_on_stack_overflow(void (*handler)(void)) {
    overflow_fn = handler;
    EM_ASM({ pdfcc.recoverOverflow = !!$0; }, handler);
}

/* Unbuffered stdout so prompts without a newline show up immediately. */
__attribute__((constructor)) static void pdfcc_init(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
}

void pdf_run(void (*frame)(void), int interval_ms) {
    frame_fn = frame;
    EM_ASM({ pdfcc.startLoop($0); }, interval_ms);
}

void pdf_stop(void) {
    frame_fn = 0;
    EM_ASM({ pdfcc.stopLoop(); });
}

double pdf_now(void) { return EM_ASM_DOUBLE({ return pdfcc.now(); }); }
uint32_t pdf_ticks(void) { return (uint32_t)pdf_now(); }

int pdf_display_width(void) { return EM_ASM_INT({ return pdfcc.display ? pdfcc.display.cols : 0; }); }
int pdf_display_height(void) { return EM_ASM_INT({ return pdfcc.display ? pdfcc.display.rows : 0; }); }

void pdf_present(const void *pixels, int width, int height, int format) {
    EM_ASM({ pdfcc.present($0, $1, $2, $3); }, pixels, width, height, format);
}

void pdf_set_palette(const uint8_t *rgb, int count) {
    EM_ASM({ pdfcc.setPalette($0, $1); }, rgb, count);
}

int pdf_term_cols(void) { return EM_ASM_INT({ return pdfcc.term ? pdfcc.term.cols : 0; }); }
int pdf_term_rows(void) { return EM_ASM_INT({ return pdfcc.term ? pdfcc.term.rows : 0; }); }
void pdf_term_clear(void) { fflush(stdout); EM_ASM({ pdfcc.termClear(); }); }
void pdf_term_goto(int row, int col) { fflush(stdout); EM_ASM({ pdfcc.termGoto($0, $1); }, row, col); }
void pdf_term_set_row(int row, const char *text) {
    fflush(stdout);
    EM_ASM({ pdfcc.termSetRow($0, UTF8ToString($1)); }, row, text);
}
void pdf_term_echo(int on) { EM_ASM({ pdfcc.echo = !!$0; }, on); }

int pdf_poll_event(pdf_event *ev) { return EM_ASM_INT({ return pdfcc.pollEvent($0); }, ev); }
int pdf_key_down(int key) { return EM_ASM_INT({ return pdfcc.keyState[$0] ? 1 : 0; }, key); }
int pdf_read_line(char *buf, int size) {
    return EM_ASM_INT({ return pdfcc.readLine($0, $1); }, buf, size);
}

void pdf_alert(const char *message) { EM_ASM({ app.alert(UTF8ToString($0)); }, message); }
void pdf_set_field(const char *name, const char *value) {
    EM_ASM({ var f = getField(UTF8ToString($0)); if (f) f.value = UTF8ToString($1); }, name, value);
}
int pdf_get_field(const char *name, char *buf, int size) {
    return EM_ASM_INT({
        var f = getField(UTF8ToString($0));
        if (!f || $2 < 1) return -1;
        return stringToUTF8(String(f.value), $1, $2); /* bytes stored, without the NUL */
    }, name, buf, size);
}
void pdf_eval(const char *js) { EM_ASM({ eval(UTF8ToString($0)); }, js); }

/* ------------------------------------------------------------- async -- */
#ifdef PDFCC_ASYNC
#include <errno.h>
#include <time.h>
#include <sys/uio.h>
#include <unistd.h>
#ifndef hidden
#define hidden __attribute__((__visibility__("hidden")))
#endif
#include "stdio_impl.h" /* musl internals, from emscripten/system/lib/libc/musl/src/internal */

/* durations are clamped to INT_MAX ms (~24 days) */
static int clamp_ms(long long ms) { return ms < 0 ? 0 : ms > INT_MAX ? INT_MAX : (int)ms; }

void pdf_sleep(int ms) {
    fflush(stdout);
    EM_ASM({ pdfcc.frameEnd(); });
    emscripten_sleep(ms > 0 ? ms : 0);
}
void pdf_yield(void) { pdf_sleep(0); }

/* Blocking sleeps yield to the viewer instead of busy-waiting. */
unsigned sleep(unsigned s) { pdf_sleep(clamp_ms(s * 1000LL)); return 0; }
int usleep(unsigned us) { pdf_sleep(clamp_ms(us / 1000)); return 0; }
int nanosleep(const struct timespec *req, struct timespec *rem) {
    if (!req || req->tv_sec < 0 || req->tv_nsec < 0 || req->tv_nsec >= 1000000000L) {
        errno = EINVAL;
        return -1;
    }
    pdf_sleep(clamp_ms((long long)req->tv_sec * 1000 + req->tv_nsec / 1000000));
    if (rem) rem->tv_sec = rem->tv_nsec = 0;
    return 0;
}

/* read() on stdin waits for input instead of failing with EAGAIN. */
ssize_t read(int fd, void *buf, size_t count) {
    struct iovec iov = { buf, count };
    for (;;) {
        ssize_t r = readv(fd, &iov, 1);
        if (r < 0 && errno == EAGAIN && fd == 0) { pdf_sleep(20); continue; }
        return r;
    }
}

/* musl's stdio read hook, made blocking for stdin: wait (yielding to the
 * viewer) until the user enters a line. Same logic as musl otherwise. */
size_t __stdio_read(FILE *f, unsigned char *buf, size_t len) {
    struct iovec iov[2] = {
        { .iov_base = buf, .iov_len = len - !!f->buf_size },
        { .iov_base = f->buf, .iov_len = f->buf_size }
    };
    ssize_t cnt;
    for (;;) {
        cnt = readv(f->fd, iov, 2);
        if (cnt < 0 && errno == EAGAIN && f->fd == 0) { pdf_sleep(20); continue; }
        break;
    }
    if (cnt <= 0) {
        f->flags |= F_EOF ^ ((F_ERR ^ F_EOF) & cnt);
        return cnt;
    }
    if ((size_t)cnt <= iov[0].iov_len) return cnt;
    cnt -= (ssize_t)iov[0].iov_len;
    f->rpos = f->buf;
    f->rend = f->buf + cnt;
    if (f->buf_size) buf[len - 1] = *f->rpos++;
    return len;
}
#else
void pdf_sleep(int ms) { (void)ms; }
void pdf_yield(void) {}
#endif
