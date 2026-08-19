import unittest
from datetime import datetime, timezone
from fpl_ai_manager.analyzer import classify_window

UTC = timezone.utc

class WindowTests(unittest.TestCase):
    def test_preview_window(self):
        now = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
        kind, hours, mode = classify_window("2026-08-20T08:00:00Z", (23,25), (2,3.5), now)
        self.assertEqual(kind, "preview")
        self.assertEqual(hours, 24)
        self.assertEqual(mode, "standard")

    def test_standard_final_window(self):
        # 19:00 Beijing, deadline 22:00 Beijing -> normal final.
        now = datetime(2026, 8, 19, 11, 0, tzinfo=UTC)
        kind, _, mode = classify_window("2026-08-19T14:00:00Z", (23,25), (2,3.5), now)
        self.assertEqual(kind, "final")
        self.assertEqual(mode, "standard")

    def test_sleep_safe_for_7am_deadline(self):
        # Deadline Sun 07:00 Beijing. Sat 22:17 Beijing should send final.
        now = datetime(2026, 8, 22, 14, 17, tzinfo=UTC)
        kind, _, mode = classify_window("2026-08-22T23:00:00Z", (23,25), (2,3.5), now)
        self.assertEqual(kind, "final")
        self.assertEqual(mode, "sleep_safe")

    def test_sleep_safe_for_8am_deadline(self):
        # Deadline Sun 08:00 Beijing. Sat 22:17 Beijing should send final.
        now = datetime(2026, 8, 22, 14, 17, tzinfo=UTC)
        kind, _, mode = classify_window("2026-08-23T00:00:00Z", (23,25), (2,3.5), now)
        self.assertEqual(kind, "final")
        self.assertEqual(mode, "sleep_safe")

    def test_10am_deadline_uses_morning_standard_final(self):
        # Deadline Sun 10:00 Beijing; 07:30 Beijing is awake and inside final window.
        now = datetime(2026, 8, 22, 23, 30, tzinfo=UTC)
        kind, _, mode = classify_window("2026-08-23T02:00:00Z", (23,25), (2,3.5), now)
        self.assertEqual(kind, "final")
        self.assertEqual(mode, "standard")

    def test_hard_cutoff_no_final_after_11pm(self):
        # A sleep-safe final that was missed must not arrive after the cutoff.
        now = datetime(2026, 8, 22, 15, 5, tzinfo=UTC)  # 23:05 Beijing
        kind, _, mode = classify_window("2026-08-22T23:00:00Z", (23,25), (2,3.5), now)
        self.assertIsNone(kind)
        self.assertIsNone(mode)

    def test_no_window(self):
        now = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
        kind, _, mode = classify_window("2026-08-21T08:00:00Z", (23,25), (2,3.5), now)
        self.assertIsNone(kind)
        self.assertIsNone(mode)

if __name__ == "__main__":
    unittest.main()
