"""services/report_loader.py: per-image CSV parsing, split-aware lookup, report split, checkpoint hash.

Every file is written to tmp_path; nothing reads the real outputs/ or assets/.
The CSV format is detection/report.py's: file, ref_oil_pixels, dice, iou, precision, recall.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from services import report_loader
from services.report_loader import check_checkpoint, load_per_image, parse_per_image, report_split

HEADER = "file,ref_oil_pixels,dice,iou,precision,recall\n"
PALSAR_0 = "palsar_0.png,13039,0.7725,0.6294,0.7422,0.8054\n"
SENTINEL_1 = "sentinel_1.png,0,1.0,1.0,1.0,1.0\n"


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Files rewritten within one test must never be served from an earlier test's cache."""
    for cached in (report_loader._per_image_cached, report_loader._json_cached, report_loader._sha256_cached):
        cached.cache_clear()
    yield


def write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- Parsing -----------------------------------------------------------------------------------


def test_valid_rows_with_the_report_split():
    report = parse_per_image(HEADER + PALSAR_0 + SENTINEL_1, default_split="val")
    assert not report.warnings and len(report.rows) == 2
    row = report.lookup("val", "palsar_0.png")
    assert (row.file, row.split, row.ref_oil_pixels) == ("palsar_0.png", "val", 13039)
    assert row.scores() == {"dice": 0.7725, "iou": 0.6294, "precision": 0.7422, "recall": 0.8054}
    assert row.ref_oil_fraction == pytest.approx(13039 / 65536) and not row.empty_reference
    assert report.lookup("val", "sentinel_1.png").empty_reference


@pytest.mark.parametrize("line, reason", [
    ("palsar_1.png,100,nan,0.5,0.5,0.5", "dice is NaN"),
    ("palsar_1.png,100,0.5,NaN,0.5,0.5", "iou is NaN"),
    ("palsar_1.png,100,1.2,0.5,0.5,0.5", "dice 1.2 is outside [0, 1]"),
    ("palsar_1.png,100,0.5,0.5,-0.01,0.5", "precision -0.01 is outside [0, 1]"),
    ("palsar_1.png,100,0.5,0.5,0.5,inf", "recall inf is outside [0, 1]"),
    ("palsar_1.png,100,high,0.5,0.5,0.5", "dice 'high' is not a number"),
    ("palsar_1.png,-3,0.5,0.5,0.5,0.5", "ref_oil_pixels -3 is outside"),
    ("palsar_1.png,12.5,0.5,0.5,0.5,0.5", "ref_oil_pixels '12.5' is not a whole number"),
    ("palsar_1.png,nan,0.5,0.5,0.5,0.5", "ref_oil_pixels 'nan' is not a whole number"),
    ("palsar_1.png,70000,0.5,0.5,0.5,0.5", "ref_oil_pixels 70000 is outside"),
    (",100,0.5,0.5,0.5,0.5", "file is empty"),
    ("palsar_1.png,100,0.5", "iou '' is not a number"),           # short row
])
def test_bad_rows_are_skipped_and_counted(line, reason):
    report = parse_per_image(HEADER + PALSAR_0 + line + "\n" + SENTINEL_1, default_split="val")
    assert set(report.rows) == {("val", "palsar_0.png"), ("val", "sentinel_1.png")}
    assert len(report.warnings) == 1
    assert "skipped 1 of 3 rows" in report.warnings[0] and "line 3" in report.warnings[0]
    assert reason in report.warnings[0]


def test_many_bad_rows_are_summarised():
    bad = "".join(f"x_{i}.png,1,nan,0,0,0\n" for i in range(5))
    report = parse_per_image(HEADER + bad + PALSAR_0, default_split="val")
    assert len(report.rows) == 1 and "skipped 5 of 6 rows" in report.warnings[0] and report.warnings[0].count("line ") == 3


def test_missing_column_gives_no_rows():
    report = parse_per_image("file,dice,iou,precision,recall\npalsar_0.png,0.7,0.6,0.7,0.8\n", default_split="val")
    assert report.rows == {} and "`ref_oil_pixels`" in report.warnings[0]


def test_empty_text_gives_no_rows_and_a_warning():
    report = parse_per_image("", default_split="val")
    assert report.rows == {} and report.warnings


def test_header_is_case_and_space_tolerant():
    report = parse_per_image(" File , REF_OIL_PIXELS,Dice,IoU,Precision,Recall\n" + PALSAR_0, default_split="val")
    assert report.lookup("val", "palsar_0.png") is not None


def test_duplicate_rows_for_one_split_are_dropped_not_guessed():
    report = parse_per_image(HEADER + PALSAR_0 + "palsar_0.png,10,0.1,0.1,0.1,0.1\n" + SENTINEL_1, default_split="val")
    assert report.lookup("val", "palsar_0.png") is None and report.lookup("val", "sentinel_1.png") is not None
    assert "appears twice" in report.warnings[0]


# --- Where a row's split comes from -------------------------------------------------------------


def test_split_column_wins_over_the_report_split():
    text = HEADER.replace("recall\n", "recall,split\n") + PALSAR_0.replace("\n", ",TEST\n")
    report = parse_per_image(text, default_split="val")
    assert report.lookup("test", "palsar_0.png") is not None and report.lookup("val", "palsar_0.png") is None


def test_empty_split_cell_falls_back_to_the_report_split():
    text = HEADER.replace("recall\n", "recall,split\n") + PALSAR_0.replace("\n", ",\n")
    assert parse_per_image(text, default_split="val").lookup("val", "palsar_0.png") is not None


@pytest.mark.parametrize("name", ["val/palsar_0.png", "data\\val\\palsar_0.png", "images/VAL/palsar_0.png"])
def test_folder_in_the_file_column_gives_the_split(name):
    report = parse_per_image(HEADER + PALSAR_0.replace("palsar_0.png", name), default_split=None)
    assert report.lookup("val", "palsar_0.png") is not None and not report.warnings


def test_folder_in_the_file_column_wins_over_the_report_split():
    report = parse_per_image(HEADER + PALSAR_0.replace("palsar_0.png", "train/palsar_0.png"), default_split="val")
    assert report.lookup("train", "palsar_0.png") is not None and report.lookup("val", "palsar_0.png") is None


def test_split_column_and_folder_must_agree():
    text = HEADER.replace("recall\n", "recall,split\n") + "val/palsar_0.png,1,0.5,0.5,0.5,0.5,train\n"
    report = parse_per_image(text)
    assert report.rows == {} and "disagrees" in report.warnings[0]


def test_no_split_anywhere_marks_rows_unknown_and_matches_nothing():
    report = parse_per_image(HEADER + PALSAR_0, default_split=None)
    assert set(report.rows) == {(None, "palsar_0.png")}
    assert report.rows[(None, "palsar_0.png")].split is None
    assert all(report.lookup(split, "palsar_0.png") is None for split in ("train", "val", "test", None))
    assert "no split is known" in report.warnings[0]


# --- Lookup needs split AND file name -----------------------------------------------------------


def test_train_image_never_gets_the_val_row():
    report = parse_per_image(HEADER + PALSAR_0, default_split="val")
    assert report.lookup("val", "palsar_0.png") is not None
    assert report.lookup("train", "palsar_0.png") is None
    assert report.lookup(None, "palsar_0.png") is None
    assert report.lookup("val", "PALSAR_0.png") is None and report.lookup("val", "palsar_0") is None


def test_regression_same_file_name_in_train_and_val_with_different_rows():
    """The real bug: train/ and val/ both have palsar_0.png; each must get its own row, never the other's."""
    text = ("file,split,ref_oil_pixels,dice,iou,precision,recall\n"
            "palsar_0.png,val,13039,0.7725,0.6294,0.7422,0.8054\n"
            "palsar_0.png,train,500,0.1111,0.1,0.2,0.3\n")
    report = parse_per_image(text)
    assert not report.warnings
    assert report.lookup("val", "palsar_0.png").dice == 0.7725
    assert report.lookup("train", "palsar_0.png").dice == 0.1111
    assert report.lookup("test", "palsar_0.png") is None


# --- Files and caching --------------------------------------------------------------------------


def test_missing_file_is_empty_without_warnings(tmp_path):
    report = load_per_image(tmp_path / "nope.csv", default_split="val")
    assert report.rows == {} and report.warnings == []


def test_file_is_reread_when_it_changes(tmp_path):
    path = write(tmp_path / "per_image_metrics.csv", HEADER + PALSAR_0)
    assert load_per_image(path, "val").lookup("val", "palsar_0.png").dice == 0.7725
    assert load_per_image(path, "val").lookup("val", "palsar_0.png").dice == 0.7725
    assert report_loader._per_image_cached.cache_info().hits == 1  # unchanged file: not parsed again
    write(path, HEADER + PALSAR_0.replace("0.7725", "0.5"))
    assert load_per_image(path, "val").lookup("val", "palsar_0.png").dice == 0.5


def test_returned_report_does_not_alter_the_cache(tmp_path):
    path = write(tmp_path / "per_image_metrics.csv", HEADER + PALSAR_0)
    load_per_image(path, "val").rows.clear()
    assert load_per_image(path, "val").lookup("val", "palsar_0.png") is not None


def test_unreadable_file_is_a_warning(tmp_path):
    path = tmp_path / "per_image_metrics.csv"
    path.write_bytes(b"\xff\xfe\x00bad")
    report = load_per_image(path, "val")
    assert report.rows == {} and report.warnings


# --- The report's split from metrics.json / summary.json ----------------------------------------


def evaluation_files(tmp_path, *contents):
    paths = [tmp_path / f"eval_{i}.json" for i in range(len(contents))]
    for path, content in zip(paths, contents):
        if content is not None:
            write(path, content if isinstance(content, str) else json.dumps(content))
    return paths


def test_report_split_from_the_first_file_that_has_one(tmp_path):
    assert report_split(evaluation_files(tmp_path, None, {"threshold": 0.5}, {"split": "val"})) == ("val", [])


def test_report_split_unknown_without_files(tmp_path):
    assert report_split(evaluation_files(tmp_path, None, "{bad json", {"threshold": 0.5})) == (None, [])


def test_disagreeing_report_splits_give_unknown(tmp_path):
    split, warnings = report_split(evaluation_files(tmp_path, {"split": "val"}, {"split": "test"}))
    assert split is None and "different splits" in warnings[0]


def test_non_text_report_split_is_a_warning(tmp_path):
    split, warnings = report_split(evaluation_files(tmp_path, {"split": 3}))
    assert split is None and warnings


# --- Checkpoint verification --------------------------------------------------------------------


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "unet_best.pth"
    path.write_bytes(b"weights" * 300_000)  # > one hash chunk
    return path


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_file_sha256_matches_hashlib_and_is_cached(checkpoint):
    assert report_loader.file_sha256(checkpoint) == digest(checkpoint)
    report_loader.file_sha256(checkpoint)
    assert report_loader._sha256_cached.cache_info().hits == 1  # not re-hashed on the next rerun
    checkpoint.write_bytes(b"retrained")
    assert report_loader.file_sha256(checkpoint) == hashlib.sha256(b"retrained").hexdigest()


def test_checkpoint_match(tmp_path, checkpoint):
    files = evaluation_files(tmp_path, {"checkpoint_sha256": digest(checkpoint).upper()}, None)
    check = check_checkpoint(checkpoint, files)
    assert check.state == "match" and check.message == "Scores were computed on this checkpoint." and not check.warnings


def test_checkpoint_mismatch_is_a_warning(tmp_path, checkpoint):
    files = evaluation_files(tmp_path, {"checkpoint_sha256": "a" * 64})
    check = check_checkpoint(checkpoint, files)
    assert check.state == "mismatch"
    assert check.message == "These scores were computed on a different checkpoint than the one running."
    assert check.warnings and "aaaaaaaaaaaa" in check.warnings[0]


def test_files_reporting_different_checkpoints_are_a_mismatch(tmp_path, checkpoint):
    files = evaluation_files(tmp_path, {"checkpoint_sha256": digest(checkpoint)}, {"checkpoint_sha256": "b" * 64})
    assert check_checkpoint(checkpoint, files).state == "mismatch"


def test_no_hash_in_the_report_is_a_quiet_note(tmp_path, checkpoint):
    check = check_checkpoint(checkpoint, evaluation_files(tmp_path, {"split": "val"}, None))
    assert check.state == "unreported" and check.message == "The report doesn't say which checkpoint was scored."
    assert not check.warnings


def test_malformed_hash_is_ignored_with_a_warning(tmp_path, checkpoint):
    check = check_checkpoint(checkpoint, evaluation_files(tmp_path, {"checkpoint_sha256": "f6ee7c36"}))
    assert check.state == "unreported" and "not a SHA-256" in check.warnings[0]


def test_reported_hash_without_a_checkpoint_on_this_computer(tmp_path):
    check = check_checkpoint(tmp_path / "missing.pth", evaluation_files(tmp_path, {"checkpoint_sha256": "c" * 64}))
    assert check.state == "no_checkpoint"
