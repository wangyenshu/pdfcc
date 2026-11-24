/* doomgeneric platform layer for pdfcc. Replaces doompdf's doomgeneric_pdfjs.c
 * and its hand-written pre.js: everything PDF-specific is in the pdfcc runtime. */
#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include "doomgeneric.h"
#include "doomkeys.h"
#include "pdfcc.h"

/* Typed keys (keyboard box) and on-screen buttons -> Doom keys.
 * Same scheme as doompdf: WASD move, shift+WASD (capitals) run, q = esc,
 * z = enter, e = use, space = fire, m = map. */
static int doom_key(int k) {
    switch (k) {
    case PDF_KEY_UP: case 'w': return KEY_UPARROW;
    case PDF_KEY_DOWN: case 's': return KEY_DOWNARROW;
    case PDF_KEY_LEFT: case 'a': return KEY_LEFTARROW;
    case PDF_KEY_RIGHT: case 'd': return KEY_RIGHTARROW;
    case PDF_KEY_ESCAPE: case 'q': return KEY_ESCAPE;
    case PDF_KEY_ENTER: case 'z': return KEY_ENTER;
    case 'e': return KEY_USE;
    case ' ': return KEY_FIRE;
    case 'm': return KEY_TAB;
    case ',': return KEY_STRAFE_L;
    case '.': return KEY_STRAFE_R;
    case PDF_KEY_SHIFT: return KEY_RSHIFT;
    case PDF_KEY_BACKSPACE: return KEY_BACKSPACE;
    default: break;
    }
    if (k >= PDF_KEY_F1 && k < PDF_KEY_F1 + 10) return KEY_F1 + (k - PDF_KEY_F1);
    if (k > 0 && k < 128) return tolower(k);
    return -1;
}

/* small FIFO so one typed capital can become shift + key */
static int queue[64], qhead, qtail;
static void push(int pressed, int key) {
    if (key < 0 || ((qtail + 1) & 63) == qhead) return;
    queue[qtail] = (pressed << 8) | (key & 0xff);
    qtail = (qtail + 1) & 63;
}

int DG_GetKey(int *pressed, unsigned char *key) {
    pdf_event ev;
    while (qhead == qtail && pdf_poll_event(&ev)) {
        if (ev.type != PDF_EV_KEYDOWN && ev.type != PDF_EV_KEYUP) continue;
        int down = ev.type == PDF_EV_KEYDOWN;
        int run = ev.key >= 'A' && ev.key <= 'Z' && strchr("WASD", ev.key);
        if (run && down) push(1, KEY_RSHIFT);
        push(down, doom_key(ev.key));
        if (run && !down) push(0, KEY_RSHIFT);
    }
    if (qhead == qtail) return 0;
    *pressed = queue[qhead] >> 8;
    *key = queue[qhead] & 0xff;
    qhead = (qhead + 1) & 63;
    return 1;
}

void DG_Init(void) {}
void DG_SleepMs(uint32_t ms) { (void)ms; }
uint32_t DG_GetTicksMs(void) { return pdf_ticks(); }
void DG_SetWindowTitle(const char *title) { (void)title; }

void DG_DrawFrame(void) {
    /* DG_ScreenBuffer is 0x00RRGGBB per pixel = bytes B,G,R,0 */
    pdf_present(DG_ScreenBuffer, DOOMGENERIC_RESX, DOOMGENERIC_RESY, PDF_BGRA32);
}

/* doompdf's d_main.c (non-blocking screen wipe) reads this */
int frame_count = 0;

static void tick(void) {
    static double t;
    doomgeneric_Tick();
    if (++frame_count % 35 == 0) {
        double now = pdf_now();
        printf("%.1f fps\n", 35000.0 / (now - t));
        t = now;
    }
}

int main(int argc, char **argv) {
    FILE *iwad = fopen("/doom1.wad", "rb");
    if (!iwad) {
        printf("No IWAD in this PDF. Put doom1.wad (shareware), doom.wad,\n"
               "doom2.wad or freedoom1.wad into its 'iwad' slot:\n\n"
               "  tools/inject.py doom_nowad.pdf -o doom.pdf \\\n"
               "      --file iwad=doom1.wad\n\n"
               "or open web/index.html to do it in the browser.\n");
        return 1;
    }
    fclose(iwad);
    doomgeneric_Create(argc, argv);
    pdf_run(tick, 0);
    return 0;
}
