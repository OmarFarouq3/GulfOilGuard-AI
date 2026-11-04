"""The click -> image -> Detect / Predict / Respond flow, through the real app with AppTest.

The folium map cannot be clicked in AppTest, so a click's outcome is simulated by writing the
selection keys to session_state (what selection.select_spill stores). Detection is stubbed by
replacing services.inference.run_detection, which AppTest's script run shares with this test.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from dashboard_testkit import APP, make_image_dir, page_text
from PIL import Image
from streamlit.testing.v1 import AppTest

from components.labels import slick_tooltip
from components.nav import STEP_HELP
from services import image_picker, inference, selection
from services.scenario import SIMULATED_OUTLINE

OVERVIEW, DETECT, PREDICT, RESPOND = "views/overview.py", "views/detection.py", "views/drift.py", "views/cleanup.py"
LOCKED = "This step is locked"
SIMULATED_CHIP = "Simulated scenario"
MIXED_CHIP = "Real detection, simulated location"
TRACEBACK = "Traceback (most recent call last): secret/path/boom.py"


def checked(at: AppTest) -> AppTest:
    assert not at.exception, [e.message for e in at.exception]
    return at


def open_page(at: AppTest, page: str) -> AppTest:
    at.switch_page(page)
    return checked(at.run())


def new_app(demo: bool = False, dev: bool = False) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["demo_mode"] = demo
    if dev:
        at.query_params["dev"] = "1"
    return at


def select(at: AppTest, spill_id: str, image) -> None:
    """The state a map click leaves behind (selection.select_spill), followed by the click's rerun.

    The rerun also matters for AppTest: a switch_page before the first run is ignored.
    """
    at.session_state[selection.SPILL_KEY] = spill_id
    at.session_state[selection.IMAGE_PATH_KEY] = str(image) if image else None
    at.session_state[selection.IMAGE_ID_KEY] = image_picker.image_id(image) if image else None
    checked(at.run())


def keys(at: AppTest) -> set[str]:
    return {k for k in (selection.DETECT_RUN_KEY, selection.DETECT_SIMULATED_KEY, selection.PREDICT_DONE_KEY,
                        selection.RESPOND_DONE_KEY) if k in at.session_state}


def button(at: AppTest, key: str):
    matches = [b for b in at.button if b.key == key]
    assert matches, f"button {key!r} not on the page"
    return matches[0]


def has_button(at: AppTest, key: str) -> bool:
    return any(b.key == key for b in at.button)


def html_bodies(at: AppTest, css_class: str) -> list[str]:
    """Bodies of the st.html elements that carry ``css_class`` (one specific card, not the page)."""
    return [h.proto.body for h in at.get("html") if f'class="{css_class}' in h.proto.body
            or f" {css_class}" in h.proto.body.split(">", 1)[0]]


def heading(at: AppTest) -> str:
    """The page heading card (title + status chip) only."""
    bodies = html_bodies(at, "gog-heading")
    assert len(bodies) == 1
    return bodies[0]


def expanders(at: AppTest) -> list[str]:
    return [e.label for e in at.expander]


@pytest.fixture
def images(tmp_path, monkeypatch):
    directory = make_image_dir(tmp_path / "images")
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    monkeypatch.setenv("GOG_CHECKPOINT", str(tmp_path / "no-model.pth"))  # never the real model here
    return sorted(directory.glob("*.png"))


@pytest.fixture
def stub_detection(monkeypatch):
    """Replace the subprocess run with one that writes the result files the loader expects."""
    calls = []

    def fake(image_path, image_id, **kwargs):
        calls.append(image_id)
        for kind, path in inference.output_files(image_id).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            pixels = np.full((12, 16), 255 if kind == "mask" else 90, dtype=np.uint8)
            Image.fromarray(pixels).save(path)
        return inference.DetectionRun("done", "Detection finished.", image_id,
                                      info={"threshold": 0.5, "oil_fraction": 1.0, "checkpoint": "stub.pth"})

    monkeypatch.setattr(inference, "run_detection", fake)
    yield calls
    for path in inference.config.DETECTION_DIR.glob("*"):
        path.unlink()


@pytest.fixture
def failing_detection(monkeypatch):
    monkeypatch.setattr(inference, "run_detection", lambda *a, **k: inference.DetectionRun(
        "failed", "Detection failed (exit code 4).", "x", detail=TRACEBACK))


def run_all_steps(at: AppTest) -> None:
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    open_page(at, PREDICT)
    button(at, "flow_run_predict").click()
    checked(at.run())
    open_page(at, RESPOND)
    button(at, "flow_run_respond").click()
    checked(at.run())


# --- Overview -------------------------------------------------------------------------------


@pytest.mark.parametrize("folder", ["missing", "empty"])
def test_overview_without_images_shows_the_empty_state_card(tmp_path, monkeypatch, folder):
    directory = tmp_path / folder
    if folder == "empty":
        directory.mkdir()
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    at = checked(new_app().run())
    assert "No incident selected yet" in page_text(at)
    assert not html_bodies(at, "gog-images-missing")  # only once a spill is selected
    select(at, "GOG-SIM-01", None)
    cards = html_bodies(at, "gog-images-missing")
    assert len(cards) == 1
    card = cards[0]
    from services import settings
    shown = settings.shown_folder(directory)  # under the home folder: "~\...", never the OS user name
    assert "No radar images found" in card and shown in card and "GOG_IMAGE_DIR" in card
    assert str(Path.home()) not in card
    assert ".png" in card and ".jpg" in card and "assets/images/val" in card
    assert not [p for p in at.get("page_link") if p.proto.label == "Continue to Detect"]
    open_page(at, DETECT)
    assert LOCKED not in page_text(at) and has_button(at, "flow_detect_simulated")


def test_overview_shows_the_assigned_image_with_caption(images):
    at = new_app()
    select(at, "GOG-SIM-02", images[1])
    captions = [str(i.proto) for i in at.get("image")]
    assert any("not geolocated to this spill" in c and images[1].name in c for c in captions)
    assert "North of Ras Al Khaimah (simulated)" in page_text(at)


def test_overview_legend_names_simulated_sites(images):
    at = checked(new_app().run())
    legend = " ".join(html_bodies(at, "gog-legend"))
    assert "Simulated spill site" in legend and "Reported spill" not in legend


def test_overview_numbers_are_labelled_simulated_with_results(images, stub_detection):
    """Fix A1: demo off, a selected spill run through all steps -> the headline numbers carry the label."""
    at = new_app(demo=False)
    select(at, "GOG-SIM-01", images[0])
    run_all_steps(at)
    open_page(at, OVERVIEW)
    status = html_bodies(at, "gog-kpi-status")
    assert len(status) == 1 and SIMULATED_CHIP in status[0]
    hero = html_bodies(at, "gog-hero")
    assert hero and "gog-chip-sim" in hero[0]


def test_overview_numbers_unlabelled_when_there_are_no_results(images):
    at = checked(new_app(demo=False).run())  # no selection, no outputs files: nothing simulated shown
    assert not html_bodies(at, "gog-kpi-status")


# --- The three steps --------------------------------------------------------------------------


@pytest.mark.parametrize("demo", [False, True], ids=["demo-off", "demo-on"])
def test_detect_predict_respond_unlock_in_order(images, stub_detection, demo):
    at = new_app(demo)
    select(at, "GOG-SIM-04", images[0])

    assert LOCKED in page_text(open_page(at, PREDICT))
    assert LOCKED in page_text(open_page(at, RESPOND))

    text = page_text(open_page(at, DETECT))
    assert "Selected radar image" in text and LOCKED not in text
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert stub_detection == [image_picker.image_id(images[0])]
    assert "U-Net prediction" in text and "Simulated slick outline" in text
    assert MIXED_CHIP in heading(at) and SIMULATED_CHIP not in heading(at)  # real mask, simulated location
    assert SIMULATED_OUTLINE in text  # the outline's tooltip, not "Scene: <image_id>"

    assert LOCKED in page_text(open_page(at, RESPOND))  # still locked: Predict not done
    text = page_text(open_page(at, PREDICT))
    assert LOCKED not in text
    button(at, "flow_run_predict").click()
    text = page_text(checked(at.run()))
    assert "Simulated drift scenario, positioned at the selected spill" in text
    assert SIMULATED_CHIP in heading(at) and MIXED_CHIP not in heading(at)  # Predict unchanged

    text = page_text(open_page(at, RESPOND))
    assert LOCKED not in text
    button(at, "flow_run_respond").click()
    text = page_text(checked(at.run()))
    assert "Simulated response plan" in text and at.dataframe
    assert SIMULATED_CHIP in heading(at) and MIXED_CHIP not in heading(at)  # Respond unchanged

    assert page_text(open_page(at, OVERVIEW)).count("gog-progress-done") == 3


def test_simulated_outline_tooltip_never_names_the_scene():
    assert "image_id" not in slick_tooltip(outline_simulated=True)
    assert "outline" in slick_tooltip(outline_simulated=True)
    assert "image_id" in slick_tooltip(outline_simulated=False)


def test_missing_checkpoint_falls_back_to_simulated_and_unlocks_predict(images):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "No trained detection model" in text and "GOG_CHECKPOINT" in text and "demo scene" in text
    assert SIMULATED_CHIP in heading(at) and MIXED_CHIP not in heading(at)  # fully simulated
    notice = " ".join(html_bodies(at, "gog-notice"))
    assert "no-model.pth" in notice  # the file is named ...
    assert str(images[0].parent.parent) not in notice  # ... but its full path is a ?dev=1 detail
    assert LOCKED not in page_text(open_page(at, PREDICT))


def test_failed_detection_hides_technical_details_without_dev(images, failing_detection):
    """Fix 10: the traceback is not anywhere in the page tree (not even in a collapsed expander)."""
    at = new_app(dev=False)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "Detection failed (exit code 4)." in text
    assert "Traceback" not in text and "secret/path" not in text
    assert "Technical details" not in expanders(at)
    assert LOCKED in page_text(open_page(at, PREDICT))
    open_page(at, DETECT)
    button(at, "flow_detect_simulated").click()
    checked(at.run())
    assert LOCKED not in page_text(open_page(at, PREDICT))


def test_failed_detection_shows_technical_details_with_dev(images, failing_detection):
    at = new_app(dev=True)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    details = [e for e in at.expander if e.label == "Technical details"]
    assert len(details) == 1
    assert [c.value for c in details[0].code] == [TRACEBACK]


def test_setup_needed_names_both_variables_and_offers_simulated(images, monkeypatch):
    """Fix 19: no torch in the dashboard's Python -> a setup message, plus the simulated route."""
    monkeypatch.setattr(inference, "run_detection", lambda *a, **k: inference.DetectionRun(
        "setup_needed", inference._setup_message(), "x", detail=TRACEBACK))
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "GOG_DETECTION_PYTHON" in text and "GOG_CHECKPOINT" in text and "Traceback" not in text
    assert has_button(at, "flow_detect_simulated")


# --- Selection changes reset the flow -----------------------------------------------------------


def finish_detection_and_predict(at: AppTest) -> None:
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    open_page(at, PREDICT)
    button(at, "flow_run_predict").click()
    checked(at.run())
    assert selection.PREDICT_DONE_KEY in keys(at)


def test_new_spill_resets_downstream(images, stub_detection):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    select(at, "GOG-SIM-03", images[0])  # another map click
    assert LOCKED in page_text(open_page(at, PREDICT))
    assert not keys(at)


def test_reroll_resets_downstream(images, stub_detection):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    open_page(at, OVERVIEW)
    button(at, "sel_reroll_image").click()
    checked(at.run())
    assert at.session_state[selection.IMAGE_PATH_KEY] != str(images[0])
    assert not keys(at)
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_unknown_spill_is_cleared_everywhere(images, stub_detection):
    """Fix 4: a spill id that is no longer offered clears the selection before anything renders."""
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    at.session_state[selection.SPILL_KEY] = "GONE-01"
    text = page_text(open_page(at, PREDICT))
    assert selection.SPILL_KEY not in at.session_state and not keys(at)
    assert "No incident selected" in text
    assert not any(help_text in text for help_text in STEP_HELP.values())  # timeline shows no old progress


def test_demo_toggle_resets_the_flow(images, stub_detection):
    """Fix 5: the options-panel toggle (real widget + callback) drops the steps done on other data."""
    at = new_app(demo=False)
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    at.toggle(key="_demo_toggle").set_value(True)
    checked(at.run())
    assert at.session_state["demo_mode"] is True
    assert at.session_state[selection.SPILL_KEY] == "GOG-SIM-01"  # still offered in demo mode
    assert not keys(at)
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_detection_files_removed_on_disk_reopen_the_step(images, stub_detection):
    """Fix 6: a "done" model detection is re-verified against disk on every render."""
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    image_id = image_picker.image_id(images[0])
    inference.output_files(image_id)["mask"].unlink()
    open_page(at, DETECT)
    assert has_button(at, "flow_run_detection")
    assert selection.DETECT_RUN_KEY not in at.session_state
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_clear_selection_returns_pages_to_the_latest_results(images):
    at = new_app(demo=True)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, OVERVIEW)
    button(at, "sel_clear").click()
    checked(at.run())
    assert selection.SPILL_KEY not in at.session_state
    text = page_text(open_page(at, PREDICT))
    assert "No incident selected" in text and SIMULATED_CHIP in text  # demo results are shown again


@pytest.mark.parametrize("demo", [False, True], ids=["demo-off", "demo-on"])
def test_every_page_renders_without_selection(images, demo):
    at = checked(new_app(demo).run())
    for page in (DETECT, PREDICT, RESPOND, OVERVIEW):
        text = page_text(open_page(at, page))
        if page != OVERVIEW:
            assert "No incident selected" in text


# --- Status labels, metrics caption, image source (dashboard review fixes) ------------------------



def write_metrics(content: dict) -> None:
    import json
    inference.config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    (inference.config.DETECTION_DIR / "metrics.json").write_text(json.dumps(content), encoding="utf-8")


def run_stubbed_detection(at: AppTest, image) -> str:
    select(at, "GOG-SIM-01", image)
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    return page_text(checked(at.run()))


def test_synthetic_scores_no_longer_change_the_detect_label(images, stub_detection):
    """The overall scores are not shown any more, so an illustrative metrics.json no longer labels a real mask."""
    write_metrics({"synthetic": True, "dice": 0.7, "iou": 0.6, "precision": 0.7, "recall": 0.7})
    at = new_app()
    text = run_stubbed_detection(at, images[0])
    assert MIXED_CHIP in heading(at) and "Overall model accuracy" not in text


def test_timeline_and_overview_use_the_mixed_wording(images, stub_detection):
    at = new_app()
    text = run_stubbed_detection(at, images[0])
    assert "gog-step-detect-mixed" in text  # timeline dot for the mixed state
    open_page(at, OVERVIEW)
    assert any(MIXED_CHIP in body for body in html_bodies(at, "gog-stage-num"))  # Detect card in the flow
    assert SIMULATED_CHIP in html_bodies(at, "gog-kpi-status")[0]  # headline area comes from the simulated outline


def test_evaluate_py_metrics_json_is_not_shown_on_detect(images, stub_detection):
    """metrics.json exactly as detection/evaluate.py writes it: none of it reaches the Detect page."""
    write_metrics({
        "checkpoint": "C:/Users/someone/models/oil_unet/best.pth", "epoch": 12, "pairs": 1615, "threshold": 0.5,
        "metrics": {"dice": 0.8689, "iou": 0.7682, "precision": 0.8459, "recall": 0.8932},
        "limitations": "Provider validation split used for model selection; not an independent test set."})
    text = run_stubbed_detection(new_app(), images[0])
    for gone in ("Overall model accuracy", "Evaluation details", "0.87", "0.85", "0.89", "1615", "1,615",
                 "best.pth", "Provider validation split", "C:/Users/someone"):
        assert gone not in text, gone


def test_image_source_caption_from_file_name(tmp_path, monkeypatch):
    from dashboard_testkit import make_image
    directory = tmp_path / "images"
    expected = {"sentinel_12.png": "Sentinel-1 SAR sample from the local dataset",
                "palsar_0.png": "ALOS PALSAR SAR sample from the local dataset", "scene_9.png": None}
    paths = {name: make_image(directory / name) for name in expected}
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    monkeypatch.setenv("GOG_CHECKPOINT", str(tmp_path / "no-model.pth"))
    for name, source in expected.items():
        at = new_app()
        select(at, "GOG-SIM-01", paths[name])
        caption = next(str(i.proto) for i in at.get("image") if "not geolocated to this spill" in str(i.proto))
        incident_line = " ".join(html_bodies(open_page(at, DETECT), "gog-flow-incident"))
        if source:
            assert source in caption and source in incident_line
        else:
            for text in (caption, incident_line):
                assert "SAR sample from" not in text and "Sentinel" not in text and "PALSAR" not in text


def test_checkpoint_message_full_paths_only_with_dev(images):
    """Item 3: viewers see which files were checked; full paths only with ?dev=1."""
    import os
    missing = os.environ["GOG_CHECKPOINT"]
    for dev in (False, True):
        at = new_app(dev=dev)
        select(at, "GOG-SIM-01", images[0])
        open_page(at, DETECT)
        button(at, "flow_run_detection").click()
        checked(at.run())
        notice = " ".join(html_bodies(at, "gog-notice"))
        assert "Checked, in order:" in notice and "no-model.pth" in notice and missing not in notice
        details = [c.value for e in at.expander if e.label == "Technical details" for c in e.code]
        assert bool(details) == dev and (missing in details[0] if dev else True)


# --- Team A's report: per-image scores, checkpoint check, galleries ------------------------------

SCORE_SECTION = "Score for this image"
SCORE_CAPTION = ("How this image scored against its reference mask (validation report). The validation split "
                 "was also used to choose the checkpoint, so this is not an independent test.")
SCORE_PROVENANCE = "Score against the reference mask (validation report)"
TRAINING_DATA = "No reference score: this image was part of the model&#x27;s training data."
NO_SCORE = "No reference score for this image."
NO_REFERENCE_OIL = "No oil in the reference mask."
GALLERY_LABEL = "Best, median and worst validation images"
MISMATCH = "These scores were computed on a different checkpoint than the one running."
UNREPORTED = "The report doesn&#x27;t say which checkpoint was scored."
REPORT_METRICS = {"model": "U-Net", "split": "val", "n_images": 3, "threshold": 0.5,
                  "dice": 0.8689, "iou": 0.7682, "precision": 0.8459, "recall": 0.8932}
PER_IMAGE_CSV = ("file,ref_oil_pixels,dice,iou,precision,recall\n"
                 "palsar_0.png,13039,0.7725,0.6294,0.7422,0.8054\n"
                 "palsar_5.png,0,0.0,0.0,0.0,0.0\n"
                 "sentinel_1.png,300,0.4,0.3,0.5,0.6\n")


@pytest.fixture
def report():
    """outputs/report/ for one test; the loader caches are cleared so no other test's files leak in."""
    from services import report_loader
    for cached in (report_loader._per_image_cached, report_loader._json_cached, report_loader._sha256_cached):
        cached.cache_clear()
    directory = inference.config.REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    yield directory
    for path in [*directory.glob("*"), *inference.config.DETECTION_DIR.glob("*")]:
        path.unlink()


@pytest.fixture
def split_images(tmp_path, monkeypatch):
    """The dataset layout: train/ and val/ share file names; one more image in a folder with no split."""
    from dashboard_testkit import make_image
    root = tmp_path / "images"
    paths = {name: make_image(root / name, seed=i) for i, name in enumerate(
        ["val/palsar_0.png", "train/palsar_0.png", "val/palsar_5.png", "val/palsar_9.png", "misc/palsar_0.png"])}
    monkeypatch.setenv("GOG_IMAGE_DIR", str(root))
    monkeypatch.setenv("GOG_CHECKPOINT", str(tmp_path / "no-model.pth"))
    return paths


def score_block(at: AppTest) -> str:
    """The per-image section only: from its heading up to the Real / Simulated box."""
    bodies = [h.proto.body for h in at.get("html")]
    start = next(i for i, b in enumerate(bodies) if SCORE_SECTION in b)
    end = next(i for i, b in enumerate(bodies) if 'class="gog-prov"' in b)
    return "\n".join(bodies[start:end])


def provenance(at: AppTest) -> str:
    return " ".join(html_bodies(at, "gog-prov"))


def run_with_report(image, csv: str = PER_IMAGE_CSV, metrics: dict | None = None) -> AppTest:
    write_metrics(REPORT_METRICS if metrics is None else metrics)
    (inference.config.REPORT_DIR / "per_image_metrics.csv").write_text(csv, encoding="utf-8")
    at = new_app()
    run_stubbed_detection(at, image)
    return at


def test_val_image_in_the_report_shows_its_scores(split_images, stub_detection, report):
    at = run_with_report(split_images["val/palsar_0.png"])
    block = score_block(at)
    assert SCORE_CAPTION in block
    for value in ("0.77", "0.63", "0.74", "0.81", "19.9", "Reference oil", "Dice", "IoU", "Precision", "Recall"):
        assert value in block
    assert SCORE_PROVENANCE in provenance(at)


def test_empty_reference_mask_shows_no_scores(split_images, stub_detection, report):
    at = run_with_report(split_images["val/palsar_5.png"])
    block = score_block(at)
    assert NO_REFERENCE_OIL in block and "Reference oil" not in block and "0.00" not in block
    assert SCORE_PROVENANCE not in provenance(at)


def test_train_image_never_gets_the_val_row(split_images, stub_detection, report):
    """Regression: palsar_0.png is in train/ and val/ with different content; the report covers val only."""
    at = run_with_report(split_images["train/palsar_0.png"])
    block = score_block(at)
    assert TRAINING_DATA in block and "0.77" not in block and SCORE_PROVENANCE not in provenance(at)


def test_regression_same_name_in_train_and_val_with_different_rows(split_images, stub_detection, report):
    csv = ("file,split,ref_oil_pixels,dice,iou,precision,recall\n"
           "palsar_0.png,train,500,0.1111,0.1,0.2,0.3\n"
           "palsar_0.png,val,13039,0.7725,0.6294,0.7422,0.8054\n")
    val = score_block(run_with_report(split_images["val/palsar_0.png"], csv))
    assert "0.77" in val and "0.11" not in val
    train = score_block(run_with_report(split_images["train/palsar_0.png"], csv))
    assert TRAINING_DATA in train and "0.11" not in train and "0.77" not in train


@pytest.mark.parametrize("image", ["val/palsar_9.png", "misc/palsar_0.png"])
def test_not_in_the_report_or_unknown_split_is_never_guessed(split_images, stub_detection, report, image):
    """palsar_9 is not in the CSV; misc/palsar_0.png has a name in the CSV but no split folder."""
    block = score_block(run_with_report(split_images[image]))
    assert NO_SCORE in block and "0.77" not in block


def test_rows_without_any_split_match_nothing(split_images, stub_detection, report):
    metrics = {k: v for k, v in REPORT_METRICS.items() if k != "split"}
    block = score_block(run_with_report(split_images["val/palsar_0.png"], metrics=metrics))
    assert NO_SCORE in block and "0.77" not in block


def test_no_report_at_all(split_images, stub_detection, report):
    at = new_app()
    run_stubbed_detection(at, split_images["val/palsar_0.png"])
    assert NO_SCORE in score_block(at)


def test_simulated_fallback_shows_no_image_score(split_images, report):
    write_metrics(REPORT_METRICS)
    (report / "per_image_metrics.csv").write_text(PER_IMAGE_CSV, encoding="utf-8")
    at = new_app()
    select(at, "GOG-SIM-01", split_images["val/palsar_0.png"])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()  # no checkpoint: the simulated detection
    text = page_text(checked(at.run()))
    assert SIMULATED_CHIP in heading(at)
    assert SCORE_SECTION not in text and SCORE_PROVENANCE not in text and GALLERY_LABEL not in text


# Checkpoint verification


@pytest.fixture
def running_checkpoint(tmp_path, monkeypatch):
    import hashlib
    path = tmp_path / "unet_best.pth"
    path.write_bytes(b"model weights")
    monkeypatch.setenv("GOG_CHECKPOINT", str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_checkpoint_hash_match(split_images, stub_detection, report, running_checkpoint):
    at = run_with_report(split_images["val/palsar_0.png"],
                         metrics={**REPORT_METRICS, "checkpoint_sha256": running_checkpoint})
    text = page_text(at)
    assert MISMATCH not in text and running_checkpoint not in text  # the hash is no detail for viewers
    assert "Scores were computed on this checkpoint." not in text  # the note of the removed overall section


def test_checkpoint_hash_mismatch_is_a_visible_warning(split_images, stub_detection, report, running_checkpoint):
    """The per-image scores come from the same report: a report made with another checkpoint is still flagged."""
    at = run_with_report(split_images["val/palsar_0.png"], metrics={**REPORT_METRICS, "checkpoint_sha256": "a" * 64})
    assert any(MISMATCH in body for body in html_bodies(at, "gog-notice"))
    assert any(MISMATCH in m.value for m in at.markdown), "also listed under Diagnostics"


def test_checkpoint_hash_missing_shows_nothing(split_images, stub_detection, report, running_checkpoint):
    at = run_with_report(split_images["val/palsar_0.png"])
    assert UNREPORTED not in page_text(at)  # the quiet note belonged to the removed overall section
    assert not any("checkpoint" in b for b in html_bodies(at, "gog-notice"))


# Galleries


def write_galleries(directory, names=("best", "median", "worst")) -> None:
    from dashboard_testkit import make_image
    for i, name in enumerate(names):
        make_image(directory / f"gallery_{name}.png", seed=i)


def gallery_expander(at: AppTest):
    return next((e for e in at.expander if e.label == GALLERY_LABEL), None)


def gallery_captions(at: AppTest) -> list[str]:
    return [img.caption for element in gallery_expander(at).get("image") for img in element.proto.imgs]


def test_galleries_shown_when_the_files_exist(split_images, stub_detection, report):
    write_galleries(report)
    at = run_with_report(split_images["val/palsar_0.png"])
    assert gallery_captions(at) == ["Best", "Median", "Worst"]
    note = " ".join(c.value for c in gallery_expander(at).caption)
    assert "green correct, red false alarm, blue missed" in note and "not an independent test" in note


def test_galleries_hidden_without_files(split_images, stub_detection, report):
    assert gallery_expander(run_with_report(split_images["val/palsar_0.png"])) is None


def test_unreadable_gallery_is_skipped_and_listed_in_diagnostics(split_images, stub_detection, report):
    write_galleries(report, ("best", "worst"))
    (report / "gallery_median.png").write_bytes(b"not a png")
    at = run_with_report(split_images["val/palsar_0.png"])
    assert gallery_captions(at) == ["Best", "Worst"]
    assert any("gallery_median.png" in m.value for m in at.markdown)


def test_galleries_hidden_next_to_the_demo_scene(images, report):
    write_galleries(report)
    write_metrics(REPORT_METRICS)
    at = checked(new_app(demo=True).run())
    assert gallery_expander(open_page(at, DETECT)) is None


def test_galleries_shown_without_a_selection(images, report):
    from dashboard_testkit import make_image
    write_galleries(report)
    inference.config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    make_image(inference.config.DETECTION_DIR / "scene_image.png")  # a scene to show: the page is not empty
    at = checked(new_app().run())
    assert gallery_captions(open_page(at, DETECT)) == ["Best", "Median", "Worst"]


def test_diagnostics_list_the_report_files(images, report):
    at = open_page(checked(new_app().run()), DETECT)
    files = [name for frame in at.dataframe for name in frame.value["File"]]
    for name in ("report/summary.json", "report/per_image_metrics.csv", "report/gallery_best.png",
                 "report/gallery_median.png", "report/gallery_worst.png", "detection/summary.json"):
        assert name in files


# --- Detection test pass fixes: details allowlist, caption, undefined precision, Diagnostics paths --------


def test_unknown_metrics_keys_and_paths_never_reach_the_page(split_images, stub_detection, report):
    at = run_with_report(split_images["val/palsar_0.png"], metrics={
        **REPORT_METRICS, "checkpoint": "C:/Users/someone/models/best.pth", "data_dir": "C:/Users/someone/sar_data",
        "notes": "internal note", "limitations": "Masks in /home/someone/masks/val were used."})
    page = page_text(at)
    assert "someone" not in page and "sar_data" not in page and "internal note" not in page
    assert "Masks in" not in page and "Evaluation details" not in page  # metrics.json is no longer shown at all
    assert not any("couldn" in b for b in html_bodies(at, "gog-notice"))


def test_nothing_predicted_shows_precision_as_undefined(split_images, stub_detection, report):
    csv = PER_IMAGE_CSV + "palsar_9.png,583,0.0,0.0,0.0,0.0\n"
    block = score_block(run_with_report(split_images["val/palsar_9.png"], csv))
    precision = block[block.index(">Precision<"):]
    precision = precision[:precision.index("gog-stat-hint")] + precision[precision.index("gog-stat-hint"):][:120]
    assert "gog-stat-empty" in precision and "No oil was predicted, so precision is undefined" in precision
    assert block.count("0.00") == 3  # Dice, IoU and Recall stay as reported


def test_reported_zero_precision_with_some_prediction_stays_a_number(split_images, stub_detection, report):
    csv = PER_IMAGE_CSV + "palsar_9.png,583,0.0,0.0,0.0,0.4\n"
    block = score_block(run_with_report(split_images["val/palsar_9.png"], csv))
    assert "precision is undefined" not in block and "0.40" in block and block.count("0.00") == 3


def diagnostics_code(at: AppTest) -> str:
    return "\n".join(c.value for c in at.code)


@pytest.mark.parametrize("dev", [False, True])
def test_diagnostics_paths_are_relative_unless_dev(split_images, stub_detection, report, dev, monkeypatch):
    from pathlib import Path

    from dashboard_testkit import TEST_OUTPUTS

    from services import settings
    write_metrics(REPORT_METRICS)
    checkpoint = settings.ROOT / "checkpoints" / "unet_best.pth"  # inside the (test) repo: shown relative
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"weights")
    monkeypatch.setenv("GOG_CHECKPOINT", str(checkpoint))
    at = new_app(dev=dev)
    run_stubbed_detection(at, split_images["val/palsar_0.png"])
    code, page = diagnostics_code(at), page_text(at)
    user = Path.home().name
    if dev:
        assert str(TEST_OUTPUTS) in code and str(checkpoint) in code
    else:
        assert "checkpoint: checkpoints/unet_best.pth" in code
        assert TEST_OUTPUTS.name in code and split_images["val/palsar_0.png"].parents[1].name in code
        for secret in (str(TEST_OUTPUTS), str(split_images["val/palsar_0.png"].parents[1]), str(settings.ROOT),
                       str(Path.home())):
            assert secret not in page and secret.replace("\\", "\\\\") not in page
        assert f"\\{user}\\" not in page and f"/{user}/" not in page


# --- Overall vs per-image scores ------------------------------------------------------------------

OVERALL = "Overall model accuracy"


def score_tiles(at: AppTest) -> dict[str, str]:
    """{tile label: the tile's HTML} of the per-image block."""
    import re
    cells = score_block(at).split('<div class="gog-stat">')[1:]
    return {re.search(r'gog-stat-label">(.*?)</div>', c, re.S).group(1).strip(): c for c in cells}


@pytest.mark.parametrize("image, csv", [
    ("train/palsar_0.png", PER_IMAGE_CSV),          # training data
    ("misc/palsar_0.png", PER_IMAGE_CSV),           # split unknown
    ("val/palsar_9.png", PER_IMAGE_CSV),            # not in the report
    ("val/palsar_5.png", PER_IMAGE_CSV),            # no oil in the reference mask
])
def test_no_overall_scores_without_per_image_scores(split_images, stub_detection, report, image, csv):
    at = run_with_report(split_images[image], csv)
    assert OVERALL not in page_text(at) and "Overall 0." not in page_text(at)


def test_score_tiles_show_this_images_values_only(split_images, stub_detection, report):
    tiles = score_tiles(run_with_report(split_images["val/palsar_0.png"]))
    for label, value in {"Dice": "0.77", "IoU": "0.63", "Precision": "0.74", "Recall": "0.81"}.items():
        assert f">{value}<" in tiles[label] and "gog-stat-secondary" not in tiles[label]  # no "Overall 0.87" line
    assert "gog-stat-secondary" not in tiles["Reference oil"]


def test_no_overall_lines_without_overall_scores(split_images, stub_detection, report):
    (report / "per_image_metrics.csv").write_text(PER_IMAGE_CSV, encoding="utf-8")
    write_metrics({"split": "val", "model": "U-Net"})  # the report's split, but no scores
    at = new_app()
    run_stubbed_detection(at, split_images["val/palsar_0.png"])
    tiles = score_tiles(at)
    assert ">0.77<" in tiles["Dice"] and "gog-stat-secondary" not in score_block(at)
    assert OVERALL not in page_text(at)


def test_undefined_precision_keeps_its_dash(split_images, stub_detection, report):
    csv = PER_IMAGE_CSV + "palsar_9.png,583,0.0,0.0,0.0,0.0\n"
    tiles = score_tiles(run_with_report(split_images["val/palsar_9.png"], csv))
    assert "gog-stat-empty" in tiles["Precision"] and "precision is undefined" in tiles["Precision"]
    assert "Overall" not in tiles["Precision"] and ">0.00<" in tiles["Dice"]
