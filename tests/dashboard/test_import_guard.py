"""Nothing under dashboard/ may import torch, opendrift, ortools or the detection package.

Two layers: a static scan of every import statement, and a clean interpreter that imports
the whole dashboard data and UI stack and inspects sys.modules. dashboard/check_schema.py
must also keep passing.
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest
from dashboard_testkit import DASHBOARD_DIR

FORBIDDEN = {"torch", "opendrift", "ortools", "detection"}
SOURCES = sorted(DASHBOARD_DIR.rglob("*.py"))


def imported_roots(path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
            roots.add(str(node.args[0].value).split(".")[0])
    return roots


def test_sources_were_found():
    assert len(SOURCES) > 20


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(DASHBOARD_DIR).as_posix())
def test_no_forbidden_import_statement(path):
    assert not imported_roots(path) & FORBIDDEN


def test_importing_the_dashboard_stack_loads_none_of_them():
    modules = sorted({p.relative_to(DASHBOARD_DIR).with_suffix("").as_posix().replace("/", ".")
                      for p in (DASHBOARD_DIR / "services").glob("*.py")}
                     | {p.relative_to(DASHBOARD_DIR).with_suffix("").as_posix().replace("/", ".")
                        for p in (DASHBOARD_DIR / "components").glob("*.py")} - {"services.__init__",
                                                                                 "components.__init__"})
    probe = ("import sys, logging; logging.disable(logging.WARNING); sys.path.insert(0, sys.argv[1]); "
             "import importlib; [importlib.import_module(m) for m in sys.argv[2:]]; "
             f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {FORBIDDEN!r}))")
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(DASHBOARD_DIR), *modules],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


def test_check_schema_passes():
    result = subprocess.run([sys.executable, str(DASHBOARD_DIR / "check_schema.py")],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "All schema checks passed." in result.stdout
