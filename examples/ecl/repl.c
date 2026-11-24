/* REPL for ECL (Embeddable Common Lisp) on the pdfcc runtime.
 *
 * ECL's own top level blocks on stdin. This front end embeds ECL instead:
 * cl_boot() once, then each typed line is appended to a buffer, and the buffer
 * is evaluated from a pdf_run() callback once it reads as complete forms.
 *
 * Deep recursion overflows V8's call stack (C functions are JavaScript
 * functions) before the C stack limit; in Chrome after ~530 nested interpreted
 * calls. The runtime then calls on_overflow(), which resets ECL's dynamic state
 * to what it was before the evaluation, as ecl_unwind() would. */
#include <ecl/ecl.h>
#include <stdio.h>
#include <string.h>
#include "pdfcc.h"

/* (%pdf-repl text) -> :incomplete, or evaluates every form and prints results */
static const char *REPL_DEFUN =
    "(defun %pdf-repl (bytes)"     /* bytes: base-string holding UTF-8 */
    "  (let ((text (or (ignore-errors (ext:octets-to-string"
    "                    (map '(vector (unsigned-byte 8)) #'char-code bytes) :external-format :utf-8))"
    "                  bytes))"
    "        (forms '()) (eof '#:eof))"
    "    (handler-case"
    "        (with-input-from-string (s text)"
    "          (loop for form = (read s nil eof) until (eq form eof) do (push form forms)))"
    "      (end-of-file () (return-from %pdf-repl :incomplete))"
    "      (serious-condition (c) (format t \"~&;;; Reader error: ~A~%\" c) (finish-output)"
    "        (return-from %pdf-repl :done)))"
    "    (dolist (form (nreverse forms))"
    "      (handler-case"
    "          (let ((values (multiple-value-list (eval form))))"
    "            (shiftf +++ ++ + form) (shiftf /// // / values)"
    "            (shiftf *** ** * (first values))"
    "            (fresh-line)"
    "            (let ((*print-level* 40) (*print-length* 200))"
    "              (if values (format t \"~{~S~^~%~}~%\" values) (format t \";;; No values~%\"))))"
    "        (serious-condition (c) (format t \"~&;;; ~A: ~A~%\" (type-of c) c)))"
    "      (finish-output))"
    "    :done))";

static char input[1 << 16];
static size_t input_len;
static cl_object repl_symbol;

/* ECL state saved before each evaluation, restored after a stack overflow */
static struct {
    __typeof__(((cl_env_ptr)0)->frs_stack.top) frs;
    __typeof__(((cl_env_ptr)0)->ihs_stack.top) ihs;
    cl_index bds, run;
    cl_object stack_frame;
} saved;

static void prompt(int more) { fputs(more ? "  " : "> ", stdout); }

static void on_overflow(void) {
    cl_env_ptr env = ecl_process_env();
    env->ihs_stack.top = saved.ihs;
    ecl_bds_unwind(env, saved.bds);
    ECL_STACK_UNWIND(env, saved.run);
    env->frs_stack.top = saved.frs;
    env->stack_frame = saved.stack_frame;
    env->nvalues = 0;
    env->disable_interrupts = 0;
    input_len = 0;
    printf("\n;;; Stack overflow (recursion too deep for the JavaScript stack)\n");
    prompt(0);
}

static void frame(void) {
    char line[4096];
    int n;
    while ((n = pdf_read_line(line, sizeof line)) >= 0) {
        if (input_len + n + 2 >= sizeof input) input_len = 0; /* drop oversized input */
        memcpy(input + input_len, line, n);
        input_len += n;
        input[input_len++] = '\n';

        cl_env_ptr env = ecl_process_env();
        saved.frs = env->frs_stack.top;
        saved.ihs = env->ihs_stack.top;
        saved.bds = env->bds_stack.top - env->bds_stack.org;
        saved.run = ECL_STACK_INDEX(env);
        saved.stack_frame = env->stack_frame;

        cl_object form = cl_list(2, repl_symbol, ecl_make_simple_base_string(input, (cl_fixnum)input_len));
        cl_object r = si_safe_eval(3, form, ECL_NIL, ECL_NIL);
        if (r == ecl_make_keyword("INCOMPLETE")) {
            prompt(1);
        } else {
            input_len = 0;
            prompt(0);
        }
    }
}

int main(int argc, char **argv) {
    double t0 = pdf_now();
    /* safety area used to run ECL's own STACK-OVERFLOW handler */
    ecl_set_option(ECL_OPT_C_STACK_SAFETY_AREA, 64 << 10);
    cl_boot(argc, argv);
    si_safe_eval(3, c_string_to_object(REPL_DEFUN), ECL_NIL, ECL_NIL);
    repl_symbol = c_string_to_object("%PDF-REPL");
    si_safe_eval(3, c_string_to_object(
        "(progn (format t \"~A ~A~%\" (lisp-implementation-type) (lisp-implementation-version))"
        " (finish-output))"), ECL_NIL, ECL_NIL);
    printf("Booted in %.1f s. Enter Lisp forms; a form may span several lines.\n\n",
           (pdf_now() - t0) / 1000);
    prompt(0);
    pdf_on_stack_overflow(on_overflow);
    pdf_run(frame, 30);
    return 0;
}
