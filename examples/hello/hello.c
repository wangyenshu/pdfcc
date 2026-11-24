/* Number guessing game: plain stdio output, line input via pdf_read_line(). */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "pdfcc.h"

static int target, tries;

static void frame(void) {
    char line[64];
    if (pdf_read_line(line, sizeof line) < 0)
        return; /* nothing typed yet */
    char *end;
    long guess = strtol(line, &end, 10);
    if (end == line || *end) {
        printf("'%s' is not a number. Your guess: ", line);
        return;
    }
    tries++;
    if (guess < target)
        printf("%ld is too low. Try again: ", guess);
    else if (guess > target)
        printf("%ld is too high. Try again: ", guess);
    else {
        printf("\x1b[1m%ld is right!\x1b[0m You needed %d tries.\n\n", guess, tries);
        target = rand() % 100 + 1;
        tries = 0;
        printf("New number. Your guess: ");
    }
}

int main(void) {
    srand((unsigned)time(NULL));
    target = rand() % 100 + 1;
    printf("Hello from inside a PDF!\n");
    printf("This is C code compiled to asm.js, running in your PDF viewer.\n\n");
    printf("I'm thinking of a number between 1 and 100.\n");
    printf("Click the box on the right, type a guess and press Enter.\n\n");
    printf("Your guess: ");
    pdf_run(frame, 50);
    return 0;
}
