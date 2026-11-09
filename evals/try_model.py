"""Try a local Ollama model on a document: its notes, cards and quiz, and how many of its
items pass the grounding checks.

Usage: .venv/bin/python -B evals/try_model.py MODEL PATH [--counts-only]

Use --counts-only for private documents, so none of their text is printed.
"""
import sys, time, json, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag import RAG
from rag.generator import OllamaGenerator
from rag.notes import make_notes
from rag.cards import build_cards
from rag.quiz import build_quiz, writer_for
model, path = sys.argv[1], sys.argv[2]
counts = '--counts-only' in sys.argv
g = OllamaGenerator(model)
class Timed:
    def __init__(self, w): self.w, self.name, self.t, self.replies = w, w.name, [], []
    def write(self, *a, **k):
        s = time.time(); r = self.w.write(*a, **k); self.t.append(round(time.time()-s,1)); self.replies.append(r); return r
w = Timed(writer_for(g)); g.quiz_writer = w
rag = RAG(path, g)
print(f"== {model} on {os.path.basename(path)}: {len(rag.chunks)} passages", flush=True)

def raw_items(key):
    try:
        d = json.loads(w.replies[-1]); return d.get(key) or []
    except Exception: return []

n = make_notes(rag, os.path.basename(path)); print(f"notes {w.t[-1]}s notice={n.get('notice')}", flush=True)
raw = raw_items('sections'); raw_pts = sum(len(s.get('points') or []) for s in raw if isinstance(s, dict)); kept = sum(len(s['points']) for s in n['sections'])
print(f"  sections {len(n['sections'])} of {len(raw)}; points kept {kept} of {raw_pts}; summary words {len(n['summary'].split())}")
if not counts:
    print("  TITLE:", n['title']); print("  SUMMARY:", n['summary'])
    for s in n['sections']:
        print("  #", s['heading'])
        for p in s['points']: print("    -", p['text'], p['citations'])
    print("  Q:", n['suggestedQuestions'])

c = build_cards(rag.chunks, 10, title="x", writer=w, seed=1); print(f"cards {w.t[-1]}s kinds={sorted(set(x.kind for x in c.cards))} n={len(c.cards)} of raw {len(raw_items('cards'))} notice={c.notice}", flush=True)
if not counts:
    for x in c.cards: print(f"  [{x.kind[:3]}] {x.prompt}  =>  {x.answer}")

q = build_quiz(rag.chunks, 5, title="x", writer=w, seed=1); print(f"quiz {w.t[-1]}s n={len(q.questions)} of raw {len(raw_items('questions'))} engine={q.engine} notice={q.notice}", flush=True)
if not counts:
    for x in q.questions:
        right = next(o.text for o in x.options if o.id == x.correct_option_id)
        print(f"  {x.prompt}  =>  {right}   | {[o.text for o in x.options if o.text != right]}")
