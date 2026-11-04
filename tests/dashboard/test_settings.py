"""services/settings.py: environment > .env > standard layout > fallback, for all three settings.

Every test builds its own repo layout in tmp_path and passes ``root`` / ``environ`` explicitly
(conftest also points settings.ROOT at an empty folder), so nothing here depends on this machine.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from dashboard_testkit import DASHBOARD_DIR, REPO_ROOT

from services import settings

KEYS = {"checkpoint": "GOG_CHECKPOINT", "python": "GOG_DETECTION_PYTHON", "images": "GOG_IMAGE_DIR"}


def resolve(kind: str, root: Path, environ: dict, os_name: str = "nt") -> settings.Resolved:
    if kind == "checkpoint":
        return settings.resolve_checkpoint(root=root, environ=environ)
    if kind == "python":
        return settings.resolve_python(root=root, environ=environ, os_name=os_name)
    return settings.resolve_image_dir(root=root, environ=environ)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def standard_layout(root: Path) -> dict[str, Path]:
    """checkpoints/unet_best.pth, .venv-detect/ (Windows layout) and assets/images/ under root."""
    images = root / "assets" / "images"
    images.mkdir(parents=True)
    return {"checkpoint": touch(root / "checkpoints" / "unet_best.pth"),
            "python": touch(root / ".venv-detect" / "Scripts" / "python.exe"), "images": images}


def write_env(root: Path, text: str) -> None:
    (root / ".env").write_text(text, encoding="utf-8")


# --- Precedence ---------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KEYS)
def test_environment_beats_env_file_beats_standard_layout(tmp_path, kind):
    layout = standard_layout(tmp_path)
    key = KEYS[kind]
    from_env, from_file = tmp_path / "from-env" / "a.bin", tmp_path / "from-file" / "b.bin"
    write_env(tmp_path, f"{key}={from_file}\n")

    assert resolve(kind, tmp_path, {key: str(from_env)}).path == from_env
    assert resolve(kind, tmp_path, {key: str(from_env)}).source == f"{key} environment variable"
    assert resolve(kind, tmp_path, {}).path == from_file
    assert resolve(kind, tmp_path, {}).source == f"{key} in .env"
    (tmp_path / ".env").unlink()
    assert resolve(kind, tmp_path, {}).path == layout[kind]
    assert resolve(kind, tmp_path, {}).source == "standard layout"


@pytest.mark.parametrize("kind", KEYS)
def test_empty_values_count_as_not_set(tmp_path, kind):
    layout = standard_layout(tmp_path)
    write_env(tmp_path, f'{KEYS[kind]}=""\n')
    assert resolve(kind, tmp_path, {KEYS[kind]: "  "}).path == layout[kind]


def test_fallbacks_without_any_layout(tmp_path):
    assert resolve("checkpoint", tmp_path, {}).path == tmp_path / "runs" / "unet_refined_sar" / "best.pth"
    assert resolve("checkpoint", tmp_path, {}).source == "built-in default"
    assert resolve("python", tmp_path, {}).path == Path(sys.executable)
    assert resolve("python", tmp_path, {}).source == "the dashboard's own Python"
    assert resolve("images", tmp_path, {}).path == tmp_path / "assets" / "images"


def test_explicit_setting_wins_even_when_its_file_is_missing(tmp_path):
    standard_layout(tmp_path)
    resolved = resolve("checkpoint", tmp_path, {"GOG_CHECKPOINT": str(tmp_path / "typo.pth")})
    assert resolved.path == tmp_path / "typo.pth" and not resolved.checked[-1].found


def test_every_check_is_recorded_in_order(tmp_path):
    resolved = resolve("checkpoint", tmp_path, {})
    assert [c.source for c in resolved.checked] == [
        "GOG_CHECKPOINT environment variable", "GOG_CHECKPOINT in .env", "standard layout", "built-in default"]
    assert [c.found for c in resolved.checked] == [False, False, False, False]


# --- .env file ----------------------------------------------------------------------------------


def test_missing_env_file(tmp_path):
    assert settings.read_env_file(tmp_path / ".env") == ({}, [])
    assert settings.env_file(tmp_path) == ({}, [])


def test_env_file_syntax(tmp_path):
    write_env(tmp_path, "﻿# comment\n\n"            # BOM, comment, blank
                        "A=plain\n"
                        "B = \"double quoted\"  \n"
                        "C='single # not a comment'\n"
                        "export D=exported\n"
                        "E=value # trailing comment\n"
                        "F=a=b\n")
    values, problems = settings.env_file(tmp_path)
    assert values == {"A": "plain", "B": "double quoted", "C": "single # not a comment", "D": "exported",
                      "E": "value", "F": "a=b"}
    assert problems == []


def test_malformed_lines_are_skipped_and_reported(tmp_path):
    write_env(tmp_path, "GOOD=1\nNO_EQUALS_SIGN\n1BAD=x\n=value\nbad key=x\nALSO_GOOD=2\n")
    values, problems = settings.env_file(tmp_path)
    assert values == {"GOOD": "1", "ALSO_GOOD": "2"}
    assert [p.split(":")[0] for p in problems] == ["`.env` line 2", "`.env` line 3", "`.env` line 4", "`.env` line 5"]


def test_malformed_env_file_still_resolves(tmp_path):
    layout = standard_layout(tmp_path)
    write_env(tmp_path, "this is not a setting\nGOG_IMAGE_DIR=assets/images\n")
    assert resolve("checkpoint", tmp_path, {}).path == layout["checkpoint"]
    assert resolve("images", tmp_path, {}).path == layout["images"]


def test_unreadable_env_file_is_a_problem_not_a_crash(tmp_path):
    (tmp_path / ".env").mkdir()  # a folder where the file should be
    values, problems = settings.env_file(tmp_path)
    assert values == {} and problems
    assert resolve("images", tmp_path, {}).path == tmp_path / "assets" / "images"


# --- Interpreter layouts ------------------------------------------------------------------------


@pytest.mark.parametrize("os_name, layout", [("nt", "Scripts/python.exe"), ("posix", "bin/python")])
def test_detection_venv_on_windows_and_posix_layouts(tmp_path, os_name, layout):
    interpreter = touch(tmp_path / ".venv-detect" / layout)
    assert settings.venv_python(tmp_path, os_name) == interpreter
    assert resolve("python", tmp_path, {}, os_name=os_name).path == interpreter


@pytest.mark.parametrize("os_name, other", [("nt", "bin/python"), ("posix", "Scripts/python.exe")])
def test_the_other_os_layout_is_not_used(tmp_path, os_name, other):
    touch(tmp_path / ".venv-detect" / other)
    assert resolve("python", tmp_path, {}, os_name=os_name).path == Path(sys.executable)


def test_bare_interpreter_name_is_looked_up_on_path(tmp_path):
    name = Path(sys.executable).stem  # "python" here, found on PATH via the current environment
    resolved = resolve("python", tmp_path, {"GOG_DETECTION_PYTHON": name})
    assert resolved.path.is_absolute() or resolved.path == Path(name)


# --- Repo root and relative paths ---------------------------------------------------------------


def test_relative_paths_resolve_against_the_repo_root_not_the_cwd(tmp_path, monkeypatch):
    root, elsewhere = tmp_path / "repo", tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    write_env(root, "GOG_CHECKPOINT=models/x.pth\nGOG_IMAGE_DIR=assets/images/val\n")
    monkeypatch.chdir(elsewhere)
    assert resolve("checkpoint", root, {}).path == root / "models" / "x.pth"
    assert resolve("images", root, {}).path == root / "assets" / "images" / "val"
    assert resolve("checkpoint", root, {"GOG_CHECKPOINT": "rel/y.pth"}).path == root / "rel" / "y.pth"


def test_repo_root_comes_from_the_file_location_not_the_cwd(tmp_path):
    """Import the real config / settings from an unrelated working directory: same repo root."""
    probe = ("import sys, logging; logging.disable(logging.WARNING); sys.path.insert(0, sys.argv[1]); "
             "import config; from services import settings; print(config.REPO_ROOT); print(settings.ROOT)")
    result = subprocess.run([sys.executable, "-c", probe, str(DASHBOARD_DIR)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert [Path(line) for line in result.stdout.splitlines()[-2:]] == [REPO_ROOT, REPO_ROOT]


# --- Messages -----------------------------------------------------------------------------------


def test_describe_names_files_without_full_paths(tmp_path):
    resolved = resolve("checkpoint", tmp_path, {})
    short = settings.describe(resolved.checked, root=tmp_path)
    assert short == ("GOG_CHECKPOINT environment variable: not set; GOG_CHECKPOINT in .env: not set; "
                     "standard layout checkpoints/unet_best.pth: missing; "
                     "built-in default runs/unet_refined_sar/best.pth: missing")
    assert str(tmp_path) not in short
    full = settings.describe(resolved.checked, root=tmp_path, full=True)
    assert str(tmp_path / "checkpoints" / "unet_best.pth") in full


def test_paths_outside_the_repo_show_only_the_file_name(tmp_path):
    outside = tmp_path / "far" / "away" / "model.pth"
    resolved = resolve("checkpoint", tmp_path / "repo", {"GOG_CHECKPOINT": str(outside)})
    assert settings.describe(resolved.checked, root=tmp_path / "repo") == \
        "GOG_CHECKPOINT environment variable model.pth: missing"


def test_last_state_marks_the_interpreter_that_was_used(tmp_path):
    resolved = resolve("python", tmp_path, {})
    assert settings.describe(resolved.checked, root=tmp_path, last_state="no PyTorch").endswith(": no PyTorch")
