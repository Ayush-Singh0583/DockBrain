"""The local model through Ollama, against a fake local server using Ollama's response
shape. No model is run and nothing is sent anywhere."""
import http.server
import json
import os
import socket
import threading
import time
import unittest
from unittest import mock

import main
from rag.chunker import chunk_text
from rag.generator import ExtractiveGenerator, GeminiGenerator, OllamaGenerator
from rag.quiz import QUIZ_INSTRUCTION, writer_for
from server.errors import for_browser, provider_error

PASSAGES = [(chunk, 1.0) for chunk in chunk_text("Jupiter is the largest planet in the Solar System.")]


def says(text: str):
    return 200, {"model": "m", "message": {"role": "assistant", "content": text}, "done": True, "done_reason": "stop"}


class OllamaTestCase(unittest.TestCase):
    def setUp(self):
        self.replies, self.requests, self.paths = [], [], []
        self.delay = 0.0
        self.crash = False
        self.installed = {"models": [{"name": "m:latest"}, {"name": "other:9b"}]}
        test = self

        class FakeOllama(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                test.paths.append(self.path)
                time.sleep(test.delay)
                if test.crash:
                    self.close_connection = True
                    return  # no response at all, as when Ollama dies while answering
                status, body = test.replies.pop(0)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:  # the client gave up waiting
                    pass

            def do_GET(self):
                test.paths.append(self.path)
                data = json.dumps(test.installed).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.generator = OllamaGenerator(model="m")
        self.generator.BASE_URL = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()


class Requests(OllamaTestCase):
    def test_a_question_goes_to_the_local_server_with_its_passages(self):
        self.replies = [says("Jupiter [1]")]
        text = self.generator.answer("Which planet is the largest?", PASSAGES)
        self.assertEqual(text, "Jupiter [1]")
        self.assertEqual(self.generator.last_origin, "document")
        self.assertEqual(self.paths, ["/api/chat"])
        body = self.requests[0]
        self.assertEqual(body["model"], "m")
        self.assertIs(body["stream"], False)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("Jupiter is the largest planet", body["messages"][1]["content"])
        self.assertNotIn("format", body)  # an answer is prose

    def test_a_reply_cannot_run_on_for_ever(self):
        self.replies = [says("Jupiter [1]")]
        self.generator.answer("Which planet is the largest?", PASSAGES)
        self.assertLessEqual(self.requests[0]["options"]["num_predict"], 6000)

    def test_a_model_stuck_repeating_itself_gets_one_warmer_try(self):
        self.replies = [(500, {"error": "prediction aborted, token repeat limit reached"}), says("{}")]
        self.assertEqual(self.generator.chat("system", "prompt", as_json=True), "{}")
        self.assertEqual(len(self.requests), 2)
        self.assertGreater(self.requests[1]["options"]["temperature"], self.requests[0]["options"]["temperature"])

    def test_reasoning_is_off_and_the_context_holds_the_passages(self):
        self.replies = [says("Jupiter [1]")]
        self.generator.answer("Which planet is the largest?", PASSAGES)
        body = self.requests[0]
        self.assertIs(body["think"], False)  # otherwise a laptop spends minutes on hidden text
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)  # Ollama's default would cut passages off

    def test_the_address_is_this_computer(self):
        self.assertEqual(OllamaGenerator.BASE_URL, "http://127.0.0.1:11434")

    def test_a_proxy_setting_cannot_send_the_request_elsewhere(self):
        self.replies = [says("Jupiter [1]")]
        proxy = {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "no_proxy": "", "NO_PROXY": ""}
        with mock.patch.dict(os.environ, proxy):
            generator = OllamaGenerator(model="m")  # proxy settings are read when the client is built
            generator.BASE_URL = self.generator.BASE_URL
            self.assertEqual(generator.answer("Largest?", PASSAGES), "Jupiter [1]")
        self.assertEqual(len(self.requests), 1)

    def test_a_model_name_is_required(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            OllamaGenerator()

    def test_the_model_name_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": " local-model "}, clear=True):
            self.assertEqual(OllamaGenerator().model, "local-model")


class Errors(OllamaTestCase):
    def failure(self) -> str:
        with self.assertRaises(RuntimeError) as caught:
            self.generator.chat("system", "prompt")
        return str(caught.exception)

    def test_a_server_that_is_not_running_says_how_to_start_it(self):
        with socket.socket() as s:  # a port nothing is listening on
            s.bind(("127.0.0.1", 0))
            self.generator.BASE_URL = f"http://127.0.0.1:{s.getsockname()[1]}"
            message = self.failure()
        self.assertIn("Ollama isn't running", message)
        self.assertIn("ollama serve", message)

    def test_a_missing_model_says_how_to_install_it_and_retrying_will_not_help(self):
        self.replies = [(404, {"error": "model 'm' not found"})]
        message = self.failure()
        self.assertIn("no model named 'm'", message)
        self.assertIn("ollama pull m", message)
        self.assertIs(provider_error(RuntimeError(message)).retryable, False)

    def test_a_server_error_passes_on_ollamas_reason(self):
        self.replies = [(500, {"error": "model requires more system memory"})]
        self.assertIn("model requires more system memory", self.failure())
        self.assertEqual(len(self.requests), 1)  # a local failure won't fix itself in two seconds

    def test_a_model_that_stays_stuck_says_so(self):
        stuck = (500, {"error": "prediction aborted, token repeat limit reached"})
        self.replies = [stuck, stuck]
        self.assertIn("stuck repeating itself", self.failure())
        self.assertEqual(len(self.requests), 2)

    def test_an_empty_reply_is_an_error(self):
        self.replies = [says("  ")]
        self.assertIn("no answer", self.failure())

    def test_an_unreadable_reply_is_an_error(self):
        self.replies = [(200, b"<html>not json</html>")]
        self.assertIn("couldn't be read", self.failure())

    def test_a_slow_model_times_out_with_a_plain_message(self):
        self.replies, self.delay = [says("late")], 0.4
        self.generator.TIMEOUT = 0.05
        self.assertIn("took too long", self.failure())

    def test_a_crash_while_answering_is_explained(self):
        self.crash = True
        self.assertIn("stopped while answering", self.failure())

    def test_the_browser_message_has_no_command_line_flags(self):
        self.replies = [(404, {"error": "model 'm' not found"})]
        self.assertNotIn("--offline", for_browser(self.failure()))


class StartupCheck(OllamaTestCase):
    def test_nothing_to_report_when_the_model_is_installed(self):
        self.assertIsNone(self.generator.startup_problem())
        self.assertEqual(self.paths, ["/api/tags"])

    def test_an_exact_tag_counts_as_installed(self):
        generator = OllamaGenerator(model="other:9b")
        generator.BASE_URL = self.generator.BASE_URL
        self.assertIsNone(generator.startup_problem())

    def test_a_missing_model_says_how_to_install_it(self):
        generator = OllamaGenerator(model="absent:4b")
        generator.BASE_URL = self.generator.BASE_URL
        self.assertIn("ollama pull absent:4b", generator.startup_problem())

    def test_a_stopped_server_says_how_to_start_it(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.generator.BASE_URL = f"http://127.0.0.1:{s.getsockname()[1]}"
            self.assertIn("ollama serve", self.generator.startup_problem())


class Writers(OllamaTestCase):
    def test_quiz_writing_asks_for_json_with_the_quiz_instruction(self):
        self.replies = [says('{"questions": []}')]
        writer = writer_for(self.generator)
        self.assertEqual(writer.name, "Ollama m")
        self.assertEqual(writer.write("the prompt"), '{"questions": []}')
        body = self.requests[0]
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["messages"][0]["content"], QUIZ_INSTRUCTION)
        self.assertEqual(body["messages"][1]["content"], "the prompt")

    def test_a_writer_can_be_given_another_instruction(self):
        self.replies = [says("{}")]
        writer_for(self.generator).write("the prompt", instruction="Write flashcards.")
        self.assertEqual(self.requests[0]["messages"][0]["content"], "Write flashcards.")


class Choosing(unittest.TestCase):
    def pick(self, env: dict, offline: bool = False):
        with mock.patch.dict(os.environ, env, clear=True):
            return main.pick_generator(offline)

    def test_a_local_model_comes_before_an_online_key(self):
        generator, name = self.pick({"OLLAMA_MODEL": "m", "GEMINI_API_KEY": "not-a-real-key"})
        self.assertIsInstance(generator, OllamaGenerator)
        self.assertIn("Ollama m", name)
        self.assertIn("this computer", name)

    def test_offline_still_means_no_model(self):
        self.assertIsInstance(self.pick({"OLLAMA_MODEL": "m"}, offline=True)[0], ExtractiveGenerator)

    def test_without_a_local_model_the_choice_is_as_before(self):
        self.assertIsInstance(self.pick({"GEMINI_API_KEY": "not-a-real-key"})[0], GeminiGenerator)
        self.assertIsInstance(self.pick({})[0], ExtractiveGenerator)


if __name__ == "__main__":
    unittest.main()
