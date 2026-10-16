"""Reuse compatible model assets or prepare them from the pinned public dataset."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ml import asl_model as asl

    if asl.MODEL.exists():
        try:
            asl.load_model()
        except (OSError, ValueError) as error:
            print(f"Existing model needs preparation: {error}", flush=True)
        else:
            print("Compatible model already exists. Skipping download, extraction, and training.", flush=True)
            return

    # Keep generated reports local and ignored by Git.
    asl.REPORTS = asl.ROOT / "reports/local"
    asl.download()
    try:
        asl.load_features()
    except (OSError, ValueError):
        print("Extracting hand landmarks. This can take several minutes...", flush=True)
        asl.extract_features()
    else:
        print("Reusing compatible cached features.", flush=True)
    asl.train_model()
    asl.load_model()
    print("Model ready. Setup reports are in ml/reports/local/.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nModel preparation interrupted. Run this command again to resume.")
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        sys.exit(f"Model preparation failed: {error}\nInstall requirements.txt and rerun scripts/prepare_model.py.")
