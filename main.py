"""Ask questions about a text file.

Usage:
    python main.py path/to/file.txt [--offline] [--show-sources]
"""
import argparse
import os

from rag import RAG
from rag.generator import ClaudeGenerator, ExtractiveGenerator


def pick_generator(offline: bool):
    if offline:
        return ExtractiveGenerator(), "extractive (offline)"
    try:
        return ClaudeGenerator(), "Claude"
    except ImportError:
        print("Note: 'anthropic' package not installed; using offline extractive answers.")
    except Exception as e:  # missing credentials etc.
        print(f"Note: Claude unavailable ({e}); using offline extractive answers.")
    return ExtractiveGenerator(), "extractive (offline)"


def main():
    parser = argparse.ArgumentParser(description="RAG Q&A over a text file")
    parser.add_argument("file")
    parser.add_argument("--offline", action="store_true", help="don't call an LLM")
    parser.add_argument("--show-sources", action="store_true", help="print retrieved chunks")
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()

    generator, name = pick_generator(args.offline or not _has_credentials())
    rag = RAG(args.file, generator, top_k=args.top_k)
    print(f"Indexed {len(rag.chunks)} chunks from {args.file} | answers: {name}")
    print("Ask a question (empty line or 'exit' to quit).\n")

    while True:
        try:
            q = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in {"exit", "quit"}:
            break
        try:
            answer, hits = rag.ask(q)
        except Exception as e:
            print(f"Error: {e}\n")
            continue
        print(f"A: {answer}\n")
        if args.show_sources:
            for i, (chunk, score) in enumerate(hits, 1):
                print(f"  [{i}] (score {score:.2f}) {chunk.text[:150]}...")
            print()


def _has_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    print("Note: no ANTHROPIC_API_KEY set; using offline extractive answers.")
    return False


if __name__ == "__main__":
    main()
