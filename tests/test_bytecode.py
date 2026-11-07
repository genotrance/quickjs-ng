"""Tests for quickjs.Context.compile and quickjs.Context.eval_bytecode."""

import unittest

import quickjs


class CompileAndEvalBytecode(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()

    def test_compile_returns_bytes(self):
        code = self.ctx.compile("1 + 2")
        self.assertIsInstance(code, bytes)
        self.assertGreater(len(code), 0)

    def test_compile_does_not_run_the_script(self):
        self.ctx.compile("globalThis.ran = true")
        self.assertIsNone(self.ctx.eval("typeof globalThis.ran === 'undefined' ? null : 1"))

    def test_eval_bytecode_returns_result_like_eval(self):
        source = "40 + 2"
        self.assertEqual(self.ctx.eval_bytecode(self.ctx.compile(source)), self.ctx.eval(source))

    def test_eval_bytecode_defines_globals(self):
        self.ctx.eval_bytecode(self.ctx.compile("function add(a, b) { return a + b; }"))
        self.assertEqual(self.ctx.eval("add(40, 2)"), 42)

    def test_bytecode_runs_in_a_fresh_context(self):
        code = self.ctx.compile("var x = 6 * 7; x")
        other = quickjs.Context()
        self.assertEqual(other.eval_bytecode(code), 42)
        self.assertEqual(other.eval("x"), 42)

    def test_bytecode_can_be_run_more_than_once(self):
        code = self.ctx.compile("globalThis.counter = (globalThis.counter || 0) + 1")
        self.ctx.eval_bytecode(code)
        self.ctx.eval_bytecode(code)
        self.assertEqual(self.ctx.eval("counter"), 2)

    def test_compile_name_is_used_in_errors(self):
        code = self.ctx.compile("throw new Error('boom')", "my-script.js")
        with self.assertRaises(quickjs.JSException) as raised:
            self.ctx.eval_bytecode(code)
        self.assertIn("boom", str(raised.exception))

    def test_compile_syntax_error_raises(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.compile("function (")

    def test_eval_bytecode_runtime_error_raises(self):
        code = self.ctx.compile("undefined_function_call()")
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval_bytecode(code)

    def test_eval_bytecode_rejects_non_bytes(self):
        with self.assertRaises(TypeError):
            self.ctx.eval_bytecode("1 + 2")

    def test_eval_bytecode_rejects_garbage(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval_bytecode(b"not bytecode at all")

    def test_eval_bytecode_rejects_truncated_bytecode(self):
        code = self.ctx.compile("var a = 1; var b = 2; a + b")
        with self.assertRaises(quickjs.JSException):
            self.ctx.eval_bytecode(code[: len(code) // 2])

    def test_compile_rejects_non_str(self):
        with self.assertRaises(TypeError):
            self.ctx.compile(42)

    def test_compiled_function_with_python_callback(self):
        self.ctx.add_callable("py_double", lambda x: x * 2)
        code = self.ctx.compile("py_double(21)")
        self.assertEqual(self.ctx.eval_bytecode(code), 42)


if __name__ == "__main__":
    unittest.main()
