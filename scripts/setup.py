"""Create the root environment, install dependencies, and prepare model assets."""

import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
PYTHON = ENVIRONMENT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-model", action="store_true", help="Install dependencies only; prepare model assets later.")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Python 3.12 is required. Use python3.12, or py -3.12 on Windows.")

    print("[1/3] Preparing .venv at the repository root...", flush=True)
    if ENVIRONMENT.exists():
        if not PYTHON.is_file():
            raise RuntimeError("Existing .venv is incomplete. Rename it, then run setup again.")
        result = subprocess.run(
            [str(PYTHON), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        if result.stdout.strip() != "3.12":
            raise RuntimeError("Existing .venv uses another Python version. Rename it, then run setup with Python 3.12.")
    else:
        venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)

    print("[2/3] Installing requirements.txt...", flush=True)
    subprocess.run([str(PYTHON), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], cwd=ROOT, check=True)
    if args.skip_model:
        print("[3/3] Model preparation skipped. Run scripts/prepare_model.py with the environment's Python when ready.", flush=True)
    else:
        print("[3/3] Checking shared model assets (missing assets will be prepared locally)...", flush=True)
        subprocess.run([str(PYTHON), str(ROOT / "scripts/prepare_model.py")], cwd=ROOT, check=True)

    relative_python = PYTHON.relative_to(ROOT)
    print(f"\nSetup complete. Start the app with:\n{relative_python} run.py --port 5001", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nSetup interrupted. Run the same command to resume.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Setup failed: {error}\nFix the error above, then run the same setup command to resume.")
