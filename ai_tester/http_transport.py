import json
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ResponseTooLarge(ValueError):
    """Raised when an HTTP response exceeds its configured byte limit."""


class InvalidJsonResponse(ValueError):
    """Raised when an HTTP response does not contain valid JSON."""


class UnexpectedJsonStructure(InvalidJsonResponse):
    """Raised when a JSON response is not an object."""


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_without_redirects(request: Request, *, timeout: float):
    return build_opener(NoRedirectHandler()).open(request, timeout=timeout)


def _content_length(response):
    getheader = getattr(response, "getheader", None)
    value = getheader("Content-Length") if getheader is not None else None
    if value is None:
        value = getattr(response, "headers", {}).get("Content-Length")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def read_bounded_json_object(response, *, max_bytes: int) -> dict:
    declared_length = _content_length(response)
    if declared_length is not None and declared_length > max_bytes:
        raise ResponseTooLarge

    raw_body = response.read(max_bytes + 1)
    if len(raw_body) > max_bytes:
        raise ResponseTooLarge

    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise InvalidJsonResponse from exc
    if not isinstance(body, dict):
        raise UnexpectedJsonStructure
    return body
