"""Memory cards built offline from a document's own sentences (rag/cards.py).

Every card's answer must appear word for word in its source sentence, and that sentence
in the passage the card cites. All documents here are invented.
"""
import json
import re
import unittest

import rag.cards
from rag.cards import MAX_CARDS, build_cards
from rag.chunker import Chunk, Sentence, chunk_text
from rag.quiz import BLANK, SPARE_ITEMS, InsufficientContent

LIGHTHOUSE = """Harbor Lights Handbook

Overview

Harbor Lights is a volunteer program that maintains the lighthouse at Corran Point. The lamp was first lit in 1871 by Mara Quill.

Schedule

Shifts run from 6 pm to midnight every evening. Each shift needs 2 volunteers on the gallery. The program closes in January for repairs, when Tomas Reyes repaints the tower.

Acknowledgements

We thank the Corran Point harbour board for their support in 2024."""

NOTHING_TO_ASK = """Notes

this list has no sentences
just short lines
and fragments"""


WITH_REFERENCES = """Field Guide

Overview

The Tessel Ridge orchard opened in 1902 near the Corran river. Its first harvest was sold to Mara Quill in 1904.

References

The Quillon survey of Corran orchards was printed in 1874 by the county office. Quillon described 40 varieties that were grown near Corran in that year.

Read by Dara Quillon for the county

Quillon gave a second talk about Corran orchards in 1880 at the county hall.
"""


def cards_for(text: str, count: int = 10, **kwargs):
    return build_cards(chunk_text(text), count, title="Handbook", **kwargs)


def only_card(text: str, seed=None):
    cards = cards_for(text, seed=seed).cards
    assert len(cards) == 1, cards
    return cards[0]


class WhatMakesACard(unittest.TestCase):
    def test_a_pronoun_is_not_something_to_define(self):
        with self.assertRaises(InsufficientContent):
            cards_for("Moons\n\nIt is the smallest moon of the planet.")

    def test_a_definition_needs_more_than_a_bare_noun(self):
        with self.assertRaises(InsufficientContent):
            cards_for("Groups\n\nHarbor Lights Volunteer Corps is a charity.")

    def test_definition_fronts_read_naturally(self):
        self.assertEqual(only_card("Towers\n\nThe Copper Spire is the tallest tower in the harbour district.").prompt,
                         "What is the Copper Spire?")
        self.assertEqual(only_card("Crew\n\nHarbor Pilots are the sailors who guide ships into port.").prompt,
                         "What are Harbor Pilots?")

    def test_a_sentence_the_document_repeats_makes_one_card(self):
        sentence = "The lamp was first lit in 1871 by Mara Quill."
        cards = cards_for(f"Log\n\n{sentence} Each shift needs 2 volunteers on the gallery. {sentence}").cards
        self.assertEqual([c.quote for c in cards].count(sentence), 1)

    def test_a_blank_never_leaves_another_copy_of_its_answer(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                self.assertEqual(only_card("Log\n\nMara Quill lit the lamp in 1871 and Mara Quill kept the log.", seed).answer, "1871")

    def test_a_blank_must_leave_enough_of_the_sentence_to_go_on(self):
        with self.assertRaises(InsufficientContent):
            cards_for("Log\n\nHarbor Lights Volunteer Corps closed down yesterday.")

    def test_any_name_or_number_in_a_sentence_can_be_the_blank(self):
        answers = {only_card("Log\n\nThe lamp was first lit in 1871 by Mara Quill.", seed).answer for seed in range(12)}
        self.assertEqual(answers, {"1871", "Mara Quill"})


class BuildingCards(unittest.TestCase):
    def test_every_card_is_grounded_in_the_passage_it_cites(self):
        cards = cards_for(LIGHTHOUSE).cards
        self.assertTrue(cards)
        for card in cards:
            with self.subTest(card.prompt):
                self.assertIn(card.quote, card.passage.text)
                self.assertIn(card.answer, card.quote)

    def test_definitions_become_what_is_questions(self):
        cards = cards_for(LIGHTHOUSE).cards
        definition = next(c for c in cards if c.kind == "definition")
        self.assertEqual(definition.prompt, "What is Harbor Lights?")
        self.assertEqual(definition.answer, "a volunteer program that maintains the lighthouse at Corran Point")

    def test_a_general_term_with_a_or_an_is_a_definition_too(self):
        text = "Field Guide\n\nOverview\n\nAn apple grader is a machine that sorts fruit by size.\n"
        card = cards_for(text).cards[0]
        self.assertEqual((card.kind, card.prompt), ("definition", "What is an apple grader?"))
        self.assertEqual(card.answer, "a machine that sorts fruit by size")

    def test_the_followed_by_a_common_noun_needs_context_so_is_not_a_definition(self):
        text = "Field Guide\n\nOverview\n\nThe result is a list that was printed by Mara Quill.\n"
        for card in cards_for(text).cards:
            self.assertEqual(card.kind, "cloze")

    def test_names_and_numbers_become_fill_in_the_blank_cards(self):
        cloze = [c for c in cards_for(LIGHTHOUSE).cards if c.kind == "cloze"]
        self.assertTrue(cloze)
        for card in cloze:
            self.assertEqual(card.prompt, f"Fill in the blank: “{card.quote.replace(card.answer, BLANK, 1)}”")
            self.assertNotIn(card.answer, card.prompt)

    def test_thank_yous_headings_and_fragments_are_not_cards(self):
        quotes = [c.quote for c in cards_for(LIGHTHOUSE).cards]
        self.assertFalse(any("We thank" in q for q in quotes))
        self.assertFalse(any(q in ("Overview", "Schedule") for q in quotes))

    def test_cards_are_spread_through_the_document_in_order(self):
        cards = cards_for(LIGHTHOUSE, count=2).cards
        self.assertEqual(len(cards), 2)
        self.assertIn("Harbor Lights", cards[0].quote)
        self.assertIn("January", cards[-1].quote)
        self.assertEqual([c.id for c in cards], ["c1", "c2"])

    def test_reference_lists_are_not_cards(self):
        cards = cards_for(WITH_REFERENCES, count=MAX_CARDS).cards
        quotes = [c.quote for c in cards]
        self.assertTrue(any("Tessel Ridge" in q for q in quotes))
        for quote in quotes:
            with self.subTest(quote):
                self.assertNotIn("Quillon", quote)  # only the reference entries name him

    def test_the_heading_of_a_reference_list_can_be_any_case_or_end_a_longer_line(self):
        for heading in ("REFERENCES", "Bibliography", "Works Cited", "Further reading", "External links", "Proverb See also"):
            with self.subTest(heading):
                text = f"Field Guide\n\nOverview\n\nThe Tessel Ridge orchard opened in 1902 near the river.\n\n{heading}\n\nThe Quillon survey was printed in 1874 by the county office.\n"
                quotes = [c.quote for c in cards_for(text).cards]
                self.assertEqual(len(quotes), 1, quotes)
                self.assertIn("Tessel Ridge", quotes[0])

    def test_a_section_that_only_mentions_sources_still_gives_cards(self):
        text = "Field Guide\n\nData Sources\n\nThe Tessel Ridge survey was collected in 1902 near the river.\n"
        self.assertTrue(any("Tessel Ridge" in c.quote for c in cards_for(text).cards))

    def test_a_contents_line_does_not_end_the_document_early(self):
        text = "Field Guide\n\nReferences\n\nOverview\n\nThe Tessel Ridge orchard opened in 1902 near the river.\n\nHistory\n\nMara Quill planted 40 trees in 1904 near the old mill.\n"
        quotes = [c.quote for c in cards_for(text).cards]
        self.assertTrue(any("Tessel Ridge" in q for q in quotes), quotes)
        self.assertTrue(any("Mara Quill" in q for q in quotes), quotes)

    def test_an_early_reference_section_is_left_out_without_losing_what_follows(self):
        text = (
            "Field Guide\n\nReferences\n\nThe Quillon survey was printed in 1874 by the county office.\n\n"
            "Overview\n\nThe Tessel Ridge orchard opened in 1902 near the river.\n\n"
            "History\n\nMara Quill planted 40 trees in 1904 near the old mill.\n\n"
            "Pruning\n\nDara Quell pruned 12 trees in 1910 near the weir.\n"
        )
        quotes = [c.quote for c in cards_for(text).cards]
        self.assertFalse(any("Quillon" in q for q in quotes), quotes)
        self.assertEqual(len(quotes), 3, quotes)

    def test_citation_lines_outside_a_reference_section_are_not_cards(self):
        for line in (
            "Harvest totals were archived at https://example.org/tessel in 2012 by the county.",
            "Archived from the original on 12 May 2008 at the Tessel Ridge library.",
            "Retrieved 3 June 2019 from the county office at Tessel Ridge.",
            "The Tessel survey has been published with ISBN 12345 in 1999 by the county.",
            "Tessel growth was reported by Quill et al. in 1999 for the county.",
        ):
            with self.subTest(line), self.assertRaises(InsufficientContent):
                cards_for(f"Field Guide\n\nOverview\n\n{line}\n")

    def test_ordinary_uses_of_those_words_still_give_cards(self):
        text = "Field Guide\n\nOverview\n\nThe records are retrieved from the Tessel Ridge office every 3 weeks by a volunteer.\n"
        self.assertTrue(cards_for(text).cards)

    def test_titles_and_lists_of_names_are_not_cards(self):
        for line in (
            "The Encyclopedia of Celtic Mythology and Folklore.",
            "White River Junction, Vermont: Chelsea Green Publishing.",
            "M. communis Desf., 1768 M. pumila Mil. Rosa Alba 1771.",
        ):
            with self.subTest(line), self.assertRaises(InsufficientContent):
                cards_for(f"Field Guide\n\nOverview\n\n{line}\n")

    def test_a_possessive_is_not_part_of_a_defined_term(self):
        text = "Field Guide\n\nOverview\n\nIts Copper Spire is a tower that was built by Mara Quill.\n"
        cards = cards_for(text).cards
        self.assertTrue(cards)
        for card in cards:
            self.assertNotIn("What is Its", card.prompt)
            self.assertEqual(card.kind, "cloze")

    def test_a_reference_mark_is_never_the_blank(self):
        text = "Field Guide\n\nOverview\n\nThe orchard at Tessel Ridge reduces tree growth every autumn.[63] and it recovers by spring.\n"
        for seed in range(25):
            for card in cards_for(text, seed=seed).cards:
                with self.subTest(seed=seed):
                    self.assertEqual(card.answer, "Tessel Ridge")

    def test_a_short_document_gets_fewer_cards_and_says_so(self):
        card_set = cards_for(LIGHTHOUSE, count=MAX_CARDS)
        self.assertLess(len(card_set.cards), MAX_CARDS)
        self.assertIn(f"Only {len(card_set.cards)} cards", card_set.notice)

    def test_a_document_with_nothing_suitable_is_insufficient_content(self):
        with self.assertRaises(InsufficientContent):
            cards_for(NOTHING_TO_ASK)

    def test_the_number_of_cards_is_checked(self):
        for count in (0, MAX_CARDS + 1, True, "5", 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                cards_for(LIGHTHOUSE, count=count)



class CardWriter:
    """Stands in for a model, so the checks on written cards run offline."""

    name = "Fake model"

    def __init__(self, *items, reply=None, error=None):
        self.reply = json.dumps({"cards": list(items)}) if reply is None else reply
        self.error = error
        self.prompts, self.instructions = [], []

    def write(self, prompt, instruction=None):
        self.prompts.append(prompt)
        self.instructions.append(instruction)
        if self.error:
            raise RuntimeError(self.error)
        return self.reply


LAMP = {"passage": 1, "question": "Who first lit the lamp at Corran Point?", "answer": "Mara Quill",
        "quote": "The lamp was first lit in 1871 by Mara Quill."}
REPAIRS = {"passage": 1, "question": "In which month does the program close for repairs?", "answer": "January",
           "quote": "The program closes in January for repairs, when Tomas Reyes repaints the tower."}


class ModelCards(unittest.TestCase):
    def test_a_grounded_model_card_becomes_a_question_card(self):
        writer = CardWriter(LAMP, REPAIRS)
        card_set = cards_for(LIGHTHOUSE, count=2, writer=writer)
        self.assertEqual(writer.instructions, [rag.cards.CARDS_INSTRUCTION])
        self.assertEqual([c.kind for c in card_set.cards], ["question", "question"])
        first = card_set.cards[0]
        self.assertEqual((first.id, first.prompt, first.answer), ("c1", LAMP["question"], "Mara Quill"))
        self.assertIn(first.quote, first.passage.text)
        self.assertIsNone(card_set.notice)

    def test_an_answer_in_other_words_is_kept_if_the_quote_supports_it(self):
        reworded = {**LAMP, "question": "When was the lamp first lit?", "answer": "It was lit in 1871"}
        self.assertEqual(cards_for(LIGHTHOUSE, count=1, writer=CardWriter(reworded)).cards[0].answer, "It was lit in 1871")

    def test_quotes_may_differ_in_spacing_and_curly_quote_marks(self):
        spaced = {**LAMP, "quote": "“The lamp was first   lit in 1871 by Mara Quill.”"}
        self.assertEqual(cards_for(LIGHTHOUSE, count=1, writer=CardWriter(spaced)).cards[0].kind, "question")

    def test_cards_that_fail_a_check_are_dropped_and_the_rest_used(self):
        invented = {**LAMP, "question": "Who owns the lighthouse?", "answer": "Anna Berg", "quote": "The lighthouse is owned by Anna Berg."}
        card_set = cards_for(LIGHTHOUSE, count=2, writer=CardWriter(invented, LAMP))
        self.assertEqual([c.prompt for c in card_set.cards], [LAMP["question"]])
        self.assertIn("Only 1 card", card_set.notice)

    def test_each_failed_check_rejects_the_card(self):
        bad = {
            "quote not in the passage": {**LAMP, "quote": "The lamp was lit in 1900 by Anna Berg."},
            "quote too short": {**LAMP, "quote": "Mara Quill."},
            "answer not in the quote": {**LAMP, "answer": "Tomas Reyes"},
            "front gives the answer away": {**LAMP, "question": "What did Mara Quill do in 1871?", "answer": "Mara Quill"},
            "front refers to the document": {**LAMP, "question": "Who lit the lamp according to this passage?"},
            "front names this module": {**LAMP, "question": "Who lit the lamp in this module?"},
            "passage out of range": {**LAMP, "passage": 99},
            "passage is a boolean": {**LAMP, "passage": True},
            "question missing": {k: v for k, v in LAMP.items() if k != "question"},
            "question not text": {**LAMP, "question": 7},
            "answer not text": {**LAMP, "answer": ["Mara Quill"]},
            "answer far too long": {**LAMP, "answer": "Mara Quill " + "and also the lamp " * 12},
            "not an object": "Mara Quill",
        }
        for why, item in bad.items():
            with self.subTest(why):
                card_set = cards_for(LIGHTHOUSE, count=3, writer=CardWriter(item), seed=1)
                self.assertNotIn("question", [c.kind for c in card_set.cards])

    def test_a_citation_is_rejected_as_a_quote(self):
        text = "Field Guide\n\nOverview\n\nRetrieved 3 June 2019 from the county office at Tessel Ridge by Mara Quill.\n\nThe Tessel Ridge orchard opened in 1902 near the river.\n"
        item = {"passage": 1, "question": "Which office held the file?", "answer": "the county office",
                "quote": "Retrieved 3 June 2019 from the county office at Tessel Ridge by Mara Quill."}
        self.assertNotIn("question", [c.kind for c in cards_for(text, writer=CardWriter(item)).cards])

    def test_nothing_usable_falls_back_to_the_documents_sentences_and_says_so(self):
        for reply in ("Sure, here are some cards", '{"cards": 5}', "[]", '{"cards": []}', "{not json"):
            with self.subTest(reply=reply):
                card_set = cards_for(LIGHTHOUSE, writer=CardWriter(reply=reply), seed=1)
                self.assertTrue(card_set.cards)
                self.assertNotIn("question", [c.kind for c in card_set.cards])
                self.assertIn("Fake model", card_set.notice)

    def test_a_model_failure_falls_back_and_gives_the_reason(self):
        card_set = cards_for(LIGHTHOUSE, writer=CardWriter(error="Ollama isn't running on this computer."), seed=1)
        self.assertTrue(card_set.cards)
        self.assertIn("Ollama isn't running on this computer", card_set.notice)

    def test_reference_lists_are_not_shown_to_the_model(self):
        writer = CardWriter(reply='{"cards": []}')
        cards_for(WITH_REFERENCES, writer=writer, seed=1)
        self.assertIn("Tessel Ridge", writer.prompts[0])
        self.assertNotIn("Quillon", writer.prompts[0])

    def test_the_prompt_asks_for_the_number_of_cards_and_numbers_the_passages(self):
        writer = CardWriter(reply='{"cards": []}')
        cards_for(LIGHTHOUSE, count=7, writer=writer, seed=1)
        self.assertIn(f"Write {7 + SPARE_ITEMS} flashcards", writer.prompts[0])  # some will fail their checks
        self.assertIn("[1]", writer.prompts[0])
        self.assertIn("The lamp was first lit in 1871", writer.prompts[0])

    def test_no_more_cards_than_asked_for(self):
        self.assertEqual(len(cards_for(LIGHTHOUSE, count=1, writer=CardWriter(LAMP, REPAIRS)).cards), 1)

    def test_the_model_cannot_crowd_the_set_onto_one_passage(self):
        text = "\n\n".join(f"Part {w}\n\nThe {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran. Its {w} gate was painted by Tomas Reyes in {1950 + i} for the county."
                           for i, w in enumerate(["north", "south", "east"]))
        chunks = chunk_text(text, max_words=30)
        first = [{"passage": 1, "question": "Who planted the north orchard near the river?", "answer": "Mara Quill",
                  "quote": "The north orchard was planted in 1900 by Mara Quill near the river Corran."},
                 {"passage": 1, "question": "Who painted the north gate for the county?", "answer": "Tomas Reyes",
                  "quote": "Its north gate was painted by Tomas Reyes in 1950 for the county."}]
        card_set = build_cards(chunks, 2, title="H", writer=CardWriter(*first), seed=1)
        self.assertEqual(len(card_set.cards), 1)

    def test_extra_cards_are_ignored_even_when_each_passage_could_give_more(self):
        chunks = [chunk_text(f"The {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran. Its {w} gate was painted by Tomas Reyes in {1950 + i} for the county.")[0]
                  for i, w in enumerate(["north", "south"])]
        for n, chunk in enumerate(chunks):
            chunk.id = n
        items = [item for n, w in enumerate(["north", "south"], start=1) for item in (
            {"passage": n, "question": f"Who planted the {w} orchard near the river?", "answer": "Mara Quill",
             "quote": f"The {w} orchard was planted in {1899 + n} by Mara Quill near the river Corran."},
            {"passage": n, "question": f"Who painted the {w} gate for the county?", "answer": "Tomas Reyes",
             "quote": f"Its {w} gate was painted by Tomas Reyes in {1949 + n} for the county."})]
        self.assertEqual(len(build_cards(chunks, 3, title="H", writer=CardWriter(*items), seed=1).cards), 3)

    def test_passages_with_nothing_but_headings_are_not_sent(self):
        headings_only = Chunk(0, "Contents Chapter One", [Sentence("Contents", is_heading=True), Sentence("Chapter One", is_heading=True)])
        body = chunk_text(LIGHTHOUSE)
        for n, chunk in enumerate(body, start=1):
            chunk.id = n
        writer = CardWriter(reply='{"cards": []}')
        build_cards([headings_only, *body], 3, title="H", writer=writer, seed=1)
        self.assertNotIn("Contents Chapter One", writer.prompts[0])

    def test_spare_cards_are_thinned_evenly_to_the_number_asked_for(self):
        chunks = [chunk_text(f"The {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran.")[0]
                  for i, w in enumerate(["north", "south", "east", "west", "upper"])]
        for n, chunk in enumerate(chunks):
            chunk.id = n
        items = [{"passage": n, "question": f"Who planted orchard number {n} near the river?", "answer": "Mara Quill", "quote": chunks[n - 1].text}
                 for n in range(1, 6)]
        card_set = build_cards(chunks, 3, title="H", writer=CardWriter(*items), seed=1)
        self.assertEqual([c.passage.id for c in card_set.cards], [0, 2, 4])  # spread out, not the first three
        self.assertIsNone(card_set.notice)

    def test_a_wrong_passage_number_is_corrected_from_the_quote(self):
        chunks = [chunk_text(f"The {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran.")[0]
                  for i, w in enumerate(["north", "south"])]
        for n, chunk in enumerate(chunks):
            chunk.id = n
        item = {"passage": 1, "question": "Who planted the south orchard near the river?", "answer": "Mara Quill", "quote": chunks[1].text}
        card = build_cards(chunks, 1, title="H", writer=CardWriter(item), seed=1).cards[0]
        self.assertEqual((card.kind, card.passage.id), ("question", 1))

    def test_a_short_documents_spare_cards_count_even_if_one_passage_gets_most(self):
        line = "The orchard holds {} pear trees near the old mill in Corran."
        chunks = [chunk_text(" ".join(line.format(n) for n in numbers))[0] for numbers in ((11, 22, 33, 44), (55, 66))]
        for n, chunk in enumerate(chunks):
            chunk.id = n
        items = [{"passage": 1 if number < 50 else 2, "question": f"How large is row {number} of the orchard?", "answer": f"{number} trees", "quote": line.format(number)}
                 for number in (11, 22, 33, 44, 55)]
        card_set = build_cards(chunks, 5, title="H", writer=CardWriter(*items), seed=1)
        self.assertEqual(len(card_set.cards), 5)
        self.assertIsNone(card_set.notice)

    def test_the_same_quote_gives_one_card(self):
        again = {**LAMP, "question": "Which person lit the first lamp?"}
        self.assertEqual(len(cards_for(LIGHTHOUSE, count=2, writer=CardWriter(LAMP, again)).cards), 1)

    def test_cards_are_in_document_order_whatever_order_the_model_uses(self):
        text = "\n\n".join(f"Part {w}\n\nThe {w} orchard was planted in {1900 + i} by Mara Quill near the river Corran."
                           for i, w in enumerate(["north", "south", "east"]))
        chunks = chunk_text(text, max_words=20)
        passages = re.findall(r"^\[(\d+)\]", rag.cards.cards_prompt(chunks[:3], 3), re.M)
        self.assertEqual(passages, ["1", "2", "3"])
        items = [{"passage": n, "question": f"Which orchard is covered in part {n} of the guide?", "answer": ["north", "south", "east"][n - 1],
                  "quote": f"The {['north', 'south', 'east'][n - 1]} orchard was planted in {1899 + n} by Mara Quill near the river Corran."}
                 for n in (3, 1, 2)]
        card_set = build_cards(chunks, 3, title="H", writer=_FirstPassages(items), seed=1)
        ids = [c.passage.id for c in card_set.cards]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), 3)


class _FirstPassages(CardWriter):
    """Answers whichever passages it is sent by finding each quote among them."""

    def __init__(self, items):
        super().__init__(reply="")
        self.items = items

    def write(self, prompt, instruction=None):
        blocks = re.split(r"^\[(\d+)\][^\n]*\n", prompt, flags=re.M)
        where = {blocks[i + 1]: int(blocks[i]) for i in range(1, len(blocks) - 1, 2)}
        placed = []
        for item in self.items:
            passage = next((n for text, n in where.items() if item["quote"] in text), None)
            if passage:
                placed.append({**item, "passage": passage})
        return json.dumps({"cards": placed})


if __name__ == "__main__":
    unittest.main()
