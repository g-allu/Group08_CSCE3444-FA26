
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  setup,
  recognize,
  createCameraStream
} = require("./frontend.test.cjs");

function prediction(letter, confidence = 0.95) {
  return {
    status: "recognized",
    letter,
    confidence
  };
}

// TEST 1: All currently supported ASL letters.

const STATIC_LETTERS = "ABCDEFGHIKLMNOPQRSTUVWXY";

test("All 24 static letters can be added", () => {
  const { elements: e, sandbox } = setup();

  for (const letter of STATIC_LETTERS) {
    recognize(sandbox, letter);
    e.addLetter.click();
  }

  assert.equal(e.transcript.textContent, STATIC_LETTERS);
});

test("Motion letters J and Z cannot be added", () => {
  const { elements: e, sandbox } = setup();

  for (const letter of ["J", "Z"]) {
    recognize(sandbox, letter);
    e.addLetter.click();
  }

  assert.equal(e.transcript.textContent, "No translation yet");
});

test("Health letters replace the default list and ignore bad entries", async () => {
  const { elements: e, sandbox } = setup({
    fetch: async () => ({
      ok: true,

      async json() {
        return { ready: true, letters: ["A", "B", "j", "ZZ", 7, "Z"] };
      }
    })
  });

  await sandbox.checkModel();

  assert.equal(e.modelStatus.textContent, "Model ready: A, B, Z");

  recognize(sandbox, "Z");
  e.addLetter.click();
  recognize(sandbox, "C");
  e.addLetter.click();

  assert.equal(e.transcript.textContent, "Z");
});

test("Health without a usable letter list keeps the default letters", async () => {
  const { elements: e, sandbox } = setup({
    fetch: async () => ({
      ok: true,

      async json() {
        return { ready: true, letters: ["?", ""] };
      }
    })
  });

  await sandbox.checkModel();

  assert.equal(
    e.modelStatus.textContent,
    "Model ready: 24 letters (all except J and Z)"
  );
});

// TEST 2: Repeated predictions should not rewrite live regions.

test("Stable recognition does not repeat unchanged announcements", () => {
  const { elements: e, sandbox } = setup();

  recognize(sandbox, "A");

  const initialLetterWrites = e.detectedLetter.textWrites;
  const initialStatusWrites = e.recognitionStatus.textWrites;
  const initialTranscriptWrites = e.transcript.textWrites;
  const initialConfidenceWrites = e.confidenceText.textWrites;

  for (let i = 0; i < 10; i++) {
    sandbox.displayRecognitionResult(
      prediction("A")
    );
  }

  assert.equal(
    e.detectedLetter.textWrites,
    initialLetterWrites
  );

  assert.equal(
    e.recognitionStatus.textWrites,
    initialStatusWrites
  );

  assert.equal(
    e.transcript.textWrites,
    initialTranscriptWrites
  );

  assert.equal(
    e.confidenceText.textWrites,
    initialConfidenceWrites
  );
});

// TEST 3: Different letters require fresh confirmation.

test("A different prediction requires two matching frames", () => {
  const { elements: e, sandbox } = setup();

  recognize(sandbox, "A");

  assert.equal(e.addLetter.disabled, false);

  sandbox.displayRecognitionResult(
    prediction("B")
  );

  assert.equal(e.addLetter.disabled, true);
  assert.equal(e.detectedLetter.textContent, "—");

  sandbox.displayRecognitionResult(
    prediction("B")
  );

  assert.equal(e.addLetter.disabled, false);
  assert.equal(e.detectedLetter.textContent, "B");
});

// TEST 4: No-hand detection clears previous recognition.

test("Removing the hand resets prediction stability", () => {
  const { elements: e, sandbox } = setup();

  recognize(sandbox, "C");

  sandbox.displayRecognitionResult({
    status: "no_hand"
  });

  sandbox.displayRecognitionResult(
    prediction("C")
  );

  assert.equal(e.addLetter.disabled, true);

  sandbox.displayRecognitionResult(
    prediction("C")
  );

  assert.equal(e.addLetter.disabled, false);
  assert.equal(e.detectedLetter.textContent, "C");
});

// TEST 5: Recognition handles empty or malformed responses.

test("Malformed prediction responses are rejected safely", () => {
  const { elements: e, sandbox } = setup();

  recognize(sandbox, "L");

  for (const result of [
    null,
    undefined,
    {},
    { status: "recognized" },
    { status: "recognized", letter: "L", confidence: "0.95" },
    { status: "recognized", letter: "L", confidence: NaN },
    { status: "recognized", letter: "L", confidence: -1 }
  ]) {
    assert.doesNotThrow(() => {
      sandbox.displayRecognitionResult(result);
    });

    assert.equal(e.addLetter.disabled, true);
    assert.equal(e.detectedLetter.textContent, "—");
  }
});

// TEST 6: Recognition handles multiple hands.

test("Multiple hands produce helpful feedback", () => {
  const { elements: e, sandbox } = setup();

  sandbox.displayRecognitionResult({
    status: "multiple_hands"
  });

  assert.equal(
    e.recognitionStatus.textContent,
    "Please show only one hand"
  );

  assert.equal(e.addLetter.disabled, true);
});

// TEST 7: Camera disconnection releases resources.

test("Camera disconnection stops recognition safely", async () => {
  const { elements: e, stream } = setup();

  await e.startCamera.click();

  const disconnect = stream.track.onended;

  assert.equal(typeof disconnect, "function");

  disconnect();

  assert.equal(e.cameraStatus.textContent, "Camera Off");
  assert.equal(e.camera.srcObject, null);
  assert.equal(stream.track.stopped, true);
  assert.equal(e.startCamera.disabled, false);
  assert.equal(e.stopCamera.disabled, true);

  assert.match(
    e.errorMessage.textContent,
    /Camera connection ended/
  );
});

// TEST 8: Camera stops when leaving the page.

test("Leaving the page releases the camera", async () => {
  const {
    elements: e,
    stream,
    windowEvents,
    sandbox
  } = setup();

  await e.startCamera.click();

  recognize(sandbox, "Y");
  e.addLetter.click();

  const pagehide = windowEvents.get("pagehide");

  assert.equal(typeof pagehide, "function");

  pagehide();

  assert.equal(e.cameraStatus.textContent, "Camera Off");
  assert.equal(stream.track.stopped, true);
  assert.equal(e.camera.srcObject, null);
  assert.equal(e.transcript.textContent, "Y");
});

// TEST 9: Restarting camera creates a fresh session.

test("Camera can restart without reusing a stopped stream", async () => {
  const firstStream = createCameraStream();
  const secondStream = createCameraStream();

  let requests = 0;

  const { elements: e } = setup({
    getUserMedia: async () => {
      requests++;
      return requests === 1
        ? firstStream
        : secondStream;
    }
  });

  await e.startCamera.click();

  assert.equal(e.camera.srcObject, firstStream);

  e.stopCamera.click();

  assert.equal(firstStream.track.stopped, true);

  await e.startCamera.click();

  assert.equal(requests, 2);
  assert.equal(e.camera.srcObject, secondStream);
  assert.equal(secondStream.track.stopped, false);

  e.stopCamera.click();

  assert.equal(secondStream.track.stopped, true);
});

// TEST 10: Older model checks cannot overwrite newer results.

test("Stale model status responses are ignored", async () => {
  let resolveFirst;
  let requests = 0;

  const firstResponse = new Promise(resolve => {
    resolveFirst = resolve;
  });

  const { elements: e, sandbox } = setup({
    fetch: async () => {
      requests++;

      if (requests === 1) {
        return firstResponse;
      }

      return {
        ok: true,

        async json() {
          return { ready: true };
        }
      };
    }
  });

  await sandbox.checkModel();

  assert.equal(
    e.modelStatus.textContent,
    "Model ready: 24 letters (all except J and Z)"
  );

  resolveFirst({
    ok: false,

    async json() {
      return { ready: false };
    }
  });

  await new Promise(resolve => setImmediate(resolve));

  assert.equal(
    e.modelStatus.textContent,
    "Model ready: 24 letters (all except J and Z)"
  );
});
