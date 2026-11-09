"""Memory cards over HTTP: create a set, fetch it again, reveal one answer at a time."""
import json
import threading
import unittest

from rag.generator import ExtractiveGenerator
from types import SimpleNamespace

from server.cards import create_cards
from server.errors import ApiError

try:
    from test_server_documents import SAMPLE, Blocking, ServerTest
except ImportError:  # run as tests.test_cards_api
    from tests.test_server_documents import SAMPLE, Blocking, ServerTest

FRAGMENTS = b"Notes\n\nthis list has no sentences\njust short lines\nand fragments"


class MemoryCards(ServerTest):
    def create(self, session_id: str, payload=None):
        body = {} if payload is None else payload
        return self.call("POST", f"/sessions/{session_id}/cards", *self.json(body))

    def test_the_server_offers_memory_cards(self):
        self.assertEqual(self.call("GET", "/capabilities")[1]["cards"], "available")

    def test_a_card_set_shows_only_the_fronts(self):
        session = self.ready()
        status, card_set, _ = self.create(session["id"], {"count": 3})
        self.assertEqual(status, 201, card_set)
        self.assertTrue(card_set["id"].startswith("cs_"))
        self.assertEqual(card_set["title"], "solar")
        self.assertIs(card_set["demo"], False)
        self.assertTrue(1 <= len(card_set["cards"]) <= 3)
        for card in card_set["cards"]:
            self.assertEqual(set(card), {"id", "kind", "prompt"})  # no answer before it's revealed

    def test_revealing_a_card_gives_its_answer_and_the_passage_it_came_from(self):
        session = self.ready()
        card_set = self.create(session["id"])[1]
        for card in card_set["cards"]:
            status, back, _ = self.call("GET", f"/sessions/{session['id']}/cards/{card_set['id']}/answers/{card['id']}")
            self.assertEqual(status, 200, back)
            self.assertEqual(back["cardId"], card["id"])
            self.assertIn(back["answer"], back["quote"])
            self.assertIn(back["quote"], back["citation"]["excerpt"])
            self.assertIn(back["quote"], SAMPLE.decode())
            self.assertIsInstance(back["citation"]["passageId"], int)
            self.assertNotIn("score", back["citation"])  # a card's passage was chosen, not ranked

    def test_a_set_can_be_fetched_again(self):
        session = self.ready()
        created = self.create(session["id"])[1]
        status, again, _ = self.call("GET", f"/sessions/{session['id']}/cards/{created['id']}")
        self.assertEqual((status, again), (200, created))

    def test_a_session_keeps_only_its_five_newest_sets(self):
        session = self.ready()
        sets = [self.create(session["id"])[1]["id"] for _ in range(6)]
        self.assertError(self.call("GET", f"/sessions/{session['id']}/cards/{sets[0]}"), 404, "not_found")
        for set_id in sets[1:]:
            self.assertEqual(self.call("GET", f"/sessions/{session['id']}/cards/{set_id}")[0], 200)

    def test_the_card_count_is_checked(self):
        session = self.ready()
        for payload in ({"count": 0}, {"count": 21}, {"count": "5"}, {"count": True}, [1]):
            with self.subTest(payload=payload):
                self.assertError(self.create(session["id"], payload), 400, "invalid_request")

    def test_unknown_sessions_sets_and_cards_are_not_found(self):
        self.assertError(self.create("s_missing"), 404, "not_found")
        session = self.ready()
        card_set = self.create(session["id"])[1]
        self.assertError(self.call("GET", f"/sessions/{session['id']}/cards/cs_missing"), 404, "not_found")
        path = f"/sessions/{session['id']}/cards/{card_set['id']}/answers/c999"
        self.assertError(self.call("GET", path), 404, "not_found")

    def test_a_document_with_nothing_suitable_explains_why(self):
        session = self.ready("fragments.txt", FRAGMENTS)
        error = self.assertError(self.create(session["id"]), 422, "insufficient_content")
        self.assertIn("memory cards", error["message"])

    def test_logs_hold_route_patterns_not_ids_or_card_text(self):
        with self.assertLogs("dockbrain.server", level="INFO") as logs:
            session = self.ready()
            card_set = self.create(session["id"])[1]
            card = card_set["cards"][0]
            back = self.call("GET", f"/sessions/{session['id']}/cards/{card_set['id']}/answers/{card['id']}")[1]
        written = "\n".join(logs.output)
        self.assertIn("GET /sessions/{session_id}/cards/{set_id}/answers/{card_id} 200", written)
        # The quote contains the answer; a short answer alone could match a status or duration.
        for private in (session["id"], card_set["id"], card["prompt"], back["quote"]):
            self.assertNotIn(private, written)

    def test_ending_the_session_drops_its_cards(self):
        session = self.ready()
        card_set = self.create(session["id"])[1]
        self.call("DELETE", f"/sessions/{session['id']}")
        self.assertError(self.call("GET", f"/sessions/{session['id']}/cards/{card_set['id']}"), 404, "not_found")


class CardsAfterDeletion(unittest.TestCase):
    def test_a_session_deleted_while_waiting_for_its_lock_is_not_found(self):
        session = SimpleNamespace(lock=threading.Lock(), rag=None)
        store = SimpleNamespace(get_ready=lambda _id: session)
        request = SimpleNamespace(headers={}, params={"session_id": "s_gone"}, store=store)
        with self.assertRaises(ApiError) as caught:
            create_cards(request)
        self.assertEqual(caught.exception.status, 404)


class ModelWriter:
    name = "Scripted model"

    def write(self, prompt, instruction=None):
        return json.dumps({"cards": [{
            "passage": 1, "question": "Which planet holds the most mass after the Sun?", "answer": "Jupiter",
            "quote": "Most of its mass is in the Sun, and the rest is mostly in Jupiter.",
        }]})


class FailingWriter:
    name = "Ollama m"

    def write(self, prompt, instruction=None):
        raise RuntimeError("Ollama isn't running on this computer. Start it with: ollama serve, or run with --offline.")


class ModelWrittenCards(ServerTest):
    def make_generator(self):
        generator = ExtractiveGenerator()
        generator.quiz_writer = ModelWriter()
        return generator

    def test_a_model_written_card_keeps_its_answer_until_revealed(self):
        session = self.ready()
        card_set = self.call("POST", f"/sessions/{session['id']}/cards", *self.json({"count": 1}))[1]
        self.assertEqual(card_set["cards"], [{"id": "c1", "kind": "question", "prompt": "Which planet holds the most mass after the Sun?"}])
        back = self.call("GET", f"/sessions/{session['id']}/cards/{card_set['id']}/answers/c1")[1]
        self.assertEqual(back["answer"], "Jupiter")
        self.assertIn(back["quote"], back["citation"]["excerpt"])


class CardsWhenTheModelFails(ServerTest):
    def make_generator(self):
        generator = ExtractiveGenerator()
        generator.quiz_writer = self.writer = FailingWriter()
        return generator

    def test_the_notice_gives_the_reason_without_command_line_advice(self):
        session = self.ready()
        card_set = self.call("POST", f"/sessions/{session['id']}/cards", *self.json({}))[1]
        self.assertTrue(card_set["cards"])
        self.assertIn("Ollama isn't running", card_set["notice"])
        self.assertNotIn("--offline", card_set["notice"])


class CardsWhileProcessing(ServerTest):
    def make_generator(self):
        return Blocking()

    def setUp(self):
        Blocking.release = threading.Event()
        super().setUp()

    def tearDown(self):
        Blocking.release.set()
        super().tearDown()

    def test_cards_wait_until_the_document_is_ready(self):
        session = self.upload("solar.txt", SAMPLE)[1]
        error = self.assertError(self.call("POST", f"/sessions/{session['id']}/cards", *self.json({})), 409, "not_ready")
        self.assertTrue(error["retryable"])


if __name__ == "__main__":
    unittest.main()
