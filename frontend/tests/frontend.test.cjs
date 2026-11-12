
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Load the actual frontend JavaScript.

const source = fs.readFileSync(
  path.join(__dirname, "../frontend/script.js"),
  "utf8"
);

// Create a simulated browser element.

function createElement() {
  const listeners = new Map();

  return {
    textContent: "",
    disabled: false,
    style: {},
    srcObject: null,
    videoWidth: 0,
    videoHeight: 0,
    readyState: 0,

    addEventListener(event, callback) {
      listeners.set(event, callback);
    },

    click() {
      if (!this.disabled) {
        return listeners.get("click")?.();
      }
    },

    async play() {
      return undefined;
    }
  };
}

// Create a simulated webcam stream.

function createCameraStream() {
  const track = {
    stopped: false,
    onended: null,

    stop() {
      this.stopped = true;
    }
  };

  return {
    track,

    getTracks() {
      return [track];
    },

    getVideoTracks() {
      return [track];
    }
  };
}

// Create a controlled frontend testing environment.

function setup(options = {}) {
  const ids = [
    "camera",
    "startCamera",
    "stopCamera",
    "cameraStatus",
    "cameraPlaceholder",
    "errorMessage",
    "modelStatus",
    "detectedLetter",
    "recognitionStatus",
    "confidenceText",
    "transcript",
    "transcriptStatus",
    "addLetter",
    "addSpace",
    "deleteLast",
    "clearText",
    "resetSession"
  ];

  const elements = {};

  ids.forEach(id => {
    elements[id] = createElement();
  });

  const stream = createCameraStream();

  let timerId = 0;

  const sandbox = {
    document: {
      getElementById(id) {
        return elements[id];
      },

      createElement() {
        return {
          getContext() {
            return {};
          }
        };
      }
    },

    navigator: {
      mediaDevices: {
        getUserMedia:
          options.getUserMedia ||
          (async () => stream)
      }
    },

    window: {
      addEventListener() {}
    },

    fetch: async () => ({
      ok: true,

      async json() {
        return { ready: true };
      }
    }),

    AbortController,
    FormData,
    performance,
    console,

    setTimeout() {
      return ++timerId;
    },

    clearTimeout() {}
  };

  vm.createContext(sandbox);

  vm.runInContext(source, sandbox);

  return {
    elements,
    stream,
    sandbox
  };
}

// Simulate two consecutive predictions.

function recognize(sandbox, letter) {
  const result = {
    status: "recognized",
    letter,
    confidence: 0.95
  };

  sandbox.displayRecognitionResult(result);
  sandbox.displayRecognitionResult(result);
}

// TEST 1: Initial application state

test("Initial controls have correct states", () => {
  const { elements } = setup();

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Off"
  );

  assert.equal(
    elements.transcript.textContent,
    "No translation yet"
  );

  assert.equal(elements.startCamera.disabled, false);
  assert.equal(elements.stopCamera.disabled, true);
  assert.equal(elements.addLetter.disabled, true);
  assert.equal(elements.addSpace.disabled, true);
  assert.equal(elements.deleteLast.disabled, true);
  assert.equal(elements.clearText.disabled, true);
});

// TEST 2: Add a recognized letter

test("Recognized letter is added to transcript", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "A");

  elements.addLetter.click();

  assert.equal(
    elements.transcript.textContent,
    "A"
  );

  assert.equal(elements.addSpace.disabled, false);
  assert.equal(elements.deleteLast.disabled, false);
  assert.equal(elements.clearText.disabled, false);
});

// TEST 3: Add spaces between letters

test("Transcript supports spaces between letters", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "A");
  elements.addLetter.click();

  elements.addSpace.click();

  recognize(sandbox, "B");
  elements.addLetter.click();

  assert.equal(
    elements.transcript.textContent,
    "A B"
  );
});

// TEST 4: Prevent extra spaces

test("Leading and repeated spaces are prevented", () => {
  const { elements, sandbox } = setup();

  elements.addSpace.click();

  assert.equal(
    elements.transcript.textContent,
    "No translation yet"
  );

  recognize(sandbox, "A");

  elements.addLetter.click();
  elements.addSpace.click();
  elements.addSpace.click();

  assert.equal(
    elements.transcript.textContent,
    "A "
  );

  assert.equal(elements.addSpace.disabled, true);
});

// TEST 5: Delete the last character

test("Delete Last removes one character", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "A");
  elements.addLetter.click();

  recognize(sandbox, "B");
  elements.addLetter.click();

  elements.deleteLast.click();

  assert.equal(
    elements.transcript.textContent,
    "A"
  );
});

// TEST 6: Clear the transcript

test("Clear Transcript removes all text", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "C");

  elements.addLetter.click();
  elements.clearText.click();

  assert.equal(
    elements.transcript.textContent,
    "No translation yet"
  );

  assert.equal(elements.deleteLast.disabled, true);
  assert.equal(elements.clearText.disabled, true);
});

// TEST 7: Stable recognition is required

test("Letter requires two consecutive predictions", () => {
  const { elements, sandbox } = setup();

  sandbox.displayRecognitionResult({
    status: "recognized",
    letter: "L",
    confidence: 0.95
  });

  assert.equal(elements.addLetter.disabled, true);

  sandbox.displayRecognitionResult({
    status: "recognized",
    letter: "L",
    confidence: 0.95
  });

  assert.equal(elements.addLetter.disabled, false);

  assert.equal(
    elements.detectedLetter.textContent,
    "L"
  );
});

// TEST 8: Unsupported letters are rejected

test("Unsupported letters cannot be added", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "Z");

  elements.addLetter.click();

  assert.equal(elements.addLetter.disabled, true);

  assert.equal(
    elements.transcript.textContent,
    "No translation yet"
  );
});

// TEST 9: Invalid confidence is rejected

test("Invalid confidence does not enable Add Letter", () => {
  const { elements, sandbox } = setup();

  sandbox.displayRecognitionResult({
    status: "recognized",
    letter: "Y",
    confidence: 2
  });

  assert.equal(elements.addLetter.disabled, true);

  assert.equal(
    elements.detectedLetter.textContent,
    "—"
  );
});

// TEST 10: No-hand detection resets recognition

test("No hand disables the current letter", () => {
  const { elements, sandbox } = setup();

  recognize(sandbox, "Y");

  sandbox.displayRecognitionResult({
    status: "no_hand"
  });

  assert.equal(elements.addLetter.disabled, true);

  assert.equal(
    elements.recognitionStatus.textContent,
    "Show one hand to the camera"
  );
});

// TEST 11: Start and stop the camera

test("Camera starts and releases its tracks when stopped", async () => {
  const { elements, stream } = setup();

  await elements.startCamera.click();

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Active"
  );

  assert.equal(elements.startCamera.disabled, true);
  assert.equal(elements.stopCamera.disabled, false);

  elements.stopCamera.click();

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Off"
  );

  assert.equal(stream.track.stopped, true);
  assert.equal(elements.camera.srcObject, null);
});

// TEST 12: Camera stop preserves text

test("Stopping the camera preserves the transcript", async () => {
  const { elements, sandbox } = setup();

  await elements.startCamera.click();

  recognize(sandbox, "A");

  elements.addLetter.click();
  elements.stopCamera.click();

  assert.equal(
    elements.transcript.textContent,
    "A"
  );
});

// TEST 13: Reset the session

test("Reset Session stops camera and clears transcript", async () => {
  const { elements, stream, sandbox } = setup();

  await elements.startCamera.click();

  recognize(sandbox, "B");

  elements.addLetter.click();
  elements.resetSession.click();

  assert.equal(
    elements.transcript.textContent,
    "No translation yet"
  );

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Off"
  );

  assert.equal(stream.track.stopped, true);
  assert.equal(elements.addLetter.disabled, true);
});

// TEST 14: Camera permission denied

test("Camera permission denial is handled", async () => {
  const error = new Error("Permission denied");
  error.name = "NotAllowedError";

  const { elements } = setup({
    getUserMedia: async () => {
      throw error;
    }
  });

  await elements.startCamera.click();

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Error"
  );

  assert.match(
    elements.errorMessage.textContent,
    /Camera access denied/
  );

  assert.equal(elements.startCamera.disabled, false);
});

// TEST 15: Reset during pending camera permission

test("Reset safely cancels a pending camera request", async () => {
  let resolvePermission;

  const pendingPermission = new Promise(resolve => {
    resolvePermission = resolve;
  });

  const lateStream = createCameraStream();

  const { elements } = setup({
    getUserMedia: () => pendingPermission
  });

  const starting = elements.startCamera.click();

  elements.resetSession.click();

  assert.equal(elements.startCamera.disabled, true);

  resolvePermission(lateStream);

  await starting;

  assert.equal(lateStream.track.stopped, true);

  assert.equal(
    elements.cameraStatus.textContent,
    "Camera Off"
  );

  assert.equal(elements.camera.srcObject, null);
  assert.equal(elements.startCamera.disabled, false);
});
