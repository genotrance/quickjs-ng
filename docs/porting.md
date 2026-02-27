# Porting History: quickjs → quickjs-ng

This document describes the changes made to port the
[PetterS/quickjs](https://github.com/PetterS/quickjs) Python wrapper to the
actively maintained [quickjs-ng](https://github.com/quickjs-ng/quickjs) engine.

The reference project is the original `quickjs` Python package (PyPI: `quickjs`,
import: `import quickjs`). The ported project is `quickjs-ng` (PyPI:
`quickjs-ng`, import: `import quickjs`).

---

## Upstream Engine

The `upstream-quickjs` git submodule was changed from Fabrice Bellard's original
QuickJS to the quickjs-ng fork:

```
# .gitmodules
[submodule "upstream-quickjs"]
    path = upstream-quickjs
    url = https://github.com/quickjs-ng/quickjs
```

quickjs-ng is a community-maintained fork with ES2023+ support, performance
improvements, and ongoing bug fixes. It introduces several API and behavioral
changes that required updates to the C extension and test suite.

---

## Package Naming

The project is published to PyPI as `quickjs-ng` but the Python package
directory is named `quickjs/` so that downstream code can do:

```python
import quickjs
```

This makes `quickjs-ng` a drop-in replacement for the original `quickjs`
package with no import changes required.

| Attribute          | Original                    | quickjs-ng                  |
|--------------------|-----------------------------|-----------------------------|
| PyPI name          | `quickjs`                   | `quickjs-ng`                |
| Import name        | `quickjs`                   | `quickjs`                   |
| Package directory  | `quickjs/`                  | `quickjs/`                  |
| C extension module | `_quickjs`                  | `_quickjs`                  |

---

## Behavioral Differences

For users migrating from the original `quickjs` package:

| Behavior                    | Original quickjs           | quickjs-ng                          |
|-----------------------------|----------------------------|-------------------------------------|
| Stack overflow message      | `"stack overflow"`         | `"Maximum call stack size exceeded"` |
| Default stack size          | 256 KB                     | 1 MB (`JS_DEFAULT_STACK_SIZE`)      |
| Error identifier quoting    | `'missing' is not defined` | `missing is not defined`            |
| Backtrace column numbers    | Not included               | Included (e.g. `<input>:3:21`)      |
| BigNum (`CONFIG_BIGNUM`)    | Enabled                    | Removed (BigInt still native)       |
| ES2023+ features            | Not available              | Supported                           |
| `JS_NewClassID` API         | 1 argument                 | 2 arguments (runtime + class ID)    |
| Worker thread stack (musl)  | 128 KB (system default)    | 8 MB (explicit, matches glibc)      |
| Threading tests             | 2 (`Function` only)        | 12 (`Function` + context-per-thread)|
| Free-threaded Python        | Not applicable             | Safe; GIL not relied upon           |
| i686 float return values    | N/A (no i686 wheels)       | Fixed via `JS_VALUE_GET_NORM_TAG`   |
| Wheel ABI tag               | N/A                        | `cp310-abi3` (stable ABI)           |

---

## Removed Files

Files from the original project that were not applicable to this port:

| File              | Reason                                                      |
|-------------------|-------------------------------------------------------------|
| `Dockerfile`      | Referenced nonexistent `quickjs_ng/foo.py`                  |
| `tox.ini`         | Redundant — CI matrix in GitHub Actions covers multi-version testing |
| `codecov.yaml`    | Not needed without Codecov integration                      |

---

## Dependency Changes

| Removed              | Reason                                               |
|----------------------|------------------------------------------------------|
| `deptry`             | Not useful for C extension projects                  |
| `tox-uv`             | `tox.ini` was removed                                |

---

## Makefile

Rewritten for a C extension project using `uv`:

| Target               | Command                             | Purpose                           |
|----------------------|-------------------------------------|-----------------------------------|
| `make install`       | `uv sync && uv pip install -e .`    | Create venv, build C extension, install pre-commit hooks |
| `make check`         | Lock check, pre-commit, mypy        | Code quality                      |
| `make test`          | `pytest tests --cov`                | Run test suite with coverage      |
| `make build`         | `uv build`                          | Build sdist and wheel             |
| `make clean`         | Remove dist/, build/, .so, .o, coverage artifacts, wheelhouse/ | Clean all build artifacts |
| `make publish`       | `uv publish`                        | Publish to PyPI                   |

Key difference from the original Makefile: `uv pip install -e .` is required
to compile the C extension in-place for development.

**Note on venv shebangs** — if the project directory is moved or renamed after
`make install`, the venv's script shebangs become stale (they embed the absolute
path at creation time). Recreate with `rm -rf .venv && make install`.
