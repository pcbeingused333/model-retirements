"""Status is computed from a date when the feed is used, and a rebuild only counts real changes.

Run with: python -m unittest discover tests
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import feedlib  # noqa: E402

TODAY = dt.date(2026, 11, 22)


def entry(**kw):
    return {"platform": "openai-api", "id": "m", "shutdown": "2026-12-11", "date_certainty": "firm",
            "replacement": "x", **kw}


class Derive(unittest.TestCase):
    def test_a_past_firm_date_is_retired(self):
        self.assertEqual(feedlib.derive(entry(shutdown="2026-09-28"), TODAY), ("retired", 0))

    def test_a_future_date_counts_down(self):
        self.assertEqual(feedlib.derive(entry(shutdown="2026-12-11"), TODAY), ("scheduled", 19))

    def test_the_day_itself_is_retired(self):
        self.assertEqual(feedlib.derive(entry(shutdown="2026-11-22"), TODAY)[0], "retired")

    def test_a_floor_is_never_a_shutdown_even_when_it_has_passed(self):
        e = entry(shutdown="2026-10-15", date_certainty="not_earlier_than")
        self.assertEqual(feedlib.derive(e, TODAY), ("active", 0))

    def test_no_date_means_active(self):
        self.assertEqual(feedlib.derive(entry(shutdown=None, date_certainty="unannounced"), TODAY), ("active", 0))

    def test_the_same_entry_changes_status_as_time_passes(self):
        e = entry(shutdown="2026-12-11")
        self.assertEqual(feedlib.derive(e, dt.date(2026, 12, 1))[0], "scheduled")
        self.assertEqual(feedlib.derive(e, dt.date(2026, 12, 12))[0], "retired")


class Changes(unittest.TestCase):
    def feed(self, *entries):
        return {"models": list(entries)}

    def test_identical_content_is_no_change_even_if_other_fields_differ(self):
        a = self.feed(entry(verified=True, days_remaining=19))
        b = self.feed(entry(verified=True, days_remaining=18, read_on="2026-11-23"))
        self.assertEqual(feedlib.changes(a, b), [])

    def test_a_moved_date_a_new_replacement_an_addition_and_a_removal_are_reported(self):
        a = self.feed(entry(id="a"), entry(id="b"), entry(id="gone"))
        b = self.feed(entry(id="a", shutdown="2027-01-28"), entry(id="b", replacement="y"), entry(id="new"))
        kinds = sorted(line.split()[0] for line in feedlib.changes(a, b))
        self.assertEqual(kinds, ["added", "changed", "changed", "removed"])


if __name__ == "__main__":
    unittest.main()
