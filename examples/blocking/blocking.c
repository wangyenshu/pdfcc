/* Ordinary blocking C: fgets, scanf, sleep. No pdfcc.h needed.
 * Build with --async so the blocking calls yield to the PDF viewer. */
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char name[64];
    printf("What's your name? ");
    if (!fgets(name, sizeof name, stdin)) return 0;
    name[strcspn(name, "\n")] = 0;

    printf("Hi %s! Counting down:\n", name);
    for (int i = 3; i > 0; i--) {
        printf("%d...\n", i);
        sleep(1);
    }
    printf("Liftoff!\n\n");

    int a, b;
    printf("Type two numbers to add: ");
    while (scanf("%d %d", &a, &b) == 2)
        printf("%d + %d = %d\nTwo more: ", a, b, a + b);
    printf("bye\n");
    return 0;
}
