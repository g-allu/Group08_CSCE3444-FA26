"""Local Flask frontend, ASL inference, and translation history API."""

import argparse
import io
import os
import signal
from uuid import uuid4
from pathlib import Path

from flask import (
    Flask,
    Request,
    jsonify,
    request,
    send_from_directory,
    session,
)
from PIL import Image, UnidentifiedImageError

from .model_service import ModelService, ModelUnavailable
from .translator import Translator
from .history import TranslationHistory


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_IMAGE_PIXELS = 4_000_000
MAX_TRANSCRIPT_LENGTH = 2000


class MemoryUploadRequest(Request):
    def _get_file_stream(
        self,
        total_content_length,
        content_type,
        filename=None,
        content_length=None,
    ):
        # Keep camera uploads in memory.
        return io.BytesIO()


def create_app(config=None, model_service=None):
    app = Flask(__name__, static_folder=None)
    app.request_class = MemoryUploadRequest

    app.config.from_mapping(
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or os.urandom(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if config:
        app.config.update(config)

    service = (
        model_service
        if model_service is not None
        else ModelService()
    )
    app.extensions["model_service"] = service

    # Translation history is stored separately for each session.
    history = TranslationHistory()
    app.extensions["translation_history"] = history

    def current_session_id():
        """Get or create an ID for this browser session."""
        session_id = session.get("history_session_id")

        if not isinstance(session_id, str) or not session_id:
            session_id = str(uuid4())
            session["history_session_id"] = session_id

        return session_id

    def current_translator():
        """Restore this browser's current transcript."""
        translator = Translator()
        saved = session.get("transcript", "")

        if isinstance(saved, str):
            translator.transcript = saved[:MAX_TRANSCRIPT_LENGTH]

        return translator

    def save_transcript(translator):
        """Save the current transcript in the browser session."""
        text = translator.get_transcript()
        session["transcript"] = text
        return jsonify(transcript=text)

    # -------------------------------------------------
    # Recognition model health
    # -------------------------------------------------

    @app.get("/api/health")
    def health():
        details = service.health()
        return jsonify(details), 200 if details["ready"] else 503

    # -------------------------------------------------
    # ASL image recognition
    # -------------------------------------------------

    @app.post("/api/predict")
    def predict():
        upload = request.files.get("file")

        if upload is None:
            return jsonify(
                error="Upload an image in multipart field 'file'."
            ), 400

        if upload.mimetype not in {"image/jpeg", "image/png"}:
            return jsonify(
                error="Only JPEG and PNG images are supported."
            ), 415

        content = upload.read()

        if not content:
            return jsonify(
                error="The uploaded image is empty."
            ), 400

        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG"}:
                    return jsonify(
                        error="Only JPEG and PNG images are supported."
                    ), 415

                if source.width * source.height > MAX_IMAGE_PIXELS:
                    return jsonify(
                        error="Images must contain at most four million pixels."
                    ), 413

                image = source.convert("RGB")

        except Image.DecompressionBombError:
            return jsonify(
                error="Images must contain at most four million pixels."
            ), 413

        except (UnidentifiedImageError, OSError, ValueError):
            return jsonify(
                error="The uploaded image is corrupt or unreadable."
            ), 400

        try:
            with image:
                return jsonify(service.predict(image))

        except ModelUnavailable as error:
            return jsonify(error=str(error)), 503

        except Exception:
            app.logger.exception("ASL inference failed")
            return jsonify(
                error="Recognition failed. Please try again."
            ), 500

    @app.errorhandler(413)
    def request_too_large(error):
        return jsonify(
            error="Request exceeds the 2 MB upload limit."
        ), 413

    # -------------------------------------------------
    # Existing transcript features
    # -------------------------------------------------

    @app.post("/api/add-letter")
    def add_letter():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400

        translator = current_translator()

        if len(translator.get_transcript()) >= MAX_TRANSCRIPT_LENGTH:
            return jsonify(
                error="Transcript length limit reached"
            ), 413

        result = translator.add_letter(data.get("letter"))

        if result is None:
            return jsonify(error="Enter one letter A-Z"), 400

        return save_transcript(translator)

    @app.post("/api/add-space")
    def add_space():
        translator = current_translator()

        if len(translator.get_transcript()) >= MAX_TRANSCRIPT_LENGTH:
            return jsonify(
                error="Transcript length limit reached"
            ), 413

        translator.add_space()
        return save_transcript(translator)

    @app.post("/api/delete-last")
    def delete_last():
        translator = current_translator()
        translator.delete_last()
        return save_transcript(translator)

    @app.post("/api/reset")
    def reset():
        translator = current_translator()
        translator.reset()
        return save_transcript(translator)

    @app.get("/api/transcript")
    def get_transcript():
        return jsonify(
            transcript=current_translator().get_transcript()
        )

    # -------------------------------------------------
    # NEW FEATURE: Translation History
    # -------------------------------------------------

    @app.post("/api/history")
    def save_history():
        """Save a translation to the current session's history."""
        data = request.get_json(silent=True)

        if data is None:
            data = {}

        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400

        # Accept text from the frontend or use the backend transcript.
        transcript = data.get("transcript")

        if transcript is None:
            transcript = current_translator().get_transcript()

        if not isinstance(transcript, str):
            return jsonify(error="Transcript must be text"), 400

        if len(transcript) > MAX_TRANSCRIPT_LENGTH:
            return jsonify(
                error="Transcript length limit reached"
            ), 413

        try:
            entry = history.save(
                current_session_id(),
                transcript,
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400

        return jsonify(entry), 201

    @app.get("/api/history")
    def get_history():
        """List translations saved in this browser session."""
        entries = history.list_history(current_session_id())
        return jsonify(history=entries)

    @app.delete("/api/history/<entry_id>")
    def delete_history_entry(entry_id):
        """Delete one translation from history."""
        deleted = history.delete(
            current_session_id(),
            entry_id,
        )

        if not deleted:
            return jsonify(
                error="History entry not found"
            ), 404

        return jsonify(message="Translation deleted")

    @app.delete("/api/history")
    def clear_history():
        """Clear all translations in this session."""
        history.clear(current_session_id())
        return jsonify(message="Translation history cleared")

    # -------------------------------------------------
    # Frontend
    # -------------------------------------------------

    @app.get("/")
    def home():
        return send_from_directory(
            FRONTEND_DIR,
            "index.html",
        )

    @app.get("/<path:filename>")
    def frontend_files(filename):
        return send_from_directory(
            FRONTEND_DIR,
            filename,
        )

    return app


def main():
    parser = argparse.ArgumentParser(
        description="Run the local ASL Flask app."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
    )
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error(
            "--port must be between 1 and 65535"
        )

    app = create_app()

    def terminate(signum, frame):
        raise SystemExit(0)

    previous_handler = signal.signal(
        signal.SIGTERM,
        terminate,
    )

    try:
        app.run(
            host="127.0.0.1",
            port=args.port,
            debug=False,
            use_reloader=False,
        )

    finally:
        try:
            app.extensions["model_service"].close()
        finally:
            signal.signal(
                signal.SIGTERM,
                previous_handler,
            )


if __name__ == "__main__":
    main()

