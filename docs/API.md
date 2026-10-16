# Flask API

The frontend and API share one origin, for example `http://localhost:5001`.
Use the root app runner described in the [README](../README.md).

## GET /api/health

A ready model returns HTTP 200:

```json
{"ready": true, "letters": ["A", "B", "C", "L", "Y"], "threshold": 0.65}
```

The threshold comes from the trained model and may differ after a new experiment.
An unavailable model returns HTTP 503 with `ready: false`, `letters`, and an
`error` explaining how to prepare assets. The frontend remains accessible.

## POST /api/predict

Upload a JPEG or PNG as multipart field `file`, with MIME type `image/jpeg` or
`image/png`. For example, with curl (use `curl.exe` on Windows):

```bash
curl -F "file=@sign.jpg" http://localhost:5001/api/predict
```

An accepted prediction returns HTTP 200:

```json
{"status": "recognized", "letter": "A", "confidence": 0.91}
```

Other successful statuses are `uncertain`, `no_hand`, `multiple_hands`, and
`invalid_landmarks`. They return a null `letter`. Confidence is null when no
features could be extracted; an uncertain classification can still have a score.
The browser applies stabilization separately to avoid sharing recognition state
between clients. Images are processed in memory and are not saved.

| HTTP status | Meaning |
| --- | --- |
| 400 | Missing, empty, or corrupt image |
| 413 | Request exceeds 2 MiB including multipart overhead, or image exceeds four million pixels |
| 415 | Unsupported image format or MIME type |
| 503 | Model unavailable |
| 500 | Unexpected inference failure |

Errors return a JSON object with an `error` message.

## Existing transcript routes

These routes remain available for compatibility. The current interface edits its
transcript locally and does not call them. Their transcript is shared within one
server process and disappears when it restarts.

| Route | Input | Result |
| --- | --- | --- |
| `GET /api/transcript` | None | Current transcript |
| `POST /api/add-letter` | JSON `{"letter": "A"}` | Append one ASCII letter A–Z, normalized to uppercase |
| `POST /api/add-space` | None | Append a space unless empty or already space-terminated |
| `POST /api/delete-last` | None | Remove the last character |
| `POST /api/reset` | None | Clear transcript |

Successful responses are `{"transcript": "..."}`. Invalid add-letter input
returns HTTP 400 with an `error` message.
