# Build System

---

## `setup.py`

`setup.py` is minimal — it only defines the C extension. All package metadata
lives in `pyproject.toml`.

### C source files

| File | Purpose |
|------|---------|
| `module.c` | Python C extension — all type and module definitions |
| `upstream-quickjs/dtoa.c` | Float-to-string conversion (new in quickjs-ng) |
| `upstream-quickjs/libregexp.c` | Regular expression engine |
| `upstream-quickjs/libunicode.c` | Unicode tables |
| `upstream-quickjs/quickjs.c` | Core JS engine |

Removed from original:

| File | Reason |
|------|--------|
| `upstream-quickjs/cutils.c` | Merged into other files in quickjs-ng |
| `upstream-quickjs/libbf.c` | BigNum (`CONFIG_BIGNUM`) removed upstream |

### Stable ABI detection

`setup.py` detects at build time whether the stable ABI (`Py_LIMITED_API`) can
be used. It is only valid for CPython non-free-threaded builds:

```python
_is_cpython = sys.implementation.name == "cpython"
_ext_suffix = _sc.get_config_var("EXT_SUFFIX") or ""
_freethreaded = bool(_sc.get_config_var("Py_GIL_DISABLED")) or "t-" in _ext_suffix
_use_stable_abi = _is_cpython and not _freethreaded
```

| Runtime | `_use_stable_abi` | Reason |
|---------|:-----------------:|---------|
| CPython 3.10–3.14 | `True` | Standard case |
| CPython 3.13t / 3.14t (free-threaded) | `False` | `Py_LIMITED_API` incompatible with `Py_GIL_DISABLED` |
| PyPy | `False` | PyPy has its own ABI; does not honour `Py_LIMITED_API` |

### Compile flags

```python
if sys.platform == "win32":
    extra_link_args = ["-static"]
    extra_compile_args = ["/std:c11"]
    if _use_stable_abi:
        extra_compile_args += ["/DPy_LIMITED_API=0x030A0000"]
else:
    extra_compile_args = ["-Werror=incompatible-pointer-types"]
    if _use_stable_abi:
        extra_compile_args += ["-DPy_LIMITED_API=0x030A0000"]
```

- **`-DPy_LIMITED_API=0x030A0000`** — enables the CPython stable ABI targeting
  Python 3.10+. The compiler rejects any symbol outside the stable surface,
  preventing accidental ABI breakage. Omitted for PyPy and free-threaded builds.
- **`/std:c11`** (Windows) — MSVC defaults to C89; this flag enables C99/C11
  features used throughout the codebase.
- **`-static`** (Windows) — static-links the MSVC runtime so the wheel does not
  depend on a specific MSVCRT DLL.
- **`-Werror=incompatible-pointer-types`** (non-Windows) — catches pointer type
  mismatches as errors during development.

### `py_limited_api=_use_stable_abi`

```python
_quickjs = Extension(
    "_quickjs",
    sources=...,
    extra_compile_args=extra_compile_args,
    extra_link_args=extra_link_args,
    py_limited_api=_use_stable_abi,
)
```

When `_use_stable_abi=True`, setuptools tags the built `.so`/`.pyd` with the
`abi3` filename convention (e.g. `_quickjs.abi3.so`), making it forward-
compatible with any CPython ≥ 3.10.

When `_use_stable_abi=False` (PyPy, free-threaded), the extension is tagged with
the runtime-specific ABI (e.g. `_quickjs.pypy310-pp73-x86_64-linux-gnu.so`).

---

## `pyproject.toml`

### Build backend

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

The original project used `hatchling`, which does not support C extensions
defined in `setup.py`. Switched to `setuptools`.

### Wheel tag

```toml
[tool.distutils.bdist_wheel]
py_limited_api = "cp310"
```

This tags the wheel `cp310-abi3-<platform>`, signalling to pip that the wheel
is compatible with any CPython ≥ 3.10. Without this setting, setuptools would
tag the wheel with the exact build interpreter (e.g. `cp313`), forcing a rebuild
per version.

### Removed compile-time macros

| Removed macro      | Reason                                                  |
|--------------------|---------------------------------------------------------|
| `CONFIG_VERSION`   | quickjs-ng has no `VERSION` file; version is in the header |
| `CONFIG_BIGNUM`    | BigNum extension removed from quickjs-ng                |

### Updated header list (sdist)

The sdist `SOURCES.txt` was updated to match the quickjs-ng source tree:
`libbf.h` and `VERSION` removed; `dtoa.h` added.

---

## Wheel matrix

cibuildwheel builds across all cp310+ interpreters and PyPy. For CPython,
`setup.py` sets `py_limited_api=_use_stable_abi=True`, so each CPython build
produces a `cp310-abi3` wheel that cibuildwheel then tests against cp311,
cp312, cp313, cp314, etc. automatically. For PyPy, `_use_stable_abi=False` and
a PyPy-tagged wheel is produced per PyPy version.

Free-threaded builds (`cp*t-*`) are excluded via `skip = ["cp*t-*"]` because
`Py_LIMITED_API` is currently incompatible with `Py_GIL_DISABLED`
(see [CPython issue #111506](https://github.com/python/cpython/issues/111506)).
Free-threaded builds are still tested in `main.yml`.

| Platform | Arch | CPython wheels | PyPy wheels | Notes |
|----------|------|:--------------:|:-----------:|-------|
| Linux (glibc) | x86_64 | 1 (abi3) | 2 (pypy310, pypy311) | |
| Linux (glibc) | i686 | 1 (abi3) | 2 | manylinux_2_28 |
| Linux (glibc) | aarch64 | 1 (abi3) | 2 | manylinux_2_28, QEMU |
| Linux (musl) | x86_64 | 1 (abi3) | — | musllinux; PyPy has no musl builds |
| Windows | AMD64 | 1 (abi3) | 2 | MSVC |
| Windows | x86 | 1 (abi3) | 2 | MSVC |
| macOS | arm64 | 1 (abi3) | 2 | Apple Silicon |

**Total: 19 wheels** — 7 CPython abi3 wheels (one per platform/arch, each
covers Python 3.10+) plus 12 PyPy wheels (pypy3.10 and pypy3.11 per
platform/arch, manylinux only — PyPy has no musllinux support).
