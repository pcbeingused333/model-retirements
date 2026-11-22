"""The cells of OpenAI's deprecations table that a loose reader turned into models that are not.

Run with: python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from parse_openai import ids  # noqa: E402


class Ids(unittest.TestCase):
    def test_comma_separated_ids(self):
        self.assertEqual(ids("gpt-5 , gpt-5-2025-08-07"), ["gpt-5", "gpt-5-2025-08-07"])
        self.assertEqual(ids("o3"), ["o3"])
        self.assertEqual(ids("whisper-1"), ["whisper-1"])

    def test_display_name_then_ids_in_parentheses(self):
        self.assertEqual(
            ids("GPT-4o ( gpt-4o-2024-08-06 , gpt-4o-2024-11-20 )"), ["gpt-4o-2024-08-06", "gpt-4o-2024-11-20"]
        )
        self.assertEqual(ids("GPT-4.5 Preview (gpt-4.5-preview)"), ["gpt-4.5-preview"])

    def test_an_id_plus_the_aliases_its_parenthesis_names(self):
        cell = "gpt-4-0125-preview (including gpt-4-turbo-preview and gpt-4-turbo-preview-completions, which point to this snapshot)"
        self.assertEqual(
            ids(cell), ["gpt-4-0125-preview", "gpt-4-turbo-preview", "gpt-4-turbo-preview-completions"]
        )

    def test_a_note_in_parentheses_adds_nothing(self):
        self.assertEqual(ids("code-davinci-002 (base GPT models)"), ["code-davinci-002"])

    def test_an_old_model_that_quotes_its_price(self):
        self.assertEqual(ids("text-davinci-003 Historical price $20.00 / 1M tokens"), ["text-davinci-003"])

    def test_rows_about_features_are_not_models(self):
        for cell in (
            "New fine-tuning training on davinci-002",
            "New fine-tuning training on babbage-002",
            "Fine-tuning on davinci Training price $30.00 / 1M tokens. Usage price $120.00 / 1K tokens",
            "Self-serve fine-tuning job creation",
            "GPT-5.2, GPT-5.4, and GPT-5.4 mini with EU data residency and service_tier: fast or priority",
            "/v1/prompts and reusable prompt objects",
            "Videos API",
            "OpenAI-Beta: assistants=v1",
        ):
            self.assertEqual(ids(cell), [], cell)


if __name__ == "__main__":
    unittest.main()
