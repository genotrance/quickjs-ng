"""Tests for quickjs.Context.compile and quickjs.Context.eval_bytecode."""

import unittest
from pathlib import Path

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


class BytecodeSizeGuard(unittest.TestCase):
    """compile() must not pass a size above PY_SSIZE_T_MAX to PyBytes_FromStringAndSize.

    No real script reaches that size, so the private _compile_with_size_limit
    runs the same code path with a smaller limit.
    """

    SOURCE = "function add(a, b) { return a + b; } add(40, 2)"

    def setUp(self):
        self.ctx = quickjs.Context()
        self.size = len(self.ctx.compile(self.SOURCE))

    def test_limit_equal_to_size_returns_same_bytecode(self):
        code = self.ctx._compile_with_size_limit(self.SOURCE, "<input>", self.size)
        self.assertEqual(code, self.ctx.compile(self.SOURCE))
        self.assertEqual(self.ctx.eval_bytecode(code), 42)

    def test_size_over_limit_raises_overflow_error(self):
        with self.assertRaises(OverflowError) as raised:
            self.ctx._compile_with_size_limit(self.SOURCE, "<input>", self.size - 1)
        self.assertIn(str(self.size), str(raised.exception))

    def test_zero_limit_raises_overflow_error(self):
        with self.assertRaises(OverflowError):
            self.ctx._compile_with_size_limit(self.SOURCE, "<input>", 0)

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ctx._compile_with_size_limit(self.SOURCE, "<input>", -1)

    def test_overflow_frees_the_quickjs_buffer(self):
        # Warm up so atoms and caches created by the first compile are not counted.
        for _ in range(3):
            with self.assertRaises(OverflowError):
                self.ctx._compile_with_size_limit(self.SOURCE, "<input>", 0)
        self.ctx.gc()
        before = self.ctx.memory()
        for _ in range(200):
            with self.assertRaises(OverflowError):
                self.ctx._compile_with_size_limit(self.SOURCE, "<input>", 0)
        self.ctx.gc()
        after = self.ctx.memory()
        self.assertEqual(after["malloc_count"], before["malloc_count"])
        self.assertLessEqual(after["malloc_size"], before["malloc_size"])

    def test_context_is_usable_after_overflow(self):
        with self.assertRaises(OverflowError):
            self.ctx._compile_with_size_limit(self.SOURCE, "<input>", 0)
        # No QuickJS exception is left pending and the GIL path is balanced.
        self.assertEqual(self.ctx.eval("1 + 1"), 2)
        self.assertEqual(self.ctx.eval_bytecode(self.ctx.compile(self.SOURCE)), 42)

    def test_syntax_error_still_raises_js_exception(self):
        with self.assertRaises(quickjs.JSException):
            self.ctx._compile_with_size_limit("function (", "<input>", 0)

    def test_compile_name_and_limit_must_be_given(self):
        with self.assertRaises(TypeError):
            self.ctx._compile_with_size_limit(self.SOURCE)


class BytecodeTrustBoundaryDocs(unittest.TestCase):
    """eval_bytecode loads unverified bytecode; every place that documents it must say so."""

    ROOT = Path(__file__).resolve().parent.parent

    def assert_trust_warning(self, text, where):
        flat = " ".join(text.split())
        self.assertIn("trusted code", flat, where)
        self.assertIn("same QuickJS build/binary configuration", flat, where)
        self.assertIn("never load bytecode from external or untrusted data", flat.lower(), where)

    def read(self, name):
        path = self.ROOT / name
        if not path.exists():
            self.skipTest(f"{name} is not available next to the tests")
        return path.read_text(encoding="utf-8")

    def test_eval_bytecode_docstring(self):
        if quickjs.Context.eval.__doc__ is None:
            # PyPy 3.10's cpyext drops the docstrings of all C methods.
            self.skipTest("C method docstrings are not exposed by this interpreter")
        self.assert_trust_warning(quickjs.Context.eval_bytecode.__doc__ or "", "eval_bytecode docstring")

    def test_type_stub(self):
        self.assert_trust_warning(self.read("_quickjs.pyi"), "_quickjs.pyi")

    def test_readme(self):
        self.assert_trust_warning(self.read("README.md"), "README.md")

    def test_c_extension_docs(self):
        self.assert_trust_warning(self.read("docs/c-extension.md"), "docs/c-extension.md")


if __name__ == "__main__":
    unittest.main()
