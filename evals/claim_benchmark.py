"""A small, frozen benchmark of the checks on model-written notes, cards and quiz questions.

The checks decide whether a model's claim may be shown to a student. This measures how often
they are wrong, against a person's judgement rather than against the checks themselves:
  - wrongly accepted: a claim the passage doesn't support got through (false confidence);
  - wrongly rejected: a claim the passage does support was thrown away.

Steps (the set in evals/claims/ is already built, so normally only the last two are needed):

  .venv/bin/python -B evals/claim_benchmark.py collect MODEL PATH...  # needs `ollama serve`
  .venv/bin/python -B evals/claim_benchmark.py build                  # choose and mix the items
  .venv/bin/python -B evals/claim_benchmark.py label                  # a person judges each one
  .venv/bin/python -B evals/claim_benchmark.py score                  # how did the checks do?

Only use public or invented documents with `collect`: passages are saved into the repository.
See evals/claims/README.md.
"""
import argparse
import json
import random
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.cards import _checked_card  # noqa: E402
from rag.chunker import Chunk, Sentence  # noqa: E402
from rag.notes import _checked_point  # noqa: E402
from rag.quiz import _checked as _checked_question  # noqa: E402
from rag.quiz import cited_passage  # noqa: E402

DATA = Path(__file__).resolve().parent / "claims"
CANDIDATES_PATH = DATA / "candidates.json"
ALTERATIONS_PATH = DATA / "alterations.json"
ITEMS_PATH = DATA / "items.json"
LABELS_PATH = DATA / "labels.json"

KINDS = ("note", "card", "quiz")
SEED = 20261110
QUOTAS = {
    "plain": {"note": 14, "card": 12, "quiz": 9},  # model output, unchanged
    "altered": {"note": 10, "card": 8, "quiz": 7},  # model output changed by hand to be wrong
}
ALTERATION_TYPES = ("negation", "number", "opposite", "swapped_name", "wrong_detail", "wrong_key")

ANSWERS = {"y": "supported", "n": "not_supported", "u": "unsure"}
GUIDE = """Judge each claim using ONLY the passage shown, not what you know.

  y  supported: the passage states it, or it plainly follows.
  n  not supported: the passage contradicts it, doesn't say it, or it's about the wrong thing.
  u  unsure: you honestly can't tell.

For a flashcard, judge the answer to that question. For a quiz question, judge the option
marked correct. Don't judge whether it's a good question, only whether it's true to the
passage. Your answers are saved as you go: q quits, and running this again carries on."""
PROMPT = "Supported by the passage? [y]es [n]o [u]nsure [b]ack [q]uit: "


class MissingAlterations(Exception):
    """Some chosen claims have no hand-written alteration yet."""

    def __init__(self, bases: list[dict]):
        super().__init__(f"{len(bases)} claims need an alteration")
        self.bases = bases


# ------------------------------------------------------------ reading model replies

def passages_in_prompt(prompt: str) -> list[str]:
    """The numbered passages a prompt showed the model, as `numbered_passages` wrote them."""
    blocks = re.split(r"\n\n(?=\[\d+\](?: Section: |\n))", prompt.split("Passages:\n\n", 1)[1])
    return [re.sub(r"^\[\d+\](?: Section: [^\n]*)?\n", "", block, count=1) for block in blocks]


def _raw_items(data: dict):
    sections = data.get("sections")
    for section in sections if isinstance(sections, list) else []:
        points = section.get("points") if isinstance(section, dict) else None
        for point in points if isinstance(points, list) else []:
            yield "note", point
    for key, kind in (("cards", "card"), ("questions", "quiz")):
        items = data.get(key)
        yield from ((kind, item) for item in (items if isinstance(items, list) else []))


def _claim(kind: str, item: dict) -> dict | None:
    """The claim an item makes, in the shape its check expects, or None if it's malformed."""
    if kind == "note":
        return {"text": item["text"]} if isinstance(item.get("text"), str) else None
    question = item.get("question")
    if not isinstance(question, str):
        return None
    if kind == "card":
        return {"question": question, "answer": item["answer"]} if isinstance(item.get("answer"), str) else None
    options, answer = item.get("options"), item.get("answer")
    if not (isinstance(options, list) and all(isinstance(o, str) for o in options)):
        return None
    if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(options):
        return None
    return {"question": question, "options": options, "answer": answer}


def candidates_from_reply(prompt: str, reply: str) -> list[dict]:
    """Every well-formed claim in a model's reply, including those the checks would reject."""
    start, end = reply.find("{"), reply.rfind("}")
    try:
        data = json.loads(reply[start : end + 1]) if 0 <= start < end else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return []
    chunks = [Chunk(i, text, [Sentence(text)]) for i, text in enumerate(passages_in_prompt(prompt))]
    found = []
    for kind, item in _raw_items(data):
        if not isinstance(item, dict) or not isinstance(item.get("quote"), str):
            continue
        index, claim = cited_passage(item, chunks), _claim(kind, item)
        if index is not None and claim is not None:
            found.append({"kind": kind, "passage": chunks[index - 1].text, "quote": item["quote"], "claim": claim})
    return found


# ------------------------------------------------------------------ the checks under test

def accepted(item: dict) -> bool:
    """Would the application's real checks let this claim through?"""
    passage = Chunk(0, item["passage"], [Sentence(item["passage"])])
    raw = {"passage": 1, "quote": item["quote"], **item["claim"]}
    if item["kind"] == "note":
        return _checked_point(raw, [passage]) is not None
    if item["kind"] == "card":
        return _checked_card(raw, passage) is not None
    return _checked_question(raw, passage) is not None


# ---------------------------------------------------------------------- choosing items

def _spread(pool: list[dict], rng: random.Random) -> list[dict]:
    """Shuffled within each document, then taken from the documents in turn."""
    documents = sorted({c["document"] for c in pool})
    queues = [rng.sample(group, len(group)) for group in ([c for c in pool if c["document"] == d] for d in documents)]
    ordered = []
    while any(queues):
        ordered += [queue.pop() for queue in queues if queue]
    return ordered


def select(candidates: list[dict], seed: int = SEED, quotas: dict = QUOTAS) -> tuple[list[dict], list[dict]]:
    """(claims kept as written, claims to alter). They never overlap, so a labeller can't
    spot an altered claim by comparing it with its original. Only claims the checks accept
    are altered: changing one they already reject would tell us nothing."""
    rng = random.Random(seed)
    plain, bases = [], []
    for kind in KINDS:
        ordered = _spread([c for c in candidates if c["kind"] == kind], rng)
        keep = quotas["plain"][kind]
        plain += ordered[:keep]
        bases += [c for c in ordered[keep:] if accepted(c)][: quotas["altered"][kind]]
    return plain, bases


def build_items(candidates: list[dict], alterations: dict, seed: int = SEED, quotas: dict = QUOTAS) -> list[dict]:
    """The benchmark: unchanged and altered claims, shuffled together."""
    plain, bases = select(candidates, seed, quotas)
    missing = [c for c in bases if c["id"] not in alterations]
    if missing:
        raise MissingAlterations(missing)
    items = [{**c, "origin": "model", "alteration": None, "from": c["id"]} for c in plain]
    for base in bases:
        alteration = alterations[base["id"]]
        if alteration["type"] not in ALTERATION_TYPES:
            raise ValueError(f"{base['id']}: unknown alteration type {alteration['type']!r}")
        claim = {**base["claim"], **alteration["changes"]}
        if claim == base["claim"]:
            raise ValueError(f"{base['id']}: the alteration changes nothing")
        items.append({**base, "claim": claim, "original": base["claim"], "origin": "altered",
                      "alteration": alteration["type"], "from": base["id"]})
    random.Random(seed).shuffle(items)
    return [{**item, "id": f"c{n:02}"} for n, item in enumerate(items, start=1)]


# ------------------------------------------------------------------------- labelling

def _wrapped(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, width=92, initial_indent=indent, subsequent_indent=indent)


def render(item: dict) -> str:
    """An item as the labeller sees it: only the passage and the claim, so nothing hints at
    how the item was made or whether the checks accept it."""
    claim = item["claim"]
    if item["kind"] == "note":
        shown = "STUDY NOTE\n" + _wrapped(claim["text"])
    elif item["kind"] == "card":
        shown = "FLASHCARD\n" + _wrapped("Question: " + claim["question"]) + "\n" + _wrapped("Answer: " + claim["answer"])
    else:
        options = "\n".join(_wrapped(f"{letter}) {text}") for letter, text in zip("abcdefgh", claim["options"]))
        shown = ("QUIZ QUESTION\n" + _wrapped(claim["question"]) + "\n" + options + "\n"
                 + _wrapped("Marked correct: " + claim["options"][claim["answer"]]))
    return "PASSAGE\n" + _wrapped(item["passage"]) + "\n\n" + shown


def label(items: list[dict], path: Path = LABELS_PATH, read=input, write=print) -> None:
    """Ask a person about each item, saving after every answer."""
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"labeller": None, "labels": {}}
    labels = saved["labels"]
    position = next((n for n, item in enumerate(items) if item["id"] not in labels), len(items))

    def save():
        path.write_text(json.dumps(saved, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        if position < len(items):
            write(GUIDE)
        if position < len(items) and not saved["labeller"]:
            saved["labeller"] = read("\nYour name (saved with your answers): ").strip() or "anonymous"
        while position < len(items):
            item = items[position]
            current = f"   (currently: {labels[item['id']]})" if item["id"] in labels else ""
            write(f"\n--- {position + 1} of {len(items)}{current}\n" + render(item) + "\n")
            answer = read(PROMPT).strip().lower()
            if answer == "q":
                break
            if answer == "b":
                position = max(0, position - 1)
            elif answer in ANSWERS:
                labels[item["id"]] = ANSWERS[answer]
                save()
                position += 1
            else:
                write("Please type y, n, u, b or q.")
    except EOFError:
        pass
    write(f"All {len(items)} items are labelled." if len(labels) >= len(items) and position >= len(items)
          else f"Saved {len(labels)} of {len(items)}. Run this again to carry on.")


# --------------------------------------------------------------------------- scoring

def score(items: list[dict], labels: dict, check=accepted) -> dict:
    """How the checks did against the labels. Unsure and unlabelled items count as neither."""
    def tally():
        return {"not_supported": 0, "wrongly_accepted": 0, "supported": 0, "wrongly_rejected": 0}

    overall, by_kind = tally(), {kind: tally() for kind in sorted({i["kind"] for i in items})}
    altered, altered_but_supported = {}, []
    model_labelled = model_not_supported = 0
    for item in items:
        passes, verdict = check(item), labels.get(item["id"])
        if item["origin"] == "altered":
            entry = altered.setdefault(item["alteration"], {"total": 0, "accepted": 0})
            entry["total"] += 1
            entry["accepted"] += passes
        if verdict not in ("supported", "not_supported"):
            continue
        for counts in (overall, by_kind[item["kind"]]):
            counts[verdict] += 1
            counts["wrongly_accepted"] += verdict == "not_supported" and passes
            counts["wrongly_rejected"] += verdict == "supported" and not passes
        if item["origin"] == "model":
            model_labelled += 1
            model_not_supported += verdict == "not_supported"
        elif verdict == "supported":
            altered_but_supported.append(item["id"])
    return {
        **overall,
        "total": len(items),
        "labelled": sum(i["id"] in labels for i in items),
        "unsure": sum(labels.get(i["id"]) == "unsure" for i in items),
        "by_kind": by_kind,
        "altered": altered,
        "altered_but_supported": altered_but_supported,
        "model_labelled": model_labelled,
        "model_not_supported": model_not_supported,
    }


def _altered_lines(altered: dict) -> list[str]:
    lines = [f"  {name:14} {entry['accepted']} of {entry['total']} accepted" for name, entry in sorted(altered.items())]
    accepted_total, total = sum(e["accepted"] for e in altered.values()), sum(e["total"] for e in altered.values())
    return lines + [f"  {'all':14} {accepted_total} of {total} accepted"]


def report(result: dict, labeller: str | None = None) -> str:
    lines = [f"Claim benchmark: {result['total']} items, {result['labelled']} labelled."]
    if not result["labelled"]:
        return "\n".join(lines + ["", "No human labels yet, so this is provisional. Claims altered by hand to be wrong,",
                                  "all of which the checks should reject:", *_altered_lines(result["altered"])])
    lines += [
        f"Labelled by {labeller or 'unknown'}; unsure on {result['unsure']}.", "",
        f"Wrongly accepted (false confidence): {result['wrongly_accepted']} of {result['not_supported']} "
        "claims a person said the passage doesn't support.",
        f"Wrongly rejected: {result['wrongly_rejected']} of {result['supported']} "
        "claims a person said the passage does support.",
        f"Unaltered model claims a person found unsupported: {result['model_not_supported']} of {result['model_labelled']}.",
        "", "By kind:",
    ]
    for kind, counts in result["by_kind"].items():
        lines.append(f"  {kind:14} accepted {counts['wrongly_accepted']} of {counts['not_supported']} unsupported; "
                     f"rejected {counts['wrongly_rejected']} of {counts['supported']} supported")
    lines += ["", "Claims altered by hand to be wrong:", *_altered_lines(result["altered"])]
    if result["altered_but_supported"]:
        lines += ["", "Altered, but a person called them supported (worth a second look): "
                  + ", ".join(result["altered_but_supported"])]
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

class _Recorder:
    """Passes requests to a writer and keeps each prompt and reply."""

    def __init__(self, writer):
        self.writer, self.name, self.calls = writer, writer.name, []

    def write(self, prompt: str, **kwargs) -> str:
        reply = self.writer.write(prompt, **kwargs)
        self.calls.append((prompt, reply))
        return reply


def collect(model: str, paths: list[str]) -> None:
    """Run the app's own notes, cards and quiz steps on each document with a local model,
    and save everything the model wrote."""
    from rag import RAG
    from rag.cards import build_cards
    from rag.generator import OllamaGenerator
    from rag.notes import make_notes
    from rag.quiz import build_quiz, writer_for

    DATA.mkdir(exist_ok=True)
    found: list[dict] = []
    for path in paths:
        generator = OllamaGenerator(model)
        recorder = _Recorder(writer_for(generator))
        generator.quiz_writer = recorder
        rag, name = RAG(path, generator), Path(path).stem
        for step in (lambda: make_notes(rag, name),
                     lambda: build_cards(rag.chunks, 10, title=name, writer=recorder, seed=1),
                     lambda: build_quiz(rag.chunks, 5, title=name, writer=recorder, seed=1)):
            try:
                step()
            except Exception as e:  # one step failing shouldn't lose the other documents
                print(f"  {name}: a step failed: {type(e).__name__}", flush=True)
        numbers = Counter()
        for prompt, reply in recorder.calls:
            for candidate in candidates_from_reply(prompt, reply):
                numbers[candidate["kind"]] += 1
                found.append({"id": f"{name}-{candidate['kind']}-{numbers[candidate['kind']]}", "document": name, **candidate})
        print(f"{name}: {dict(numbers)}", flush=True)
        CANDIDATES_PATH.write_text(json.dumps({"model": model, "candidates": found}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_items() -> list[dict]:
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))["items"]


def build() -> int:
    data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    alterations = json.loads(ALTERATIONS_PATH.read_text(encoding="utf-8")) if ALTERATIONS_PATH.exists() else {}
    try:
        items = build_items(data["candidates"], alterations)
    except MissingAlterations as e:
        print(json.dumps([{k: c[k] for k in ("id", "kind", "quote", "claim")} for c in e.bases], indent=1, ensure_ascii=False))
        print(f"\n{len(e.bases)} chosen claims need an entry in {ALTERATIONS_PATH}.", file=sys.stderr)
        return 1
    ITEMS_PATH.write_text(json.dumps({"model": data["model"], "items": items}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} items to {ITEMS_PATH}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the checks on model-written claims.")
    commands = parser.add_subparsers(dest="command", required=True)
    collecting = commands.add_parser("collect", help="save what a local model writes for public documents")
    collecting.add_argument("model")
    collecting.add_argument("paths", nargs="+")
    commands.add_parser("build", help="choose and mix the items")
    for name, text in (("label", "judge each item yourself"), ("score", "see how the checks did")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--labels", type=Path, default=LABELS_PATH, help="labels file (one per person)")
    args = parser.parse_args()

    if args.command == "collect":
        collect(args.model, args.paths)
    elif args.command == "build":
        return build()
    elif args.command == "label":
        label(_load_items(), args.labels)
    else:
        saved = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels.exists() else {"labels": {}, "labeller": None}
        print(report(score(_load_items(), saved["labels"]), saved["labeller"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
