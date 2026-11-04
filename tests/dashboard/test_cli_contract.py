"""The contract between services/inference.py and detection/predict_cli.py (fix 11).

No torch needed: predict_cli imports torch only inside main(), so its real parser can be built here.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from dashboard_testkit import REPO_ROOT, make_image
from PIL import Image

from detection import predict_cli
from services import inference
from shared import detection_cli


def test_command_parses_with_the_real_cli_parser(tmp_path):
    command = inference._command("python", tmp_path / "best.pth", tmp_path / "scene 1.png", tmp_path / "out",
                                 "scene_1-abcd1234")
    assert command[1:3] == ["-m", detection_cli.MODULE]
    args = predict_cli.build_parser().parse_args(command[3:])
    assert args.checkpoint == tmp_path / "best.pth" and args.image == tmp_path / "scene 1.png"
    assert args.out == tmp_path / "out" and args.image_id == "scene_1-abcd1234" and args.device == "cpu"


def test_parser_rejects_a_missing_argument():
    with pytest.raises(SystemExit) as exit_info:
        predict_cli.build_parser().parse_args(["--image", "x.png", "--out", "o", "--image-id", "x"])
    assert exit_info.value.code == detection_cli.EXIT_BAD_ARGS


def test_module_resolves_from_the_repo_root():
    assert importlib.util.find_spec(detection_cli.MODULE) is not None


def test_building_the_parser_does_not_import_torch():
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); from detection.predict_cli import build_parser; "
             "build_parser(); print('torch' in sys.modules)")
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(REPO_ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_cli_accepts_the_dashboard_command_end_to_end(tmp_path):
    """Run the real CLI with the dashboard's real command: it must get past argparse.

    Exit 2 would mean the arguments don't match; without torch it stops with EXIT_NO_TORCH, with
    torch it fails on the fake checkpoint (EXIT_FAILED). Either way the contract holds.
    """
    image = make_image(tmp_path / "in.png")
    (tmp_path / "best.pth").write_bytes(b"not a checkpoint")
    command = inference._command(sys.executable, tmp_path / "best.pth", image, tmp_path / "out", "in-1")
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode in (detection_cli.EXIT_NO_TORCH, detection_cli.EXIT_FAILED), result.stderr[-2000:]


@pytest.mark.parametrize("path", ["dashboard/services/inference.py", "detection/predict_cli.py"])
def test_result_prefix_and_exit_codes_are_defined_once(path):
    """Both sides import the contract from shared/detection_cli.py instead of redefining it."""
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    assigned = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert not assigned & {"RESULT_PREFIX", "EXIT_NO_TORCH", "EXIT_FAILED", "MODULE", "KINDS"}
    assert inference.RESULT_PREFIX is detection_cli.RESULT_PREFIX is predict_cli.RESULT_PREFIX


def test_cli_writes_outputs_atomically(tmp_path, monkeypatch):
    """Fix 7: every PNG lands via a same-folder temp file + replace; a failed write leaves the old file."""
    image = make_image(tmp_path / "in.png", size=(8, 6))
    Image.fromarray(np.zeros((6, 8), dtype=np.uint8)).save(tmp_path / "raw_mask.png")
    out = tmp_path / "out"
    out.mkdir()
    moves = []
    real = predict_cli.atomic_replace
    monkeypatch.setattr(predict_cli, "atomic_replace",
                        lambda s, t, **k: (moves.append((Path(s), Path(t))), real(s, t, **k))[-1])
    predict_cli.write_outputs(image, tmp_path / "raw_mask.png", out, "img")
    assert [t.name for _s, t in moves] == ["img_image.png", "img_mask.png", "img_overlay.png"]
    assert all(s.parent == t.parent == out and s.name.startswith(".") and s.suffix == ".tmp" for s, t in moves)
    assert sorted(p.name for p in out.iterdir()) == ["img_image.png", "img_mask.png", "img_overlay.png"]

    before = (out / "img_mask.png").read_bytes()
    original_save = Image.Image.save

    def failing_save(self, fp, *args, **kwargs):
        if ".img_mask." in str(fp):
            raise OSError("disk full")
        return original_save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", failing_save)
    with pytest.raises(OSError):
        predict_cli.write_outputs(image, tmp_path / "raw_mask.png", out, "img")
    assert (out / "img_mask.png").read_bytes() == before  # never half-written
    assert not [p for p in out.iterdir() if p.suffix == ".tmp"]  # temp file removed
