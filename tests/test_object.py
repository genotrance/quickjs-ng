"""Tests for quickjs.Object and quickjs.Function wrappers."""

import json
import unittest

import quickjs


class ObjectTests(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_function_is_object(self):
        f = self.ctx.eval("""
            a = function(x) {
                return 40 + x;
            }
            """)
        self.assertIsInstance(f, quickjs.Object)

    def test_function_call_int(self):
        f = self.ctx.eval("""
            f = function(x) {
                return 40 + x;
            }
            """)
        self.assertEqual(f(2), 42)

    def test_function_call_int_two_args(self):
        f = self.ctx.eval("""
            f = function(x, y) {
                return 40 + x + y;
            }
            """)
        self.assertEqual(f(3, -1), 42)

    def test_function_call_many_times(self):
        n = 1000
        f = self.ctx.eval("""
            f = function(x, y) {
                return x + y;
            }
            """)
        s = 0
        for _i in range(n):
            s += f(1, 1)
        self.assertEqual(s, 2 * n)

    def test_function_call_str(self):
        f = self.ctx.eval("""
            f = function(a) {
                return a + " hej";
            }
            """)
        self.assertEqual(f("1"), "1 hej")

    def test_function_call_str_three_args(self):
        f = self.ctx.eval("""
            f = function(a, b, c) {
                return a + " hej " + b + " ho " + c;
            }
            """)
        self.assertEqual(f("1", "2", "3"), "1 hej 2 ho 3")

    def test_function_call_object(self):
        d = self.ctx.eval("d = {data: 42};")
        f = self.ctx.eval("""
            f = function(d) {
                return d.data;
            }
            """)
        self.assertEqual(f(d), 42)
        # Try again to make sure refcounting works.
        self.assertEqual(f(d), 42)
        self.assertEqual(f(d), 42)

    def test_function_call_unsupported_arg(self):
        f = self.ctx.eval("""
            f = function(x) {
                return 40 + x;
            }
            """)
        with self.assertRaisesRegex(TypeError, "Unsupported type"):
            self.assertEqual(f({}), 42)

    def test_json(self):
        d = self.ctx.eval("d = {data: 42};")
        self.assertEqual(json.loads(d.json()), {"data": 42})

    def test_call_nonfunction(self):
        d = self.ctx.eval("({data: 42})")
        with self.assertRaisesRegex(quickjs.JSException, "TypeError: not a function"):
            d(1)

    def test_wrong_context(self):
        context1 = quickjs.Context()
        context2 = quickjs.Context()
        f = context1.eval("(function(x) { return x.a; })")
        d = context2.eval("({a: 1})")
        with self.assertRaisesRegex(ValueError, "Can not mix JS objects from different contexts."):
            f(d)


class FunctionHelper(unittest.TestCase):
    def test_adder(self):
        f = quickjs.Function(
            "adder",
            """
            function adder(x, y) {
                return x + y;
            }
            """,
        )
        self.assertEqual(f(1, 1), 2)
        self.assertEqual(f(100, 200), 300)
        self.assertEqual(f("a", "b"), "ab")

    def test_identity(self):
        identity = quickjs.Function(
            "identity",
            """
            function identity(x) {
                return x;
            }
            """,
        )
        for x in [True, [1], {"a": 2}, 1, 1.5, "hej", None]:
            self.assertEqual(identity(x), x)

    def test_bool(self):
        f = quickjs.Function(
            "f",
            """
            function f(x) {
                return [typeof x ,!x];
            }
            """,
        )
        self.assertEqual(f(False), ["boolean", True])
        self.assertEqual(f(True), ["boolean", False])

    def test_empty(self):
        f = quickjs.Function("f", "function f() { }")
        self.assertEqual(f(), None)

    def test_lists(self):
        f = quickjs.Function(
            "f",
            """
            function f(arr) {
                const result = [];
                arr.forEach(function(elem) {
                    result.push(elem + 42);
                });
                return result;
            }""",
        )
        self.assertEqual(f([0, 1, 2]), [42, 43, 44])

    def test_dict(self):
        f = quickjs.Function(
            "f",
            """
            function f(obj) {
                return obj.data;
            }""",
        )
        self.assertEqual(f({"data": {"value": 42}}), {"value": 42})

    def test_time_limit(self):
        f = quickjs.Function(
            "f",
            """
            function f() {
                let arr = [];
                for (let i = 0; i < 100000; ++i) {
                    arr.push(i);
                }
                return arr;
            }
        """,
        )
        f()
        f.set_time_limit(0)
        with self.assertRaisesRegex(quickjs.JSException, "InternalError: interrupted"):
            f()
        f.set_time_limit(-1)
        f()

    def test_garbage_collection(self):
        f = quickjs.Function(
            "f",
            """
            function f() {
                let a = {};
                let b = {};
                a.b = b;
                b.a = a;
                a.i = 42;
                return a.i;
            }
        """,
        )
        initial_count = f.memory()["obj_count"]
        for _i in range(10):
            prev_count = f.memory()["obj_count"]
            self.assertEqual(f(run_gc=False), 42)
            current_count = f.memory()["obj_count"]
            self.assertGreater(current_count, prev_count)

        f.gc()
        self.assertLessEqual(f.memory()["obj_count"], initial_count)

    def test_deep_recursion(self):
        f = quickjs.Function(
            "f",
            """
            function f(v) {
                if (v <= 0) {
                    return 0;
                } else {
                    return 1 + f(v - 1);
                }
            }
        """,
            own_executor=True,
        )

        self.assertEqual(f(10), 10)
        # Set a tiny 64 KB JS stack.  QuickJS JS frames are ~736 bytes on
        # 64-bit platforms and ~368 bytes on 32-bit (i686) platforms, so 300
        # frames overflows 64 KB on every supported arch (64-bit: overflows at
        # ~89; 32-bit: overflows at ~178).
        f.set_max_stack_size(64 * 1024)
        with self.assertRaises(quickjs.StackOverflow):
            f(300)
        # Restore to 256 KB: that accommodates ~348 frames on 64-bit and ~696
        # on 32-bit, so f(50) succeeds comfortably on every platform.
        f.set_max_stack_size(256 * 1024)
        self.assertEqual(f(50), 50)

    def test_recursion_depth_margin(self):
        f = quickjs.Function(
            "f",
            "function f(v) { return v <= 0 ? 0 : 1 + f(v - 1); }",
            own_executor=True,
        )
        f.set_max_stack_size(256 * 1024)
        self.assertEqual(f(60), 60)

    def test_add_callable(self):
        f = quickjs.Function(
            "f",
            """
            function f() {
                return pfunc();
            }
        """,
        )
        f.add_callable("pfunc", lambda: 42)

        self.assertEqual(f(), 42)

    def test_execute_pending_job(self):
        f = quickjs.Function(
            "f",
            """
            obj = {x: 0, y: 0};
            async function a() {
                obj.x = await 1;
            }
            a();
            Promise.resolve().then(() => {obj.y = 1});
            function f() {
                return obj.x + obj.y;
            }
        """,
        )
        self.assertEqual(f(), 0)
        self.assertEqual(f.execute_pending_job(), True)
        self.assertEqual(f(), 1)
        self.assertEqual(f.execute_pending_job(), True)
        self.assertEqual(f(), 2)
        self.assertEqual(f.execute_pending_job(), False)

    def test_global(self):
        f = quickjs.Function(
            "f",
            """
            function f() {
            }
        """,
        )
        self.assertTrue(isinstance(f.globalThis, quickjs.Object))
        with self.assertRaises(AttributeError):
            f.globalThis = 1
