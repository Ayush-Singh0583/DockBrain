"""Gemini requests against a local fake server, using response shapes captured from
the live API. No network, no real key, and nothing is sent to Google."""
import http.server
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rag import RAG
from rag.chunker import Chunk
from rag.generator import GeminiGenerator

# A real success: a hidden reasoning step comes before the answer.
LIVE_ANSWER = {
    "status": "completed",
    "object": "interaction",
    "model": "gemini-3.6-flash",
    "steps": [
        {"signature": "EuoDCucDAWkUfRMppwR9DS9h", "type": "thought"},
        {"content": [{"text": "Jupiter [1]", "type": "text"}], "type": "model_output"},
    ],
}
# A real overload error: an object here, though bad-key errors arrive wrapped in a list.
LIVE_OVERLOAD = {
    "error": {
        "message": "gemini-3.8-flash is currently experiencing high demand, spikes in demand are usually temporary.",
        "code": "service_unavailable",
    }
}
# Real free-tier limits: same status and code, very different waits.
LIVE_DAILY_LIMIT = {"error": {
    "message": "Rate limit exceeded for model gemini-test (limit: 20 requests per day on Free Tier). "
               "Please retry in 9h41s or upgrade your tier at https://ai.dev/rate-limit.",
    "code": "too_many_requests",
}}
LIVE_MINUTE_LIMIT = {"error": {
    "message": "Rate limit exceeded for model gemini-test (limit: 5 requests per minute on Free Tier). "
               "Please retry in 9s or upgrade your tier at https://ai.dev/rate-limit.",
    "code": "too_many_requests",
}}


def says(text: str):
    """A successful live-shaped reply containing this text."""
    return 200, {**LIVE_ANSWER, "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


# Ten short sections; only the last one answers "who leads", and in different words.
ORCHARDS = [f"Orchard {n} grows {fruit} near the river." for n, fruit in enumerate(
    ["apples", "pears", "plums", "figs", "kiwis", "mangoes", "lemons", "limes", "cherries"])]
ORCHARDS.append("China accounts for the largest share of global apple production.")


class GeminiTestCase(unittest.TestCase):
    def setUp(self):
        self.replies, self.requests, self.paths, self.headers = [], [], [], []
        test = self

        class FakeGemini(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                test.paths.append(self.path)
                test.headers.append(self.headers)
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
        for patcher in (
            mock.patch.object(GeminiGenerator, "BASE_URL", f"http://127.0.0.1:{server.server_port}/v1beta"),
            mock.patch.object(GeminiGenerator, "RETRY_DELAYS", (0, 0)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.generator = GeminiGenerator(api_key="test-key", model="gemini-test")
        self.hits = [(Chunk(0, "Jupiter is the largest planet."), 1.0)]

    def test_the_key_goes_only_in_the_header_and_nothing_is_stored(self):
        self.replies = [(200, LIVE_ANSWER)]
        self.generator.answer("What is the largest planet?", self.hits)
        self.assertEqual(self.headers[0]["x-goog-api-key"], "test-key")
        self.assertEqual(self.paths[0], "/v1beta/interactions")
        self.assertNotIn("test-key", json.dumps(self.requests[0]))
        self.assertIs(self.requests[0]["store"], False)

    def test_the_request_contains_the_question_and_the_passage(self):
        self.replies = [(200, LIVE_ANSWER)]
        self.generator.answer("What is the largest planet?", self.hits)
        self.assertIn("What is the largest planet?", self.requests[0]["input"])
        self.assertIn("Jupiter is the largest planet.", self.requests[0]["input"])

    def test_problems_that_retrying_cannot_fix_are_explained_at_once(self):
        cases = [
            (401, {"error": {"code": "authentication", "message": "API key invalid"}}, "rejected your API key"),
            (400, [{"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}}],
             "rejected your API key"),
            (404, {"error": {"code": "model_not_found", "message": "nope"}}, "GEMINI_MODEL"),
            (403, {"error": {"code": "permission_denied", "message": "project denied"}}, "project denied"),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, expected=expected):
                self.replies, self.requests[:] = [(status, body)], []
                with self.assertRaises(RuntimeError) as caught:
                    self.generator.answer("What is the largest planet?", self.hits)
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn("test-key", str(caught.exception))
                self.assertEqual(len(self.requests), 1)

    def test_an_answer_that_was_cut_off_says_so(self):
        self.replies = [(200, {**LIVE_ANSWER, "status": "incomplete"})]
        self.assertIn("cut this answer short", self.generator.answer("What is the largest planet?", self.hits))

    def test_an_empty_answer_is_an_error(self):
        self.replies = [(200, {"status": "failed", "steps": []})]
        with self.assertRaisesRegex(RuntimeError, "no answer"):
            self.generator.answer("What is the largest planet?", self.hits)

    def test_the_answer_is_read_past_the_hidden_reasoning_step(self):
        self.replies = [(200, LIVE_ANSWER)]
        self.assertEqual(self.generator.answer("What is the largest planet?", self.hits), "Jupiter [1]")

    def test_reasoning_text_is_not_shown_as_part_of_the_answer(self):
        reasoning = {"type": "thought", "content": [{"type": "text", "text": "hidden reasoning"}]}
        self.replies = [(200, {**LIVE_ANSWER, "steps": [reasoning, *LIVE_ANSWER["steps"]]})]
        self.assertEqual(self.generator.answer("What is the largest planet?", self.hits), "Jupiter [1]")

    def test_a_question_nothing_matched_is_still_answered_without_document_text(self):
        self.replies = [(200, LIVE_ANSWER)]
        answer = self.generator.answer("What is the capital of France?", [])
        self.assertEqual(answer, "It wasn't in the information I was given. Jupiter")
        self.assertIn("What is the capital of France?", self.requests[0]["input"])
        self.assertNotIn(self.hits[0][0].text, self.requests[0]["input"])

    def ask_about(self, paragraphs: list[str], question: str):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doc.txt"
            path.write_text("\n\n".join(paragraphs))
            rag = RAG(str(path), self.generator, chunk_words=8)
            return rag, rag.ask(question)

    def test_a_small_document_is_sent_whole_so_the_label_can_say_so(self):
        self.replies = [(200, {**LIVE_ANSWER, "steps": [{"type": "model_output", "content": [
            {"type": "text", "text": "It wasn't in the information I was given, but Paris."}]}]})]
        paragraphs = ["Apples grow on trees.", "Pears ripen slowly.", "Plums taste sweet."]
        rag, (answer, hits) = self.ask_about(paragraphs, "What is the capital of France?")
        for paragraph in paragraphs:
            self.assertIn(paragraph, self.requests[0]["input"])
        self.assertEqual(answer, "It wasn't in the information I was given, but Paris.")
        self.assertEqual(len(hits), len(rag.chunks))

    def test_a_large_document_label_says_how_much_was_searched(self):
        self.replies = [(200, {**LIVE_ANSWER, "steps": [{"type": "model_output", "content": [
            {"type": "text", "text": "It wasn't in the information I was given, but Paris."}]}]})]
        paragraphs = [f"Orchard {n} grows {fruit} near the river." for n, fruit in enumerate(
            ["apples", "pears", "plums", "figs", "kiwis", "mangoes", "lemons", "limes", "cherries", "grapes"])]
        rag, (answer, hits) = self.ask_about(paragraphs, "Who has apples?")
        self.assertEqual(answer, f"I searched {len(hits)} of {len(rag.chunks)} sections of the document "
                                 "and didn't find this, but Paris.")
        self.assertLess(len(hits), len(rag.chunks))
        self.assertNotIn("lemons", self.requests[0]["input"])

    def test_a_failed_first_search_tries_the_words_the_model_suggests(self):
        self.replies = [
            says("It wasn't in the information I was given, but probably China.\nSEARCH TERMS: production, largest share"),
            says("China leads apple production [1]."),
        ]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which nation leads output?")
        self.assertEqual(answer, "China leads apple production [1].")
        self.assertEqual(len(self.requests), 2)
        self.assertIn("China accounts", self.requests[1]["input"])
        self.assertIn("China accounts", hits[0][0].text)

    def test_the_second_request_adds_new_sections_without_repeating_earlier_ones(self):
        self.replies = [
            says("It wasn't in the information I was given, but unknown.\nSEARCH TERMS: cherries, production"),
            says("China leads [1]."),
        ]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which orchard grows apples?")
        first, second = self.requests[0]["input"], self.requests[1]["input"]
        self.assertIn("Orchard 0 grows apples", first)
        self.assertEqual(second.count("Orchard 0 grows apples"), first.count("Orchard 0 grows apples"))
        self.assertLess(second.index("cherries"), second.index("Orchard 0 grows apples"))

    def test_a_suggestion_line_is_never_shown(self):
        self.replies = [says("Orchard 0 grows apples [1].\nSEARCH TERMS: cherries")]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which orchard grows apples?")
        self.assertEqual(answer, "Orchard 0 grows apples [1].")
        self.assertEqual(len(self.requests), 1)

    def test_no_suggestions_means_no_second_request(self):
        self.replies = [says("It wasn't in the information I was given, but Paris.")]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "What is the capital of France?")
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(answer.startswith("No section of the document matched"))

    def test_a_failed_second_request_keeps_the_first_answer(self):
        self.replies = [says("It wasn't in the information I was given, but China.\nSEARCH TERMS: production")]
        self.replies += [(503, LIVE_OVERLOAD)] * 3
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which nation leads output?")
        self.assertEqual(answer, "No section of the document matched the words in this question, but China.")
        self.assertEqual(hits, [])

    def test_when_the_second_search_also_misses_the_label_counts_both(self):
        self.replies = [
            says("It wasn't in the information I was given, but China.\nSEARCH TERMS: cherries"),
            says("It wasn't in the information I was given, but China."),
        ]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which orchard grows apples?")
        sent = len(re.findall(r"(?m)^\[\d+\] ", self.requests[1]["input"]))  # the second holds both searches
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(answer, f"I searched {sent} of {len(rag.chunks)} sections of the document "
                                 "and didn't find this, but China.")

    def test_a_small_document_needs_no_second_search(self):
        self.replies = [says("It wasn't in the information I was given, but Paris.\nSEARCH TERMS: capital")]
        rag, (answer, hits) = self.ask_about(["Apples grow on trees.", "Pears ripen slowly."], "What is the capital?")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(answer, "It wasn't in the information I was given, but Paris.")

    def test_a_question_never_makes_more_than_three_http_attempts(self):
        # Overloads in both rounds used to allow six attempts.
        self.replies = [(503, LIVE_OVERLOAD), (503, LIVE_OVERLOAD),
                        says("It wasn't in the information I was given, but China.\nSEARCH TERMS: cherries"),
                        (503, LIVE_OVERLOAD), says("Never sent [1].")]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which orchard grows apples?")
        self.assertEqual(len(self.requests), 3)
        self.assertIn("China", answer)

    def test_attempts_left_over_from_the_first_round_go_to_the_second(self):
        self.replies = [says("It wasn't in the information I was given, but China.\nSEARCH TERMS: cherries"),
                        (503, LIVE_OVERLOAD), says("Orchard 8 grows cherries [1].")]
        rag, (answer, hits) = self.ask_about(ORCHARDS, "Which orchard grows apples?")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(answer, "Orchard 8 grows cherries [1].")

    def test_no_retry_pause_once_the_budget_is_spent(self):
        self.replies = [says("It wasn't in the information I was given, but China.\nSEARCH TERMS: cherries"),
                        (503, LIVE_OVERLOAD), (503, LIVE_OVERLOAD)]
        with mock.patch("rag.generator.time.sleep") as pause:
            self.ask_about(ORCHARDS, "Which orchard grows apples?")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(pause.call_count, 1)  # after the first overload only; the second spends the budget

    def test_an_overload_shows_googles_reason_and_what_to_do(self):
        self.replies = [(503, LIVE_OVERLOAD)] * 3
        with self.assertRaises(RuntimeError) as caught:
            self.generator.answer("What is the largest planet?", self.hits)
        message = str(caught.exception)
        self.assertIn("high demand", message)
        self.assertIn("GEMINI_MODEL", message)
        self.assertIn("--offline", message)

    def test_the_daily_limit_explains_the_alternatives_without_retrying(self):
        self.replies = [(429, LIVE_DAILY_LIMIT)] * 3
        with self.assertRaises(RuntimeError) as caught:
            self.generator.answer("What is the largest planet?", self.hits)
        message = str(caught.exception)
        self.assertEqual(len(self.requests), 1)
        self.assertIn("GEMINI_MODEL", message)
        self.assertIn("--offline", message)
        self.assertNotIn("Wait a minute", message)

    def test_the_per_minute_limit_is_retried(self):
        self.replies = [(429, LIVE_MINUTE_LIMIT), (200, LIVE_ANSWER)]
        self.assertEqual(self.generator.answer("What is the largest planet?", self.hits), "Jupiter [1]")

    def test_a_brief_overload_is_retried(self):
        self.replies = [(503, LIVE_OVERLOAD), (200, LIVE_ANSWER)]
        self.assertEqual(self.generator.answer("What is the largest planet?", self.hits), "Jupiter [1]")
        self.assertEqual(len(self.requests), 2)


if __name__ == "__main__":
    unittest.main()
