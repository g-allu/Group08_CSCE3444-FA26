

# ASL Translator - Group 08
# Backend: FR-07, FR-08, FR-09

class Translator:
    def __init__(self):
        self.transcript = ""

    # FR-07: Add recognized letter
    def add_letter(self, letter):
        if not isinstance(letter, str):
            return None

        letter = letter.upper()

        if len(letter) != 1 or not letter.isascii() or not letter.isalpha():
            return None

        self.transcript += letter
        return self.transcript

    # FR-07: Add space between words
    def add_space(self):
        if self.transcript and not self.transcript.endswith(" "):
            self.transcript += " "
        return self.transcript

    # FR-08: Delete last character
    def delete_last(self):
        self.transcript = self.transcript[:-1]
        return self.transcript

    # FR-09: Reset session
    def reset(self):
        self.transcript = ""
        return self.transcript

    def get_transcript(self):
        return self.transcript
