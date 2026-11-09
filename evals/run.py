"""Measure search and offline answers on the question sets. Offline only; nothing is sent anywhere.

    .venv/bin/python -B evals/run.py --prepare   # once: download the public Wikipedia "Apple" PDF and, if
                                                 # this copy has the private reports in docs/, convert them
                                                 # to PDF (needs network and LibreOffice)
    .venv/bin/python -B evals/run.py             # print the numbers

The private reports and the questions about them aren't in the repository, so in a public copy
these numbers cover the public and invented documents only.
"""
import argparse
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

from questions import APPLE, DATA, FRESH, OLD, TUNING, judge  # noqa: E402
from rag import RAG  # noqa: E402
from rag.generator import ExtractiveGenerator  # noqa: E402

APPLE_URL = "https://en.wikipedia.org/api/rest_v1/page/pdf/Apple"


def report_files(folder: str = "docs") -> list[str]:
    """The private reports to convert, if this copy has them."""
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".docx")]


def prepare() -> None:
    os.makedirs(DATA, exist_ok=True)
    request = urllib.request.Request(APPLE_URL, headers={"User-Agent": "DockBrain-evals/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, open(APPLE, "wb") as out:
        out.write(response.read())
    docx = report_files()
    if docx:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", DATA, *docx], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Prepared {DATA}/. The Wikipedia PDF changes over time, so numbers can drift slightly.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prepare", action="store_true")
    if parser.parse_args().prepare:
        prepare()
        return
    cache = {}

    def rag(path):
        return cache.setdefault(path, RAG(path, ExtractiveGenerator()))

    def found(questions, k):
        return sum(ev.lower() in " ".join(c.text for c, _ in rag(f).retriever.search(q, k)).lower() for f, q, ev in questions)

    def quoted(questions):
        return sum(ev.lower() in rag(f).ask(q)[0].lower() for f, q, ev in questions)

    for name, questions in (("tuning", TUNING), ("fresh (held out)", FRESH)):
        print(f"{name:17} {len(questions)} reworded: evidence in top 4 {found(questions, 4)}, "
              f"top 8 {found(questions, 8)}; offline answer quotes it {quoted(questions)}")
    unanswerable = [c for c in OLD if c[2] == ["couldn't find"]]
    print(f"old answer quality: {sum(judge(c, rag(c[0]).ask(c[1])[0]) for c in OLD)}/{len(OLD)} "
          f"(of which unanswerable questions correctly not answered: "
          f"{sum(judge(c, rag(c[0]).ask(c[1])[0]) for c in unanswerable)}/{len(unanswerable)})")
    pdf = [c for c in OLD if c[0].endswith(".docx")]
    if not pdf:
        print("report questions skipped: the private reports aren't in this copy")
        return
    as_pdf = sum(judge(c, rag(f"{DATA}/{os.path.basename(c[0])[:-5]}.pdf").ask(c[1])[0]) for c in pdf)
    print(f"report questions as .docx {sum(judge(c, rag(c[0]).ask(c[1])[0]) for c in pdf)}/{len(pdf)}, "
          f"as PDF conversions {as_pdf}/{len(pdf)}")


if __name__ == "__main__":
    main()
