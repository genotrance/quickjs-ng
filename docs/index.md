# quickjs-ng Python Wrapper — Documentation

This folder contains the full technical specification and reference documentation
for the `quickjs-ng` Python package — a thin wrapper around the
[quickjs-ng](https://github.com/quickjs-ng/quickjs) JavaScript engine.

## Contents

| File | Description |
|------|-------------|
| [porting.md](porting.md) | Porting history: changes from PetterS/quickjs to quickjs-ng |
| [c-extension.md](c-extension.md) | C extension (`module.c`) design, stable ABI, and all changes |
| [build.md](build.md) | Build system: `setup.py`, `pyproject.toml`, wheel configuration |
| [ci.md](ci.md) | GitHub Actions workflows: CI, build wheels, check-upstream |
| [versioning.md](versioning.md) | Version scheme and automated version stamping |
| [threading.md](threading.md) | Threading model, safe patterns, musl stack fix |
| [testing.md](testing.md) | Test suite layout, new tests, memory leak detection |
| [typing.md](typing.md) | Type annotations, stub file, mypy configuration |

## Quick Reference

- **PyPI name**: `quickjs-ng`
- **Import**: `import quickjs`
- **Requires**: Python ≥ 3.10
- **Wheel tag**: `cp310-abi3` (one wheel per platform, covers Python 3.10+)
- **Engine**: [quickjs-ng](https://github.com/quickjs-ng/quickjs) (community fork of QuickJS)
