/* Snake: emscripten_set_main_loop() and an 8-bit palette framebuffer. */
#include <emscripten.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pdfcc.h"

#define GW 32          /* grid size in cells */
#define GH 20
#define CELL 4         /* pixels per cell */
#define FW (GW * CELL)
#define FH (GH * CELL)

static unsigned char fb[FW * FH];
static int sx[GW * GH], sy[GW * GH], len, dir, next_dir, food_x, food_y, score, best, dead;
static double last_step;

static const unsigned char palette[] = {
    255, 255, 255, /* 0 background */
    20, 20, 20,    /* 1 snake      */
    120, 120, 120, /* 2 food       */
    200, 200, 200, /* 3 grid dots  */
};

static void place_food(void) {
    for (;;) {
        food_x = rand() % GW;
        food_y = rand() % GH;
        int hit = 0;
        for (int i = 0; i < len; i++) hit |= sx[i] == food_x && sy[i] == food_y;
        if (!hit) return;
    }
}

static void reset(void) {
    len = 4;
    for (int i = 0; i < len; i++) { sx[i] = GW / 2 - i; sy[i] = GH / 2; }
    dir = next_dir = 0;
    score = 0;
    dead = 0;
    place_food();
    printf("New game. Arrows/WASD to steer.\n");
}

static void cell(int cx, int cy, unsigned char color, int inset) {
    for (int y = inset; y < CELL - inset; y++)
        for (int x = inset; x < CELL - inset; x++)
            fb[(cy * CELL + y) * FW + cx * CELL + x] = color;
}

static void draw(void) {
    memset(fb, 0, sizeof fb);
    for (int y = 0; y < GH; y++)
        for (int x = 0; x < GW; x++) fb[(y * CELL + CELL / 2) * FW + x * CELL + CELL / 2] = 3;
    cell(food_x, food_y, 2, 0);
    for (int i = 0; i < len; i++) cell(sx[i], sy[i], 1, i == 0 ? 0 : (dead ? 1 : 0));
    pdf_present(fb, FW, FH, PDF_INDEX8);
}

static void step(void) {
    static const int dx[] = {1, 0, -1, 0}, dy[] = {0, 1, 0, -1};
    if ((next_dir ^ dir) != 2) dir = next_dir; /* no reversing into yourself */
    int nx = (sx[0] + dx[dir] + GW) % GW, ny = (sy[0] + dy[dir] + GH) % GH;
    for (int i = 0; i < len - 1; i++)
        if (sx[i] == nx && sy[i] == ny) {
            dead = 1;
            if (score > best) best = score;
            printf("Game over! Score %d (best %d). Press Enter or space.\n", score, best);
            return;
        }
    memmove(sx + 1, sx, sizeof(int) * len);
    memmove(sy + 1, sy, sizeof(int) * len);
    sx[0] = nx;
    sy[0] = ny;
    if (nx == food_x && ny == food_y) {
        len++;
        score += 10;
        place_food();
        printf("Score: %d\n", score);
    }
}

static void loop(void) {
    pdf_event ev;
    while (pdf_poll_event(&ev)) {
        if (ev.type != PDF_EV_KEYDOWN) continue;
        switch (ev.key) {
        case PDF_KEY_RIGHT: case 'd': case 'D': next_dir = 0; break;
        case PDF_KEY_DOWN: case 's': case 'S': next_dir = 1; break;
        case PDF_KEY_LEFT: case 'a': case 'A': next_dir = 2; break;
        case PDF_KEY_UP: case 'w': case 'W': next_dir = 3; break;
        case PDF_KEY_ENTER: case ' ': if (dead) reset(); break;
        default: break;
        }
    }
    double now = emscripten_get_now();
    if (!dead && now - last_step > 140 - (len > 30 ? 60 : len * 2)) {
        last_step = now;
        step();
    }
    draw();
}

int main(void) {
    srand((unsigned)emscripten_get_now());
    pdf_set_palette(palette, 4);
    reset();
    emscripten_set_main_loop(loop, 30, 1);
    return 0;
}
