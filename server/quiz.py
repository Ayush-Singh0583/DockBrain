"""HTTP routes for "Quiz yourself": make a quiz from a session's document, fetch it again,
grade submitted answers, and delete it.

`server/app.py` (owned by the learn-from-document session) adds `ROUTES`. Each handler
takes a `Request` (`.params`, `.store`, `.json()`, `.query`) and returns
`(status, payload)`. Generation and grading live in `rag/quiz.py`; this module only
validates requests, keeps quizzes on the session, and shapes responses as described in
FRONTEND/API_CONTRACT.md. Nothing here logs; responses never include provider keys.
"""
from __future__ import annotations

import secrets
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass

from rag.chunker import Chunk
from rag.quiz import MAX_QUESTIONS, InsufficientContent, Quiz, QuizQuestion, build_quiz, grade, writer_for

from .errors import ApiError, for_browser, invalid

DEFAULT_QUESTIONS = 5
MAX_QUIZZES_PER_SESSION = 20  # the oldest is dropped beyond this
MAX_ANSWERS = 50
MAX_ID_LENGTH = 40


@dataclass
class _Stored:
    quiz: Quiz
    reveal: bool  # whether answers are included before grading


def _quizzes(session) -> OrderedDict:
    return session.data.setdefault("quizzes", OrderedDict())


@contextmanager
def _locked_session(request):
    """The request's ready session, held under its lock. 404 if it ended while we waited."""
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        if getattr(session, "deleted", False):
            raise ApiError(404, "not_found", "This session has ended. Choose your file again to continue.")
        session.touch()
        yield session


def _stored(session, quiz_id: str) -> _Stored:
    stored = _quizzes(session).get(quiz_id)
    if stored is None:
        raise ApiError(404, "not_found", "This quiz doesn't exist, or it was deleted.")
    return stored


# ------------------------------------------------------------------- response shapes

def citation(chunk: Chunk) -> dict:
    """The passage a question is based on, as a contract `Citation` (index 1 within its question)."""
    cited = {"index": 1, "excerpt": chunk.text, "passageId": chunk.id}
    section = next((s.section for s in chunk.sentences if s.section), "")
    if section:
        cited["section"] = section
    return cited


def question_payload(q: QuizQuestion, reveal: bool) -> dict:
    payload = {"id": q.id, "prompt": q.prompt, "options": [{"id": o.id, "text": o.text} for o in q.options]}
    if reveal:
        payload.update(correctOptionId=q.correct_option_id, explanation=q.explanation,
                       citation=citation(q.passage), quote=q.quote)
    return payload


def quiz_payload(stored: _Stored) -> dict:
    quiz = stored.quiz
    payload = {
        "id": quiz.id,
        "title": quiz.title,
        "demo": False,
        "engine": quiz.engine,
        "answersRevealed": stored.reveal,
        "questions": [question_payload(q, stored.reveal) for q in quiz.questions],
    }
    if quiz.notice:
        payload["notice"] = for_browser(quiz.notice)  # provider messages carry command-line advice
    return payload


# -------------------------------------------------------------------------- routes

def create_quiz(request):
    body = request.json()
    if not isinstance(body, dict):
        raise invalid("Send a JSON object, such as {\"count\": 5}.")
    count = body.get("count", DEFAULT_QUESTIONS)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_QUESTIONS:
        raise invalid(f"\"count\" must be a whole number from 1 to {MAX_QUESTIONS}.")
    reveal = body.get("revealAnswers", True)
    if not isinstance(reveal, bool):
        raise invalid("\"revealAnswers\" must be true or false.")

    with _locked_session(request) as session:
        name = getattr(session, "display_name", None) or "your document"
        try:
            quiz = build_quiz(
                session.rag.chunks,
                count,
                title=f"Quiz: {name}",
                writer=writer_for(session.rag.generator),
                quiz_id="qz_" + secrets.token_urlsafe(9),
                seed=secrets.randbits(64),
            )
        except InsufficientContent as e:
            raise ApiError(422, "insufficient_content", str(e)) from None
        quizzes = _quizzes(session)
        stored = quizzes[quiz.id] = _Stored(quiz, reveal)
        while len(quizzes) > MAX_QUIZZES_PER_SESSION:
            quizzes.popitem(last=False)
        return 200, quiz_payload(stored)


def get_quiz(request):
    with _locked_session(request) as session:
        return 200, quiz_payload(_stored(session, request.params["quiz_id"]))


def _answers(body) -> list[tuple[str, str]]:
    if not isinstance(body, dict) or not isinstance(body.get("answers"), list):
        raise invalid("Send {\"answers\": [{\"questionId\": \"q1\", \"optionId\": \"a\"}, …]}.")
    answers = body["answers"]
    if len(answers) > MAX_ANSWERS:
        raise invalid(f"Send at most {MAX_ANSWERS} answers.")
    pairs = []
    for answer in answers:
        question_id = answer.get("questionId") if isinstance(answer, dict) else None
        option_id = answer.get("optionId") if isinstance(answer, dict) else None
        if not all(isinstance(v, str) and 0 < len(v) <= MAX_ID_LENGTH for v in (question_id, option_id)):
            raise invalid("Each answer needs a \"questionId\" and an \"optionId\".")
        pairs.append((question_id, option_id))
    return pairs


def submit_answers(request):
    pairs = _answers(request.json())
    with _locked_session(request) as session:
        quiz = _stored(session, request.params["quiz_id"]).quiz
        try:
            result = grade(quiz, pairs)
        except ValueError as e:
            raise invalid(str(e)) from None
        return 200, {
            "quizId": quiz.id,
            "score": {"correct": result.correct, "total": result.total},
            "results": [
                {
                    "questionId": r.question.id,
                    "selectedOptionId": r.selected,
                    "correctOptionId": r.question.correct_option_id,
                    "correct": r.correct,
                    "explanation": r.question.explanation,
                    "quote": r.question.quote,
                    "citation": citation(r.question.passage),
                }
                for r in result.results
            ],
        }


def delete_quiz(request):
    with _locked_session(request) as session:
        if _quizzes(session).pop(request.params["quiz_id"], None) is None:
            raise ApiError(404, "not_found", "This quiz doesn't exist, or it was already deleted.")
        return 204, None


ROUTES = [
    ("POST", "/sessions/{session_id}/quizzes", create_quiz),
    ("GET", "/sessions/{session_id}/quizzes/{quiz_id}", get_quiz),
    ("POST", "/sessions/{session_id}/quizzes/{quiz_id}/answers", submit_answers),
    ("DELETE", "/sessions/{session_id}/quizzes/{quiz_id}", delete_quiz),
]
