import unittest

from email_validation import parse_student_email


class EmailValidationTests(unittest.TestCase):
    def test_accepts_both_domains_and_suffix_cases(self):
        self.assertEqual(
            parse_student_email("12347001S@gapps.ntnu.edu.tw"),
            ("12347001", "12347001s@gapps.ntnu.edu.tw"),
        )
        self.assertEqual(
            parse_student_email("98747999s@ntnu.edu.tw"),
            ("98747999", "98747999s@ntnu.edu.tw"),
        )

    def test_rejects_wrong_student_number_or_domain(self):
        self.assertIsNone(parse_student_email("12346001s@gapps.ntnu.edu.tw"))
        self.assertIsNone(parse_student_email("12347001@gapps.ntnu.edu.tw"))
        self.assertIsNone(parse_student_email("12347001s@example.com"))


if __name__ == "__main__":
    unittest.main()

