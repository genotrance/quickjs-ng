# C Extension (`module.c`)

This document describes the design of the `_quickjs` C extension and all changes
made during porting and subsequent improvements.

---

## Overview

`module.c` implements two Python types (`Context` and `Object`) and a module-level
`test()` function. Both types are GC-tracked so Python's cyclic garbage collector
can break reference cycles between `Context` and `Object` instances.

---

## Stable ABI Migration (cp310 / abi3)

### Motivation

By targeting the CPython **stable ABI** (`Py_LIMITED_API = 0x030A0000`), wheels
are forward-compatible with all Python ≥ 3.10. Free-threaded builds (cp313t,
cp314t) require separate wheels but benefit from the same stable API surface.

### What changes at the C level

| Old approach | Stable ABI approach |
|---|---|
| Static `PyTypeObject` struct literal | `PyType_Spec` + `PyType_FromSpec` |
| `PyObject_GC_New(T, type)` | `PyType_GetSlot(type, Py_tp_alloc)(type, 0)` |
| `PyObject_GC_Del(self)` | `PyType_GetSlot(Py_TYPE(self), Py_tp_free)(self)` |
| `PyTuple_SET_ITEM(t, i, v)` | `PyTuple_SetItem(t, i, v)` |
| `PyUnicode_AsUTF8(s)` | `PyUnicode_AsUTF8AndSize(s, &size)` |
| `Py_TYPE(x)->tp_name` | `PyObject_GetAttrString(type, "__name__")` |
| `PyObject_GC_Track(self)` manually | Removed — `tp_alloc` tracks automatically |
| `PyModule_AddObject` + manual `Py_INCREF` | `PyModule_AddObjectRef` (available from cp3.10) |
| Type globals as `static PyTypeObject` | Type globals as `static PyObject *` |
| `moduledef.m_size = sizeof(module_state)` | `moduledef.m_size = -1` (no per-module state) |

### `#define Py_LIMITED_API`

```c
// CPython Stable ABI target: 3.10+
#define Py_LIMITED_API 0x030A0000
#include <Python.h>
```

This define causes `Python.h` to expose only the stable API surface. Any use of
an unstable symbol produces a compile error, preventing accidental ABI breakage.

### Type creation via `PyType_FromSpec`

Instead of a static `PyTypeObject`, each type is defined via a slot array and spec:

```c
static PyType_Slot context_slots[] = {
    {Py_tp_doc,      "Quickjs context"},
    {Py_tp_traverse, runtime_traverse},
    {Py_tp_clear,    runtime_clear},
    {Py_tp_new,      runtime_new},
    {Py_tp_dealloc,  runtime_dealloc},
    {Py_tp_methods,  runtime_methods},
    {Py_tp_getset,   runtime_getsetters},
    {0, NULL}
};

static PyType_Spec context_spec = {
    "_quickjs.Context",
    sizeof(RuntimeData),
    0,
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    context_slots
};
```

The type object pointer is stored as `static PyObject *ContextType` and
populated in `PyInit__quickjs`:

```c
ContextType = PyType_FromSpec(&context_spec);
```

### Allocation via `PyType_GetSlot`

`PyObject_GC_New` is not in the stable ABI. Use `tp_alloc` retrieved through
`PyType_GetSlot`:

```c
static PyObject *runtime_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    allocfunc alloc = (allocfunc)PyType_GetSlot(type, Py_tp_alloc);
    RuntimeData *self = (RuntimeData *)alloc(type, 0);
    ...
}
```

Similarly for `tp_free` in `tp_dealloc`:

```c
static void runtime_dealloc(RuntimeData *self) {
    PyObject_GC_UnTrack(self);
    JS_FreeContext(self->context);
    JS_FreeRuntime(self->runtime);
    freefunc free_fn = (freefunc)PyType_GetSlot(Py_TYPE(self), Py_tp_free);
    free_fn((PyObject *)self);
}
```

**Important:** `tp_alloc` for a GC type automatically calls `PyObject_GC_Track`.
Do **not** call `PyObject_GC_Track` manually after `tp_alloc` — this causes a
double-track assertion failure.

### GC `UnTrack` in `tp_dealloc`

`PyObject_GC_UnTrack` **is** in the stable ABI. It must still be called at the
start of `tp_dealloc` before any Python-object references are cleared:

```c
static void object_dealloc(ObjectData *self) {
    PyObject_GC_UnTrack(self);   // required — in stable ABI
    if (self->runtime_data) {
        JS_FreeValue(self->runtime_data->context, self->object);
        Py_CLEAR(self->runtime_data);
    }
    freefunc free_fn = (freefunc)PyType_GetSlot(Py_TYPE(self), Py_tp_free);
    free_fn((PyObject *)self);
}
```

### Unicode to UTF-8 string conversion

Neither `PyUnicode_AsUTF8` nor `PyUnicode_AsUTF8AndSize` are in the stable ABI
before 3.10. The cp39-compatible replacement uses `PyUnicode_AsEncodedString`
(stable ABI since 3.2) to produce a temporary `bytes` object, then reads its
buffer with `PyBytes_AsStringAndSize`:

```c
// BEFORE
return JS_NewString(runtime_data->context, PyUnicode_AsUTF8(item));

// AFTER (stable ABI cp39+)
PyObject *bytes = PyUnicode_AsEncodedString(item, "utf-8", "strict");
if (!bytes) { return JS_UNDEFINED; }
Py_ssize_t size;
char *buf;
PyBytes_AsStringAndSize(bytes, &buf, &size);
JSValue result = JS_NewStringLen(runtime_data->context, buf, (size_t)size);
Py_DECREF(bytes);
return result;
```

`JS_NewStringLen` avoids a redundant `strlen` by passing the known byte length.

### `PyTuple_SetItem` instead of `PyTuple_SET_ITEM`

`PyTuple_SET_ITEM` is a macro that accesses `PyTupleObject` internals directly —
not available in the stable ABI. `PyTuple_SetItem` (the function) is used instead.
Both steal a reference to the item, so ownership semantics are identical:

```c
// BEFORE
PyTuple_SET_ITEM(args, i, arg);

// AFTER — PyTuple_SetItem steals the reference, matching our ownership of arg.
PyTuple_SetItem(args, i, arg);
```

### Type name in error messages

`Py_TYPE(x)->tp_name` accesses the opaque `PyTypeObject` struct — not available
in the stable ABI. Use `PyObject_GetAttrString` on `__name__` instead:

```c
PyObject *type_obj = (PyObject *)Py_TYPE(item);
PyObject *type_name = PyObject_GetAttrString(type_obj, "__name__");
PyErr_Format(PyExc_TypeError,
             "Unsupported type when converting a Python object to quickjs: %U.",
             type_name);
Py_XDECREF(type_name);
```

Note: `PyType_GetName` was added in 3.11 and is not usable when targeting cp310.

---

## API Changes from quickjs-ng Upstream

### `JS_NewClassID` signature change

The quickjs-ng API changed `JS_NewClassID` to require a `JSRuntime *` argument:

| Version     | Signature                                                |
|-------------|----------------------------------------------------------|
| Original    | `JSClassID JS_NewClassID(JSClassID *pclass_id)`          |
| quickjs-ng  | `JSClassID JS_NewClassID(JSRuntime *rt, JSClassID *pclass_id)` |

The call was moved from `PyInit__quickjs` (no runtime available) to `runtime_new`
(runtime just created):

```c
// AFTER (runtime_new)
self->runtime = JS_NewRuntime();
JS_NewClassID(self->runtime, &js_python_function_class_id);
self->context = JS_NewContext(self->runtime);
```

### i686 / 32-bit NaN-boxing fix

On 32-bit platforms, QuickJS uses NaN-boxing where `JSValue` is a `uint64_t`.
`JS_VALUE_GET_TAG` returns raw upper bits for floats, not the canonical
`JS_TAG_FLOAT64`. Using `JS_VALUE_GET_NORM_TAG` normalizes any float tag:

```c
// BEFORE
int tag = JS_VALUE_GET_TAG(value);

// AFTER
int tag = JS_VALUE_GET_NORM_TAG(value);
```

### Stack overflow error string

quickjs-ng changed `"stack overflow"` to `"Maximum call stack size exceeded"`.
Both patterns are matched:

```c
if (strstr(cstring, "stack overflow") != NULL ||
    strstr(cstring, "call stack size exceeded") != NULL) {
    PyErr_Format(StackOverflow, ...);
```

---

## PyPy Support

### Stable ABI exclusion

The `Py_LIMITED_API` stable ABI is CPython-specific. PyPy has its own ABI and
does not honour `Py_LIMITED_API`. `setup.py` detects the runtime and skips the
flag for non-CPython builds:

```python
_is_cpython = sys.implementation.name == "cpython"
_ext_suffix = _sc.get_config_var("EXT_SUFFIX") or ""
_freethreaded = bool(_sc.get_config_var("Py_GIL_DISABLED")) or "t-" in _ext_suffix
_use_stable_abi = _is_cpython and not _freethreaded
```

When `_use_stable_abi` is `False` (PyPy, free-threaded CPython), the
`-DPy_LIMITED_API` compile flag and `py_limited_api=True` extension option are
both omitted. The resulting `.so` carries the PyPy ABI tag
(e.g. `_quickjs.pypy310-pp73-x86_64-linux-gnu.so`) rather than `abi3`.

### `runtime_gc` — portable `gc.collect()` call

PyPy's GC is a tracing collector; Python-side objects are not freed by
reference counting. Any Python wrapper still alive when `JS_RunGC` scans the
JS heap appears as a live root, preventing cycle collection.

`runtime_gc` calls Python's `gc.collect()` via the C API before running the
JS GC, flushing any pending Python-side wrappers on both CPython and PyPy:

```c
static PyObject *runtime_gc(RuntimeData *self, PyObject *unused) {
    PyObject *gc_module = PyImport_ImportModule("gc");
    if (gc_module) {
        PyObject *result = PyObject_CallMethod(gc_module, "collect", NULL);
        Py_XDECREF(result);
        Py_DECREF(gc_module);
    } else {
        PyErr_Clear();
    }
    JS_RunGC(self->runtime);
    Py_RETURN_NONE;
}
```

`PyGC_Collect` (the C-level shortcut) is not exported by PyPy's shared library,
so the portable `gc` module route is used. On CPython the call is a near-zero-
cost no-op when there is no cyclic garbage.

---

## Windows MSVC Fixes

### `PyObject_HEAD` trailing semicolon

`PyObject_HEAD` expands to `PyObject ob_base;` — an extra `;` after it creates
an empty declaration rejected by MSVC (`C2059`):

```c
// BEFORE — invalid in MSVC C mode
typedef struct { PyObject_HEAD; RuntimeData *runtime_data; ... } ObjectData;

// AFTER
typedef struct { PyObject_HEAD RuntimeData *runtime_data; ... } ObjectData;
```

### Empty struct

MSVC rejects empty structs (`C2016`). The `module_state` struct has a dummy
member:

```c
struct module_state { int dummy; };
```

### C99 features require `/std:c11`

`module.c` uses C99 features (loop-variable declarations, designated initialisers)
that MSVC's default C89 mode rejects. Adding `/std:c11` to `extra_compile_args`
on Windows resolves all these errors.
