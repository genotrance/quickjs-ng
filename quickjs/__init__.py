import concurrent.futures
import json
import threading
from collections.abc import Callable
from typing import Any

import _quickjs


def test() -> Any:
    return _quickjs.test()


Context = _quickjs.Context
Object = _quickjs.Object
JSException = _quickjs.JSException
StackOverflow = _quickjs.StackOverflow


# QuickJS's default internal stack limit is 1 MB (JS_DEFAULT_STACK_SIZE).  The
# Function helper below runs JS on a dedicated ThreadPoolExecutor worker thread.
# On glibc the default thread stack is 8 MB — plenty of headroom.  On musl-based
# systems (Alpine, musllinux wheels) the default thread stack is only 128 KB,
# which is smaller than QuickJS's own limit.  When a JS function recurses deeply
# (or the user calls set_max_stack_size to raise the limit), the real C stack
# overflows before QuickJS's guard can fire, causing a segfault.
#
# Fix: create every executor thread with an explicit 8 MB stack so behaviour is
# consistent across glibc, musl, and Windows.
_THREAD_STACK_SIZE = 8 * 1024 * 1024  # 8 MB, matches glibc default
_executor_count = 0


def _create_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Create a single-thread executor whose worker has a large enough stack.

    ``threading.stack_size`` (and the underlying ``_thread.stack_size``) is a
    global setting that affects all threads created afterwards.  We set it,
    force the worker thread to spawn immediately, then restore the previous
    value so we don't affect unrelated threads.

    On CPython/Windows ``_thread.stack_size`` sets the *commit* size passed to
    ``_beginthreadex``, so it does work — unlike the common misconception that
    it is ignored.  ``threading.stack_size`` is a thin wrapper around it and
    works the same way.
    """
    global _executor_count
    _executor_count += 1
    prefix = f"quickjs-worker-{_executor_count}"
    old = threading.stack_size()
    try:
        threading.stack_size(_THREAD_STACK_SIZE)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=prefix)
        # ThreadPoolExecutor creates threads lazily.  Submit a no-op so the
        # worker is spawned *now*, while the enlarged stack size is in effect.
        pool.submit(lambda: None).result()
    finally:
        threading.stack_size(old)
    return pool


_shared_executor: concurrent.futures.ThreadPoolExecutor | None = None
_shared_executor_lock = threading.Lock()


def _get_shared_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the process-wide worker executor, creating it on first use.

    This is created lazily rather than at import time on purpose: importing
    ``quickjs`` must not spawn a worker thread. A non-daemon
    ``ThreadPoolExecutor`` thread makes interpreter shutdown hang under gevent
    (the ``concurrent.futures`` atexit handler joins the worker, but that join
    blocks forever in gevent's hub). Code that only uses ``Context`` never
    instantiates a ``Function`` and therefore never pays for the thread.
    """
    global _shared_executor
    if _shared_executor is None:
        with _shared_executor_lock:
            if _shared_executor is None:
                _shared_executor = _create_executor()
    return _shared_executor


class Function:
    # There are unit tests demonstrating that we are crashing if different threads are accessing the
    # same runtime, even if it is not at the same time. So we run everything on the same thread in
    # order to prevent this.

    def __init__(self, name: str, code: str, *, own_executor: bool = False) -> None:
        """
        Arguments:
            name: The name of the function in the provided code that will be executed.
            code: The source code of the function and possibly helper functions, classes, global
                  variables etc.
            own_executor: Create an executor specifically for this function. The default is False in
                          order to save system resources if a large number of functions are created.
        """
        self._threadpool = _create_executor() if own_executor else _get_shared_executor()
        self._lock = threading.Lock()

        future = self._threadpool.submit(self._compile, name, code)
        concurrent.futures.wait([future])
        self._context, self._f = future.result()

    def __call__(self, *args: Any, run_gc: bool = True) -> Any:
        with self._lock:
            future = self._threadpool.submit(self._call, *args, run_gc=run_gc)
            concurrent.futures.wait([future])
            return future.result()

    def set_memory_limit(self, limit: int) -> None:
        with self._lock:
            self._context.set_memory_limit(limit)

    def set_time_limit(self, limit: float) -> None:
        with self._lock:
            self._context.set_time_limit(limit)

    def set_max_stack_size(self, limit: int) -> None:
        with self._lock:
            self._context.set_max_stack_size(limit)

    def memory(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = self._context.memory()
            return result

    def add_callable(self, global_name: str, fn: Callable) -> None:
        with self._lock:
            self._context.add_callable(global_name, fn)

    def gc(self) -> None:
        """Manually run the garbage collection.

        It will run by default when calling the function unless otherwise specified.
        """
        with self._lock:
            self._context.gc()

    def execute_pending_job(self) -> bool:
        with self._lock:
            return bool(self._context.execute_pending_job())

    @property
    def globalThis(self) -> _quickjs.Object:
        with self._lock:
            return self._context.globalThis

    def _compile(self, name: str, code: str) -> tuple[_quickjs.Context, _quickjs.Object]:
        context = Context()
        context.eval(code)
        f = context.get(name)
        return context, f

    def _call(self, *args: Any, run_gc: bool = True) -> Any:
        def convert_arg(arg: Any) -> Any:
            if isinstance(arg, (type(None), str, bool, float, int)):
                return arg
            else:
                # More complex objects are passed through JSON.
                return self._context.parse_json(json.dumps(arg))

        try:
            result = self._f(*[convert_arg(a) for a in args])
            if isinstance(result, Object):
                result = json.loads(result.json())
            return result
        finally:
            if run_gc:
                self._context.gc()
