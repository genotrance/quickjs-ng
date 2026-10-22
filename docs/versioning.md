# Version Scheme

The wrapper version follows the format `X.Y.Z.P`:

| Component | Meaning | Example |
|-----------|---------|---------|
| `X.Y.Z` | Matches the upstream quickjs-ng tag (minus `v`) | `0.12.1` |
| `P` | Wrapper patch version; starts at `1` for each new upstream release | `1` |

Examples:

| Scenario | Result |
|----------|--------|
| First build against upstream `v0.12.1` | `0.12.1.1` |
| Second wrapper-only fix for `v0.12.1` | `0.12.1.2` |
| Build after upstream bumps to `v0.12.2` | `0.12.2.1` |

The version in `pyproject.toml` is the source of truth. It is committed to
`main` together with the `upstream-quickjs` submodule pointer; the build
workflow never rewrites it. A release always corresponds to one commit on
`main` whose `pyproject.toml` version is `X.Y.Z.P` and whose submodule is at the
upstream tag `vX.Y.Z`.

`uv.lock` records the project version as well (CI runs `uv lock --locked`), so
it is updated in the same commit.

---

## Bumping the version

### New upstream release (automatic)

`check-upstream.yml` handles this monthly (see [ci.md](ci.md)):

1. Find the latest stable upstream tag, e.g. `v0.17.0`.
2. Find what has been released: the newest of the repository's `vX.Y.Z.P` git
   tags and the latest version on PyPI. Its `X.Y.Z` part is the released base.
3. If the upstream version is newer than the released base, update the
   submodule to the upstream tag, set `pyproject.toml` (and `uv.lock`) to
   `X.Y.Z.1`, commit and push to `main`, then dispatch `build.yml` with that
   commit SHA and version.

If `main` already carries the bump for that upstream tag (for example an
earlier run committed it but the build failed), the commit is skipped and the
build is dispatched for the current `main` head, keeping the existing wrapper
patch.

Manual equivalent:

```bash
git -C upstream-quickjs fetch --tags && git -C upstream-quickjs checkout v0.17.0
# edit pyproject.toml: version = "0.17.0.1", and the quickjs-ng entry in uv.lock
git add upstream-quickjs pyproject.toml uv.lock
git commit -m "Update upstream quickjs-ng to v0.17.0 (version 0.17.0.1)"
```

### Wrapper-only fix (manual)

Increment `P` in `pyproject.toml` (and `uv.lock`) in the same commit as the fix,
e.g. `0.17.0.1` to `0.17.0.2`, and push to `main`. `build.yml` runs on the push
and publishes the new version. Without the bump the build still runs, but the
publish job finds the version already on PyPI and skips the upload.

---

## Release safety checks (`build.yml`)

`build.yml` builds exactly the commit it is given (`sha` input, or the pushed
commit) and checks, before anything is uploaded:

- The `setup` job reads the version from `pyproject.toml` at that commit and
  fails if the optional `version` input differs, or if the submodule is not at
  the upstream tag `vX.Y.Z` matching the version's `X.Y.Z`.
- The `publish` job fails before upload if the version differs from
  `pyproject.toml` at that commit (or from the `version` input), or if any built
  wheel/sdist carries a different version.
- If the version is already on PyPI, the upload is skipped.
- The `vX.Y.Z.P` tag is created on that commit only after a successful upload.
  If the tag already exists on another commit the job fails.

Re-running a failed release is therefore safe: build, check and upload are
idempotent, and a version is never uploaded twice.
