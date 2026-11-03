"""services.image_picker: listing, random picking and ids. All images are generated in tmp_path."""

from __future__ import annotations

import os
import random
import re

import pytest
from dashboard_testkit import make_image

from services import image_picker as ip


def test_missing_and_empty_dirs_give_no_images(tmp_path):
    assert ip.list_images(tmp_path / "missing") == []
    (tmp_path / "empty").mkdir()
    assert ip.list_images(tmp_path / "empty") == []


def test_dir_with_only_non_images_gives_no_images(tmp_path):
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "fake.png").write_bytes(b"\x89PNG not really")
    assert ip.list_images(tmp_path) == []


def test_lists_only_readable_visible_images_recursively(tmp_path):
    expected = [make_image(tmp_path / "a.png"), make_image(tmp_path / "b.JPG"), make_image(tmp_path / "nested" / "deep" / "c.jpeg")]
    make_image(tmp_path / "scene.tif")  # unsupported extension (PNG bytes, wrong name)
    make_image(tmp_path / ".hidden.png")
    make_image(tmp_path / "._resource_fork.png")
    make_image(tmp_path / ".cache" / "inside_hidden_dir.png")
    (tmp_path / "corrupt.png").write_bytes(b"garbage")
    (tmp_path / "truncated.jpg").write_bytes(make_image(tmp_path / "tmp.jpg").read_bytes()[:20])
    (tmp_path / "tmp.jpg").unlink()
    (tmp_path / "folder.png").mkdir()  # a directory with an image extension

    assert ip.list_images(tmp_path) == sorted(expected)


def test_image_dir_resolution_argument_env_default(tmp_path, monkeypatch):
    from services import settings
    assert ip.image_dir() == settings.ROOT / "assets" / "images"  # conftest: no GOG_IMAGE_DIR, empty layout
    monkeypatch.setenv("GOG_IMAGE_DIR", str(tmp_path))
    assert ip.image_dir() == tmp_path
    assert ip.image_dir(tmp_path / "arg") == tmp_path / "arg"


def test_pick_is_deterministic_with_seeded_rng(image_dir):
    first = [ip.pick_random_image(image_dir, rng=random.Random(42)) for _ in range(5)]
    assert len(set(first)) == 1
    sequence_a = [ip.pick_random_image(image_dir, rng=rng) for rng in [random.Random(7)] for _ in range(10)]
    rng = random.Random(7)
    sequence_b = [ip.pick_random_image(image_dir, rng=rng) for _ in range(10)]
    assert sequence_a == sequence_b


@pytest.mark.parametrize("count", [2, 3])
def test_pick_honours_exclude_when_there_is_a_choice(tmp_path, count):
    images = [make_image(tmp_path / f"{i}.png", seed=i) for i in range(count)]
    rng = random.Random(0)
    for excluded in images:
        for _ in range(30):
            assert ip.pick_random_image(tmp_path, exclude=excluded, rng=rng) != excluded
        assert ip.pick_random_image(tmp_path, exclude=str(excluded), rng=rng) != excluded  # str works too


def test_pick_single_and_none(tmp_path):
    only = make_image(tmp_path / "only.png")
    assert ip.pick_random_image(tmp_path, exclude=only, rng=random.Random(1)) == only
    assert ip.pick_random_image(tmp_path / "missing") is None
    assert ip.choose_image([]) is None


@pytest.mark.parametrize("name, stem", [
    ("S1A IW (copy).v2.png", "s1a_iw_copy_v2"),
    ("Scene_01.PNG", "scene_01"),
    ("ünïcode scène.png", "n_code_sc_ne"),
    ("---.png", "---"),
    ("!!!.png", "image"),
    ("a" * 100 + ".png", "a" * 60),
])
def test_image_id_is_sanitised_and_stable(tmp_path, name, stem):
    path = tmp_path / name
    image_id = ip.image_id(path, root=tmp_path)
    assert re.fullmatch(r"[a-z0-9_-]+", image_id)
    assert image_id.rsplit("-", 1)[0] == stem
    assert ip.image_id(path, root=tmp_path) == image_id  # stable across calls


def test_image_ids_do_not_collide_for_same_stem(tmp_path):
    """Decided behaviour: same stem in other folders / formats -> different ids (no silent overwrite)."""
    paths = [tmp_path / "a" / "x.png", tmp_path / "b" / "x.png", tmp_path / "x.png", tmp_path / "x.jpg"]
    ids = [ip.image_id(p, root=tmp_path) for p in paths]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("x-") for i in ids)


def test_image_id_does_not_depend_on_the_os(tmp_path, monkeypatch):
    """Same dataset, same ids everywhere: no os.path.normcase (which folds case on Windows only)."""
    path = tmp_path / "Sub" / "Scene.png"
    expected = ip.image_id(path, root=tmp_path)
    monkeypatch.setattr(os.path, "normcase", lambda p: p.upper())  # would change a normcase-based id
    assert ip.image_id(path, root=tmp_path) == expected
    digest = ip.hashlib.sha1(b"Sub/Scene.png").hexdigest()[:8]  # exact POSIX relative path
    assert expected == f"scene-{digest}"


def test_case_only_difference_still_gets_distinct_ids(tmp_path):
    """On case-sensitive file systems X.png and x.png are two files: the readable part is shared,
    the hash keeps them apart (the decided no-silent-collision behaviour)."""
    upper, lower = ip.image_id(tmp_path / "X.png", root=tmp_path), ip.image_id(tmp_path / "x.png", root=tmp_path)
    assert upper != lower and upper.startswith("x-") and lower.startswith("x-")


@pytest.mark.parametrize("name, expected", [
    ("sentinel_12.png", "Sentinel-1 SAR sample from the local dataset"),
    ("Sentinel_7.PNG", "Sentinel-1 SAR sample from the local dataset"),
    ("palsar_1088.png", "ALOS PALSAR SAR sample from the local dataset"),
    ("sub/palsar_0.jpg", "ALOS PALSAR SAR sample from the local dataset"),
    ("scene_0.png", None), ("sentinel12.png", None), ("s1_sentinel_3.png", None), ("palsar.png", None),
])
def test_image_source_only_from_documented_prefixes(name, expected):
    assert ip.image_source(name) == expected


def test_image_id_is_relative_to_the_image_folder(tmp_path):
    """Moving the whole dataset keeps the ids; a file outside the folder still gets an id."""
    assert ip.image_id(tmp_path / "one" / "x.png", root=tmp_path / "one") == \
        ip.image_id(tmp_path / "two" / "x.png", root=tmp_path / "two")
    assert re.fullmatch(r"x-[0-9a-f]{8}", ip.image_id(tmp_path / "x.png", root=tmp_path / "elsewhere"))


# --- Split from folder names ----------------------------------------------------------------------


@pytest.mark.parametrize("relative, split", [
    ("val/palsar_0.png", "val"),
    ("train/palsar_0.png", "train"),
    ("test/x.png", "test"),
    ("Val/x.png", "val"),                       # folder names are compared case-insensitively
    ("val/sub/x.png", "val"),                   # nearest split folder above the image
    ("train/val/x.png", "val"),
    ("val/train/x.png", "train"),
    ("x.png", None),                            # directly in the image folder "images"
    ("validation/x.png", None),                 # only the exact names count
    ("training_data/x.png", None),
])
def test_split_from_the_folders_under_the_image_folder(tmp_path, relative, split):
    root = tmp_path / "images"
    assert ip.image_split(root / relative, root=root) == split


def test_image_folder_itself_named_val(tmp_path, monkeypatch):
    """GOG_IMAGE_DIR pointing straight at a folder called val."""
    root = tmp_path / "assets" / "images" / "val"
    image = make_image(root / "palsar_0.png")
    monkeypatch.setenv("GOG_IMAGE_DIR", str(root))
    assert ip.image_split(image) == "val"
    assert ip.image_split(make_image(root / "nested" / "x.png")) == "val"


def test_folders_above_the_image_folder_do_not_count(tmp_path):
    root = tmp_path / "val" / "images"  # "val" is above the image folder: unknown
    assert ip.image_split(root / "x.png", root=root) is None


def test_image_outside_the_image_folder_is_unknown(tmp_path):
    assert ip.image_split(tmp_path / "val" / "x.png", root=tmp_path / "images") is None


def test_split_from_folders_is_pure():
    assert ip.split_from_folders(["data", "TRAIN", "x"]) == "train"
    assert ip.split_from_folders([]) is None
