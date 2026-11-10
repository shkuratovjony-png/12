"""Static SQL and input tests for isolated admin reporting."""
from datetime import datetime, timezone
import unittest
import admin_insights


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def query(self, sql, args=()):
        self.calls.append((sql, args))
        # No server, network, payment processor or personal data required.
        return [{"n": 0, "total": 0, "men": 0, "women": 0,
                 "completed": 0, "without_profile": 0,
                 "delivered": 0, "recipients": 0, "orders": 0,
                 "buyers": 0, "revenue_kopecks": 0,
                 "accrued_kopecks": 0, "paid_kopecks": 0,
                 "requested_kopecks": 0, "available_kopecks": 0,
                 "hold_kopecks": 0}]

    def test_snapshot_only_reads_and_binds_search(self):
        result = admin_insights.snapshot(
            self.query, datetime(2026,11,1,tzinfo=timezone.utc),
            {"insights_page": 1, "insights_search": "@ja'ne"})
        self.assertEqual(result["total"], 0)
        self.assertEqual(len(self.calls), 12)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql, _ in self.calls))
        for sql, args in self.calls:
            self.assertEqual(sql.count("%s"), len(args))
            self.assertNotIn("ja'ne", sql)
        self.assertTrue(any("%ja'ne%" in args for _, args in self.calls))

    def test_invalid_page_fails_before_database(self):
        for value in ("0","not-a-page", -10, 10001):
            with self.assertRaises(ValueError):
                admin_insights.snapshot(self.query, datetime.now(timezone.utc),
                                        {"insights_page": value})
        self.assertEqual(self.calls, [])


if __name__=="__main__":
    unittest.main()
