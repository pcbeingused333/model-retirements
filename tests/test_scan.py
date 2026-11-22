"""What the scanner reports, and what it leaves out and says it left out.

Run with: python -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("scan", HERE / "scan.py")
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)


def entry(model, platform="openai-api", provider="OpenAI", shutdown="2026-01-01", cert="firm", repl="gpt-new"):
    return {"id": model, "platform": platform, "provider": provider, "shutdown": shutdown, "date_certainty": cert,
            "replacement": repl, "source": "https://example.test", "verified": True, "also_written_as": []}


FEED = {"generated_at": "2026-11-22", "sources": {}, "models": [
    entry("gpt-3.5-turbo"),
    entry("gemini-2.5-flash", "vertex-ai", "Vertex AI", "2026-10-20"),
    entry("gemini-2.5-flash", "gemini-api", "Google", "2026-12-01", "not_earlier_than"),
    entry("claude-opus-5", "claude-api", "Anthropic", "2027-07-24", "not_earlier_than"),
]}


def run(files, *flags):
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            p = Path(tmp) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        feed = Path(tmp) / "_feed.json"
        feed.write_text(json.dumps(FEED), encoding="utf-8")
        out = subprocess.run([sys.executable, "-I", str(HERE / "scan.py"), str(feed), tmp, "--json", *flags],
                             capture_output=True, text=True, check=False)
        return json.loads(out.stdout)


class Context(unittest.TestCase):
    def check(self, line, model, expected):
        self.assertEqual(scan.context_of(line, line.index(model)), expected, line)

    def test_a_value_of_a_model_setting_is_config(self):
        self.check('model="gpt-3.5-turbo",', "gpt-3.5-turbo", "config")
        self.check('    model: "gpt-3.5-turbo",', "gpt-3.5-turbo", "config")
        self.check('Settings.llm = OpenAI(model="gpt-3.5-turbo")', "gpt-3.5-turbo", "config")
        self.check("model: gpt-3.5-turbo", "gpt-3.5-turbo", "config")
        self.check("MODEL=gpt-3.5-turbo", "gpt-3.5-turbo", "config")
        self.check('model = os.getenv("MODEL", "gpt-3.5-turbo")', "gpt-3.5-turbo", "config")

    def test_prose_is_a_mention(self):
        self.check('model: Model name (e.g., "gpt-4o", "gpt-3.5-turbo")', "gpt-3.5-turbo", "mention")
        self.check("model_name: Name of the model to use (default: gpt-3.5-turbo)", "gpt-3.5-turbo", "mention")
        self.check("Sending completion request using model: gpt-3.5-turbo", "gpt-3.5-turbo", "mention")

    def test_a_comment_is_a_comment(self):
        self.check('# model="gpt-3.5-turbo" was used before', "gpt-3.5-turbo", "comment")


class Kinds(unittest.TestCase):
    def test_tests_and_docs_are_left_out_of_the_default_report_and_counted(self):
        d = run({"src/app.py": 'MODEL = "gpt-3.5-turbo"\n',
                 "tests/test_app.py": 'MODEL = "gpt-3.5-turbo"\n',
                 "docs/guide.md": 'model: "gpt-3.5-turbo"\n'}, "--config-only")
        self.assertEqual([f["file"] for f in d["findings"]], ["src/app.py"])
        self.assertEqual(d["hidden"], {"test": 1, "docs": 1})

    def test_all_shows_everything_with_its_kind(self):
        d = run({"src/app.py": 'MODEL = "gpt-3.5-turbo"\n', "tests/test_app.py": 'MODEL = "gpt-3.5-turbo"\n'},
                "--config-only", "--all")
        self.assertEqual(sorted(f["kind"] for f in d["findings"]), ["source", "test"])

    def test_a_file_that_lists_many_models_is_a_catalogue(self):
        feed_ids = "\n".join(f'"model-{i}": 1,' for i in range(20))
        FEED["models"].extend(entry(f"model-{i}") for i in range(20))
        try:
            d = run({"litellm/prices.py": feed_ids, "src/app.py": 'MODEL = "gpt-3.5-turbo"\n'}, "--all")
        finally:
            del FEED["models"][-20:]
        kinds = {f["file"]: f["kind"] for f in d["findings"]}
        self.assertEqual(kinds["litellm/prices.py"], "catalogue")
        self.assertEqual(kinds["src/app.py"], "source")


class Platforms(unittest.TestCase):
    def test_an_id_on_two_platforms_shows_both_even_when_one_is_only_a_floor(self):
        d = run({"src/app.py": 'MODEL = "gemini-2.5-flash"\n'}, "--config-only")
        [f] = d["findings"]
        self.assertEqual({p["platform"]: p["date_certainty"] for p in f["platforms"]},
                         {"vertex-ai": "firm", "gemini-api": "not_earlier_than"})

    def test_a_current_model_with_only_a_floor_is_not_reported(self):
        d = run({"src/app.py": 'MODEL = "claude-opus-5"\n'}, "--config-only")
        self.assertEqual(d["findings"], [])


if __name__ == "__main__":
    unittest.main()
