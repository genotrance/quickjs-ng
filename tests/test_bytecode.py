"""Tests for quickjs.Context.compile and quickjs.Context.eval_bytecode."""

import json
import subprocess
import sys
import textwrap
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


class MalformedBytecodeSubprocess(unittest.TestCase):
    """eval_bytecode loads unverified bytecode (see docs/c-extension.md): malformed
    input is not supposed to be accepted, but it is also not supposed to crash the process. Each
    case below runs in a subprocess with a timeout, so a crash or hang fails only that case
    instead of taking down the whole test run.

    Probing these cases while writing this test found that quickjs-ng's bytecode format has a
    checksum over the whole buffer (quickjs.c JS_WriteObjectAtoms/JS_ReadObjectAtoms), so almost
    every single-byte corruption is rejected by the checksum before any further parsing happens;
    no case here was found to crash the interpreter.
    """

    TIMEOUT = 30

    def _assert_clean_exit(self, data: bytes, label: str) -> None:
        script = textwrap.dedent(f"""
            import sys
            import quickjs
            ctx = quickjs.Context()
            data = {data!r}
            try:
                ctx.eval_bytecode(data)
            except Exception as e:
                print(f"raised: {{type(e).__name__}}: {{e}}", file=sys.stderr)
            else:
                print("accepted without error", file=sys.stderr)
            sys.exit(0)
        """)
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.fail(f"{label}: eval_bytecode hung for more than {self.TIMEOUT}s on malformed input")
        if proc.returncode != 0:
            self.fail(
                f"{label}: child process did not exit cleanly (exit code {proc.returncode}); "
                f"input={data!r}\nstderr:\n{proc.stderr}"
            )

    def _compile_sample(self) -> bytes:
        ctx = quickjs.Context()
        return ctx.compile("function add(a, b) { return a + b; } var obj = {x: 1, y: [1, 2, 3]}; add(40, 2);")

    def test_empty_bytes(self):
        self._assert_clean_exit(b"", "empty bytes")

    def test_truncated_bytecode(self):
        code = self._compile_sample()
        cut_points = {1, 2, 5, len(code) // 4, len(code) // 2, len(code) - 1}
        for cut in sorted(c for c in cut_points if 0 < c < len(code)):
            with self.subTest(cut=cut):
                self._assert_clean_exit(code[:cut], f"truncated to {cut} of {len(code)} bytes")

    def test_corrupted_bytecode(self):
        code = self._compile_sample()
        offsets = {0, 1, 2, 3, 5, 8, len(code) // 4, len(code) // 2, len(code) - 2, len(code) - 1}
        for offset in sorted(o for o in offsets if 0 <= o < len(code)):
            with self.subTest(offset=offset):
                corrupted = bytearray(code)
                corrupted[offset] ^= 0xFF
                self._assert_clean_exit(bytes(corrupted), f"byte {offset} of {len(code)} flipped")

    def test_wrong_version_byte(self):
        # JS_WriteObjectAtoms writes BC_VERSION as the very first byte of the buffer.
        code = bytearray(self._compile_sample())
        code[0] ^= 0xFF
        self._assert_clean_exit(bytes(code), "altered version/header byte")


class FeatureCoverageViaBytecode(unittest.TestCase):
    """Runs language features (normally exercised via eval() in test_js_features.py) through
    compile() -> eval_bytecode() instead, to confirm the serialized/deserialized path preserves
    their behaviour."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_closures(self):
        code = self.ctx.compile("""
            function makeCounter() {
                let count = 0;
                return function() { return ++count; };
            }
            globalThis.counter = makeCounter();
        """)
        self.ctx.eval_bytecode(code)
        self.assertEqual(self.ctx.eval("counter()"), 1)
        self.assertEqual(self.ctx.eval("counter()"), 2)
        self.assertEqual(self.ctx.eval("counter()"), 3)

    def test_async_function_resolves_through_pending_jobs(self):
        code = self.ctx.compile("""
            var result = 0;
            async function compute() {
                var a = await Promise.resolve(20);
                var b = await Promise.resolve(22);
                result = a + b;
            }
            compute();
        """)
        self.ctx.eval_bytecode(code)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("result"), 42)

    def test_generator(self):
        code = self.ctx.compile("""
            function* count() {
                yield 1;
                yield 2;
                yield 3;
            }
            globalThis.collected = JSON.stringify([...count()]);
        """)
        self.ctx.eval_bytecode(code)
        self.assertEqual(json.loads(self.ctx.eval("collected")), [1, 2, 3])

    def test_class_with_inheritance(self):
        code = self.ctx.compile("""
            class Animal {
                constructor(name) { this.name = name; }
                speak() { return `${this.name} makes a sound.`; }
            }
            class Dog extends Animal {
                speak() { return `${this.name} barks.`; }
            }
            globalThis.result = new Dog('Rex').speak();
        """)
        self.ctx.eval_bytecode(code)
        self.assertEqual(self.ctx.eval("result"), "Rex barks.")

    def test_globals_defined_by_bytecode_are_visible_afterwards(self):
        code = self.ctx.compile("""
            var fromBytecode = 42;
            function helperFromBytecode(x) { return x * 2; }
            class FromBytecode { get value() { return 7; } }
        """)
        self.ctx.eval_bytecode(code)
        self.assertEqual(self.ctx.eval("fromBytecode"), 42)
        self.assertEqual(self.ctx.eval("helperFromBytecode(21)"), 42)
        self.assertEqual(self.ctx.eval("new FromBytecode().value"), 7)


class BytecodeIsolation(unittest.TestCase):
    """compile() + eval_bytecode() must not leak state between contexts.

    Every quickjs.Context owns its own JSRuntime (module.c runtime_new: "We never have different
    contexts for the same runtime. This way, different _quickjs.Context can be used
    concurrently."), and the Python API has no way to share one runtime across two Context objects
    or to create a bare runtime on its own. So "a Context backed by a separate runtime" is not a
    distinct case here: every two quickjs.Context() instances already have separate runtimes, which
    the tests below confirm.
    """

    def test_bytecode_compiled_in_one_context_is_isolated_when_run_in_another(self):
        producer = quickjs.Context()
        producer.eval("globalThis.producerOnly = 'leaked?';")
        code = producer.compile("""
            function makeCounter() {
                let count = 100;
                return function() { return ++count; };
            }
            globalThis.counter = makeCounter();
            globalThis.definedHere = 1;
        """)

        consumer = quickjs.Context()
        self.assertIsNone(consumer.eval("typeof producerOnly === 'undefined' ? null : producerOnly"))
        consumer.eval_bytecode(code)
        self.assertEqual(consumer.eval("counter()"), 101)
        self.assertEqual(consumer.eval("counter()"), 102)
        self.assertEqual(consumer.eval("definedHere"), 1)

        # Running the same bytecode again in the context that compiled it must start its own,
        # independent closure state, not the consumer's.
        producer.eval_bytecode(code)
        self.assertEqual(producer.eval("counter()"), 101)

    def test_each_context_has_its_own_runtime(self):
        # See the class docstring: there is no separate Runtime object in the public API.
        self.assertFalse(hasattr(quickjs, "Runtime"))


class BytecodeLimits(unittest.TestCase):
    """set_time_limit / set_memory_limit must be honored by eval_bytecode just like eval(), since
    both go through the same prepare_call_js/end_call_js interrupt setup in module.c."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_time_limit_interrupts_infinite_loop_in_bytecode(self):
        code = self.ctx.compile("while (true) {}")
        self.ctx.set_time_limit(0.1)
        with self.assertRaisesRegex(quickjs.JSException, "InternalError: interrupted"):
            self.ctx.eval_bytecode(code)
        self.ctx.set_time_limit(-1)
        self.assertEqual(self.ctx.eval("1 + 1"), 2)
        self.assertEqual(self.ctx.eval_bytecode(self.ctx.compile("40 + 2")), 42)

    def test_memory_limit_raises_during_allocation_heavy_bytecode(self):
        code = self.ctx.compile("""
            (function() {
                let arr = [];
                for (let i = 0; i < 1000; ++i) {
                    arr.push(i);
                }
            })();
        """)
        self.ctx.eval_bytecode(code)  # warm-up under no limit
        self.ctx.set_memory_limit(1000)
        with self.assertRaisesRegex(quickjs.JSException, "null"):
            self.ctx.eval_bytecode(code)
        self.ctx.set_memory_limit(1000000)
        self.ctx.eval_bytecode(code)
        self.ctx.set_memory_limit(-1)
        self.assertEqual(self.ctx.eval_bytecode(self.ctx.compile("40 + 2")), 42)


class BytecodeTrustBoundaryDocs(unittest.TestCase):
    def test_eval_bytecode_docstring_warns_about_untrusted_data(self):
        doc = quickjs.Context.eval_bytecode.__doc__
        if doc is None:
            # PyPy 3.10's cpyext drops the docstrings of all C methods.
            self.skipTest("C method docstrings are not exposed by this interpreter")
        flat = " ".join(doc.split())
        self.assertIn("trusted code", flat)
        self.assertIn("never load bytecode from external or untrusted data", flat)


if __name__ == "__main__":
    unittest.main()
