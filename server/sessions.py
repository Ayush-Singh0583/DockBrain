"""Document sessions: each upload is read and indexed once, then kept in memory.

Uploads live in their own temporary directory only until indexing ends (successfully or
not), so the file is gone as soon as it isn't needed. The index (`session.rag`) is deleted
with the session: on `DELETE /sessions/{id}`, or after `ttl_seconds` without use. Nothing
here logs document text, file names or session ids.

Other features (the quiz) use `store.get_ready(id)` and hold `session.lock` while they use
`session.rag`, because the answer engines keep per-question state.
"""
import logging
import secrets
import shutil
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from .errors import ApiError, not_found

log = logging.getLogger("dockbrain.server")

DEFAULT_TTL_SECONDS = 30 * 60


class Session:
    def __init__(self, kind: str, display_name: str, directory: Path | None):
        self.id = "s_" + secrets.token_urlsafe(12)
        self.kind = kind
        self.display_name = display_name
        self.status = "processing"  # then "ready" or "failed"
        self.error: dict | None = None
        self.rag = None
        self.lock = threading.Lock()  # hold while using self.rag
        self.data: dict = {}  # per-feature state, e.g. data["quizzes"]; dropped with the session
        self.directory = directory  # the upload's directory, until indexing ends
        self.deleted = False
        self.last_used = time.monotonic()

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def resource(self) -> dict:
        """The session resource of the API contract."""
        processing = self.status == "processing"
        body = {
            "id": self.id,
            "kind": self.kind,
            "displayName": self.display_name,
            "status": self.status,
            "stage": "reading" if processing else "ready" if self.status == "ready" else None,
            "progress": None,
            "message": f"Reading and indexing {self.display_name}…" if processing else None,
            "sectionCount": len(self.rag.chunks) if self.rag is not None else None,
            "notice": None,
        }
        if self.error:
            body["error"] = self.error
        return body


class SessionStore:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, workers: int = 2):
        self.ttl_seconds = ttl_seconds
        self.root = Path(tempfile.mkdtemp(prefix="dockbrain-uploads-"))
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dockbrain-index")
        self._jobs: set[Future] = set()
        self._closed = threading.Event()
        self._sweeper = threading.Thread(target=self._sweep_regularly, name="dockbrain-expiry", daemon=True)
        self._sweeper.start()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------ creating

    def new_directory(self) -> Path:
        """A private directory for one upload."""
        return Path(tempfile.mkdtemp(dir=self.root))

    def start(self, kind: str, display_name: str, directory: Path, build: Callable[[], object]) -> Session:
        """Register a processing session and index it in the background. `build` returns
        the session's `rag.RAG`, or raises ApiError (or any error) if it can't be read."""
        session = Session(kind, display_name, directory)
        with self._lock:
            self._sessions[session.id] = session
            future = self._executor.submit(self._index, session, build)
            self._jobs.add(future)
        future.add_done_callback(self._jobs.discard)
        return session

    def _index(self, session: Session, build: Callable[[], object]) -> None:
        rag, error = None, None
        try:
            rag = build()
        except ApiError as e:
            error = {"code": e.code, "message": e.message}
        except Exception as e:  # a damaged file can fail in many ways; never show internals
            log.warning("indexing failed: %s", type(e).__name__)
            error = {"code": "unreadable", "message": f"{session.display_name} couldn't be read. It may be damaged."}
        finally:
            self._remove_directory(session)  # the index holds what's needed; the file can go
        with self._lock:
            if session.deleted:  # deleted while processing: drop the result
                return
            session.rag = rag
            session.error = error
            session.status = "failed" if error else "ready"

    # ------------------------------------------------------------------ using

    def get(self, session_id: str) -> Session:
        """The session, whatever its status; 404 if unknown, deleted or expired."""
        self.sweep()
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise not_found()
        session.touch()
        return session

    def get_ready(self, session_id: str) -> Session:
        """A session whose document is indexed: 404 if unknown, 409 while processing, and
        the indexing error if it failed."""
        session = self.get(session_id)
        if session.status == "processing":
            raise ApiError(409, "not_ready", "The document is still being read. Try again in a moment.", retryable=True)
        if session.status == "failed":
            error = session.error or {}
            raise ApiError(422, error.get("code", "unreadable"), error.get("message", "This document couldn't be read."))
        return session

    # ------------------------------------------------------------------ ending

    def delete(self, session_id: str) -> None:
        """End a session and delete its data. Unknown ids are fine: deleting is idempotent.
        A session still processing is dropped when its job ends."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                return
            session.deleted = True
        self._forget(session)

    def sweep(self) -> None:
        """Delete sessions unused for longer than the time limit, processing or not, so
        abandoned uploads don't linger."""
        cutoff = time.monotonic() - self.ttl_seconds
        with self._lock:
            expired = [s for s in self._sessions.values() if s.last_used < cutoff]
            for session in expired:
                del self._sessions[session.id]
                session.deleted = True
        for session in expired:
            self._forget(session)
        if expired:
            log.info("expired %d idle session(s)", len(expired))

    def _sweep_regularly(self) -> None:
        interval = min(max(self.ttl_seconds / 2, 0.05), 60)
        while not self._closed.wait(interval):
            self.sweep()

    def _forget(self, session: Session) -> None:
        self._remove_directory(session)
        with session.lock:  # wait for any feature still using it
            session.rag = None
            session.data.clear()

    @staticmethod
    def _remove_directory(session: Session) -> None:
        directory, session.directory = session.directory, None
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)

    def wait_for_jobs(self, timeout: float | None = None) -> None:
        """Wait for background indexing to finish (used by tests and shutdown)."""
        with self._lock:
            jobs = set(self._jobs)
        wait(jobs, timeout=timeout)

    def close(self) -> None:
        """Stop indexing, delete every session and every upload."""
        self._closed.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.deleted = True
            self._forget(session)
        shutil.rmtree(self.root, ignore_errors=True)
