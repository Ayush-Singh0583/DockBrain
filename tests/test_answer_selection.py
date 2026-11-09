"""Offline answers: which sentences a quoted answer may include.

A sentence belongs in the answer only if it adds evidence for the question. Sharing the
question's words, or sitting under a heading that mentions them, isn't enough. All the
documents here are invented.
"""
import unittest

from rag.chunker import chunk_text
from rag.generator import NOT_FOUND, UNSURE, ExtractiveGenerator
from rag.retriever import BM25Retriever

MONGO = """Data Layer

MongoDB is a document database that stores records as BSON. The service keeps one database per region.

Sensor Queries

MongoDB sensor queries return the newest document for each device id. Pass the device id and a time window. Results are cached for five minutes."""

LARKSPUR = """Build Tools

Larkspur is a build cache for monorepos. It stores compiled artifacts by content hash, so unchanged code is never rebuilt.

Larkspur Dashboard Setup

Open the admin page and choose a team. Charts refresh every minute. Ask an administrator for access first."""

TWO_DEFINITIONS = """Tools

Larkspur is a build cache for monorepos. Larkspur is written in Go and ships as a single binary. The office closes at six on Fridays."""

HARDWARE = """System Design

2.1 Hardware Requirements

Processor: Intel Core i5 or better
Memory: 8 GB RAM
Storage: 256 GB SSD

2.2 Software Requirements

Python 3.12 and a modern browser."""

OFFICE = """Office Notes

The team moved its old artifacts to the basement last spring, together with the spare chairs, the broken printer, the holiday decorations and several boxes of paper that nobody has opened since the move.

Larkspur Retention

Ask Priya first. Parking is free on Fridays."""

IN_PASSING = """Tools

Larkspur is a build cache for monorepos. The tool that the platform group picked after a long trial of several caching products during the spring migration of the payments monorepo is Larkspur."""

ASIDES = """Services

Ravel, our scheduling service, is a cron replacement for clusters. Ravel logs are kept for a week.

Tern (Transfer Engine) is a file mover for labs. Tern jobs run every night."""

TOWERS = """Varn Guide

The Copper Spire is the tallest tower in Varn. The tallest tower in Varn opens at noon for visitors."""

QUILLMARK = """Video Tools

Quillmark is a font renderer for e-readers. Quillmark draws the captions on every exported video frame."""

HARDWARE_WITH_SUMMARY = """System Design

2.1 Hardware Requirements

The hardware requirements are modest.
Processor: Intel Core i5 or better
Memory: 8 GB RAM

2.2 Software Requirements

Python 3.12 and a modern browser."""

ORCHARD = """Orchard Report

The orchard has 240 pear trees and 180 apple trees. Pears are picked in late summer. The farm shop opens at nine.

Orchard Pests

Codling moths damage the apples most years. Netting keeps the birds away from the pears."""


def offline(text: str, question: str) -> tuple[str, ExtractiveGenerator]:
    generator = ExtractiveGenerator()
    retriever = BM25Retriever(chunk_text(text))
    generator.attach(retriever)
    return generator.answer(question, retriever.search(question, 4)), generator


class DefinitionQuestions(unittest.TestCase):
    def test_a_sentence_that_only_shares_the_subjects_words_is_left_out(self):
        for question in ("According to the document, what is MongoDB?", "What is MongoDB?"):
            with self.subTest(question):
                answer, generator = offline(MONGO, question)
                self.assertEqual(answer, "MongoDB is a document database that stores records as BSON.")
                self.assertEqual(generator.last_origin, "document")
                self.assertTrue(generator.last_cited)

    def test_a_heading_naming_the_subject_does_not_make_its_sentences_answers(self):
        answer, _ = offline(LARKSPUR, "What is Larkspur?")
        for unrelated in ("admin page", "Charts refresh", "administrator"):
            self.assertNotIn(unrelated, answer)

    def test_a_definition_and_the_sentence_continuing_it_are_both_quoted(self):
        answer, _ = offline(LARKSPUR, "What is Larkspur?")
        self.assertEqual(
            answer,
            "Larkspur is a build cache for monorepos. "
            "It stores compiled artifacts by content hash, so unchanged code is never rebuilt.",
        )

    def test_every_sentence_that_defines_the_subject_is_kept(self):
        answer, _ = offline(TWO_DEFINITIONS, "What is Larkspur?")
        self.assertEqual(answer, "Larkspur is a build cache for monorepos. Larkspur is written in Go and ships as a single binary.")

    def test_a_long_sentence_ending_in_is_x_does_not_count_as_strongly_as_the_definition(self):
        self.assertEqual(offline(IN_PASSING, "What is Larkspur?")[0], "Larkspur is a build cache for monorepos.")

    def test_a_definition_may_have_an_aside_or_a_bracket_after_the_subject(self):
        self.assertEqual(offline(ASIDES, "What is Ravel?")[0], "Ravel, our scheduling service, is a cron replacement for clusters.")
        self.assertEqual(offline(ASIDES, "What is Tern?")[0], "Tern (Transfer Engine) is a file mover for labs.")

    def test_a_sentence_naming_what_was_asked_about_is_the_answer(self):
        self.assertEqual(offline(TOWERS, "What is the tallest tower in Varn?")[0], "The Copper Spire is the tallest tower in Varn.")

    def test_what_something_is_used_for_is_not_a_definition_question(self):
        self.assertIn("draws the captions", offline(QUILLMARK, "What is Quillmark used for?")[0])

    def test_framing_like_according_to_the_report_is_not_part_of_the_question(self):
        plain, _ = offline(LARKSPUR, "What is Larkspur?")
        framed, generator = offline(LARKSPUR, "According to the report, what is Larkspur?")
        self.assertEqual(framed, plain)
        self.assertEqual(generator.last_origin, "document")


class PassageLevelMatches(unittest.TestCase):
    def test_a_heading_sharing_a_question_word_does_not_make_its_sentences_evidence(self):
        answer, _ = offline(OFFICE, "Which artifacts does Larkspur retain?")
        self.assertIn("old artifacts", answer)
        for unrelated in ("Ask Priya", "Parking"):
            self.assertNotIn(unrelated, answer)


class UnchangedBehaviour(unittest.TestCase):
    def test_a_list_under_the_heading_that_names_the_question_is_still_the_answer(self):
        answer, _ = offline(HARDWARE, "What are the hardware requirements?")
        self.assertEqual(answer, "Processor: Intel Core i5 or better Memory: 8 GB RAM Storage: 256 GB SSD")

    def test_a_section_named_for_the_subject_answers_as_a_whole(self):
        answer, _ = offline(HARDWARE_WITH_SUMMARY, "What are the hardware requirements?")
        self.assertIn("Processor: Intel Core i5 or better", answer)
        self.assertIn("Memory: 8 GB RAM", answer)

    def test_quantity_questions_prefer_the_sentence_with_the_number(self):
        answer, _ = offline(ORCHARD, "How many pear trees does the orchard have?")
        self.assertEqual(answer, "The orchard has 240 pear trees and 180 apple trees.")

    def test_overview_questions_still_summarise(self):
        answer, generator = offline(ORCHARD, "What is this report about?")
        self.assertTrue(answer.startswith("The orchard has 240 pear trees"))
        self.assertEqual(generator.last_origin, "document")

    def test_unanswerable_questions_keep_their_labels(self):
        answer, generator = offline(ORCHARD, "According to the document, what is the capital of France?")
        self.assertTrue(answer == NOT_FOUND or answer.startswith(UNSURE), answer)
        self.assertEqual(generator.last_origin, "insufficient")
        answer, generator = offline(LARKSPUR, "What is the capital of France?")
        self.assertEqual((answer, generator.last_origin), (NOT_FOUND, "insufficient"))

    def test_without_a_defining_sentence_the_best_matching_sentences_are_used(self):
        answer, _ = offline(ORCHARD, "What are codling moths?")
        self.assertEqual(answer, "Codling moths damage the apples most years.")


if __name__ == "__main__":
    unittest.main()
