import unittest
from pathlib import Path

from database import VerificationDatabase


class VerificationDatabaseTests(unittest.TestCase):
    def test_email_request_and_pass_times_are_retained_after_session_cleanup(self):
        database = VerificationDatabase(Path(":memory:"))
        database.save_email_session(
            100,
            200,
            "10047s@ntnu.edu.tw",
            "10047001",
            "code",
            2000.0,
            requested_at=1000.0,
        )

        database.mark_verification_passed(100, "email", passed_at=1500.0)
        database.delete_email_session(100)

        record = database.connection.execute(
            "SELECT requested_at, passed_at FROM verification_records "
            "WHERE user_id = 100 AND method = 'email'"
        ).fetchone()
        self.assertEqual(tuple(record), (1000.0, 1500.0))

    def test_manual_session_exposes_request_time(self):
        database = VerificationDatabase(Path(":memory:"))
        database.save_manual_session(100, 200, requested_at=1234.0)

        session = database.get_manual_session(100)

        self.assertIsNotNone(session)
        self.assertEqual(session.requested_at, 1234.0)


if __name__ == "__main__":
    unittest.main()
