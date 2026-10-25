# GitHub Actions CI/CD

---

## Workflow Overview

Three workflows live under `.github/workflows/`:

| File | Trigger | Purpose |
|------|---------|---------|
| `main.yml` | Push/PR, weekly schedule, dispatch, reusable call | Fast or complete regression coverage (pytest) |
| `build.yml` | Push to `main`, `workflow_call`, `workflow_dispatch` | Run the full CI matrix on the exact commit, then build abi3 wheels + sdist, publish to PyPI, tag |
| `check-upstream.yml` | Monthly cron (1st of month, 06:00 UTC), `workflow_dispatch` | Detect a new upstream tag, commit to `main`, then dispatch the (self-gated) wheel build |
| `python-support.yml` | Monthly cron (1st of month, 07:00 UTC), `workflow_dispatch` | Open an issue when the official CPython support window differs from package classifiers |

---

## Branch flow

`devel` is the development branch: pull requests, Dependabot updates, and fixes
target it. A release bumps the wrapper version on `devel` and merges `devel`
into `main`; that merge triggers `build.yml`, which publishes and tags the
release commit. The monthly upstream check still commits its update to `main`;
merge `main` back into `devel` afterwards so development includes the upstream
release.

## CI (`main.yml`)

Pushes and pull requests run a deliberately small, representative matrix:

| Runner | Interpreters | Why it runs on every change |
|--------|--------------|-----------------------------|
| Ubuntu | CPython 3.10, 3.15, 3.15t; PyPy 3.11 | Oldest/newest ABI, newest free-threaded runtime, and PyPy |
| Windows | CPython 3.15 | Windows compiler and path handling |
| macOS | CPython 3.15 | macOS compiler and path handling |
| `ubuntu-24.04-arm` | CPython 3.15 | Native Linux aarch64 path used for release wheels |

See [testing.md](testing.md#why-the-matrix-is-split) for why the matrix is
this small on every push.

The weekly Monday 05:00 UTC schedule (`schedule` triggers only run from the
repository's default branch, `devel`), manual `workflow_dispatch`, and a
`workflow_call` with `full: true` use the complete matrix: CPython 3.10–3.15,
free-threaded 3.13t/3.14t/3.15t, and PyPy 3.10/3.11 on Ubuntu, Windows, and
macOS (11 interpreters x 3 OSes = 33 jobs), plus CPython 3.15 on native Linux
aarch64 (34 test jobs). The fast matrix has 7 test jobs. Each run also has the
`quality` and `select-matrix` jobs: fast = 9 jobs, full = 36 jobs.

`workflow_call` takes an explicit boolean `full` input (default `false`). In a
called workflow `github.event_name` is the caller's event, never
`workflow_call`, so the selector honours `inputs.full` rather than the event
name.

### Release gate

Three paths can publish to PyPI, and all three run through `build.yml`: a push
to `main` carrying a new version, a manual `workflow_dispatch` of `build.yml`,
and `check-upstream.yml`'s dispatch of `build.yml` after it commits a version
bump to `main`. `build.yml`'s `full-ci` job calls `main.yml` with
`sha=<resolved SHA>` and `full: true` (`permissions: contents: read`).
`build-sdist` and `build-wheels` need `full-ci`, and `publish` needs all of
them, so for every one of the three paths nothing uploads unless the full
matrix passed on the exact SHA being built — there is no code path in
`build.yml` that reaches `publish` without `full-ci` having succeeded first.
`full-ci` runs only when `setup` decides to build: a push to `main` whose
version is already on PyPI skips `full-ci`, the builds, and the upload,
leaving a cheap no-op.

What is *not* enforced by any workflow is the pre-merge check: nothing in this
repository requires a green full-matrix run on `devel` before merging it into
`main` (push/PR CI on `devel` only runs the fast matrix, and there is no
branch-protection configuration in this repo to check). Dispatching `main.yml`
with `full: true` against `devel` before merging — see
[Operator verification](#operator-verification) below — is an operator
procedure, not a gate. Skipping it cannot let a broken build publish, because
`build.yml`'s own `full-ci` job still runs automatically on the resulting
`main` commit before anything uploads; skipping it only means a break surfaces
on `main` instead of being caught on `devel` first.

The package's supported CPython window is tracked by classifiers and
`python-support.yml`. That workflow parses the official
[`devguide.python.org/versions`](https://devguide.python.org/versions/) table
monthly and opens one issue if the supported bugfix/security versions drift.
An operator updates the classifiers, CI table, wheel policy, and docs together.
`requires-python >=3.10` remains to preserve the shipped PyPy 3.10 wheel;
CPython support itself follows the classifier window. CPython 3.10 is
restored until its end of life on 2026-10-31 (classifier, fast/full matrices,
cibuildwheel `build`); after that date `python-support.yml` reports that 3.10
can be dropped, and an operator removes it everywhere in one change.

Fast jobs run `pytest -m "not slow"`; the full matrix and wheel tests use no
marker filter and run every test. See
[testing.md](testing.md#test-selection-and-local-commands) for what the `slow`
marker means, why no test currently carries it, and the equivalent local
commands.

The composite action `.github/actions/setup-python-env`:
- Sets `allow-prereleases: true` on `actions/setup-python@v5` so that new
  CPython releases and PyPy can be installed as they enter the support window.
- Runs `uv pip install setuptools` before `uv pip install -e .` because PyPy
  venvs created by `uv sync` do not include `setuptools` by default, which is
  required to build the C extension.

**Why ordinary CI is fast:**
CI builds the C extension in-place via `uv pip install -e .` using the host
Python. There is no Docker, no QEMU, no wheel packaging — just compile and run
pytest directly. The green baseline run `40064370056` spent 6m06s wall time on
25 jobs (24 test jobs consumed 1,978 runner-seconds; setup was 78–92 seconds
per job while pytest itself took 2–3 seconds). The push/PR policy now launches
seven test jobs rather than 24, a 71% reduction in test job setup work; the
weekly/full path preserves the complete coverage. The prior QEMU aarch64 wheel
job took 35–50 minutes; native `ubuntu-24.04-arm` avoids emulation, with an
expected 4–6 minute build. The first release run records the hosted timing.

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

`check-upstream.yml` first runs the complete reusable `main.yml` matrix for the
SHA and version of the commit it just pushed, then dispatches `build.yml`. The
commit is built as is: `pyproject.toml` and the submodule pointer are not
modified in the runner.

### Jobs

**`setup`** — Checks out the commit and reads the wrapper version from
`pyproject.toml`. Fails if the `version` input differs or if the submodule is
not at the upstream tag `vX.Y.Z` matching the version
(see [versioning.md](versioning.md)).
Outputs: `sha`, `upstream_tag`, `version`, `publish`.

**`build-sdist`** — Builds a source distribution with `pipx run build --sdist`.

**`build-wheels`** — Matrix of 6 platform/arch combinations, each running
`cibuildwheel@v4.3.3`. It builds and tests one `cp310-abi3` wheel on both the
oldest and newest supported CPython, and builds/tests the two shipped PyPy
wheels. The duplicate abi3 compatibility test does not add a shipped wheel.

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
| `ubuntu-24.04-arm` | aarch64 | `aarch64` | `manylinux_2_28`; native ARM runner |
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
build = ["cp310-*", "cp315-*", "pp310-*", "pp311-*"]
enable = ["pypy", "pypy-eol"]
skip = ["cp*t-*"]
```

- **`build`** — exercises abi3 wheels on CPython 3.10 and 3.15 only. `cp310`
  builds the `cp310-abi3` wheel; for `cp315` cibuildwheel reuses that
  compatible abi3 wheel (skipping the build) and only tests it, so the
  artifact set remains one CPython wheel per platform while retaining
  oldest/newest compatibility coverage. It also builds and tests both shipped PyPy wheel versions.
- **`enable = ["pypy", "pypy-eol"]`** — builds wheels for PyPy 3.11 (`pypy`)
  and PyPy 3.10 (`pypy-eol` — moved to end-of-life in cibuildwheel v3.2.0).
- **`skip = ["cp*t-*"]`** — excludes free-threaded CPython builds (`cp313t`,
  `cp314t`, `cp315t`) because `Py_LIMITED_API` is currently incompatible with
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
| Trigger | Every push + PR | Push to `main`, `workflow_call`/`dispatch` (after the full matrix on the same SHA) |
| Speed | 7 test jobs on push/PR; complete matrix weekly/manual | 2–10 min (native aarch64; no QEMU) |
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
6. Dispatches `build.yml` on `main` with `sha` set to the committed `HEAD` and
   `version` set to the new version. `build.yml` runs the full matrix on that
   SHA (`full-ci`) before it builds or publishes; the matrix is not run twice.

```
upstream version <= released base  →  no action
upstream version > released base → commit bump to main, dispatch build.yml at that SHA (which runs full CI first)
```

Retries: if any step fails, re-run the workflow. An already committed bump is
reused and `build.yml` skips PyPI upload for versions that are already published.

The push uses `GITHUB_TOKEN`, which does not trigger other workflows, so the
push does not start `build.yml` or `main.yml` by itself. The `actions: write`
trigger job dispatches `build.yml`, whose own `full-ci` gate tests the commit. If `main` has branch protection, the Actions bot must
be allowed to push to it.

### Required permissions

```yaml
jobs:
  check:
    permissions:
      contents: write   # required to push the bump commit to main
  trigger-build:
    permissions:
      actions: write    # required to call createWorkflowDispatch
```

The `GITHUB_TOKEN` for scheduled workflows defaults to read-only. Without
`actions: write`, the dispatch call returns HTTP 403 `Resource not accessible by
integration`.

### Target branch

The bump is committed to `main` and the dispatch targets `ref: 'main'` — the
stable branch that triggers publishing. The workflow always checks out `main`,
whichever branch the workflow run itself was started from.

### Operator-approved release dispatch

```bash
gh workflow run "Check upstream quickjs-ng" --repo genotrance/quickjs-ng --ref devel
```

Then watch:

```bash
gh run watch --repo genotrance/quickjs-ng
```

## Operator verification

After this change lands on `devel`, confirm the automatic push/PR run has seven
test jobs plus quality and matrix selection:

```bash
gh run list --repo genotrance/quickjs-ng --workflow main.yml --branch devel --limit 1
gh run watch --repo genotrance/quickjs-ng
```

Run the full pre-release dry run explicitly before release review (it tests the
selected `devel` commit without publishing):

```bash
gh workflow run CI --repo genotrance/quickjs-ng --ref devel
gh run list --repo genotrance/quickjs-ng --workflow main.yml --branch devel --limit 1
gh run watch --repo genotrance/quickjs-ng
```

The scheduled full run needs no dispatch. During an upstream release,
`check-upstream.yml` dispatches `build.yml`, which runs the full matrix itself
before publishing.

### Expected runs for the 3.10 / release-gate change

Timings come from the earlier green run (about 78–92 s setup plus 2–3 s pytest
per test job; Windows and macOS runners are slower), so treat them as estimates.

| Operator run | Jobs | Expected wall time |
|--------------|------|--------------------|
| `git push` to `devel` (CI) | 9: `quality`, `select-matrix`, 7 fast tests (Ubuntu 3.10/3.15/3.15t/PyPy 3.11, Windows 3.15, macOS 3.15, ARM 3.15) | 2–4 min |
| `gh workflow run CI --repo genotrance/quickjs-ng --ref devel` | 36: `quality`, `select-matrix`, 34 full tests (33 + ARM 3.15); title `Test (full)` | 5–10 min |
| `gh workflow run "Build wheels" --repo genotrance/quickjs-ng --ref devel -f sha=<devel sha>` | about 45: `setup`, `full-ci` (36 nested), `build-sdist`, 6 `build-wheels`, `publish` | 25–45 min (full CI 5–10 min, then wheels in parallel with native aarch64 at 10–20 min) |
| `@dependabot rebase` on PR #18 | 9 (fast matrix, as for any PR) | 2–4 min |

The 0.17.0.2 dispatch is safe: `publish` finds the version on PyPI, skips the
upload and the tag, and the only effect is the gate plus a wheel build. A push
to `main` with that version runs `setup` only (1 job, under a minute) and skips
`full-ci`, builds, and publish. Confirm `full-ci` appears in the run and that
the wheel jobs start only after it succeeds.

## Lock file enforcement

The setup action uses `uv sync --locked` and the test step uses
`uv run --locked`; CI fails if `uv.lock` is out of date. Dependabot's `uv`
ecosystem (monthly, minor/patch grouped) proposes upgrades.
