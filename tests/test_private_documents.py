"""The reports in docs/ are private. They, and the questions written about them, must stay
out of the repository, and the evaluations must still run in a copy that doesn't have them."""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))


def load_questions(private):
    """evals/questions.py as imported with, or (private=None) without, the private questions."""
    saved = {name: sys.modules.get(name) for name in ("questions", "private_questions")}
    sys.modules.pop("questions", None)
    sys.modules["private_questions"] = private  # None makes the import fail, as in a public copy
    try:
        return importlib.import_module("questions")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs a git checkout")
class NothingPrivateIsTracked(unittest.TestCase):
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

    def test_the_reports_and_their_questions_are_not_tracked(self):
        self.assertEqual(self.git("ls-files", "docs", "evals/private_questions.py").stdout, "")

    def test_git_ignores_them(self):
        for path in ("docs/a-report.docx", "evals/private_questions.py", "evals/data/a-report.pdf"):
            self.assertEqual(self.git("check-ignore", "-q", path).returncode, 0, path)


class PublicQuestions(unittest.TestCase):
    def setUp(self):
        self.questions = load_questions(None)

    def test_a_public_copy_only_asks_about_public_documents(self):
        q = self.questions
        public = {q.APPLE, q.IDS, q.CODEX, q.S}
        for name in ("TUNING", "FRESH", "OLD"):
            self.assertLessEqual({entry[0] for entry in getattr(q, name)}, public, name)

    def test_the_public_sets_are_all_there(self):
        q = self.questions
        self.assertEqual((len(q.TUNING), len(q.FRESH), len(q.OLD)), (14, 10, 14))

    def test_the_public_file_names_no_word_document(self):
        self.assertNotIn(".docx", (EVALS / "questions.py").read_text(encoding="utf-8"))


class PrivateQuestions(unittest.TestCase):
    def test_they_are_added_when_this_copy_has_them(self):
        public = load_questions(None)
        private = types.ModuleType("private_questions")
        private.TUNING, private.FRESH, private.OLD = [("t",)], [("f",)], [("o",)]
        merged = load_questions(private)
        self.assertEqual(merged.TUNING, public.TUNING + [("t",)])
        self.assertEqual(merged.FRESH, public.FRESH + [("f",)])
        self.assertEqual(merged.OLD, public.OLD + [("o",)])


class ReportFiles(unittest.TestCase):
    def setUp(self):
        import run
        self.run = run
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def test_a_copy_without_the_folder_has_none(self):
        self.assertEqual(self.run.report_files(str(self.folder / "missing")), [])

    def test_only_word_documents_are_converted_in_name_order(self):
        for name in ("b.docx", "a.docx", "notes.txt"):
            (self.folder / name).write_text("x")
        self.assertEqual(self.run.report_files(str(self.folder)),
                         [os.path.join(str(self.folder), n) for n in ("a.docx", "b.docx")])


if __name__ == "__main__":
    unittest.main()
