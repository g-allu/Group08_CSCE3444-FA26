"""Install requirements into an existing virtual environment and check the model."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-model", action="store_true", help="Install dependencies without checking the bundled model.")
    args = parser.parse_args()
    if sys.version_info[:2] < (3, 12):
        parser.error("Python 3.12 or newer is required by the app dependencies.")
    if sys.prefix == sys.base_prefix:
        parser.error("Create a virtual environment first, then run this script with that environment's Python.")

    print("Installing requirements.txt into the current virtual environment...", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], cwd=ROOT, check=True)
    if not args.skip_model:
        print("Checking the bundled pretrained model...", flush=True)
        subprocess.run(
            [sys.executable, "-c", "from ml.asl_model import load_model; load_model()"],
            cwd=ROOT, check=True,
        )

    print("\nSetup complete. With your environment activated, run:\npython run.py --port 5001", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nSetup interrupted. Run the same command to resume.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Setup failed: {error}\nFix the error above, then run the same setup command to resume.")
