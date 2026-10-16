"""Start the local Flask app from the repository root."""

import sys


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 12):
        sys.exit("Use Python 3.12. See the setup steps in README.md.")
    try:
        from backend.app import main
    except ModuleNotFoundError as error:
        sys.exit(f"Missing dependency: {error.name}. Run scripts/setup.py with Python 3.12 first.")
    main()
