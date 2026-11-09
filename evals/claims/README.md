# Claim benchmark

DockBrain's model writes study notes, flashcards and quiz questions. Before one is shown,
code checks it against the document (`_checked_point` in `rag/notes.py`, `_checked_card` in
`rag/cards.py`, `_checked` in `rag/quiz.py`). This benchmark measures how often those checks
get it wrong, judged by a person and not by the checks.

- **Wrongly accepted:** the passage doesn't support the claim, but it would reach a student.
  This is the number that matters most.
- **Wrongly rejected:** the passage does support the claim, but it was thrown away.

It measures whether a claim is true to its passage. It doesn't measure whether a question is
useful, whether its wrong options are fair, or whether anyone learns from it.

## Label it

Reading 60 short items takes about 30 to 45 minutes. Your answers are saved as you go.

```bash
.venv/bin/python -B evals/claim_benchmark.py label
.venv/bin/python -B evals/claim_benchmark.py score
```

Judge only from the passage on screen. Please don't open `items.json` first: it says which
claims were altered. For a second person, add `--labels evals/claims/labels-NAME.json` to
both commands.

## What's in it

60 items, in random order:

- **35 written by the model and left unchanged.** Chosen at random, spread across the
  documents, and including items the checks reject, so wrong rejections can be counted.
- **25 written by the model and then changed by hand to be wrong**: negation, a changed
  number, an opposite word, a swapped name, a changed detail, or a quiz whose answer key
  points at the wrong option. Only claims the checks accepted were altered. No altered
  claim also appears unaltered.

| File | What it holds |
| --- | --- |
| `candidates.json` | Everything the model wrote for the documents below |
| `alterations.json` | The hand-written changes |
| `items.json` | The frozen set. `claim_benchmark.py build` remakes it exactly from the two files above |
| `labels.json` | A person's answers (absent until someone labels the set) |

## Keeping it honest

- The set is frozen, so a change to the checks is compared on the same items.
- Don't change the items or labels to improve a score. If a label is wrong, correct it and
  say so where the score is reported.
- The person labelling shouldn't be the author of the checks.
- `score` runs whatever the checks are at that moment, so run it before and after any change.

## Sources

Model: `qwen3.5:9b` through Ollama, on 2026-11-10, using DockBrain's own prompts.

| Document | Source |
| --- | --- |
| `sample` | `sample.txt` in this repository |
| `ml-ids-sample` | `evals/ml-ids-sample.txt`, an invented document |
| `Apple` | Wikipedia, [Apple](https://en.wikipedia.org/wiki/Apple), as a PDF, fetched 2026-11-07 |
| `Photosynthesis` | Wikipedia, [Photosynthesis](https://en.wikipedia.org/w/index.php?oldid=1383248806), revision 1383248806 |
| `Transmission_Control_Protocol` | Wikipedia, [Transmission Control Protocol](https://en.wikipedia.org/w/index.php?oldid=1382108671), revision 1382108671 |
| `Printing_press` | Wikipedia, [Printing press](https://en.wikipedia.org/w/index.php?oldid=1384322441), revision 1384322441 |

Wikipedia text is available under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The claims in these files
are derived from it, and the altered ones are deliberately false.
