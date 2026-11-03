"""Find radar images in the local dataset folder and pick one at random.

No Streamlit here, so everything is easy to unit-test. The folder resolves in this order:
1. the ``directory`` argument of each function (tests)
2. the ``GOG_IMAGE_DIR`` environment variable
3. ``<repo root>/assets/images`` (git-ignored: every machine needs its own copy)

(GOG_IMAGE_DIR may also come from ``<repo root>/.env``; see services/settings.py.) The picked
image is a random sample from the dataset. It is NOT geolocated to any spill.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

import config
from services import settings

IMAGE_DIR = config.REPO_ROOT / "assets" / "images"
IMAGE_DIR_ENV = settings.IMAGE_DIR_KEY
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def image_dir(directory: str | Path | None = None) -> Path:
    """The folder to search: the argument, else GOG_IMAGE_DIR (environment, then .env), else assets/images."""
    if directory is not None:
        return Path(directory)
    return settings.resolve_image_dir().path


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


# File-name prefix -> sensor, for the Refined Deep-SAR SOS crops in assets/images
# (docs/literature_review.md: "ALOS PALSAR and Sentinel-1A, 8,070 crops of 256x256 px").
SENSOR_PREFIXES = {"sentinel_": "Sentinel-1", "palsar_": "ALOS PALSAR"}


def image_source(path: str | Path) -> str | None:
    """'Sentinel-1 SAR sample from the local dataset' from the file-name prefix; None when unknown.

    Only the documented prefixes count; anything else is not guessed.
    """
    stem = Path(path).stem.lower()
    sensor = next((name for prefix, name in SENSOR_PREFIXES.items() if stem.startswith(prefix)), None)
    return f"{sensor} SAR sample from the local dataset" if sensor else None


# Dataset split folders. train/ and val/ reuse the same file names, so a name alone is ambiguous.
SPLITS = ("train", "val", "test")


def split_from_folders(folders: Sequence[str]) -> str | None:
    """The nearest (last) folder named train / val / test, case-insensitively; None if there is none."""
    return next((name.lower() for name in reversed(folders) if name.lower() in SPLITS), None)


def image_split(path: str | Path, root: str | Path | None = None) -> str | None:
    """Split of an image from its folders: ``.../images/val/x.png`` -> ``"val"``; None when unknown.

    Only the folders from the image's own folder up to and including the image folder ``root``
    (default ``image_dir()``) count, so GOG_IMAGE_DIR may point straight at ``.../val``. Folders
    above the image folder, and images outside it, give None: the split is never guessed.
    """
    path = Path(path)
    base = Path(root) if root is not None else image_dir()
    try:
        inside = path.resolve().parent.relative_to(base.resolve()).parts
    except ValueError:
        return None
    return split_from_folders([base.resolve().name, *inside])


def image_id(path: str | Path, root: str | Path | None = None) -> str:
    """Stable id ``<stem>-<hash>`` limited to [A-Za-z0-9_-] (key for outputs/detection/<id>_*).

    The readable part is the sanitised, lowercased file stem; the 8-hex hash is of the exact
    relative path (``root``, default ``image_dir()``, as a POSIX string), so ``a/x.png``,
    ``b/x.png``, ``x.jpg`` and, on case-sensitive systems, ``X.png`` never share an id and
    overwrite each other's results. Nothing depends on the OS: the same dataset gets the same
    ids on Windows, macOS and Linux (paths come from ``list_images``, which returns the names
    as stored on disk).
    """
    path = Path(path)
    base = Path(root) if root is not None else image_dir()
    try:
        key = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:  # outside the image folder: fall back to the absolute path
        key = path.resolve().as_posix()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^a-z0-9_-]+", "_", path.stem.lower()).strip("_")[:60] or "image"
    return f"{stem}-{digest}"
