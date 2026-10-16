"""Standalone five-letter ASL experiment. No web application dependencies."""

from __future__ import annotations

import argparse
from collections import Counter
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
from PIL import Image
from scipy.fft import dctn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold

if __package__:
    from .download_data import LANDMARKER, MANIFEST, PARQUET, download, sha256
else:
    from download_data import LANDMARKER, MANIFEST, PARQUET, download, sha256

LETTERS = ("A", "B", "C", "L", "Y")
CLASSES = (*LETTERS, "OTHER")
FEATURE_VERSION = "world-wrist-relative-middle-mcp-scale-v1"
FEATURES = ROOT / "data/processed/features.npz"
SPLITS = ROOT / "data/processed/splits.json"
MODEL = ROOT / "artifacts/asl_five_letters.joblib"
REPORTS = ROOT / "reports"
SEED = 42
NEAR_DUPLICATE_DISTANCE = 4


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
        pixels = np.ascontiguousarray(image.convert("RGB"), dtype=np.uint8)
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
    rows, features, labels, statuses, digests, hashes = [], [], [], [], [], []
    start = time.perf_counter()
    with HandExtractor() as extractor:
        for index, letter, content in source_rows():
            with Image.open(io.BytesIO(content)) as image:
                image = image.convert("RGB")
                phash = perceptual_hash(image)
                feature, status = extractor.extract(image)
            rows.append(index)
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
        statuses=np.asarray(statuses), groups=groups, digests=np.asarray(digests),
        phashes=np.asarray(hashes, dtype=np.uint64), feature_version=FEATURE_VERSION,
        source_sha256=sha256(PARQUET), landmarker_sha256=sha256(LANDMARKER),
    )
    counts = {
        letter: dict(Counter(status for label, status in zip(labels, statuses) if label == letter))
        for letter in sorted(set(labels))
    }
    summary = {
        "images": len(rows), "statuses": dict(Counter(statuses)), "by_source_letter": counts,
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
        probabilities = model.predict_proba(features[valid])
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
    rejection = float((~accepted[~supported]).mean()) if (~supported).any() else 0.0
    return {
        "samples": len(truth), "supported_samples": int(supported.sum()),
        "accepted_predictions": int(accepted.sum()),
        "accepted_letter_precision": precision,
        "supported_recall": float(correct[supported].mean()) if supported.any() else 0.0,
        "unsupported_rejection_rate": rejection,
        "macro_f1_supported": float(report["macro avg"]["f1-score"]),
        "per_letter": per_letter,
        "acceptance_passed": bool(precision >= 0.9 and rejection >= 0.9 and all(v["recall"] >= 0.8 for v in per_letter.values())),
    }


def select_threshold(model, features: np.ndarray, truth: np.ndarray):
    trials = []
    selected = None
    for threshold in np.round(np.arange(0.5, 0.951, 0.05), 2):
        predictions, _ = model_predictions(model, features, float(threshold))
        metrics = metrics_for(truth, predictions)
        trials.append({"threshold": float(threshold), **metrics})
        if selected is None and metrics["accepted_letter_precision"] >= 0.9 and metrics["unsupported_rejection_rate"] >= 0.9:
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
    model = RandomForestClassifier(
        n_estimators=300, max_depth=20, min_samples_leaf=2,
        class_weight="balanced", random_state=SEED, n_jobs=1,
    )
    print(f"Training on {len(train):,} detected hands: {dict(Counter(y[train]))}", flush=True)
    start = time.perf_counter()
    model.fit(data["features"][train], y[train])
    val = splits["validation"]
    threshold, qualified, trials = select_threshold(model, data["features"][val], y[val])
    manifest = {
        "seed": SEED, "feature_cache_sha256": sha256(FEATURES),
        "splits": {name: data["rows"][indices].tolist() for name, indices in splits.items()},
        "groups": {str(row): int(group) for row, group in zip(data["rows"], data["groups"])},
    }
    write_json(SPLITS, manifest)
    metadata = {
        "letters": list(LETTERS), "classes": list(CLASSES), "feature_version": FEATURE_VERSION,
        "threshold": threshold, "validation_threshold_qualified": qualified,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "seed": SEED,
        "source": json.loads(MANIFEST.read_text()), "split_manifest_sha256": sha256(SPLITS),
        "feature_cache_sha256": sha256(FEATURES), "python": platform.python_version(),
        "dependencies": {name: version(name) for name in ("mediapipe", "scikit-learn", "numpy", "joblib", "Pillow", "pyarrow", "opencv-contrib-python")},
        "forest": model.get_params(), "training_samples": len(train),
        "training_seconds": round(time.perf_counter() - start, 2),
    }
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, MODEL, compress=3)
    write_json(ROOT / "artifacts/model_metadata.json", metadata)
    write_json(REPORTS / "training.json", {
        **metadata, "validation_threshold_trials": trials,
        "split_counts": {name: {"images": len(indices), "source_letters": dict(Counter(data["labels"][indices])), "target_classes": dict(Counter(y[indices]))} for name, indices in splits.items()},
        "limitations": ["Public data has no signer identities; these are image-group splits, not signer-independent splits.", "OTHER contains unsupported static letters; arbitrary non-sign poses remain unvalidated.", "No webcam validation has been performed by the training command."],
    })
    print(f"Saved {MODEL}; threshold {threshold:.2f}; validation threshold qualified: {qualified}", flush=True)


def load_model():
    if not MODEL.exists():
        raise FileNotFoundError("Run asl_model.py train first")
    bundle = joblib.load(MODEL)
    if bundle["metadata"]["feature_version"] != FEATURE_VERSION or tuple(bundle["metadata"]["letters"]) != LETTERS:
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

    fig, axis = plt.subplots(figsize=(7, 6))
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
    def __init__(self, required: int = 2):
        self.required = required
        self.previous = None
        self.count = 0

    def update(self, result: dict) -> str | None:
        letter = result["letter"] if result["status"] == "recognized" else None
        if letter is None:
            self.previous, self.count = None, 0
            return None
        self.count = self.count + 1 if letter == self.previous else 1
        self.previous = letter
        return letter if self.count >= self.required else None


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


def render_webcam_output(frame: np.ndarray, result: dict, letter: str | None, elapsed_ms: float) -> np.ndarray:
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
    font_scale, thickness = (2.4, 5) if letter else (1.4, 3)
    color = (80, 255, 140) if letter else (255, 255, 255)
    cv2.putText(display, title, (24, height + 72), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)
    score = f"{result['confidence']:.0%}" if result["confidence"] is not None else "--"
    cv2.putText(display, f"Score: {score}  |  Processing: {elapsed_ms:.0f} ms", (24, height + 119), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (225, 225, 225), 2, cv2.LINE_AA)
    cv2.putText(display, "A B C L Y  |  One hand  |  Q or Esc to exit", (24, height + 160), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (200, 200, 200), 2, cv2.LINE_AA)
    return display


def webcam(camera_index: int) -> None:
    import cv2

    bundle = load_model()
    capture = open_camera(camera_index)
    stable = StablePrediction()
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
                display = render_webcam_output(frame, result, letter, elapsed)
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
        webcam(args.camera)
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
