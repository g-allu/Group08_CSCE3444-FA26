"""Standalone static-alphabet ASL experiment. No web application dependencies."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from contextlib import AbstractContextManager
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "artifacts/matplotlib"))

import joblib
import numpy as np
from PIL import Image, ImageOps
from scipy.fft import dctn
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

if __package__:
    from .download_data import LANDMARKER, MANIFEST, PARQUET, download, sha256
else:
    from download_data import LANDMARKER, MANIFEST, PARQUET, download, sha256

# J and Z are signed with motion, so a single-frame classifier cannot recognize them.
MOTION_LETTERS = ("J", "Z")
LETTERS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1) if chr(code) not in MOTION_LETTERS)
CLASSES = LETTERS
# v2 retries hand detection on a padded copy when the first pass finds no hand.
FEATURE_VERSION = "world-wrist-relative-middle-mcp-scale-padded-retry-v2"
MODEL_FEATURE_VERSION = "landmarks-plus-tip-distances-joint-angles-orientation-v2"
MIN_THRESHOLD = 0.5
TARGET_PRECISION = 0.98
FEATURES = ROOT / "data/processed/features.npz"
SPLITS = ROOT / "data/processed/splits.json"
MODEL = ROOT / "artifacts/asl_alphabet.joblib"
REPORTS = ROOT / "reports"
SEED = 42
NEAR_DUPLICATE_DISTANCE = 4
RETRY_PADDING = 0.5


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def normalize_landmarks(points: np.ndarray) -> np.ndarray:
    """Use the same orientation-preserving features in training and inference."""
    points = np.asarray(points, dtype=np.float64)
    if points.shape != (21, 3) or not np.isfinite(points).all():
        raise ValueError("Expected 21 finite three-dimensional landmarks")
    relative = points - points[0]
    scale = np.linalg.norm(relative[9])
    if scale < 1e-8:
        raise ValueError("Degenerate hand landmarks")
    return (relative / scale).astype(np.float32).reshape(63)


FINGERTIPS = (4, 8, 12, 16, 20)
FINGER_CHAINS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
THUMB_TARGETS = (5, 6, 9, 10, 13, 14, 17)


def model_features(features: np.ndarray) -> np.ndarray:
    """Append hand-shape geometry to normalized landmarks.

    Fingertip spacing, finger bend angles, and thumb placement separate similar
    letters (for example M, N, S, T, A, and E) far better than raw coordinates.
    Finger directions and palm orientation separate letters that share a shape
    but point differently (K and P, G and Q, U and H). Rows with missing
    landmarks stay NaN.
    """
    features = np.asarray(features, dtype=np.float64)
    points = features.reshape(-1, 21, 3)
    columns = []
    for first, tip in enumerate(FINGERTIPS):
        columns.extend(np.linalg.norm(points[:, tip] - points[:, other], axis=1) for other in FINGERTIPS[first + 1:])
    columns.extend(np.linalg.norm(points[:, tip], axis=1) for tip in FINGERTIPS)
    for chain in FINGER_CHAINS:
        joints = [points[:, 0], *(points[:, index] for index in chain)]
        for middle in range(1, len(joints) - 1):
            before, after = joints[middle - 1] - joints[middle], joints[middle + 1] - joints[middle]
            lengths = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
            columns.append((before * after).sum(axis=1) / np.maximum(lengths, 1e-8))
    columns.extend(np.linalg.norm(points[:, 4] - points[:, index], axis=1) for index in THUMB_TARGETS)

    def unit(vectors):
        return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-8)

    directions = [unit(points[:, tip] - points[:, base]) for base, tip in ((2, 4), (5, 8), (9, 12), (13, 16), (17, 20))]
    palm_normal = unit(np.cross(points[:, 5] - points[:, 0], points[:, 17] - points[:, 0]))
    # Sign shows whether the index and middle fingers cross (R).
    crossing = (palm_normal * np.cross(points[:, 8] - points[:, 5], points[:, 12] - points[:, 9])).sum(axis=1)
    columns.append(crossing)
    columns.extend((points[:, tip] * palm_normal).sum(axis=1) for tip in FINGERTIPS)
    columns.extend(
        np.linalg.norm(points[:, 4] - (points[:, first] + points[:, second]) / 2, axis=1)
        for first, second in ((6, 10), (10, 14), (14, 18))
    )
    return np.hstack([features, np.stack(columns, axis=1), *directions, palm_normal]).astype(np.float32)


def mirror_landmarks(features: np.ndarray) -> np.ndarray:
    """Reflect normalized landmarks across x so one hand's samples teach the other hand."""
    points = np.array(features, dtype=np.float32).reshape(-1, 21, 3)
    points[:, :, 0] *= -1
    return points.reshape(-1, 63)


def perceptual_hash(image: Image.Image) -> int:
    pixels = np.asarray(image.convert("L").resize((32, 32)), dtype=np.float64)
    low = dctn(pixels, norm="ortho")[:8, :8].reshape(-1)[1:]
    result = 0
    for bit in low > np.median(low):
        result = (result << 1) | int(bit)
    return result


def duplicate_groups(hashes: list[int], digests: list[str], radius: int = NEAR_DUPLICATE_DISTANCE) -> np.ndarray:
    """Group exact/near duplicates using union-find and a Hamming-distance BK tree."""
    parent = list(range(len(hashes)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        first, second = find(first), find(second)
        parent[max(first, second)] = min(first, second)

    tree = None
    exact = {}
    for index, (value, digest) in enumerate(zip(hashes, digests, strict=True)):
        if digest in exact:
            union(index, exact[digest])
        exact[digest] = index
        if tree is None:
            tree = [value, index, {}]
            continue
        pending = [tree]
        while pending:
            node = pending.pop()
            distance = (value ^ node[0]).bit_count()
            if distance <= radius:
                union(index, node[1])
            pending.extend(child for edge, child in node[2].items() if distance - radius <= edge <= distance + radius)
        node = tree
        while True:
            distance = (value ^ node[0]).bit_count()
            if distance == 0:
                break
            if distance not in node[2]:
                node[2][distance] = [value, index, {}]
                break
            node = node[2][distance]
    return np.asarray([find(index) for index in range(len(parent))])


class HandExtractor(AbstractContextManager):
    def __init__(self):
        if not LANDMARKER.exists():
            raise FileNotFoundError("Run download_data.py first")
        import mediapipe as mp
        from mediapipe.tasks.python import vision

        self.mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(LANDMARKER)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)

    def extract(self, image: Image.Image) -> tuple[np.ndarray | None, str]:
        feature, status, _ = self.extract_detailed(image)
        return feature, status

    def extract_detailed(self, image: Image.Image) -> tuple[np.ndarray | None, str, bool]:
        """Detect one hand; retry with a black border when a close-up hand is missed.

        The palm detector often misses hands that fill the frame. Padding shrinks
        the hand relative to the image and recovers many of those cases.
        """
        image = image.convert("RGB")
        feature, status = self._detect(image)
        if status != "no_hand":
            return feature, status, False
        border = max(1, round(max(image.size) * RETRY_PADDING))
        feature, status = self._detect(ImageOps.expand(image, border=border, fill=(0, 0, 0)))
        return feature, status, status == "ok"

    def _detect(self, image: Image.Image) -> tuple[np.ndarray | None, str]:
        pixels = np.ascontiguousarray(image, dtype=np.uint8)
        result = self.detector.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=pixels))
        if not result.hand_world_landmarks:
            return None, "no_hand"
        if len(result.hand_world_landmarks) != 1:
            return None, "multiple_hands"
        points = np.asarray([[point.x, point.y, point.z] for point in result.hand_world_landmarks[0]])
        try:
            return normalize_landmarks(points), "ok"
        except ValueError:
            return None, "invalid_landmarks"

    def __exit__(self, *args):
        self.detector.close()


def source_rows():
    import pyarrow.parquet as pq

    if not PARQUET.exists():
        raise FileNotFoundError("Run download_data.py first")
    table = pq.read_table(PARQUET)
    for index, row in enumerate(table.to_pylist()):
        letter = chr(65 + int(row["label"]))
        if letter not in ("J", "Z"):
            yield index, letter, row["image"]["bytes"]


def extract_features() -> None:
    rows, features, labels, statuses, digests, hashes, padded = [], [], [], [], [], [], []
    start = time.perf_counter()
    with HandExtractor() as extractor:
        for index, letter, content in source_rows():
            with Image.open(io.BytesIO(content)) as image:
                image = image.convert("RGB")
                phash = perceptual_hash(image)
                feature, status, used_padding = extractor.extract_detailed(image)
            rows.append(index)
            padded.append(used_padding)
            labels.append(letter)
            hashes.append(phash)
            digests.append(hashlib.sha256(content).hexdigest())
            features.append(feature if feature is not None else np.full(63, np.nan, dtype=np.float32))
            statuses.append(status)
            if len(rows) % 500 == 0:
                print(f"Extracted {len(rows):,} images in {time.perf_counter() - start:.1f}s; {dict(Counter(statuses))}", flush=True)
    print("Grouping duplicate images...", flush=True)
    groups = duplicate_groups(hashes, digests)
    FEATURES.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        FEATURES, features=np.asarray(features), rows=np.asarray(rows), labels=np.asarray(labels),
        statuses=np.asarray(statuses), padded=np.asarray(padded), groups=groups, digests=np.asarray(digests),
        phashes=np.asarray(hashes, dtype=np.uint64), feature_version=FEATURE_VERSION,
        source_sha256=sha256(PARQUET), landmarker_sha256=sha256(LANDMARKER),
    )
    counts = {
        letter: dict(Counter(status for label, status in zip(labels, statuses) if label == letter))
        for letter in sorted(set(labels))
    }
    summary = {
        "images": len(rows), "statuses": dict(Counter(statuses)), "by_source_letter": counts,
        "recovered_with_padding": int(sum(padded)),
        "duplicate_groups": len(set(groups.tolist())), "phash_max_distance": NEAR_DUPLICATE_DISTANCE,
        "extraction_seconds": round(time.perf_counter() - start, 2),
        "feature_version": FEATURE_VERSION,
        "source": json.loads(MANIFEST.read_text()),
    }
    write_json(REPORTS / "data_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


def load_features():
    if not FEATURES.exists():
        raise FileNotFoundError("Run asl_model.py extract first")
    data = dict(np.load(FEATURES, allow_pickle=False))
    if str(data["feature_version"]) != FEATURE_VERSION:
        raise ValueError("Incompatible feature cache; extract features again")
    if str(data["source_sha256"]) != sha256(PARQUET) or str(data["landmarker_sha256"]) != sha256(LANDMARKER):
        raise ValueError("Source data or hand landmarker changed; extract features again")
    return data


def make_splits(labels: np.ndarray, groups: np.ndarray) -> dict[str, np.ndarray]:
    splitter = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=SEED)
    fold = np.full(len(labels), -1)
    for number, (_, indices) in enumerate(splitter.split(np.zeros(len(labels)), labels, groups)):
        fold[indices] = number
    splits = {"train": np.flatnonzero(fold >= 2), "validation": np.flatnonzero(fold == 1), "test": np.flatnonzero(fold == 0)}
    for name, indices in splits.items():
        if set(labels[indices]) != set(labels):
            raise ValueError(f"{name} split is missing source letters; inspect duplicate groups")
    names = list(splits)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            if set(groups[splits[first]]) & set(groups[splits[second]]):
                raise ValueError("Duplicate groups leaked between splits")
    return splits


def target_labels(labels: np.ndarray) -> np.ndarray:
    return np.asarray([letter if letter in LETTERS else "OTHER" for letter in labels])


def model_predictions(model, features: np.ndarray, threshold: float):
    predicted = np.full(len(features), "REJECT", dtype="<U6")
    scores = np.zeros(len(features))
    valid = np.isfinite(features).all(axis=1)
    if valid.any():
        probabilities = model.predict_proba(model_features(features[valid]))
        best = probabilities.argmax(axis=1)
        candidates = model.classes_[best]
        confidence = probabilities[np.arange(len(best)), best]
        scores[valid] = confidence
        predicted[valid] = np.where((candidates != "OTHER") & (confidence >= threshold), candidates, "REJECT")
    return predicted, scores


def metrics_for(truth: np.ndarray, predicted: np.ndarray) -> dict:
    accepted = predicted != "REJECT"
    supported = truth != "OTHER"
    correct = predicted == truth
    report = classification_report(truth, predicted, labels=list(LETTERS), zero_division=0, output_dict=True)
    per_letter = {letter: {key: float(value) for key, value in report[letter].items()} for letter in LETTERS}
    precision = float(correct[accepted].mean()) if accepted.any() else 0.0
    # Every static letter is supported, so there may be no unsupported samples to reject.
    rejection = float((~accepted[~supported]).mean()) if (~supported).any() else None
    return {
        "samples": len(truth), "supported_samples": int(supported.sum()),
        "accepted_predictions": int(accepted.sum()),
        "accepted_letter_precision": precision,
        "supported_recall": float(correct[supported].mean()) if supported.any() else 0.0,
        "unsupported_rejection_rate": rejection,
        "macro_f1_supported": float(report["macro avg"]["f1-score"]),
        "per_letter": per_letter,
        "acceptance_passed": bool(
            precision >= 0.9 and (rejection is None or rejection >= 0.9)
            and all(v["recall"] >= 0.8 for v in per_letter.values())
        ),
    }


def select_threshold(model, features: np.ndarray, truth: np.ndarray):
    trials = []
    selected = None
    for threshold in np.round(np.arange(MIN_THRESHOLD, 0.951, 0.05), 2):
        predictions, _ = model_predictions(model, features, float(threshold))
        metrics = metrics_for(truth, predictions)
        trials.append({"threshold": float(threshold), **metrics})
        rejection = metrics["unsupported_rejection_rate"]
        if selected is None and metrics["accepted_letter_precision"] >= TARGET_PRECISION and (rejection is None or rejection >= 0.9):
            selected = float(threshold)
    return selected if selected is not None else 0.95, selected is not None, trials


def train_model() -> None:
    data = load_features()
    splits = make_splits(data["labels"], data["groups"])
    y = target_labels(data["labels"])
    train = splits["train"]
    train = train[np.isfinite(data["features"][train]).all(axis=1)]
    if set(y[train]) != set(CLASSES):
        raise ValueError("Training data has no detected hands for one or more classes")
    # An RBF SVM matched the forest's precision with higher recall at a fraction of the size.
    model = make_pipeline(StandardScaler(), SVC(C=10, gamma="scale", probability=True, random_state=SEED))
    print(f"Training on {len(train):,} detected hands: {dict(Counter(y[train]))}", flush=True)
    start = time.perf_counter()
    features = data["features"][train]
    # Mirrored copies stay in the training split, so validation and test remain unseen.
    model.fit(model_features(np.vstack([features, mirror_landmarks(features)])), np.concatenate([y[train], y[train]]))
    val = splits["validation"]
    threshold, qualified, trials = select_threshold(model, data["features"][val], y[val])
    manifest = {
        "seed": SEED, "feature_cache_sha256": sha256(FEATURES),
        "splits": {name: data["rows"][indices].tolist() for name, indices in splits.items()},
        "groups": {str(row): int(group) for row, group in zip(data["rows"], data["groups"])},
    }
    write_json(SPLITS, manifest)
    metadata = {
        "letters": list(LETTERS), "classes": list(CLASSES), "unsupported_letters": list(MOTION_LETTERS),
        "feature_version": FEATURE_VERSION, "model_feature_version": MODEL_FEATURE_VERSION,
        "training_augmentation": "horizontal mirror of training landmarks",
        "threshold": threshold, "validation_threshold_qualified": qualified,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "seed": SEED,
        "source": json.loads(MANIFEST.read_text()), "split_manifest_sha256": sha256(SPLITS),
        "feature_cache_sha256": sha256(FEATURES), "python": platform.python_version(),
        "dependencies": {name: version(name) for name in ("mediapipe", "scikit-learn", "numpy", "joblib", "Pillow", "pyarrow", "opencv-contrib-python")},
        "classifier": {"type": "StandardScaler + SVC", **{key: value for key, value in model[-1].get_params().items() if key != "random_state"}, "random_state": SEED}, "training_samples": len(train), "training_rows_with_mirrors": 2 * len(train),
        "training_seconds": round(time.perf_counter() - start, 2),
    }
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, MODEL, compress=3)
    write_json(ROOT / "artifacts/model_metadata.json", metadata)
    write_json(REPORTS / "training.json", {
        **metadata, "validation_threshold_trials": trials,
        "split_counts": {name: {"images": len(indices), "source_letters": dict(Counter(data["labels"][indices])), "target_classes": dict(Counter(y[indices]))} for name, indices in splits.items()},
        "limitations": ["Public data has no signer identities; these are image-group splits, not signer-independent splits.", "J and Z require motion and are not recognized by this single-frame model.", "The dataset contains no non-sign poses, so rejection of arbitrary hand shapes relies only on the confidence threshold and remains unvalidated.", "No webcam validation has been performed by the training command."],
    })
    print(f"Saved {MODEL}; threshold {threshold:.2f}; validation threshold qualified: {qualified}", flush=True)


def load_model():
    if not MODEL.exists():
        raise FileNotFoundError("Run asl_model.py train first")
    bundle = joblib.load(MODEL)
    metadata = bundle["metadata"]
    if (
        metadata["feature_version"] != FEATURE_VERSION
        or metadata.get("model_feature_version") != MODEL_FEATURE_VERSION
        or tuple(metadata["letters"]) != LETTERS
    ):
        raise ValueError("Incompatible model preprocessing or label mapping")
    if bundle["metadata"]["source"]["files"]["landmarker"]["sha256"] != sha256(LANDMARKER):
        raise ValueError("Hand landmarker checksum differs from training")
    return bundle


def evaluate_model() -> None:
    data = load_features()
    bundle = load_model()
    manifest = json.loads(SPLITS.read_text())
    if sha256(FEATURES) != bundle["metadata"]["feature_cache_sha256"] or sha256(SPLITS) != bundle["metadata"]["split_manifest_sha256"]:
        raise ValueError("Evaluation data or splits differ from the trained model")
    indices = np.flatnonzero(np.isin(data["rows"], manifest["splits"]["test"]))
    truth = target_labels(data["labels"][indices])
    predictions, _ = model_predictions(bundle["model"], data["features"][indices], bundle["metadata"]["threshold"])
    report = metrics_for(truth, predictions)
    report.update({
        "threshold": bundle["metadata"]["threshold"], "model_sha256": sha256(MODEL),
        "feature_cache_sha256": sha256(FEATURES), "split_manifest_sha256": sha256(SPLITS),
        "detection_statuses": dict(Counter(data["statuses"][indices])),
        "webcam_validation": "not_performed", "signer_independent": False,
        "source_letter_counts": dict(Counter(data["labels"][indices])),
    })
    valid = np.isfinite(data["features"][indices]).all(axis=1)
    if valid.any():
        report["detected_hands_only"] = metrics_for(truth[valid], predictions[valid])
    write_json(REPORTS / "test_metrics.json", report)
    display_truth = np.where(truth == "OTHER", "REJECT", truth)
    names = [*LETTERS, "REJECT"]
    matrix = confusion_matrix(display_truth, predictions, labels=names)
    REPORTS.mkdir(parents=True, exist_ok=True)
    with (REPORTS / "confusion_matrix.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual / predicted", *names])
        for name, values in zip(names, matrix):
            writer.writerow([name, *values.tolist()])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import ConfusionMatrixDisplay

    fig, axis = plt.subplots(figsize=(14, 12))
    ConfusionMatrixDisplay(matrix, display_labels=names).plot(ax=axis, colorbar=False, cmap="Blues")
    axis.set_title("Held-out ASL images including hand-detection failures")
    fig.tight_layout()
    fig.savefig(REPORTS / "confusion_matrix.png", dpi=160)
    plt.close(fig)
    print(json.dumps(report, indent=2), flush=True)


def predict_image(image: Image.Image, extractor: HandExtractor, bundle: dict) -> dict:
    feature, status = extractor.extract(image)
    if feature is None:
        return {"status": status, "letter": None, "confidence": None}
    predictions, confidence = model_predictions(bundle["model"], feature[None, :], bundle["metadata"]["threshold"])
    letter = str(predictions[0])
    return {"status": "recognized" if letter != "REJECT" else "uncertain", "letter": letter if letter != "REJECT" else None, "confidence": float(confidence[0])}


class StablePrediction:
    """Choose the letter to display from a short window of recent frames.

    Single frames are noisy: motion blur or a borderline confidence can blank or
    flip the letter. A letter locks in when it leads the window's confidence-
    weighted vote with at least ``share`` of the letter votes and appears in at
    least half of the window's frames (and ``min_frames`` frames), once the window
    is at least half full. Once shown, it stays until another letter wins the
    window, or until no frame has shown it for ``hold`` seconds (uncertain,
    no-hand, or disagreeing frames).
    """

    def __init__(self, window: float = 0.6, hold: float = 0.4, share: float = 0.6, min_frames: int = 3):
        if window <= 0 or hold <= 0:
            raise ValueError("Window and hold must be greater than zero seconds")
        self.window, self.hold, self.share, self.min_frames = window, hold, share, min_frames
        self.frames: deque[tuple[float, str | None, float]] = deque()
        self.letter: str | None = None
        self.last_seen = 0.0
        self.leader: str | None = None
        self.leader_share = 0.0

    def update(self, result: dict, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        letter = result["letter"] if result["status"] == "recognized" else None
        self.frames.append((now, letter, float(result.get("confidence") or 0.0) if letter else 0.0))
        while self.frames[0][0] <= now - self.window:
            self.frames.popleft()

        votes, counts = Counter(), Counter()
        for _, voted, weight in self.frames:
            if voted is not None:
                votes[voted] += weight
                counts[voted] += 1
        self.leader, self.leader_share = None, 0.0
        if votes:
            self.leader = max(votes, key=votes.get)
            self.leader_share = votes[self.leader] / max(sum(votes.values()), 1e-9)
        locked = (
            self.leader is not None
            and now - self.frames[0][0] >= self.window / 2
            and self.leader_share >= self.share
            and counts[self.leader] >= max(self.min_frames, len(self.frames) / 2)
        )
        if locked and self.leader != self.letter:
            self.letter, self.last_seen = self.leader, now
        elif self.letter is not None and letter == self.letter:
            # The grace period counts from the last frame that actually showed the letter.
            self.last_seen = now
        if self.letter is not None and now - self.last_seen > self.hold:
            self.letter = None
        return self.letter


def open_camera(camera_index: int):
    """Use the native Mac backend instead of FFmpeg device autodetection."""
    import cv2

    if camera_index < 0:
        raise ValueError("Camera index must be zero or greater")
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    capture = cv2.VideoCapture(camera_index, backend)
    if not capture.isOpened():
        capture.release()
        if sys.platform == "darwin":
            guidance = (
                "In System Settings > Privacy & Security > Camera, allow the app "
                "running this command (Terminal, iTerm, VS Code, or Codex). "
                "Quit and reopen that app after changing access. Close other camera apps. "
                "If another camera is connected, try webcam --camera 1."
            )
        else:
            guidance = (
                "Allow camera access for the app running this command and close other camera apps. "
                "If another camera is connected, try webcam --camera 1."
            )
        raise RuntimeError(f"Could not open webcam {camera_index}. {guidance}")
    return capture


def render_webcam_output(
    frame: np.ndarray, result: dict, letter: str | None, elapsed_ms: float,
    leader: str | None = None, leader_share: float = 0.0,
) -> np.ndarray:
    """Keep the prediction large and readable below the camera image."""
    import cv2

    width, height, panel_height = 800, 600, 180
    frame_height, frame_width = frame.shape[:2]
    scale = min(width / frame_width, height / frame_height)
    preview_width = max(1, round(frame_width * scale))
    preview_height = max(1, round(frame_height * scale))
    preview = cv2.resize(cv2.flip(frame, 1), (preview_width, preview_height))
    display = np.zeros((height + panel_height, width, 3), dtype=np.uint8)
    left, top = (width - preview_width) // 2, (height - preview_height) // 2
    display[top:top + preview_height, left:left + preview_width] = preview
    messages = {
        "recognized": "Hold steady...",
        "uncertain": "Sign not recognized",
        "no_hand": "No hand detected",
        "multiple_hands": "Show one hand only",
        "invalid_landmarks": "Reposition your hand",
    }
    title = f"Letter: {letter}" if letter else messages.get(result["status"], "Waiting for a sign")
    if not letter and leader:
        # Show which letter is building up in the window and how strongly it leads.
        title = f"Hold steady... ({leader} {leader_share:.0%})"
    font_scale, thickness = (2.4, 5) if letter else (1.4, 3)
    color = (80, 255, 140) if letter else (255, 255, 255)
    cv2.putText(display, title, (24, height + 72), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)
    score = f"{result['confidence']:.0%}" if result["confidence"] is not None else "--"
    cv2.putText(display, f"Score: {score}  |  Processing: {elapsed_ms:.0f} ms", (24, height + 119), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (225, 225, 225), 2, cv2.LINE_AA)
    cv2.putText(display, "Static letters A-Y (no J or Z)  |  One hand  |  Q or Esc to exit", (24, height + 160), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (200, 200, 200), 2, cv2.LINE_AA)
    return display


def webcam(camera_index: int, window: float = 0.6, hold: float = 0.4) -> None:
    import cv2

    stable = StablePrediction(window=window, hold=hold)
    bundle = load_model()
    capture = open_camera(camera_index)
    try:
        with HandExtractor() as extractor:
            while True:
                success, frame = capture.read()
                if not success:
                    raise RuntimeError("Camera stopped returning frames")
                start = time.perf_counter()
                result = predict_image(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), extractor, bundle)
                letter = stable.update(result)
                # Classify original pixels; mirror and resize only the display.
                elapsed = (time.perf_counter() - start) * 1000
                display = render_webcam_output(frame, result, letter, elapsed, stable.leader, stable.leader_share)
                cv2.imshow("Group08 standalone ASL model", display)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27) or cv2.getWindowProperty("Group08 standalone ASL model", cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        capture.release()
        cv2.destroyAllWindows()


def benchmark(count: int) -> None:
    """Measure image decode + detection + classification, excluding model startup."""
    import pyarrow.parquet as pq

    if count <= 0:
        raise ValueError("Benchmark count must be positive")
    table = pq.read_table(PARQUET)
    manifest = json.loads(SPLITS.read_text())
    rows = manifest["splits"]["test"]
    rng = np.random.default_rng(SEED)
    chosen = rng.choice(rows, size=min(count, len(rows)), replace=False)
    bundle = load_model()
    durations, statuses = [], []
    with HandExtractor() as extractor:
        # Warm-up occurs before timing.
        with Image.open(io.BytesIO(table["image"][int(chosen[0])].as_py()["bytes"])) as image:
            predict_image(image, extractor, bundle)
        for row in chosen:
            content = table["image"][int(row)].as_py()["bytes"]
            start = time.perf_counter()
            with Image.open(io.BytesIO(content)) as image:
                result = predict_image(image, extractor, bundle)
            durations.append((time.perf_counter() - start) * 1000)
            statuses.append(result["status"])
    report = {
        "samples": len(durations), "median_ms": float(np.median(durations)),
        "p95_ms": float(np.percentile(durations, 95)), "statuses": dict(Counter(statuses)),
        "platform": platform.system(), "architecture": platform.machine(), "python": platform.python_version(),
        "excludes_model_startup": True, "model_sha256": sha256(MODEL),
        "latency_target_passed": bool(np.percentile(durations, 95) < 500),
    }
    write_json(REPORTS / "benchmark.json", report)
    print(json.dumps(report, indent=2))


def nonnegative_integer(value: str) -> int:
    try:
        integer = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if integer < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return integer


def positive_integer(value: str) -> int:
    integer = nonnegative_integer(value)
    if integer == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return integer


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not np.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Run without arguments to start the webcam. Example: python ml/asl_model.py webcam --camera 0",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("download", "extract", "train", "evaluate"):
        commands.add_parser(name)
    predict_parser = commands.add_parser("predict")
    predict_parser.add_argument("image", type=Path)
    webcam_parser = commands.add_parser("webcam")
    webcam_parser.add_argument("--camera", type=nonnegative_integer, default=0)
    webcam_parser.add_argument(
        "--window", type=positive_float, default=0.6, metavar="SECONDS",
        help="Seconds of recent frames that vote on the letter; larger is steadier but slower (default 0.6)",
    )
    webcam_parser.add_argument(
        "--hold", type=positive_float, default=0.4, metavar="SECONDS",
        help="Seconds a shown letter survives dropouts before clearing (default 0.4)",
    )
    benchmark_parser = commands.add_parser("benchmark")
    benchmark_parser.add_argument("--count", type=positive_integer, default=100)
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Editor Run buttons and double-click launches usually supply no subcommand.
    if not arguments:
        print("Starting webcam on camera 0. Press Q or Esc to exit.", flush=True)
        arguments = ["webcam"]
    elif arguments[0] == "--camera" or arguments[0].startswith("--camera="):
        arguments.insert(0, "webcam")
    args = parser.parse_args(arguments)
    if args.command == "download":
        download()
    elif args.command == "extract":
        extract_features()
    elif args.command == "train":
        train_model()
    elif args.command == "evaluate":
        evaluate_model()
    elif args.command == "predict":
        bundle = load_model()
        with Image.open(args.image) as image, HandExtractor() as extractor:
            print(json.dumps(predict_image(image, extractor, bundle), indent=2))
    elif args.command == "webcam":
        webcam(args.camera, args.window, args.hold)
    elif args.command == "benchmark":
        benchmark(args.count)


def cli(argv: list[str] | None = None) -> int:
    try:
        main(argv)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
