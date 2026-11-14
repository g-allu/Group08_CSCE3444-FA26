
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  setup,
  recognize,
  sendFrame
} = require("./frontend.test.cjs");

const {
  initializeExport
} = require("../transcript-export.js");

function createButton() {
  let listener;

  return {
    disabled: true,
    textContent: "",

    addEventListener(event, callback) {
      if (event === "click") {
        listener = callback;
      }
    },

    click() {
      if (!this.disabled) {
        return listener?.();
      }
    }
  };
}

// Connect the actual application script and export module
// inside one simulated browser environment.

function setupIntegration() {
  const app = setup();

  const elements = app.elements;

  elements.copyTranscript = createButton();
  elements.downloadTranscript = createButton();

  elements.transcriptCount = {
    textContent: ""
  };

  elements.exportStatus = {
    textContent: ""
  };

  const copied = [];
  const downloads = [];
  const revoked = [];

  let observerCallback;
  let downloadedBlob;

  const pendingTimers = [];

  // Observe transcript updates made by the application.

  const descriptor = Object.getOwnPropertyDescriptor(
    elements.transcript,
    "textContent"
  );

  Object.defineProperty(elements.transcript, "textContent", {
    configurable: true,

    get() {
      return descriptor.get.call(this);
    },

    set(value) {
      descriptor.set.call(this, value);

      observerCallback?.();
    }
  });

  const env = {
    document: {
      getElementById(id) {
        return elements[id] || null;
      },

      body: {
        appendChild(link) {
          link.attached = true;
        }
      },

      createElement() {
        return {
          style: {},
          attached: false,

          click() {
            downloads.push({
              name: this.download,
              href: this.href
            });
          },

          remove() {
            this.attached = false;
          }
        };
      }
    },

    navigator: {
      clipboard: {
        async writeText(text) {
          copied.push(text);
        }
      }
    },

    Blob,

    URL: {
      createObjectURL(blob) {
        downloadedBlob = blob;

        return "blob:integration-test";
      },

      revokeObjectURL(url) {
        revoked.push(url);
      }
    },

    setTimeout(callback) {
      pendingTimers.push(callback);
    },

    MutationObserver: class {
      constructor(callback) {
        observerCallback = callback;
      }

      observe() {}
    }
  };

  initializeExport(env);

  function flushTimers() {
    while (pendingTimers.length) {
      pendingTimers.shift()();
    }
  }

  return {
    ...app,
    copied,
    downloads,
    revoked,

    getDownloadedBlob() {
      return downloadedBlob;
    },

    flushTimers
  };
}

// TEST 1: Full translation and editing workflow.

test("Camera recognition and editing build a transcript", async () => {
  const {
    elements: e,
    sandbox,
    stream
  } = setupIntegration();

  await e.startCamera.click();

  assert.equal(
    e.cameraStatus.textContent,
    "Camera Active"
  );

  recognize(sandbox, "A");
  e.addLetter.click();

  recognize(sandbox, "B");
  e.addLetter.click();

  e.addSpace.click();

  recognize(sandbox, "C");
  e.addLetter.click();

  recognize(sandbox, "Y");
  e.addLetter.click();

  assert.equal(
    e.transcript.textContent,
    "AB CY"
  );

  e.deleteLast.click();

  assert.equal(
    e.transcript.textContent,
    "AB C"
  );

  assert.equal(
    e.transcriptCount.textContent,
    "4 characters · 2 words"
  );

  e.stopCamera.click();

  assert.equal(stream.track.stopped, true);

  assert.equal(
    e.transcript.textContent,
    "AB C"
  );

  assert.equal(
    e.copyTranscript.disabled,
    false
  );
});

// TEST 2: Copy and download actual application output.

test("Copy and download preserve the generated transcript", async () => {
  const app = setupIntegration();

  const {
    elements: e,
    sandbox,
    copied,
    downloads
  } = app;

  await e.startCamera.click();

  for (const letter of ["B", "A", "L", "L"]) {
    recognize(sandbox, letter);
    e.addLetter.click();
  }

  e.addSpace.click();

  for (const letter of ["B", "A", "B", "Y"]) {
    recognize(sandbox, letter);
    e.addLetter.click();
  }

  e.stopCamera.click();

  assert.equal(
    e.transcript.textContent,
    "BALL BABY"
  );

  await e.copyTranscript.click();

  assert.deepEqual(
    copied,
    ["BALL BABY"]
  );

  e.downloadTranscript.click();

  assert.equal(
    downloads[0].name,
    "asl-transcript.txt"
  );

  assert.equal(
    await app.getDownloadedBlob().text(),
    "BALL BABY"
  );

  app.flushTimers();

  assert.deepEqual(
    app.revoked,
    ["blob:integration-test"]
  );
});

// TEST 3: Reset updates both editing and export controls.

test("Reset clears translation and disables export", async () => {
  const {
    elements: e,
    sandbox,
    stream
  } = setupIntegration();

  await e.startCamera.click();

  recognize(sandbox, "Y");

  e.addLetter.click();

  assert.equal(
    e.copyTranscript.disabled,
    false
  );

  await e.copyTranscript.click();

  e.resetSession.click();

  assert.equal(
    e.cameraStatus.textContent,
    "Camera Off"
  );

  assert.equal(stream.track.stopped, true);

  assert.equal(
    e.transcript.textContent,
    "No translation yet"
  );

  assert.equal(
    e.transcriptCount.textContent,
    "0 characters · 0 words"
  );

  assert.equal(e.addLetter.disabled, true);
  assert.equal(e.deleteLast.disabled, true);
  assert.equal(e.copyTranscript.disabled, true);
  assert.equal(e.downloadTranscript.disabled, true);
  assert.equal(e.exportStatus.textContent, "");
});

// TEST 4: Uncertain recognition must not modify the transcript.

test("Invalid recognition preserves existing translation", async () => {
  const {
    elements: e,
    sandbox
  } = setupIntegration();

  await e.startCamera.click();

  recognize(sandbox, "A");
  e.addLetter.click();

  // Keep the hand away longer than the 600 ms hold.
  for (let frame = 0; frame < 4; frame++) {
    sendFrame(sandbox, { status: "no_hand" });
  }

  e.addLetter.click();

  assert.equal(
    e.transcript.textContent,
    "A"
  );

  assert.equal(e.addLetter.disabled, true);

  assert.equal(
    e.copyTranscript.disabled,
    false
  );

  sandbox.displayRecognitionResult({
    status: "recognized",
    letter: "Z",
    confidence: 0.99
  });

  e.addLetter.click();

  assert.equal(
    e.transcript.textContent,
    "A"
  );

  e.stopCamera.click();
});

// TEST 5: Clearing text updates the export counter.

test("Clearing the transcript disables saving controls", () => {
  const {
    elements: e,
    sandbox
  } = setupIntegration();

  recognize(sandbox, "C");
  e.addLetter.click();

  assert.equal(
    e.transcriptCount.textContent,
    "1 characters · 1 words"
  );

  e.clearText.click();

  assert.equal(
    e.transcript.textContent,
    "No translation yet"
  );

  assert.equal(
    e.transcriptCount.textContent,
    "0 characters · 0 words"
  );

  assert.equal(e.copyTranscript.disabled, true);
  assert.equal(e.downloadTranscript.disabled, true);
});
