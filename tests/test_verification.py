import hashlib
import unittest

from verification import codes_match, make_verification_code


class VerificationTests(unittest.TestCase):
    def test_code_matches_requested_concat_formula(self):
        expected = hashlib.md5("I240part1part2".encode()).hexdigest()
        self.assertEqual(make_verification_code("I240", "part1", "part2"), expected)

    def test_code_comparison_is_case_insensitive_and_trimmed(self):
        self.assertTrue(codes_match("ABC123", " abc123 "))
        self.assertFalse(codes_match("ABC123", "ABC124"))


if __name__ == "__main__":
    unittest.main()

