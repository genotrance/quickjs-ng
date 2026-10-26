# Test Suite

---

## Organization

The original project had a single monolithic `test_quickjs.py`. All tests were
split into six logical files:

| File | Contents |
|------|----------|
| `tests/test_callable.py` | Python-callable-from-JS tests (`add_callable`) |
| `tests/test_context.py` | Core `Context` API: eval, get/set, JSON, error handling, limits |
| `tests/test_js_features.py` | ES2020–ES2023 features, async, generators, typed arrays, RegExp, etc. |
| `tests/test_memory.py` | Memory leak detection via `tracemalloc` |
| `tests/test_object.py` | `Object` and `Function` wrapper tests |
| `tests/test_threading.py` | Threading safety tests |

---

## Test selection and local commands

`slow` (`pyproject.toml` `[tool.pytest.ini_options]`) is the only registered
pytest marker, for tests that deliberately use expensive stress, timeout, or
network behavior; this project has no `smoke` marker. Push/PR CI runs
`pytest -m "not slow"`; full scheduled, manual, release, and wheel runs use no
marker filter and include every test. CI passes `--durations=15` so the GitHub
logs record per-test time. See [ci.md](ci.md#ci-mainyml) for the exact fast and
full job matrices and when each one runs.

**No test currently qualifies.** The whole suite takes about 1.73 s, and
`test_no_memory_leak` (the only `tracemalloc` leak coverage) is a fast test that
must run on every PR, so it is not marked. A test qualifies for `slow` only when
it takes more than 5 s on CI or needs the network; check the `--durations=15`
output in the CI logs before adding the marker.

Run the same selections locally with [uv](https://docs.astral.sh/uv/):

| Command | Runs |
|---------|------|
| `uv run --locked --no-default-groups --group test python -m pytest tests -m "not slow"` | Fast set, same as push/PR CI |
| `uv run --locked --no-default-groups --group test python -m pytest tests` | Everything, same as the full matrix |
| `uv run --locked --no-default-groups --group test python -m pytest tests -m slow` | Only the `slow`-marked tests |

### Why the matrix is split

This is a small project, and GitHub's macOS (and to a lesser degree Windows)
runners are slow to queue and limited in free concurrent jobs, so the full
interpreter x OS matrix on every push would make ordinary feedback slow and
expensive. The shipped wheels are `cp310-abi3`, so a push only needs to prove
the oldest and newest supported CPython, one free-threaded build, and PyPy
still work; the full matrix — every supported interpreter on all three desktop
OSes, plus native Linux ARM — still runs before every release so nothing ships
untested, see [ci.md](ci.md#release-gate).

### Free-threaded builds (3.13t / 3.14t / 3.15t)

`setup.py` turns off the stable ABI (`Py_LIMITED_API`/abi3) when
`Py_GIL_DISABLED` is set, so free-threaded interpreters get a version-specific
extension compiled from source instead of the shared abi3 build — see
[build.md](build.md#stable-abi-detection) for how that detection works. The
full CI matrix tests 3.13t/3.14t/3.15t from source; the fast set tests 3.15t.
`cibuildwheel` skips `cp*t-*` (`pyproject.toml` `[tool.cibuildwheel]`), so no
free-threaded wheel is ever built or shipped — only the from-source CI path
exercises these interpreters.

---

## Adapted Tests

Three categories of changes were needed when porting tests from the original
`quickjs` project:

**Error message format** — quickjs-ng no longer quotes identifiers in
`ReferenceError` messages:

```python
# BEFORE
"ReferenceError: 'missing' is not defined"
# AFTER
"ReferenceError: missing is not defined"
```

**Backtrace format** — quickjs-ng includes column numbers in stack traces.
Assertions were relaxed to use prefix matching:

```python
# BEFORE
self.assertIn("at funcA (<input>:3)\n", msg)
# AFTER
self.assertIn("at funcA (<input>:3", msg)
```

**Stack overflow recursion limit** — completely redesigned to be reliable across
all platforms and architectures (Linux x86_64/i686, macOS arm64, Windows
x86_64/i686):

```python
# BEFORE — relied on default 1 MB QuickJS stack; fragile across platforms
limit = 500

# AFTER — set an explicit 64 KB JS stack; 300 frames overflows on every arch
# (64-bit: overflows at ~89 frames; 32-bit i686: overflows at ~178 frames)
f.set_max_stack_size(64 * 1024)
with self.assertRaises(quickjs.StackOverflow):
    f(300)
# Restore to 256 KB to verify recovery; fits comfortably on all platforms
f.set_max_stack_size(256 * 1024)
self.assertEqual(f(50), 50)
```

---

## JS Features Tests (`tests/test_js_features.py`)

A comprehensive test file covering modern JavaScript features:

| Test class | Features tested |
|------------|----------------|
| `ES2020Features` | Optional chaining, nullish coalescing, globalThis, Promise.allSettled, BigInt |
| `ES2021Features` | Logical assignment, numeric separators, replaceAll, Promise.any, WeakRef |
| `ES2022Features` | Class fields (public/private/static), `.at()`, Object.hasOwn, error cause, regex match indices, top-level await |
| `ES2023Features` | findLast, toReversed, toSorted, toSpliced, `.with()`, hashbang comments |
| `AsyncAndPromises` | async/await, error handling, promise chains, finally, for-await-of |
| `Generators` | Basic generators, return values, yield delegation |
| `Destructuring` | Array, object, nested, rest elements, defaults |
| `SpreadOperator` | Array spread, object spread, function argument spread |
| `TemplateLiterals` | Basic templates, tagged templates, multiline |
| `MapAndSet` | Map, Set, WeakMap |
| `ProxyAndReflect` | Proxy get/set handlers, Reflect.ownKeys |
| `Iterators` | Symbol.iterator protocol, Array.from |
| `TypedArrays` | Uint8Array, Float64Array, ArrayBuffer/DataView |
| `RegExpFeatures` | Named groups, dotAll flag, lookbehind, Unicode property escapes |
| `StringMethods` | padStart/End, trimStart/End, matchAll, unicode |
| `ObjectMethods` | entries, fromEntries, values, Object.assign |
| `StringAndBigIntRepresentations` | Rope strings (large concatenations) and short/heap BigInts converted to Python |

---

## PyPy Compatibility

### `test_memory.py` — `tracemalloc` import guard

`tracemalloc` is CPython-only and does not exist in PyPy. The module-level
`import tracemalloc` must come **after** the `pytest.skip` guard, not before:

```python
import sys

if sys.implementation.name != "cpython":
    import pytest
    pytest.skip("tracemalloc is CPython-only", allow_module_level=True)

import tracemalloc  # only reached on CPython
```

Previously the import was at the top of the file, so collection failed on PyPy
with `ModuleNotFoundError` before the skip could execute.

### `runtime_gc` — `gc.collect()` before `JS_RunGC`

PyPy uses a tracing (non-reference-counting) GC. Python-side wrapper objects
created during `eval()` calls are not freed immediately — they are only released
when Python's GC runs. If any such wrapper still holds a JS reference when
`JS_RunGC` runs its cycle scan, the objects appear live and the cycle is not
collected.

Fix: call `gc.collect()` (via the C API) before `JS_RunGC` in `runtime_gc`:

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

`PyGC_Collect` is not exported by PyPy's C API, so the portable `gc` module
route is required. On CPython, `gc.collect()` is a lightweight no-op for
non-cyclic garbage, so there is no measurable overhead.

This fixes `test_gc_manual` which creates a JS cycle (`a.ref = b; b.ref = a`)
and asserts that `ctx.gc()` reduces the `obj_count`. On PyPy without this fix,
the count stays the same; with it, the count drops as expected.

---

## Memory Leak Tests (`tests/test_memory.py`)

### Original approach

The original `check_memory.py` re-ran the entire unittest suite inside a
`tracemalloc` window. This caused:
1. **Recursive discovery** — `unittest.discover` re-executed every test file,
   causing double-execution or infinite recursion.
2. **Not pytest-compatible** — excluded from cibuildwheel test runs via
   `--ignore`, meaning the leak check never ran in CI.

### Rewritten approach

A standard pytest test function that directly exercises key APIs inside a
`tracemalloc` window:

```python
def _exercise_quickjs():
    ctx = quickjs.Context()
    ctx.eval("40 + 2")
    # ... more API calls ...
    del ctx

def test_no_memory_leak():
    _exercise_quickjs()          # warm-up (JIT caches, atom tables, etc.)
    tracemalloc.start(25)
    gc.collect()
    snapshot1 = tracemalloc.take_snapshot().filter_traces(_filters)
    _exercise_quickjs()
    gc.collect()
    snapshot2 = tracemalloc.take_snapshot().filter_traces(_filters)
    tracemalloc.stop()
    leaked = [s for s in snapshot2.compare_to(snapshot1, "traceback")
              if s.size_diff > 0]
    assert not leaked
```

Key design decisions:
- **Direct API exercise** — no test discovery; avoids recursion and is self-contained.
- **Warm-up pass** — the first call before `tracemalloc.start` lets one-time
  allocations (module import caches, atom tables) settle.
- **Filters** — traces filtered to `quickjs/` and `_quickjs` modules only.
- **`--ignore` removed** — the test now runs as part of the normal pytest suite.

---

## Threading Tests (`tests/test_threading.py`)

### Existing tests (`FunctionThreads` class)

Extracted from the original `test_quickjs.py`:

| Test | Purpose |
|------|---------|
| `test_concurrent` | `Function` is safe when called from multiple threads via a shared executor |
| `test_concurrent_own_executor` | Same, but with `own_executor=True` for separate `Function` instances |

### New tests (`ContextPerThread` class)

10 tests exercising the recommended context-per-thread pattern. Each test runs a
`target` function in 8 parallel threads, each performing 50 iterations. A
`_run_in_threads` helper propagates assertions from any thread.

| Test | What it exercises |
|------|-------------------|
| `test_eval_basic` | `eval()` with arithmetic across threads |
| `test_get_set` | `get()`/`set()` global variable isolation |
| `test_function_calls` | Define and call JS functions per thread |
| `test_add_callable` | Register and invoke Python→JS callables per thread |
| `test_parse_json` | `parse_json` + `.json()` roundtrip per thread |
| `test_memory_and_gc` | `memory()` dict inspection and `gc()` per thread |
| `test_resource_limits` | Independent `set_memory_limit`, `set_time_limit`, `set_max_stack_size` per thread |
| `test_many_contexts_concurrent` | 20 threads × 20 computations with full result verification |
| `test_context_isolation_across_threads` | `threading.Barrier`-synchronized proof that globals don't leak between contexts |
| `test_pending_jobs_per_thread` | `Promise.resolve` + `execute_pending_job` per thread |

### Design notes

- **Thread name instead of thread ident** — `threading.current_thread().ident`
  can exceed JavaScript's safe integer range (2^53) on 64-bit Linux, causing
  silent truncation when stored via `ctx.set()`. Tests use
  `threading.current_thread().name` (a string) instead.
- **No shared state** — each test creates contexts inside the thread function.
- **Barrier synchronization** — `test_context_isolation_across_threads` uses a
  `threading.Barrier` to force all threads to set their value before any thread
  reads, maximizing the chance of detecting cross-context leakage.
