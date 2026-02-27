# Threading Model

---

## Threading Model

QuickJS runtimes are **single-threaded by design**. The `JSRuntime` struct has no
internal mutexes protecting its general state (GC lists, atom tables, stack
pointer, etc.). The only mutex in QuickJS (`js_atomics_mutex`) protects
`SharedArrayBuffer` atomics, not the runtime itself.

The C extension calls `JS_UpdateStackTop(rt)` in `prepare_call_js` before every
JS invocation. This updates `rt->stack_top` to the current thread's stack
pointer — if a different OS thread calls into the same runtime, the stack
overflow guard sees a nonsensical value and may segfault or silently corrupt
state.

---

## Safe Patterns

| Pattern | How it works | Thread-safe | Overhead |
|---------|-------------|:-----------:|---------|
| **Context per thread** | Each thread creates its own `Context` (and therefore its own `JSRuntime`). No shared state. | ✅ | None |
| **`Function` helper** | Wraps a `Context` with a dedicated single-thread executor and `threading.Lock`. All JS runs on one thread. | ✅ | Small (executor dispatch) |
| **Shared `Context`** | Multiple threads use the same `Context`. | ❌ | — |

Adding a C-level mutex to `Context` was considered and rejected:
- It would **serialize** all JS execution, removing any parallelism benefit.
- Users might assume fine-grained safety and share mutable JS state, leading to
  subtle logic bugs.
- The context-per-thread pattern gives true parallelism with zero overhead.

---

## Free-Threaded Python (3.13t / 3.14t)

When the GIL is disabled the same threading rules apply. The two safe patterns
(`Function` helper and context-per-thread) remain correct because they already
serialize access to each JS runtime independently of the GIL. The package does
not rely on the GIL for thread-safety — `prepare_call_js` explicitly releases it
before every JS call, and `end_call_js` re-acquires it afterwards. These calls
become no-ops or use lighter-weight mechanisms on free-threaded builds but do not
cause crashes.

---

## musl / Alpine Stack Size Fix (`quickjs/__init__.py`)

### Problem

The `Function` helper runs JavaScript on a dedicated `ThreadPoolExecutor` worker
thread. On glibc-based systems the default thread stack is 8 MB, but on
musl-based systems (Alpine Linux, musllinux wheels) it is only 128 KB. QuickJS's
internal stack limit defaults to 1 MB (`JS_DEFAULT_STACK_SIZE`). When JS code
recurses deeply — or the user calls `set_max_stack_size` to raise the limit — the
real C stack overflows before QuickJS's guard can fire, causing a **segfault**
instead of a clean `StackOverflow` exception.

### Fix

A `_create_executor()` helper in `quickjs/__init__.py` creates every
`ThreadPoolExecutor` with an explicit 8 MB stack:

```python
_THREAD_STACK_SIZE = 8 * 1024 * 1024  # 8 MB, matches glibc default

def _create_executor() -> concurrent.futures.ThreadPoolExecutor:
    old = threading.stack_size()
    try:
        threading.stack_size(_THREAD_STACK_SIZE)
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=prefix)
        # Force the worker to spawn now while the enlarged stack is active.
        pool.submit(lambda: None).result()
    finally:
        threading.stack_size(old)
    return pool
```

Key design decisions:

- **`threading.stack_size` is global** — it affects all threads created
  afterwards. The helper saves and restores the previous value so that unrelated
  threads are not affected.
- **Eager worker spawn** — `ThreadPoolExecutor` creates threads lazily. A no-op
  `submit().result()` forces the worker to spawn immediately while the enlarged
  stack size is in effect.
- **Named threads** — each executor gets a unique
  `thread_name_prefix="quickjs-worker-N"` for debugging.

Both the class-level shared executor and the `own_executor=True` path in
`Function.__init__` use `_create_executor()`.

### Original code (for comparison)

```python
# Original quickjs — no stack size handling
class Function:
    _threadpool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def __init__(self, name, code, *, own_executor=False):
        if own_executor:
            self._threadpool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
```
