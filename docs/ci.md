# GitHub Actions CI/CD

---

## Workflow Overview

Three workflows live under `.github/workflows/`:

| File | Trigger | Purpose |
|------|---------|---------|
| `main.yml` | Push + PR to `main`/`devel` | Fast regression feedback (pytest) |
| `build.yml` | Push to `main`, `workflow_call`, `workflow_dispatch` | Build abi3 wheels + sdist of an exact commit, publish to PyPI, tag |
| `check-upstream.yml` | Monthly cron (1st of month, 06:00 UTC), `workflow_dispatch` | Detect new quickjs-ng upstream tags, commit the update to `main`, dispatch `build.yml` at that commit |

---

## Branch flow

`devel` is the development branch: pull requests, Dependabot updates, and fixes
target it. A release bumps the wrapper version on `devel` and merges `devel`
into `main`; that merge triggers `build.yml`, which publishes and tags the
release commit. The monthly upstream check still commits its update to `main`;
merge `main` back into `devel` afterwards so development includes the upstream
release.

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

| Event | Commit built | Inputs |
|-------|--------------|--------|
| Push to `main` | The pushed commit | none |
| `workflow_call` | `sha` input (default: triggering commit) | `sha`, `version` (both optional) |
| `workflow_dispatch` | `sha` input (default: head of the selected ref) | `sha`, `version` (both optional) |

`check-upstream.yml` dispatches `build.yml` with the SHA and version of the
commit it just pushed. The commit is built as is: `pyproject.toml` and the
submodule pointer are not modified in the runner.

### Jobs

**`setup`** — Checks out the commit and reads the wrapper version from
`pyproject.toml`. Fails if the `version` input differs or if the submodule is
not at the upstream tag `vX.Y.Z` matching the version
(see [versioning.md](versioning.md)).
Outputs: `sha`, `upstream_tag`, `version`, `publish`.

**`build-sdist`** — Builds a source distribution with `pipx run build --sdist`.

**`build-wheels`** — Matrix of 6 platform/arch combinations, each running
`cibuildwheel@v2.23` with `CIBW_BUILD: "cp310-*"`. Produces one `cp310-abi3`
wheel per platform.

**`publish`** — Downloads all artifacts and, in order:
1. Fails if the version differs from `pyproject.toml` at the commit (or from
   the `version` input), or if any built file has a different version.
2. Queries PyPI; if the version already exists the upload and tagging are
   skipped (a notice names the commit the existing `vX.Y.Z.P` tag points at; a
   warning is logged if the tag is missing). On `push` events the `setup` job
   also checks PyPI and, when the version is already published, skips the sdist
   and wheel builds and the publish job entirely (output `build=false`), so
   later pushes to `main` (Dependabot, lock or docs changes) are a no-op;
   `main.yml` already tests every push. `workflow_dispatch` and `workflow_call`
   (check-upstream) always build.
3. Publishes to PyPI via Trusted Publishing (OIDC, `id-token: write`).
4. Only after a successful upload, tags the built commit `vX.Y.Z.P` and pushes
   the tag.

Re-running the workflow for the same commit is safe.

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

1. Checks out `main` with submodules and all tags.
2. Finds the latest stable upstream tag (`vX.Y.Z`) with `git ls-remote`.
3. Determines what has been released: the newest of the repository's `vX.Y.Z.P`
   tags and the latest version on PyPI. Its `X.Y.Z` part is the released base.
4. If the upstream version is newer than the released base, a release is needed
   (the committed submodule is not used for this decision, so a committed but
   unreleased bump is retried).
5. Updates `upstream-quickjs` to the upstream tag and `pyproject.toml` /
   `uv.lock` to `X.Y.Z.1` (or keeps the version if `main` already has that
   upstream's bump), commits `Update upstream quickjs-ng to vX.Y.Z (version
   X.Y.Z.P)` and pushes it to `main`. No commit is made if nothing changed.
6. Dispatches `build.yml` on `main` with `sha` set to the resulting `HEAD` and
   `version` set to the new version.

```
upstream version <= released base  →  no action
upstream version >  released base  →  commit bump to main, dispatch build.yml at that SHA
```

Retries: if any step fails, re-run the workflow. An already committed bump is
reused and `build.yml` skips PyPI upload for versions that are already published.

The push uses `GITHUB_TOKEN`, which does not trigger other workflows, so the
push does not start `build.yml` or `main.yml` by itself; the explicit dispatch
(which is allowed for `GITHUB_TOKEN`) starts the build. `main.yml` therefore
does not run for the bump commit; the wheel builds run the test suite through
cibuildwheel. If `main` has branch protection, the Actions bot must be allowed
to push to it.

### Required permissions

```yaml
jobs:
  check:
    permissions:
      actions: write    # required to call createWorkflowDispatch
      contents: write   # required to push the bump commit to main
```

The `GITHUB_TOKEN` for scheduled workflows defaults to read-only. Without
`actions: write`, the dispatch call returns HTTP 403 `Resource not accessible by
integration`.

### Target branch

The bump is committed to `main` and the dispatch targets `ref: 'main'` — the
stable branch that triggers publishing. The workflow always checks out `main`,
whichever branch the workflow run itself was started from.

### Testing the workflow manually

```bash
gh workflow run "Check upstream quickjs-ng" --repo genotrance/quickjs-ng --ref devel
```

Then watch:

```bash
gh run watch --repo genotrance/quickjs-ng
```

## Lock file enforcement

The setup action uses `uv sync --locked` and the test step uses
`uv run --locked`; CI fails if `uv.lock` is out of date. Dependabot's `uv`
ecosystem (monthly, minor/patch grouped) proposes upgrades.
