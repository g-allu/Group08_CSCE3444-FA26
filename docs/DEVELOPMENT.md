# Development

Run the quick-start setup in the [README](../README.md) first. All commands below
run from the repository root with Python 3.12. On Windows replace
`.venv/bin/python` with `.venv\Scripts\python.exe`.

## Application

```bash
.venv/bin/python run.py --port 5001
```

`run.py` delegates to the Flask app runner, which keeps one model/extractor pair
per process, serializes inference, and closes the detector on shutdown. Use this
runner rather than `flask run` so MediaPipe closes before Python shuts down its
thread executors. Debug mode and auto-reload are disabled.

Flask serves `frontend/` directly and exposes `/api/health` and `/api/predict`.
The browser sends original, unmirrored JPEG frames resized to at most 640 pixels
on either side, with at most five requests per second and one request in flight.
Two matching predictions enable Add Letter. Errors clear the accepted prediction;
request timeouts are five seconds and service failures retry after two seconds.
Transcript text stays in browser memory. See the [API reference](API.md).

## Dependencies

Install the full app from the root manifest:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

The root manifest includes `backend/requirements.txt` (Flask and its dependencies)
and `ml/requirements.txt` (tested model pipeline dependencies and pytest).
Keep ML dependency changes consistent between `ml/requirements.in` and its pinned
requirements file. Keep the environment in the root `.venv/` directory.
No JavaScript packages, Node server, or frontend build step are required to run the app.

## Model workflow

```bash
.venv/bin/python scripts/prepare_model.py
```

The repository includes a compatible classifier and hand detector; this normally
checks them and returns without downloading data or training. If they are missing
or incompatible, it downloads pinned, checksum-verified training assets, reuses a
compatible feature cache, trains missing/incompatible model assets, and validates
that the result can load. It reuses an existing compatible model without training.
Setup-generated reports go to ignored `ml/reports/local/` so onboarding does not
modify the checked-in experiment results.

For explicit model experiments, the existing CLI remains available:

```bash
.venv/bin/python ml/asl_model.py download
.venv/bin/python ml/asl_model.py extract
.venv/bin/python ml/asl_model.py train
.venv/bin/python ml/asl_model.py evaluate
.venv/bin/python ml/asl_model.py webcam --camera 0
```

These experiment commands write reports under `ml/reports/`; review those changes
before committing. The standalone webcam window uses Q or Esc to exit.
The shared inference files `ml/artifacts/asl_five_letters.joblib`,
`ml/artifacts/model_metadata.json`, and `ml/data/models/hand_landmarker.task` are
included in Git. Keep the classifier and metadata together when updating the model.
Other contents of `ml/data/` and `ml/artifacts/` are generated and Git-ignored.
Do not commit downloaded datasets, virtual environments, or caches.

## Tests

```bash
.venv/bin/python -m pytest backend/tests ml/tests -q
node --test frontend/tests/recognition.test.cjs
```

Use Node.js 20 or newer for the optional frontend tests. Python tests cover model
behavior, API input/errors, inference concurrency, cleanup, and transcript routes.
Frontend tests use fake camera/network adapters to check recognition, Add/Clear,
request failures, and camera lifecycle without requiring a physical camera.

Real-model tests skip if model assets are absent. Tests involving saved features
and held-out images also require the local training data and cache; run the
`download`, `extract`, and `train` experiment commands above to recreate these
before claiming full dataset validation. Normal setup reuses the bundled model
and does not create evaluation data. Dataset metrics do not establish live webcam
accuracy.

For interface changes manually check camera permission denial, one-hand recognition,
uncertainty/multiple hands, repeated letters, clearing text, stop/restart during an
active request, and leaving the page. Stop/restart the server with the camera active
to verify recovery. Include screenshots for visual changes.
