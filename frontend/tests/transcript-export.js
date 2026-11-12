
(function () {
  "use strict";

  const emptyMessage = "No translation yet";

  // Return the actual transcript instead of placeholder text.
  function getTranscript(value) {
    const text = String(value ?? "");

    if (!text.trim() || text.trim() === emptyMessage) {
      return "";
    }

    return text;
  }

  // Calculate transcript length and word count.
  function getStatistics(value) {
    const text = getTranscript(value);

    return {
      characters: text.length,
      words: text ? text.trim().split(/\s+/).length : 0
    };
  }

  // Copy the transcript to the device clipboard.
  async function copyTranscript(value, clipboard) {
    const text = getTranscript(value);

    if (!text) {
      throw new Error("There is no transcript to copy.");
    }

    if (typeof clipboard?.writeText !== "function") {
      throw new Error("Clipboard access is unavailable.");
    }

    await clipboard.writeText(text);

    return text;
  }

  // Download the transcript as a plain text file.
  function downloadTranscript(value, env) {
    const text = getTranscript(value);

    if (!text) {
      throw new Error("There is no transcript to download.");
    }

    const blob = new env.Blob([text], {
      type: "text/plain;charset=utf-8"
    });

    const url = env.URL.createObjectURL(blob);

    let link;

    try {
      link = env.document.createElement("a");
      link.href = url;
      link.download = "asl-transcript.txt";
      link.style.display = "none";

      env.document.body.appendChild(link);

      link.click();
    } finally {
      link?.remove();

      env.setTimeout(() => {
        env.URL.revokeObjectURL(url);
      }, 1000);
    }

    return text;
  }

  // Connect export functionality to the application.
  function initializeExport(env) {
    const doc = env.document;

    const transcript = doc.getElementById("transcript");
    const copy = doc.getElementById("copyTranscript");
    const download = doc.getElementById("downloadTranscript");
    const count = doc.getElementById("transcriptCount");
    const status = doc.getElementById("exportStatus");

    if (
      !transcript ||
      !copy ||
      !download ||
      !count ||
      !status
    ) {
      return null;
    }

    let lastText = null;
    let operation = 0;

    // Update the export controls whenever the transcript changes.
    function update() {
      const text = getTranscript(transcript.textContent);

      const stats = getStatistics(text);

      copy.disabled = !text;
      download.disabled = !text;

      count.textContent =
        `${stats.characters} characters · ${stats.words} words`;

      if (text !== lastText) {
        lastText = text;
        operation++;

        status.textContent = "";
      }
    }

    function report(message, id, text) {
      if (
        id === operation &&
        getTranscript(transcript.textContent) === text
      ) {
        status.textContent = message;
      }
    }

    copy.addEventListener("click", async () => {
      const text = getTranscript(transcript.textContent);

      if (!text) {
        return;
      }

      const id = ++operation;

      try {
        await copyTranscript(
          text,
          env.navigator.clipboard
        );

        report("Transcript copied.", id, text);
      } catch {
        report(
          "Copy unavailable. Select the transcript to copy it manually.",
          id,
          text
        );
      }
    });

    download.addEventListener("click", () => {
      const text = getTranscript(transcript.textContent);

      if (!text) {
        return;
      }

      const id = ++operation;

      try {
        downloadTranscript(text, env);

        report(
          "Transcript download requested.",
          id,
          text
        );
      } catch {
        report(
          "Unable to download. Please try again.",
          id,
          text
        );
      }
    });

    // Observe changes made by the existing transcript controls.
    const observer = new env.MutationObserver(update);

    observer.observe(transcript, {
      childList: true,
      characterData: true,
      subtree: true
    });

    update();

    return observer;
  }

  // Export functions for automated Node.js testing.
  if (
    typeof module !== "undefined" &&
    module.exports
  ) {
    module.exports = {
      getTranscript,
      getStatistics,
      copyTranscript,
      downloadTranscript,
      initializeExport
    };
  }

  // Initialize the module when running in a browser.
  if (
    typeof window !== "undefined" &&
    window.document
  ) {
    initializeExport(window);
  }

})();
