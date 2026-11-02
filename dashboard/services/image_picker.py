"""Find radar images in the local dataset folder and pick one at random.

No Streamlit here, so everything is easy to unit-test. The folder resolves in this order:
1. the ``directory`` argument of each function (tests)
2. the ``GOG_IMAGE_DIR`` environment variable
3. ``<repo root>/assets/images`` (git-ignored: every machine needs its own copy)

The picked image is a random sample from the dataset. It is NOT geolocated to any spill.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

import config

IMAGE_DIR = config.REPO_ROOT / "assets" / "images"
IMAGE_DIR_ENV = "GOG_IMAGE_DIR"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def image_dir(directory: str | Path | None = None) -> Path:
    """The folder to search: the argument, else GOG_IMAGE_DIR, else assets/images."""
    if directory is not None:
        return Path(directory)
    env_value = os.environ.get(IMAGE_DIR_ENV)
    return Path(env_value).expanduser() if env_value else IMAGE_DIR


def _is_hidden(path: Path, root: Path) -> bool:
    """Dot-files and anything inside a dot-folder (also macOS ``._x`` resource forks)."""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _is_readable(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:  # PIL raises many exception types for bad images
        return False


def list_images(directory: str | Path | None = None) -> list[Path]:
    """Every readable .png/.jpg/.jpeg below the folder (recursive), sorted. [] if missing or empty."""
    root = image_dir(directory)
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()
        and not _is_hidden(path, root) and _is_readable(path)
    )


def choose_image(images: Sequence[Path], exclude: str | Path | None = None,
                 rng: random.Random | None = None) -> Path | None:
    """Random image from ``images``; avoids ``exclude`` (the previous pick) when there is a choice."""
    if not images:
        return None
    candidates = list(images)
    if exclude is not None and len(candidates) > 1:
        candidates = [p for p in candidates if Path(p) != Path(exclude)] or candidates
    return (rng or random).choice(candidates)


def pick_random_image(directory: str | Path | None = None, exclude: str | Path | None = None,
                      rng: random.Random | None = None) -> Path | None:
    """Random readable image from the folder, or None if there is none."""
    return choose_image(list_images(directory), exclude, rng)


def image_id(path: str | Path, root: str | Path | None = None) -> str:
    """Stable id ``<stem>-<hash>`` limited to [A-Za-z0-9_-] (key for outputs/detection/<id>_*).

    The readable part is the sanitised file stem; the 8-hex hash is of the path relative to the
    image folder (``root``, default ``image_dir()``), so ``a/x.png``, ``b/x.png`` and ``x.jpg``
    never share an id and overwrite each other's results. Case is folded where the file system
    ignores it (Windows), so one file always gets one id.
    """
    path = Path(path)
    base = Path(root) if root is not None else image_dir()
    try:
        key = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:  # outside the image folder: fall back to the absolute path
        key = path.resolve().as_posix()
    digest = hashlib.sha1(os.path.normcase(key).encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_")[:60] or "image"
    return f"{stem}-{digest}"
