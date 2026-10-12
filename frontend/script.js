
const camera = document.getElementById("camera");
const startButton = document.getElementById("startCamera");
const stopButton = document.getElementById("stopCamera");
const cameraStatus = document.getElementById("cameraStatus");
const cameraPlaceholder = document.getElementById("cameraPlaceholder");
const errorMessage = document.getElementById("errorMessage");

let cameraStream = null;
let isStarting = false;

function updateStatus(message) {
  cameraStatus.textContent = message;
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }

  camera.srcObject = null;
  cameraPlaceholder.style.display = "block";

  startButton.disabled = false;
  stopButton.disabled = true;

  updateStatus("Camera Off");
}

startButton.addEventListener("click", async () => {
  if (cameraStream || isStarting) return;

  isStarting = true;
  startButton.disabled = true;
  errorMessage.textContent = "";

  updateStatus("Starting Camera...");

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera API is unavailable.");
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false
    });

    cameraStream = stream;
    camera.srcObject = stream;

    await camera.play();

    cameraPlaceholder.style.display = "none";
    stopButton.disabled = false;

    updateStatus("Camera Active");

  } catch (error) {
    console.error("Camera error:", error);

    stopCamera();

    if (error.name === "NotAllowedError") {
      errorMessage.textContent =
        "Camera permission denied. Allow camera access in your browser settings.";
    } else if (error.name === "NotFoundError") {
      errorMessage.textContent =
        "No webcam was detected on this device.";
    } else {
      errorMessage.textContent =
        "Unable to start the camera. Check your device and try again.";
    }

  } finally {
    isStarting = false;
  }
});

stopButton.addEventListener("click", () => {
  stopCamera();
  errorMessage.textContent = "";
});

window.addEventListener("pagehide", () => {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
  }
});
