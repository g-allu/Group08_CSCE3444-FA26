"""Own one model/extractor pair for the life of the Flask process."""

import logging
from threading import Lock


class ModelUnavailable(RuntimeError):
    pass


class ModelService:
    def __init__(self):
        self.lock = Lock()
        self.bundle = None
        self.extractor = None
        self.letters = ()
        self.error = None
        try:
            from ml.asl_model import HandExtractor, LETTERS, load_model, predict_image

            self.letters = LETTERS
            self.predict_image = predict_image
            self.bundle = load_model()
            self.extractor = HandExtractor()
        except Exception as error:
            self.error = (
                f"Model unavailable: {error}. Install requirements.txt in your virtual environment "
                "and make sure the bundled model assets are present. "
                "Restart Flask after restoring compatible assets."
            )
            logging.getLogger(__name__).warning(self.error)

    def health(self):
        with self.lock:
            ready = self.extractor is not None
            result = {"ready": ready, "letters": list(self.letters)}
            if ready:
                result["threshold"] = self.bundle["metadata"]["threshold"]
            else:
                result["error"] = self.error or "Model service is closed. Restart Flask."
            return result

    def predict(self, image):
        with self.lock:
            if self.extractor is None:
                raise ModelUnavailable(self.error or "Model service is closed. Restart Flask.")
            return self.predict_image(image, self.extractor, self.bundle)

    def close(self):
        with self.lock:
            if self.extractor is not None:
                extractor, self.extractor = self.extractor, None
                extractor.__exit__(None, None, None)
