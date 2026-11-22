"""The check that stops a broken rebuild from replacing a good feed.

Run with: python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from rebuild import gate  # noqa: E402


def feed(**counts):
    return {"models": [{"provider": p, "id": f"{p}-{i}"} for p, n in counts.items() for i in range(n)]}


class Gate(unittest.TestCase):
    def test_a_stable_feed_passes(self):
        self.assertEqual(gate(feed(OpenAI=100, Anthropic=40), feed(OpenAI=104, Anthropic=40)), [])

    def test_a_provider_that_reads_nothing_fails(self):
        problems = gate(feed(OpenAI=100, Anthropic=40), feed(OpenAI=100))
        self.assertEqual(len(problems), 1)
        self.assertIn("Anthropic", problems[0])
        self.assertIn("no entries", problems[0])

    def test_losing_more_than_a_fifth_fails(self):
        self.assertEqual(len(gate(feed(OpenAI=100), feed(OpenAI=79))), 1)

    def test_losing_a_little_is_allowed(self):
        self.assertEqual(gate(feed(OpenAI=100), feed(OpenAI=85)), [])


if __name__ == "__main__":
    unittest.main()
