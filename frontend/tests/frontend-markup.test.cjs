
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// Read the application's actual frontend files.

const html = fs.readFileSync(
  path.join(__dirname, "../index.html"),
  "utf8"
);

const javascript = fs.readFileSync(
  path.join(__dirname, "../script.js"),
  "utf8"
);

const css = fs.readFileSync(
  path.join(__dirname, "../style.css"),
  "utf8"
);

// Find all HTML element IDs.

const ids = Array.from(
  html.matchAll(/\bid\s*=\s*["']([^"']+)["']/g),
  match => match[1]
);

function findElement(id) {
  const tags = html.match(/<[a-z][^>]*>/gi) || [];

  return tags.find(tag => {
    const match = tag.match(
      /\bid\s*=\s*["']([^"']+)["']/
    );

    return match && match[1] === id;
  });
}

// TEST 1: IDs must be unique.

test("HTML element IDs are unique", () => {
  const uniqueIds = new Set(ids);

  assert.equal(
    uniqueIds.size,
    ids.length,
    "Duplicate HTML IDs were found"
  );
});

// TEST 2: All JavaScript element references must exist.

test("All JavaScript control IDs exist in HTML", () => {
  const references = Array.from(
    javascript.matchAll(
      /getElementById\(["']([^"']+)["']\)/g
    ),
    match => match[1]
  );

  assert.ok(references.length > 0);

  for (const id of references) {
    assert.ok(
      ids.includes(id),
      `Missing HTML element: ${id}`
    );
  }
});

// TEST 3: Buttons must have the correct type and initial state.

test("Camera and transcript buttons have correct markup", () => {
  const buttonIds = [
    "startCamera",
    "stopCamera",
    "addLetter",
    "addSpace",
    "deleteLast",
    "clearText",
    "resetSession"
  ];

  const initiallyDisabled = [
    "stopCamera",
    "addLetter",
    "addSpace",
    "deleteLast",
    "clearText"
  ];

  for (const id of buttonIds) {
    const tag = findElement(id);

    assert.ok(tag, `Missing button: ${id}`);

    assert.match(
      tag,
      /^<button\b/i,
      `${id} must be a button`
    );

    assert.match(
      tag,
      /\btype=["']button["']/,
      `${id} must use type="button"`
    );

    assert.equal(
      /\bdisabled\b/.test(tag),
      initiallyDisabled.includes(id),
      `${id} has an incorrect initial state`
    );
  }
});

// TEST 4: Accessibility references must point to existing IDs.

test("ARIA labels and descriptions reference valid elements", () => {
  const references = html.matchAll(
    /\baria-(?:labelledby|describedby)\s*=\s*["']([^"']+)["']/g
  );

  for (const match of references) {
    const targets = match[1].trim().split(/\s+/);

    for (const target of targets) {
      assert.ok(
        ids.includes(target),
        `Invalid ARIA reference: ${target}`
      );
    }
  }

  const video = findElement("camera");

  assert.match(video, /\baria-label=["'][^"']+["']/);
  assert.match(video, /\bplaysinline\b/);
});

// TEST 5: Live regions and error messages must be identifiable.

test("Recognition and transcript updates have accessible status markup", () => {
  const statusIds = [
    "cameraStatus",
    "modelStatus",
    "recognitionStatus",
    "transcriptStatus"
  ];

  for (const id of statusIds) {
    const tag = findElement(id);

    assert.ok(tag, `Missing status element: ${id}`);

    assert.match(
      tag,
      /\brole=["']status["']/,
      `${id} must expose a status role`
    );
  }

  const transcript = findElement("transcript");
  const detectedLetter = findElement("detectedLetter");
  const error = findElement("errorMessage");

  assert.match(
    transcript,
    /\baria-live=["']polite["']/
  );

  assert.match(
    detectedLetter,
    /\baria-live=["']polite["']/
  );

  assert.match(
    error,
    /\brole=["']alert["']/
  );
});

// TEST 6: Keyboard navigation and frontend assets.

test("Keyboard navigation and frontend assets are present", () => {
  assert.match(
    html,
    /<a\b[^>]*href=["']#mainContent["'][^>]*>/i
  );

  const main = findElement("mainContent");

  assert.ok(main);
  assert.match(main, /^<main\b/i);
  assert.match(main, /\btabindex=["']-1["']/);

  assert.match(
    css,
    /\.skip-link:focus\s*\{/
  );

  assert.match(
    css,
    /button:focus-visible/
  );

  assert.match(
    html,
    /<link\b[^>]*href=["']style\.css["'][^>]*>/i
  );

  assert.match(
    html,
    /<script\b[^>]*src=["']script\.js["'][^>]*>/i
  );

  assert.match(
    html,
    /<html\b[^>]*lang=["']en["'][^>]*>/i
  );

  assert.match(
    html,
    /name=["']viewport["']/
  );
});
