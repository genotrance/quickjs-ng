# Test that the quickjs wrapper does not leak memory.
#
# It finds the leak if a Py_DECREF is commented out in module.c.

import contextlib
import gc
import sys

if sys.implementation.name != "cpython":
    import pytest

    pytest.skip("tracemalloc is CPython-only", allow_module_level=True)

import tracemalloc

import quickjs


def _exercise_quickjs():
    """Exercise the key quickjs APIs to detect memory leaks."""
    ctx = quickjs.Context()

    # Basic eval
    ctx.eval("40 + 2")
    ctx.eval("'hello' + ' world'")
    ctx.eval("true || false")
    ctx.eval("40.0 + 2.0")
    ctx.eval("null")
    ctx.eval("undefined")

    # Objects and functions
    ctx.eval("([1, 2, 3])")
    ctx.eval("({a: 1, b: 2})")
    func = ctx.eval("(function(x) { return x * 2; })")
    func(21)

    # Python callable from JS
    ctx.add_callable("py_add", lambda a, b: a + b)
    ctx.eval("py_add(1, 2)")

    # Get/set globals
    ctx.set("x", 42)
    ctx.get("x")
    ctx.set("s", "hello")
    ctx.get("s")

    # JSON
    ctx.eval("JSON.stringify({a: 1})")
    ctx.parse_json('{"a": 1}')

    # Exceptions
    with contextlib.suppress(quickjs.JSException):
        ctx.eval("throw new Error('test');")

    # Multiple contexts
    for _ in range(10):
        c = quickjs.Context()
        c.eval("1 + 1")
        del c

    del func
    del ctx


_filters = [
    tracemalloc.Filter(True, quickjs.__file__),
]


def test_no_memory_leak():
    """Exercise quickjs APIs twice and verify no memory is leaked."""
    # Warm up (to discount regex cache etc.)
    _exercise_quickjs()

    tracemalloc.start(25)
    gc.collect()
    snapshot1 = tracemalloc.take_snapshot().filter_traces(_filters)
    _exercise_quickjs()
    gc.collect()
    snapshot2 = tracemalloc.take_snapshot().filter_traces(_filters)
    tracemalloc.stop()

    top_stats = snapshot2.compare_to(snapshot1, "traceback")

    leaked = []
    for stat in top_stats:
        if stat.size_diff > 0:
            leaked.append(stat)

    assert not leaked, "Memory leaked in quickjs native code:\n" + "\n".join(
        f"  {stat}\n" + "\n".join(f"      {line}" for line in stat.traceback.format()) for stat in leaked
    )
