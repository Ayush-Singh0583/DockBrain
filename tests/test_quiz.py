"""Quiz generation and grading (rag/quiz.py), without a server or network.

Documents here are made up. A fake writer stands in for Gemini or Claude, so the checks
on model-written questions run offline.
"""
import http.server
import json
import re
import threading
import types
import unittest
from unittest import mock

import rag.quiz
from rag.chunker import Chunk, Sentence, chunk_text
from rag.generator import ClaudeGenerator, ExtractiveGenerator, GeminiGenerator
from rag.quiz import QUIZ_INSTRUCTION, InsufficientContent, build_quiz, grade, verbatim_quote, writer_for

ORCHARD = """Orchard Report

Planting

The orchard was planted in 1998 by Mara Lindqvist near the town of Eskdale.
It covers 42 hectares on a gentle slope that faces south.

Varieties

The main variety is Bramley, a cooking apple with a sharp flavour.
Smaller rows grow Cox and Egremont Russet for the farm shop in Keswick.

Harvest

Picking starts in late September and lasts about six weeks.
In 2023 the orchard produced 310 tonnes of fruit, up from 255 tonnes in 2021.

Pests

Codling moth is the most damaging pest in the orchard, according to Tom Okafor.
Grease bands on the trunks stop winter moth from climbing into the trees.

Staff

The orchard employs 14 people all year and 60 pickers at harvest.
Ruth Adeyemi manages the cold store, which holds up to 400 tonnes.
"""


REFERENCES = """
References

The Quillon survey of Eskdale orchards was printed in 1874 by the county office.
Quillon described 40 varieties that were grown near Keswick in that year.
Quillon gave a second talk about Eskdale orchards in 1880 at the county hall.
"""


def chunks(text: str = ORCHARD, words: int = 30):
    return chunk_text(text, max_words=words)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class FakeWriter:
    """Plays a model: returns a scripted reply, or raises like a failing provider."""

    name = "Fake model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    def write(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise RuntimeError(self.error)
        return self.reply(prompt) if callable(self.reply) else self.reply


def passages_in(prompt: str) -> list[str]:
    """The numbered passages a writer was shown, in order."""
    return [m.group(1).strip() for m in re.finditer(r"^\[\d+\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", prompt, re.M | re.S)]


class OfflineQuiz(unittest.TestCase):
    def test_builds_the_requested_number_of_multiple_choice_questions(self):
        quiz = build_quiz(chunks(), 5, title="Orchard", seed=1)
        self.assertEqual(len(quiz.questions), 5)
        self.assertIsNone(quiz.notice)
        for q in quiz.questions:
            ids = [o.id for o in q.options]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreaterEqual(len(q.options), 3)
            self.assertIn(q.correct_option_id, ids)
            texts = [normalise(o.text) for o in q.options]
            self.assertEqual(len(texts), len(set(texts)), "options must differ")

    def test_every_answer_is_stated_in_its_cited_passage(self):
        doc = chunks()
        for q in build_quiz(doc, 5, title="Orchard", seed=2).questions:
            self.assertIn(q.passage, doc)  # cites a real passage of this document
            correct = next(o.text for o in q.options if o.id == q.correct_option_id)
            # The supporting sentence is in the passage, and filling the blank with the
            # correct option gives back exactly that sentence.
            self.assertIn(normalise(q.quote), normalise(q.passage.text))
            self.assertEqual(normalise(q.prompt_statement.replace("_____", correct)), normalise(q.quote))
            self.assertIn(q.quote, q.explanation)

    def test_wrong_options_come_from_the_document_and_do_not_fit_the_sentence(self):
        text = normalise(ORCHARD)
        for q in build_quiz(chunks(), 5, title="Orchard", seed=3).questions:
            for option in q.options:
                self.assertIn(normalise(option.text), text)  # nothing invented
                if option.id != q.correct_option_id:
                    self.assertNotIn(normalise(option.text), normalise(q.quote))

    def test_questions_come_from_different_parts_of_the_document(self):
        quiz = build_quiz(chunks(), 5, title="Orchard", seed=4)
        self.assertGreater(len({q.passage.id for q in quiz.questions}), 2)

    def test_no_sentence_is_asked_about_twice(self):
        # Passages overlap by one sentence. Without headings, that sentence is a statement
        # that could be asked about twice; asking for every question exposes any repeat.
        plain = " ".join(line for line in ORCHARD.splitlines() if line.endswith("."))
        doc = chunks(plain)
        self.assertTrue(any(a.sentences[-1].text == b.sentences[0].text for a, b in zip(doc, doc[1:])))
        quotes = [q.quote for q in build_quiz(doc, 10, title="Orchard", seed=4).questions]
        self.assertEqual(len(quotes), len(set(quotes)))

    def test_a_short_quiz_still_covers_the_start_and_the_end(self):
        doc = chunks()
        ids = [q.passage.id for q in build_quiz(doc, 3, title="Orchard", seed=4).questions]
        self.assertLessEqual(min(ids), len(doc) // 3)
        self.assertGreaterEqual(max(ids), 2 * (len(doc) - 1) // 3)

    def test_the_same_seed_gives_the_same_quiz(self):
        def summary(quiz):
            return [(q.prompt, [o.text for o in q.options], q.correct_option_id) for q in quiz.questions]

        self.assertEqual(summary(build_quiz(chunks(), 4, title="O", seed=7)), summary(build_quiz(chunks(), 4, title="O", seed=7)))

    def test_a_short_document_gives_fewer_questions_and_says_so(self):
        doc = chunks("Ruth Adeyemi planted 42 trees in 1998 near Eskdale. Tom Okafor planted 17 more trees in 2003 near Keswick.")
        quiz = build_quiz(doc, 5, title="Short", seed=1)
        self.assertGreaterEqual(len(quiz.questions), 1)
        self.assertLess(len(quiz.questions), 5)
        self.assertIn(f"Only {len(quiz.questions)}", quiz.notice)

    def test_a_document_without_statements_is_reported_as_insufficient(self):
        for text in ("Contents\n\nIntroduction\n\nMethods\n\nResults", "Hello.", ""):
            with self.subTest(text=text), self.assertRaises(InsufficientContent):
                build_quiz(chunks(text), 5, title="Empty", seed=1)

    def test_the_number_of_questions_must_be_1_to_10(self):
        for count in (0, 11, -1, True, 2.5, "5"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                build_quiz(chunks(), count, title="O", seed=1)

    def test_contents_pages_and_thank_you_text_are_not_quizzed(self):
        text = (ORCHARD + "\n\nAcknowledgements\n\nWe thank Priya Natarajan and the 12 volunteers "
                "from Eskdale for their help in 2022.")
        for q in build_quiz(chunks(text), 10, title="O", seed=5).questions:
            self.assertNotIn("thank", q.quote.lower())


def model_reply(build):
    """A writer reply built from the passages it was shown: build(index, passage) -> item or None."""

    def reply(prompt):
        items = [build(i, p) for i, p in enumerate(passages_in(prompt), start=1)]
        return json.dumps({"questions": [item for item in items if item]})

    return reply


def sentence_with(passage: str, words: str):
    return next((s for s in re.split(r"(?<=[.!?])\s+", passage) if words in s), None)


def faithful(i, passage):
    """A well-behaved model: asks about a fact and quotes the sentence that states it."""
    sentence = sentence_with(passage, "1998")
    if sentence:
        return {"passage": i, "question": "When was the orchard planted?",
                "options": ["1998", "2021", "2023", "1987"], "answer": 0, "quote": sentence}
    return None


def any_fact(i, passage):
    """A grounded question about the first number in a passage's sentences, if it has one."""
    for sentence in re.split(r"(?<=[.!?])\s+", passage):
        numbers = re.findall(r"\b\d+\b", sentence)
        if numbers and len(sentence.split()) >= 6:
            wrong = [n for n in ("7", "13", "999") if n not in sentence]
            return {"passage": i, "question": f"Which number appears in passage {i}?",
                    "options": [numbers[0], *wrong], "answer": 0, "quote": sentence}
    return None


class ModelWrittenQuiz(unittest.TestCase):
    def test_the_model_sees_only_document_passages_and_its_valid_questions_are_used(self):
        writer = FakeWriter(model_reply(faithful))
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertEqual(len(writer.prompts), 1)  # one request for the whole quiz
        for passage in passages_in(writer.prompts[0]):
            self.assertIn(normalise(passage), normalise(ORCHARD))
        written = [q for q in quiz.questions if q.prompt == "When was the orchard planted?"]
        self.assertEqual(len(written), 1)
        q = written[0]
        self.assertEqual(next(o.text for o in q.options if o.id == q.correct_option_id), "1998")
        self.assertIn("1998", q.passage.text)
        self.assertIn(q.quote, q.explanation)
        self.assertEqual(quiz.engine, "Fake model")

    def test_a_quote_that_is_not_in_the_passage_is_rejected(self):
        def invented(i, passage):
            return {"passage": i, "question": "Who owns the orchard?", "options": ["Anna Berg", "Mara Lindqvist", "Tom Okafor", "Cox"],
                    "answer": 0, "quote": "The orchard is owned by Anna Berg."}

        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(model_reply(invented)))
        self.assertEqual(len(quiz.questions), 3)
        for q in quiz.questions:
            self.assertNotIn("Anna Berg", " ".join(o.text for o in q.options))
            self.assertIn(normalise(q.quote), normalise(q.passage.text))
        self.assertIn("rebuilt", quiz.notice)

    def test_an_answer_the_quote_does_not_support_is_rejected(self):
        def unsupported(i, passage):
            sentence = sentence_with(passage, "planted")
            if not sentence:
                return None
            return {"passage": i, "question": "Which county is it in?", "options": ["Cumbria", "Kent", "Devon", "Fife"],
                    "answer": 0, "quote": sentence}

        writer = FakeWriter(model_reply(unsupported))
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertIn("planted", writer.prompts[0])  # the model was shown the sentence it misused
        self.assertNotIn("Which county is it in?", [q.prompt for q in quiz.questions])

    def test_a_wrong_option_the_quote_also_supports_is_rejected(self):
        def ambiguous(i, passage):
            sentence = sentence_with(passage, "Cox")
            if not sentence:
                return None
            return {"passage": i, "question": "Which variety grows in the smaller rows?",
                    "options": ["Cox", "Egremont Russet", "Gala", "Fuji"], "answer": 0, "quote": sentence}

        writer = FakeWriter(model_reply(ambiguous))
        quiz = build_quiz(chunks(), 5, title="O", seed=1, writer=writer)
        self.assertIn("Cox", writer.prompts[0])  # the model was shown the sentence it misused
        self.assertNotIn("Which variety grows in the smaller rows?", [q.prompt for q in quiz.questions])

    def test_a_question_for_a_passage_that_was_not_sent_is_ignored(self):
        def misnumbered(i, passage):
            item = faithful(i, passage)
            return item and {**item, "passage": bad}

        for bad in (0, -1, 99, "x", True, None):
            with self.subTest(passage=bad):
                quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(model_reply(misnumbered)))
                self.assertNotIn("When was the orchard planted?", [q.prompt for q in quiz.questions])

    def test_the_model_cannot_crowd_the_quiz_onto_one_passage(self):
        def greedy(prompt):
            first = passages_in(prompt)[0]
            items = [{"passage": 1, "question": f"Question {n} about passage one?", "options": [answer, *wrong],
                      "answer": 0, "quote": sentence_with(first, answer)}
                     for n, (answer, wrong) in enumerate([("1998", ["2021", "2023", "1987"]),
                                                          ("42", ["14", "60", "400"])])]
            return json.dumps({"questions": [i for i in items if i["quote"]]})

        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(greedy))
        written = [q for q in quiz.questions if q.prompt.startswith("Question ")]
        self.assertEqual(len(written), 1)  # one question per passage when there are enough passages
        self.assertEqual(len(quiz.questions), 1)  # and nothing built offline to make up the number

    def test_questions_are_in_document_order_whatever_order_the_model_uses(self):
        def backwards(prompt):
            items = json.loads(model_reply(any_fact)(prompt))["questions"]
            return json.dumps({"questions": items[::-1]})

        quiz = build_quiz(chunks(), 4, title="O", seed=1, writer=FakeWriter(backwards))
        ids = [q.passage.id for q in quiz.questions]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(any(q.prompt.startswith("Which number") for q in quiz.questions))

    def test_the_model_is_asked_for_a_few_spares_since_some_fail_their_checks(self):
        writer = FakeWriter('{"questions": []}')
        build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertIn(f"Write {3 + rag.quiz.SPARE_ITEMS} multiple-choice questions", writer.prompts[0])

    def test_spare_questions_are_thinned_to_the_number_asked_for(self):
        quiz = build_quiz(chunks(), 2, title="O", seed=1, writer=FakeWriter(model_reply(any_fact)))
        self.assertEqual(len(quiz.questions), 2)
        self.assertIsNone(quiz.notice)

    def test_a_wrong_passage_number_is_corrected_from_the_quote(self):
        def renumbered(i, passage):
            item = faithful(i, passage)
            return item and {**item, "passage": 3 if i != 3 else 1}

        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(model_reply(renumbered)))
        question = next(q for q in quiz.questions if q.prompt == "When was the orchard planted?")
        self.assertIn(normalise(question.quote), normalise(question.passage.text))

    def test_a_short_documents_spare_questions_count_even_if_one_passage_gets_most(self):
        first = "The orchard holds {} pear trees near the old mill in Eskdale."
        passages = [chunk_text(" ".join(first.format(n) for n in numbers))[0] for numbers in ((11, 22, 33, 44), (55, 66))]
        for n, passage in enumerate(passages):
            passage.id = n
        items = [{"passage": 1 if number < 50 else 2, "question": f"Which count goes with row {number} of the orchard?",
                  "options": [str(number), "7001", "7002", "7003"], "answer": 0, "quote": first.format(number)}
                 for number in (11, 22, 33, 44, 55)]
        quiz = build_quiz(passages, 5, title="O", seed=1, writer=FakeWriter(json.dumps({"questions": items})))
        self.assertEqual(len(quiz.questions), 5)
        self.assertIsNone(quiz.notice)

    def test_a_model_can_quiz_a_document_with_no_names_or_numbers(self):
        text = ("The orchard keeps cold air near the ground during the night. "
                "The pickers prefer dry mornings because wet fruit bruises easily.")
        item = {"passage": 1, "question": "Why do pickers prefer dry mornings?", "answer": 0,
                "options": ["Wet fruit bruises easily", "The ladders are lighter", "The sun is warmer", "The carts roll faster"],
                "quote": "The pickers prefer dry mornings because wet fruit bruises easily."}
        with self.assertRaises(InsufficientContent):
            build_quiz(chunk_text(text), 1, title="O", seed=1)  # nothing to blank out without a model
        quiz = build_quiz(chunk_text(text), 1, title="O", seed=1, writer=FakeWriter(json.dumps({"questions": [item]})))
        self.assertEqual([q.prompt for q in quiz.questions], [item["question"]])

    def test_passages_with_nothing_but_headings_are_not_sent_to_the_model(self):
        headings = Chunk(0, "Contents Chapter One", [Sentence("Contents", is_heading=True), Sentence("Chapter One", is_heading=True)])
        body = chunks()
        for n, chunk in enumerate(body, start=1):
            chunk.id = n
        writer = FakeWriter('{"questions": []}')
        build_quiz([headings, *body], 3, title="O", seed=1, writer=writer)
        self.assertNotIn("Contents Chapter One", writer.prompts[0])

    def test_questions_that_fail_are_dropped_when_others_pass(self):
        def first_only(i, passage):
            return faithful(i, passage) if i == 1 else {"passage": i, "question": "Who owns the orchard?",
                                                        "options": ["Anna Berg", "Mara", "Tom", "Cox"], "answer": 0,
                                                        "quote": "The orchard is owned by Anna Berg."}

        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(model_reply(first_only)))
        self.assertEqual([q.prompt for q in quiz.questions], ["When was the orchard planted?"])
        self.assertEqual([q.prompt_statement for q in quiz.questions], [None])  # not rebuilt offline
        self.assertIn("Only 1 question", quiz.notice)
        self.assertNotIn("rebuilt", quiz.notice)

    def test_a_question_about_the_document_itself_is_rejected(self):
        def about_itself(i, passage):
            item = faithful(i, passage)
            return item and {**item, "question": "When was the orchard planted, according to this passage?"}

        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(model_reply(about_itself)))
        self.assertNotIn("When was the orchard planted, according to this passage?", [q.prompt for q in quiz.questions])

    def test_reference_lists_are_not_shown_to_the_model(self):
        writer = FakeWriter('{"questions": []}')
        build_quiz(chunks(ORCHARD + REFERENCES), 3, title="O", seed=1, writer=writer)
        self.assertNotIn("Quillon", writer.prompts[0])
        self.assertIn("orchard", writer.prompts[0])

    def test_offline_questions_skip_reference_lists_too(self):
        for seed in range(8):
            quiz = build_quiz(chunks(ORCHARD + REFERENCES), 8, title="O", seed=seed)
            self.assertFalse([q.quote for q in quiz.questions if "Quillon" in q.quote])

    def test_an_unreadable_reply_falls_back_to_questions_from_the_document(self):
        for reply in ("Sure! Here are some questions...", "{\"questions\": 5}", "[]", "{not json"):
            with self.subTest(reply=reply):
                quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=FakeWriter(reply))
                self.assertEqual(len(quiz.questions), 3)
                self.assertIn("rebuilt", quiz.notice)

    def test_a_provider_failure_still_gives_a_grounded_quiz_and_says_why(self):
        writer = FakeWriter(error="Gemini's usage limit was reached. Wait a minute and try again.")
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertEqual(len(quiz.questions), 3)
        self.assertIn("usage limit", quiz.notice)
        for q in quiz.questions:
            self.assertIn(normalise(q.quote), normalise(q.passage.text))


class Grading(unittest.TestCase):
    def setUp(self):
        self.quiz = build_quiz(chunks(), 3, title="O", seed=1)
        self.q1, self.q2, self.q3 = self.quiz.questions

    def wrong(self, q):
        return next(o.id for o in q.options if o.id != q.correct_option_id)

    def test_scores_correct_wrong_and_unanswered_questions(self):
        result = grade(self.quiz, [(self.q1.id, self.q1.correct_option_id), (self.q2.id, self.wrong(self.q2))])
        self.assertEqual((result.correct, result.total), (1, 3))
        by_id = {r.question.id: r for r in result.results}
        self.assertTrue(by_id[self.q1.id].correct)
        self.assertFalse(by_id[self.q2.id].correct)
        self.assertEqual(by_id[self.q2.id].selected, self.wrong(self.q2))
        self.assertIsNone(by_id[self.q3.id].selected)
        self.assertFalse(by_id[self.q3.id].correct)

    def test_rejects_answers_that_do_not_belong_to_the_quiz(self):
        cases = {
            "unknown question": [("q99", "a")],
            "unknown option": [(self.q1.id, "z")],
            "answered twice": [(self.q1.id, self.q1.correct_option_id), (self.q1.id, self.wrong(self.q1))],
        }
        for name, answers in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                grade(self.quiz, answers)


def gemini_reply(text: str) -> dict:
    """A live-shaped Gemini interaction whose output is this text."""
    return {"status": "completed", "object": "interaction",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


class CheckingQuotes(unittest.TestCase):
    PASSAGE = chunk_text("The skin is covered in a protective layer of wax.[12][13] The flesh is pale, and it may be pink or green near the core.")[0]

    def test_a_quote_word_for_word_passes(self):
        self.assertIsNotNone(verbatim_quote("The skin is covered in a protective layer of wax.", self.PASSAGE))

    def test_reference_marks_do_not_count_either_way(self):
        self.assertIsNotNone(verbatim_quote("protective layer of wax. The flesh is pale", self.PASSAGE))
        self.assertIsNotNone(verbatim_quote("protective layer of wax.[12] The flesh", self.PASSAGE))

    def test_a_shortened_quote_passes_if_each_piece_is_there_in_order(self):
        for quote in ("The skin is covered ... of wax.", "The skin is covered … it may be pink"):
            with self.subTest(quote):
                self.assertIsNotNone(verbatim_quote(quote, self.PASSAGE))

    def test_punctuation_does_not_count(self):
        self.assertIsNotNone(verbatim_quote("the skin is covered, in a protective-layer of wax", self.PASSAGE))

    def test_different_words_still_fail(self):
        self.assertIsNone(verbatim_quote("the skin is coated in a protective layer of wax", self.PASSAGE))

    def test_shortening_cannot_hide_an_invented_piece(self):
        self.assertIsNone(verbatim_quote("The skin is covered ... of solid gold.", self.PASSAGE))

    def test_shortened_pieces_must_be_in_the_passages_order(self):
        self.assertIsNone(verbatim_quote("The flesh is pale ... The skin is covered", self.PASSAGE))

    def test_a_quote_from_elsewhere_or_too_short_fails(self):
        self.assertIsNone(verbatim_quote("The skin is covered in solid gold leaf.", self.PASSAGE))
        self.assertIsNone(verbatim_quote("The skin", self.PASSAGE))


class GeminiQuizWriter(unittest.TestCase):
    """The real Gemini adapter, against a local fake server: no network, no real key."""

    def setUp(self):
        self.replies, self.requests, self.headers = [], [], []
        self.respond = None  # or a function from the prompt to the model's reply text
        test = self

        class FakeGemini(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.requests.append(request)
                test.headers.append(self.headers)
                if test.respond:
                    status, body = 200, gemini_reply(test.respond(request["input"]))
                else:
                    status, body = test.replies.pop(0)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGemini)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for patcher in (mock.patch.object(GeminiGenerator, "BASE_URL", f"http://127.0.0.1:{server.server_port}/v1beta"),
                        mock.patch.object(GeminiGenerator, "RETRY_DELAYS", (0, 0))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.writer = writer_for(GeminiGenerator(api_key="test-key", model="gemini-test"))

    def test_sends_the_quiz_instructions_and_only_the_chosen_passages(self):
        self.respond = model_reply(faithful)  # a grounded question about whatever was sent
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=self.writer)
        self.assertEqual(len(self.requests), 1)
        sent = self.requests[0]
        self.assertEqual(self.headers[0]["x-goog-api-key"], "test-key")
        self.assertNotIn("test-key", json.dumps(sent))
        self.assertIs(sent["store"], False)
        self.assertEqual(sent["system_instruction"], QUIZ_INSTRUCTION)
        for passage in passages_in(sent["input"]):
            self.assertIn(normalise(passage), normalise(ORCHARD))
        self.assertEqual(quiz.engine, "Gemini gemini-test")
        self.assertIn("When was the orchard planted?", [q.prompt for q in quiz.questions])

    def test_cards_and_notes_can_give_the_model_their_own_instruction(self):
        self.replies = [(200, gemini_reply("{}"))]
        self.writer.write("the prompt", instruction="Write flashcards.")
        self.assertEqual(self.requests[0]["system_instruction"], "Write flashcards.")

    def test_an_overload_falls_back_after_the_attempt_budget(self):
        overload = (503, {"error": {"message": "high demand", "code": "service_unavailable"}})
        self.replies = [overload] * 3
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=self.writer)
        self.assertEqual(len(self.requests), 3)  # the same 3-attempt budget as one question
        self.assertEqual(len(quiz.questions), 3)
        self.assertIn("Gemini can't answer right now", quiz.notice)

    def test_a_daily_limit_is_not_retried(self):
        daily = (429, {"error": {"message": "limit: 20 requests per day on Free Tier", "code": "too_many_requests"}})
        self.replies = [daily]
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=self.writer)
        self.assertEqual(len(self.requests), 1)
        self.assertIn("daily free limit", quiz.notice)


class ClaudeQuizWriter(unittest.TestCase):
    """The real Claude adapter with a stand-in client (no network, no key)."""

    def writer(self, outcomes):
        calls, retries = [], []

        class Messages:
            def create(self, **request):
                calls.append(request)
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                text = outcome(request["messages"][0]["content"]) if callable(outcome) else outcome
                return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])

        class Client:
            beta = types.SimpleNamespace(messages=Messages())

            def with_options(self, max_retries):
                retries.append(max_retries)
                return self

        generator = ClaudeGenerator.__new__(ClaudeGenerator)  # skips the API key
        generator.model, generator.client = "claude-test", Client()
        return writer_for(generator), calls, retries

    def test_sends_the_quiz_instructions_and_uses_grounded_questions(self):
        writer, calls, retries = self.writer([model_reply(faithful)])
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertEqual(len(calls), 1)
        self.assertEqual(retries, [1])
        self.assertEqual(calls[0]["system"], QUIZ_INSTRUCTION)
        self.assertEqual(calls[0]["model"], "claude-test")
        self.assertIn("When was the orchard planted?", [q.prompt for q in quiz.questions])

    def test_cards_and_notes_can_give_the_model_their_own_instruction(self):
        writer, calls, _ = self.writer(["{}"])
        writer.write("the prompt", instruction="Write flashcards.")
        self.assertEqual(calls[0]["system"], "Write flashcards.")

    def test_an_sdk_error_falls_back_with_a_notice(self):
        try:
            import anthropic
            import httpx2
        except ImportError:
            self.skipTest("anthropic isn't installed")
        error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://example.invalid"))
        writer, _, _ = self.writer([error])
        quiz = build_quiz(chunks(), 3, title="O", seed=1, writer=writer)
        self.assertEqual(len(quiz.questions), 3)
        self.assertIn("Claude couldn't be reached", quiz.notice)

    def test_offline_answers_have_no_quiz_writer(self):
        self.assertIsNone(writer_for(ExtractiveGenerator()))


if __name__ == "__main__":
    unittest.main()
