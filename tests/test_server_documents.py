"""HTTP API for "Learn from a document": upload, ask with citations, passages, delete.

Each test runs the real server on a free local port and talks to it over HTTP. Answers come
from the offline extractive generator or from a scripted online generator, so nothing is
sent to any provider.
"""
import importlib.util
import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

from rag.generator import NOT_FOUND, OUTSIDE_NOTICE, ExtractiveGenerator, _OnlineGenerator
from server.app import create_server

SAMPLE = (Path(__file__).resolve().parent.parent / "sample.txt").read_bytes()
HAS_PYPDF = importlib.util.find_spec("pypdf") is not None
WAIT_SECONDS = 10


def multipart(fields: dict, files: dict) -> tuple[bytes, dict]:
    """A multipart/form-data body like a browser's FormData: fields, then (name, bytes) files."""
    boundary = f"----dockbrain{uuid.uuid4().hex}"
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data) in files.items():
        out.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", xml)
    return buffer.getvalue()


def many_sections(count: int) -> bytes:
    """A document with `count` sections, each about a different made-up fruit."""
    fruits = [f"fruit{chr(97 + i)}{chr(97 + i)}" for i in range(count)]
    paragraphs = [
        f"Section {i + 1}\n\nThe {name} grows in valley number {i + 1}. " + " ".join(["It ripens slowly."] * 25)
        for i, name in enumerate(fruits)
    ]
    return "\n\n".join(paragraphs).encode()


class ScriptedGenerator(_OnlineGenerator):
    """An online answer mode whose model reply is scripted, so the real labelling runs."""

    def __init__(self, reply):
        self.reply = reply

    def _reply(self, question, hits):
        reply = self.reply()
        if isinstance(reply, Exception):
            raise reply
        return reply


class ServerTest(unittest.TestCase):
    server_options: dict = {}

    def make_generator(self):
        return ExtractiveGenerator()

    def setUp(self):
        self.server = create_server(port=0, generator_factory=self.make_generator, **self.server_options)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/api/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.store.close()

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=WAIT_SECONDS) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None, response.headers
        except urllib.error.HTTPError as error:
            with error:
                raw = error.read()
                return error.code, json.loads(raw) if raw else None, error.headers

    def upload(self, filename: str, data: bytes, kind: str = "document"):
        return self.call("POST", "/sessions", *multipart({"kind": kind}, {"file": (filename, data)}))

    def finished(self, session: dict) -> dict:
        """Poll the session until it is no longer processing, as the frontend does."""
        deadline = time.monotonic() + WAIT_SECONDS
        while session["status"] == "processing" and time.monotonic() < deadline:
            time.sleep(0.02)
            session = self.call("GET", f"/sessions/{session['id']}")[1]
        return session

    def ready(self, filename: str = "solar.txt", data: bytes = SAMPLE) -> dict:
        status, session, _ = self.upload(filename, data)
        self.assertIn(status, (200, 202), session)
        session = self.finished(session)
        self.assertEqual(session["status"], "ready", session)
        return session

    def ask(self, session_id: str, question: str):
        return self.call("POST", f"/sessions/{session_id}/questions", *self.json({"question": question}))

    @staticmethod
    def json(payload) -> tuple[bytes, dict]:
        return json.dumps(payload).encode(), {"Content-Type": "application/json"}

    def stored_files(self) -> list[Path]:
        return [p for p in Path(self.server.store.root).rglob("*") if p.is_file()]

    def assertError(self, response, status: int, code: str):
        self.assertEqual(response[0], status, response[1])
        error = response[1]["error"]
        self.assertEqual(error["code"], code)
        self.assertTrue(error["message"])
        self.assertIsInstance(error["retryable"], bool)
        return error


class Capabilities(ServerTest):
    def test_reports_what_this_server_offers(self):
        status, capabilities, _ = self.call("GET", "/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["mode"], "live")
        self.assertEqual(capabilities["ask"], "available")
        self.assertEqual(capabilities["notes"], "available")
        self.assertEqual(capabilities["codebase"], "unavailable")
        self.assertIn(capabilities["quiz"], ("available", "unavailable"))
        self.assertEqual(capabilities["maxDocumentBytes"], 52428800)
        self.assertEqual(capabilities["documentExtensions"], [".pdf", ".docx", ".txt", ".md", ".markdown"])
        self.assertTrue(capabilities["answerEngine"])

    def test_offline_servers_say_answers_stay_on_this_computer(self):
        offline = create_server(port=0, offline=True)
        try:
            self.assertIn("Offline", offline.answer_engine)
            self.assertIsInstance(offline.generator_factory(), ExtractiveGenerator)
        finally:
            offline.server_close()
            offline.store.close()


class UploadingDocuments(ServerTest):
    def test_a_text_file_becomes_a_ready_session(self):
        status, session, _ = self.upload("solar.txt", SAMPLE)
        self.assertIn(status, (200, 202))
        self.assertTrue(session["id"].startswith("s_"))
        self.assertEqual((session["kind"], session["displayName"]), ("document", "solar.txt"))
        session = self.finished(session)
        self.assertEqual(session["status"], "ready")
        self.assertEqual(session["sectionCount"], 2)

    def test_markdown_word_and_pdf_documents_are_read(self):
        documents = [
            ("notes.md", b"# Fruit\n\nApples grow on trees in cool climates."),
            ("notes.markdown", b"Pears ripen after they are picked."),
            ("report.docx", docx_bytes(["Harvest report", "Cherries were picked in June."])),
        ]
        if HAS_PYPDF:
            try:
                from test_pdf import pdf_bytes
            except ImportError:  # run as tests.test_server_documents
                from tests.test_pdf import pdf_bytes

            documents.append(("report.pdf", pdf_bytes([["Plums are harvested in late summer."]])))
        for filename, data in documents:
            with self.subTest(filename):
                session = self.ready(filename, data)
                self.assertGreaterEqual(session["sectionCount"], 1)
                self.assertEqual(session["displayName"], filename)

    def test_the_uploaded_file_is_deleted_once_indexed(self):
        self.ready()
        self.assertEqual(self.stored_files(), [])

    def test_the_file_name_cannot_choose_where_the_upload_is_saved(self):
        outside = Path(self.server.store.root).parent / "escape.txt"
        session = self.ready("../../escape.txt", SAMPLE)
        self.assertEqual(session["displayName"], "escape.txt")
        self.assertFalse(outside.exists())


class RejectingUploads(ServerTest):
    def test_unsupported_file_types_are_refused(self):
        for filename in ("photo.png", "old.doc", "no-extension", "page.html"):
            with self.subTest(filename):
                error = self.assertError(self.upload(filename, b"some bytes"), 415, "unsupported")
                self.assertFalse(error["retryable"])
        self.assertEqual(self.stored_files(), [])

    def test_codebase_sessions_are_not_offered_yet(self):
        self.assertError(self.upload("app.py", b"print(1)", kind="codebase"), 415, "unsupported")

    def test_an_empty_file_is_unreadable(self):
        self.assertError(self.upload("empty.txt", b""), 422, "unreadable")

    def test_damaged_and_textless_documents_fail_with_a_reason_to_show(self):
        cases = [("broken.docx", b"this is not a zip file"), ("blank.txt", b"   \n\n \t ")]
        if HAS_PYPDF:
            cases.append(("broken.pdf", b"%PDF-1.4 this is not really a PDF"))
        for filename, data in cases:
            with self.subTest(filename):
                status, session, _ = self.upload(filename, data)
                session = self.finished(session) if status in (200, 202) else session
                if status in (200, 202):
                    self.assertEqual(session["status"], "failed")
                    error = session["error"]
                else:
                    error = self.assertError((status, session), 422, "unreadable")
                self.assertEqual(error["code"], "unreadable")
                self.assertIn(filename, error["message"])
                self.assertNotIn(str(self.server.store.root), error["message"])
                self.assertNotIn("Traceback", error["message"])
        self.assertEqual(self.stored_files(), [])

    def test_requests_without_a_document_are_invalid(self):
        body, headers = multipart({"kind": "document"}, {})
        self.assertError(self.call("POST", "/sessions", body, headers), 400, "invalid_request")
        self.assertError(self.call("POST", "/sessions", *self.json({"kind": "document"})), 400, "invalid_request")
        body, headers = multipart({}, {"file": ("solar.txt", SAMPLE)})
        self.assertError(self.call("POST", "/sessions", body, headers), 400, "invalid_request")


class LimitingUploadSize(ServerTest):
    server_options = {"max_document_bytes": 1000}

    def test_documents_over_the_limit_are_refused(self):
        self.assertError(self.upload("big.txt", b"word " * 400), 413, "too_large")
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(self.call("GET", "/capabilities")[1]["maxDocumentBytes"], 1000)

    def test_documents_at_the_limit_are_accepted(self):
        self.ready("exact.txt", b"Apples. " * 125)


class AskingOffline(ServerTest):
    def test_an_answer_quotes_the_document_and_cites_where_it_came_from(self):
        session = self.ready()
        status, answer, _ = self.ask(session["id"], "Which planet is the largest?")
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer["id"].startswith("a_"))
        self.assertEqual(answer["question"], "Which planet is the largest?")
        self.assertIn("Jupiter is the largest planet", answer["text"])
        self.assertEqual(answer["origin"], "document")
        self.assertFalse(answer["demo"])
        self.assertEqual(answer["coverage"], {"searched": 2, "total": 2})
        quoted = [c for c in answer["citations"] if "Jupiter is the largest planet" in c["excerpt"]]
        self.assertTrue(quoted, answer["citations"])
        for citation in answer["citations"]:
            self.assertGreaterEqual(citation["index"], 1)
            self.assertIsInstance(citation["passageId"], int)

    def test_no_matching_passage_is_insufficient_evidence(self):
        session = self.ready()
        answer = self.ask(session["id"], "What is the capital of France?")[1]
        self.assertEqual((answer["origin"], answer["text"], answer["citations"]), ("insufficient", NOT_FOUND, []))

    def test_a_closest_match_is_not_presented_as_an_answer(self):
        session = self.ready()
        answer = self.ask(session["id"], "Who discovered Neptune?")[1]
        self.assertEqual(answer["origin"], "insufficient")
        self.assertTrue(answer["text"].startswith("I couldn't find a direct answer"))
        self.assertTrue(any("Neptune" in c["excerpt"] for c in answer["citations"]))

    def test_questions_are_checked(self):
        session_id = self.ready()["id"]
        path = f"/sessions/{session_id}/questions"
        for body in ({"question": ""}, {"question": "   "}, {"question": "x" * 1001}, {}, {"question": 7}):
            with self.subTest(body):
                self.assertError(self.call("POST", path, *self.json(body)), 400, "invalid_request")
        self.assertError(self.call("POST", path, b"{not json", {"Content-Type": "application/json"}), 400, "invalid_request")
        self.assertEqual(self.ask(session_id, "x" * 1000)[0], 200)

    def test_oversized_requests_are_refused_unread(self):
        session_id = self.ready()["id"]
        huge = self.json({"question": "Which planet?", "padding": "x" * 70_000})
        self.assertError(self.call("POST", f"/sessions/{session_id}/questions", *huge), 413, "too_large")

    def test_unknown_sessions_are_not_found(self):
        self.assertError(self.ask("s_nothing_here", "Which planet is the largest?"), 404, "not_found")
        self.assertError(self.call("GET", "/sessions/s_nothing_here"), 404, "not_found")


class AskingOnline(ServerTest):
    reply = "Jupiter is the largest planet [1]."

    def make_generator(self):
        return ScriptedGenerator(lambda: self.reply)

    def answer(self, reply, data: bytes = SAMPLE, question: str = "Tell me something."):
        self.reply = reply
        session = self.session = self.ready("doc.txt", data)
        status, answer, _ = self.ask(session["id"], question)
        self.assertEqual(status, 200, answer)
        return answer

    def test_cited_answers_are_supported_by_the_document(self):
        answer = self.answer("Jupiter is the largest planet [1].")
        self.assertEqual(answer["origin"], "document")
        self.assertEqual(answer["text"], "Jupiter is the largest planet [1].")
        self.assertEqual([c["index"] for c in answer["citations"]], [1])
        self.assertIn("Jupiter", answer["citations"][0]["excerpt"])
        self.assertEqual(answer["coverage"], {"searched": 2, "total": 2})  # a small document is sent whole

    def test_partly_cited_answers_are_partial(self):
        answer = self.answer(
            "Mars has two small moons [2]. The rest wasn't in the information I was given, but they were found in 1877."
        )
        self.assertEqual(answer["origin"], "mixed")
        self.assertEqual([c["index"] for c in answer["citations"]], [2])
        self.assertIn("Phobos", answer["citations"][0]["excerpt"])

    def test_general_knowledge_is_labelled_and_cites_nothing(self):
        answer = self.answer("It wasn't in the information I was given, but Paris is the capital of France.")
        self.assertEqual((answer["origin"], answer["citations"]), ("general", []))
        self.assertTrue(answer["text"].startswith("It wasn't in the information I was given"))

    def test_an_unlabelled_uncited_reply_is_labelled_as_general_knowledge(self):
        answer = self.answer("Paris is the capital of France.")
        self.assertEqual(answer["origin"], "general")
        self.assertTrue(answer["text"].startswith(OUTSIDE_NOTICE))

    def test_not_knowing_is_insufficient_evidence(self):
        answer = self.answer("It wasn't in the information I was given, and I don't know.")
        self.assertEqual((answer["origin"], answer["citations"]), ("insufficient", []))

    def test_a_declined_question_is_insufficient_evidence(self):
        answer = self.answer(None)
        self.assertEqual((answer["origin"], answer["citations"]), ("insufficient", []))

    def test_large_documents_say_how_much_was_searched(self):
        answer = self.answer(
            "It wasn't in the information I was given, but nobody knows.",
            data=many_sections(12),
            question="Where does the fruitcc grow?",
        )
        self.assertEqual(answer["origin"], "general")
        searched, total = answer["coverage"]["searched"], answer["coverage"]["total"]
        self.assertEqual(total, self.session["sectionCount"])
        self.assertGreater(total, 6)  # too big to send whole
        self.assertLess(searched, total)
        self.assertIn(f"I searched {searched} of {total} sections", answer["text"])

    def test_provider_failures_become_structured_errors(self):
        cases = [
            (RuntimeError("Gemini's daily free limit for m is used up (quota). Until it resets, set GEMINI_MODEL "
                          "to another model such as gemini-3.5-flash-lite, or run with --offline."),
             429, "rate_limited", False),
            (RuntimeError("Gemini's usage limit was reached (busy). Wait a minute and try again, or run with --offline."),
             429, "rate_limited", True),
            (RuntimeError("Gemini can't answer right now (overloaded). Try again shortly, set GEMINI_MODEL "
                          "to another model such as gemini-3.5-flash-lite, or run with --offline."),
             503, "unavailable", True),
            (RuntimeError("Couldn't reach Gemini. Check your internet connection, or run with --offline."),
             503, "unavailable", True),
        ]
        for failure, status, code, retryable in cases:
            with self.subTest(code=code, retryable=retryable):
                self.reply = failure
                session = self.ready()
                error = self.assertError(self.ask(session["id"], "Which planet is the largest?"), status, code)
                self.assertEqual(error["retryable"], retryable)
                self.assertNotIn("--offline", error["message"])  # a command-line flag means nothing in the browser


class Passages(ServerTest):
    def test_a_cited_passage_can_be_fetched_with_its_neighbours(self):
        session = self.ready()
        answer = self.ask(session["id"], "Which planet is the largest?")[1]
        citation = answer["citations"][0]
        status, passage, _ = self.call("GET", f"/sessions/{session['id']}/passages/{citation['passageId']}")
        self.assertEqual(status, 200, passage)
        self.assertEqual(passage["passageId"], citation["passageId"])
        self.assertEqual(passage["text"], citation["excerpt"])
        first = self.call("GET", f"/sessions/{session['id']}/passages/0")[1]
        last = self.call("GET", f"/sessions/{session['id']}/passages/1")[1]
        self.assertEqual((first["previousId"], first["nextId"]), (None, 1))
        self.assertEqual((last["previousId"], last["nextId"]), (0, None))

    def test_unknown_passages_are_not_found(self):
        session_id = self.ready()["id"]
        for passage in ("2", "99", "-1", "abc", "1.5"):
            with self.subTest(passage):
                self.assertError(self.call("GET", f"/sessions/{session_id}/passages/{passage}"), 404, "not_found")
        self.assertError(self.call("GET", "/sessions/s_unknown/passages/0"), 404, "not_found")


class FlakyNotesWriter:
    name = "Scripted model"

    def __init__(self):
        self.calls = 0

    def write(self, prompt, instruction=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Ollama isn't running on this computer. Start it with: ollama serve, or run with --offline.")
        return json.dumps({
            "summary": "Jupiter is the largest planet.",
            "sections": [{"heading": "The largest planet", "points": [
                {"text": "Jupiter is the largest planet.", "passage": 1, "quote": "Jupiter is the largest planet."}]}],
            "questions": [],
        })


class ModelWrittenNotes(ServerTest):
    def make_generator(self):
        generator = ExtractiveGenerator()
        generator.quiz_writer = self.writer = FlakyNotesWriter()
        return generator

    def test_a_model_failure_is_tried_again_and_a_success_is_kept(self):
        session = self.ready()
        path = f"/sessions/{session['id']}/notes"
        first = self.call("GET", path)[1]
        self.assertIn("Ollama isn't running", first["notice"])
        self.assertNotIn("--offline", first["notice"])
        second = self.call("GET", path)[1]
        self.assertEqual(second["sections"][0]["heading"], "The largest planet")
        self.assertEqual(self.call("GET", path)[1], second)
        self.assertEqual(self.writer.calls, 2)


class Notes(ServerTest):
    def test_notes_quote_the_document_and_cite_their_passages(self):
        session = self.ready()
        status, notes, _ = self.call("GET", f"/sessions/{session['id']}/notes")
        self.assertEqual(status, 200, notes)
        self.assertEqual(notes["title"], "The Solar System")
        self.assertIn("4.6 billion years ago", notes["summary"])
        self.assertIs(notes["demo"], False)
        sources = {source["index"]: source for source in notes["sources"]}
        points = [p for section in notes["sections"] for p in section["points"]]
        self.assertTrue(points)
        for point in points:
            self.assertIn(point["text"], SAMPLE.decode())
            self.assertTrue(all(point["text"] in sources[i]["excerpt"] for i in point["citations"]))

    def test_notes_for_unknown_sessions_are_not_found(self):
        self.assertError(self.call("GET", "/sessions/s_unknown/notes"), 404, "not_found")


class Blocking(ExtractiveGenerator):
    """Holds a session in processing until released, to test what happens meanwhile."""

    release = threading.Event()

    def attach(self, retriever):
        self.release.wait(WAIT_SECONDS)
        super().attach(retriever)


class EndingSessions(ServerTest):
    def make_generator(self):
        return Blocking()

    def setUp(self):
        Blocking.release = threading.Event()
        super().setUp()

    def tearDown(self):
        Blocking.release.set()
        super().tearDown()

    def test_deleting_a_session_removes_it(self):
        Blocking.release.set()
        session_id = self.ready()["id"]
        self.assertEqual(self.call("DELETE", f"/sessions/{session_id}")[0], 204)
        self.assertError(self.call("GET", f"/sessions/{session_id}"), 404, "not_found")
        self.assertError(self.ask(session_id, "Which planet is the largest?"), 404, "not_found")
        self.assertEqual(self.stored_files(), [])

    def test_deleting_twice_or_an_unknown_session_is_harmless(self):
        Blocking.release.set()
        session_id = self.ready()["id"]
        for target in (session_id, session_id, "s_never_existed"):
            self.assertEqual(self.call("DELETE", f"/sessions/{target}")[0], 204)

    def test_questions_wait_until_the_document_is_ready(self):
        status, session, _ = self.upload("solar.txt", SAMPLE)
        self.assertEqual((status, session["status"]), (202, "processing"))
        error = self.assertError(self.ask(session["id"], "Which planet is the largest?"), 409, "not_ready")
        self.assertTrue(error["retryable"])
        Blocking.release.set()
        self.assertEqual(self.finished(session)["status"], "ready")

    def test_notes_wait_until_the_document_is_ready(self):
        session = self.upload("solar.txt", SAMPLE)[1]
        self.assertError(self.call("GET", f"/sessions/{session['id']}/notes"), 409, "not_ready")

    def test_a_session_deleted_while_processing_is_discarded(self):
        session = self.upload("solar.txt", SAMPLE)[1]
        self.assertEqual(self.call("DELETE", f"/sessions/{session['id']}")[0], 204)
        Blocking.release.set()
        self.server.store.wait_for_jobs(WAIT_SECONDS)
        self.assertError(self.call("GET", f"/sessions/{session['id']}"), 404, "not_found")
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(len(self.server.store), 0)


class ExpiringSessions(ServerTest):
    server_options = {"ttl_seconds": 0.3}

    def test_idle_sessions_expire(self):
        session_id = self.ready()["id"]
        time.sleep(0.5)
        self.assertError(self.call("GET", f"/sessions/{session_id}"), 404, "not_found")
        self.assertEqual(len(self.server.store), 0)

    def test_using_a_session_keeps_it_alive(self):
        session_id = self.ready()["id"]
        for _ in range(4):
            time.sleep(0.15)
            self.assertEqual(self.ask(session_id, "Which planet is the largest?")[0], 200)


class Privacy(ServerTest):
    SECRET = "Zebracorn Lane is where the quokka keeps its spare keys."

    def test_logs_never_contain_document_text_questions_or_session_ids(self):
        with self.assertLogs("dockbrain.server", level="INFO") as logs:
            session = self.ready("private.txt", self.SECRET.encode())
            self.ask(session["id"], "Where does the quokka keep its spare keys?")
            self.call("DELETE", f"/sessions/{session['id']}")
        written = "\n".join(logs.output)
        for private in ("Zebracorn", "quokka", "private.txt", session["id"]):
            self.assertNotIn(private, written)
        self.assertIn("POST /sessions/{session_id}/questions 200", written)

    def test_only_the_frontend_may_call_from_a_browser(self):
        allowed = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
        status, _, headers = self.call("OPTIONS", "/sessions", headers=allowed)
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        other = {"Origin": "https://example.com", "Access-Control-Request-Method": "POST"}
        self.assertIsNone(self.call("OPTIONS", "/sessions", headers=other)[2].get("Access-Control-Allow-Origin"))
        self.assertIsNone(self.call("GET", "/capabilities", headers={"Origin": "https://example.com"})[2]
                          .get("Access-Control-Allow-Origin"))

    def test_unknown_routes_get_a_structured_error(self):
        self.assertError(self.call("GET", "/nothing"), 404, "not_found")
        self.assertError(self.call("PUT", "/capabilities"), 405, "invalid_request")


if __name__ == "__main__":
    unittest.main()
