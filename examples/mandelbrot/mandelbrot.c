/* Mandelbrot explorer: framebuffer output (PDF_GRAY8), keys and buttons.
 * Arrows / WASD pan, + and - zoom, p toggles a plasma animation (fps test). */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "pdfcc.h"

static int W, H;
static unsigned char *fb;
static double cx = -0.6, cy = 0.0, scale = 3.2;
static int dirty = 1, plasma = 0, frames = 0;
static double t_last;

static void render_mandelbrot(void) {
    int maxit = 48 + (int)(12 * log2(3.2 / scale));
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            double re = cx + (x - W / 2.0) * scale / W;
            double im = cy + (y - H / 2.0) * scale / W * 1.0;
            double zr = 0, zi = 0;
            int i = 0;
            while (i < maxit && zr * zr + zi * zi < 4) {
                double t = zr * zr - zi * zi + re;
                zi = 2 * zr * zi + im;
                zr = t;
                i++;
            }
            /* inside = black, outside = bright -> dark with escape time */
            fb[y * W + x] = i == maxit ? 0 : (unsigned char)(255 - 255 * sqrt((double)i / maxit));
        }
}

static void render_plasma(double t) {
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            double v = sin(x * 0.06 + t) + sin((y * 0.08 + t) * 1.3) + sin((x + y) * 0.05 + t * 0.7) +
                       sin(sqrt((x - W / 2.0) * (x - W / 2.0) + (y - H / 2.0) * (y - H / 2.0)) * 0.09 - t);
            fb[y * W + x] = (unsigned char)(127.5 + 31.8 * v);
        }
}

static void frame(void) {
    pdf_event ev;
    while (pdf_poll_event(&ev)) {
        if (ev.type != PDF_EV_KEYDOWN) continue;
        switch (ev.key) {
        case PDF_KEY_LEFT: case 'a': cx -= scale * 0.15; break;
        case PDF_KEY_RIGHT: case 'd': cx += scale * 0.15; break;
        case PDF_KEY_UP: case 'w': cy -= scale * 0.15; break;
        case PDF_KEY_DOWN: case 's': cy += scale * 0.15; break;
        case '+': case '=': scale /= 1.6; break;
        case '-': case '_': scale *= 1.6; break;
        case 'p': plasma = !plasma; frames = 0; t_last = pdf_now();
            printf(plasma ? "plasma on\n" : "plasma off\n"); break;
        default: continue;
        }
        dirty = 1;
    }
    if (plasma) {
        render_plasma(pdf_now() / 400.0);
        pdf_present(fb, W, H, PDF_GRAY8);
        if (++frames == 30) {
            double now = pdf_now();
            printf("30 frames in %.0f ms (%.1f fps)\n", now - t_last, 30000.0 / (now - t_last));
            frames = 0;
            t_last = now;
        }
    } else if (dirty) {
        double t0 = pdf_now();
        render_mandelbrot();
        double t1 = pdf_now();
        pdf_present(fb, W, H, PDF_GRAY8);
        printf("center %.5f%+.5fi  width %.2e  (compute %.0f ms, draw %.0f ms)\n",
               cx, cy, scale, t1 - t0, pdf_now() - t1);
        dirty = 0;
    }
}

int main(void) {
    W = pdf_display_width();
    H = pdf_display_height();
    fb = malloc(W * H);
    printf("Mandelbrot %dx%d. Arrows/WASD: pan  +/-: zoom  p: plasma\n", W, H);
    pdf_run(frame, 0);
    return 0;
}
