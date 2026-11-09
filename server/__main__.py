"""Run DockBrain's HTTP API for the web app.

    python -m server [--host 127.0.0.1] [--port 8000] [--offline]

Then set VITE_DOCKBRAIN_API_URL=http://127.0.0.1:8000/api/v1 in FRONTEND/.env.local.
The model (OLLAMA_MODEL) and provider keys come from the terminal or the .env file next to
main.py, as for the CLI.
"""
import argparse
import logging
import os

from main import ENV_FILE, load_env_file

from .app import API_PREFIX, create_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m server", description="DockBrain HTTP API for the web app")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--offline", action="store_true", help="use no AI model: notes, cards and quizzes are cut from the document's sentences")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    load_env_file(ENV_FILE)
    ttl = os.environ.get("DOCKBRAIN_SESSION_TTL")
    server = create_server(args.host, args.port, offline=args.offline, ttl_seconds=float(ttl) if ttl else None)
    print(f"DockBrain API on http://{args.host}:{server.server_port}{API_PREFIX} | answers: {server.answer_engine}")
    check = getattr(server.generator_factory(), "startup_problem", None)
    problem = check() if check else None
    if problem:
        print(f"Warning: {problem}")
        print("Until then, notes, cards and quizzes are cut from the document's sentences, and questions can't be answered.")
    print("Press Ctrl+C to stop. Uploaded documents are deleted when their session ends.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.store.close()


if __name__ == "__main__":
    main()
