"""Structured API errors, as FRONTEND/API_CONTRACT.md defines them.

Every non-2xx response carries `{"error": {"code", "message", "retryable"}}`. Messages are
shown to people as they are, so they never contain document text, questions, answers,
server paths or provider keys.
"""
import re


class ApiError(Exception):
    """An error to send to the client: HTTP status, contract code, and a message to show."""

    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


def json_body(request):
    """The request's JSON body (see `server.app.Request.json`)."""
    return request.json()


def invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)


def not_found(message: str = "This session has ended. Choose your file again to continue.") -> ApiError:
    return ApiError(404, "not_found", message)


# The answer engines word their errors for the command line; a browser has no --offline flag.
_CLI_ADVICE = re.compile(r",?\s*(?:or\s+)?run with --offline", re.IGNORECASE)


def for_browser(message: str) -> str:
    text = _CLI_ADVICE.sub("", message).strip()
    return re.sub(r"\s+\.", ".", text)


def provider_error(error: Exception) -> ApiError:
    """Turn an answer engine's RuntimeError (rag.generator) into the contract's error.
    Its messages name the provider's reason and never include document text."""
    message = for_browser(str(error)) or "The answer service couldn't answer. Try again shortly."
    lower = message.lower()
    if "daily" in lower and "limit" in lower:  # waiting a minute won't help
        return ApiError(429, "rate_limited", message, retryable=False)
    if "usage limit" in lower or "rate limit" in lower:
        return ApiError(429, "rate_limited", message, retryable=True)
    if "api key" in lower or "no model named" in lower:  # the server's settings need fixing
        return ApiError(503, "unavailable", message, retryable=False)
    return ApiError(503, "unavailable", message, retryable=True)
