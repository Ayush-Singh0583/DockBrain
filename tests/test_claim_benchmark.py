"""The claim benchmark's own machinery: reading model replies, choosing items, blind
labelling and scoring. All text here is invented; no model is called."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import claim_benchmark as cb  # noqa: E402
from rag.chunker import Chunk, Sentence  # noqa: E402
from rag.quiz import numbered_passages  # noqa: E402

PASSAGE = "Copper trees produce blue fruit during winter. Farmers harvest the fruit by hand in early spring."
QUOTE = "Copper trees produce blue fruit during winter."


def chunk(text, n=0):
    return Chunk(n, text, [Sentence(text)])


def prompt_for(*texts):
    return "Write things.\n\nPassages:\n\n" + numbered_passages([chunk(t, i) for i, t in enumerate(texts)])


def note(**changes):
    return {"id": "n", "document": "d", "kind": "note", "passage": PASSAGE, "quote": QUOTE,
            "claim": {"text": "Copper trees produce blue fruit during winter."}, **changes}


def card(**changes):
    return {"id": "c", "document": "d", "kind": "card", "passage": PASSAGE, "quote": QUOTE,
            "claim": {"question": "When do copper trees fruit?", "answer": "During winter"}, **changes}


def quiz(**changes):
    return {"id": "q", "document": "d", "kind": "quiz", "passage": PASSAGE, "quote": QUOTE,
            "claim": {"question": "What colour is the fruit of copper trees?",
                      "options": ["Blue", "Green", "Yellow", "Violet"], "answer": 0}, **changes}


class ReadingReplies(unittest.TestCase):
    def test_passages_come_back_in_order_with_or_without_section_lines(self):
        passages = [Chunk(0, "One two.", [Sentence("One two.", "Fruit")]), chunk("Three four.", 1)]
        prompt = "Rules.\n\nPassages:\n\n" + numbered_passages(passages)
        self.assertEqual(cb.passages_in_prompt(prompt), ["One two.", "Three four."])

    def test_a_note_reply_gives_its_points_and_ignores_its_suggested_questions(self):
        reply = json.dumps({"summary": "S", "questions": ["Why?"], "sections": [
            {"heading": "H", "points": [{"text": "Trees fruit in winter.", "passage": 1, "quote": QUOTE}]}]})
        found = cb.candidates_from_reply(prompt_for(PASSAGE), reply)
        self.assertEqual([(c["kind"], c["claim"], c["passage"], c["quote"]) for c in found],
                         [("note", {"text": "Trees fruit in winter."}, PASSAGE, QUOTE)])

    def test_a_card_reply(self):
        reply = json.dumps({"cards": [{"passage": 1, "question": "When?", "answer": "Winter", "quote": QUOTE}]})
        found = cb.candidates_from_reply(prompt_for(PASSAGE), reply)
        self.assertEqual([(c["kind"], c["claim"]) for c in found], [("card", {"question": "When?", "answer": "Winter"})])

    def test_a_quiz_reply(self):
        item = {"passage": 1, "question": "What?", "options": ["A", "B"], "answer": 1, "quote": QUOTE}
        found = cb.candidates_from_reply(prompt_for(PASSAGE), json.dumps({"questions": [item]}))
        self.assertEqual([(c["kind"], c["claim"]) for c in found],
                         [("quiz", {"question": "What?", "options": ["A", "B"], "answer": 1})])

    def test_a_quote_found_in_another_passage_moves_the_item_there_as_the_app_does(self):
        other = "Silver hedges grow slowly on stony hillsides near the coast."
        reply = json.dumps({"cards": [{"passage": 1, "question": "When?", "answer": "Winter", "quote": QUOTE}]})
        self.assertEqual(cb.candidates_from_reply(prompt_for(other, PASSAGE), reply)[0]["passage"], PASSAGE)

    def test_items_the_checks_would_reject_are_kept_so_wrong_rejections_can_be_measured(self):
        reply = json.dumps({"cards": [{"passage": 1, "question": "When?", "answer": "Winter", "quote": "Not in the passage at all, really."}]})
        self.assertEqual(len(cb.candidates_from_reply(prompt_for(PASSAGE), reply)), 1)

    def test_malformed_items_are_skipped(self):
        bad = [{"passage": 9, "question": "Q?", "answer": "A", "quote": QUOTE},
               {"passage": 1, "question": 3, "answer": "A", "quote": QUOTE},
               {"passage": 1, "question": "Q?", "answer": "A", "quote": None},
               {"passage": 1, "question": "Q?", "answer": 7, "quote": QUOTE},
               "not an item"]
        self.assertEqual(cb.candidates_from_reply(prompt_for(PASSAGE), json.dumps({"cards": bad})), [])
        questions = [{"passage": 1, "question": "Q?", "options": ["A", "B"], "answer": 5, "quote": QUOTE},
                     {"passage": 1, "question": "Q?", "options": "AB", "answer": 0, "quote": QUOTE},
                     {"passage": 1, "question": "Q?", "options": ["A", "B"], "answer": True, "quote": QUOTE}]
        self.assertEqual(cb.candidates_from_reply(prompt_for(PASSAGE), json.dumps({"questions": questions})), [])
        points = {"sections": [{"heading": "H", "points": [{"text": 5, "passage": 1, "quote": QUOTE}, "not a point"]}, "not a section"]}
        self.assertEqual(cb.candidates_from_reply(prompt_for(PASSAGE), json.dumps(points)), [])

    def test_a_reply_that_is_not_json_gives_nothing(self):
        self.assertEqual(cb.candidates_from_reply(prompt_for(PASSAGE), "Sorry, I can't."), [])
        self.assertEqual(cb.candidates_from_reply(prompt_for(PASSAGE), "{this is not json}"), [])


class UsesTheRealChecks(unittest.TestCase):
    def test_each_kind_goes_to_its_own_check(self):
        self.assertTrue(cb.accepted(note()))
        self.assertTrue(cb.accepted(card()))
        self.assertTrue(cb.accepted(quiz()))

    def test_a_quote_that_is_not_in_the_passage_is_rejected_for_every_kind(self):
        for item in (note, card, quiz):
            self.assertFalse(cb.accepted(item(quote="Silver hedges grow slowly on stony hillsides.")))

    def test_rules_only_one_kind_has_are_applied(self):
        # A card's front must not contain its answer; a note has no such rule.
        self.assertFalse(cb.accepted(card(claim={"question": "Do trees fruit during winter?", "answer": "during winter"})))
        # A quiz's quote must not also support a wrong option.
        options = {"question": "What colour?", "options": ["Blue fruit", "Winter fruit"], "answer": 0}
        self.assertFalse(cb.accepted(quiz(claim=options)))


def candidates(kind, documents, each):
    return [{**{"note": note, "card": card, "quiz": quiz}[kind](), "id": f"{d}-{kind}-{i}", "document": d}
            for d in documents for i in range(each)]


QUOTAS = {"plain": {"note": 2, "card": 2, "quiz": 1}, "altered": {"note": 2, "card": 1, "quiz": 1}}


class Choosing(unittest.TestCase):
    def setUp(self):
        self.pool = [c for k in ("note", "card", "quiz") for c in candidates(k, ("a", "b", "c"), 4)]

    def test_the_same_seed_chooses_the_same_items(self):
        self.assertEqual(cb.select(self.pool, 7, QUOTAS), cb.select(self.pool, 7, QUOTAS))
        self.assertNotEqual(cb.select(self.pool, 7, QUOTAS), cb.select(self.pool, 8, QUOTAS))

    def test_quotas_are_met_and_an_altered_claim_never_also_appears_unaltered(self):
        plain, bases = cb.select(self.pool, 7, QUOTAS)
        for group, quota in ((plain, QUOTAS["plain"]), (bases, QUOTAS["altered"])):
            self.assertEqual({k: sum(c["kind"] == k for c in group) for k in quota}, quota)
        self.assertFalse({c["id"] for c in plain} & {c["id"] for c in bases})

    def test_items_are_spread_across_documents(self):
        plain, _ = cb.select(self.pool, 7, {"plain": {"note": 3, "card": 0, "quiz": 0}, "altered": {"note": 0, "card": 0, "quiz": 0}})
        self.assertEqual(sorted(c["document"] for c in plain), ["a", "b", "c"])

    def test_only_claims_the_checks_accept_are_altered(self):
        rejected = {**note(), "id": "x-note-0", "document": "x", "quote": "Silver hedges grow slowly on stony hillsides."}
        for seed in range(30):
            pool = [rejected] + candidates("note", ("a",), 6)
            _, bases = cb.select(pool, seed, {"plain": {"note": 1, "card": 0, "quiz": 0}, "altered": {"note": 3, "card": 0, "quiz": 0}})
            self.assertNotIn("x-note-0", [c["id"] for c in bases])

    def test_a_missing_alteration_is_named(self):
        _, bases = cb.select(self.pool, 7, QUOTAS)
        with self.assertRaises(cb.MissingAlterations) as caught:
            cb.build_items(self.pool, {}, 7, QUOTAS)
        self.assertEqual(sorted(c["id"] for c in caught.exception.bases), sorted(c["id"] for c in bases))

    def test_built_items_record_what_was_changed_and_how(self):
        _, bases = cb.select(self.pool, 7, QUOTAS)
        alterations = {}
        for c in bases:
            field = {"note": "text", "card": "answer", "quiz": "answer"}[c["kind"]]
            alterations[c["id"]] = {"type": "negation", "changes": {field: 1 if c["kind"] == "quiz" else "changed"}}
        items = cb.build_items(self.pool, alterations, 7, QUOTAS)
        self.assertEqual(len(items), 9)
        self.assertEqual(sorted(i["id"] for i in items), [f"c{n:02}" for n in range(1, 10)])
        altered = [i for i in items if i["origin"] == "altered"]
        self.assertEqual(len(altered), 4)
        for item in altered:
            self.assertEqual(item["alteration"], "negation")
            self.assertNotEqual(item["claim"], item["original"])
        for item in items:
            if item["origin"] == "model":
                self.assertIsNone(item["alteration"])

    def test_an_unknown_alteration_type_is_refused(self):
        _, bases = cb.select(self.pool, 7, QUOTAS)
        alterations = {c["id"]: {"type": "negation", "changes": {"answer": 1} if c["kind"] != "note" else {"text": "x"}} for c in bases}
        alterations[bases[0]["id"]]["type"] = "made-up"
        with self.assertRaisesRegex(ValueError, "unknown alteration"):
            cb.build_items(self.pool, alterations, 7, QUOTAS)

    def test_an_alteration_that_changes_nothing_is_refused(self):
        _, bases = cb.select(self.pool, 7, QUOTAS)
        alterations = {c["id"]: {"type": "negation", "changes": {"answer": 1} if c["kind"] != "note" else {"text": "x"}} for c in bases}
        alterations[bases[0]["id"]]["changes"] = {}
        with self.assertRaisesRegex(ValueError, "changes nothing"):
            cb.build_items(self.pool, alterations, 7, QUOTAS)

    def test_altered_items_are_mixed_in_not_grouped(self):
        pool = [c for k in ("note", "card", "quiz") for c in candidates(k, ("a", "b", "c"), 20)]
        quotas = {"plain": {"note": 10, "card": 8, "quiz": 6}, "altered": {"note": 10, "card": 8, "quiz": 6}}
        _, bases = cb.select(pool, 7, quotas)
        alterations = {c["id"]: {"type": "number", "changes": {"answer": 1} if c["kind"] != "note" else {"text": "x"}} for c in bases}
        origins = [i["origin"] for i in cb.build_items(pool, alterations, 7, quotas)]
        self.assertNotEqual(origins, sorted(origins))
        self.assertNotEqual(origins, sorted(origins, reverse=True))


class WhatTheLabellerSees(unittest.TestCase):
    def secret(self, item):
        return {**item, "origin": "SECRET-ORIGIN", "alteration": "SECRET-TYPE", "original": {"text": "SECRET-ORIGINAL"},
                "from": "SECRET-FROM", "quote": "SECRET-QUOTE"}

    def test_nothing_reveals_how_an_item_was_made(self):
        for item in (note, card, quiz):
            self.assertNotIn("SECRET", cb.render(self.secret(item())))

    def test_the_passage_and_the_whole_claim_are_shown(self):
        shown = " ".join(cb.render(note()).split())
        self.assertIn(" ".join(PASSAGE.split()), shown)
        self.assertIn("Copper trees produce blue fruit during winter.", shown)
        shown = cb.render(card())
        self.assertIn("When do copper trees fruit?", shown)
        self.assertIn("During winter", shown)

    def test_a_quiz_shows_every_option_and_which_is_marked_correct(self):
        shown = cb.render(quiz(claim={"question": "Colour?", "options": ["Blue", "Green"], "answer": 1}))
        self.assertIn("Blue", shown)
        self.assertRegex(shown, r"(?i)marked correct:\s*Green")


class Labelling(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "labels.json"
        self.items = [{**note(), "id": f"c0{n}"} for n in range(1, 4)]
        self.output = []

    def run_label(self, *answers):
        answers = iter(answers)
        def read(_prompt=""):
            try:
                return next(answers)
            except StopIteration:
                raise EOFError from None
        cb.label(self.items, self.path, read=read, write=self.output.append)

    def saved(self):
        return json.loads(self.path.read_text())["labels"]

    def test_answers_are_recorded(self):
        self.run_label("Sam", "y", "n", "u")
        self.assertEqual(self.saved(), {"c01": "supported", "c02": "not_supported", "c03": "unsure"})
        self.assertEqual(json.loads(self.path.read_text())["labeller"], "Sam")

    def test_quitting_keeps_earlier_answers_and_resuming_continues_after_them(self):
        self.run_label("Sam", "y", "q", "n")  # nothing after q is taken as an answer
        self.assertEqual(self.saved(), {"c01": "supported"})
        self.run_label("n", "y")
        self.assertEqual(self.saved(), {"c01": "supported", "c02": "not_supported", "c03": "supported"})

    def test_input_ending_early_loses_nothing(self):
        self.run_label("Sam", "y")
        self.assertEqual(self.saved(), {"c01": "supported"})

    def test_back_lets_an_answer_be_changed(self):
        self.run_label("Sam", "y", "b", "n", "y", "y")
        self.assertEqual(self.saved(), {"c01": "not_supported", "c02": "supported", "c03": "supported"})

    def test_back_on_the_first_item_stays_there(self):
        self.run_label("Sam", "b", "y")
        self.assertEqual(self.saved(), {"c01": "supported"})

    def test_an_unknown_answer_asks_again_without_recording(self):
        self.run_label("Sam", "maybe", "y")
        self.assertEqual(self.saved(), {"c01": "supported"})
        self.assertTrue(any("y, n, u, b or q" in line for line in self.output))

    def test_a_finished_set_says_so(self):
        self.run_label("Sam", "y", "y", "y")
        self.output.clear()
        self.run_label()
        self.assertTrue(any("All 3" in line for line in self.output))


class Scoring(unittest.TestCase):
    ITEMS = [
        {"id": "a", "kind": "note", "origin": "model", "alteration": None},
        {"id": "b", "kind": "note", "origin": "model", "alteration": None},
        {"id": "c", "kind": "card", "origin": "altered", "alteration": "negation"},
        {"id": "d", "kind": "card", "origin": "altered", "alteration": "negation"},
        {"id": "e", "kind": "quiz", "origin": "altered", "alteration": "number"},
        {"id": "f", "kind": "quiz", "origin": "model", "alteration": None},
        {"id": "g", "kind": "note", "origin": "model", "alteration": None},
    ]
    LABELS = {"a": "supported", "b": "supported", "c": "not_supported", "d": "not_supported",
              "e": "supported", "f": "not_supported", "g": "unsure"}
    ACCEPTED = {"a", "c", "e", "f", "g"}

    def score(self, labels=None):
        return cb.score(self.ITEMS, self.LABELS if labels is None else labels, check=lambda i: i["id"] in self.ACCEPTED)

    def test_counts_both_kinds_of_mistake(self):
        result = self.score()
        self.assertEqual((result["not_supported"], result["wrongly_accepted"]), (3, 2))
        self.assertEqual((result["supported"], result["wrongly_rejected"]), (3, 1))

    def test_unsure_and_unlabelled_items_are_not_counted_as_either(self):
        result = self.score({"a": "supported", "g": "unsure"})
        self.assertEqual((result["total"], result["labelled"], result["unsure"]), (7, 2, 1))
        self.assertEqual((result["supported"], result["not_supported"]), (1, 0))

    def test_broken_down_by_kind(self):
        by_kind = self.score()["by_kind"]
        self.assertEqual(by_kind["note"], {"not_supported": 0, "wrongly_accepted": 0, "supported": 2, "wrongly_rejected": 1})
        self.assertEqual(by_kind["card"], {"not_supported": 2, "wrongly_accepted": 1, "supported": 0, "wrongly_rejected": 0})
        self.assertEqual(by_kind["quiz"], {"not_supported": 1, "wrongly_accepted": 1, "supported": 1, "wrongly_rejected": 0})

    def test_model_written_claims_people_rejected_are_reported_apart(self):
        result = self.score()
        self.assertEqual((result["model_not_supported"], result["model_labelled"]), (1, 3))

    def test_an_altered_claim_a_person_called_supported_is_flagged_for_a_second_look(self):
        self.assertEqual(self.score()["altered_but_supported"], ["e"])

    def test_altered_claims_are_tallied_by_type_before_any_labels_exist(self):
        result = self.score({})
        self.assertEqual(result["altered"], {"negation": {"total": 2, "accepted": 1}, "number": {"total": 1, "accepted": 1}})

    def test_the_report_says_when_nothing_has_been_labelled_by_a_person(self):
        text = cb.report(self.score({}))
        self.assertIn("No human labels", text)
        self.assertIn("negation", text)

    def test_the_report_gives_the_counts(self):
        text = cb.report(self.score(), labeller="Sam")
        self.assertIn("Sam", text)
        self.assertRegex(text, r"2 of 3")
        self.assertRegex(text, r"1 of 3")


class TheFrozenSet(unittest.TestCase):
    """The committed benchmark itself."""

    @classmethod
    def setUpClass(cls):
        cls.items = json.loads(cb.ITEMS_PATH.read_text(encoding="utf-8"))["items"]

    def test_it_has_the_planned_shape(self):
        self.assertEqual(len(self.items), 60)
        self.assertEqual(len({i["id"] for i in self.items}), 60)
        self.assertEqual({i["origin"] for i in self.items}, {"model", "altered"})
        self.assertEqual(sum(i["origin"] == "altered" for i in self.items), 25)
        self.assertEqual({i["kind"] for i in self.items}, {"note", "card", "quiz"})

    def test_no_claim_appears_both_altered_and_unaltered(self):
        sources = [i["from"] for i in self.items]
        self.assertEqual(len(sources), len(set(sources)))

    def test_every_altered_claim_really_differs_from_its_original(self):
        for item in self.items:
            if item["origin"] == "altered":
                self.assertIn(item["alteration"], cb.ALTERATION_TYPES)
                self.assertNotEqual(item["claim"], item["original"], item["id"])

    def test_every_item_can_be_shown_and_checked(self):
        for item in self.items:
            self.assertIn(cb.accepted(item), (True, False))
            self.assertTrue(cb.render(item).strip())

    def test_it_comes_from_more_than_one_document(self):
        self.assertGreaterEqual(len({i["document"] for i in self.items}), 4)

    def test_it_rebuilds_exactly_from_the_candidates_and_alterations(self):
        candidates = json.loads(cb.CANDIDATES_PATH.read_text(encoding="utf-8"))["candidates"]
        alterations = json.loads(cb.ALTERATIONS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(cb.build_items(candidates, alterations), self.items)


if __name__ == "__main__":
    unittest.main()
