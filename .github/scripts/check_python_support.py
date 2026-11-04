"""Compare pyproject.toml classifiers with what the pinned cibuildwheel builds.

Usage: check_python_support.py IDENTIFIERS_FILE
Writes drift=true/false and a markdown body to GITHUB_OUTPUT / GITHUB_STEP_SUMMARY if set.
"""

import os
import re
import sys
import tomllib
from pathlib import Path

key = lambda v: tuple(map(int, v.split(".")))  # noqa: E731
ids = Path(sys.argv[1]).read_text().split()
project = tomllib.loads(Path("pyproject.toml").read_text())

listed = set(re.findall(r"Programming Language :: Python :: (3\.\d+)$", "\n".join(project["project"]["classifiers"]), re.M))
minimum = re.search(r">=\s*(3\.\d+)", project["project"]["requires-python"]).group(1)
buildable = {f"3.{m}" for m in re.findall(r"^cp3(\d+)-", "\n".join(ids), re.M)}
buildable_tags = {i.split("-")[0] for i in ids}

selectors = project.get("tool", {}).get("cibuildwheel", {}).get("build", [])
selectors = [selectors] if isinstance(selectors, str) else selectors
shipped = {s.split("-")[0] for s in selectors if re.fullmatch(r"(pp3\d+|cp3\d+t)-.*", s)}

add = sorted((v for v in buildable - listed if key(v) >= key(minimum)), key=key)
lost = sorted(listed - buildable, key=key)
lost_variants = sorted(shipped - buildable_tags)

lines = []
if add:
    lines.append(f"The pinned cibuildwheel can build CPython {', '.join(add)}, which the classifiers do not list. Add the classifier, CI matrix entries, docs and wheel builds as applicable.")
if lost:
    lines.append(f"The pinned cibuildwheel no longer builds listed CPython {', '.join(lost)}. Decide whether to drop it, or pin a cibuildwheel that still builds it.")
if lost_variants:
    lines.append(f"The pinned cibuildwheel no longer builds shipped variant(s) {', '.join(lost_variants)}.")

print(f"classifiers: {sorted(listed, key=key)}; cibuildwheel CPython: {sorted(buildable, key=key)}; shipped variants: {sorted(shipped)}")
print("\n".join(lines) or "No drift.")
if out := os.environ.get("GITHUB_OUTPUT"):
    with open(out, "a") as f:
        f.write(f"drift={'true' if lines else 'false'}\n")
Path(os.environ.get("ORC_BODY_FILE", "support-drift-body.md")).write_text("\n\n".join(lines) + "\n")
