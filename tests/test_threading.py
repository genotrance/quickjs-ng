"""Tests for thread safety of quickjs.Function and Context-per-thread patterns."""

import concurrent.futures
import json
import subprocess
import sys
import threading
import unittest

import quickjs


class FunctionThreads(unittest.TestCase):
    """Tests for quickjs.Function used from multiple threads."""

    def setUp(self):
        self.executor = concurrent.futures.ThreadPoolExecutor()

    def tearDown(self):
        self.executor.shutdown()

    def test_concurrent(self):
        """Demonstrates that the execution will crash unless the function executes on the same
        thread every time.

        If the executor in Function is not present, this test will fail.
        """
        data = list(range(1000))
        jssum = quickjs.Function(
            "sum",
            """
                function sum(data) {
                    return data.reduce((a, b) => a + b, 0)
                }
            """,
        )

        futures = [self.executor.submit(jssum, data) for _ in range(10)]
        expected = sum(data)
        for future in concurrent.futures.as_completed(futures):
            self.assertEqual(future.result(), expected)

    def test_concurrent_own_executor(self):
        data = list(range(1000))
        jssum1 = quickjs.Function(
            "sum",
            """
                                    function sum(data) {
                                        return data.reduce((a, b) => a + b, 0)
                                    }
                                  """,
            own_executor=True,
        )
        jssum2 = quickjs.Function(
            "sum",
            """
                                    function sum(data) {
                                        return data.reduce((a, b) => a + b, 0)
                                    }
                                  """,
            own_executor=True,
        )

        futures = [self.executor.submit(f, data) for _ in range(10) for f in (jssum1, jssum2)]
        expected = sum(data)
        for future in concurrent.futures.as_completed(futures):
            self.assertEqual(future.result(), expected)


class LazyExecutor(unittest.TestCase):
    """The worker executor must be created lazily, not at import time.

    A non-daemon ThreadPoolExecutor thread created at import deadlocks
    interpreter shutdown under gevent (the concurrent.futures atexit join never
    completes in gevent's hub). Importing quickjs and using Context must spawn no
    worker thread; only creating a Function does.
    """

    def _worker_thread_count(self, snippet):
        code = (
            "import threading, quickjs\n"
            + snippet
            + "\nprint(sum('quickjs-worker' in t.name for t in threading.enumerate()))\n"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return int(out.stdout.strip().splitlines()[-1])

    def test_import_and_context_spawn_no_worker(self):
        self.assertEqual(self._worker_thread_count("quickjs.Context().eval('1 + 1')"), 0)

    def test_function_creates_worker(self):
        self.assertGreaterEqual(
            self._worker_thread_count("quickjs.Function('f', 'function f(){ return 1; }')"), 1
        )


class ContextPerThread(unittest.TestCase):
    """Tests for the recommended Context-per-thread pattern.

    Each thread creates its own Context.  Since every Context owns an independent
    JSRuntime, these tests exercise true parallel JS execution with no shared state.
    """

    NUM_THREADS = 8
    ITERATIONS = 50

    def _run_in_threads(self, target):
        """Run *target* in NUM_THREADS threads, propagating any assertion errors."""
        errors = []

        def wrapper():
            try:
                target()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=wrapper) for _ in range(self.NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise errors[0]

    def test_eval_basic(self):
        """Each thread evals simple expressions on its own Context."""

        def work():
            ctx = quickjs.Context()
            for i in range(self.ITERATIONS):
                self.assertEqual(ctx.eval(f"{i} + 1"), i + 1)

        self._run_in_threads(work)

    def test_get_set(self):
        """Each thread uses get/set on its own Context without interference."""

        def work():
            ctx = quickjs.Context()
            name = threading.current_thread().name
            ctx.set("tid", name)
            for _ in range(self.ITERATIONS):
                self.assertEqual(ctx.get("tid"), name)

        self._run_in_threads(work)

    def test_function_calls(self):
        """Each thread defines and calls JS functions on its own Context."""

        def work():
            ctx = quickjs.Context()
            ctx.eval("function add(a, b) { return a + b; }")
            add = ctx.get("add")
            for i in range(self.ITERATIONS):
                self.assertEqual(add(i, 1), i + 1)

        self._run_in_threads(work)

    def test_add_callable(self):
        """Each thread registers and invokes Python callables on its own Context."""

        def work():
            ctx = quickjs.Context()
            ctx.add_callable("double", lambda x: x * 2)
            for i in range(self.ITERATIONS):
                self.assertEqual(ctx.eval(f"double({i})"), i * 2)

        self._run_in_threads(work)

    def test_parse_json(self):
        """Each thread parses JSON on its own Context."""

        def work():
            ctx = quickjs.Context()
            for i in range(self.ITERATIONS):
                data = json.dumps({"value": i})
                obj = ctx.parse_json(data)
                self.assertEqual(json.loads(obj.json()), {"value": i})

        self._run_in_threads(work)

    def test_memory_and_gc(self):
        """Each thread queries memory and runs GC on its own Context."""

        def work():
            ctx = quickjs.Context()
            ctx.eval("var arr = [];")
            for _i in range(self.ITERATIONS):
                ctx.eval("arr.push({});")
            mem = ctx.memory()
            self.assertGreater(mem["obj_count"], 0)
            ctx.gc()

        self._run_in_threads(work)

    def test_resource_limits(self):
        """Each thread can set its own memory/time limits independently."""

        def work():
            ctx = quickjs.Context()
            ctx.set_memory_limit(4 * 1024 * 1024)
            ctx.set_time_limit(5)
            ctx.set_max_stack_size(512 * 1024)
            for i in range(self.ITERATIONS):
                self.assertEqual(ctx.eval(f"{i} * 2"), i * 2)
            ctx.set_time_limit(-1)
            ctx.set_memory_limit(-1)

        self._run_in_threads(work)

    def test_many_contexts_concurrent(self):
        """Many contexts created and used across many threads simultaneously."""
        results = {}

        def work(thread_id):
            ctx = quickjs.Context()
            ctx.eval(f"var id = {thread_id};")
            ctx.eval("function compute(x) { return id * 1000 + x; }")
            compute = ctx.get("compute")
            results[thread_id] = [compute(i) for i in range(20)]

        threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for tid, vals in results.items():
            for i, v in enumerate(vals):
                self.assertEqual(v, tid * 1000 + i)

    def test_context_isolation_across_threads(self):
        """Globals set in one thread's Context are invisible to another's."""
        barrier = threading.Barrier(self.NUM_THREADS)

        def work():
            ctx = quickjs.Context()
            name = threading.current_thread().name
            ctx.set("myvar", name)
            barrier.wait()
            self.assertEqual(ctx.get("myvar"), name)

        self._run_in_threads(work)

    def test_pending_jobs_per_thread(self):
        """Each thread can resolve promises on its own Context."""

        def work():
            ctx = quickjs.Context()
            ctx.eval("var result = 0;")
            ctx.eval("Promise.resolve(42).then(v => { result = v; });")
            self.assertTrue(ctx.execute_pending_job())
            self.assertEqual(ctx.eval("result"), 42)

        self._run_in_threads(work)
