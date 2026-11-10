"""Import-boundary lint (T-2.1.1, AD-11; R-03, R-04, R-06, R-07).

Rules (TRD section 5):
  fc_core      imports only the standard library: no database, network, clock or env.
  fc_platform  never imports fc_db, fc_api or fc_worker.
  fc_db        never imports fc_api or fc_worker.
  fc_api       never imports fc_worker.
  fc_worker    never imports fc_api or a web framework.
Exit 1 and print every violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "fc_core": ROOT / "packages/core/fc_core",
    "fc_platform": ROOT / "packages/platform/fc_platform",
    "fc_db": ROOT / "packages/db/fc_db",
    "fc_api": ROOT / "apps/api/fc_api",
    "fc_worker": ROOT / "apps/worker/fc_worker",
}
WEB = {"fastapi", "starlette", "uvicorn", "httpx", "pydantic"}
CORE_FORBIDDEN_STDLIB = {"os", "socket", "subprocess", "urllib", "http", "sqlite3", "random", "time"}
FORBIDDEN: dict[str, set[str]] = {
    "fc_platform": {"fc_db", "fc_api", "fc_worker", *WEB},
    "fc_db": {"fc_api", "fc_worker", *WEB},
    "fc_api": {"fc_worker"},
    "fc_worker": {"fc_api", *WEB},
}


def imports_of(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module.split(".")[0]))
    return out


def violations(packages: dict[str, Path] = PACKAGES) -> list[str]:
    stdlib = set(sys.stdlib_module_names)
    found: list[str] = []
    for pkg, root in packages.items():
        for f in sorted(root.rglob("*.py")):
            if "migrations" in f.parts:
                continue
            for line, mod in imports_of(f):
                if mod == pkg or mod == "__future__":
                    continue
                if pkg == "fc_core":
                    bad = (mod not in stdlib and mod != "fc_core") or mod in CORE_FORBIDDEN_STDLIB
                else:
                    bad = mod in FORBIDDEN.get(pkg, set())
                if bad:
                    found.append(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}:{line}: {pkg} must not import {mod}")
    return found


def main() -> int:
    v = violations()
    for line in v:
        print(line)
    print(f"{len(v)} boundary violation(s)")
    return 1 if v else 0


if __name__ == "__main__":
    raise SystemExit(main())
