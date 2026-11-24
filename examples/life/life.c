/* Conway's Game of Life. Click cells on the display to toggle them
 * (click grid -> PDF_EV_CLICK), buttons to run/step/clear. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pdfcc.h"

#define GW 40
#define GH 25
#define CELL 4

enum { BTN_RUN = 1, BTN_STEP, BTN_CLEAR, BTN_RANDOM, BTN_GLIDER };

static unsigned char grid[GH][GW], next[GH][GW];
static unsigned char fb[GH * CELL * GW * CELL];
static int running, generation;
static double last;

static void draw(void) {
    for (int y = 0; y < GH * CELL; y++)
        for (int x = 0; x < GW * CELL; x++) {
            int edge = x % CELL == CELL - 1 || y % CELL == CELL - 1;
            fb[y * GW * CELL + x] = grid[y / CELL][x / CELL] ? (edge ? 90 : 0) : (edge ? 225 : 255);
        }
    pdf_present(fb, GW * CELL, GH * CELL, PDF_GRAY8);
}

static void step(void) {
    for (int y = 0; y < GH; y++)
        for (int x = 0; x < GW; x++) {
            int n = 0;
            for (int dy = -1; dy <= 1; dy++)
                for (int dx = -1; dx <= 1; dx++)
                    if (dx || dy) n += grid[(y + dy + GH) % GH][(x + dx + GW) % GW];
            next[y][x] = n == 3 || (n == 2 && grid[y][x]);
        }
    memcpy(grid, next, sizeof grid);
    generation++;
}

static void glider(int x, int y) {
    static const char *g[] = {".#.", "..#", "###"};
    for (int j = 0; j < 3; j++)
        for (int i = 0; i < 3; i++) grid[(y + j) % GH][(x + i) % GW] = g[j][i] == '#';
}

static void frame(void) {
    pdf_event ev;
    int changed = 0;
    while (pdf_poll_event(&ev)) {
        changed = 1;
        if (ev.type == PDF_EV_CLICK) {
            grid[ev.y][ev.x] ^= 1;
        } else if (ev.type == PDF_EV_BUTTON || ev.type == PDF_EV_KEYDOWN) {
            int k = ev.key;
            if (k == BTN_RUN || k == ' ') {
                running = !running;
                printf(running ? "running\n" : "paused at generation %d\n", generation);
            } else if (k == BTN_STEP || k == 's') {
                step();
            } else if (k == BTN_CLEAR || k == 'c') {
                memset(grid, 0, sizeof grid);
                generation = 0;
            } else if (k == BTN_RANDOM || k == 'r') {
                for (int y = 0; y < GH; y++)
                    for (int x = 0; x < GW; x++) grid[y][x] = rand() % 4 == 0;
                generation = 0;
            } else if (k == BTN_GLIDER || k == 'g') {
                glider(rand() % GW, rand() % GH);
            }
        }
    }
    if (running && pdf_now() - last > 120) {
        last = pdf_now();
        step();
        changed = 1;
    }
    if (changed) draw();
}

int main(void) {
    glider(2, 2);
    glider(12, 6);
    draw();
    printf("Game of Life %dx%d. Click cells to toggle them.\n", GW, GH);
    pdf_run(frame, 20);
    return 0;
}
