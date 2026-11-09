"""Reading settings such as GEMINI_API_KEY from a .env file."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main as app


class EnvFileTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.env_file = Path(folder.name) / ".env"
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class ReadingTheFile(EnvFileTestCase):
    def loaded(self, content: str) -> dict:
        self.env_file.write_text(content)
        app.load_env_file(self.env_file)
        return dict(os.environ)

    def test_spaces_around_the_equals_sign_are_allowed(self):
        self.assertEqual(self.loaded("GEMINI_API_KEY = abc123\n"), {"GEMINI_API_KEY": "abc123"})

    def test_quotes_are_removed(self):
        self.assertEqual(self.loaded("A=\"one\"\nB='two'\n"), {"A": "one", "B": "two"})

    def test_an_export_prefix_is_allowed(self):
        self.assertEqual(self.loaded("export A=one\n"), {"A": "one"})

    def test_comments_and_blank_lines_are_skipped(self):
        self.assertEqual(self.loaded("# GEMINI_API_KEY=old\n\nA=one  # note\n"), {"A": "one"})

    def test_a_line_that_is_not_a_setting_is_skipped(self):
        self.assertEqual(self.loaded("this line has no setting\nA=one\n"), {"A": "one"})

    def test_a_value_already_in_the_environment_wins(self):
        os.environ["A"] = "from-terminal"
        self.assertEqual(self.loaded("A=from-file\n"), {"A": "from-terminal"})

    def test_a_missing_file_is_fine(self):
        app.load_env_file(self.env_file)
        self.assertEqual(dict(os.environ), {})


class StartingTheApp(EnvFileTestCase):
    def first_line(self, *flags) -> str:
        """Start the app and quit at the first prompt, so nothing is sent anywhere."""
        out = io.StringIO()
        with (mock.patch.object(app, "ENV_FILE", self.env_file),
              mock.patch("sys.argv", ["main.py", "sample.txt", *flags]),
              mock.patch("builtins.input", side_effect=EOFError),
              contextlib.redirect_stdout(out)):
            app.main()
        return out.getvalue().splitlines()[0]

    def test_a_key_in_the_file_turns_on_gemini(self):
        self.env_file.write_text("GEMINI_API_KEY = abc123\n")
        self.assertIn("answers: Gemini", self.first_line())

    def test_offline_still_wins_over_a_key_in_the_file(self):
        self.env_file.write_text("GEMINI_API_KEY = abc123\n")
        self.assertIn("answers: extractive (offline)", self.first_line("--offline"))

    def test_with_no_key_the_app_stays_offline(self):
        self.assertIn("answers: extractive (offline)", self.first_line())


if __name__ == "__main__":
    unittest.main()
