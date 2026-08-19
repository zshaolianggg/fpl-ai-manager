import unittest
from datetime import datetime, timezone
from fpl_ai_manager.analyzer import classify_window

NOW = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)

class WindowTests(unittest.TestCase):
    def test_preview_window(self):
        kind, hours = classify_window("2026-08-20T08:00:00Z", (23,25), (2,3.5), NOW)
        self.assertEqual(kind, "preview")
        self.assertEqual(hours, 24)

    def test_final_window(self):
        kind, _ = classify_window("2026-08-19T11:00:00Z", (23,25), (2,3.5), NOW)
        self.assertEqual(kind, "final")

    def test_no_window(self):
        kind, _ = classify_window("2026-08-21T08:00:00Z", (23,25), (2,3.5), NOW)
        self.assertIsNone(kind)

if __name__ == "__main__":
    unittest.main()
