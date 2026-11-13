
import unittest
from backend.translator import Translator


class TestIndependentSessions(unittest.TestCase):

    def test_two_sessions_are_independent(self):
        user_a = Translator()
        user_b = Translator()

        user_a.add_letter("A")
        user_b.add_letter("B")

        self.assertEqual(user_a.get_transcript(), "A")
        self.assertEqual(user_b.get_transcript(), "B")

        user_a.reset()

        self.assertEqual(user_a.get_transcript(), "")
        self.assertEqual(user_b.get_transcript(), "B")


if __name__ == "__main__":
    unittest.main()

