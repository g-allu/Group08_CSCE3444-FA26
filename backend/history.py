
"""Translation history for individual ASL Translator sessions."""

from datetime import datetime, timezone
from uuid import uuid4


class TranslationHistory:
    def __init__(self, max_entries=100):
        self.max_entries = max_entries
        self._history = {}

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
                return True

        return False

    def clear(self, session_id):
        """Remove all saved translations for one session."""
        self._history.pop(session_id, None)

