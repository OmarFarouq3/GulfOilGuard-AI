"""No internal team or team-member name ever reaches a viewer.

Renders every page (Overview, Detect, Predict, Respond, with the options panel and its Diagnostics)
with no site selected, in the demo scenario, and for each of S1 to S4 using a copy of the real
outputs/, and checks the whole element tree: page text, captions, labels, help tooltips, table
headers and cells, map tooltips, warnings and Diagnostics. Also scans every string constant in the
dashboard source (docstrings and comments are developer documentation and are left out).
"""

from __future__ import annotations

import ast
import re
import shutil

import pytest
from dashboard_testkit import DASHBOARD_DIR, REPO_ROOT
from test_sites import go, new_app, sites  # noqa: F401  (fixture)

import config
from services import selection
from services.files import PEOPLE, display_text, neutral

FORBIDDEN = re.compile(r"\bteams?\b|\bteam\s+[a-d]\b|\bprovided by\b|\bshared by\b|\bowners?\b|\b(?:%s)\b"
                       % "|".join(PEOPLE), re.IGNORECASE)
REAL = REPO_ROOT / "outputs"
PAGES = ("views/overview.py", "views/detection.py", "views/drift.py", "views/cleanup.py")
needs_real = pytest.mark.skipif(not (REAL / "sites" / "S1" / "routing" / "routes.geojson").is_file(),
                                reason="the real outputs/ are not on this machine")


def tree_text(at) -> str:
    """Every element's protobuf as text, from the root (top bar, options panel and Diagnostics included)."""
    parts: list[str] = []

    def walk(node) -> None:
        proto = getattr(node, "proto", None)
        if proto is not None:
            text = str(proto)
            if "body:" in text and "/* GulfOilGuard-AI" in text:  # the stylesheet: CSS, not text
                return
            parts.append(text)
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(at._tree)
    return "\n".join(parts)


def hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in FORBIDDEN.finditer(text)})


@pytest.fixture(scope="module")
def real_outputs():
    """A copy of the real outputs/ (detection, drift, report, fleet, sites) in the test outputs folder."""
    copied = []
    for name in ("detection", "drift", "report", "fleet", "sites"):
        if (REAL / name).is_dir():
            shutil.copytree(REAL / name, config.OUTPUTS_DIR / name, dirs_exist_ok=True)
            copied.append(config.OUTPUTS_DIR / name)
    yield
    for path in copied:
        shutil.rmtree(path, ignore_errors=True)


def render_all(spill: str | None = None, demo: bool = False) -> dict[str, str]:
    """{page: text} with Detect done (simulated) and Predict done for a site, and the plan shown on Respond."""
    texts = {}
    for page in PAGES:
        at = new_app(spill, demo=demo)
        if spill:
            at.session_state[selection.PREDICT_DONE_KEY] = True
            at.run()
        if page != "views/overview.py":
            go(at, page, "flow_run_respond" if spill and page == "views/cleanup.py" else None)
        assert not at.exception, [e.message for e in at.exception]
        texts[page] = tree_text(at)
    return texts


@needs_real
@pytest.mark.parametrize("case", ["no site", "demo", "S1", "S2", "S3", "S4"])
def test_no_team_or_member_name_on_any_page(real_outputs, case):
    texts = render_all(spill=None if case in ("no site", "demo") else case, demo=case == "demo")
    found = {page: hits(text) for page, text in texts.items() if hits(text)}
    assert not found, found
    if case.startswith("S"):  # the pages really show this site's results (not an empty or demo page)
        assert "Precomputed result from the saved routing plan" in texts["views/cleanup.py"]
        assert "Loader warnings" in texts["views/overview.py"]  # Diagnostics was rendered and scanned


SANITISER = {"PEOPLE", "_TEAM", "_POSSESSIVE", "_REFERENCE"}  # services/files.py: the names and patterns it removes


def string_constants(path) -> list[tuple[int, str]]:
    """(line, text) of every string constant except docstrings and the sanitiser's own list of names."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.add(id(first.value))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in SANITISER for t in node.targets):
            skip.update(id(c) for c in ast.walk(node.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


@pytest.mark.parametrize("path", sorted(DASHBOARD_DIR.rglob("*.py")), ids=lambda p: p.relative_to(DASHBOARD_DIR).as_posix())
def test_no_team_or_member_name_in_source_strings(path):
    found = [f"line {line}: {text[:80]!r}" for line, text in string_constants(path) if FORBIDDEN.search(text)]
    assert not found, found


def test_the_guard_catches_the_old_wording():
    for old in ("Precomputed result from the Team B drift run", "Warnings from the cleanup team's checks",
                "saved drift runs (Team B)", "Validate Haris's latest emulsion run", "provided by Ayham"):
        assert FORBIDDEN.search(old), old
    for fine in ("Precomputed result from the saved drift run", "steamship", "fromarray", "Maritime City"):
        assert not FORBIDDEN.search(fine), fine


@pytest.mark.parametrize("raw, shown", [
    ("Precomputed result from the Team B drift run", "Precomputed result from the project drift run"),
    ("Validate Haris's latest emulsion run", "Validate the latest emulsion run"),
    ("checked by the cleanup team", "checked by the project"),
    ("Team C's plan, provided by Omar", "the plan, provided by the project"),
    ("Port Saqr moved 2.1 km to the nearest water", "Port Saqr moved 2.1 km to the nearest water"),
])
def test_text_from_files_is_neutralised(raw, shown):
    assert neutral(raw) == shown
    assert not hits(neutral(raw).replace("provided by", ""))


@pytest.mark.parametrize("value, shown", [
    ("C:/Users/someone/models/best.pth", "best.pth"),
    ("C:\\Users\\someone\\best.pth", "best.pth"),
    ("/home/someone/runs/unet/best.pth", "best.pth"),
    ("\\\\server\\share\\best.pth", "best.pth"),
    ("runs/unet_refined_sar/best.pth", "best.pth"),
    ("U-Net (unet_refined_sar)", "U-Net (unet_refined_sar)"),
    ("train/val split", "train/val split"),
    ("Scored with C:\\Users\\someone\\Documents\\UOS\\Hack for Earth Competition\\x\\unet_best.pth only.",
     "Scored with unet_best.pth only."),
    ("Masks from C:/Users/someone/data/masks were used.", "Masks from masks were used."),
])
def test_paths_in_text_from_files_are_reduced_to_file_names(value, shown):
    """Moved from test_detection_metrics.py: the same path hiding now covers all text read from files."""
    assert display_text(value) == shown


def test_a_team_name_in_a_data_file_never_reaches_the_page(sites):
    """meta.json note, plan message and validation warnings mentioning teams are shown neutralised."""
    import json
    sites("S1", validation={"counts": {"OK": 1, "WARN": 1, "FAIL": 0},
                            "checks": [{"level": "WARN", "group": "Team C checks",
                                        "text": "unserved targets: ['T06'] in Haris's run"}]})
    meta_file = config.site_files("S1")["drift"]["meta"]
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["note"] = "Run by Team B (Maqqavi) for the demo."
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    summary_file = config.site_files("S1")["routing"]["summary"]
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    summary["message"] = "plan provided by Omar's team; unserved: T09 (Team C rule)"
    summary_file.write_text(json.dumps(summary), encoding="utf-8")
    texts = render_all("S1")
    assert "Run by the project (the project) for the demo." in texts["views/drift.py"]
    found = {page: hits(text.replace("provided by", "")) for page, text in texts.items()}
    assert not any(found.values()), found
