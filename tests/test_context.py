"""Tests for quickjs.Context: eval, get/set, memory/time limits, JSON, modules, pending jobs."""

import contextlib
import gc
import json
import unittest

import quickjs


class LoadModule(unittest.TestCase):
    def test_42(self):
        self.assertEqual(quickjs.test(), 42)


class Eval(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_eval_int(self):
        self.assertEqual(self.ctx.eval("40 + 2"), 42)

    def test_eval_float(self):
        self.assertEqual(self.ctx.eval("40.0 + 2.0"), 42.0)

    def test_eval_str(self):
        self.assertEqual(self.ctx.eval("'4' + '2'"), "42")

    def test_eval_bool(self):
        self.assertEqual(self.ctx.eval("true || false"), True)
        self.assertEqual(self.ctx.eval("true && false"), False)

    def test_eval_null(self):
        self.assertIsNone(self.ctx.eval("null"))

    def test_eval_undefined(self):
        self.assertIsNone(self.ctx.eval("undefined"))

    def test_wrong_type(self):
        with self.assertRaises(TypeError):
            self.ctx.eval(1)

    def test_context_between_calls(self):
        self.ctx.eval("x = 40; y = 2;")
        self.assertEqual(self.ctx.eval("x + y"), 42)

    def test_function(self):
        self.ctx.eval("""
            function special(x) {
                return 40 + x;
            }
            """)
        self.assertEqual(self.ctx.eval("special(2)"), 42)

    def test_error(self):
        with self.assertRaisesRegex(quickjs.JSException, "ReferenceError: missing is not defined"):
            self.ctx.eval("missing + missing")

    def test_lifetime(self):
        def get_f():
            context = quickjs.Context()
            f = context.eval("""
            a = function(x) {
                return 40 + x;
            }
            """)
            return f

        f = get_f()
        self.assertTrue(f)
        # The context has left the scope after f. f needs to keep the context alive for the
        # its lifetime. Otherwise, we will get problems.

    def test_backtrace(self):
        try:
            self.ctx.eval("""
                function funcA(x) {
                    x.a.b = 1;
                }
                function funcB(x) {
                    funcA(x);
                }
                funcB({});
            """)
        except Exception as e:
            msg = str(e)
        else:
            self.fail("Expected exception.")

        self.assertIn("at funcA (<input>:3", msg)
        self.assertIn("at funcB (<input>:6", msg)

    def test_syntax_error(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval("function {")

    def test_type_error(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval("null.property")

    def test_range_error(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval("new Array(-1)")

    def test_uri_error(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval("decodeURIComponent('%')")

    def test_error_properties(self):
        try:
            self.ctx.eval("throw new TypeError('test message');")
            self.fail("Expected exception")
        except quickjs.JSException as e:
            self.assertIn("TypeError", str(e))
            self.assertIn("test message", str(e))

    def test_custom_error(self):
        with self.assertRaisesRegex(quickjs.JSException, "CustomError"):
            self.ctx.eval("""
                class CustomError extends Error {
                    constructor(msg) { super(msg); this.name = 'CustomError'; }
                }
                throw new CustomError('boom');
            """)

    def test_stack_overflow_recovery(self):
        """After a stack overflow, the context should still be usable."""
        with contextlib.suppress(quickjs.StackOverflow):
            self.ctx.eval("""
                function recurse() { return recurse(); }
                recurse();
            """)
        # Context should still work
        self.assertEqual(self.ctx.eval("1 + 1"), 2)


class GetAndSet(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_get(self):
        self.ctx.eval("x = 42; y = 'foo';")
        self.assertEqual(self.ctx.get("x"), 42)
        self.assertEqual(self.ctx.get("y"), "foo")
        self.assertEqual(self.ctx.get("z"), None)

    def test_set(self):
        self.ctx.eval("x = 'overriden'")
        self.ctx.set("x", 42)
        self.ctx.set("y", "foo")
        self.assertTrue(self.ctx.eval("x == 42"))
        self.assertTrue(self.ctx.eval("y == 'foo'"))

    def test_set_get_int(self):
        self.ctx.set("x", 42)
        self.assertEqual(self.ctx.get("x"), 42)

    def test_set_get_float(self):
        self.ctx.set("x", 3.14)
        self.assertAlmostEqual(self.ctx.get("x"), 3.14)

    def test_set_get_string(self):
        self.ctx.set("x", "hello")
        self.assertEqual(self.ctx.get("x"), "hello")

    def test_set_get_bool(self):
        self.ctx.set("x", True)
        self.assertEqual(self.ctx.get("x"), True)
        self.ctx.set("x", False)
        self.assertEqual(self.ctx.get("x"), False)

    def test_set_get_none(self):
        self.ctx.set("x", None)
        self.assertIsNone(self.ctx.get("x"))

    def test_get_nonexistent(self):
        self.assertIsNone(self.ctx.get("nonexistent"))

    def test_set_overwrite(self):
        self.ctx.set("x", 1)
        self.ctx.set("x", 2)
        self.assertEqual(self.ctx.get("x"), 2)

    def test_set_unicode(self):
        self.ctx.set("x", "日本語")
        self.assertEqual(self.ctx.get("x"), "日本語")

    def test_set_empty_string(self):
        self.ctx.set("x", "")
        self.assertEqual(self.ctx.get("x"), "")

    def test_set_large_int(self):
        self.ctx.set("x", 2**30)
        self.assertEqual(self.ctx.eval("x"), 2**30)

    def test_set_negative(self):
        self.ctx.set("x", -42)
        self.assertEqual(self.ctx.get("x"), -42)
        self.ctx.set("y", -3.14)
        self.assertAlmostEqual(self.ctx.get("y"), -3.14)

    def test_large_python_integers_to_quickjs(self):
        # Without a careful implementation, this made Python raise a SystemError/OverflowError.
        self.ctx.set("v", 10**25)
        # There is precision loss occurring in JS due to
        # the floating point implementation of numbers.
        self.assertTrue(self.ctx.eval("v == 1e25"))

    def test_symbol_conversion(self):
        self.ctx.eval("a = Symbol();")
        self.ctx.set("b", self.ctx.eval("a"))
        self.assertTrue(self.ctx.eval("a === b"))


class GlobalThis(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_global(self):
        self.ctx.set("f", self.ctx.globalThis)
        self.assertTrue(isinstance(self.ctx.globalThis, quickjs.Object))
        self.assertTrue(self.ctx.eval("f === globalThis"))
        with self.assertRaises(AttributeError):
            self.ctx.globalThis = 1

    def test_globalthis_set_var(self):
        self.ctx.eval("globalThis.myVar = 42")
        self.assertEqual(self.ctx.eval("myVar"), 42)


class MemoryAndLimits(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_memory_info_keys(self):
        mem = self.ctx.memory()
        expected_keys = ["memory_used_size", "memory_used_count", "atom_count", "str_count", "obj_count"]
        for key in expected_keys:
            self.assertIn(key, mem)

    def test_memory_limit(self):
        code = """
            (function() {
                let arr = [];
                for (let i = 0; i < 1000; ++i) {
                    arr.push(i);
                }
            })();
        """
        self.ctx.eval(code)
        self.ctx.set_memory_limit(1000)
        with self.assertRaisesRegex(quickjs.JSException, "null"):
            self.ctx.eval(code)
        self.ctx.set_memory_limit(1000000)
        self.ctx.eval(code)

    def test_memory_limit_removed(self):
        self.ctx.set_memory_limit(1024)
        self.ctx.set_memory_limit(-1)
        self.ctx.eval("new Array(100).fill('x')")

    def test_time_limit(self):
        code = """
            (function() {
                let arr = [];
                for (let i = 0; i < 100000; ++i) {
                    arr.push(i);
                }
                return arr;
            })();
        """
        self.ctx.eval(code)
        self.ctx.set_time_limit(0)
        with self.assertRaisesRegex(quickjs.JSException, "InternalError: interrupted"):
            self.ctx.eval(code)
        self.ctx.set_time_limit(-1)
        self.ctx.eval(code)

    def test_time_limit_interrupts_infinite_loop(self):
        self.ctx.set_time_limit(0.1)
        with self.assertRaisesRegex(quickjs.JSException, "InternalError: interrupted"):
            self.ctx.eval("while (true) {}")
        self.ctx.set_time_limit(-1)
        self.assertEqual(self.ctx.eval("1 + 1"), 2)

    def test_gc_manual(self):
        self.ctx.eval("""
            var a = {}; var b = {};
            a.ref = b; b.ref = a;
        """)
        before = self.ctx.memory()["obj_count"]
        self.ctx.eval("a = null; b = null;")
        self.ctx.gc()
        after = self.ctx.memory()["obj_count"]
        self.assertLess(after, before)


class PendingJobs(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_execute_pending_job(self):
        self.ctx.eval("obj = {}")
        self.assertEqual(self.ctx.execute_pending_job(), False)
        self.ctx.eval("Promise.resolve().then(() => {obj.x = 1;})")
        self.assertEqual(self.ctx.execute_pending_job(), True)
        self.assertEqual(self.ctx.eval("obj.x"), 1)
        self.assertEqual(self.ctx.execute_pending_job(), False)


class JSONParsing(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_parse_json_simple(self):
        self.assertEqual(self.ctx.parse_json("42"), 42)

    def test_parse_json_object(self):
        result = self.ctx.parse_json('{"a": 1, "b": [2, 3]}')
        self.assertTrue(isinstance(result, quickjs.Object))

    def test_parse_json_primitives(self):
        self.assertEqual(self.ctx.parse_json('"hello"'), "hello")
        self.assertEqual(self.ctx.parse_json("true"), True)
        self.assertEqual(self.ctx.parse_json("null"), None)

    def test_parse_json_error(self):
        with self.assertRaisesRegex(quickjs.JSException, "unexpected token"):
            self.ctx.parse_json("a b c")

    def test_object_json_roundtrip(self):
        obj = self.ctx.eval("({nested: {arr: [1, 'two', true, null]}})")
        data = json.loads(obj.json())
        self.assertEqual(data, {"nested": {"arr": [1, "two", True, None]}})


class ModuleSupport(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_module_basic(self):
        self.ctx.module("""
            export function hello() { return 'world'; }
        """)

    def test_module_sets_global(self):
        self.ctx.module("""
            globalThis.fromModule = 42;
        """)
        self.assertEqual(self.ctx.eval("fromModule"), 42)

    def test_module_class(self):
        self.ctx.module("""
            class Adder {
                constructor(a) { this.a = a; }
                add(b) { return this.a + b; }
            }
            globalThis.Adder = Adder;
        """)
        self.assertEqual(self.ctx.eval("new Adder(40).add(2)"), 42)


class ContextIsolation(unittest.TestCase):
    def test_separate_globals(self):
        ctx1 = quickjs.Context()
        ctx2 = quickjs.Context()
        ctx1.eval("var x = 1;")
        ctx2.eval("var x = 2;")
        self.assertEqual(ctx1.eval("x"), 1)
        self.assertEqual(ctx2.eval("x"), 2)

    def test_many_contexts(self):
        contexts = [quickjs.Context() for _ in range(50)]
        for i, ctx in enumerate(contexts):
            ctx.eval(f"var v = {i};")
        for i, ctx in enumerate(contexts):
            self.assertEqual(ctx.eval("v"), i)

    def test_context_gc(self):
        """Contexts should be garbage-collectable."""
        for _ in range(100):
            ctx = quickjs.Context()
            ctx.eval("var big = new Array(1000).fill('x');")
        gc.collect()


class QJS:
    def __init__(self):
        self.interp = quickjs.Context()
        self.interp.eval('var foo = "bar";')


class QuickJSContextInClass(unittest.TestCase):
    def test_github_issue_7(self):
        # This used to give stack overflow internal error, due to how QuickJS calculates stack
        # frames. Passes with the 2021-03-27 release.
        qjs = QJS()
        self.assertEqual(qjs.interp.eval("2+2"), 4)
