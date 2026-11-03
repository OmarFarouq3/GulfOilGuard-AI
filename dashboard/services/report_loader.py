"""Team A's evaluation report: per-image scores and which checkpoint was scored.

Files (all optional; see config.REPORT_FILES and config.EVALUATION_FILES):
- ``outputs/report/per_image_metrics.csv`` (detection/report.py): columns ``file``,
  ``ref_oil_pixels``, ``dice``, ``iou``, ``precision``, ``recall``, optionally ``split``
- ``metrics.json`` / ``summary.json``: the report's ``"split"`` and ``"checkpoint_sha256"``

train/ and val/ reuse the same file names, so a row only ever matches an image on BOTH split and
file name. A row's split comes from its ``split`` column, else from a folder in ``file``
(``val/x.png``), else from the report's ``"split"``; with none of these it stays unknown and
matches nothing. Nothing is guessed.

No Streamlit here. Results are cached on the file's path, mtime and size, so a changed file is
re-read on the next rerun and an unchanged one never is.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import config
from services.image_picker import split_from_folders

IMAGE_PIXELS = 256 * 256  # the dataset's crops are 256 x 256
SCORE_COLUMNS = config.DETECTION_METRICS
REQUIRED_COLUMNS = ("file", "ref_oil_pixels", *SCORE_COLUMNS)
SHOWN_PROBLEMS = 3
SHA256 = re.compile(r"[0-9a-f]{64}")
HASH_CHUNK = 1 << 20


@dataclass(frozen=True)
class ImageScore:
    file: str  # bare file name, e.g. "palsar_0.png"
    split: str | None
    ref_oil_pixels: int
    dice: float
    iou: float
    precision: float
    recall: float

    @property
    def ref_oil_fraction(self) -> float:
        return self.ref_oil_pixels / IMAGE_PIXELS

    @property
    def empty_reference(self) -> bool:
        """No oil in the reference mask: the scores are then degenerate (0 or 1)."""
        return self.ref_oil_pixels == 0

    def scores(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in SCORE_COLUMNS}


@dataclass
class PerImageReport:
    rows: dict[tuple[str | None, str], ImageScore] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def lookup(self, split: str | None, filename: str) -> ImageScore | None:
        """The row for exactly this split and file name; None if the split is unknown."""
        if split is None:
            return None
        return self.rows.get((split, filename))


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size) if path.is_file() else None


# --- Parsing ----------------------------------------------------------------------------------


def _score(text: str, name: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{name} {text!r} is not a number") from None
    if math.isnan(value):
        raise ValueError(f"{name} is NaN")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} {text} is outside [0, 1]")
    return value


def _pixels(text: str) -> int:
    try:
        value = int(text)  # "12.5", "nan" and "" are not whole numbers
    except ValueError:
        raise ValueError(f"ref_oil_pixels {text!r} is not a whole number") from None
    if not 0 <= value <= IMAGE_PIXELS:
        raise ValueError(f"ref_oil_pixels {text} is outside [0, {IMAGE_PIXELS}]")
    return value


def _row(raw: dict[str, str], default_split: str | None) -> ImageScore:
    file_value = (raw.get("file") or "").strip().replace("\\", "/")
    if not file_value:
        raise ValueError("file is empty")
    path = PurePosixPath(file_value)
    from_path = split_from_folders(path.parts[:-1])
    from_column = (raw.get("split") or "").strip().lower() or None
    if from_column and from_path and from_column != from_path:
        raise ValueError(f"split {from_column!r} disagrees with the folder in {file_value!r}")
    split = from_column or from_path or default_split
    scores = {name: _score((raw.get(name) or "").strip(), name) for name in SCORE_COLUMNS}
    pixels = _pixels((raw.get("ref_oil_pixels") or "").strip())
    return ImageScore(path.name, split, pixels, **scores)


def parse_per_image(text: str, default_split: str | None = None, name: str = "per_image_metrics.csv") -> PerImageReport:
    """Parse the CSV text. Bad rows are skipped and counted; a missing column gives no rows."""
    report = PerImageReport()
    reader = csv.DictReader(io.StringIO(text))
    try:
        header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            report.warnings.append(f"`{name}` has no {', '.join(f'`{c}`' for c in missing)} column; "
                                   "per-image scores are not shown.")
            return report
        problems, total, seen = [], 0, {}
        for number, raw in enumerate(reader, start=2):  # line 1 is the header
            total += 1
            try:
                row = _row(raw, default_split)
            except ValueError as exc:
                problems.append(f"line {number}: {exc}")
                continue
            key = (row.split, row.file)
            if key in seen:
                problems.append(f"line {number}: {row.file} appears twice for split {row.split}; "
                                f"both rows dropped (line {seen[key]})")
                report.rows.pop(key, None)
                continue
            seen[key] = number
            report.rows[key] = row
    except csv.Error as exc:
        report.warnings.append(f"`{name}` is not a valid CSV file ({exc}).")
        return report
    if problems:
        shown = "; ".join(problems[:SHOWN_PROBLEMS]) + (" ..." if len(problems) > SHOWN_PROBLEMS else "")
        report.warnings.append(f"`{name}`: skipped {len(problems)} of {total} rows ({shown}).")
    if report.rows and all(split is None for split, _file in report.rows):
        report.warnings.append(f"`{name}`: no split is known for its rows (no `split` column, no folder in "
                               "`file`, no `\"split\"` in metrics.json or summary.json), so they match no image.")
    return report


@lru_cache(maxsize=8)
def _per_image_cached(path_str: str, stamp: tuple[int, int], default_split: str | None) -> PerImageReport:
    path = Path(path_str)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return PerImageReport(warnings=[f"Could not read `{path.name}` ({type(exc).__name__})."])
    return parse_per_image(text, default_split, path.name)


def load_per_image(path: Path | None = None, default_split: str | None = None) -> PerImageReport:
    """Parsed per-image rows (default: outputs/report/per_image_metrics.csv); empty if the file is missing.

    ``default_split`` is the report's split, used for rows that do not carry their own.
    """
    path = Path(path) if path is not None else config.REPORT_FILES["per_image"]
    stamp = _stamp(path)
    if stamp is None:
        return PerImageReport()
    report = _per_image_cached(str(path), stamp, default_split)
    return PerImageReport(dict(report.rows), list(report.warnings))  # callers may not alter the cache


# --- metrics.json / summary.json ---------------------------------------------------------------


@lru_cache(maxsize=16)
def _json_cached(path_str: str, stamp: tuple[int, int]) -> dict[str, Any] | None:
    try:
        value = json.loads(Path(path_str).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None  # detection_loader already reports unreadable evaluation files
    return value if isinstance(value, dict) else None


def _evaluation_values(key: str, paths=None) -> list[tuple[str, Any]]:
    """(file name, value) of ``key`` in each evaluation file that has it, in config.EVALUATION_FILES order."""
    found = []
    for path in paths if paths is not None else config.EVALUATION_FILES:
        stamp = _stamp(Path(path))
        raw = _json_cached(str(path), stamp) if stamp else None
        if raw is not None and key in raw:
            found.append((Path(path).name, raw[key]))
    return found


def report_split(paths=None) -> tuple[str | None, list[str]]:
    """The evaluated split from metrics.json / summary.json, or None. Disagreeing files give None."""
    values = {(str(v).strip().lower() if isinstance(v, str) else None) for _name, v in _evaluation_values("split", paths)}
    values.discard("")
    if None in values:
        return None, ["`split` in metrics.json / summary.json should be text such as \"val\"."]
    if len(values) > 1:
        return None, [f"metrics.json and summary.json name different splits ({', '.join(sorted(values))}); "
                      "per-image scores without their own split match no image."]
    return next(iter(values), None), []


def per_image_report() -> PerImageReport:
    """outputs/report/per_image_metrics.csv, with the report's split for rows without their own."""
    split, warnings = report_split()
    report = load_per_image(default_split=split)
    report.warnings[:0] = warnings
    return report


# --- Checkpoint verification -------------------------------------------------------------------

CheckpointState = Literal["match", "mismatch", "unreported", "no_checkpoint"]
CHECKPOINT_MESSAGES = {
    "match": "Scores were computed on this checkpoint.",
    "mismatch": "These scores were computed on a different checkpoint than the one running.",
    "unreported": "The report doesn't say which checkpoint was scored.",
    "no_checkpoint": "The report names the checkpoint it scored, but there is no checkpoint on this "
                     "computer to compare it with.",
}


@dataclass(frozen=True)
class CheckpointCheck:
    state: CheckpointState
    warnings: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return CHECKPOINT_MESSAGES[self.state]


@lru_cache(maxsize=4)
def _sha256_cached(path_str: str, stamp: tuple[int, int]) -> str:
    digest = hashlib.sha256()
    with open(path_str, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str | None:
    """SHA-256 of a file, read in chunks; cached on path + mtime + size. None if it can't be read."""
    stamp = _stamp(Path(path))
    if stamp is None:
        return None
    try:
        return _sha256_cached(str(path), stamp)
    except OSError:
        return None


def check_checkpoint(checkpoint: Path, paths=None) -> CheckpointCheck:
    """Compare the ``checkpoint_sha256`` the evaluation files report with the checkpoint in use."""
    reported, warnings = set(), []
    for name, value in _evaluation_values("checkpoint_sha256", paths):
        text = value.strip().lower() if isinstance(value, str) else ""
        if SHA256.fullmatch(text):
            reported.add(text)
        else:
            warnings.append(f"`{name}`: `checkpoint_sha256` is not a SHA-256 (64 hex characters); ignored.")
    if not reported:
        return CheckpointCheck("unreported", tuple(warnings))
    actual = file_sha256(checkpoint)
    if actual is None:
        return CheckpointCheck("no_checkpoint", tuple(warnings))
    if reported != {actual}:
        return CheckpointCheck("mismatch", (*warnings, f"{CHECKPOINT_MESSAGES['mismatch']} (report: "
                                            f"{', '.join(sorted(h[:12] for h in reported))}…; running "
                                            f"{Path(checkpoint).name}: {actual[:12]}…)"))
    return CheckpointCheck("match", tuple(warnings))
