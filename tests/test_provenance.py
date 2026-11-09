"""The app decides how an answer's origin is labelled, whatever the model replies.
This checks labels and excerpt numbers only: a valid number does not prove a claim."""
import unittest

from rag.chunker import Chunk
from rag.generator import with_provenance

ONE_HIT = [(Chunk(0, "Jupiter is the largest planet."), 1.0)]
NOTICE = "It wasn't in the information I was given."
NOTE = "(Removed a reference to a section that doesn't exist.)"


class CheckingModelReplies(unittest.TestCase):
    def test_replies(self):
        cases = [
            # A compliant reply passes through untouched.
            ("cited answer", "Jupiter [1]", ONE_HIT, "Jupiter [1]"),
            ("several citations", "Jupiter [1]. It is big [1, 1].", ONE_HIT, "Jupiter [1]. It is big [1, 1]."),
            ("labelled answer", "It wasn't in the information I was given, but Paris.", [],
             "It wasn't in the information I was given, but Paris."),
            ("don't know", "It wasn't in the information I was given, and I don't know.", [],
             "It wasn't in the information I was given, and I don't know."),
            ("mixed answer", "Data [1]. The rest wasn't in the information I was given, but CIC.", ONE_HIT,
             "Data [1]. The rest wasn't in the information I was given, but CIC."),
            # Nothing retrieved: a citation cannot be real, and the label is mandatory.
            ("citation with no excerpts", "Paris [1]", [], f"{NOTICE} Paris"),
            ("no label, no excerpts", "Paris", [], f"{NOTICE} Paris"),
            # Excerpts retrieved, but the reply doesn't show that it used them.
            ("no citation and no label", "Paris", ONE_HIT, f"{NOTICE} Paris"),
            ("only a nonexistent citation", "Mars [7]", ONE_HIT, f"{NOTICE} Mars"),
            ("nonexistent citation in a mixed reply", "Mars [7]. The rest wasn't in the information I was given, but CIC.",
             ONE_HIT, f"{NOTICE} Mars. The rest wasn't in the information I was given, but CIC."),
            # A real citation alongside a nonexistent one.
            ("one bad citation", "Jupiter [1] and Mars [7]", ONE_HIT, f"Jupiter [1] and Mars {NOTE}"),
            ("bad number in a list", "Jupiter [1, 7]", ONE_HIT, f"Jupiter [1] {NOTE}"),
            ("excerpt zero is not real", "Jupiter [1] and Mars [0]", ONE_HIT, f"Jupiter [1] and Mars {NOTE}"),
            # Outside knowledge cannot cite the document.
            ("citation after the label", "It wasn't in the information I was given, but Paris [1].", ONE_HIT,
             "It wasn't in the information I was given, but Paris."),
            ("citation after a mixed label", "Data [1]. The rest wasn't in the information I was given, but CIC [1].",
             ONE_HIT, "Data [1]. The rest wasn't in the information I was given, but CIC."),
            ("label in a different case", "IT WASN'T IN THE INFORMATION I WAS GIVEN, BUT PARIS [1].", ONE_HIT,
             "IT WASN'T IN THE INFORMATION I WAS GIVEN, BUT PARIS."),
            ("empty reply", "", [], NOTICE),
        ]
        for name, reply, hits, expected in cases:
            with self.subTest(name):
                self.assertEqual(with_provenance(reply, hits), expected)


class SayingHowMuchWasSearched(unittest.TestCase):
    """When only part of the document was read, a label must not suggest the whole document
    lacks the answer."""

    def test_labels(self):
        searched = "I searched 1 of 10 sections of the document and didn't find"
        nothing = "No section of the document matched the words in this question"
        cases = [
            ("part read, outside answer", "It wasn't in the information I was given, but Paris.", ONE_HIT, 10,
             f"{searched} this, but Paris."),
            ("part read, mixed answer", "Data [1]. The rest wasn't in the information I was given, but CIC.", ONE_HIT, 10,
             f"Data [1]. {searched} the rest, but CIC."),
            ("part read, don't know", "It wasn't in the information I was given, and I don't know.", ONE_HIT, 10,
             f"{searched} this, and I don't know."),
            ("part read, app adds the label", "Paris", ONE_HIT, 10, f"{searched} this. Paris"),
            ("nothing matched", "It wasn't in the information I was given, but Paris.", [], 10, f"{nothing}, but Paris."),
            ("nothing matched, app adds the label", "Paris", [], 10, f"{nothing}. Paris"),
            ("whole document read", "It wasn't in the information I was given, but Paris.", ONE_HIT, 1,
             "It wasn't in the information I was given, but Paris."),
            ("document answer is unchanged", "Jupiter [1]", ONE_HIT, 10, "Jupiter [1]"),
        ]
        for name, reply, hits, sections, expected in cases:
            with self.subTest(name):
                self.assertEqual(with_provenance(reply, hits, sections), expected)


if __name__ == "__main__":
    unittest.main()
