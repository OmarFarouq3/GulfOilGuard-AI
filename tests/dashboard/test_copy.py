"""E6: no repeated-word typos ("SAR imagery imagery", "the the") in the dashboard's text.

Scans every string literal in dashboard/*.py, including literals split over lines
("... imagery " "imagery ..."), and dashboard/README.md.
"""

from __future__ import annotations

import ast
import re

import pytest
from dashboard_testkit import DASHBOARD_DIR

REPEAT = re.compile(r"\b([A-Za-z]+)\s+\1\b", re.IGNORECASE)
SOURCES = sorted(DASHBOARD_DIR.rglob("*.py"))


def texts(path) -> list[tuple[int, str]]:
    """(line, text) of every string literal, plus each pair of literals on consecutive lines joined."""
    source = path.read_text(encoding="utf-8")
    found = [(node.lineno, node.value) for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for m in re.finditer(r'"([^"\n]*)"\s*\n\s*f?"([^"\n]*)"', source):
        found.append((source[:m.start()].count("\n") + 1, m.group(1) + m.group(2)))
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(DASHBOARD_DIR).as_posix())
def test_no_repeated_words_in_strings(path):
    repeats = [f"line {line}: {m.group(0)!r}" for line, text in texts(path) for m in REPEAT.finditer(text)]
    assert not repeats, repeats


def test_no_repeated_words_in_the_readme():
    lines = (DASHBOARD_DIR / "README.md").read_text(encoding="utf-8").splitlines()
    repeats = [f"line {i}: {m.group(0)!r}" for i, line in enumerate(lines, start=1) for m in REPEAT.finditer(line)]
    assert not repeats, repeats


def test_the_check_catches_the_reported_typo():
    assert REPEAT.search("A U-Net model reads SAR imagery imagery and outlines oil")
    assert REPEAT.search("over the the sea") and not REPEAT.search("oil oily water")
