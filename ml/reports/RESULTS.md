# Initial five letter model results

The Python ASL classifier has been trained for **A, B, C, L, and Y**, plus an
`OTHER` class. It is an experimental baseline and **does not yet meet the MVP
recall target**. The frontend and backend are not part of this experiment.

## Held out evaluation

Training used 6,213 successfully detected hands. Validation selected a score
threshold of **0.65**, without consulting the test split. Evaluation then used
**1,004 held-out images**, including 210 supported-letter images and 794 images
of unsupported static letters. Image duplicate groups remain in a single split.

| Measure | Result |
| --- | --- |
| Precision of accepted letter predictions | 93.10% (135 correct out of 145 accepted) |
| Recall across supported-letter images | 64.29% (135 correct out of 210 attempts) |
| Rejection of unsupported static letters | 98.74% (784 out of 794) |
| Macro F1 across the five supported letters | 75.19% |
| Supported-letter recall when a hand was detected | 78.03% |
| Median image inference latency | 13.79 ms |
| 95th percentile image inference latency | 18.85 ms |

Latency was measured on this Apple Silicon Mac across 100 held-out images. It
includes image decoding, hand detection, and classification, with model startup
and warm-up excluded. It is not a measurement of webcam frame rate.

| Letter | Precision | End to end recall | Correct / attempts |
| --- | --- | --- | --- |
| A | 100.00% | 80.95% | 34 / 42 |
| B | 93.55% | 69.05% | 29 / 42 |
| C | 84.21% | 38.10% | 16 / 42 |
| L | 96.55% | 66.67% | 28 / 42 |
| Y | 87.50% | 66.67% | 28 / 42 |

## Interpretation and next experiment

The model is fast and conservative, but it rejects too many valid supported
letters. C needs the most improvement. Of the 1,004 test images, 242 did not
produce a hand detection; 37 of those were supported letters. These failures
are included in the recall above rather than removed from the benchmark.

The next model experiment should improve hand detection and recognition of C,
using validation data for model selection. Keep this report as the baseline;
after inspecting these test results, do not describe future experiments on the
same test split as evaluation on a previously unseen benchmark.

This dataset has no signer identities, so the scores are not signer-independent
results. The unsupported class contains other static letters, not every possible
non-sign hand pose. Live webcam accuracy has **not been validated**. Use the
standalone webcam command in the parent README for separate live trials before
considering application integration.

Machine-readable evidence is in `data_summary.json`, `training.json`,
`test_metrics.json`, `confusion_matrix.csv`, and `benchmark.json` beside this file.

All **36 automated tests passed**, including default webcam startup, CLI argument
validation, clean interruption handling, macOS camera backend selection,
camera failure cleanup, raw held-out image inference for
each letter, empty-image rejection, corrupted-file handling, model serialization,
and isolation of duplicate groups across the train, validation, and test splits.
