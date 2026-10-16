"""HTTP contracts and lifecycle checks without requiring trained model assets."""

from concurrent.futures import ThreadPoolExecutor
import io
import signal
import sys
import threading
import time
from unittest.mock import MagicMock, Mock

from PIL import Image
import pytest

from backend.app import create_app
from backend import app as app_module
from backend.model_service import ModelService, ModelUnavailable
from ml import asl_model as asl


def image_bytes(format="JPEG", size=(80, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size).save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture
def service():
    fake = Mock()
    fake.health.return_value = {"ready": True, "letters": list(asl.LETTERS), "threshold": 0.75}
    fake.predict.return_value = {"status": "recognized", "letter": "A", "confidence": 0.91}
    return fake


@pytest.fixture
def app(service):
    instance = create_app({"TESTING": True}, model_service=service)
    yield instance
    service.close()


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, content=None, mimetype="image/jpeg"):
    if content is None:
        content = image_bytes()
    return client.post("/api/predict", data={"file": (io.BytesIO(content), "frame", mimetype)})


def test_health_and_frontend_routes(client, service):
    assert client.get("/api/health").json == service.health.return_value
    assert client.get("/").status_code == 200
    assert client.get("/script.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    service.health.return_value = {"ready": False, "letters": [], "error": "Train model first"}
    assert client.get("/api/health").status_code == 503
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("format,mimetype,status,letter,confidence", [
    ("JPEG", "image/jpeg", "recognized", "A", 0.91),
    ("PNG", "image/png", "recognized", "A", 0.91),
    ("JPEG", "image/jpeg", "uncertain", None, 0.6),
])
def test_prediction_contract(client, service, format, mimetype, status, letter, confidence):
    expected = {"status": status, "letter": letter, "confidence": confidence}
    service.predict.return_value = expected
    response = upload(client, image_bytes(format), mimetype)
    assert response.status_code == 200
    assert response.json == expected


@pytest.mark.parametrize("content,mimetype,expected", [
    (b"", "image/jpeg", 400), (b"broken", "image/jpeg", 400),
    (b"text", "text/plain", 415), (image_bytes("GIF"), "image/png", 415),
    (b"x" * (2 * 1024 * 1024), "image/jpeg", 413),
    (image_bytes("PNG", (2001, 2000)), "image/png", 413),
])
def test_invalid_uploads_never_run_model(client, service, content, mimetype, expected):
    response = upload(client, content, mimetype)
    assert response.status_code == expected
    assert "error" in response.json
    service.predict.assert_not_called()


def test_missing_file(client, service):
    assert client.post("/api/predict").status_code == 400
    service.predict.assert_not_called()


def test_inference_failures_return_json(client, service):
    service.predict.side_effect = ModelUnavailable("Train model first")
    assert upload(client).status_code == 503
    service.predict.side_effect = RuntimeError("internal details")
    response = upload(client)
    assert response.status_code == 500
    assert "internal details" not in response.json["error"]


def test_existing_transcript_api(client):
    assert client.get("/api/transcript").json == {"transcript": ""}
    assert client.post("/api/add-letter", json={"letter": "a"}).json == {"transcript": "A"}
    assert client.post("/api/add-space").json == {"transcript": "A "}
    assert client.post("/api/add-space").json == {"transcript": "A "}
    assert client.post("/api/delete-last").json == {"transcript": "A"}
    assert client.post("/api/reset").json == {"transcript": ""}
    for value in (None, [], {}, {"letter": "AB"}, {"letter": "é"}):
        assert client.post("/api/add-letter", json=value).status_code == 400


def test_service_loads_once_serializes_inference_and_closes_once(monkeypatch):
    bundle = {"metadata": {"threshold": 0.8}}
    loader = Mock(return_value=bundle)
    extractor = MagicMock()
    factory = Mock(return_value=extractor)
    active = 0
    maximum_active = 0
    counter_lock = threading.Lock()

    def predict(image, actual_extractor, actual_bundle):
        nonlocal active, maximum_active
        assert actual_extractor is extractor
        assert actual_bundle is bundle
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with counter_lock:
            active -= 1
        return {"status": "no_hand", "letter": None, "confidence": None}

    monkeypatch.setattr(asl, "load_model", loader)
    monkeypatch.setattr(asl, "HandExtractor", factory)
    monkeypatch.setattr(asl, "predict_image", predict)
    service = ModelService()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(service.predict, [None] * 8))
        assert len(results) == 8
        assert maximum_active == 1
        loader.assert_called_once_with()
        factory.assert_called_once_with()
        assert service.health()["threshold"] == 0.8
    finally:
        service.close()
    service.close()
    extractor.__exit__.assert_called_once_with(None, None, None)
    assert not service.health()["ready"]
    with pytest.raises(ModelUnavailable):
        service.predict(None)


def test_missing_assets_keep_app_available(monkeypatch):
    monkeypatch.setattr(asl, "load_model", Mock(side_effect=FileNotFoundError("Missing model")))
    service = ModelService()
    assert not service.health()["ready"]
    assert "Restart Flask" in service.health()["error"]
    app = create_app({"TESTING": True}, model_service=service)
    try:
        client = app.test_client()
        assert client.get("/").status_code == 200
        assert client.get("/api/health").status_code == 503
        assert upload(client).status_code == 503
    finally:
        service.close()


@pytest.mark.skipif(not asl.MODEL.exists() or not asl.LANDMARKER.exists(), reason="Prepare local model assets first")
def test_real_model_through_flask():
    app = create_app({"TESTING": True})
    service = app.extensions["model_service"]
    try:
        client = app.test_client()
        assert client.get("/api/health").status_code == 200
        response = upload(client, image_bytes(size=(640, 480)))
        assert response.status_code == 200
        assert response.json == {"status": "no_hand", "letter": None, "confidence": None}
    finally:
        service.close()


@pytest.mark.parametrize("stop", ["interrupt", "terminate", "startup_error"])
def test_runner_closes_model_when_server_stops(monkeypatch, service, stop):
    app = create_app({"TESTING": True}, model_service=service)
    monkeypatch.setattr(app_module, "create_app", Mock(return_value=app))
    monkeypatch.setattr(sys, "argv", ["backend.app"])
    previous_handler = signal.getsignal(signal.SIGTERM)

    def run(**kwargs):
        if stop == "terminate":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise KeyboardInterrupt if stop == "interrupt" else OSError("Port unavailable")

    monkeypatch.setattr(app, "run", run)
    expected = {"interrupt": KeyboardInterrupt, "terminate": SystemExit, "startup_error": OSError}
    with pytest.raises(expected[stop]):
        app_module.main()
    service.close.assert_called_once_with()
    assert signal.getsignal(signal.SIGTERM) == previous_handler
