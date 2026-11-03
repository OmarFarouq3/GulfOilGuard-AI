"""Where the detection model, its Python and the radar images are: no setup for the standard layout.

Each setting resolves in this order (the first hit wins):
1. a real environment variable (``GOG_CHECKPOINT``, ``GOG_DETECTION_PYTHON``, ``GOG_IMAGE_DIR``)
2. the same key in ``<repo root>/.env`` (optional and git-ignored; see ``.env.example``)
3. the standard layout: ``checkpoints/unet_best.pth``, ``.venv-detect/`` (``Scripts/python.exe``
   on Windows, ``bin/python`` elsewhere), ``assets/images``. The checkpoint and the interpreter
   are only taken from here when the file exists.
4. the built-in fallback: ``config.DETECTION_CHECKPOINT``; the dashboard's own Python (which has
   no torch, so detection then reports "setup needed")

The repo root comes from this file's location (``config.REPO_ROOT``), never from the working
directory, and relative paths from either source are resolved against it, so the dashboard finds
everything however Streamlit is launched. Every resolution records what it checked, in order,
for the error messages. Standard library only, no Streamlit: easy to test.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import config

ROOT = config.REPO_ROOT  # the repo root; tests point it at a temporary layout
ENV_FILE = ".env"
CHECKPOINT_KEY = "GOG_CHECKPOINT"
PYTHON_KEY = "GOG_DETECTION_PYTHON"
IMAGE_DIR_KEY = "GOG_IMAGE_DIR"
STANDARD_CHECKPOINT = Path("checkpoints") / "unet_best.pth"
DETECT_VENV = ".venv-detect"
STANDARD_IMAGE_DIR = Path("assets") / "images"
DEFAULT_CHECKPOINT = config.DETECTION_CHECKPOINT.relative_to(config.REPO_ROOT)
KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Check:
    """One place that was looked at: ``path`` is None when the variable was not set."""

    source: str
    path: Path | None
    found: bool


@dataclass(frozen=True)
class Resolved:
    path: Path
    source: str
    checked: tuple[Check, ...]  # every place tried, in order; the last one is the one used


# --- .env -----------------------------------------------------------------------------------


def read_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse ``KEY=VALUE`` lines. Returns (values, problems); a missing file is ({}, []).

    Blank lines and ``#`` comments are skipped, an ``export`` prefix is allowed, matching
    single or double quotes are stripped, and an unquoted value may end in `` # comment``.
    A malformed line is skipped and reported; the other lines still count.
    """
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}, []
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"`{ENV_FILE}` could not be read ({type(exc).__name__})."]
    values, problems = {}, []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not KEY_PATTERN.fullmatch(key):
            problems.append(f"`{ENV_FILE}` line {number}: expected KEY=VALUE; skipped.")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values, problems


def env_file(root: Path | None = None) -> tuple[dict[str, str], list[str]]:
    return read_env_file((root or ROOT) / ENV_FILE)


# --- Resolution -----------------------------------------------------------------------------


def _path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _interpreter(value: str, root: Path) -> Path:
    """A bare command name (``python3``) is looked up on PATH; anything else is a path."""
    if not any(sep in value for sep in ("/", "\\")):
        found = shutil.which(value)
        return Path(found) if found else Path(value)
    return _path(value, root)


def _resolve(key: str, root: Path | None, environ: Mapping[str, str | None] | None,
             standard: Path | None, fallback: Path, fallback_source: str, *, interpreter: bool = False) -> Resolved:
    root = Path(root) if root is not None else ROOT
    environ = os.environ if environ is None else environ
    from_file, _problems = env_file(root)
    checks: list[Check] = []
    for source, value in ((f"{key} environment variable", environ.get(key)), (f"{key} in .env", from_file.get(key))):
        value = (value or "").strip()
        if value:  # an explicit setting wins even when the file is missing: the message then says so
            path = _interpreter(value, root) if interpreter else _path(value, root)
            checks.append(Check(source, path, path.exists()))
            return Resolved(path, source, tuple(checks))
        checks.append(Check(source, None, False))
    if standard is not None:
        exists = standard.exists()
        checks.append(Check("standard layout", standard, exists))
        if exists:
            return Resolved(standard, "standard layout", tuple(checks))
    checks.append(Check(fallback_source, fallback, fallback.exists()))
    return Resolved(fallback, fallback_source, tuple(checks))


def venv_python(root: Path, os_name: str | None = None) -> Path:
    """The interpreter inside ``.venv-detect`` for this OS layout."""
    windows = (os_name or os.name) == "nt"
    return root / DETECT_VENV / ("Scripts/python.exe" if windows else "bin/python")


def resolve_checkpoint(root: Path | None = None, environ: Mapping[str, str | None] | None = None) -> Resolved:
    root = Path(root) if root is not None else ROOT
    return _resolve(CHECKPOINT_KEY, root, environ, root / STANDARD_CHECKPOINT, root / DEFAULT_CHECKPOINT,
                    "built-in default")


def resolve_python(root: Path | None = None, environ: Mapping[str, str | None] | None = None,
                   os_name: str | None = None) -> Resolved:
    root = Path(root) if root is not None else ROOT
    return _resolve(PYTHON_KEY, root, environ, venv_python(root, os_name), Path(sys.executable),
                    "the dashboard's own Python", interpreter=True)


def resolve_image_dir(root: Path | None = None, environ: Mapping[str, str | None] | None = None) -> Resolved:
    root = Path(root) if root is not None else ROOT
    return _resolve(IMAGE_DIR_KEY, root, environ, None, root / STANDARD_IMAGE_DIR, "standard layout")


def given(path: Path | str, source: str) -> Resolved:
    """A value passed in directly (tests, scripts): no lookup."""
    path = Path(path)
    return Resolved(path, source, (Check(source, path, path.exists()),))


# --- Messages -------------------------------------------------------------------------------


def display(path: Path, root: Path | None = None) -> str:
    """``checkpoints/unet_best.pth`` inside the repo, else just the file name (no local paths)."""
    try:
        return Path(path).resolve().relative_to(Path(root or ROOT).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def describe(checks: tuple[Check, ...], *, full: bool = False, last_state: str | None = None,
             root: Path | None = None, separator: str = "; ") -> str:
    """'GOG_CHECKPOINT environment variable: not set; standard layout checkpoints/unet_best.pth: missing'.

    ``full`` shows absolute paths (only for ?dev=1). ``last_state`` overrides the state of the
    place that was used (e.g. "no PyTorch").
    """
    parts = []
    for index, check in enumerate(checks):
        if check.path is None:
            parts.append(f"{check.source}: not set")
            continue
        shown = str(check.path) if full else display(check.path, root)
        state = "found" if check.found else "missing"
        if last_state and index == len(checks) - 1:
            state = last_state
        parts.append(f"{check.source} {shown}: {state}")
    return separator.join(parts)
