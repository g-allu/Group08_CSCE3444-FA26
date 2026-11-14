
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Load the actual application script.
const source = fs.readFileSync(
  path.join(__dirname, "../script.js"),
  "utf8"
);

function createElement() {
  const listeners = new Map();
  let text = "";

  return {
    disabled: false,
    style: {},
    srcObject: null,
    videoWidth: 0,
    videoHeight: 0,
    readyState: 0,
    textWrites: 0,

    get textContent() {
      return text;
    },

    set textContent(value) {
      text = value;
      this.textWrites++;
    },

    addEventListener(event, callback) {
      listeners.set(event, callback);
    },

    click() {
      if (!this.disabled) {
        return listeners.get("click")?.();
      }
    },

    async play() {}
  };
}

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

function setup(options = {}) {
  const ids = [
    "camera", "startCamera", "stopCamera",
    "cameraStatus", "cameraPlaceholder",
    "errorMessage", "modelStatus",
    "detectedLetter", "recognitionStatus",
    "confidenceText", "transcript",
    "transcriptStatus", "addLetter",
    "addSpace", "deleteLast",
    "clearText", "resetSession"
  ];

  const elements = {};

  ids.forEach(id => {
    elements[id] = createElement();
  });

  const stream = createCameraStream();
  const timers = new Map();
  const windowEvents = new Map();

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
      addEventListener(event, callback) {
        windowEvents.set(event, callback);
      }
    },

    fetch: options.fetch || (async () => ({
      ok: true,
      async json() {
        return { ready: true };
      }
    })),

    AbortController,
    FormData,
    performance: createClock(),
    console,

    setTimeout(callback, delay) {
      const id = ++timerId;
      timers.set(id, { callback, delay });
      return id;
    },

    clearTimeout(id) {
      timers.delete(id);
    }
  };

  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);

  return {
    elements,
    stream,
    sandbox,
    timers,
    windowEvents
  };
}

// Fake clock so recognition timing is deterministic. Tests move time forward
// with sandbox.performance.advance(ms).
function createClock() {
  let time = 0;

  return {
    now() {
      return time;
    },

    advance(ms) {
      time += ms;
      return time;
    }
  };
}

// The app sends a frame every 200 ms at most.
const FRAME_MS = 200;

// Send one response FRAME_MS after the previous one.
function sendFrame(sandbox, result) {
  sandbox.performance.advance(FRAME_MS);
  sandbox.displayRecognitionResult(result);
}

// Hold a letter long enough for the vote window to lock it in.
function recognize(sandbox, letter) {
  const result = {
    status: "recognized",
    letter,
    confidence: 0.95
  };

  for (let frame = 0; frame < 4; frame++) {
    sendFrame(sandbox, result);
  }
}

module.exports = {
  setup,
  recognize,
  sendFrame,
  FRAME_MS,
  createCameraStream
};

if (require.main === module) {

  test("Initial controls have correct states", () => {
    const { elements: e } = setup();

    assert.equal(e.cameraStatus.textContent, "Camera Off");
    assert.equal(e.transcript.textContent, "No translation yet");
    assert.equal(e.startCamera.disabled, false);
    assert.equal(e.stopCamera.disabled, true);
    assert.equal(e.addLetter.disabled, true);
    assert.equal(e.addSpace.disabled, true);
    assert.equal(e.deleteLast.disabled, true);
    assert.equal(e.clearText.disabled, true);
  });

  test("Recognized letter is added to transcript", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "A");
    e.addLetter.click();

    assert.equal(e.transcript.textContent, "A");
    assert.equal(e.addSpace.disabled, false);
    assert.equal(e.deleteLast.disabled, false);
    assert.equal(e.clearText.disabled, false);
  });

  test("Transcript supports spaces between letters", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "A");
    e.addLetter.click();
    e.addSpace.click();

    recognize(sandbox, "B");
    e.addLetter.click();

    assert.equal(e.transcript.textContent, "A B");
  });

  test("Leading and repeated spaces are prevented", () => {
    const { elements: e, sandbox } = setup();

    e.addSpace.click();
    assert.equal(e.transcript.textContent, "No translation yet");

    recognize(sandbox, "A");
    e.addLetter.click();
    e.addSpace.click();
    e.addSpace.click();

    assert.equal(e.transcript.textContent, "A ");
    assert.equal(e.addSpace.disabled, true);
  });

  test("Delete Last removes one character", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "A");
    e.addLetter.click();

    recognize(sandbox, "B");
    e.addLetter.click();

    e.deleteLast.click();

    assert.equal(e.transcript.textContent, "A");
  });

  test("Clear Transcript removes all text", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "C");
    e.addLetter.click();
    e.clearText.click();

    assert.equal(e.transcript.textContent, "No translation yet");
    assert.equal(e.deleteLast.disabled, true);
    assert.equal(e.clearText.disabled, true);
  });

  test("Letter locks in once the vote window agrees", () => {
    const { elements: e, sandbox } = setup();

    const result = {
      status: "recognized",
      letter: "L",
      confidence: 0.95
    };

    sendFrame(sandbox, result);
    sendFrame(sandbox, result);
    assert.equal(e.addLetter.disabled, true);
    assert.equal(e.recognitionStatus.textContent, "Hold the sign steady");

    // Third frame: the 800 ms window is half full, so L locks in.
    sendFrame(sandbox, result);
    assert.equal(e.addLetter.disabled, false);
    assert.equal(e.detectedLetter.textContent, "L");
  });

  test("Unsupported letters cannot be added", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "Z");
    e.addLetter.click();

    assert.equal(e.addLetter.disabled, true);
    assert.equal(e.transcript.textContent, "No translation yet");
  });

  test("Invalid confidence is rejected", () => {
    const { elements: e, sandbox } = setup();

    sandbox.displayRecognitionResult({
      status: "recognized",
      letter: "Y",
      confidence: 2
    });

    assert.equal(e.addLetter.disabled, true);
    assert.equal(e.detectedLetter.textContent, "—");
  });

  test("No hand disables the current letter after the hold period", () => {
    const { elements: e, sandbox } = setup();

    recognize(sandbox, "Y");

    for (let frame = 0; frame < 4; frame++) {
      sendFrame(sandbox, { status: "no_hand" });
    }

    assert.equal(e.addLetter.disabled, true);
    assert.equal(
      e.recognitionStatus.textContent,
      "Show one hand to the camera"
    );
  });

  test("Camera starts and releases tracks when stopped", async () => {
    const { elements: e, stream } = setup();

    await e.startCamera.click();

    assert.equal(e.cameraStatus.textContent, "Camera Active");
    assert.equal(e.startCamera.disabled, true);
    assert.equal(e.stopCamera.disabled, false);

    e.stopCamera.click();

    assert.equal(e.cameraStatus.textContent, "Camera Off");
    assert.equal(stream.track.stopped, true);
    assert.equal(e.camera.srcObject, null);
  });

  test("Stopping camera preserves the transcript", async () => {
    const { elements: e, sandbox } = setup();

    await e.startCamera.click();

    recognize(sandbox, "A");
    e.addLetter.click();
    e.stopCamera.click();

    assert.equal(e.transcript.textContent, "A");
  });

  test("Reset Session stops camera and clears transcript", async () => {
    const { elements: e, sandbox, stream } = setup();

    await e.startCamera.click();

    recognize(sandbox, "B");
    e.addLetter.click();
    e.resetSession.click();

    assert.equal(e.transcript.textContent, "No translation yet");
    assert.equal(e.cameraStatus.textContent, "Camera Off");
    assert.equal(stream.track.stopped, true);
    assert.equal(e.addLetter.disabled, true);
  });

  test("Camera permission denial is handled", async () => {
    const error = new Error("Permission denied");
    error.name = "NotAllowedError";

    const { elements: e } = setup({
      getUserMedia: async () => {
        throw error;
      }
    });

    await e.startCamera.click();

    assert.equal(e.cameraStatus.textContent, "Camera Error");
    assert.match(e.errorMessage.textContent, /Camera access denied/);
    assert.equal(e.startCamera.disabled, false);
  });

  test("Reset cancels a pending camera request", async () => {
    let resolvePermission;

    const pending = new Promise(resolve => {
      resolvePermission = resolve;
    });

    const lateStream = createCameraStream();

    const { elements: e } = setup({
      getUserMedia: () => pending
    });

    const starting = e.startCamera.click();

    e.resetSession.click();

    assert.equal(e.startCamera.disabled, true);

    resolvePermission(lateStream);
    await starting;

    assert.equal(lateStream.track.stopped, true);
    assert.equal(e.cameraStatus.textContent, "Camera Off");
    assert.equal(e.camera.srcObject, null);
    assert.equal(e.startCamera.disabled, false);
  });
}
