"""Download the fixed public training snapshot and MediaPipe feature extractor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import ssl
import urllib.request

import certifi

ROOT = Path(__file__).resolve().parent
DATASET = "Marxulia/asl_sign_languages_alphabets_v03"
REVISION = "1adf43b2d31eb9d7aea5855edaeac0231d8a2757"
PARQUET = ROOT / "data/raw/asl.parquet"
LANDMARKER = ROOT / "data/models/hand_landmarker.task"
MANIFEST = ROOT / "data/source.json"
EXPECTED_SHA256 = {
    "dataset": "a2211d863e15846bbad01bec5137c161262ae3eaf29ad8debd96490c15ebfcd6",
    "landmarker": "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
}
SOURCES = {
    "dataset": (
        f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/data/train-00000-of-00001.parquet",
        PARQUET,
    ),
    "landmarker": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        LANDMARKER,
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download() -> None:
    previous = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    manifest = {"dataset": DATASET, "revision": REVISION, "files": {}}
    context = ssl.create_default_context(cafile=certifi.where())
    for name, (url, path) in SOURCES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            print(f"Downloading {name}...", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "Group08-ASL-ML/1.0"})
            partial = path.with_suffix(path.suffix + ".part")
            try:
                with urllib.request.urlopen(request, context=context, timeout=120) as response:
                    expected = response.headers.get("Content-Length")
                    with partial.open("wb") as handle:
                        for chunk in iter(lambda: response.read(1024 * 1024), b""):
                            handle.write(chunk)
                if expected and partial.stat().st_size != int(expected):
                    raise RuntimeError(f"Incomplete download: {name}")
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        checksum = sha256(path)
        if checksum != EXPECTED_SHA256[name]:
            raise RuntimeError(f"Checksum mismatch for {path}; remove the corrupt file and download again")
        old = previous.get("files", {}).get(name, {})
        if old.get("sha256") and old["sha256"] != checksum:
            raise RuntimeError(f"Checksum mismatch for {path}; remove the corrupt file and download again")
        manifest["files"][name] = {
            "url": url,
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": checksum,
        }
        print(f"{name}: {path.stat().st_size:,} bytes, SHA256 {checksum}", flush=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    download()
