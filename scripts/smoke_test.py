
"""Smoke tests for the running ASL Translator application."""

import argparse
import json
import sys

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXPECTED_LETTERS = {"A", "B", "C", "L", "Y"}


def request(base_url, path, method="GET", data=None, headers=None):
    url = base_url.rstrip("/") + path

    req = Request(
        url,
        data=data,
        headers=headers or {},
        method=method
    )

    try:
        with urlopen(req, timeout=30) as response:
            return (
                response.status,
                response.read(),
                response.headers
            )

    except HTTPError as error:
        return (
            error.code,
            error.read(),
            error.headers
        )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_homepage(base_url):
    status, body, headers = request(base_url, "/")

    require(
        status == 200,
        f"Homepage returned HTTP {status}"
    )

    require(
        "text/html" in headers.get("Content-Type", ""),
        "Homepage did not return HTML"
    )

    html = body.decode("utf-8")

    expected_elements = [
        'id="camera"',
        'id="startCamera"',
        'id="stopCamera"',
        'id="addLetter"',
        'id="addSpace"',
        'id="deleteLast"',
        'id="clearText"',
        'id="resetSession"',
        'id="copyTranscript"',
        'id="downloadTranscript"',
        'id="transcriptCount"',
        'src="transcript-export.js"'
    ]

    for element in expected_elements:
        require(
            element in html,
            f"Homepage is missing {element}"
        )


def check_frontend_assets(base_url):
    assets = {
        "/script.js": "displayRecognitionResult",
        "/style.css": ".transcript-controls",
        "/transcript-export.js": "initializeExport"
    }

    for asset, expected_text in assets.items():
        status, body, _ = request(base_url, asset)

        require(
            status == 200,
            f"{asset} returned HTTP {status}"
        )

        require(
            expected_text in body.decode("utf-8"),
            f"{asset} does not contain expected code"
        )


def check_model_health(base_url):
    status, body, _ = request(
        base_url,
        "/api/health"
    )

    details = json.loads(body)

    require(
        status == 200,
        f"Model health returned HTTP {status}: {details}"
    )

    require(
        details.get("ready") is True,
        "Recognition model is not ready"
    )

    letters = details.get("letters", [])

    require(
        EXPECTED_LETTERS.issubset(set(letters)),
        f"Unexpected supported letters: {letters}"
    )

    print(
        "  Supported letters:",
        ", ".join(sorted(letters))
    )


def check_missing_image(base_url):
    status, body, _ = request(
        base_url,
        "/api/predict",
        method="POST",
        data=b"",
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        }
    )

    require(
        status == 400,
        f"Missing image returned HTTP {status}, expected 400"
    )

    result = json.loads(body)

    require(
        "error" in result,
        "Missing-image response has no error message"
    )


def check_invalid_image(base_url):
    boundary = "ASLSmokeTestBoundary"

    data = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; '
        'name="file"; filename="invalid.jpg"\r\n'
        "Content-Type: image/jpeg\r\n"
        "\r\n"
        "This is not a valid JPEG image.\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    status, body, _ = request(
        base_url,
        "/api/predict",
        method="POST",
        data=data,
        headers={
            "Content-Type":
                f"multipart/form-data; boundary={boundary}"
        }
    )

    require(
        status == 400,
        f"Invalid image returned HTTP {status}, expected 400"
    )

    result = json.loads(body)

    require(
        "error" in result,
        "Invalid-image response has no error message"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Verify a running ASL Translator application."
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5001",
        help="Application base URL"
    )

    args = parser.parse_args()

    checks = [
        ("Homepage and controls", check_homepage),
        ("Frontend JavaScript and CSS", check_frontend_assets),
        ("Recognition model health", check_model_health),
        ("Missing image validation", check_missing_image),
        ("Invalid image validation", check_invalid_image)
    ]

    print("ASL Translator smoke tests")
    print(f"Server: {args.url}")
    print("-" * 50)

    passed = 0
    failed = 0

    for name, check in checks:
        try:
            check(args.url)

            print(f"PASS: {name}")

            passed += 1

        except (
            AssertionError,
            URLError,
            ValueError,
            OSError
        ) as error:

            print(f"FAIL: {name}")
            print(f"  {error}")

            failed += 1

    print("-" * 50)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
