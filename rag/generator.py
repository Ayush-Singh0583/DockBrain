"""Answer generation. Works offline by quoting the document's most relevant
sentences; uses Gemini or Claude instead if an API key is configured. Only those
online modes can answer from outside the document, and they say when they do."""
import json
import os
import re
import time
import urllib.error
import urllib.request

from .chunker import Chunk, Sentence, is_noise, section_name
from .retriever import OVERVIEW_SECTIONS, STOPWORDS, is_overview_question, stem, tokenize

NOT_FOUND = "I couldn't find an answer using the words in this question. The document may use different wording."
UNSURE = "I couldn't find a direct answer. Closest match: "
OUTSIDE_NOTICE = "It wasn't in the information I was given."
REMOVED_CITATION_NOTE = "(Removed a reference to a section that doesn't exist.)"
_LABEL = "wasn't in the information i was given"
_LABEL_PHRASE = re.compile(r"\b(it|the rest) wasn't in the information i was given", re.IGNORECASE)
# The model's "and I don't know" after the label: no answer at all, from anywhere.
_DONT_KNOW = re.compile(r"wasn't in the information i was given,?\s+and i don['’]t know", re.IGNORECASE)
# Where an answer came from, as reported to the web app (FRONTEND/API_CONTRACT.md, AnswerOrigin):
# "document" (cited excerpts support it), "mixed" (partly cited, the rest labelled general
# knowledge), "general" (labelled general knowledge, citing nothing) or "insufficient" (no
# answer: nothing matched, only a closest match, a refusal, or the model didn't know).
DECLINED = "The model declined to answer this question."
WHOLE_DOCUMENT_SECTIONS = 6  # documents this small are sent to the model in full
SECOND_SEARCH_SECTIONS = 4  # new sections added in the one extra request made with suggested words
# HTTP attempts per question, shared by retries and the second search, so a question can't
# turn into six requests when the service is overloaded.
QUESTION_ATTEMPTS = 3
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_SEARCH_TERMS = re.compile(r"^[ \t]*search terms[ \t]*:(.*)$", re.IGNORECASE | re.MULTILINE)
_CITATION = re.compile(r"\s*\[\s*(\d+(?:\s*[,;-]\s*\d+)*)\s*\]")
HEADING_WEIGHT = 0.8  # a question term in the section's heading, adding to the sentence's own matches
SECTION_MATCH = 0.6  # a heading this share of the question names the section that answers it
SECTION_BONUS = 1.2  # just below a sentence that names the term up front
# Words that frame a question without being part of it: "According to the document, …".
_SOURCE = r"(?:the|this)\s+(?:document|text|report|passage|article|file|paper|pdf|notes)"
_FRAMING = re.compile(
    rf"^\s*(?:according to|based on|in|from)\s+{_SOURCE}\s*,?\s*"
    rf"|[\s,]*\b(?:according to|based on|in)\s+{_SOURCE}\s*(?=[?.!]*\s*$)",
    re.IGNORECASE,
)
# "What is X?", "Who are X?": the question asks what X is.
_DEFINITION_QUESTION = re.compile(r"^\s*(?:what|who)\s+(?:is|are|was|were)\s+(?P<subject>[^?.!]+?)\s*[?.!]*\s*$", re.IGNORECASE)
_DEFINING_VERBS = {"is", "are", "was", "were", "means", "refers", "stands", "denotes"}
_COPULAS = {"is", "are", "was", "were"}
_CONTINUES = re.compile(r"^(?:it|its|they|their)\b", re.IGNORECASE)  # "It stores …" right after "X is …"
_CODE_LINE = re.compile(r"[{};=]|\(\)|^(?:import|from|const|let|var|function|return|def|class)\b")
_ASKS_QUANTITY = re.compile(r"\bhow (?:many|much|old|long|far|big|tall|large)\b|\bnumber of\b", re.IGNORECASE)
_HAS_QUANTITY = re.compile(
    r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|hundred|thousand|million|billion)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = (
    "You answer questions about a document, checking the provided context excerpts first. "
    "If the excerpts answer the question, use only them and cite the excerpt numbers you used, like [1] or [2]. "
    "If they don't, start your reply with exactly \"It wasn't in the information I was given, but\" and finish "
    "that sentence with the answer from your general knowledge, without citing any excerpt. "
    "If they answer only part of the question, answer that part with citations, then give the rest the same way, "
    "starting with \"The rest wasn't in the information I was given, but\". "
    "Never present general knowledge as if it came from the document. "
    "If you don't know the answer either, or it depends on private details you can't know, reply "
    "\"It wasn't in the information I was given, and I don't know.\" "
    "Whenever you use that \"wasn't in the information I was given\" wording, add a final line starting "
    "\"SEARCH TERMS:\" with up to eight comma-separated words or short phrases the document might use "
    "for what you couldn't find."
)


def build_prompt(question: str, hits: list[tuple[Chunk, float]]) -> str:
    context = "\n\n".join(f"[{i + 1}] {chunk.text}" for i, (chunk, _) in enumerate(hits))
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


def with_provenance(reply: str, hits: list[tuple[Chunk, float]], sections: int | None = None,
                    searched: int | None = None) -> str:
    """The reply, labelled and with its citations checked (see `labelled_reply`)."""
    return labelled_reply(reply, hits, sections, searched)[0]


def labelled_reply(reply: str, hits: list[tuple[Chunk, float]], sections: int | None = None,
                   searched: int | None = None) -> tuple[str, str]:
    """Enforce the origin label in code, since a model may not follow its instructions.
    A reply needs a real excerpt number or the label. Numbers that match no excerpt are
    removed, as is any number after the label, because outside knowledge can't cite the
    document. A valid number shows only that the excerpt exists, not that it says this.
    Given the document's section count, the label says how much was actually read: by
    default the sections in hits, or `searched` when earlier requests read others too.
    Returns the text and its origin: "document", "mixed", "general" or "insufficient"."""
    label = reply.lower().find(_LABEL)
    inside, outside = (reply, "") if label == -1 else (reply[:label], reply[label:])
    kept = removed = False

    def check(match):
        nonlocal kept, removed
        numbers = [int(n) for n in re.findall(r"\d+", match[1])]
        valid = [n for n in numbers if 1 <= n <= len(hits)]
        kept = kept or bool(valid)
        if len(valid) == len(numbers):
            return match[0]
        removed = True
        return f" [{', '.join(map(str, valid))}]" if valid else ""

    inside = _CITATION.sub(check, inside)
    text = (inside + _CITATION.sub("", outside)).strip()
    # What comes before the label: only "It" or "The rest" if the whole answer is labelled.
    unlabelled = re.sub(r"(?i)\b(?:it|the rest)\s*$", "", inside).strip()
    if not kept and (label == -1 or unlabelled):
        text = f"{OUTSIDE_NOTICE} {text}".strip()
        origin = "general"
    else:
        if removed:
            text = f"{text} {REMOVED_CITATION_NOTE}"
        origin = "document" if label == -1 else "mixed" if kept else "general"
    if origin == "general" and _DONT_KNOW.search(outside):
        origin = "insufficient"
    read = len({chunk.id for chunk, _ in hits}) if searched is None else searched
    return _say_how_much_was_read(text, read, sections), origin


def _split_search_terms(reply: str) -> tuple[str, list[str]]:
    """The reply without any "SEARCH TERMS:" line, and the suggested words (never shown)."""
    terms = [t.strip() for m in _SEARCH_TERMS.finditer(reply) for t in m[1].split(",") if t.strip()]
    return _SEARCH_TERMS.sub("", reply).strip(), terms[:8]


def _cited(text: str, count: int) -> set[int]:
    """The real excerpt numbers (1 to count) that the text cites."""
    return {int(n) for m in _CITATION.finditer(text) for n in re.findall(r"\d+", m[1]) if 1 <= int(n) <= count}


def _supported_sentences(reply: str, count: int) -> list[str]:
    """Sentences before any outside-knowledge label that cite a real excerpt."""
    label = reply.lower().find(_LABEL)
    inside = reply if label == -1 else reply[:label]
    return [sentence for sentence in _SENTENCE_BREAK.split(inside.strip()) if _cited(sentence, count)]


def _renumber(text: str, shift: int) -> str:
    """Move every excerpt number up by shift, for excerpts that moved down the list."""
    return _CITATION.sub(lambda m: m[0].replace(m[1], re.sub(r"\d+", lambda d: str(int(d[0]) + shift), m[1])), text)


def _claude_errors() -> tuple:
    """The Claude SDK's error types, if the optional package is installed."""
    try:
        import anthropic
    except ImportError:
        return ()
    return (anthropic.APIError,)


def _relies_on_outside_knowledge(reply: str, hits: list[tuple[Chunk, float]]) -> bool:
    cited = any(1 <= int(n) <= len(hits) for m in _CITATION.finditer(reply) for n in re.findall(r"\d+", m[1]))
    return _LABEL in reply.lower() or not cited


def _say_how_much_was_read(text: str, searched: int, sections: int | None) -> str:
    """"It wasn't in the information I was given" is only true of the whole document. When
    just some sections were read, say so, so a search miss can't pass for absence."""
    if sections is None or searched >= sections:
        return text

    def replace(match):
        if not searched:
            return "No section of the document matched the words in this question"
        missing = "the rest" if match[1].lower() == "the rest" else "this"
        return f"I searched {searched} of {sections} sections of the document and didn't find {missing}"

    return _LABEL_PHRASE.sub(replace, text)


class _OnlineGenerator:
    """Shared by the online answer modes: decides what to send and labels the reply.
    After each answer, `last_origin`, `last_coverage` ({"searched", "total"} sections) and
    `last_cited` (the excerpt numbers the text cites) describe it."""

    retriever = None
    used_hits = None
    last_origin = None
    last_coverage = None
    last_cited: set[int] = set()
    _attempts_left = QUESTION_ATTEMPTS

    def attach(self, retriever) -> None:
        self.retriever = retriever

    def answer(self, question: str, hits: list[tuple[Chunk, float]]) -> str:
        sections = len(self.retriever.chunks) if self.retriever else None
        if sections is not None and sections <= WHOLE_DOCUMENT_SECTIONS:
            hits = [(chunk, 1.0) for chunk in self.retriever.chunks]
        self._attempts_left = QUESTION_ATTEMPTS
        reply = self._reply(question, hits)
        if reply is None:
            self.used_hits = hits
            self._describe("insufficient", len(hits), sections or len(hits), set())
            return DECLINED
        reply, terms = _split_search_terms(reply)
        searched = {chunk.id for chunk, _ in hits}
        # On a large document, a miss may only mean the search used the wrong words. Try once
        # more with words the model suggested, on sections not yet sent (so a document sent
        # whole has none left to try), if the attempt budget allows. The second request shows
        # the new sections first and the earlier ones after, so nothing found is forgotten. If
        # that request fails, the first answer stands.
        if terms and sections and self._attempts_left > 0 and _relies_on_outside_knowledge(reply, hits):
            more = self.retriever.search_excluding(" ".join(terms), SECOND_SEARCH_SECTIONS, exclude=searched)
            if more:
                combined = more + hits
                try:
                    second = self._reply(question, combined)
                except RuntimeError:
                    second = None
                if second is not None:
                    second = _split_search_terms(second)[0]
                    # Keep any fact the first reply supported that the second neither repeats nor cites.
                    carried = [_renumber(s, len(more)) for s in _supported_sentences(reply, len(hits))]
                    cited_now = _cited(second, len(combined))
                    dropped = [s for s in carried if not _cited(s, len(combined)) & cited_now]
                    reply, hits = " ".join([*dropped, second]).strip(), combined
                    searched |= {chunk.id for chunk, _ in more}
        self.used_hits = hits
        text, origin = labelled_reply(reply, hits, sections, searched=len(searched))
        self._describe(origin, len(searched), sections or len(hits), _cited(text, len(hits)))
        return text

    def _describe(self, origin: str, searched: int, total: int, cited: set[int]) -> None:
        self.last_origin = origin
        self.last_coverage = {"searched": searched, "total": total}
        self.last_cited = cited if origin in ("document", "mixed") else set()


class ClaudeGenerator(_OnlineGenerator):
    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic  # imported lazily so the project runs without it

        self.client = anthropic.Anthropic()
        self.model = model

    def _reply(self, question: str, hits: list[tuple[Chunk, float]]) -> str | None:
        # The SDK retries by itself; allow at most one retry, within the question's budget.
        retries = max(0, min(1, self._attempts_left - 1))
        self._attempts_left -= retries + 1
        client = self.client.with_options(max_retries=retries) if hasattr(self.client, "with_options") else self.client
        try:
            response = self._create(client, question, hits)
        except _claude_errors() as e:
            raise RuntimeError(f"Claude couldn't answer ({e}). Try again shortly, or run with --offline.") from None
        if response.stop_reason == "refusal":
            return None
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _create(self, client, question: str, hits: list[tuple[Chunk, float]]):
        return client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": build_prompt(question, hits)}],
        )


class GeminiGenerator(_OnlineGenerator):
    """Written answers from Google's Gemini API, using only the standard library."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    API_REVISION = "2026-05-20"
    DEFAULT_MODEL = "gemini-3.6-flash"  # a stable model: the newest ones are often overloaded
    TIMEOUT = 60  # seconds
    RETRY_DELAYS = (2, 5)  # seconds to wait out brief overloads and per-minute limits

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY isn't set.")
        self.model = model or os.environ.get("GEMINI_MODEL", "").strip() or self.DEFAULT_MODEL

    def _reply(self, question: str, hits: list[tuple[Chunk, float]]) -> str:
        return self._read_text(self._post({
            "model": self.model,
            "input": build_prompt(question, hits),
            "system_instruction": SYSTEM_PROMPT,
            "generation_config": {"thinking_level": "low"},
            "store": False,  # each question stands alone, so Google needn't keep it for follow-ups
        }))

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.BASE_URL}/interactions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,  # in a header so it can't end up in a logged URL
                "Api-Revision": self.API_REVISION,
            },
            method="POST",
        )
        for delay in (*self.RETRY_DELAYS, None):
            if self._attempts_left <= 0:
                raise RuntimeError("DockBrain's limit of tries for this question was reached. Try again shortly, "
                                   "or run with --offline.")
            self._attempts_left -= 1
            try:
                with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                    return json.load(response)
            except urllib.error.HTTPError as e:
                code, message = _gemini_error(e)
                retryable = e.code in (500, 502, 503, 504) or (e.code == 429 and code != "quota_exceeded")
                if not retryable or delay is None or self._attempts_left <= 0:
                    raise RuntimeError(self._explain(e.code, code, message)) from None
            except OSError:
                raise RuntimeError(
                    "Couldn't reach Gemini. Check your internet connection, or run with --offline."
                ) from None
            except ValueError:
                raise RuntimeError("Gemini sent a response that couldn't be read. Try again.") from None
            time.sleep(delay)

    def _explain(self, status: int, code: str, message: str) -> str:
        if status == 401 or "api key" in message.lower():
            return (
                f"Gemini rejected your API key ({message}). "
                "Check GEMINI_API_KEY, or create a new key at https://aistudio.google.com/apikey"
            )
        if code == "quota_exceeded":
            return (
                f"Gemini's daily free limit for {self.model} is used up ({message}). Until it resets, set "
                "GEMINI_MODEL to another model such as gemini-3.5-flash-lite, or run with --offline."
            )
        if status == 429:
            return f"Gemini's usage limit was reached ({message}). Wait a minute and try again, or run with --offline."
        if status == 404:
            return f"Gemini has no model named '{self.model}'. Set GEMINI_MODEL to a current one."
        if status >= 500:
            reason = f" ({message})" if message else ""
            return (
                f"Gemini can't answer right now{reason}. Try again shortly, set GEMINI_MODEL "
                "to another model such as gemini-3.5-flash-lite, or run with --offline."
            )
        return f"Gemini returned an error ({status}): {message}"

    @staticmethod
    def _read_text(interaction: dict) -> str:
        text = "".join(
            part.get("text", "")
            for step in interaction.get("steps") or []
            if step.get("type") == "model_output"
            for part in step.get("content") or []
            if part.get("type") == "text"
        ).strip()
        status = interaction.get("status")
        if not text:
            raise RuntimeError(f"Gemini returned no answer (status: {status}). Try rephrasing the question.")
        return f"{text} (Gemini cut this answer short.)" if status == "incomplete" else text


class _StuckRepeating(RuntimeError):
    """Ollama stopped a reply because the model kept repeating itself."""


class OllamaGenerator(_OnlineGenerator):
    """Written answers from a model running on this computer through Ollama. Nothing leaves
    it, so there are no usage limits, and an answer takes as long as the hardware needs."""

    BASE_URL = "http://127.0.0.1:11434"
    CONTEXT_TOKENS = 12288  # Ollama's default would cut off all but a few passages
    MAX_REPLY_TOKENS = 4096  # room for full notes, and a limit on a reply that runs away
    TIMEOUT = 600  # seconds: notes on a long document can take minutes on a laptop

    def __init__(self, model: str | None = None):
        self.model = (model or os.environ.get("OLLAMA_MODEL", "")).strip()
        if not self.model:
            raise ValueError("OLLAMA_MODEL isn't set.")
        # Never through a proxy, even if one is configured: this must stay on this computer.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _reply(self, question: str, hits: list[tuple[Chunk, float]]) -> str:
        self._attempts_left -= 1
        return self.chat(SYSTEM_PROMPT, build_prompt(question, hits))

    def startup_problem(self) -> str | None:
        """What stops this model from answering, if anything, in words to show at startup."""
        try:
            with self._opener.open(f"{self.BASE_URL}/api/tags", timeout=5) as response:
                installed = [m.get("name", "") for m in json.load(response).get("models", [])]
        except (OSError, ValueError, AttributeError):
            return "Ollama isn't running on this computer. Start it with: ollama serve"
        if self.model in installed or f"{self.model}:latest" in installed:
            return None
        return f"Ollama doesn't have the model '{self.model}'. Install it with: ollama pull {self.model}"

    def chat(self, system: str, prompt: str, as_json: bool = False) -> str:
        """One reply from the model. Raises RuntimeError with a message to show if it can't."""
        for temperature in (0.2, 0.7):  # a warmer second try usually gets a model out of a loop
            try:
                return self._send(system, prompt, as_json, temperature)
            except _StuckRepeating:
                continue
        raise RuntimeError("The local model got stuck repeating itself. Try again, or run with --offline.")

    def _send(self, system: str, prompt: str, as_json: bool, temperature: float) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "think": False,  # hidden reasoning can take minutes on a laptop
            "options": {"num_ctx": self.CONTEXT_TOKENS, "num_predict": self.MAX_REPLY_TOKENS, "temperature": temperature},
        }
        if as_json:
            body["format"] = "json"
        request = urllib.request.Request(
            f"{self.BASE_URL}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.TIMEOUT) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as e:
            with e:
                message = self._explain(e)
            raise (_StuckRepeating if "repeat limit" in message else RuntimeError)(message) from None
        except TimeoutError:
            raise RuntimeError("The local model took too long to answer. Try again, or run with --offline.") from None
        except urllib.error.URLError:
            raise RuntimeError("Ollama isn't running on this computer. Start it with: ollama serve, "
                               "or run with --offline.") from None
        except OSError:
            raise RuntimeError("Ollama stopped while answering. Try again, or run with --offline.") from None
        except ValueError:
            raise RuntimeError("Ollama sent a response that couldn't be read. Try again.") from None
        text = ((reply.get("message") or {}).get("content") or "").strip() if isinstance(reply, dict) else ""
        if not text:
            raise RuntimeError("The local model returned no answer. Try rephrasing the question.")
        return text

    def _explain(self, error: urllib.error.HTTPError) -> str:
        if error.code == 404:
            return f"Ollama has no model named '{self.model}'. Install it with: ollama pull {self.model}, or run with --offline."
        try:
            reason = json.load(error).get("error") or ""
        except (OSError, ValueError, AttributeError):
            reason = ""
        detail = f" ({reason})" if reason else ""
        return f"The local model couldn't answer{detail}. Try again shortly, or run with --offline."


def _gemini_error(error: urllib.error.HTTPError) -> tuple[str, str]:
    """The code and message from an error response, if it has a readable body."""
    try:
        with error:
            body = json.load(error)
        # The live API wraps the error in a list; the docs show it bare.
        details = (body[0] if isinstance(body, list) else body)["error"]
        code = str(details.get("code", "")).lower()
        if re.search(r"per ?day", json.dumps(details), re.IGNORECASE):  # a daily limit: retrying won't help
            code = "quota_exceeded"
        return code, str(details.get("message", ""))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError):
        return "", ""


def _is_statement(s: Sentence) -> bool:
    """A full sentence or table row, not a short leftover line or a lead-in to a list."""
    if s.text.endswith(":"):
        return False
    if " | " in s.text:
        return len(s.text.split()) >= 6  # shorter rows are table headers
    return s.text[-1] in ".!?" or len(s.text.split()) >= 8


def _without_framing(question: str) -> str:
    """The question without "According to the document," and the like."""
    return _FRAMING.sub(" ", question).strip() or question


def _definition_subject(question: str) -> list[str]:
    """For a "What is X?" question, the word stems of X (up to four words), else []."""
    match = _DEFINITION_QUESTION.match(question)
    if not match:
        return []
    raw = re.findall(r"[a-z0-9]+", match["subject"].lower())
    if not raw or raw[-1] in STOPWORDS:  # "What is X used for?" asks something else
        return []
    words = [w for w in raw if w not in STOPWORDS]
    return [stem(w) for w in words] if len(words) <= 4 else []


def _defines(subject: list[str], text: str) -> bool:
    """Whether a sentence says what the subject is: "X is …" (also "X (…) is …", "X, …, is …"
    and "X refers to …"), or names it: "… is the X". "X sensor queries return …" mentions X
    but doesn't say what it is."""
    words = re.findall(r"[a-z0-9]+|,", re.sub(r"\([^)]*\)", " ", text.lower()))

    def subject_end(i: int) -> int:
        """The index after the subject if it starts at word i (little words skipped), else -1."""
        found = 0
        while i < len(words) and found < len(subject):
            if words[i] == ",":
                return -1
            if words[i] not in STOPWORDS:
                if stem(words[i]) != subject[found]:
                    return -1
                found += 1
            i += 1
        return i if found == len(subject) else -1

    end = subject_end(0)
    if end != -1:
        aside = words[end + 1:end + 12] if end < len(words) and words[end] == "," else []
        if "," in aside:  # "X, the team's main store, is …"
            end += 2 + aside.index(",")
        if end < len(words) and words[end] in _DEFINING_VERBS:
            return True
    return any(word in _COPULAS and subject_end(i + 1) != -1 for i, word in enumerate(words))


def _join(sentences: list[Sentence]) -> str:
    parts = [s.text if s.text[-1] in ".!?:" else s.text + ";" for s in sentences]
    return " ".join(parts).rstrip(";")


class ExtractiveGenerator:
    """Offline answers: quote the sentences most relevant to the question. After each
    answer, `last_origin`, `last_coverage` and `last_cited` (the excerpts quoted, by
    number) describe it, as for the online modes."""

    last_origin = None
    last_coverage = None
    last_cited: set[int] = set()

    def __init__(self, max_words: int = 80, keep_ratio: float = 0.7):
        self.max_words = max_words
        self.keep_ratio = keep_ratio  # drop sentences scoring below this share of the best one
        self.idf = {}
        self.word_forms = lambda term: set()
        self.sections = None

    def attach(self, retriever) -> None:
        """Share the index's word rarity, so 'watermark' outweighs 'project', and its word
        forms, so a sentence saying 'production' answers 'who produces'."""
        self.idf = retriever.idf
        self.word_forms = retriever.word_forms
        self.sections = len(retriever.chunks)

    @staticmethod
    def _tokens(text: str, forms: dict[str, str]) -> list[str]:
        """The text's words, with each listed word form counted as its question word."""
        return [forms.get(token, token) for token in tokenize(text)]

    def answer(self, question: str, hits: list[tuple[Chunk, float]]) -> str:
        question = _without_framing(question)
        if is_overview_question(question) and hits:
            overview = self._overview(hits)
            if not overview:  # nothing summary-like: show the first passage as it is
                return self._describe("document", hits, hits[0][0].sentences, hits[0][0].text)
            return self._describe("document", hits, overview, _join(overview))
        picked = self._best_matches(question, hits) if hits else []
        if not picked:
            return self._describe("insufficient", hits, [], NOT_FOUND)
        if self._mostly_unknown(question):  # only a closest match: shown, but not as an answer
            return self._describe("insufficient", hits, picked, UNSURE + _join(picked))
        return self._describe("document", hits, picked, _join(picked))

    def _describe(self, origin: str, hits: list[tuple[Chunk, float]], quoted: list[Sentence], text: str) -> str:
        self.last_origin = origin
        self.last_coverage = {"searched": len(hits), "total": self.sections if self.sections is not None else len(hits)}
        self.last_cited = {i for i, (chunk, _) in enumerate(hits, 1) if any(s in quoted for s in chunk.sentences)}
        return text

    def _mostly_unknown(self, question: str) -> bool:
        """Half the question is words the document never uses ("capital of France"),
        so a match may be a coincidence. Still quoted, since "happened to Pluto" and
        "how is piracy detected" look the same and do have answers."""
        q = set(tokenize(question))
        unknown = {t for t in q if t not in self.idf and not self.word_forms(t)}
        return bool(self.idf) and 2 * len(unknown) >= len(q)

    def _within_budget(self, sentences: list[Sentence]) -> list[Sentence]:
        picked, words = [], 0
        for s in sentences:
            n = len(s.text.split())
            if picked and words + n > self.max_words:
                break
            picked.append(s)
            words += n
        return picked

    def _overview(self, hits: list[tuple[Chunk, float]]) -> list[Sentence]:
        """Opening sentences of the abstract/introduction."""
        sentences = list({s.text: s for chunk, _ in hits for s in chunk.sentences}.values())
        start = next(
            (i + 1 for i, s in enumerate(sentences)
             if s.is_heading and section_name(s.text) in OVERVIEW_SECTIONS),
            0,
        )
        picked = []
        for s in sentences[start:]:
            if s.is_heading and picked:
                break  # end of the section
            if _is_statement(s) and not is_noise(s.text):
                picked.append(s)
        return self._within_budget(picked)

    def _weight(self, terms: set[str]) -> float:
        # A word missing from the document counts as rare: it's probably the point of the question.
        unknown = max(self.idf.values(), default=1.0)
        return sum(self.idf.get(t) or max((self.idf[f] for f in self.word_forms(t)), default=unknown) for t in terms)

    def _answers_section(self, q: set[str], s: Sentence, forms: dict[str, str], subject: list[str]) -> bool:
        """Whether the sentence's whole section answers the question: its heading holds most
        of the question's weight. For "What is X?", the heading's main (last) word must also
        be one of X's: "Objectives" answers "What are the objectives of the project?", but
        "Larkspur Dashboard Setup" is about a setup, not about what Larkspur is."""
        heading = [t for t in self._tokens(s.section, forms) if not t.isdigit()]
        if self._weight(q & set(heading)) < SECTION_MATCH * self._weight(q):
            return False
        return not subject or (bool(heading) and stem(heading[-1]) in subject)

    def _score(self, q: set[str], s: Sentence, wants_quantity: bool, forms: dict[str, str],
               subject: list[str] = ()) -> float:
        tokens = self._tokens(s.text, forms)
        section_terms = q & set(self._tokens(s.section, forms))
        in_answering_section = bool(s.section) and self._answers_section(q, s, forms, subject)
        # Short lines and lead-ins only make sense inside the section being asked about.
        if not in_answering_section and not _is_statement(s):
            return 0.0
        direct = q & set(tokens)
        if not direct and not in_answering_section:
            return 0.0  # a heading's words alone aren't evidence from this sentence
        score = self._weight(direct) + HEADING_WEIGHT * self._weight(section_terms - direct)
        if in_answering_section:
            score = self._weight(q) * SECTION_BONUS
        elif q & set(tokens[:4]):
            score *= 1.5  # the sentence is about the term: "IPFS is...", "Jupiter is..."
        if wants_quantity and _HAS_QUANTITY.search(s.text):
            score *= 1.5
        if _CODE_LINE.search(s.text):
            score *= 0.4
        score /= 1 + len(tokens) / 40  # long sentences match words by chance
        return score * 0.15 if is_noise(s.text) else score

    def _best_matches(self, question: str, hits: list[tuple[Chunk, float]]) -> list[Sentence]:
        q = set(tokenize(question))
        if not q:
            return []
        wants_quantity = bool(_ASKS_QUANTITY.search(question))
        # Other word forms stand in only for question words the passages never use exactly:
        # "production" for "produces", but not "technological" where "technology" appears.
        present = {t for chunk, _ in hits for s in chunk.sentences for t in tokenize(f"{s.text} {s.section}")}
        forms = {form: term for term in q - present for form in self.word_forms(term)}
        subject = _definition_subject(question)
        scored, seen, sections_answer = [], set(), False
        for rank, (chunk, _) in enumerate(hits):
            for pos, s in enumerate(chunk.sentences):
                if s.is_heading or s.text in seen:
                    continue
                seen.add(s.text)
                score = self._score(q, s, wants_quantity, forms, subject) / (1 + 0.1 * rank)
                if score > 0:
                    scored.append((score, (chunk.id, pos), s))
                    sections_answer = sections_answer or (bool(s.section) and self._answers_section(q, s, forms, subject))
        if not scored:
            return []
        scored.sort(key=lambda x: -x[0])
        # "What is X?": quote what the document says X is, not every sentence that mentions
        # X. A section named for X still answers it as a whole, as below.
        if subject and not sections_answer:
            definitions = [x for x in scored if _is_statement(x[2]) and _defines(subject, x[2].text)]
            if definitions:
                return self._with_continuations(definitions, hits)
        floor = scored[0][0] * self.keep_ratio
        kept = [x for x in scored if x[0] >= floor]
        allowed = {id(s) for s in self._within_budget([x[2] for x in kept])}
        # Read in document order so lists and explanations stay coherent.
        return [x[2] for x in sorted(kept, key=lambda x: x[1]) if id(x[2]) in allowed]

    def _with_continuations(self, definitions: list, hits: list[tuple[Chunk, float]]) -> list[Sentence]:
        """The strongest definitions, each with the sentence right after it when that one
        carries the definition on ("It stores …"), within the word budget, in document order."""
        chunks = {chunk.id: chunk for chunk, _ in hits}
        floor = definitions[0][0] * self.keep_ratio
        chosen: dict[str, tuple] = {}
        for score, (chunk_id, pos), s in definitions:
            if score < floor:
                break
            chosen.setdefault(s.text, ((chunk_id, pos), s))
            following = chunks[chunk_id].sentences[pos + 1:pos + 2]
            if following and not following[0].is_heading and _CONTINUES.match(following[0].text) \
                    and _is_statement(following[0]):
                chosen.setdefault(following[0].text, ((chunk_id, pos + 1), following[0]))
        allowed = {id(s) for s in self._within_budget([s for _, s in chosen.values()])}
        return [s for key, s in sorted(chosen.values(), key=lambda x: x[0]) if id(s) in allowed]
