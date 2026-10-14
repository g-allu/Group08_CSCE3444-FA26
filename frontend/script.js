
// ASL Translator - Group 08
// The Thinkers
// F-01: Camera Access
// F-02: Recognition Results
// F-03: Translation Transcript

// ----------------------------------
// HTML Elements
// ----------------------------------

const camera = document.getElementById("camera");
const startButton = document.getElementById("startCamera");
const stopButton = document.getElementById("stopCamera");
const cameraStatus = document.getElementById("cameraStatus");
const cameraPlaceholder = document.getElementById("cameraPlaceholder");
const errorMessage = document.getElementById("errorMessage");

const detectedLetter = document.getElementById("detectedLetter");
const recognitionStatus = document.getElementById("recognitionStatus");
const confidenceText = document.getElementById("confidenceText");
const demoLetter = document.getElementById("demoLetter");
const testRecognition = document.getElementById("testRecognition");

const transcriptDisplay = document.getElementById("transcript");
const transcriptStatus = document.getElementById("transcriptStatus");

const addLetterButton = document.getElementById("addLetter");
const addSpaceButton = document.getElementById("addSpace");
const deleteLastButton = document.getElementById("deleteLast");
const clearTextButton = document.getElementById("clearText");
const resetSessionButton = document.getElementById("resetSession");

// ----------------------------------
// Application State
// ----------------------------------

let cameraStream = null;
let isStarting = false;
let transcript = "";
let currentLetter = "";

// ----------------------------------
// Camera and Recognition Status
// ----------------------------------

function updateCameraStatus(message) {
  cameraStatus.textContent = message;
}

function resetRecognition() {
  currentLetter = "";
  detectedLetter.textContent = "—";
  confidenceText.textContent = "Recognition confidence: —";
  recognitionStatus.textContent = "Waiting for camera";

  demoLetter.value = "";
  testRecognition.disabled = true;

  updateTranscriptControls();
}

function updateRecognitionControls() {
  const cameraActive = cameraStream !== null;

  testRecognition.disabled =
    !cameraActive || demoLetter.value === "";
}

// ----------------------------------
// Transcript Display and Buttons
// ----------------------------------

function updateTranscriptDisplay() {
  transcriptDisplay.textContent =
    transcript.length > 0 ? transcript : "No translation yet";

  updateTranscriptControls();
}

function updateTranscriptControls() {
  addLetterButton.disabled = currentLetter === "";

  addSpaceButton.disabled =
    transcript.length === 0 || transcript.endsWith(" ");

  deleteLastButton.disabled = transcript.length === 0;
  clearTextButton.disabled = transcript.length === 0;
}

function addLetterToTranscript() {
  if (!currentLetter) {
    transcriptStatus.textContent =
      "Select and test a letter first.";
    return;
  }

  transcript += currentLetter;
  updateTranscriptDisplay();

  transcriptStatus.textContent =
    `Added ${currentLetter} to transcript`;
}

function addSpaceToTranscript() {
  if (transcript.length === 0 || transcript.endsWith(" ")) {
    return;
  }

  transcript += " ";
  updateTranscriptDisplay();

  transcriptStatus.textContent = "Space added";
}

function deleteLastCharacter() {
  if (transcript.length === 0) {
    return;
  }

  transcript = transcript.slice(0, -1);
  updateTranscriptDisplay();

  transcriptStatus.textContent =
    "Last character removed";
}

function clearTranscript() {
  transcript = "";
  updateTranscriptDisplay();

  transcriptStatus.textContent = "Transcript cleared";
}

function resetSession() {
  transcript = "";
  resetRecognition();
  updateTranscriptDisplay();

  recognitionStatus.textContent = cameraStream
    ? "Camera ready - select a demo letter"
    : "Waiting for camera";

  transcriptStatus.textContent =
    "Session reset. You can start a new translation.";
}

// ----------------------------------
// Display Recognition Result
// ----------------------------------

function displayRecognitionResult(letter, confidence = null) {
  if (!cameraStream) {
    recognitionStatus.textContent =
      "Please start the camera first";
    return;
  }

  const validLetter =
    typeof letter === "string" &&
    /^[A-Z]$/.test(letter);

  if (!validLetter) {
    currentLetter = "";
    detectedLetter.textContent = "—";
    recognitionStatus.textContent = "No valid letter detected";
    confidenceText.textContent = "Recognition confidence: —";
    updateTranscriptControls();
    return;
  }

  currentLetter = letter;
  detectedLetter.textContent = letter;

  recognitionStatus.textContent =
    "Simulated recognition result received";

  if (
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    confidence >= 0 &&
    confidence <= 1
  ) {
    confidenceText.textContent =
      `Recognition confidence: ${Math.round(confidence * 100)}%`;
  } else {
    confidenceText.textContent =
      "Recognition confidence: Not available";
  }

  updateTranscriptControls();
}

// ----------------------------------
// Stop Camera
// ----------------------------------

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });

    cameraStream = null;
  }

  camera.srcObject = null;
  cameraPlaceholder.style.display = "block";

  startButton.disabled = false;
  stopButton.disabled = true;

  updateCameraStatus("Camera Off");
  resetRecognition();

  // Preserve text when the camera is stopped.
  // The transcript is cleared only by the user.
}

// ----------------------------------
// Start Camera
// ----------------------------------

startButton.addEventListener("click", async () => {
  if (cameraStream || isStarting) {
    return;
  }

  isStarting = true;
  startButton.disabled = true;
  errorMessage.textContent = "";

  updateCameraStatus("Starting Camera...");
  recognitionStatus.textContent = "Waiting for camera access";

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera API unavailable");
    }

    const stream =
      await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false
      });

    cameraStream = stream;
    camera.srcObject = stream;

    await camera.play();

    const videoTrack = stream.getVideoTracks()[0];

    if (videoTrack) {
      videoTrack.onended = () => {
        stopCamera();
        errorMessage.textContent =
          "Camera connection ended. Please try again.";
      };
    }

    cameraPlaceholder.style.display = "none";
    startButton.disabled = true;
    stopButton.disabled = false;

    updateCameraStatus("Camera Active");
    recognitionStatus.textContent =
      "Camera ready - select a demo letter";

    updateRecognitionControls();
  } catch (error) {
    console.error("Camera error:", error);
    stopCamera();

    updateCameraStatus("Camera Error");

    if (error.name === "NotAllowedError") {
      errorMessage.textContent =
        "Camera permission denied. Allow access in browser settings.";
    } else if (error.name === "NotFoundError") {
      errorMessage.textContent =
        "No webcam was detected.";
    } else if (error.name === "NotReadableError") {
      errorMessage.textContent =
        "Webcam is already in use or unavailable.";
    } else {
      errorMessage.textContent =
        "Unable to start the camera. Please try again.";
    }

    recognitionStatus.textContent = "Camera unavailable";
  } finally {
    isStarting = false;
  }
});

// ----------------------------------
// Stop Camera Button
// ----------------------------------

stopButton.addEventListener("click", () => {
  stopCamera();
  errorMessage.textContent = "";
});

// ----------------------------------
// Simulated Recognition Controls
// ----------------------------------

demoLetter.addEventListener("change", () => {
  // A selection must be tested before it can be added.
  currentLetter = "";
  detectedLetter.textContent = "—";
  confidenceText.textContent = "Recognition confidence: —";

  recognitionStatus.textContent = cameraStream
    ? "Click Test Result to display this letter"
    : "Start camera first";

  updateRecognitionControls();
  updateTranscriptControls();
});

testRecognition.addEventListener("click", () => {
  if (!cameraStream) {
    recognitionStatus.textContent = "Start camera first";
    return;
  }

  displayRecognitionResult(demoLetter.value);
});

// ----------------------------------
// Transcript Button Events
// ----------------------------------

addLetterButton.addEventListener(
  "click",
  addLetterToTranscript
);

addSpaceButton.addEventListener(
  "click",
  addSpaceToTranscript
);

deleteLastButton.addEventListener(
  "click",
  deleteLastCharacter
);

clearTextButton.addEventListener(
  "click",
  clearTranscript
);

resetSessionButton.addEventListener(
  "click",
  resetSession
);

// ----------------------------------
// Stop Camera When Page Closes
// ----------------------------------

window.addEventListener("pagehide", () => {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });

    cameraStream = null;
  }
});

// ----------------------------------
// Initialize Application
// ----------------------------------

resetRecognition();
updateCameraStatus("Camera Off");
updateTranscriptDisplay();

startButton.disabled = false;
stopButton.disabled = true;
