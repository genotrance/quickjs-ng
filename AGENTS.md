# Agent Guidelines for quickjs-ng

## Before pushing to GitHub

- Test all affected configurations locally (if possible) before pushing to GitHub.
- Cancel all old/running jobs on GitHub Actions before pushing new changes.
- Monitor jobs after pushing until they complete and confirm they pass.

## Documentation

- Keep `docs/` and `README.md` up to date with any changes made to the code, build system, or CI configuration.
- Update `docs/ci.md` when workflows change, `docs/build.md` when the build system changes, `docs/c-extension.md` when the C extension changes, and `docs/testing.md` when test structure changes.

## Scope discipline

- Do not remove any capability or support unless explicitly asked by the user.
- Do not weaken or delete tests without explicit direction.

## Test coverage

- Make sure test cases test all features and configurations of the project.
- When adding new features or fixing bugs, add or update tests to cover the new behaviour.
- All tests must pass on CPython 3.10–3.14 (including free-threaded 3.13t/3.14t) and PyPy 3.10/3.11 before merging.
