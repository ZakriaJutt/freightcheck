"""T-2.1.1 acceptance: a forbidden import fails the boundary check; the real tree passes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_boundaries as cb


def test_real_tree_has_no_violations() -> None:
    assert cb.violations() == []


def test_forbidden_imports_are_reported(tmp_path: Path) -> None:
    core = tmp_path / "fc_core"
    core.mkdir()
    (core / "bad.py").write_text("import sqlalchemy\nimport os\nfrom datetime import date\n")
    worker = tmp_path / "fc_worker"
    worker.mkdir()
    (worker / "bad.py").write_text("from fastapi import FastAPI\nimport fc_db\n")
    found = cb.violations({"fc_core": core, "fc_worker": worker})
    assert len(found) == 3
    assert any("fc_core must not import sqlalchemy" in f for f in found)
    assert any("fc_core must not import os" in f for f in found)
    assert any("fc_worker must not import fastapi" in f for f in found)
