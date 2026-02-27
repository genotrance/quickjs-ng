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

The version in `pyproject.toml` is the source of truth. It is updated
automatically by the `build.yml` workflow before each build.

---

## Automated Version Stamping (`build.yml`)

The `setup` job in `build.yml` computes the version before building:

```bash
UPSTREAM_VER="${TAG#v}"           # strip leading 'v', e.g. 0.12.1
CURRENT_VER=$(python3 -c "
import re, pathlib
text = pathlib.Path('pyproject.toml').read_text()
m = re.search(r'version = \"(.+?)\"', text)
print(m.group(1))
")
CURRENT_BASE="${CURRENT_VER%.*}"  # strip patch, e.g. 0.12.1

if [ "$CURRENT_BASE" = "$UPSTREAM_VER" ]; then
    VERSION=$CURRENT_VER          # same upstream → keep wrapper patch
else
    VERSION=${UPSTREAM_VER}.1     # new upstream → reset patch to 1
fi

sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
```

This logic ensures:
- Wrapper-only fixes (e.g. bug fix without upstream change) preserve the patch
  number by leaving `pyproject.toml` unchanged before the build.
- A new upstream tag always resets the patch to `.1`.
