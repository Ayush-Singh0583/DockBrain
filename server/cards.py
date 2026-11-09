"""Routes for Memory cards (FRONTEND/API_CONTRACT.md, "Memory cards").

A card set shows only each card's front. A card's answer, source sentence and citation
come from a separate request when the learner reveals that card, so answers never reach
the browser early. Sets are written by the session's model if it has one (rag/cards.py),
kept on the session, and dropped with it. "Know it" / "Review again" marks stay in the
browser.
"""
import secrets
from pathlib import PurePath

from rag.cards import DEFAULT_CARDS, MAX_CARDS, build_cards
from rag.quiz import InsufficientContent, writer_for

from .documents import citation
from .errors import ApiError, for_browser, invalid, not_found

KEEP_SETS = 5  # per session; older sets are dropped when a new one is made


def _sets(session) -> dict:
    return session.data.setdefault("cardSets", {})


def _front(card_set) -> dict:
    return {
        "id": card_set.id,
        "title": card_set.title,
        "cards": [{"id": c.id, "kind": c.kind, "prompt": c.prompt} for c in card_set.cards],
        "notice": for_browser(card_set.notice) if card_set.notice else None,
        "demo": False,
    }


def create_cards(request):
    """POST /sessions/{session_id}/cards  {"count": 1–20, default 10}: a new card set."""
    body = request.json() if request.headers.get("Content-Length", "0") not in ("", "0") else {}
    if not isinstance(body, dict):
        raise invalid("Send the request as a JSON object, e.g. {\"count\": 10}.")
    count = body.get("count", DEFAULT_CARDS)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_CARDS:
        raise invalid(f"\"count\" must be a whole number from 1 to {MAX_CARDS}.")
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        if session.rag is None:  # deleted or expired while waiting for the lock
            raise not_found()
        title = PurePath(session.display_name).stem or session.display_name
        try:
            card_set = build_cards(session.rag.chunks, count, title=title, set_id="cs_" + secrets.token_urlsafe(9),
                                   writer=writer_for(session.rag.generator))
        except InsufficientContent as e:
            raise ApiError(422, "insufficient_content", str(e)) from None
        sets = _sets(session)
        sets[card_set.id] = card_set
        while len(sets) > KEEP_SETS:
            sets.pop(next(iter(sets)))
    return 201, _front(card_set)


def _card_set(request, session):
    card_set = _sets(session).get(request.params["set_id"])
    if card_set is None:
        raise not_found("That card set isn't in this session. Make a new set.")
    return card_set


def get_cards(request):
    """GET /sessions/{session_id}/cards/{set_id}: the set again, fronts only."""
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        result = _front(_card_set(request, session))
    return 200, result


def reveal_card(request):
    """GET /sessions/{session_id}/cards/{set_id}/answers/{card_id}: one card's back."""
    session = request.store.get_ready(request.params["session_id"])
    with session.lock:
        card_set = _card_set(request, session)
        card = next((c for c in card_set.cards if c.id == request.params["card_id"]), None)
        if card is None:
            raise not_found("That card isn't in this set.")
        source = citation(1, card.passage, 1.0)
        source.pop("score")  # a card's passage was chosen, not ranked
        result = {"cardId": card.id, "answer": card.answer, "quote": card.quote, "citation": source}
    return 200, result


ROUTES = [
    ("POST", "/sessions/{session_id}/cards", create_cards),
    ("GET", "/sessions/{session_id}/cards/{set_id}", get_cards),
    ("GET", "/sessions/{session_id}/cards/{set_id}/answers/{card_id}", reveal_card),
]
