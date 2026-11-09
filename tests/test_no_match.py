"""What each answer mode does when nothing in the document matches the question."""
import types
import unittest

from rag import RAG
from rag.generator import ClaudeGenerator, ExtractiveGenerator


class OfflineMode(unittest.TestCase):
    def test_it_says_what_it_tried_instead_of_claiming_the_answer_is_absent(self):
        answer = RAG("sample.txt", ExtractiveGenerator()).ask("What is the capital of France?")[0]
        self.assertEqual(answer, "I couldn't find an answer using the words in this question. "
                                 "The document may use different wording.")


class ClaudeMode(unittest.TestCase):
    def test_a_declined_question_is_reported_as_declined_not_labelled(self):
        def create(**request):
            return types.SimpleNamespace(stop_reason="refusal", content=[])

        generator = ClaudeGenerator.__new__(ClaudeGenerator)  # skips the optional package and key
        generator.model = "claude-test"
        generator.client = types.SimpleNamespace(
            beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        )
        self.assertEqual(generator.answer("A question", []), "The model declined to answer this question.")

    def test_the_question_reaches_the_model_and_the_answer_is_labelled(self):
        sent = []

        def create(**request):
            sent.append(request)
            block = types.SimpleNamespace(type="text", text="Paris [1]")
            return types.SimpleNamespace(stop_reason="end_turn", content=[block])

        generator = ClaudeGenerator.__new__(ClaudeGenerator)  # skips the optional package and key
        generator.model = "claude-test"
        generator.client = types.SimpleNamespace(
            beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        )
        answer = generator.answer("What is the capital of France?", [])
        self.assertEqual(answer, "It wasn't in the information I was given. Paris")
        self.assertIn("What is the capital of France?", sent[0]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
