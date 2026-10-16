# ASL Translator

A local webcam app that recognizes **A, B, C, L, and Y**. Hold a sign steady,
click **Add Letter** to build a transcript, and use **Clear Transcript** to start
again. Flask serves the interface and runs the Python model; no frontend build
or separate backend service is needed.

## Quick start

You need **Python 3.12**, an internet connection for initial setup, and a webcam.
Node.js is optional and only needed for frontend tests.

Clone the repository, or download and extract its ZIP:

```bash
git clone https://github.com/g-allu/Group08_CSCE3444-FA26.git
cd Group08_CSCE3444-FA26
```

Run the following commands from that folder.

### macOS / Linux

```bash
python3.12 scripts/setup.py
.venv/bin/python run.py --port 5001
```

### Windows (PowerShell or Command Prompt)

```powershell
py -3.12 scripts/setup.py
.venv\Scripts\python.exe run.py --port 5001
```

Open **http://localhost:5001**, click **Start Camera**, and allow camera access.
Show one hand and hold a supported sign until the letter is ready. Click Add Letter
again for repeated letters. Stop Camera preserves text; reloading the page clears it.
Press **Ctrl+C** in the terminal to stop the app.

The repository includes the trained five-letter model and MediaPipe hand detector
(about **12 MB** combined), so teammates can run recognition without downloading
the training dataset or training a model. Setup creates `.venv/` at the repository
root, installs `requirements.txt`, and checks the included model. Dependency
installation can take several minutes and requires internet. No activation step
is required for the commands above. The dependency pins have been tested on Apple
Silicon macOS; Windows and Linux still need verification.

If the model assets are missing or incompatible, setup falls back to downloading
about **82 MB** of training assets, extracting landmarks, and training locally.
Training datasets, feature caches, and virtual environments are not included in Git.

## Everyday commands

After setup, start the app with the same `run.py` command; you do not need to
repeat setup. Choose another port with `--port` if 5001 is occupied.

To install dependencies without checking or preparing the model:

```bash
python3.12 scripts/setup.py --skip-model
```

Prepare the model later with `.venv/bin/python scripts/prepare_model.py`
(or `.venv\Scripts\python.exe scripts/prepare_model.py` on Windows).
The included model works with either setup command. If assets are missing, the
interface can start, but recognition requires model preparation.

## Sharing the prepared model

When committing this app, include these files along with the code:

- `ml/artifacts/asl_five_letters.joblib` — the trained classifier.
- `ml/artifacts/model_metadata.json` — training details and source information.
- `ml/data/models/hand_landmarker.task` — the matching hand detector.

These three files are explicitly allowed by `.gitignore`; other generated model
files and training data stay ignored. They are regular Git files, so both cloning
and GitHub's Download ZIP include them. After retraining, commit the updated
classifier and metadata together. Share `.venv/` through the setup script rather
than copying your local environment.

## Repository layout

```text
run.py                  Start the combined app
requirements.txt        Install the complete Python environment
scripts/                Initial setup and model preparation
frontend/               HTML, CSS, JavaScript, and frontend tests
backend/                Flask API, model integration, and tests/
ml/                     Model pipeline, tests/, and experiment reports/
docs/                   Development, API, and troubleshooting guides
.venv/                  Local Python environment (generated, ignored)
```

- [Development and testing](docs/DEVELOPMENT.md)
- [API reference](docs/API.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Model experiment results and limitations](ml/reports/RESULTS.md)

## Team

Group 08 — The Thinkers, CSCE 3444.

- Team lead / ML: Gnaneswar
- Frontend: Tanya
- Backend: Sajol Kumar

[Project board](https://github.com/users/g-allu/projects/2)
