# Troubleshooting

## Python cannot be found or setup reports the wrong version

Install Python 3.12 and reopen your terminal. On macOS/Linux use
`python3.12 scripts/setup.py`; on Windows use `py -3.12 scripts/setup.py`.
Other Python versions are not the tested environment for these dependency pins.

## Existing environment has the wrong Python version

Rename the root `.venv/` directory and rerun setup with Python 3.12. Do not reuse
an environment copied from another computer: virtual environments contain local
executable paths. Setup installs dependencies into `.venv/` without requiring activation.

## Dependency installation or model download fails

Check your internet connection and the error printed above the setup failure.
If a pinned package has no compatible wheel, verify that you are using Python 3.12
and a supported architecture. The dependency pins were tested on Apple Silicon
macOS; other platforms need separate verification. Do not silently substitute
package versions when reproducing the existing model.

Rerun the same setup command after fixing the problem. Completed downloads and
compatible features/model assets are reused. Downloads are checked against fixed
SHA-256 values. If an error identifies a corrupt file, remove only that named
local generated file and rerun setup.

## Model unavailable

The repository includes the classifier and hand detector. Confirm that your clone
or extracted ZIP contains `ml/artifacts/asl_five_letters.joblib` and
`ml/data/models/hand_landmarker.task`. Restore missing shared assets from Git, or
prepare replacements:

```bash
.venv/bin/python scripts/prepare_model.py
```

On Windows use `.venv\Scripts\python.exe scripts/prepare_model.py`.
Restart the app afterward: it loads the model at startup. Check `/api/health`
for an actionable error. Preparation reuses compatible assets; if they are missing
or incompatible, it downloads the training assets and trains locally.

## Port already in use

Choose another port:

```bash
.venv/bin/python run.py --port 5002
```

Open http://localhost:5002. The default backend port is 5000, which can be used by
macOS AirPlay Receiver; the README uses 5001 to avoid that common conflict.

## Camera unavailable

Open the app through Flask on localhost, allow browser camera permission, and
check the operating system's camera privacy settings. Close other apps that may
be using the camera. A remote browser needs HTTPS for camera access.

## No letter appears

Show only one hand in good lighting and hold A, B, C, L, or Y steady. Add Letter
becomes available after two matching accepted predictions. Unsupported or uncertain
signs clear the current letter. This is a five-letter experimental model, not a
complete ASL translator; see the [model results](../ml/reports/RESULTS.md).

## Static page opens but recognition fails

Use `run.py`, not `python -m http.server` or a `file://` URL. The interface needs
the Flask prediction API on the same origin. If the server was stopped, start it
again; the active camera loop retries failed requests automatically.
