
"""Translation history with persistent JSON storage for each session."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class TranslationHistory:
    def __init__(self, max_entries=100, storage_path=None):
        self.max_entries = max_entries
        self.storage_path = Path(
            storage_path or Path(__file__).resolve().parent / "translation_history.json"
        )
        self._history = {}
        self._load()

    def _load(self):
        if not self.storage_path.exists():
            return

        try:
            with self.storage_path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                raise ValueError("Invalid history file")

            self._history = {
                session_id: entries[:self.max_entries]
                for session_id, entries in data.items()
                if isinstance(session_id, str) and isinstance(entries, list)
            }
        except (OSError, json.JSONDecodeError, ValueError):
            raise RuntimeError(
                f"Could not load translation history: {self.storage_path}"
            )

    def _persist(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = self.storage_path.with_name(
            self.storage_path.name + f".{uuid4().hex}.tmp"
        )

        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(self._history, file, indent=2, ensure_ascii=False)

            os.replace(temporary_path, self.storage_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def save(self, session_id, transcript):
        """Save a non-empty translation for one session."""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("A session ID is required")

        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError("Cannot save an empty translation")

        entry = {
            "id": str(uuid4()),
            "transcript": transcript.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        entries = self._history.setdefault(session_id, [])
        entries.insert(0, entry)

        if len(entries) > self.max_entries:
            del entries[self.max_entries:]

        self._persist()
        return entry.copy()

    def list_history(self, session_id):
        """Return saved translations for one session."""
        return [
            entry.copy()
            for entry in self._history.get(session_id, [])
        ]

    def delete(self, session_id, entry_id):
        """Delete one saved translation."""
        entries = self._history.get(session_id, [])

        for index, entry in enumerate(entries):
            if entry["id"] == entry_id:
                entries.pop(index)
                self._persist()
                return True

        return False

    def clear(self, session_id):
        """Remove all saved translations for one session."""
        self._history.pop(session_id, None)
        self._persist()

