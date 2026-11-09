"""The quiz endpoints over real HTTP, on a loopback server with a fake answer generator.

Uploads are made-up documents; nothing reaches Gemini or Claude.
"""
import contextlib
import io
import json
import logging
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

from rag.generator import ExtractiveGenerator
from tests.test_quiz import ORCHARD

try:
    from server.app import create_server
except ImportError:  # the server package isn't there yet
    create_server = None


class ModelGenerator(ExtractiveGenerator):
    """Answers offline, but writes quiz questions like a model (scripted, no network)."""

    def __init__(self, writer):
        super().__init__()
        self.quiz_writer = writer


class ScriptedWriter:
    name = "Scripted model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def write(self, prompt):
        if self.error:
            raise RuntimeError(self.error)
        return self.reply(prompt)


def first_passage_question(prompt: str) -> str:
    """A grounded model reply: one question about the 1998 planting, if passage 1 mentions it."""
    passage = re.search(r"^\[1\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", prompt, re.M | re.S).group(1)
    sentence = next((s for s in re.split(r"(?<=[.!?])\s+", passage) if "1998" in s), None)
    items = [] if sentence is None else [{
        "passage": 1, "question": "When was the orchard planted?",
        "options": ["1998", "2021", "2023", "1987"], "answer": 0, "quote": sentence.strip()}]
    # Every other passage gets a grounded question too, as a working model would write.
    passages = re.findall(r"^\[(\d+)\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", prompt, re.M | re.S)
    quoted = {item["quote"] for item in items}
    for number, text in passages:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip() not in quoted]
        for n, sentence in enumerate(sentences):
            figure = re.search(r"\b\d+\b|(?<=\s)[A-Z][a-z]{3,}\b", sentence)
            if figure and len(sentence.split()) >= 4:
                items.append({"passage": int(number), "question": f"Which figure goes with item {number}.{n} of the report?",
                              "options": [figure.group(), "11111", "22222", "33333"], "answer": 0, "quote": sentence})
    return json.dumps({"questions": items})


@unittest.skipIf(create_server is None, "server.app isn't available yet")
class QuizApi(unittest.TestCase):
    generator = staticmethod(ExtractiveGenerator)

    def setUp(self):
        self.log = io.StringIO()
        handler = logging.StreamHandler(self.log)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        redirect = contextlib.redirect_stderr(self.log)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

        self.server = create_server("127.0.0.1", 0, generator_factory=lambda: self.generator())
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"

    # ------------------------------------------------------------------ helpers

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = response.read().decode()
                return response.status, json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            with e:
                text = e.read().decode()
            return e.code, json.loads(text) if text else None

    def upload(self, text: str, name: str = "orchard.txt") -> str:
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\ndocument\r\n'.encode(),
            (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
             "Content-Type: text/plain\r\n\r\n").encode() + text.encode() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(self.base + "/sessions", data=b"".join(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            session = json.load(response)
        deadline = time.monotonic() + 10
        while session["status"] == "processing" and time.monotonic() < deadline:
            time.sleep(0.05)
            session = self.call("GET", f"/sessions/{session['id']}")[1]
        self.assertEqual(session["status"], "ready", session)
        return session["id"]

    def quiz(self, session_id, body=None):
        return self.call("POST", f"/sessions/{session_id}/quizzes", {"count": 3} if body is None else body)

    def assert_error(self, response, status, code):
        self.assertEqual(response[0], status, response)
        error = response[1]["error"]
        self.assertEqual(error["code"], code)
        self.assertIsInstance(error["message"], str)
        self.assertTrue(error["message"])

    # -------------------------------------------------------------------- tests

    def test_creates_a_quiz_in_the_contract_shape_with_answers_traced_to_passages(self):
        sid = self.upload(ORCHARD)
        status, quiz = self.quiz(sid)
        self.assertEqual(status, 200)
        self.assertTrue(quiz["id"].startswith("qz_"))
        self.assertIs(quiz["demo"], False)
        self.assertIn("orchard.txt", quiz["title"])
        self.assertEqual(len(quiz["questions"]), 3)
        flat = re.sub(r"\s+", " ", ORCHARD)
        for q in quiz["questions"]:
            option_ids = [o["id"] for o in q["options"]]
            self.assertIn(q["correctOptionId"], option_ids)
            citation = q["citation"]
            self.assertEqual(citation["index"], 1)
            self.assertIsInstance(citation["passageId"], int)
            self.assertIn(citation["excerpt"], flat)  # a real passage of the upload
            self.assertIn(q["quote"], citation["excerpt"])  # which states the answer
            self.assertIn(q["quote"], q["explanation"])

    def test_the_quiz_can_be_fetched_again_and_graded(self):
        sid = self.upload(ORCHARD)
        quiz = self.quiz(sid)[1]
        self.assertEqual(self.call("GET", f"/sessions/{sid}/quizzes/{quiz['id']}"), (200, quiz))

        q1, q2, q3 = quiz["questions"]
        wrong = next(o["id"] for o in q2["options"] if o["id"] != q2["correctOptionId"])
        status, graded = self.call("POST", f"/sessions/{sid}/quizzes/{quiz['id']}/answers", {"answers": [
            {"questionId": q1["id"], "optionId": q1["correctOptionId"]},
            {"questionId": q2["id"], "optionId": wrong},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(graded["score"], {"correct": 1, "total": 3})
        results = {r["questionId"]: r for r in graded["results"]}
        self.assertTrue(results[q1["id"]]["correct"])
        self.assertEqual((results[q2["id"]]["selectedOptionId"], results[q2["id"]]["correct"]), (wrong, False))
        self.assertIsNone(results[q3["id"]]["selectedOptionId"])
        for q in quiz["questions"]:
            r = results[q["id"]]
            self.assertEqual(r["correctOptionId"], q["correctOptionId"])
            self.assertEqual((r["explanation"], r["citation"]), (q["explanation"], q["citation"]))

    def test_answers_can_be_kept_hidden_until_the_quiz_is_submitted(self):
        sid = self.upload(ORCHARD)
        status, quiz = self.quiz(sid, {"count": 2, "revealAnswers": False})
        self.assertEqual(status, 200)
        self.assertIs(quiz["answersRevealed"], False)
        for q in quiz["questions"]:
            self.assertFalse({"correctOptionId", "explanation", "citation", "quote"} & q.keys())
        self.assertNotIn("correctOptionId", json.dumps(self.call("GET", f"/sessions/{sid}/quizzes/{quiz['id']}")[1]))
        graded = self.call("POST", f"/sessions/{sid}/quizzes/{quiz['id']}/answers", {"answers": []})[1]
        self.assertEqual(graded["score"], {"correct": 0, "total": 2})
        self.assertTrue(all(r["correctOptionId"] and r["explanation"] for r in graded["results"]))

    def test_rejects_malformed_requests(self):
        sid = self.upload(ORCHARD)
        for body in ({"count": 0}, {"count": 11}, {"count": "5"}, {"count": True}, {"revealAnswers": "no"}, [3]):
            with self.subTest(body=body):
                self.assert_error(self.quiz(sid, body), 400, "invalid_request")
        self.assert_error(self.call("POST", f"/sessions/{sid}/quizzes", raw=b"{not json"), 400, "invalid_request")

        quiz = self.quiz(sid)[1]
        path = f"/sessions/{sid}/quizzes/{quiz['id']}/answers"
        q1 = quiz["questions"][0]
        bad_answers = [
            {},
            {"answers": "a"},
            {"answers": [{"questionId": q1["id"]}]},
            {"answers": [{"questionId": [q1["id"]], "optionId": "a"}]},
            {"answers": [{"questionId": q1["id"], "optionId": {"id": "a"}}]},
            {"answers": [{"questionId": q1["id"], "optionId": "a" * 100}]},
            {"answers": ["q1"]},
            {"answers": [{"questionId": "q99", "optionId": "a"}]},
            {"answers": [{"questionId": q1["id"], "optionId": "z"}]},
            {"answers": [{"questionId": q1["id"], "optionId": q1["correctOptionId"]}] * 2},
        ]
        for body in bad_answers:
            with self.subTest(body=body):
                self.assert_error(self.call("POST", path, body), 400, "invalid_request")

    def test_unknown_sessions_and_quizzes_are_not_found(self):
        sid = self.upload(ORCHARD)
        self.assert_error(self.quiz("s_missing"), 404, "not_found")
        for method, path, body in (("GET", "", None), ("DELETE", "", None), ("POST", "/answers", {"answers": []})):
            with self.subTest(method=method, path=path):
                self.assert_error(self.call(method, f"/sessions/{sid}/quizzes/qz_missing{path}", body), 404, "not_found")

    def test_deleting_a_quiz_or_its_session_removes_it(self):
        sid = self.upload(ORCHARD)
        first, second = self.quiz(sid)[1], self.quiz(sid)[1]
        self.assertEqual(self.call("DELETE", f"/sessions/{sid}/quizzes/{first['id']}"), (204, None))
        self.assert_error(self.call("GET", f"/sessions/{sid}/quizzes/{first['id']}"), 404, "not_found")
        self.assertEqual(self.call("GET", f"/sessions/{sid}/quizzes/{second['id']}")[0], 200)

        self.assertIn(self.call("DELETE", f"/sessions/{sid}")[0], (200, 204))
        self.assert_error(self.call("GET", f"/sessions/{sid}/quizzes/{second['id']}"), 404, "not_found")

    def test_a_document_with_nothing_to_ask_about_is_reported(self):
        sid = self.upload("Contents\n\nIntroduction\n\nMethods\n\nResults\n\nAppendix", name="contents.txt")
        self.assert_error(self.quiz(sid), 422, "insufficient_content")

    def test_logs_never_contain_document_text_quiz_content_or_ids(self):
        sid = self.upload(ORCHARD)
        quiz = self.quiz(sid)[1]
        self.call("POST", f"/sessions/{sid}/quizzes/{quiz['id']}/answers", {"answers": []})
        self.call("DELETE", f"/sessions/{sid}/quizzes/{quiz['id']}")
        log = self.log.getvalue()
        for secret in [sid, quiz["id"], "Lindqvist", "Bramley", *(q["quote"] for q in quiz["questions"])]:
            self.assertNotIn(secret, log)


@unittest.skipIf(create_server is None, "server.app isn't available yet")
class ModelQuizApi(QuizApi):
    """The same endpoints when the session's provider writes the questions."""

    writer = ScriptedWriter(first_passage_question)

    def generator(self):
        return ModelGenerator(self.writer)

    def test_model_questions_are_used_when_grounded_and_the_engine_is_named(self):
        sid = self.upload(ORCHARD)
        quiz = self.quiz(sid)[1]
        self.assertEqual(quiz["engine"], "Scripted model")
        written = [q for q in quiz["questions"] if q["prompt"] == "When was the orchard planted?"]
        self.assertEqual(len(written), 1)
        answer = next(o["text"] for o in written[0]["options"] if o["id"] == written[0]["correctOptionId"])
        self.assertEqual(answer, "1998")
        self.assertIn("1998", written[0]["citation"]["excerpt"])

    def test_a_provider_failure_still_gives_a_quiz_with_a_notice(self):
        self.writer = ScriptedWriter(error="Gemini's usage limit was reached. Wait a minute and try again, "
                                           "or run with --offline.")
        sid = self.upload(ORCHARD)
        status, quiz = self.quiz(sid)
        self.assertEqual(status, 200)
        self.assertEqual(len(quiz["questions"]), 3)
        self.assertIn("usage limit", quiz["notice"])
        self.assertNotIn("--offline", quiz["notice"])  # command-line advice means nothing in a browser


if __name__ == "__main__":
    unittest.main()
