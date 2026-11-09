"""Version 2: asking questions about a PDF.

Run with: python -m unittest discover -s tests
The PDFs are built here, so the repo needs no binary fixtures.
"""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rag import RAG
from rag.chunker import chunk_text, split_sentences
from rag.generator import ExtractiveGenerator
from rag.loader import load_document

ROOT = Path(__file__).resolve().parent.parent
HAS_PYPDF = importlib.util.find_spec("pypdf") is not None
needs_pypdf = unittest.skipUnless(HAS_PYPDF, "needs pypdf: pip install -r requirements.txt")


def pdf_bytes(pages: list[list[str]]) -> bytes:
    """A valid PDF where each page is a list of text lines. An empty list makes a
    page with only a drawn shape and no text, like a scanned image."""
    objects = [b"<</Type/Catalog/Pages 2 0 R>>", b"", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/StandardEncoding>>"]
    kids = []
    for lines in pages:
        if lines:
            shown = "".join("({}) Tj T*\n".format(
                line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")) for line in lines)
            shown = shown.replace("\u2022", "\xb7")  # the bullet's byte in Standard encoding
            stream = f"BT /F1 11 Tf 14 TL 72 720 Td\n{shown}ET".encode("latin-1")
        else:
            stream = b"0 0 100 100 re f"
        page_id, content_id = len(objects) + 1, len(objects) + 2
        kids.append(f"{page_id} 0 R")
        objects.append(
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents {content_id} 0 R"
            "/Resources<</Font<</F1 3 0 R>>>>>>".encode()
        )
        objects.append(b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream))
    objects[1] = f"<</Type/Pages/Kids[{' '.join(kids)}]/Count {len(kids)}>>".encode()

    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


class PdfTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write_pdf(self, pages, name="doc.pdf") -> Path:
        path = self.folder / name
        path.write_bytes(pdf_bytes(pages))
        return path

    def locked_pdf(self, user_password: str) -> Path:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=PdfReader(self.write_pdf([["Jupiter is the largest planet."]])))
        writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
        path = self.folder / "locked.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def ask(self, path: Path, question: str) -> str:
        return RAG(str(path), ExtractiveGenerator()).ask(question)[0]


@needs_pypdf
class ReadingText(PdfTestCase):
    def test_every_page_is_read_in_order(self):
        text = load_document(str(self.write_pdf([["Apples grow on trees."], ["Mangoes need warm weather."]])))
        self.assertLess(text.index("Apples"), text.index("Mangoes"))

    def test_a_sentence_wrapped_across_lines_is_found_whole(self):
        path = self.write_pdf([["Jupiter is the", "largest planet.", "Mars has two small moons."]])
        self.assertEqual(self.ask(path, "What is the largest planet?"), "Jupiter is the largest planet.")

    def test_a_word_hyphenated_at_a_line_end_can_be_searched(self):
        path = self.write_pdf([["Apples are sold through inter-", "national markets every year."]])
        self.assertIn("international markets", self.ask(path, "Where are international sales made?"))

    def test_a_heading_stays_apart_from_the_text_below_it(self):
        # The abstract can only be found if its heading survives as its own line.
        path = self.write_pdf([
            ["Thanks to everyone who supported this long study of orchards.",
             "ABSTRACT",
             "This study compares apple yields across three regions."],
        ])
        self.assertEqual(self.ask(path, "What is this about?"),
                         "This study compares apple yields across three regions.")

    def test_page_numbers_do_not_end_up_in_sentences(self):
        path = self.write_pdf([["Apples grow on trees.", "12"], ["13", "Mangoes need warm weather."]])
        text = load_document(str(path))
        self.assertNotIn("12", text)
        self.assertNotIn("13", text)

    def test_ordinary_numbers_in_the_text_are_kept(self):
        path = self.write_pdf([["Harvest totals", "12", "were recorded in the first week."]])
        self.assertIn("12", load_document(str(path)))


@needs_pypdf
class ReadingRealPageLayouts(PdfTestCase):
    """Each of these came from a real PDF that gave a wrong answer."""

    def test_a_heading_under_a_running_header_is_still_found(self):
        path = self.write_pdf([
            ["Acme Institute of Technology", "4", "Thanks to everyone who supported this study of orchards."],
            ["Acme Institute of Technology", "5", "ABSTRACT", "This study compares apple yields across three regions."],
            ["Acme Institute of Technology", "6", "Results Summary", "Mangoes need warm weather to ripen properly."],
        ])
        self.assertEqual(self.ask(path, "What is this about?"),
                         "This study compares apple yields across three regions.")

    def test_a_running_footer_is_removed(self):
        bodies = ["Apples grow on trees.", "Mangoes need warm weather.", "Pears ripen slowly.", "Plums taste sweet."]
        path = self.write_pdf([[body, f"Fruit Handbook page {n}"] for n, body in enumerate(bodies, 1)])
        text = load_document(str(path))
        self.assertEqual(text.count("Fruit Handbook"), 1)
        self.assertIn("Plums taste sweet.", text)

    def test_a_line_repeated_on_only_a_few_pages_is_kept(self):
        pages = [["Overview of apples", body] for body in ("Apples grow on trees.", "Pears ripen slowly.")]
        pages += [[body] for body in ("Mangoes need warm weather.", "Plums taste sweet.", "Figs dry well.", "Kiwis ship far.")]
        self.assertIn("Overview of apples", load_document(str(self.write_pdf(pages))))

    def test_a_numbered_heading_names_its_section(self):
        path = self.write_pdf([
            ["This paragraph is about something else entirely.", "1.2 Technology Stack",
             "React draws the pages.", "Vite builds the code."],
        ])
        answer = self.ask(path, "What technologies are in use?")
        self.assertIn("React draws the pages.", answer)
        self.assertNotIn("1.2 Technology Stack", answer)

    def test_a_numbered_heading_after_a_long_unfinished_line_is_found(self):
        path = self.write_pdf([
            ["\u2022 Smart contracts for licensing content across many different regions",
             "1.5 Significance", "This project shows a practical use of the idea."],
        ])
        self.assertEqual(self.ask(path, "What is the significance?"), "This project shows a practical use of the idea.")

    def test_one_wide_line_does_not_turn_narrow_column_lines_into_headings(self):
        # From a two-column paper: a title spans the page, so every column line looks short.
        path = self.write_pdf([[
            "A very wide title line that runs right across both of the columns at the top of this page of the paper here",
            "these deep models can learn many useful features",
            "while older systems needed careful manual work",
            "and that changed how most of the field thinks",
            "about building language tools from scratch today",
            "since training now happens on very large corpora",
            "which were simply not available in earlier years",
            "so most new results build upon pretrained models from",
            "Transformers and other recent methods",
            "Google and others have published similar results.",
        ]])
        self.assertNotIn("\n\nTransformers", load_document(str(path)))

    def test_a_year_at_the_start_of_a_line_is_not_a_heading_number(self):
        path = self.write_pdf([["This opening sentence ends cleanly.", "2019 Harvest Totals", "Yields rose by a third."]])
        self.assertIn("2019", load_document(str(path)))

    def test_each_bullet_is_a_separate_point(self):
        path = self.write_pdf([
            ["The system shall:", "\u2022 Validate credentials against the login database",
             "\u2022 Hash passwords using bcrypt before they are stored"],
        ])
        answer = self.ask(path, "How are passwords hashed?")
        self.assertEqual(answer, "Hash passwords using bcrypt before they are stored")

    def test_a_wrapped_bullet_stays_whole(self):
        path = self.write_pdf([
            ["\u2022 Hash passwords using bcrypt before", "they are stored in the database",
             "\u2022 Validate credentials at each login attempt"],
        ])
        self.assertIn("before they are stored", load_document(str(path)).replace("\n", " "))

    def test_a_heading_after_a_list_without_full_stops_is_found(self):
        path = self.write_pdf([
            ["This is a long opening sentence that fills up the whole width of the page.",
             "\u2022 First short item", "Results Summary", "Apple yields rose by a third."],
        ])
        self.assertEqual(self.ask(path, "What does the results summary say?"), "Apple yields rose by a third.")

    def test_a_ligature_does_not_break_a_word(self):
        path = self.write_pdf([["Apple classi\xaecation depends on colour and taste."]])
        self.assertIn("classification", load_document(str(path)))

    def test_a_sentence_continuing_onto_the_next_page_stays_whole(self):
        path = self.write_pdf([["Mars has moons. Jupiter is the"], ["largest planet."]])
        self.assertEqual(self.ask(path, "What is the largest planet?"), "Jupiter is the largest planet.")

    def test_a_word_hyphenated_across_pages_can_be_searched(self):
        path = self.write_pdf([["Apples are sold through inter-"], ["national markets every year."]])
        self.assertIn("international markets", load_document(str(path)).replace("\n", " "))


@needs_pypdf
class KeepingSourceContent(PdfTestCase):
    """The loader must not delete or alter text it isn't sure about."""

    def flat(self, pages) -> str:
        return " ".join(load_document(str(self.write_pdf(pages))).split())

    def test_similar_rows_on_one_page_are_content(self):
        rows = [f"Batch {n} contains {n * 10} apples." for n in range(1, 5)]
        text = self.flat([rows])
        for row in rows:
            self.assertIn(row, text)

    def test_inventory_quantities_survive(self):
        text = self.flat([["Fruit Inventory", "12 Apple trees", "24 Mango trees", "36 Pear trees",
                           "48 Plum trees", "The inventory was recorded in June."]])
        self.assertIn("12 Apple trees", text)
        self.assertIn("48 Plum trees", text)

    def test_a_number_ending_a_page_is_not_assumed_to_be_a_page_number(self):
        text = self.flat([["Harvest Report", "The total number of apples harvested was", "1250"]])
        self.assertIn("harvested was 1250", text)

    def test_a_wrapped_sentence_before_a_proper_noun_stays_whole(self):
        text = load_document(str(self.write_pdf([[
            "Introduction", "This survey studies fruit cultivation in", "New Zealand and Australia.",
            "Both countries supplied data for the entire growing season.",
        ]])))
        self.assertIn("This survey studies fruit cultivation in New Zealand and Australia.", split_sentences(text))

    def test_a_short_sentence_case_line_of_prose_is_not_a_heading(self):
        text = load_document(str(self.write_pdf([[
            "Introduction", "This survey studies fruit cultivation", "New Zealand and Australia supplied the data.",
        ]])))
        self.assertIn("This survey studies fruit cultivation New Zealand and Australia supplied the data.", split_sentences(text))

    def test_a_capitalized_line_ending_mid_phrase_is_not_a_heading(self):
        text = load_document(str(self.write_pdf([["An opening sentence.", "Fruit Grown In", "New Zealand supplied the data."]])))
        self.assertIn("Fruit Grown In New Zealand supplied the data.", split_sentences(text))

    def test_numbered_lines_at_the_top_of_each_page_are_content(self):
        questions = [f"Question {n}: Which fruit ripens in month {n}?" for n in range(1, 5)]
        text = self.flat([[question, "Answer below."] for question in questions])
        for question in questions:
            self.assertIn(question, text)

    def test_a_number_that_breaks_the_page_sequence_is_kept(self):
        text = self.flat([["Apples grow on trees.", "12"], ["Pears ripen slowly.", "13"],
                          ["The total harvested was", "1250"], ["Plums taste sweet.", "15"]])
        self.assertIn("harvested was 1250", text)
        for page_number in ("12", "13", "15"):
            self.assertNotIn(f" {page_number} ", f" {text} ")

    def test_real_page_numbers_are_removed_from_the_second_line_too(self):
        text = self.flat([["Acme Institute", str(n), body] for n, body in enumerate(
            ["Apples grow on trees.", "Pears ripen slowly.", "Plums taste sweet.", "Figs dry well."], 4)])
        self.assertEqual(text.count("Acme Institute"), 1)
        self.assertNotIn(" 5 ", text)

    def test_a_header_with_the_page_number_on_the_same_line_is_removed(self):
        bodies = ["Apples grow on trees.", "Pears ripen slowly.", "Plums taste sweet.", "Figs dry well."]
        text = self.flat([[f"Department of Fruit Science {n}", body] for n, body in enumerate(bodies, 7)])
        self.assertEqual(text.count("Department of Fruit Science"), 1)

    def test_a_page_number_below_two_header_lines_is_removed(self):
        bodies = ["Apples grow on trees.", "Pears ripen slowly.", "Plums taste sweet.", "Figs dry well."]
        # Long enough that the number is not among a page's last few lines either.
        text = self.flat([["Acme Institute", "Department of Fruit", str(n), body, f"Note {n * 3} on {body}", "More notes here.",
                           f"Further notes {n * 7} here."] for n, body in enumerate(bodies, 5)])
        for page_number in ("5", "6", "7", "8"):
            self.assertNotIn(f" {page_number} ", f" {text} ")

    def test_short_numbered_labels_at_the_top_of_each_page_are_content(self):
        bodies = ["Apples grow on trees.", "Pears ripen slowly.", "Plums taste sweet.", "Figs dry well."]
        text = self.flat([[f"Step {n}", body] for n, body in enumerate(bodies, 1)])
        for n in range(1, 5):
            self.assertIn(f"Step {n}", text)

    def test_a_sentence_ending_in_a_number_on_one_page_is_kept(self):
        pages = [["The total harvested was 1250", "Apples grow on trees."], ["Pears ripen slowly."], ["Plums taste sweet."]]
        self.assertIn("The total harvested was 1250", self.flat(pages))

    def test_changing_totals_at_the_top_of_each_page_are_kept(self):
        # These differ in the number only, but don't track the pages.
        pages = [[f"The total harvested was {n}", f"Orchard {label} produced apples.", "The harvest was inspected."]
                 for n, label in zip((100, 200, 300), ("Alpha", "Beta", "Gamma"))]
        text = self.flat(pages)
        for total in (100, 200, 300):
            self.assertIn(f"The total harvested was {total}", text)

    def test_sequential_quantities_finishing_a_sentence_are_kept(self):
        # 100, 101, 102 advance with the pages like page numbers.
        pages = [[f"Orchard {label} harvest.", "The count was", str(n)] for n, label in zip((100, 101, 102), ("Alpha", "Beta", "Gamma"))]
        text = self.flat(pages)
        for count in ("was 100", "was 101", "was 102"):
            self.assertIn(count, text)

    def test_a_number_continuing_a_sentence_onto_the_next_page_is_kept(self):
        pages = [["Apples grow on trees.", "12"], ["Pears ripen slowly. The count reached"], ["14", "Plums taste sweet."],
                 ["Figs dry well.", "15"]]
        text = self.flat(pages)
        self.assertIn("The count reached 14", text)
        self.assertNotIn(" 12 ", f" {text} ")

    def test_a_page_number_interrupting_a_sentence_is_removed(self):
        pages = [["The orchard grows apples in", "12"], ["many regions of the north.", "Pears ripen.", "13"],
                 ["Plums taste sweet.", "14"]]
        text = self.flat(pages)
        self.assertIn("grows apples in many regions", text)
        self.assertNotIn(" 12 ", f" {text} ")

    def test_numbering_on_most_pages_of_a_long_document_is_removed_beside_headings(self):
        # Like a real report: page numbers sit after headings and bullets, not finished sentences.
        pages = [[str(n), f"Chapter {n} Overview", f"\u2022 Point about topic {n}"] for n in range(1, 9)]
        text = self.flat(pages)
        for n in range(1, 9):
            self.assertIn(f"Chapter {n} Overview", text)
            self.assertNotIn(f"Point about topic {n - 1} {n} Chapter", text)

    def test_a_number_after_an_unfinished_phrase_is_kept_even_in_long_numbering(self):
        pages = [[str(n), f"Section {n} text ends here."] for n in range(1, 9)]
        pages[3] = ["4", "The total harvested was"]
        pages[4] = ["5", "Section five text ends here."]
        self.assertIn("harvested was 5", self.flat(pages))

    def test_a_repeated_header_is_kept_once_so_its_text_can_be_found(self):
        pages = [["Acme Institute", body] for body in ("Apples grow.", "Pears ripen.", "Plums taste sweet.", "Figs dry.")]
        self.assertEqual(self.flat(pages).count("Acme Institute"), 1)

    def test_the_same_line_many_times_on_one_page_is_not_a_header(self):
        lines = ["Total", "Apples grew well.", "Total", "Pears ripened.", "Total", "Plums were sweet.", "Total"]
        self.assertEqual(self.flat([lines, ["Figs dried well."], ["Kiwis shipped far."]]).count("Total"), 4)

    def test_a_section_number_stays_in_the_text(self):
        self.assertIn("1.5 Significance", self.flat([["An opening sentence.", "1.5 Significance", "It matters a lot."]]))

    def test_a_negative_number_keeps_its_sign(self):
        self.assertIn("- 5 degrees", self.flat([["Night temperatures fell to", "- 5 degrees", "across the orchard."]]))

    def test_a_compound_word_used_elsewhere_keeps_its_hyphen(self):
        text = self.flat([["Careful fine-tuning helps. Later fine-", "tuning helped even more."]])
        self.assertNotIn("finetuning", text)
        self.assertEqual(text.count("fine-tuning"), 2)

    def test_a_longer_compound_split_at_a_line_end_keeps_its_hyphens(self):
        self.assertIn("state-of-the-art", self.flat([["These are state-of-", "the-art methods for storing apples."]]))

    def test_stacked_headings_are_still_found(self):
        text = load_document(str(self.write_pdf([["An opening sentence.", "Types of Watermarks", "Visible Watermarks",
                                                  "These can be seen by the viewer."]])))
        headings = [s.text for chunk in chunk_text(text) for s in chunk.sentences if s.is_heading]
        self.assertEqual(headings, ["Types of Watermarks", "Visible Watermarks"])

    def test_one_unreadable_page_does_not_lose_the_others(self):
        from pypdf import PageObject

        real = PageObject.extract_text
        calls = []

        def fail_on_second_page(page, *args, **kwargs):
            calls.append(page)
            if len(calls) == 2:
                raise ValueError("damaged page")
            return real(page, *args, **kwargs)

        path = self.write_pdf([["Apples grow on trees."], ["Pears ripen slowly."], ["Plums taste sweet."]])
        errors = io.StringIO()
        with mock.patch.object(PageObject, "extract_text", fail_on_second_page), contextlib.redirect_stderr(errors):
            text = load_document(str(path))
        self.assertIn("Apples", text)
        self.assertIn("Plums", text)
        self.assertIn("1 of 3 pages", errors.getvalue())


@needs_pypdf
class PdfsThatCannotBeFullyRead(PdfTestCase):
    def test_a_pdf_with_no_text_explains_why(self):
        with self.assertRaisesRegex(ValueError, "no readable text.*scanned"):
            load_document(str(self.write_pdf([[], []])))

    def test_pages_without_text_are_reported_and_the_rest_still_load(self):
        path = self.write_pdf([["Apples grow on trees."], [], ["Mangoes need warm weather."]])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            text = load_document(str(path))
        self.assertIn("Mangoes", text)
        self.assertIn("1 of 3 pages", errors.getvalue())

    def test_fully_readable_pdf_reports_nothing(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            load_document(str(self.write_pdf([["Apples grow on trees."]])))
        self.assertEqual(errors.getvalue(), "")

    def test_a_password_protected_pdf_says_so(self):
        with self.assertRaisesRegex(ValueError, "password"):
            load_document(str(self.locked_pdf(user_password="secret")))

    def test_a_pdf_restricted_only_by_owner_password_still_opens(self):
        self.assertIn("Jupiter", load_document(str(self.locked_pdf(user_password=""))))

    def test_a_corrupt_file_says_so(self):
        path = self.folder / "broken.pdf"
        path.write_bytes(b"this is not really a pdf")
        with self.assertRaisesRegex(ValueError, "broken.pdf isn't a readable PDF"):
            load_document(str(path))


class WithoutPypdfInstalled(PdfTestCase):
    def test_a_pdf_explains_what_to_install(self):
        path = self.write_pdf([["Apples grow on trees."]])
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaisesRegex(ValueError, "pip install"):
                load_document(str(path))

    def test_other_file_types_still_work(self):
        path = self.folder / "notes.txt"
        path.write_text("Apples grow on trees.")
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            self.assertIn("Apples", load_document(str(path)))


class RunningTheApp(PdfTestCase):
    def run_app(self, target, questions="exit\n"):
        return subprocess.run(
            [sys.executable, "main.py", str(target), "--offline"],
            input=questions, capture_output=True, text=True, cwd=ROOT, timeout=60,
        )

    @needs_pypdf
    def test_ask_a_question_about_a_pdf(self):
        path = self.write_pdf([["Mars has two small moons."], ["Jupiter is the largest planet."]])
        result = self.run_app(path, "What is the largest planet?\nexit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("A: Jupiter is the largest planet.", result.stdout)

    def assert_clean_failure(self, result, message):
        self.assertEqual(result.returncode, 1)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    @needs_pypdf
    def test_an_unreadable_pdf_fails_with_a_message(self):
        path = self.folder / "broken.pdf"
        path.write_bytes(b"this is not really a pdf")
        self.assert_clean_failure(self.run_app(path), "isn't a readable PDF")

    @needs_pypdf
    def test_the_pdf_library_adds_no_noise_to_an_error(self):
        path = self.folder / "broken.pdf"
        path.write_bytes(b"this is not really a pdf")
        self.assertEqual(self.run_app(path).stderr.strip(), "Error: broken.pdf isn't a readable PDF.")

    def test_a_missing_file_fails_with_a_message(self):
        self.assert_clean_failure(self.run_app("no-such-file.pdf"), "No such file")

    def test_an_unsupported_type_fails_with_a_message(self):
        self.assert_clean_failure(self.run_app("main.py"), "Unsupported file type")


if __name__ == "__main__":
    unittest.main()
