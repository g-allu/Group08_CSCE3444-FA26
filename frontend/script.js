
const camera = document.getElementById("camera");
const startButton = document.getElementById("startCamera");
const stopButton = document.getElementById("stopCamera");
const cameraStatus = document.getElementById("cameraStatus");
const cameraPlaceholder = document.getElementById("cameraPlaceholder");
const errorMessage = document.getElementById("errorMessage");
const modelStatus = document.getElementById("modelStatus");
const detectedLetter = document.getElementById("detectedLetter");
const recognitionStatus = document.getElementById("recognitionStatus");
const confidenceText = document.getElementById("confidenceText");
const transcriptDisplay = document.getElementById("transcript");
const transcriptStatus = document.getElementById("transcriptStatus");

const addLetterButton = document.getElementById("addLetter");
const addSpaceButton = document.getElementById("addSpace");
const deleteLastButton = document.getElementById("deleteLast");
const clearTextButton = document.getElementById("clearText");
const resetSessionButton = document.getElementById("resetSession");

const canvas = document.createElement("canvas");
const context = canvas.getContext("2d");

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

// J and Z are signed with motion, so the single-frame model leaves them out.
// /api/health can replace this list when the model supports more letters.
const DEFAULT_LETTERS = ALPHABET.filter(
  letter => letter !== "J" && letter !== "Z"
);

let supportedLetters = new Set(DEFAULT_LETTERS);

const VOTE_WINDOW_MS = 800;
const HOLD_MS = 600;
const MIN_SHARE = 0.6;
const MIN_FRAMES = 3;

let recentVotes = [];
let lastSeenAt = 0;

function lettersSummary(letters) {
  const sorted = [...letters].sort();
  const missing = ALPHABET.filter(letter => !letters.has(letter));

  if (missing.length === 0) {
    return "all 26 letters";
  }

  if (sorted.length <= 8) {
    return sorted.join(", ");
  }

  return `${sorted.length} letters (all except ${missing.join(" and ")})`;
}

function lettersFromHealth(result) {
  if (!Array.isArray(result?.letters)) {
    return null;
  }

  const letters = new Set(
    result.letters.filter(
      letter => typeof letter === "string" && /^[A-Z]$/.test(letter)
    )
  );

  return letters.size > 0 ? letters : null;
}

let cameraStream = null;
let isStarting = false;
let transcript = "";
let currentLetter = "";
let generation = 0;
let recognitionTimer = null;
let activeRequest = null;
let modelCheckId = 0;

// Update visible text only when its value changes.
function setText(element, value) {
  if (element.textContent !== value) {
    element.textContent = value;
  }
}

function setDisabled(element, disabled) {
  if (element.disabled !== disabled) {
    element.disabled = disabled;
  }
}

function updateTranscript() {
  setText(
    transcriptDisplay,
    transcript || "No translation yet"
  );

  setDisabled(addLetterButton, !currentLetter);

  setDisabled(
    addSpaceButton,
    !transcript || transcript.endsWith(" ")
  );

  setDisabled(deleteLastButton, !transcript);
  setDisabled(clearTextButton, !transcript);
}

function updateCameraButtons() {
  setDisabled(
    startButton,
    isStarting || cameraStream !== null
  );

  setDisabled(
    stopButton,
    !isStarting && cameraStream === null
  );
}

function resetRecognition(message = "Waiting for camera") {
  currentLetter = "";
  recentVotes = [];
  lastSeenAt = 0;

  setText(detectedLetter, "—");
  setText(confidenceText, "Recognition confidence: —");
  setText(recognitionStatus, message);

  updateTranscript();
}

// Pick the letter to show from the last VOTE_WINDOW_MS of responses instead
// of reacting to every frame. One blurry or uncertain frame no longer blanks or
// flips the letter. Tuned for the five requests per second sent below; the
// standalone webcam uses the same rule (StablePrediction in ml/asl_model.py).
function updateVotes(letter, confidence, now) {
  recentVotes.push({ time: now, letter, confidence });

  while (recentVotes[0].time <= now - VOTE_WINDOW_MS) {
    recentVotes.shift();
  }

  const weights = new Map();
  const counts = new Map();

  for (const vote of recentVotes) {
    if (vote.letter) {
      weights.set(vote.letter, (weights.get(vote.letter) || 0) + vote.confidence);
      counts.set(vote.letter, (counts.get(vote.letter) || 0) + 1);
    }
  }

  let leader = "";
  let total = 0;

  for (const [candidate, weight] of weights) {
    total += weight;

    if (!leader || weight > weights.get(leader)) {
      leader = candidate;
    }
  }

  // A letter locks in once the window is half full and the letter leads the
  // confidence-weighted vote and appears in at least half of the frames.
  const locked =
    leader !== "" &&
    now - recentVotes[0].time >= VOTE_WINDOW_MS / 2 &&
    weights.get(leader) / Math.max(total, 1e-9) >= MIN_SHARE &&
    counts.get(leader) >= Math.max(MIN_FRAMES, recentVotes.length / 2);

  if (locked && leader !== currentLetter) {
    currentLetter = leader;
    lastSeenAt = now;
  } else if (currentLetter && letter === currentLetter) {
    // The grace period counts from the last frame that showed the letter.
    lastSeenAt = now;
  }

  if (currentLetter && now - lastSeenAt > HOLD_MS) {
    currentLetter = "";
  }
}

function displayRecognitionResult(result, now = performance.now()) {
  const messages = {
    no_hand: "Show one hand to the camera",
    multiple_hands: "Please show only one hand",
    invalid_landmarks: "Hand unclear. Adjust your position",
    uncertain: "Sign uncertain. Hold the sign clearly and steady"
  };

  const validConfidence =
    typeof result?.confidence === "number" &&
    Number.isFinite(result.confidence) &&
    result.confidence >= 0 &&
    result.confidence <= 1;

  const isVote =
    result?.status === "recognized" &&
    supportedLetters.has(result?.letter) &&
    validConfidence;

  // Known non-letter outcomes and unsupported letters count as empty votes,
  // so a letter already shown survives them for up to HOLD_MS.
  const isEmptyVote =
    !isVote &&
    (Object.hasOwn(messages, result?.status ?? "") ||
      (result?.status === "recognized" &&
        typeof result?.letter === "string" &&
        validConfidence));

  if (!isVote && !isEmptyVote) {
    resetRecognition("No valid letter detected");
    return;
  }

  updateVotes(
    isVote ? result.letter : "",
    isVote ? result.confidence : 0,
    now
  );

  setText(detectedLetter, currentLetter || "—");

  setText(
    confidenceText,
    isVote
      ? `Recognition confidence: ${Math.round(result.confidence * 100)}%`
      : "Recognition confidence: —"
  );

  let status = "Hold the sign steady";

  if (!isVote) {
    status = messages[result.status] || "No valid letter detected";
  } else if (currentLetter) {
    status = "Letter ready. Click Add Letter";
  }

  setText(recognitionStatus, status);

  updateTranscript();
}

async function checkModel() {
  const checkId = ++modelCheckId;
  const controller = new AbortController();

  const timeout = setTimeout(
    () => controller.abort(),
    5000
  );

  setText(modelStatus, "Checking recognition model…");

  try {
    const response = await fetch("/api/health", {
      signal: controller.signal,
      cache: "no-store"
    });

    const result = await response.json();

    if (!response.ok || !result?.ready) {
      throw new Error(
        result?.error || "Recognition model unavailable."
      );
    }

    if (checkId === modelCheckId) {
      supportedLetters = lettersFromHealth(result) || supportedLetters;

      setText(
        modelStatus,
        `Model ready: ${lettersSummary(supportedLetters)}`
      );
    }
  } catch (error) {
    if (checkId === modelCheckId) {
      setText(
        modelStatus,
        error.name === "AbortError"
          ? "Model check timed out. Start the camera to retry."
          : "Model unavailable. Check the recognition server."
      );
    }
  } finally {
    clearTimeout(timeout);
  }
}

async function recognizeFrame(session) {
  if (session !== generation || !cameraStream) {
    return;
  }

  const started = performance.now();

  let retryDelay = 0;
  let timeout = null;
  let controller = null;

  try {
    if (
      !camera.videoWidth ||
      !camera.videoHeight ||
      camera.readyState < 2
    ) {
      recognitionTimer = setTimeout(
        () => recognizeFrame(session),
        200
      );

      return;
    }

    const scale = Math.min(
      1,
      640 / Math.max(camera.videoWidth, camera.videoHeight)
    );

    canvas.width = Math.max(
      1,
      Math.round(camera.videoWidth * scale)
    );

    canvas.height = Math.max(
      1,
      Math.round(camera.videoHeight * scale)
    );

    context.drawImage(
      camera,
      0,
      0,
      canvas.width,
      canvas.height
    );

    const blob = await new Promise(resolve =>
      canvas.toBlob(resolve, "image/jpeg", 0.85)
    );

    if (session !== generation || !cameraStream) {
      return;
    }

    if (!blob) {
      throw new Error("Unable to capture camera frame.");
    }

    const form = new FormData();
    form.append("file", blob, "frame.jpg");

    controller = new AbortController();
    activeRequest = controller;

    timeout = setTimeout(
      () => controller.abort(),
      5000
    );

    const response = await fetch("/api/predict", {
      method: "POST",
      body: form,
      signal: controller.signal
    });

    const result = await response.json();

    if (session !== generation || !cameraStream) {
      return;
    }

    if (!response.ok) {
      throw new Error(
        result?.error || "Recognition service unavailable."
      );
    }

    modelCheckId++;

    setText(errorMessage, "");
    setText(modelStatus, modelReadyMessage);

    displayRecognitionResult(result);
  } catch (error) {
    if (session !== generation || !cameraStream) {
      return;
    }

    modelCheckId++;

    resetRecognition("Recognition unavailable. Retrying…");

    setText(
      modelStatus,
      "Recognition service unavailable"
    );

    setText(
      errorMessage,
      error.name === "AbortError"
        ? "Recognition timed out. Retrying…"
        : error instanceof TypeError
          ? "Cannot reach the recognition server. Retrying…"
          : "Recognition failed. Retrying…"
    );

    retryDelay = 2000;
  } finally {
    clearTimeout(timeout);

    if (activeRequest === controller) {
      activeRequest = null;
    }
  }

  if (session === generation && cameraStream) {
    recognitionTimer = setTimeout(
      () => recognizeFrame(session),
      retryDelay ||
        Math.max(0, 200 - (performance.now() - started))
    );
  }
}

function stopCamera() {
  generation++;

  clearTimeout(recognitionTimer);
  recognitionTimer = null;

  activeRequest?.abort();
  activeRequest = null;

  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });

    cameraStream = null;
  }

  camera.srcObject = null;
  cameraPlaceholder.style.display = "block";

  setText(cameraStatus, "Camera Off");

  resetRecognition();

  setDisabled(startButton, isStarting);
  setDisabled(stopButton, true);
}

startButton.addEventListener("click", async () => {
  if (cameraStream || isStarting) {
    return;
  }

  isStarting = true;

  const session = ++generation;

  updateCameraButtons();

  setText(errorMessage, "");
  setText(cameraStatus, "Starting Camera…");

  resetRecognition("Waiting for camera access");

  checkModel();

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera API unavailable");
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "user",
        width: { ideal: 640 },
        height: { ideal: 480 }
      },
      audio: false
    });

    if (session !== generation) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }

    cameraStream = stream;
    camera.srcObject = stream;

    stream.getVideoTracks().forEach(track => {
      track.onended = () => {
        if (session !== generation) {
          return;
        }

        stopCamera();

        setText(
          errorMessage,
          "Camera connection ended. Start the camera again."
        );
      };
    });

    await camera.play();

    if (session !== generation) {
      return;
    }

    cameraPlaceholder.style.display = "none";

    setText(cameraStatus, "Camera Active");

    resetRecognition("Looking for a sign…");

    recognizeFrame(session);
  } catch (error) {
    if (session !== generation) {
      return;
    }

    stopCamera();

    setText(cameraStatus, "Camera Error");

    const messages = {
      NotAllowedError:
        "Camera access denied. Allow access in browser settings.",

      NotFoundError:
        "No webcam was detected.",

      NotReadableError:
        "Your webcam is unavailable or being used by another app.",

      OverconstrainedError:
        "The camera does not support the requested settings.",

      SecurityError:
        "Camera access is blocked by browser security settings."
    };

    setText(
      errorMessage,
      messages[error.name] ||
        "Unable to start the camera. Use localhost or HTTPS and check permissions."
    );

    setText(recognitionStatus, "Camera unavailable");
  } finally {
    isStarting = false;
    updateCameraButtons();
  }
});

stopButton.addEventListener("click", () => {
  stopCamera();

  setText(errorMessage, "");

  setText(
    transcriptStatus,
    transcript
      ? "Camera stopped. Your transcript is preserved."
      : "Camera stopped. Start again to translate."
  );
});

addLetterButton.addEventListener("click", () => {
  if (!currentLetter) {
    return;
  }

  transcript += currentLetter;

  setText(
    transcriptStatus,
    `Added ${currentLetter} to transcript`
  );

  updateTranscript();
});

addSpaceButton.addEventListener("click", () => {
  if (!transcript || transcript.endsWith(" ")) {
    return;
  }

  transcript += " ";

  setText(transcriptStatus, "Space added");

  updateTranscript();
});

deleteLastButton.addEventListener("click", () => {
  if (!transcript) {
    return;
  }

  transcript = transcript.slice(0, -1);

  setText(
    transcriptStatus,
    "Last character deleted"
  );

  updateTranscript();
});

clearTextButton.addEventListener("click", () => {
  transcript = "";

  setText(transcriptStatus, "Transcript cleared");

  updateTranscript();
});

resetSessionButton.addEventListener("click", () => {
  stopCamera();

  transcript = "";

  setText(
    transcriptStatus,
    "Session reset. Start the camera to translate again."
  );

  setText(errorMessage, "");

  updateTranscript();
});

window.addEventListener("pagehide", stopCamera);

resetRecognition();

setText(cameraStatus, "Camera Off");

updateCameraButtons();
checkModel();
