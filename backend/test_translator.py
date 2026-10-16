
import unittest
from translator import Translator


class TestTranslator(unittest.TestCase):

    def setUp(self):
        self.translator = Translator()

    def test_add_letter(self):
        self.assertEqual(self.translator.add_letter("H"), "H")
        self.assertEqual(self.translator.add_letter("I"), "HI")

    def test_add_space(self):
        self.translator.add_letter("H")
        self.assertEqual(self.translator.add_space(), "H ")

    def test_delete_last(self):
        self.translator.add_letter("H")
        self.translator.add_letter("I")
        self.assertEqual(self.translator.delete_last(), "H")

    def test_reset(self):
        self.translator.add_letter("A")
        self.assertEqual(self.translator.reset(), "")

    def test_invalid_letter(self):
        self.assertIsNone(self.translator.add_letter("123"))


if __name__ == "__main__":
    unittest.main()
