# Type Annotations & mypy

---

## Problem

Running `make check` (which includes `uv run mypy`) produced 16 errors:

- `import-not-found` — mypy could not locate the C extension `_quickjs` and had
  no stub to fall back on.
- `no-untyped-def` — several methods in `quickjs/__init__.py` lacked full type
  annotations.
- `valid-type` — `Object` and `Context` are module-level names assigned from the
  C extension (values, not type aliases), so mypy rejected them when used as type
  hints in `-> Object` / `Tuple[Context, Object]`.
- `no-any-return` — methods declared `-> None` used `return self._context.set_X()`,
  and `memory()` returned an untyped `Any`.

---

## Stub File (`_quickjs.pyi`)

A PEP 484 stub file at the project root (`_quickjs.pyi`) describes the C
extension's public API. mypy resolves stubs by looking for `<module>.pyi`
alongside the module, and the C extension `.so` lives at the project root, so
the stub must also live there (not inside the `quickjs/` package directory).

```python
# _quickjs.pyi
from typing import Any

class Object:
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def json(self) -> str: ...

class JSException(Exception): ...
class StackOverflow(JSException): ...

class Context:
    globalThis: Object
    def eval(self, code: str, *args: Any, **kwargs: Any) -> Any: ...
    def module(self, code: str, *args: Any, **kwargs: Any) -> Any: ...
    def get(self, name: str) -> Any: ...
    def set(self, name: str, value: Any) -> None: ...
    def parse_json(self, s: str) -> Any: ...
    def add_callable(self, global_name: str, callable: Any) -> None: ...
    def set_memory_limit(self, limit: int) -> None: ...
    def set_time_limit(self, limit: float) -> None: ...
    def set_max_stack_size(self, limit: int) -> None: ...
    def memory(self) -> dict[str, Any]: ...
    def gc(self) -> None: ...
    def execute_pending_job(self) -> bool: ...

def test() -> Any: ...
```

---

## `mypy_path` in `pyproject.toml`

```toml
[tool.mypy]
files = ["quickjs"]
mypy_path = "."
```

`mypy_path = "."` makes mypy search the project root for stubs and source files.
Without this, mypy only searches `sys.path` and the `quickjs/` package directory
and would never find `_quickjs.pyi` at the project root.

---

## Annotation Fixes in `quickjs/__init__.py`

| Location | Change |
|----------|--------|
| `from typing import ...` | Added `Any` to imports |
| `test()` | Added `-> Any` return type |
| `Function.__init__` | `own_executor=False` → `own_executor: bool = False` |
| `Function.__call__` | `*args` → `*args: Any`, `run_gc=True` → `run_gc: bool = True`, added `-> Any` |
| `set_memory_limit` | Added `limit: int` and `-> None`; removed `return` |
| `set_time_limit` | Added `limit: float` and `-> None`; removed `return` |
| `set_max_stack_size` | Added `limit: int` and `-> None`; removed `return` |
| `memory()` | Added `-> dict[str, Any]`; used explicit typed local variable |
| `gc()` | Added `-> None` |
| `execute_pending_job` | Wrapped return in `bool(...)` to satisfy `-> bool` |
| `globalThis` property | Changed `-> Object` to `-> _quickjs.Object` |
| `_compile` | Changed `Tuple[Context, Object]` to `Tuple[_quickjs.Context, _quickjs.Object]` |
| `_call` | `*args` → `*args: Any`, `run_gc=True` → `run_gc: bool = True`, added `-> Any` |
| `convert_arg` (inner) | Added `arg: Any` and `-> Any` |
