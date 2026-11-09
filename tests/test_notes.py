"""Study notes built offline from a document's own sentences (rag/notes.py).

Every point must be a sentence quoted from the document and cite the passage it came from,
so notes can't say anything the document doesn't. All documents here are invented.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

import rag.notes
from rag import RAG
from rag.chunker import Chunk
from rag.generator import ExtractiveGenerator
from rag.notes import POINTS_PER_SECTION, make_notes

HANDBOOK = """Harbor Lights Handbook

Overview

Harbor Lights is a volunteer program that maintains the lighthouse at Corran Point. Volunteers keep the lamp clean and log passing ships.

Schedule

Tea is provided. Bring a warm jacket. Shifts run from 6 pm to midnight every evening. Each shift needs two volunteers. The program closes in January for repairs. Coordinators publish the rota on the first Monday of each month. Volunteers swap shifts through the rota board.

Safety

Volunteers must wear harnesses on the gallery. The stairs are steep and narrow.

Acknowledgements

We thank the Corran Point harbour board for their support."""

PLAIN = """Pears ripen after they are picked. Store them at room temperature until the flesh near the stem softens. Refrigerate ripe pears to slow them down. Bartlett pears turn yellow when ripe. Bosc pears keep their brown skin and stay firm. Comice pears bruise easily, so growers pack them in single layers. Asian pears are crisp and are eaten while still hard. Pear trees need a second variety nearby for pollination."""


class NotesTestCase(unittest.TestCase):
    def notes_for(self, text: str, name: str = "handbook.txt"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(text, encoding="utf-8")
            rag = RAG(str(path), ExtractiveGenerator())
        return rag, make_notes(rag, name)


class BuildingNotes(NotesTestCase):
    def test_notes_have_the_contracts_shape(self):
        _, notes = self.notes_for(HANDBOOK)
        self.assertEqual(set(notes), {"title", "summary", "sections", "sources", "suggestedQuestions", "demo"})
        self.assertIs(notes["demo"], False)
        for section in notes["sections"]:
            self.assertEqual(set(section), {"id", "heading", "points"})

    def test_the_title_and_summary_come_from_the_document(self):
        _, notes = self.notes_for(HANDBOOK)
        self.assertEqual(notes["title"], "Harbor Lights Handbook")
        self.assertIn("Harbor Lights is a volunteer program", notes["summary"])

    def test_sections_follow_the_documents_headings_in_order(self):
        _, notes = self.notes_for(HANDBOOK)
        headings = [s["heading"] for s in notes["sections"]]
        self.assertEqual(headings[:2], ["Schedule", "Safety"])

    def test_every_point_is_quoted_and_cites_the_passage_it_came_from(self):
        rag, notes = self.notes_for(HANDBOOK)
        sentences = {s.text for chunk in rag.chunks for s in chunk.sentences}
        sources = {source["index"]: source for source in notes["sources"]}
        points = [p for section in notes["sections"] for p in section["points"]]
        self.assertTrue(points)
        for point in points:
            self.assertIn(point["text"], sentences)
            self.assertTrue(point["citations"])
            for index in point["citations"]:
                self.assertIn(point["text"], sources[index]["excerpt"])
                self.assertIsInstance(sources[index]["passageId"], int)

    def test_sections_keep_their_most_informative_sentences(self):
        _, notes = self.notes_for(HANDBOOK)
        schedule = next(s for s in notes["sections"] if s["heading"] == "Schedule")
        texts = [p["text"] for p in schedule["points"]]
        self.assertLessEqual(len(texts), POINTS_PER_SECTION)
        self.assertNotIn("Tea is provided.", texts)
        self.assertNotIn("Bring a warm jacket.", texts)  # filler, though it comes first
        self.assertIn("Shifts run from 6 pm to midnight every evening.", texts)

    def test_thank_yous_are_not_key_points(self):
        _, notes = self.notes_for(HANDBOOK)
        points = [p["text"] for section in notes["sections"] for p in section["points"]]
        self.assertFalse(any("We thank" in text for text in points))

    def test_the_summary_is_not_repeated_as_points(self):
        _, notes = self.notes_for(HANDBOOK)
        points = [p["text"] for section in notes["sections"] for p in section["points"]]
        self.assertNotIn("Harbor Lights is a volunteer program that maintains the lighthouse at Corran Point.", points)

    def test_headings_are_shown_without_numbers_or_reference_marks(self):
        text = ("Fruit Guide\n\nOverview\n\nThis guide covers keeping fruit and fighting pests.\n\n"
                "2.1 Storage[4]\n\nApples keep for months in cold, humid storage rooms.")
        _, notes = self.notes_for(text + "\n\n2.2 Pests\n\nCodling moths damage the apples in most years.")
        self.assertEqual([s["heading"] for s in notes["sections"]], ["Storage", "Pests"])

    def test_text_right_after_the_title_is_key_points_not_a_second_title(self):
        _, notes = self.notes_for("Pear Notes\n\n" + PLAIN, "pears.txt")
        self.assertEqual(notes["title"], "Pear Notes")
        self.assertEqual([s["heading"] for s in notes["sections"]], ["Key points"])

    def test_a_document_without_headings_gets_key_points(self):
        _, notes = self.notes_for(PLAIN, "pears.txt")
        self.assertEqual(notes["title"], "pears")
        self.assertTrue(notes["summary"])
        self.assertEqual([s["heading"] for s in notes["sections"]], ["Key points"])


class SuggestingQuestions(NotesTestCase):
    def test_suggested_questions_ask_about_terms_the_document_defines(self):
        _, notes = self.notes_for(HANDBOOK)
        self.assertIn("What is Harbor Lights?", notes["suggestedQuestions"])

    def test_suggested_questions_can_be_answered_from_the_document(self):
        rag, notes = self.notes_for(HANDBOOK)
        for question in notes["suggestedQuestions"]:
            with self.subTest(question):
                reply = rag.reply(question)
                self.assertEqual(reply.origin, "document", reply.text)



class NotesWriter:
    name = "Fake model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.prompts, self.instructions = [], []

    def write(self, prompt, instruction=None):
        self.prompts.append(prompt)
        self.instructions.append(instruction)
        if self.error:
            raise RuntimeError(self.error)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


SHIFTS = {"text": "Shifts run from 6 pm until midnight every evening.", "passage": 1,
          "quote": "Shifts run from 6 pm to midnight every evening."}
HARNESS = {"text": "Volunteers must wear harnesses on the gallery.", "passage": 1,
           "quote": "Volunteers must wear harnesses on the gallery."}
WRITTEN = {
    "summary": "Harbor Lights volunteers maintain the lighthouse at Corran Point.",
    "sections": [{"heading": "Working a shift", "points": [SHIFTS]}, {"heading": "Staying safe", "points": [HARNESS]}],
    "questions": ["When do shifts run?", "What must volunteers wear on the gallery?"],
}


class ModelNotes(NotesTestCase):
    def written(self, reply=None, error=None, text: str = HANDBOOK):
        writer = NotesWriter(WRITTEN if reply is None and error is None else reply, error)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "handbook.txt"
            path.write_text(text, encoding="utf-8")
            document = RAG(str(path), ExtractiveGenerator())
            document.generator.quiz_writer = writer
            return document, make_notes(document, "handbook.txt"), writer

    def test_grounded_model_notes_are_used(self):
        _, notes, writer = self.written()
        self.assertEqual(writer.instructions, [rag.notes.NOTES_INSTRUCTION])
        self.assertEqual(notes["summary"], WRITTEN["summary"])
        self.assertEqual([s["heading"] for s in notes["sections"]], ["Working a shift", "Staying safe"])
        self.assertEqual([s["id"] for s in notes["sections"]], ["s1", "s2"])
        self.assertEqual(notes["sections"][0]["points"], [{"text": SHIFTS["text"], "citations": [1]}])
        self.assertEqual(notes["suggestedQuestions"], WRITTEN["questions"])
        self.assertEqual(notes["title"], "Harbor Lights Handbook")
        self.assertIs(notes["demo"], False)
        self.assertFalse(notes.get("notice"))

    def test_each_cited_source_holds_the_quote(self):
        _, notes, _ = self.written()
        self.assertEqual([s["index"] for s in notes["sources"]], [1])
        self.assertIn(SHIFTS["quote"], notes["sources"][0]["excerpt"])
        self.assertIsInstance(notes["sources"][0]["passageId"], int)

    def test_points_that_fail_a_check_are_dropped(self):
        bad = {
            "quote not in the passage": {**SHIFTS, "quote": "Shifts run all night in the winter months."},
            "point not supported": {**SHIFTS, "text": "Aliens from Neptune repaint every lighthouse in Antarctica."},
            "passage out of range": {**SHIFTS, "passage": 40},
            "passage is a boolean": {**SHIFTS, "passage": True},
            "text not text": {**SHIFTS, "text": 5},
            "not an object": "Shifts run all night.",
        }
        for why, point in bad.items():
            with self.subTest(why):
                reply = {**WRITTEN, "sections": [{"heading": "Working a shift", "points": [point, SHIFTS]},
                                                 {"heading": "Empty after checks", "points": [point]}]}
                _, notes, _ = self.written(reply)
                self.assertEqual([s["heading"] for s in notes["sections"]], ["Working a shift"])
                self.assertEqual([p["text"] for p in notes["sections"][0]["points"]], [SHIFTS["text"]])

    def test_a_wrong_passage_number_is_corrected_from_the_quote(self):
        text = "\n\n".join(f"Part {w}\n\nThe {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran. " * 8
                           for i, w in enumerate(["north", "south", "east", "west"]))
        quote = "The west orchard was planted in 1903 by Mara Quill near the river Corran."
        reply = {**WRITTEN, "summary": "", "sections": [{"heading": "West orchard", "points": [
            {"text": "The west orchard was planted in 1903 by Mara Quill.", "passage": 1, "quote": quote}]}]}
        _, notes, _ = self.written(reply, text=text)
        self.assertEqual(notes["sections"][0]["heading"], "West orchard")
        self.assertIn(quote, notes["sources"][0]["excerpt"])

    def test_a_model_cannot_write_more_sections_or_points_than_fit(self):
        many = {**WRITTEN, "sections": [{"heading": f"Topic {n}", "points": [SHIFTS] * 9} for n in range(20)]}
        _, notes, _ = self.written(many)
        self.assertEqual(len(notes["sections"]), rag.notes.MAX_SECTIONS)
        self.assertEqual(len(notes["sections"][0]["points"]), rag.notes.MAX_WRITTEN_POINTS)

    def test_a_summary_sentence_the_document_does_not_support_is_dropped(self):
        summary = f"{WRITTEN['summary']} Aliens from Neptune founded the program in 1620."
        _, notes, _ = self.written({**WRITTEN, "summary": summary})
        self.assertEqual(notes["summary"], WRITTEN["summary"])

    def test_a_summary_with_nothing_supported_uses_the_documents_own_opening(self):
        _, notes, _ = self.written({**WRITTEN, "summary": "Aliens from Neptune founded it in 1620."})
        self.assertIn("Harbor Lights is a volunteer program", notes["summary"])
        self.assertEqual(notes["sections"][0]["heading"], "Working a shift")

    def test_a_section_needs_a_short_text_heading(self):
        for heading in (None, 5, "", "word " * 30):
            with self.subTest(heading=heading):
                reply = {**WRITTEN, "sections": [{"heading": heading, "points": [SHIFTS]}, {"heading": "Staying safe", "points": [HARNESS]}]}
                _, notes, _ = self.written(reply)
                self.assertEqual([s["heading"] for s in notes["sections"]], ["Staying safe"])

    def test_only_real_questions_are_suggested_and_only_a_few(self):
        reply = {**WRITTEN, "questions": ["When do shifts run?", 7, "Not a question", "Who runs it?", "Why January?", "Is it free?"]}
        _, notes, _ = self.written(reply)
        self.assertEqual(notes["suggestedQuestions"], ["When do shifts run?", "Who runs it?", "Why January?"])

    def test_questions_fall_back_to_the_documents_terms(self):
        _, notes, _ = self.written({**WRITTEN, "questions": "none"})
        self.assertEqual(notes["suggestedQuestions"], ["What is Harbor Lights?"])

    def test_unusable_replies_fall_back_to_quoted_notes_and_say_so(self):
        for reply in ("Sure, here are notes", "[]", '{"sections": 5}', "{not json", {"summary": "x", "sections": [{"heading": "A", "points": []}]}):
            with self.subTest(reply=reply):
                _, notes, _ = self.written(reply)
                self.assertTrue(notes["sections"])
                self.assertIn("Fake model", notes["notice"])

    def test_a_model_failure_falls_back_and_gives_the_reason(self):
        _, notes, _ = self.written(error="Ollama isn't running on this computer.")
        self.assertTrue(notes["sections"])
        self.assertIn("Ollama isn't running on this computer", notes["notice"])

    def test_reference_lists_are_not_shown_to_the_model(self):
        text = HANDBOOK + "\n\nReferences\n\nThe Quillon survey was printed in 1874 by the county office.\nQuillon described 40 varieties near Corran that year.\nQuillon gave a second talk in 1880 at the county hall.\nQuillon wrote a third paper in 1881 for the county.\nQuillon retired in 1890 near the county hall.\nQuillon died in 1899 near the county hall."
        _, _, writer = self.written(text=text)
        self.assertIn("Corran Point", writer.prompts[0])
        self.assertNotIn("Quillon", writer.prompts[0])

    def test_a_long_document_is_sampled_so_it_fits_the_model(self):
        text = "\n\n".join(f"Part {i}\n\nOrchard number {i} grew {i} varieties of fruit near the old river in the valley every year."
                           for i in range(200))
        _, _, writer = self.written(text=text)
        self.assertLessEqual(len(re.findall(r"^\[\d+\]", writer.prompts[0], re.M)), rag.notes.MAX_NOTE_PASSAGES)

    def test_many_short_passages_are_limited_by_number(self):
        passages = [Chunk(n, f"Short passage {n}.", []) for n in range(200)]
        self.assertEqual(len(rag.notes._sampled(passages)), rag.notes.MAX_NOTE_PASSAGES)

    def test_oversized_passages_are_sampled_more_thinly_so_they_fit(self):
        long_part = " ".join(f"Orchard {i} grew fruit near the old river in the valley every year" for i in range(40)) + "."
        text = "\n\n".join(f"Part {i}\n\n{long_part}" for i in range(60))
        _, _, writer = self.written(text=text)
        sent = writer.prompts[0].split("Passages:", 1)[1]
        self.assertLessEqual(len(sent), rag.notes.MAX_NOTE_CHARS * 1.1)  # numbering and section labels add a little
        self.assertGreaterEqual(len(re.findall(r"^\[\d+\]", sent, re.M)), 2)

    def test_offline_notes_have_no_notice(self):
        _, notes = self.notes_for(HANDBOOK)
        self.assertFalse(notes.get("notice"))


if __name__ == "__main__":
    unittest.main()
