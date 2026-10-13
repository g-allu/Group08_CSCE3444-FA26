
// ASL Translator - Group 08
// The Thinkers
// F-01: Camera Access
// F-02: Recognition Results Interface

// --------------------------------------
// HTML Elements
// --------------------------------------

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

// --------------------------------------
// Application State
// --------------------------------------

let cameraStream = null;
let isStarting = false;

// --------------------------------------
// Camera Status
// --------------------------------------

function updateCameraStatus(message) {
  cameraStatus.textContent = message;
}

// --------------------------------------
// Reset Recognition Results
// --------------------------------------

function resetRecognition() {
  detectedLetter.textContent = "—";

  confidenceText.textContent =
    "Recognition confidence: —";

  demoLetter.value = "";
  testRecognition.disabled = true;

  recognitionStatus.textContent =
    "Waiting for camera";
}

// --------------------------------------
// Enable Recognition Demo Controls
// --------------------------------------

function updateRecognitionControls() {
  const cameraActive = cameraStream !== null;

  const letterSelected = demoLetter.value !== "";

  testRecognition.disabled =
    !cameraActive || !letterSelected;
}

// --------------------------------------
// Display Recognition Result
// --------------------------------------

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

    detectedLetter.textContent = "—";

    recognitionStatus.textContent =
      "No valid letter detected";

    confidenceText.textContent =
      "Recognition confidence: —";

    return;
  }

  detectedLetter.textContent = letter;

  recognitionStatus.textContent =
    "Simulated recognition result received";

  if (
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    confidence >= 0 &&
    confidence <= 1
  ) {

    const percentage = Math.round(confidence * 100);

    confidenceText.textContent =
      `Recognition confidence: ${percentage}%`;

  } else {

    confidenceText.textContent =
      "Recognition confidence: Not available";

  }
}

// --------------------------------------
// Stop Camera
// --------------------------------------

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
}

// --------------------------------------
// Start Camera
// --------------------------------------

startButton.addEventListener("click", async () => {

  if (cameraStream || isStarting) {
    return;
  }

  isStarting = true;

  startButton.disabled = true;

  errorMessage.textContent = "";

  updateCameraStatus("Starting Camera...");

  recognitionStatus.textContent =
    "Waiting for camera access";

  try {

    if (!navigator.mediaDevices?.getUserMedia) {

      throw new Error(
        "Camera access is not supported in this context."
      );
    }

    const stream =
      await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false
      });

    cameraStream = stream;

    camera.srcObject = stream;

    await camera.play();

    // Handle camera disconnection or browser interruption.
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
        "Camera permission denied. Please allow camera access in your browser settings.";

    } else if (error.name === "NotFoundError") {

      errorMessage.textContent =
        "No webcam was detected on this device.";

    } else if (error.name === "NotReadableError") {

      errorMessage.textContent =
        "The webcam is already in use or cannot be accessed.";

    } else {

      errorMessage.textContent =
        "Unable to start the camera. Check your connection and browser permissions.";
    }

    recognitionStatus.textContent =
      "Camera unavailable";

  } finally {

    isStarting = false;
  }
});

// --------------------------------------
// Stop Camera Button
// --------------------------------------

stopButton.addEventListener("click", () => {

  stopCamera();

  errorMessage.textContent = "";
});

// --------------------------------------
// Demo Letter Dropdown
// --------------------------------------

demoLetter.addEventListener("change", () => {

  updateRecognitionControls();
});

// --------------------------------------
// Demo Recognition Button
// --------------------------------------

testRecognition.addEventListener("click", () => {

  const selectedLetter = demoLetter.value;

  if (!selectedLetter) {

    recognitionStatus.textContent =
      "Please select a letter";

    return;
  }

  if (!cameraStream) {

    recognitionStatus.textContent =
      "Please start the camera first";

    return;
  }

  // Simulated result for frontend testing.
  // Replace this input with the backend result
  // when ASL recognition integration is ready.

  displayRecognitionResult(selectedLetter);
});

// --------------------------------------
// Clean Up Camera On Page Exit
// --------------------------------------

window.addEventListener("pagehide", () => {

  if (cameraStream) {

    cameraStream.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });

    cameraStream = null;
  }
});

// --------------------------------------
// Initial Page State
// --------------------------------------

resetRecognition();

updateCameraStatus("Camera Off");

startButton.disabled = false;
stopButton.disabled = true;
