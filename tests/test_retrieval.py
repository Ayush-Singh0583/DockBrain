"""Finding the right passage when the question words differ from the document's."""
import tempfile
import unittest
from pathlib import Path

from rag import RAG
from rag.chunker import chunk_text
from rag.generator import ExtractiveGenerator
from rag.retriever import BM25Retriever

FRUIT = """China accounts for the largest share of global apple production.

Pears ripen slowly in cool weather and need careful storage.

Plums are sweet and are often dried into prunes."""


def retriever(text: str) -> BM25Retriever:
    return BM25Retriever(chunk_text(text, max_words=12))


class WordForms(unittest.TestCase):
    def test_another_form_of_a_word_finds_the_passage(self):
        hits = retriever(FRUIT).search("Who produces the most?")
        self.assertTrue(hits)
        self.assertIn("China", hits[0][0].text)

    def test_the_exact_word_outranks_another_form_of_it(self):
        # "producers" appears twice in a shorter passage, so with equal weights it would win;
        # only its lower weight keeps the passage with the exact word on top. Passages are
        # kept separate so neither contains the other's word.
        text = "Apple production rose sharply this year.\n\nApple producers met apple producers."
        hits = BM25Retriever(chunk_text(text, max_words=6, overlap_sentences=0)).search("apple production")
        self.assertEqual([chunk.text for chunk, _ in hits],
                         ["Apple production rose sharply this year.", "Apple producers met apple producers."])

    def test_a_short_shared_start_is_not_a_match(self):
        self.assertEqual(retriever("The application runs quickly.\n\nPears ripen slowly.").search("apple"), [])

    def ask_offline(self, text: str, question: str) -> str:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doc.txt"
            path.write_text(text)
            return RAG(str(path), ExtractiveGenerator()).ask(question)[0]

    def test_an_offline_answer_quotes_the_passage_found_by_word_form(self):
        answer = self.ask_offline(FRUIT, "Who produces the most?")
        self.assertIn("China accounts for the largest share of global apple production.", answer)

    def test_an_offline_answer_prefers_the_exact_word_when_the_passage_has_it(self):
        text = "The technology stack uses sensors to grade apples.\n\nThis technological university studies apples closely."
        answer = self.ask_offline(text, "What technology is used?")
        self.assertIn("The technology stack uses sensors", answer)
        self.assertNotIn("technological university", answer)


class WordEndings(unittest.TestCase):
    """Singular, plural, and verb forms ending in "e" must meet at the same word."""

    def test_forms_find_each_other(self):
        cases = [
            ("An apple a day keeps you healthy.", "apples"),
            ("Many apples grow here.", "apple"),
            ("Users create accounts first.", "When are accounts created?"),
            ("Uploading a file takes a minute.", "How long do files take?"),
            ("Each box holds ten pears.", "How many pears fit in the boxes?"),
            ("The price rises each spring.", "When did the price rise?"),
            # Words ending in "ss" keep both letters; these are too short for word forms to help.
            ("One class studies pests.", "Which classes exist?"),
            ("A glass jar keeps seeds dry.", "Are glasses useful?"),
        ]
        for passage, question in cases:
            with self.subTest(question):
                hits = retriever(f"{passage}\n\nPlums are dried into prunes on racks.").search(question)
                self.assertTrue(hits)
                self.assertEqual(hits[0][0].text.split(".")[0] + ".", passage)


if __name__ == "__main__":
    unittest.main()
