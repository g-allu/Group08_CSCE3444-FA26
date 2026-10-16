"""Regression checks for leakage, rejection, and the actual saved experiment."""

import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import joblib
import numpy as np
from PIL import Image
import pytest
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asl_model as asl


def test_features_ignore_translation_and_scale_but_preserve_orientation():
    points = np.random.default_rng(17).normal(size=(21, 3))
    expected = asl.normalize_landmarks(points)
    np.testing.assert_allclose(asl.normalize_landmarks(points * 3 + [6, 7, 8]), expected, atol=1e-6)
    rotated = points.copy()
    rotated[:, [0, 1]] = points[:, [1, 0]]
    assert not np.allclose(asl.normalize_landmarks(rotated), expected)


@pytest.mark.parametrize("points", [np.zeros((21, 3)), np.full((21, 3), np.nan), np.ones((20, 3))])
def test_invalid_landmarks_rejected(points):
    with pytest.raises(ValueError):
        asl.normalize_landmarks(points)


def test_duplicate_groups_transitively_connect_near_images():
    groups = asl.duplicate_groups([0, 1, 3, 255], ["a", "b", "c", "d"], radius=1)
    assert groups[0] == groups[1] == groups[2]
    assert groups[3] != groups[0]


def test_exact_duplicate_content_stays_together_even_when_hash_differs():
    groups = asl.duplicate_groups([0, 255], ["same-content", "same-content"], radius=0)
    assert groups[0] == groups[1]


def test_grouped_splits_are_disjoint_complete_and_reproducible():
    labels = np.repeat(["A", "B", "C", "L", "Y", "D"], 100)
    groups = np.repeat(np.arange(300), 2)
    first = asl.make_splits(labels, groups)
    second = asl.make_splits(labels, groups)
    assert sorted(np.concatenate(list(first.values())).tolist()) == list(range(600))
    for name in first:
        np.testing.assert_array_equal(first[name], second[name])
        for other in first:
            if name != other:
                assert not set(groups[first[name]]) & set(groups[first[other]])


def test_failing_hand_detection_counts_against_supported_letter_recall():
    truth = np.asarray([*asl.LETTERS, "OTHER"])
    predicted = np.asarray(["REJECT", "B", "C", "L", "Y", "REJECT"])
    report = asl.metrics_for(truth, predicted)
    assert report["per_letter"]["A"]["recall"] == 0
    assert report["supported_recall"] == 0.8
    assert report["unsupported_rejection_rate"] == 1
    assert not report["acceptance_passed"]


def test_rejecting_everything_cannot_pass_acceptance():
    truth = np.asarray([*asl.LETTERS, "OTHER"])
    report = asl.metrics_for(truth, np.repeat("REJECT", len(truth)))
    assert report["accepted_letter_precision"] == 0
    assert not report["acceptance_passed"]


def test_missing_features_and_other_class_are_rejected():
    features = np.asarray([[0] * 63, [1] * 63], dtype=np.float32)
    classifier = RandomForestClassifier(n_estimators=5, random_state=1).fit(features, ["A", "OTHER"])
    missing = np.full((1, 63), np.nan, dtype=np.float32)
    predicted, _ = asl.model_predictions(classifier, np.concatenate([features, missing]), threshold=0)
    assert predicted.tolist() == ["A", "REJECT", "REJECT"]


def test_stabilization_resets_after_uncertainty_or_letter_change():
    stable = asl.StablePrediction()
    result = {"status": "recognized", "letter": "A"}
    assert stable.update(result) is None
    assert stable.update(result) == "A"
    assert stable.update({"status": "uncertain", "letter": None}) is None
    assert stable.update(result) is None
    assert stable.update({"status": "recognized", "letter": "B"}) is None


@pytest.mark.parametrize("operating_system", ["darwin", "linux", "win32"])
def test_camera_uses_native_mac_backend_and_default_elsewhere(monkeypatch, operating_system):
    import cv2

    capture = Mock()
    capture.isOpened.return_value = True
    constructor = Mock(return_value=capture)
    monkeypatch.setattr(asl.sys, "platform", operating_system)
    monkeypatch.setattr(cv2, "VideoCapture", constructor)
    assert asl.open_camera(1) is capture
    constructor.assert_called_once_with(1, cv2.CAP_AVFOUNDATION if operating_system == "darwin" else cv2.CAP_ANY)
    capture.release.assert_not_called()


def test_camera_open_failure_releases_device_and_explains_mac_permissions(monkeypatch):
    import cv2

    capture = Mock()
    capture.isOpened.return_value = False
    monkeypatch.setattr(asl.sys, "platform", "darwin")
    monkeypatch.setattr(cv2, "VideoCapture", Mock(return_value=capture))
    with pytest.raises(RuntimeError, match="System Settings > Privacy & Security > Camera"):
        asl.open_camera(0)
    capture.release.assert_called_once()


def test_negative_camera_index_does_not_open_a_device(monkeypatch):
    import cv2

    constructor = Mock()
    monkeypatch.setattr(cv2, "VideoCapture", constructor)
    with pytest.raises(ValueError, match="zero or greater"):
        asl.open_camera(-1)
    constructor.assert_not_called()


@pytest.mark.parametrize("arguments", [[], ["webcam"], ["--camera", "1"], ["--camera=1"], ["webcam", "--camera", "1"]])
def test_direct_run_and_explicit_webcam_commands(monkeypatch, arguments):
    start = Mock()
    monkeypatch.setattr(asl, "webcam", start)
    assert asl.cli(arguments) == 0
    start.assert_called_once_with(1 if any("1" in value for value in arguments) else 0)


def test_default_run_reads_real_process_arguments(monkeypatch):
    start = Mock()
    monkeypatch.setattr(asl, "webcam", start)
    monkeypatch.setattr(sys, "argv", ["asl_model.py"])
    assert asl.cli() == 0
    start.assert_called_once_with(0)


def test_help_exits_successfully_without_opening_camera(monkeypatch, capsys):
    start = Mock()
    monkeypatch.setattr(asl, "webcam", start)
    with pytest.raises(SystemExit) as error:
        asl.main(["--help"])
    assert error.value.code == 0
    assert "Run without arguments to start the webcam" in capsys.readouterr().out
    start.assert_not_called()


@pytest.mark.parametrize("arguments", [["typo"], ["--unknown"], ["webcam", "--camera", "-1"], ["webcam", "--camera", "abc"], ["benchmark", "--count", "0"], ["predict"]])
def test_invalid_arguments_do_not_start_camera_or_benchmark(monkeypatch, arguments):
    start = Mock()
    benchmark = Mock()
    monkeypatch.setattr(asl, "webcam", start)
    monkeypatch.setattr(asl, "benchmark", benchmark)
    with pytest.raises(SystemExit) as error:
        asl.main(arguments)
    assert error.value.code == 2
    start.assert_not_called()
    benchmark.assert_not_called()


def test_camera_failure_has_concise_error_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(asl, "webcam", Mock(side_effect=RuntimeError("Camera access denied")))
    assert asl.cli([]) == 1
    error = capsys.readouterr().err
    assert "Error: Camera access denied" in error
    assert "Traceback" not in error


def test_ctrl_c_exits_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(asl, "webcam", Mock(side_effect=KeyboardInterrupt))
    assert asl.cli([]) == 130
    assert capsys.readouterr().err.strip() == "Stopped."


def test_module_entrypoint_supports_help_without_camera():
    result = subprocess.run([sys.executable, "-m", "ml.asl_model", "--help"], cwd=asl.ROOT.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Run without arguments to start the webcam" in result.stdout


@pytest.mark.skipif(not asl.MODEL.exists(), reason="Train the local model first")
def test_saved_model_roundtrip_and_real_split_integrity(tmp_path):
    bundle = asl.load_model()
    data = asl.load_features()
    manifest = json.loads(asl.SPLITS.read_text())
    group_sets = []
    for rows in manifest["splits"].values():
        group_sets.append(set(data["groups"][np.isin(data["rows"], rows)]))
    assert all(not group_sets[i] & group_sets[j] for i in range(3) for j in range(i + 1, 3))
    valid = np.isfinite(data["features"]).all(axis=1)
    held_out = np.isin(data["rows"], manifest["splits"]["test"]) & valid
    features = data["features"][held_out][:40]
    assert len(features) == 40
    path = tmp_path / "roundtrip.joblib"
    joblib.dump(bundle, path)
    restored = joblib.load(path)
    before = asl.model_predictions(bundle["model"], features, bundle["metadata"]["threshold"])
    after = asl.model_predictions(restored["model"], features, restored["metadata"]["threshold"])
    np.testing.assert_array_equal(before[0], after[0])
    np.testing.assert_array_equal(before[1], after[1])


@pytest.mark.skipif(not asl.MODEL.exists(), reason="Train the local model first")
def test_real_pipeline_rejects_empty_image():
    with asl.HandExtractor() as extractor:
        result = asl.predict_image(Image.new("RGB", (640, 480)), extractor, asl.load_model())
    assert result["status"] == "no_hand"
    assert result["letter"] is None


@pytest.mark.skipif(not asl.MODEL.exists(), reason="Train the local model first")
def test_real_held_out_images_match_cached_feature_predictions():
    import pyarrow.parquet as pq

    bundle = asl.load_model()
    data = asl.load_features()
    manifest = json.loads(asl.SPLITS.read_text())
    held_out = np.isin(data["rows"], manifest["splits"]["test"])
    table = pq.read_table(asl.PARQUET)
    with asl.HandExtractor() as extractor:
        for letter in asl.LETTERS:
            index = np.flatnonzero(held_out & (data["labels"] == letter))[0]
            content = table["image"][int(data["rows"][index])].as_py()["bytes"]
            with Image.open(io.BytesIO(content)) as image:
                actual = asl.predict_image(image, extractor, bundle)
            expected, confidence = asl.model_predictions(bundle["model"], data["features"][[index]], bundle["metadata"]["threshold"])
            assert actual["letter"] == (None if expected[0] == "REJECT" else expected[0])
            if actual["confidence"] is not None:
                assert actual["confidence"] == pytest.approx(confidence[0], abs=1e-5)


@pytest.mark.skipif(not asl.MODEL.exists(), reason="Train the local model first")
def test_corrupted_image_cli_fails_clearly(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    result = subprocess.run([sys.executable, str(asl.ROOT / "asl_model.py"), "predict", str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "Error:" in result.stderr
    assert "Traceback" not in result.stderr
