"""Question sets for measuring DockBrain's search and offline answers.

- OLD: answer-quality questions used since the first session (pass/fail by required and banned words).
- TUNING: reworded questions used while tuning search (already seen; don't tune on FRESH).
- FRESH: reworded questions written on 2026-11-07 before any measurement, held out.

Each TUNING/FRESH entry is (document, question, evidence phrase that must appear in the
retrieved text). Paths are relative to the repository root; `python evals/run.py --prepare`
creates the files under evals/data/.

These cover public and invented documents. Questions about the private reports in docs/ are in
evals/private_questions.py, which is gitignored and added below when it's there: 43 OLD, 23 TUNING
and 16 FRESH with it, 14, 14 and 10 without.
"""
DATA = "evals/data"
APPLE = f"{DATA}/apple-wikipedia.pdf"
IDS, CODEX = "evals/ml-ids-sample.txt", "evals/codex-apples.txt"
S = "sample.txt"
NOISE = ["thank", "grateful", "certify", "affirm", "violation", "submitted", "chapter 5", "chapter 2"]
TUNING = [
 (APPLE, 'Which country produces the most apples?', 'China producing'),
 (APPLE, 'Who is the biggest apple producer in the world?', 'China producing'),
 (APPLE, 'Who grows the most apples?', 'China producing'),
 (APPLE, 'How many tonnes of apples are made worldwide?', '98 million tonnes'),
 (APPLE, 'Are apple seeds dangerous to eat?', 'amygdalin'),
 (APPLE, 'Which bugs attack apple trees?', 'codling moth'),
 (APPLE, 'Where did apples first come from?', 'Central Asia'),
 (APPLE, 'What botanical family do apples belong to?', 'Rosaceae'),
 (APPLE, 'How are apples kept fresh after harvest?', 'controlled'),
 (APPLE, 'Do apples help prevent illness?', 'health'),
 (IDS, 'What algorithm classifies the traffic?', 'random forest'),
 (IDS, 'How accurate is the model?', '97 percent'),
 (IDS, 'Where do the warnings get saved?', 'log file'),
 (CODEX, 'Who produces the most?', 'China accounts'),
]

FRESH = [
 (APPLE, 'Which nation leads the world in apple output?', 'China producing'),
 (APPLE, 'What harmful chemical is found in the seeds?', 'amygdalin'),
 (APPLE, 'What is the scientific name for the apple tree?', 'Malus domestica'),
 (APPLE, 'When in the year do apples ripen?', 'late summer'),
 (APPLE, 'Which countries come after the top producer?', 'Secondary producers'),
 (APPLE, 'Name an insect that harms orchards.', 'codling moth'),
 (IDS, 'Which data was the model trained on?', 'CICIDS2017'),
 (IDS, 'Who looks at the warnings?', 'Administrators'),
 (IDS, 'What kinds of attacks get caught?', 'port scans'),
 (CODEX, 'Which nation leads production?', 'China accounts'),
]

OLD = [  # (file, question, required groups, banned)
 (S, 'How many planets are there?', ['eight'], ['iron oxide']),
 (S, 'What is the largest planet?', ['jupiter is the largest'], ['iron oxide', 'there are eight']),
 (S, 'Why is Mars called the Red Planet?', ['iron oxide'], ['pluto']),
 (S, 'What happened to Pluto?', ['dwarf'], []),
 (S, 'What is the tallest volcano?', ['olympus mons'], []),
 (S, 'How old is the Solar System?', ['4.6 billion'], ['olympus']),
 (S, 'Which planets are gas giants?', ['jupiter'], []),
 (S, 'What are the moons of Mars?', ['phobos'], []),
 (S, 'How long has the Great Red Spot lasted?', ['350'], []),
 (S, 'Where is most of the mass of the Solar System?', ['sun'], []),
 (S, 'What is the capital of France?', ["couldn't find"], []),
 (S, 'What is Olympus Mons?', ['volcano'], []),
 (S, 'Is Pluto a planet?', ['dwarf'], []),
 (S, 'What is the weather on Mars?', ["couldn't find"], []),
]

try:
    import private_questions as _private
except ImportError:  # a public copy of the repository
    _private = None
if _private is not None:
    TUNING, FRESH, OLD = TUNING + _private.TUNING, FRESH + _private.FRESH, OLD + _private.OLD


def judge(case, answer: str) -> bool:
    low = answer.lower()
    return all(any(w in low for w in g.split("|")) for g in case[2]) and not any(b in low for b in case[3])
