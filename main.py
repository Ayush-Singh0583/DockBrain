"""Ask questions about a document (.txt, .md, .docx or .pdf).

Usage:
    python main.py path/to/document [--offline] [--show-sources]

Written answers use, in this order: OLLAMA_MODEL (a model on this computer, through
Ollama, so nothing leaves it), GEMINI_API_KEY, or ANTHROPIC_API_KEY, from the terminal or a
.env file next to this script. Without any of them, or with --offline, no model is used
and answers quote the document.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from rag import RAG
from rag.generator import ClaudeGenerator, ExtractiveGenerator, GeminiGenerator, OllamaGenerator

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file(path: Path) -> None:
    """Read settings like GEMINI_API_KEY from a .env file. A value already set in the
    terminal wins, so one run can override the file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(.*)$", line)
        if match:
            os.environ.setdefault(match[1], re.sub(r"\s+#.*$", "", match[2]).strip().strip("'\""))


def pick_generator(offline: bool):
    """Offline unless a model is set up: OLLAMA_MODEL (on this computer), then
    GEMINI_API_KEY, then ANTHROPIC_API_KEY."""
    if not offline and os.environ.get("OLLAMA_MODEL", "").strip():
        generator = OllamaGenerator()
        return generator, f"Ollama {generator.model} (runs on this computer; nothing is sent anywhere)"
    if not offline and os.environ.get("GEMINI_API_KEY", "").strip():
        generator = GeminiGenerator()
        return generator, f"Gemini {generator.model} (parts of the document are sent to Google)"
    if not offline and _has_claude_credentials():
        try:
            return ClaudeGenerator(), "Claude"
        except ImportError:
            print("Note: 'anthropic' package not installed; using offline extractive answers.")
        except Exception as e:  # missing credentials etc.
            print(f"Note: Claude unavailable ({e}); using offline extractive answers.")
    return ExtractiveGenerator(), "extractive (offline)"


def main():
    parser = argparse.ArgumentParser(description="RAG Q&A over a document (.txt, .md, .docx, .pdf)")
    parser.add_argument("file")
    parser.add_argument("--offline", action="store_true", help="use no AI model: answers quote the document, and nothing is sent anywhere")
    parser.add_argument("--show-sources", action="store_true", help="print retrieved chunks")
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()

    load_env_file(ENV_FILE)
    generator, name = pick_generator(args.offline)
    try:
        rag = RAG(args.file, generator, top_k=args.top_k)
    except (OSError, ValueError) as e:
        sys.exit(f"Error: {e}")
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


def _has_claude_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


if __name__ == "__main__":
    main()
