"""The second search in online modes: keeping what the first answer found, failing safely,
and staying within the per-question attempt budget. The model is scripted; no network."""
import importlib.util
import types
import unittest

from rag.chunker import Chunk
from rag.generator import QUESTION_ATTEMPTS, ClaudeGenerator, _OnlineGenerator
from rag.retriever import BM25Retriever

HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None


def index() -> BM25Retriever:
    """Eight sections: the launch code first, the quota last, orchards between."""
    texts = ["The launch code is cedar."] + [f"Orchard {n} grows fruit near the river." for n in range(6)]
    texts.append("The daily quota is seven requests.")
    return BM25Retriever([Chunk(i, text) for i, text in enumerate(texts)])


class Scripted(_OnlineGenerator):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []

    def _reply(self, question, hits):
        self.sent.append([chunk.text for chunk, _ in hits])
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ask(replies, question="What are the launch code and daily quota?"):
    retriever = index()
    generator = Scripted(replies)
    generator.attach(retriever)
    return generator, generator.answer(question, [(retriever.chunks[0], 1.0)])


FIRST = ("The launch code is cedar [1]. The rest wasn't in the information I was given, "
         "and I don't know.\nSEARCH TERMS: quota")


class KeepingTheFirstAnswer(unittest.TestCase):
    def test_a_fact_the_second_reply_drops_is_kept_with_its_source(self):
        # The second reply forgets the launch code that the first one found.
        generator, answer = ask([FIRST, "The daily quota is seven requests [1]. The rest wasn't in the "
                                        "information I was given, and I don't know the launch code."])
        self.assertIn("seven", answer)
        self.assertIn("cedar", answer)
        cited = int(answer.split("cedar [")[1].split("]")[0])
        self.assertEqual(generator.used_hits[cited - 1][0].text, "The launch code is cedar.")

    def test_the_second_request_shows_new_sections_first_and_earlier_ones_once(self):
        generator, _ = ask([FIRST, "The launch code is cedar [2] and the quota is seven requests [1]."])
        second = generator.sent[1]
        self.assertEqual(second[0], "The daily quota is seven requests.")
        self.assertEqual(second.count("The launch code is cedar."), 1)

    def test_nothing_is_repeated_when_the_second_reply_already_cites_the_earlier_section(self):
        reply = "The launch code is cedar [2] and the quota is seven requests [1]."
        _, answer = ask([FIRST, reply])
        self.assertEqual(answer, reply)

    def test_a_failed_second_request_keeps_the_first_answer(self):
        _, answer = ask([FIRST, RuntimeError("overloaded")])
        self.assertTrue(answer.startswith("The launch code is cedar [1]."))

    def test_the_label_counts_every_section_seen(self):
        _, answer = ask([FIRST, "The launch code is cedar [2]. The rest wasn't in the information I was given, "
                                "and I don't know."])
        self.assertIn("I searched 2 of 8 sections", answer)


class AttemptBudget(unittest.TestCase):
    def test_no_second_round_once_the_budget_is_spent(self):
        class Spender(Scripted):
            def _reply(self, question, hits):
                self._attempts_left = 0  # as if retries used every attempt
                return super()._reply(question, hits)

        retriever = index()
        generator = Spender([FIRST, "The daily quota is seven requests [1]."])
        generator.attach(retriever)
        generator.answer("What are the launch code and daily quota?", [(retriever.chunks[0], 1.0)])
        self.assertEqual(len(generator.sent), 1)


@unittest.skipUnless(HAS_ANTHROPIC, "needs the optional anthropic package")
class ClaudeFailures(unittest.TestCase):
    def claude(self, outcomes):
        calls = []

        class Messages:
            def create(self, **request):
                calls.append(request)
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return types.SimpleNamespace(stop_reason="end_turn",
                                             content=[types.SimpleNamespace(type="text", text=outcome)])

        retries = []

        class Client:
            beta = types.SimpleNamespace(messages=Messages())

            def with_options(self, max_retries):
                retries.append(max_retries)
                return self

        generator = ClaudeGenerator.__new__(ClaudeGenerator)  # skips the API key
        generator.model = "claude-test"
        generator.client = Client()
        retriever = index()
        generator.attach(retriever)
        return generator, retriever, calls, retries

    def connection_error(self):
        import anthropic
        import httpx2

        return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://example.invalid"))

    def test_a_connection_error_on_the_second_request_keeps_the_first_answer(self):
        generator, retriever, calls, _ = self.claude([FIRST, self.connection_error()])
        answer = generator.answer("What are the launch code and daily quota?", [(retriever.chunks[0], 1.0)])
        self.assertEqual(len(calls), 2)
        self.assertTrue(answer.startswith("The launch code is cedar [1]."))

    def test_a_connection_error_on_the_first_request_is_reported_plainly(self):
        generator, retriever, _, _ = self.claude([self.connection_error()])
        with self.assertRaisesRegex(RuntimeError, "Claude"):
            generator.answer("What are the launch code and daily quota?", [(retriever.chunks[0], 1.0)])

    def test_sdk_retries_stay_within_the_question_budget(self):
        generator, retriever, _, retries = self.claude([FIRST, "The daily quota is seven requests [1]."])
        generator.answer("What are the launch code and daily quota?", [(retriever.chunks[0], 1.0)])
        self.assertLessEqual(sum(r + 1 for r in retries), QUESTION_ATTEMPTS)
        self.assertEqual(len(retries), 2)


if __name__ == "__main__":
    unittest.main()
