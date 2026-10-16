// ASL Translator - Group 08
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
const clearTextButton = document.getElementById("clearText");
const canvas = document.createElement("canvas");
const context = canvas.getContext("2d");
const supportedLetters = new Set(["A", "B", "C", "L", "Y"]);

let cameraStream = null;
let isStarting = false;
let transcript = "";
let currentLetter = "";
let previousLetter = "";
let consecutivePredictions = 0;
let generation = 0;
let recognitionTimer = null;
let activeRequest = null;

function updateTranscript() {
  transcriptDisplay.textContent = transcript || "No translation yet";
  addLetterButton.disabled = currentLetter === "";
  clearTextButton.disabled = transcript.length === 0;
}

function resetRecognition(message = "Waiting for camera") {
  currentLetter = "";
  previousLetter = "";
  consecutivePredictions = 0;
  detectedLetter.textContent = "—";
  confidenceText.textContent = "Recognition confidence: —";
  recognitionStatus.textContent = message;
  updateTranscript();
}

function displayRecognitionResult(result) {
  const messages = {
    no_hand: "Show one hand to the camera",
    multiple_hands: "Please show only one hand",
    invalid_landmarks: "Hand unclear. Adjust your position",
    uncertain: "Sign uncertain. Hold A, B, C, L, or Y clearly"
  };
  const validConfidence = typeof result.confidence === "number" &&
    Number.isFinite(result.confidence) && result.confidence >= 0 && result.confidence <= 1;
  if (result.status !== "recognized" || !supportedLetters.has(result.letter) || !validConfidence) {
    resetRecognition(messages[result.status] || "No valid letter detected");
    return;
  }

  consecutivePredictions = result.letter === previousLetter ? consecutivePredictions + 1 : 1;
  previousLetter = result.letter;
  currentLetter = consecutivePredictions >= 2 ? result.letter : "";
  detectedLetter.textContent = currentLetter || "—";
  confidenceText.textContent = `Recognition confidence: ${Math.round(result.confidence * 100)}%`;
  recognitionStatus.textContent = currentLetter ? "Letter ready. Click Add Letter" : "Hold the sign steady";
  updateTranscript();
}

async function checkModel() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
    const result = await response.json();
    if (!response.ok || !result.ready) {
      throw new Error(result.error || "Model unavailable. Prepare model assets and restart Flask.");
    }
    modelStatus.textContent = "Model ready · A, B, C, L, Y";
  } catch (error) {
    modelStatus.textContent = error.name === "AbortError"
      ? "Model check timed out. Start the camera to retry."
      : error.message;
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
    if (!camera.videoWidth || !camera.videoHeight || camera.readyState < 2) {
      recognitionTimer = setTimeout(() => recognizeFrame(session), 200);
      return;
    }
    const scale = Math.min(1, 640 / Math.max(camera.videoWidth, camera.videoHeight));
    canvas.width = Math.max(1, Math.round(camera.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(camera.videoHeight * scale));
    // Capture original pixels; CSS preview mirroring must never affect inference.
    context.drawImage(camera, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (session !== generation || !cameraStream) {
      return;
    }
    if (!blob) {
      throw new Error("Unable to capture a camera frame. Please try again.");
    }
    const form = new FormData();
    form.append("file", blob, "frame.jpg");
    controller = new AbortController();
    activeRequest = controller;
    timeout = setTimeout(() => controller.abort(), 5000);
    const response = await fetch("/api/predict", { method: "POST", body: form, signal: controller.signal });
    const result = await response.json();
    if (session !== generation || !cameraStream) {
      return;
    }
    if (!response.ok) {
      throw new Error(result.error || "Recognition service unavailable. Retrying…");
    }
    errorMessage.textContent = "";
    modelStatus.textContent = "Model ready · A, B, C, L, Y";
    displayRecognitionResult(result);
  } catch (error) {
    if (session !== generation || !cameraStream) {
      return;
    }
    resetRecognition("Recognition unavailable. Retrying…");
    modelStatus.textContent = "Recognition service unavailable";
    errorMessage.textContent = error.name === "AbortError"
      ? "Recognition timed out. Retrying…"
      : error instanceof TypeError ? "Unable to reach the backend. Retrying…" : error.message;
    retryDelay = 2000;
  } finally {
    clearTimeout(timeout);
    if (activeRequest === controller) {
      activeRequest = null;
    }
  }
  if (session === generation && cameraStream) {
    recognitionTimer = setTimeout(() => recognizeFrame(session),
      retryDelay || Math.max(0, 200 - (performance.now() - started)));
  }
}

function stopCamera() {
  generation += 1;
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
  startButton.disabled = isStarting;
  stopButton.disabled = true;
  cameraStatus.textContent = "Camera Off";
  resetRecognition();
}

startButton.addEventListener("click", async () => {
  if (cameraStream || isStarting) {
    return;
  }
  isStarting = true;
  const session = ++generation;
  startButton.disabled = true;
  stopButton.disabled = false;
  errorMessage.textContent = "";
  cameraStatus.textContent = "Starting Camera…";
  resetRecognition("Waiting for camera access");
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera API unavailable");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    if (session !== generation) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    cameraStream = stream;
    camera.srcObject = stream;
    stream.getVideoTracks().forEach(track => {
      track.onended = () => {
        stopCamera();
        errorMessage.textContent = "Camera connection ended. Please try again.";
      };
    });
    await camera.play();
    if (session !== generation) {
      return;
    }
    cameraPlaceholder.style.display = "none";
    cameraStatus.textContent = "Camera Active";
    resetRecognition("Looking for a sign…");
    recognizeFrame(session);
  } catch (error) {
    if (session !== generation) {
      return;
    }
    stopCamera();
    cameraStatus.textContent = "Camera Error";
    const messages = {
      NotAllowedError: "Camera permission denied. Allow access in browser settings.",
      NotFoundError: "No webcam was detected.",
      NotReadableError: "Webcam is already in use or unavailable."
    };
    errorMessage.textContent = messages[error.name] || "Unable to start the camera. Open this app on localhost and try again.";
    recognitionStatus.textContent = "Camera unavailable";
  } finally {
    isStarting = false;
    startButton.disabled = cameraStream !== null;
    stopButton.disabled = cameraStream === null;
  }
});

stopButton.addEventListener("click", () => {
  stopCamera();
  errorMessage.textContent = "";
});

addLetterButton.addEventListener("click", () => {
  if (!currentLetter) {
    return;
  }
  transcript += currentLetter;
  transcriptStatus.textContent = `Added ${currentLetter} to transcript`;
  updateTranscript();
});

clearTextButton.addEventListener("click", () => {
  transcript = "";
  transcriptStatus.textContent = "Transcript cleared";
  updateTranscript();
});

window.addEventListener("pagehide", stopCamera);
resetRecognition();
cameraStatus.textContent = "Camera Off";
startButton.disabled = false;
stopButton.disabled = true;
checkModel();
