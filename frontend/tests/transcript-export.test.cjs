
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  getTranscript,
  getStatistics,
  copyTranscript,
  downloadTranscript,
  initializeExport
} = require("../transcript-export.js");

// Create a simulated browser environment.

function createEnvironment(options = {}) {
  const elements = {};

  const ids = [
    "transcript",
    "copyTranscript",
    "downloadTranscript",
    "transcriptCount",
    "exportStatus"
  ];

  for (const id of ids) {
    const listeners = new Map();

    elements[id] = {
      textContent: "",
      disabled: true,

      addEventListener(event, callback) {
        listeners.set(event, callback);
      },

      click() {
        if (!this.disabled) {
          return listeners.get("click")?.();
        }
      }
    };
  }

  elements.transcript.textContent =
    "No translation yet";

  const downloads = [];
  const revoked = [];
  const copied = [];
  const pendingTimers = [];

  let observer;

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
        const link = {
          style: {},
          attached: false,

          click() {
            if (options.downloadError) {
              throw new Error("Blocked");
            }

            downloads.push({
              name: this.download,
              href: this.href
            });
          },

          remove() {
            this.attached = false;
          }
        };

        env.lastLink = link;

        return link;
      }
    },

    navigator: {
      clipboard: options.clipboard || {
        async writeText(text) {
          copied.push(text);
        }
      }
    },

    Blob,

    URL: {
      createObjectURL(blob) {
        env.lastBlob = blob;

        return "blob:transcript-test";
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
        observer = callback;
      }

      observe() {}
    }
  };

  function changeTranscript(text) {
    elements.transcript.textContent = text;

    observer?.();
  }

  function flushTimers() {
    while (pendingTimers.length) {
      pendingTimers.shift()();
    }
  }

  return {
    env,
    elements,
    copied,
    downloads,
    revoked,
    changeTranscript,
    flushTimers
  };
}

// TEST 1: Empty transcript handling.

test("Empty transcript and placeholder text are excluded", () => {
  const values = [
    null,
    undefined,
    "",
    "  ",
    "No translation yet"
  ];

  for (const value of values) {
    assert.equal(getTranscript(value), "");

    assert.deepEqual(getStatistics(value), {
      characters: 0,
      words: 0
    });
  }
});

// TEST 2: Transcript statistics.

test("Transcript preserves letters and spacing", () => {
  assert.equal(
    getTranscript("ABC LY "),
    "ABC LY "
  );

  assert.deepEqual(
    getStatistics("ABC LY "),
    {
      characters: 7,
      words: 2
    }
  );
});

// TEST 3: Copy exact text.

test("Copy passes exact transcript to clipboard", async () => {
  const { env, copied } = createEnvironment();

  await copyTranscript(
    "ABC LY",
    env.navigator.clipboard
  );

  assert.deepEqual(copied, ["ABC LY"]);
});

// TEST 4: Copy validation.

test("Copy rejects empty transcript and missing clipboard", async () => {
  await assert.rejects(
    copyTranscript("", {}),
    /no transcript/i
  );

  await assert.rejects(
    copyTranscript("ABC", undefined),
    /clipboard/i
  );
});

// TEST 5: Text file contents and cleanup.

test("Download contains exact text and releases temporary URL", async () => {
  const {
    env,
    downloads,
    revoked,
    flushTimers
  } = createEnvironment();

  downloadTranscript("ABC LY ", env);

  assert.equal(
    await env.lastBlob.text(),
    "ABC LY "
  );

  assert.match(
    env.lastBlob.type,
    /^text\/plain/
  );

  assert.deepEqual(downloads, [
    {
      name: "asl-transcript.txt",
      href: "blob:transcript-test"
    }
  ]);

  assert.equal(
    env.lastLink.attached,
    false
  );

  flushTimers();

  assert.deepEqual(
    revoked,
    ["blob:transcript-test"]
  );
});

// TEST 6: Empty transcript download.

test("Download refuses empty transcript", () => {
  const { env, downloads } =
    createEnvironment();

  assert.throws(
    () => downloadTranscript(
      "No translation yet",
      env
    ),
    /no transcript/i
  );

  assert.equal(downloads.length, 0);
});

// TEST 7: Enable and disable export controls.

test("Export controls follow transcript changes and reset", () => {
  const {
    env,
    elements: e,
    changeTranscript
  } = createEnvironment();

  initializeExport(env);

  assert.equal(e.copyTranscript.disabled, true);
  assert.equal(e.downloadTranscript.disabled, true);

  changeTranscript("ABC LY");

  assert.equal(e.copyTranscript.disabled, false);
  assert.equal(e.downloadTranscript.disabled, false);

  assert.equal(
    e.transcriptCount.textContent,
    "6 characters · 2 words"
  );

  changeTranscript("No translation yet");

  assert.equal(e.copyTranscript.disabled, true);
  assert.equal(e.downloadTranscript.disabled, true);

  assert.equal(
    e.transcriptCount.textContent,
    "0 characters · 0 words"
  );
});

// TEST 8: Export button feedback.

test("Copy and download buttons provide feedback", async () => {
  const {
    env,
    elements: e,
    copied,
    downloads,
    changeTranscript
  } = createEnvironment();

  initializeExport(env);

  changeTranscript("ABC");

  await e.copyTranscript.click();

  assert.deepEqual(copied, ["ABC"]);

  assert.equal(
    e.exportStatus.textContent,
    "Transcript copied."
  );

  e.downloadTranscript.click();

  assert.equal(downloads.length, 1);

  assert.equal(
    e.exportStatus.textContent,
    "Transcript download requested."
  );
});

// TEST 9: Clipboard permission failure.

test("Clipboard failure provides manual copy guidance", async () => {
  const {
    env,
    elements: e,
    changeTranscript
  } = createEnvironment({
    clipboard: {
      async writeText() {
        throw new Error("Permission denied");
      }
    }
  });

  initializeExport(env);

  changeTranscript("ABC");

  await e.copyTranscript.click();

  assert.match(
    e.exportStatus.textContent,
    /copy it manually/i
  );
});

// TEST 10: Reset while copying.

test("Reset suppresses stale clipboard feedback", async () => {
  let finishCopy;

  const pending = new Promise(resolve => {
    finishCopy = resolve;
  });

  const {
    env,
    elements: e,
    changeTranscript
  } = createEnvironment({
    clipboard: {
      writeText: () => pending
    }
  });

  initializeExport(env);

  changeTranscript("ABC");

  const copying = e.copyTranscript.click();

  changeTranscript("No translation yet");

  finishCopy();

  await copying;

  assert.equal(
    e.exportStatus.textContent,
    ""
  );

  assert.equal(
    e.copyTranscript.disabled,
    true
  );
});

// TEST 11: Download failure and cleanup.

test("Download failure cleans up and displays an error", () => {
  const {
    env,
    elements: e,
    revoked,
    changeTranscript,
    flushTimers
  } = createEnvironment({
    downloadError: true
  });

  initializeExport(env);

  changeTranscript("ABC");

  e.downloadTranscript.click();

  assert.match(
    e.exportStatus.textContent,
    /unable to download/i
  );

  assert.equal(
    env.lastLink.attached,
    false
  );

  flushTimers();

  assert.deepEqual(
    revoked,
    ["blob:transcript-test"]
  );
});
