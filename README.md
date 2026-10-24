# quickjs-ng

[![Build status](https://img.shields.io/github/actions/workflow/status/genotrance/quickjs-ng/main.yml?branch=main)](https://github.com/genotrance/quickjs-ng/actions/workflows/main.yml?query=branch%3Amain)
[![License](https://img.shields.io/github/license/genotrance/quickjs-ng)](https://img.shields.io/github/license/genotrance/quickjs-ng)

Python wrapper around [quickjs-ng](https://github.com/quickjs-ng/quickjs), the actively maintained fork of the [QuickJS](https://bellard.org/quickjs/) JavaScript engine.

Drop-in replacement for the archived [quickjs](https://github.com/PetterS/quickjs) package — `import quickjs` works unchanged.

## Installation

```bash
pip install quickjs-ng
```

Requires CPython 3.11+ or PyPy 3.10/3.11. Pre-built wheels are available for Linux (x86_64, i686, aarch64), Windows (AMD64, x86), and macOS (arm64).

## Usage

```python
import quickjs

# Evaluate expressions
ctx = quickjs.Context()
ctx.eval("1 + 2")  # => 3

# Call JS functions from Python
ctx.eval("function add(a, b) { return a + b; }")
add = ctx.get("add")
add(3, 4)  # => 7

# Call Python functions from JS
ctx.add_callable("py_add", lambda a, b: a + b)
ctx.eval("py_add(3, 4)")  # => 7

# Use the Function helper for thread-safe execution
f = quickjs.Function("f", "function f(x) { return x * 2; }")
f(21)  # => 42

# Resource limits
ctx.set_memory_limit(1024 * 1024)  # 1 MB
ctx.set_time_limit(5)              # 5 seconds of CPU time
ctx.set_max_stack_size(512 * 1024) # 512 KB stack
```

## Threading

Each `Context` owns an isolated QuickJS runtime — there is no shared state between contexts. A single `Context` is **not thread-safe** and must not be used from multiple threads.

**Recommended patterns:**

- **Context per thread** — create a separate `Context` in each thread. No locking, no overhead, full parallelism:

  ```python
  import threading, quickjs

  def worker():
      ctx = quickjs.Context()
      print(ctx.eval("1 + 1"))

  threads = [threading.Thread(target=worker) for _ in range(4)]
  for t in threads: t.start()
  ```

- **`Function` helper** — wraps a `Context` with a dedicated worker thread and lock, safe to call from any thread:

  ```python
  f = quickjs.Function("f", "function f(x) { return x * 2; }")
  # safe to call f(21) from any thread
  ```

| Pattern | Thread-safe | Overhead |
|---------|:-----------:|----------|
| Context per thread | ✅ | None |
| `Function` helper | ✅ | Small (executor dispatch) |
| Shared `Context` | ❌ | — |

**Free-threaded Python (3.13t / 3.14t / 3.15t):** Both patterns remain safe. The GIL was never relied upon for thread-safety.

**musl / Alpine:** Worker threads are automatically created with an 8 MB stack (matching glibc defaults) so `set_max_stack_size` and deep recursion work correctly on musl-based systems.

## Versioning

Version format is `X.Y.Z.P` where `X.Y.Z` matches the upstream quickjs-ng tag and `P` is the wrapper patch (starts at 1 per upstream release). Development, Dependabot updates, and fixes target `devel`. A release bumps the wrapper version on `devel`, then merges `devel` into `main`, where wheels are built and published from exactly that commit. The monthly upstream check commits to `main`; merge `main` back into `devel` afterwards.

## Development

Requires a C compiler and [uv](https://docs.astral.sh/uv/).

```bash
git clone --recurse-submodules https://github.com/genotrance/quickjs-ng.git
cd quickjs-ng
make install
make test
```

| Target         | Description                                        |
|----------------|----------------------------------------------------|
| `make install` | Create venv, build C extension, install pre-commit |
| `make test`    | Run tests with coverage                            |
| `make check`   | Run linters and type checking                      |
| `make build`   | Build sdist and wheel                              |
| `make clean`   | Remove build artifacts                             |
| `make publish` | Publish to PyPI                                    |

## Contributing

Bug reports and pull requests are welcome at <https://github.com/genotrance/quickjs-ng/issues>.

1. Fork and clone with `--recurse-submodules`.
2. Run `make install` to set up the venv, build the C extension, and install pre-commit hooks.
3. Create a feature branch from `devel`, make changes, add tests in `tests/`.
4. Run `make check && make test` — all checks must pass.
5. Open a pull request to `devel`. Fast CI covers representative oldest/newest CPython, free-threaded, PyPy, Windows, macOS, and native Linux ARM paths; weekly and manual runs cover CPython 3.11–3.15 (including 3.13t/3.14t/3.15t) and PyPy 3.10/3.11 across all three desktop OSes.

Dependabot updates and fixes also target `devel`. For a release, bump the
wrapper version there and merge `devel` into `main`; after the automatic
upstream release, merge `main` back into `devel`.

## Documentation

Full technical documentation is in the [`docs/`](docs/) folder:

| File | Contents |
|------|----------|
| [docs/porting.md](docs/porting.md) | Porting history from PetterS/quickjs |
| [docs/c-extension.md](docs/c-extension.md) | C extension design and stable ABI migration |
| [docs/build.md](docs/build.md) | Build system: setup.py, pyproject.toml, wheels |
| [docs/ci.md](docs/ci.md) | GitHub Actions workflows |
| [docs/threading.md](docs/threading.md) | Threading model and musl stack fix |
| [docs/testing.md](docs/testing.md) | Test suite layout and memory leak tests |
| [docs/versioning.md](docs/versioning.md) | Version scheme and automated stamping |
| [docs/typing.md](docs/typing.md) | Type annotations and mypy configuration |

## Acknowledgments

This project is a fork of [quickjs](https://github.com/PetterS/quickjs) by [Petter Strandmark](https://github.com/PetterS). The original design of the C bindings, the `Function` thread-safety wrapper, and the overall API shape are all his work.

The porting to quickjs-ng, the stable ABI migration, the expanded test suite, CICD and all documentation were developed with the assistance of LLMs.

## License

MIT

## Fork safety

Create `quickjs.Function` objects (and `own_executor=True` executors) after
`fork()`. A child forked after first use inherits a dead worker thread and
hangs; `spawn`/`forkserver` are fine. See `docs/threading.md`.
