"""Routes for "Learn from a document": upload a document, read study notes on it, ask
questions about it with citations, fetch a cited passage whole, and end the session
(FRONTEND/API_CONTRACT.md).

Answers come from the existing RAG pipeline (`rag.RAG`): the same loader, chunker, search
and answer engines as the command line. The engine reports where each answer came from:
"document" (cited excerpts), "mixed" (partly cited, the rest labelled general knowledge),
"general" (labelled general knowledge, citing nothing) or "insufficient" (no answer).
"""
import secrets
import shutil

from rag import RAG
from rag.chunker import Chunk
from rag.notes import make_notes

from .errors import ApiError, for_browser, invalid, not_found, provider_error
from .uploads import read_upload

MAX_QUESTION_CHARS = 1000

_OLD_WORD = ("Old Word .doc files can't be read. Open the file in Word, save it as .docx, "
             "and choose that file instead.")


def create_session(request):
    """POST /sessions: upload a document; it is read and indexed in the background."""
    server = request.server
    directory = request.store.new_directory()
    try:
        upload = read_upload(request.handler, directory, server.max_document_bytes)
        kind = upload.fields.get("kind", "").strip()
        if kind == "codebase":
            raise ApiError(415, "unsupported", "This DockBrain server doesn't explain codebases yet. Choose a document.")
        if kind != "document":
            raise invalid('Say what is being uploaded: the "kind" field must be "document".')
        if upload.path is None:
            raise invalid('Choose a document to upload: the "file" field is missing.')
        extension = upload.path.suffix.lower()
        if extension == ".doc":
            raise ApiError(415, "unsupported", _OLD_WORD)
        if extension not in server.document_extensions:
            raise ApiError(415, "unsupported", f"{upload.filename} can't be read. Choose a PDF, Word (.docx), "
                                               "text or Markdown file.")
        if upload.size == 0:
            raise ApiError(422, "unreadable", f"{upload.filename} is empty. Choose a file with some text in it.")
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    def build():
        try:
            engine = server.generator_factory()
        except Exception:
            raise ApiError(503, "unavailable", "The answer service isn't set up correctly on this server.") from None
        try:
            rag = RAG(str(upload.path), engine)
        except ValueError as e:  # the loader's reasons are written for people and name only the file
            raise ApiError(422, "unreadable", str(e)) from None
        if not rag.chunks:
            raise ApiError(422, "unreadable", f"{upload.filename} has no readable text.")
        return rag

    session = request.store.start("document", upload.filename, directory, build)
    return 202, session.resource()


def get_session(request):
    """GET /sessions/{session_id}: the session's status, polled while processing."""
    return 200, request.store.get(request.params["session_id"]).resource()


def delete_session(request):
    """DELETE /sessions/{session_id}: end the session and delete its data (idempotent)."""
    request.store.delete(request.params["session_id"])
    return 204, None


def notes(request):
    """GET /sessions/{session_id}/notes: study notes on the document, each point citing its
    passage, written by the session's model if it has one. Kept for the session, unless the
    model failed, so that opening the notes again can try it again."""
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        if session.rag is None:  # deleted or expired while waiting for the lock
            raise not_found()
        result = session.data.get("notes")
        if result is None:
            result = make_notes(session.rag, session.display_name)
            if result.get("notice"):
                result = {**result, "notice": for_browser(result["notice"])}
            else:
                session.data["notes"] = result
    session.touch()
    return 200, result


def ask(request):
    """POST /sessions/{session_id}/questions: answer from the document, with citations."""
    body = request.json()
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise invalid("Type a question first.")
    if len(question) > MAX_QUESTION_CHARS:
        raise invalid(f"Questions can be at most {MAX_QUESTION_CHARS} characters long.")
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        if session.rag is None:  # deleted or expired while waiting for the lock
            raise not_found()
        try:
            reply = session.rag.reply(question.strip())
        except RuntimeError as e:
            raise provider_error(e) from None
    session.touch()
    return 200, {
        "id": "a_" + secrets.token_urlsafe(9),
        "question": question,
        "text": reply.text,
        "origin": reply.origin,
        "citations": [citation(i, *reply.hits[i - 1]) for i in sorted(reply.cited) if 1 <= i <= len(reply.hits)],
        "coverage": reply.coverage,
        "demo": False,
    }


def passage(request):
    """GET /sessions/{session_id}/passages/{passage_id}: a passage whole, with its neighbours."""
    session = request.store.get_ready(request.params["session_id"])
    raw = request.params["passage_id"]
    with session.lock:
        chunks = session.rag.chunks if session.rag is not None else []
    if not raw.isdigit() or int(raw) >= len(chunks):
        raise not_found("That passage isn't in this document.")
    chunk = chunks[int(raw)]
    return 200, {
        "passageId": chunk.id,
        "text": chunk.text,
        "section": section_of(chunk),
        "previousId": chunk.id - 1 if chunk.id > 0 else None,
        "nextId": chunk.id + 1 if chunk.id + 1 < len(chunks) else None,
    }


def section_of(chunk: Chunk) -> str | None:
    """The heading the passage falls under, if the chunker found one."""
    return next((s.section for s in chunk.sentences if s.section), None)


def citation(index: int, chunk: Chunk, score: float) -> dict:
    """An excerpt the answer cites as [index] (or quotes, offline)."""
    out = {"index": index, "excerpt": chunk.text, "passageId": chunk.id, "score": round(float(score), 3)}
    section = section_of(chunk)
    if section:
        out["section"] = section
    return out


ROUTES = [
    ("POST", "/sessions", create_session),
    ("GET", "/sessions/{session_id}", get_session),
    ("DELETE", "/sessions/{session_id}", delete_session),
    ("GET", "/sessions/{session_id}/notes", notes),
    ("POST", "/sessions/{session_id}/questions", ask),
    ("GET", "/sessions/{session_id}/passages/{passage_id}", passage),
]
