# GitHub Actions CI/CD

---

## Workflow Overview

Three workflows live under `.github/workflows/`:

| File | Trigger | Purpose |
|------|---------|---------|
| `main.yml` | Push + PR to `main`/`devel` | Fast regression feedback (pytest) |
| `build.yml` | Push to `main`, `workflow_call`, `workflow_dispatch` | Build abi3 wheels + sdist, publish to PyPI |
| `check-upstream.yml` | Monthly cron (1st of month, 06:00 UTC), `workflow_dispatch` | Detect new quickjs-ng upstream tags, trigger `build.yml` |

---

## CI (`main.yml`)

Runs `pytest` across Python 3.10–3.14 and PyPy 3.10/3.11 on Ubuntu, Windows,
and macOS.

The composite action `.github/actions/setup-python-env`:
- Sets `allow-prereleases: true` on `actions/setup-python@v5` so that Python
  3.14 (pre-release) and PyPy can be installed.
- Runs `uv pip install setuptools` before `uv pip install -e .` because PyPy
  venvs created by `uv sync` do not include `setuptools` by default, which is
  required to build the C extension.

**Why CI is fast (~2 min):**
CI builds the C extension in-place via `uv pip install -e .` using the host
Python. There is no Docker, no QEMU, no wheel packaging — just compile and run
pytest directly. This gives fast feedback on every push.

**PyPy notes:**
- `test_memory.py` is automatically skipped on PyPy (`tracemalloc` is
  CPython-only); all other 187 tests pass.
- The `test_gc_manual` test (JS cycle collection) is fixed by calling
  `gc.collect()` inside `Context.gc()` before `JS_RunGC` — see
  [c-extension.md](c-extension.md#pypy-support).

---

## Build Wheels (`build.yml`)

### Triggers

| Event | When | `publish` flag |
|-------|------|---------------|
| Push to `main` | Direct push | `true` |
| `workflow_call` | Triggered by `check-upstream.yml` | `true` |
| `workflow_dispatch` | Manual trigger with `upstream_tag` input | `true` |

### Jobs

**`setup`** — Resolves the upstream tag and wrapper version:
- If called with `upstream_tag` input (via `workflow_call` / `workflow_dispatch`):
  checks out that tag in the submodule.
- If triggered by push: detects the tag at the current submodule HEAD.
- Computes the wrapper version (see [versioning.md](versioning.md)).
- Outputs: `upstream_tag`, `version`, `publish`.

**`build-sdist`** — Builds a source distribution with `pipx run build --sdist`.

**`build-wheels`** — Matrix of 6 platform/arch combinations, each running
`cibuildwheel@v2.23` with `CIBW_BUILD: "cp310-*"`. Produces one `cp310-abi3`
wheel per platform.

**`publish`** — Downloads all artifacts, publishes to PyPI via Trusted Publishing
(OIDC, `id-token: write`), and creates + pushes a git tag.

### Build matrix

| Runner | Arch | `cibw_archs` | Notes |
|--------|------|--------------|-------|
| `ubuntu-latest` | x86_64 | `x86_64` | manylinux + musllinux |
| `ubuntu-latest` | i686 | `i686` | `manylinux_2_28` image (GCC ≥ 8 for C99) |
| `ubuntu-latest` | aarch64 | `aarch64` | `manylinux_2_28`; QEMU via `docker/setup-qemu-action` |
| `windows-latest` | x86_64 | `AMD64` | MSVC with `/std:c11` |
| `windows-latest` | i686 | `x86` | MSVC with `/std:c11` |
| `macos-14` | arm64 | `arm64` | Apple Silicon runner |

`macos-13` (Intel x86_64) is excluded — that runner image is deprecated.

The `manylinux_2_28` image is required for i686 and aarch64 because the older
`manylinux2014` image ships GCC 4.8, which rejects the C99 construct
`case X: { int y; … }` (declaration after a label) used in `cutils.h`.

### cibuildwheel configuration

In `pyproject.toml`:

```toml
[tool.cibuildwheel]
before-build = "rm -rf {project}/build {project}/*.so {project}/_quickjs*"
test-requires = ["pytest"]
test-command = "pytest {project}/tests -q"
enable = ["pypy", "pypy-eol"]
skip = ["cp*t-*"]
```

- **`enable = ["pypy", "pypy-eol"]`** — builds wheels for PyPy 3.11 (`pypy`)
  and PyPy 3.10 (`pypy-eol` — moved to end-of-life in cibuildwheel v3.2.0).
  CPython 3.14 is now stable and built by default without any enable flag
  (as of cibuildwheel v3.2.1).
- **`skip = ["cp*t-*"]`** — excludes free-threaded CPython builds (`cp313t`,
  `cp314t`) because `Py_LIMITED_API` is currently incompatible with
  `Py_GIL_DISABLED` (see [CPython issue #111506](https://github.com/python/cpython/issues/111506)).
  Free-threaded builds still work; they are tested in `main.yml` via `uv`.
- The **`before-build` hook** removes stale `.so` files that would otherwise be
  picked up by setuptools from the host instead of being rebuilt inside the
  build container. This is especially important for PyPy since the PyPy `.so`
  tag differs from the CPython `abi3` tag.
- **PyPy + musllinux**: PyPy has no musllinux (musl/Alpine) builds — only
  manylinux. The musllinux wheel built per platform is CPython-only.

### Why two separate workflows (CI vs Build wheels)?

| Aspect | CI (`main.yml`) | Build wheels (`build.yml`) |
|--------|-----------------|----------------------------|
| Trigger | Every push + PR | Push to `main`, `workflow_call`/`dispatch` |
| Speed | ~2 min per job | 2–60 min (aarch64 via QEMU) |
| What it builds | C extension via `uv pip install -e .` | Binary abi3 wheels via `cibuildwheel` in Docker |
| Test environment | Native host Python | Exact manylinux/musllinux/Windows wheel environment |
| Purpose | Fast regression feedback | Validates exact published artifact; handles PyPI publishing |

Both are necessary: CI gives fast feedback on every push; Build wheels validates
the exact published artifact in the exact target environment and handles publishing.

---

## Check Upstream (`check-upstream.yml`)

Runs monthly on the 1st at 06:00 UTC, and on `workflow_dispatch`.

### How it works

1. Checks out the repo with submodules.
2. Gets the current `upstream-quickjs` submodule SHA.
3. Fetches all tags from `upstream-quickjs` origin and finds the latest by semver.
4. Compares SHAs:
   - Equal → already up to date, exit.
   - Different → triggers `build.yml` via `createWorkflowDispatch` with the new tag.

```
current submodule SHA == latest tag SHA  →  no action
current submodule SHA != latest tag SHA  →  trigger build.yml with latest tag
```

### Required permissions

```yaml
jobs:
  check:
    permissions:
      actions: write   # required to call createWorkflowDispatch
```

The `GITHUB_TOKEN` for scheduled workflows defaults to read-only. Without
`actions: write`, the dispatch call returns HTTP 403 `Resource not accessible by
integration`.

### Target branch

The dispatch targets `ref: 'main'` — the stable branch that triggers publishing.
While the project is on `devel`, run the workflow manually via `workflow_dispatch`
to test it (it targets whichever branch the workflow file is on for the dispatch
call, but `build.yml` will be dispatched against `main` once it exists).

### Testing the workflow manually

```bash
gh workflow run "Check upstream quickjs-ng" --repo genotrance/quickjs-ng --ref devel
```

Then watch:

```bash
gh run watch --repo genotrance/quickjs-ng
```
