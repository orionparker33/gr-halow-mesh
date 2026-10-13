// SPDX-License-Identifier: GPL-3.0-or-later
// Bounded soft-decision K=7, rate-1/2 Viterbi for S1G BCC.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define STATES 64
#define MAX_STEPS 1200000

static PyObject *decode(PyObject *self, PyObject *arg)
{
    (void)self;
    Py_buffer view;
    if (PyObject_GetBuffer(arg, &view, PyBUF_CONTIG_RO | PyBUF_FORMAT) != 0)
        return NULL;
    if (view.itemsize != sizeof(float) || !view.format || strcmp(view.format, "f") != 0 || view.len % (2 * sizeof(float))) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "soft input must be contiguous float32 pairs");
        return NULL;
    }
    Py_ssize_t steps = view.len / (2 * sizeof(float));
    if (steps < 1 || steps > MAX_STEPS) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Viterbi input outside bounded step range");
        return NULL;
    }
    uint8_t *decisions = PyMem_Malloc((size_t)steps * STATES);
    if (!decisions) {
        PyBuffer_Release(&view);
        return PyErr_NoMemory();
    }
    PyObject *out = PyBytes_FromStringAndSize(NULL, steps);
    if (!out) {
        PyMem_Free(decisions);
        PyBuffer_Release(&view);
        return NULL;
    }
    float old[STATES], next[STATES];
    int8_t sign0[STATES][2], sign1[STATES][2];
    for (int state = 0; state < STATES; ++state) {
        old[state] = state == 0 ? 0.0f : INFINITY;
        for (int branch = 0; branch < 2; ++branch) {
            int previous = 2 * (state & 31) + branch;
            int bit = state >> 5;
            int o0 = (bit ^ previous ^ (previous >> 1) ^ (previous >> 3) ^ (previous >> 4)) & 1;
            int o1 = (bit ^ previous ^ (previous >> 3) ^ (previous >> 4) ^ (previous >> 5)) & 1;
            sign0[state][branch] = (int8_t)(2 * o0 - 1);
            sign1[state][branch] = (int8_t)(2 * o1 - 1);
        }
    }
    const float *input = (const float *)view.buf;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t t = 0; t < steps; ++t) {
        float a = input[2*t], b = input[2*t+1];
        for (int state = 0; state < STATES; ++state) {
            int prev0 = 2 * (state & 31);
            int prev1 = prev0 + 1;
            float cost0 = old[prev0] - sign0[state][0] * a - sign1[state][0] * b;
            float cost1 = old[prev1] - sign0[state][1] * a - sign1[state][1] * b;
            uint8_t branch = cost1 < cost0;
            next[state] = branch ? cost1 : cost0;
            decisions[t*STATES+state] = branch;
        }
        memcpy(old, next, sizeof old);
    }
    int state = 0; // terminated BCC tail
    char *bits = PyBytes_AS_STRING(out);
    for (Py_ssize_t t = steps; t-- > 0;) {
        bits[t] = (char)(state >> 5);
        state = 2 * (state & 31) + decisions[t*STATES+state];
    }
    Py_END_ALLOW_THREADS
    PyMem_Free(decisions);
    PyBuffer_Release(&view);
    return out;
}

static PyMethodDef methods[] = {
    {"decode", (PyCFunction)decode, METH_O, "Decode terminated K=7 rate-1/2 soft bits."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_fec", NULL, -1, methods};
PyMODINIT_FUNC PyInit__fec(void) { return PyModule_Create(&module); }
