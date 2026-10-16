"""A teammate's source download can run inference without any training data."""

from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_shared_model_runs_without_dataset_or_training(tmp_path):
    checkout = tmp_path / "teammate checkout"
    for directory in ("backend", "ml", "scripts", "frontend"):
        source = ROOT / directory
        for path in source.glob("*"):
            if path.suffix in {".py", ".html", ".css", ".js"}:
                target = checkout / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    assets = (
        "ml/artifacts/asl_five_letters.joblib",
        "ml/artifacts/model_metadata.json",
        "ml/data/models/hand_landmarker.task",
    )
    for asset in assets:
        target = checkout / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / asset, target)

    # Fail immediately if preparation attempts any part of the training pipeline.
    check = """
import io
from unittest.mock import patch
from PIL import Image
from ml import asl_model as asl
from scripts.prepare_model import main
from backend.app import create_app

with patch.object(asl, 'download', side_effect=AssertionError('Unexpected download')), \
     patch.object(asl, 'extract_features', side_effect=AssertionError('Unexpected extraction')), \
     patch.object(asl, 'train_model', side_effect=AssertionError('Unexpected training')):
    main()

app = create_app({'TESTING': True})
try:
    client = app.test_client()
    assert client.get('/').status_code == 200
    health = client.get('/api/health')
    assert health.status_code == 200, health.json
    assert health.json['letters'] == ['A', 'B', 'C', 'L', 'Y']
    content = io.BytesIO()
    Image.new('RGB', (640, 480)).save(content, format='JPEG')
    content.seek(0)
    response = client.post('/api/predict', data={'file': (content, 'frame.jpg', 'image/jpeg')})
    assert response.status_code == 200, response.json
    assert response.json['status'] == 'no_hand'
finally:
    app.extensions['model_service'].close()
"""
    result = subprocess.run(
        [sys.executable, "-c", check], cwd=checkout,
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipping download, extraction, and training" in result.stdout
    assert not (checkout / "ml/data/raw").exists()
    assert not (checkout / "ml/data/processed").exists()
