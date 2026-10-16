"""Start the local Flask app from the repository root."""

import sys


if __name__ == "__main__":
    if sys.version_info[:2] < (3, 12):
        sys.exit("Python 3.12 or newer is required by the app dependencies.")
    try:
        from backend.app import main
    except ModuleNotFoundError as error:
        sys.exit(f"Missing dependency: {error.name}. Install requirements.txt in your virtual environment first.")
    main()
