"""Tests for JavaScript language features supported by quickjs-ng.

Covers ES2020-ES2023+ features, generators, destructuring, spread, template literals,
Map/Set, Proxy/Reflect, iterators, typed arrays, RegExp, string methods, and object methods.
"""

import json
import unittest

import quickjs


class ES2020Features(unittest.TestCase):
    """Test ES2020 features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_optional_chaining(self):
        f = quickjs.Function(
            "f",
            """
            function f(x) {
                return x?.one?.two;
            }
        """,
        )
        self.assertIsNone(f({}))
        self.assertIsNone(f({"one": 12}))
        self.assertEqual(f({"one": {"two": 42}}), 42)

    def test_optional_chaining_method_call(self):
        self.ctx.eval("var obj = {greet() { return 'hello'; }}")
        self.assertEqual(self.ctx.eval("obj.greet?.()"), "hello")
        self.assertIsNone(self.ctx.eval("obj.missing?.()"))

    def test_nullish_coalescing(self):
        f = quickjs.Function(
            "f",
            """
            function f(x) {
                return x ?? 42;
            }
        """,
        )
        self.assertEqual(f(""), "")
        self.assertEqual(f(0), 0)
        self.assertEqual(f(11), 11)
        self.assertEqual(f(None), 42)

    def test_nullish_coalescing_context(self):
        self.assertEqual(self.ctx.eval("null ?? 'default'"), "default")
        self.assertEqual(self.ctx.eval("undefined ?? 'default'"), "default")
        self.assertEqual(self.ctx.eval("false ?? 'default'"), False)

    def test_promise_allsettled(self):
        self.ctx.eval("""
            var results = [];
            Promise.allSettled([
                Promise.resolve(1),
                Promise.reject('err'),
                Promise.resolve(3)
            ]).then(r => { results = r; });
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("results.length"), 3)
        self.assertEqual(self.ctx.eval("results[0].status"), "fulfilled")
        self.assertEqual(self.ctx.eval("results[0].value"), 1)
        self.assertEqual(self.ctx.eval("results[1].status"), "rejected")
        self.assertEqual(self.ctx.eval("results[1].reason"), "err")

    def test_bigint_basic(self):
        self.assertEqual(self.ctx.eval("BigInt('12345678901234567890')"), 12345678901234567890)

    def test_bigint_arithmetic(self):
        self.assertEqual(self.ctx.eval("BigInt(2) ** BigInt(64)"), 2**64)

    def test_bigint_negative(self):
        self.assertEqual(self.ctx.eval("BigInt('-999999999999999999')"), -999999999999999999)

    def test_bigint_large(self):
        self.assertEqual(self.ctx.eval(f"BigInt('{10**100}')"), 10**100)
        self.assertEqual(self.ctx.eval(f"BigInt('{-(10**100)}')"), -(10**100))


class ES2021Features(unittest.TestCase):
    """Test ES2021 features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_logical_assignment_or(self):
        self.ctx.eval("var a = null; a ||= 42;")
        self.assertEqual(self.ctx.eval("a"), 42)

    def test_logical_assignment_and(self):
        self.ctx.eval("var a = 1; a &&= 42;")
        self.assertEqual(self.ctx.eval("a"), 42)

    def test_logical_assignment_nullish(self):
        self.ctx.eval("var a = null; a ??= 42;")
        self.assertEqual(self.ctx.eval("a"), 42)
        self.ctx.eval("var b = 0; b ??= 42;")
        self.assertEqual(self.ctx.eval("b"), 0)

    def test_numeric_separators(self):
        self.assertEqual(self.ctx.eval("1_000_000"), 1000000)
        self.assertEqual(self.ctx.eval("0xFF_FF"), 65535)

    def test_string_replaceall(self):
        self.assertEqual(self.ctx.eval("'aabbcc'.replaceAll('b', 'x')"), "aaxxcc")

    def test_promise_any(self):
        self.ctx.eval("""
            var result = null;
            Promise.any([
                Promise.reject('a'),
                Promise.resolve(42),
                Promise.resolve(99)
            ]).then(v => { result = v; });
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("result"), 42)

    def test_promise_any_all_rejected(self):
        self.ctx.eval("""
            var errType = '';
            Promise.any([
                Promise.reject('a'),
                Promise.reject('b')
            ]).catch(e => { errType = e.constructor.name; });
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("errType"), "AggregateError")

    def test_weakref(self):
        result = self.ctx.eval("""
            (function() {
                var obj = {data: 42};
                var ref = new WeakRef(obj);
                return ref.deref().data;
            })()
        """)
        self.assertEqual(result, 42)


class ES2022Features(unittest.TestCase):
    """Test ES2022 features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_class_public_fields(self):
        result = self.ctx.eval("""
            class Point {
                x = 0;
                y = 0;
                constructor(x, y) { this.x = x; this.y = y; }
            }
            var p = new Point(3, 4);
            p.x + p.y;
        """)
        self.assertEqual(result, 7)

    def test_class_private_fields(self):
        result = self.ctx.eval("""
            class Counter {
                #count = 0;
                increment() { this.#count++; }
                get value() { return this.#count; }
            }
            var c = new Counter();
            c.increment();
            c.increment();
            c.increment();
            c.value;
        """)
        self.assertEqual(result, 3)

    def test_class_private_methods(self):
        result = self.ctx.eval("""
            class MyClass {
                #secret() { return 42; }
                reveal() { return this.#secret(); }
            }
            new MyClass().reveal();
        """)
        self.assertEqual(result, 42)

    def test_class_static_block(self):
        result = self.ctx.eval("""
            class Config {
                static value;
                static {
                    Config.value = 42;
                }
            }
            Config.value;
        """)
        self.assertEqual(result, 42)

    def test_top_level_await_in_module(self):
        self.ctx.module("""
            const val = await Promise.resolve(42);
            globalThis.moduleResult = val;
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("moduleResult"), 42)

    def test_at_method_array(self):
        self.assertEqual(self.ctx.eval("[10, 20, 30].at(-1)"), 30)
        self.assertEqual(self.ctx.eval("[10, 20, 30].at(0)"), 10)

    def test_at_method_string(self):
        self.assertEqual(self.ctx.eval("'hello'.at(-1)"), "o")

    def test_object_hasown(self):
        self.assertTrue(self.ctx.eval("Object.hasOwn({a: 1}, 'a')"))
        self.assertFalse(self.ctx.eval("Object.hasOwn({a: 1}, 'b')"))

    def test_error_cause(self):
        result = self.ctx.eval("""
            try {
                throw new Error('outer', {cause: new Error('inner')});
            } catch(e) {
                e.cause.message;
            }
        """)
        self.assertEqual(result, "inner")

    def test_regexp_match_indices(self):
        result = self.ctx.eval("""
            var m = /(?<year>[0-9]{4})/d.exec('2025');
            m.indices[0][0];
        """)
        self.assertEqual(result, 0)


class ES2023Features(unittest.TestCase):
    """Test ES2023 features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_array_findlast(self):
        self.assertEqual(self.ctx.eval("[1, 2, 3, 4].findLast(x => x % 2 === 0)"), 4)

    def test_array_findlastindex(self):
        self.assertEqual(self.ctx.eval("[1, 2, 3, 4].findLastIndex(x => x % 2 === 0)"), 3)

    def test_array_toreversed(self):
        result = self.ctx.eval("""
            var a = [1, 2, 3];
            var b = a.toReversed();
            JSON.stringify([a, b]);
        """)
        self.assertEqual(json.loads(result), [[1, 2, 3], [3, 2, 1]])

    def test_array_tosorted(self):
        result = self.ctx.eval("""
            var a = [3, 1, 2];
            var b = a.toSorted();
            JSON.stringify([a, b]);
        """)
        self.assertEqual(json.loads(result), [[3, 1, 2], [1, 2, 3]])

    def test_array_tospliced(self):
        result = self.ctx.eval("""
            var a = [1, 2, 3, 4];
            var b = a.toSpliced(1, 2, 'a', 'b');
            JSON.stringify(b);
        """)
        self.assertEqual(json.loads(result), [1, "a", "b", 4])

    def test_array_with(self):
        result = self.ctx.eval("""
            var a = [1, 2, 3];
            var b = a.with(1, 99);
            JSON.stringify([a, b]);
        """)
        self.assertEqual(json.loads(result), [[1, 2, 3], [1, 99, 3]])

    def test_hashbang_comment(self):
        result = self.ctx.eval("#!/usr/bin/env node\n42")
        self.assertEqual(result, 42)


class AsyncAndPromises(unittest.TestCase):
    """Test async/await and Promise functionality."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_async_await_basic(self):
        self.ctx.eval("""
            var result = 0;
            async function compute() {
                var a = await Promise.resolve(20);
                var b = await Promise.resolve(22);
                result = a + b;
            }
            compute();
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("result"), 42)

    def test_async_await_error_handling(self):
        self.ctx.eval("""
            var caught = '';
            async function failing() {
                try {
                    await Promise.reject('boom');
                } catch(e) {
                    caught = e;
                }
            }
            failing();
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("caught"), "boom")

    def test_promise_chain(self):
        self.ctx.eval("""
            var result = 0;
            Promise.resolve(1)
                .then(v => v + 1)
                .then(v => v * 21)
                .then(v => { result = v; });
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertEqual(self.ctx.eval("result"), 42)

    def test_promise_finally(self):
        self.ctx.eval("""
            var finalized = false;
            Promise.resolve(42).finally(() => { finalized = true; });
        """)
        while self.ctx.execute_pending_job():
            pass
        self.assertTrue(self.ctx.eval("finalized"))

    def test_for_await_of(self):
        self.ctx.eval("""
            var result = [];
            async function* gen() {
                yield 1;
                yield 2;
                yield 3;
            }
            async function collect() {
                for await (var v of gen()) {
                    result.push(v);
                }
            }
            collect();
        """)
        while self.ctx.execute_pending_job():
            pass
        result = json.loads(self.ctx.eval("JSON.stringify(result)"))
        self.assertEqual(result, [1, 2, 3])


class Generators(unittest.TestCase):
    """Test generator functions."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_basic_generator(self):
        result = self.ctx.eval("""
            function* count() {
                yield 1;
                yield 2;
                yield 3;
            }
            var arr = [];
            for (var v of count()) arr.push(v);
            JSON.stringify(arr);
        """)
        self.assertEqual(json.loads(result), [1, 2, 3])

    def test_generator_return(self):
        result = self.ctx.eval("""
            function* gen() {
                yield 1;
                return 42;
            }
            var g = gen();
            g.next();
            g.next().value;
        """)
        self.assertEqual(result, 42)

    def test_generator_delegation(self):
        result = self.ctx.eval("""
            function* inner() { yield 2; yield 3; }
            function* outer() { yield 1; yield* inner(); yield 4; }
            var arr = [];
            for (var v of outer()) arr.push(v);
            JSON.stringify(arr);
        """)
        self.assertEqual(json.loads(result), [1, 2, 3, 4])


class Destructuring(unittest.TestCase):
    """Test destructuring features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_array_destructuring(self):
        self.ctx.eval("var [a, b, c] = [1, 2, 3];")
        self.assertEqual(self.ctx.eval("a + b + c"), 6)

    def test_object_destructuring(self):
        self.ctx.eval("var {x, y} = {x: 10, y: 20};")
        self.assertEqual(self.ctx.eval("x + y"), 30)

    def test_nested_destructuring(self):
        self.ctx.eval("var {a: {b}} = {a: {b: 42}};")
        self.assertEqual(self.ctx.eval("b"), 42)

    def test_rest_elements(self):
        self.ctx.eval("var [first, ...rest] = [1, 2, 3, 4];")
        self.assertEqual(self.ctx.eval("first"), 1)
        result = json.loads(self.ctx.eval("JSON.stringify(rest)"))
        self.assertEqual(result, [2, 3, 4])

    def test_default_values(self):
        self.ctx.eval("var {a = 10, b = 20} = {a: 1};")
        self.assertEqual(self.ctx.eval("a"), 1)
        self.assertEqual(self.ctx.eval("b"), 20)


class SpreadOperator(unittest.TestCase):
    """Test spread operator."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_array_spread(self):
        result = json.loads(self.ctx.eval("JSON.stringify([1, ...[2, 3], 4])"))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_object_spread(self):
        result = json.loads(self.ctx.eval("JSON.stringify({a: 1, ...{b: 2, c: 3}})"))
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})

    def test_function_spread(self):
        self.ctx.eval("function sum(a, b, c) { return a + b + c; }")
        self.assertEqual(self.ctx.eval("sum(...[1, 2, 3])"), 6)


class TemplateLiterals(unittest.TestCase):
    """Test template literals."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_basic_template(self):
        self.ctx.eval("var x = 42;")
        self.assertEqual(self.ctx.eval("`value is ${x}`"), "value is 42")

    def test_tagged_template(self):
        result = self.ctx.eval("""
            function tag(strings, ...values) {
                return strings[0] + values[0] * 2;
            }
            tag`result: ${21}`;
        """)
        self.assertEqual(result, "result: 42")

    def test_multiline_template(self):
        result = self.ctx.eval("`line1\\nline2`")
        self.assertEqual(result, "line1\nline2")


class MapAndSet(unittest.TestCase):
    """Test Map and Set."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_map_basic(self):
        result = self.ctx.eval("""
            var m = new Map();
            m.set('a', 1);
            m.set('b', 2);
            m.get('a') + m.get('b');
        """)
        self.assertEqual(result, 3)

    def test_map_size(self):
        self.assertEqual(self.ctx.eval("new Map([[1,2],[3,4]]).size"), 2)

    def test_set_basic(self):
        result = self.ctx.eval("""
            var s = new Set([1, 2, 3, 2, 1]);
            s.size;
        """)
        self.assertEqual(result, 3)

    def test_set_has(self):
        self.ctx.eval("var s = new Set([1, 2, 3]);")
        self.assertTrue(self.ctx.eval("s.has(2)"))
        self.assertFalse(self.ctx.eval("s.has(4)"))

    def test_weakmap(self):
        result = self.ctx.eval("""
            var wm = new WeakMap();
            var obj = {};
            wm.set(obj, 42);
            wm.get(obj);
        """)
        self.assertEqual(result, 42)


class ProxyAndReflect(unittest.TestCase):
    """Test Proxy and Reflect."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_proxy_get(self):
        result = self.ctx.eval("""
            var handler = {
                get: function(target, prop) {
                    return prop in target ? target[prop] : 42;
                }
            };
            var p = new Proxy({a: 1}, handler);
            p.missing;
        """)
        self.assertEqual(result, 42)

    def test_proxy_set(self):
        result = self.ctx.eval("""
            var log = [];
            var handler = {
                set: function(target, prop, value) {
                    log.push(prop + '=' + value);
                    target[prop] = value;
                    return true;
                }
            };
            var p = new Proxy({}, handler);
            p.x = 1;
            p.y = 2;
            JSON.stringify(log);
        """)
        self.assertEqual(json.loads(result), ["x=1", "y=2"])

    def test_reflect_ownkeys(self):
        result = self.ctx.eval("""
            JSON.stringify(Reflect.ownKeys({a: 1, b: 2}));
        """)
        self.assertEqual(json.loads(result), ["a", "b"])


class Iterators(unittest.TestCase):
    """Test iterators and iterables."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_symbol_iterator(self):
        result = self.ctx.eval("""
            var obj = {
                [Symbol.iterator]() {
                    var i = 0;
                    return {
                        next() {
                            return i < 3 ? {value: i++, done: false} : {done: true};
                        }
                    };
                }
            };
            var arr = [];
            for (var v of obj) arr.push(v);
            JSON.stringify(arr);
        """)
        self.assertEqual(json.loads(result), [0, 1, 2])

    def test_array_from_iterable(self):
        result = self.ctx.eval("""
            JSON.stringify(Array.from({length: 3}, (_, i) => i * 2));
        """)
        self.assertEqual(json.loads(result), [0, 2, 4])


class TypedArrays(unittest.TestCase):
    """Test TypedArrays."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_uint8array(self):
        result = self.ctx.eval("""
            var a = new Uint8Array([1, 2, 3]);
            a[0] + a[1] + a[2];
        """)
        self.assertEqual(result, 6)

    def test_float64array(self):
        result = self.ctx.eval("""
            var a = new Float64Array([1.5, 2.5]);
            a[0] + a[1];
        """)
        self.assertEqual(result, 4.0)

    def test_arraybuffer(self):
        result = self.ctx.eval("""
            var buf = new ArrayBuffer(4);
            var view = new DataView(buf);
            view.setInt32(0, 42);
            view.getInt32(0);
        """)
        self.assertEqual(result, 42)


class RegExpFeatures(unittest.TestCase):
    """Test modern RegExp features."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_named_groups(self):
        self.assertEqual(
            self.ctx.eval("'2025-01-15'.match(/(?<y>\\d{4})-(?<m>\\d{2})-(?<d>\\d{2})/).groups.y"),
            "2025",
        )

    def test_dotall_flag(self):
        self.assertTrue(self.ctx.eval("/a.b/s.test('a\\nb')"))

    def test_lookbehind(self):
        self.assertEqual(self.ctx.eval("'$42'.match(/(?<=\\$)\\d+/)[0]"), "42")

    def test_unicode_property_escape(self):
        self.assertTrue(self.ctx.eval("/\\p{Letter}/u.test('ä')"))


class StringMethods(unittest.TestCase):
    """Test modern string methods."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_unicode_strings(self):
        identity = quickjs.Function(
            "identity",
            """
            function identity(x) {
                return x;
            }
            """,
        )
        for x in ["äpple", "≤≥", "☺"]:
            self.assertEqual(identity(x), x)
            self.assertEqual(self.ctx.eval('(function(){ return "' + x + '";})()'), x)

    def test_padstart(self):
        self.assertEqual(self.ctx.eval("'5'.padStart(3, '0')"), "005")

    def test_padend(self):
        self.assertEqual(self.ctx.eval("'5'.padEnd(3, '0')"), "500")

    def test_trimstart(self):
        self.assertEqual(self.ctx.eval("'  hello  '.trimStart()"), "hello  ")

    def test_trimend(self):
        self.assertEqual(self.ctx.eval("'  hello  '.trimEnd()"), "  hello")

    def test_matchall(self):
        result = self.ctx.eval("""
            var matches = [...'aAbBcC'.matchAll(/[a-z]/g)];
            JSON.stringify(matches.map(m => m[0]));
        """)
        self.assertEqual(json.loads(result), ["a", "b", "c"])


class ObjectMethods(unittest.TestCase):
    """Test modern Object methods."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_object_entries(self):
        result = json.loads(self.ctx.eval("JSON.stringify(Object.entries({a: 1, b: 2}))"))
        self.assertEqual(result, [["a", 1], ["b", 2]])

    def test_object_fromentries(self):
        result = json.loads(self.ctx.eval("JSON.stringify(Object.fromEntries([['a', 1], ['b', 2]]))"))
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_object_values(self):
        result = json.loads(self.ctx.eval("JSON.stringify(Object.values({a: 1, b: 2}))"))
        self.assertEqual(result, [1, 2])

    def test_object_assign(self):
        result = json.loads(
            self.ctx.eval("""
            var orig = {a: 1, b: 2};
            var clone = Object.assign({}, orig, {c: 3});
            JSON.stringify(clone);
        """)
        )
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})


class StringAndBigIntRepresentations(unittest.TestCase):
    """Rope strings (large concatenations) and short/heap BigInts convert to Python."""

    def setUp(self):
        self.ctx = quickjs.Context()

    def test_long_concatenated_strings(self):
        for n in (100, 8000, 8192, 8193, 20000, 100000):
            s = self.ctx.eval(f"'a'.repeat({n // 2}) + 'b'.repeat({n - n // 2})")
            self.assertEqual(s, "a" * (n // 2) + "b" * (n - n // 2))

    def test_rope_via_loop(self):
        s = self.ctx.eval("var s = ''; for (var i = 0; i < 5000; i++) s += 'xyz'; s")
        self.assertEqual(s, "xyz" * 5000)

    def test_strings_from_function_and_object(self):
        f = self.ctx.eval("(function(n) { var s = ''; for (var i = 0; i < n; i++) s += 'abc'; return s; })")
        self.assertEqual(f(10000), "abc" * 10000)
        o = self.ctx.eval("var o = {}; for (var i = 0; i < 10000; i++) o.v = (o.v || '') + 'abc'; o")
        self.assertEqual(o.json(), json.dumps({"v": "abc" * 10000}, separators=(",", ":")))

    def test_bigints(self):
        self.assertEqual(self.ctx.eval("1n"), 1)
        self.assertEqual(self.ctx.eval("-5n"), -5)
        self.assertEqual(self.ctx.eval("2n ** 62n"), 2**62)
        self.assertEqual(self.ctx.eval("-(2n ** 100n)"), -(2**100))
        self.assertEqual(self.ctx.eval("2n ** 1000n"), 2**1000)

    def test_bigint_function_roundtrip(self):
        big = self.ctx.eval("(function(s) { return BigInt(s); })")
        for v in (1, -7, 2**40, -(2**70), 2**100):
            self.assertEqual(big(str(v)), v)
        g = self.ctx.eval("(function(n) { return BigInt(n) + 1n; })")
        self.assertEqual(g(1), 2)
        self.assertEqual(self.ctx.eval("(function() { return 1n; })")(), 1)
