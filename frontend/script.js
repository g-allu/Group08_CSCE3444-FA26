
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

const supportedLetters = new Set(["A", "B", "C", "L", "Y"]);
const modelReadyMessage = "Model ready: A, B, C, L, Y";

let cameraStream = null;
let isStarting = false;
let transcript = "";
let currentLetter = "";
let previousLetter = "";
let consecutivePredictions = 0;
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
  previousLetter = "";
  consecutivePredictions = 0;

  setText(detectedLetter, "—");
  setText(confidenceText, "Recognition confidence: —");
  setText(recognitionStatus, message);

  updateTranscript();
}

function displayRecognitionResult(result) {
  const messages = {
    no_hand: "Show one hand to the camera",
    multiple_hands: "Please show only one hand",
    invalid_landmarks: "Hand unclear. Adjust your position",
    uncertain: "Sign uncertain. Hold A, B, C, L, or Y clearly"
  };

  const validConfidence =
    typeof result?.confidence === "number" &&
    Number.isFinite(result.confidence) &&
    result.confidence >= 0 &&
    result.confidence <= 1;

  if (
    result?.status !== "recognized" ||
    !supportedLetters.has(result?.letter) ||
    !validConfidence
  ) {
    const message = Object.hasOwn(
      messages,
      result?.status
    )
      ? messages[result.status]
      : "No valid letter detected";

    resetRecognition(message);
    return;
  }

  if (result.letter === previousLetter) {
    consecutivePredictions = Math.min(
      consecutivePredictions + 1,
      2
    );
  } else {
    consecutivePredictions = 1;
  }

  previousLetter = result.letter;

  currentLetter =
    consecutivePredictions >= 2 ? result.letter : "";

  setText(detectedLetter, currentLetter || "—");

  setText(
    confidenceText,
    `Recognition confidence: ${Math.round(result.confidence * 100)}%`
  );

  setText(
    recognitionStatus,
    currentLetter
      ? "Letter ready. Click Add Letter"
      : "Hold the sign steady"
  );

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
      setText(modelStatus, modelReadyMessage);
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
