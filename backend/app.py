"""Local Flask frontend and ASL inference API."""

import argparse
import io
import signal
from pathlib import Path

from flask import Flask, Request, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError

from .model_service import ModelService, ModelUnavailable
from .translator import Translator

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_IMAGE_PIXELS = 4_000_000


class MemoryUploadRequest(Request):
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        # Werkzeug otherwise spills uploads above 500 KB to temporary files.
        # MAX_CONTENT_LENGTH bounds memory use for the entire request.
        return io.BytesIO()


def create_app(config=None, model_service=None):
    app = Flask(__name__, static_folder=None)
    app.request_class = MemoryUploadRequest
    app.config.from_mapping(MAX_CONTENT_LENGTH=2 * 1024 * 1024)
    if config:
        app.config.update(config)

    service = model_service if model_service is not None else ModelService()
    app.extensions["model_service"] = service
    translator = Translator()
    app.extensions["translator"] = translator

    @app.get("/api/health")
    def health():
        details = service.health()
        return jsonify(details), 200 if details["ready"] else 503

    @app.post("/api/predict")
    def predict():
        upload = request.files.get("file")
        if upload is None:
            return jsonify(error="Upload an image in multipart field 'file'."), 400
        if upload.mimetype not in {"image/jpeg", "image/png"}:
            return jsonify(error="Only JPEG and PNG images are supported."), 415

        # The request is bounded before parsing. Never save camera frames to disk.
        content = upload.read()
        if not content:
            return jsonify(error="The uploaded image is empty."), 400
        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG"}:
                    return jsonify(error="Only JPEG and PNG images are supported."), 415
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    return jsonify(error="Images must contain at most four million pixels."), 413
                image = source.convert("RGB")
        except Image.DecompressionBombError:
            return jsonify(error="Images must contain at most four million pixels."), 413
        except (UnidentifiedImageError, OSError, ValueError):
            return jsonify(error="The uploaded image is corrupt or unreadable."), 400

        try:
            with image:
                return jsonify(service.predict(image))
        except ModelUnavailable as error:
            return jsonify(error=str(error)), 503
        except Exception:
            app.logger.exception("ASL inference failed")
            return jsonify(error="Recognition failed. Please try again."), 500

    @app.errorhandler(413)
    def request_too_large(error):
        return jsonify(error="Request exceeds the 2 MB upload limit."), 413

    # Preserve the existing transcript API. The MVP UI edits text locally.
    @app.post("/api/add-letter")
    def add_letter():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400
        result = translator.add_letter(data.get("letter"))
        if result is None:
            return jsonify(error="Enter one letter A-Z"), 400
        return jsonify(transcript=result)

    @app.post("/api/add-space")
    def add_space():
        return jsonify(transcript=translator.add_space())

    @app.post("/api/delete-last")
    def delete_last():
        return jsonify(transcript=translator.delete_last())

    @app.post("/api/reset")
    def reset():
        return jsonify(transcript=translator.reset())

    @app.get("/api/transcript")
    def get_transcript():
        return jsonify(transcript=translator.get_transcript())

    @app.get("/")
    def home():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def frontend_files(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    return app


def main():
    parser = argparse.ArgumentParser(description="Run the local ASL Flask app.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    app = create_app()

    def terminate(signum, frame):
        raise SystemExit(0)

    previous_handler = signal.signal(signal.SIGTERM, terminate)
    try:
        app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
    finally:
        # MediaPipe must close before Python shuts down its thread executors.
        try:
            app.extensions["model_service"].close()
        finally:
            signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    main()
