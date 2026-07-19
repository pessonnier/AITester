import json

import pytest

from ai_tester.http_transport import (
    InvalidJsonResponse,
    ResponseTooLarge,
    UnexpectedJsonStructure,
    read_bounded_json_object,
)


class Response:
    def __init__(self, body, *, content_length=None, header_style="headers"):
        self.body = body
        self.requested_size = None
        self.headers = {}
        if header_style == "headers" and content_length is not None:
            self.headers["Content-Length"] = content_length
        self._content_length = content_length if header_style == "getheader" else None

    def getheader(self, name):
        return self._content_length if name == "Content-Length" else None

    def read(self, size=-1):
        self.requested_size = size
        return self.body[:size]


@pytest.mark.parametrize("header_style", ["headers", "getheader"])
def test_read_bounded_json_object_supports_standard_response_headers(header_style):
    response = Response(
        json.dumps({"status": "ok"}).encode(),
        content_length="16",
        header_style=header_style,
    )

    assert read_bounded_json_object(response, max_bytes=64) == {"status": "ok"}
    assert response.requested_size == 65


def test_read_bounded_json_object_rejects_declared_and_actual_oversize():
    with pytest.raises(ResponseTooLarge):
        read_bounded_json_object(Response(b"{}", content_length="65"), max_bytes=64)

    with pytest.raises(ResponseTooLarge):
        read_bounded_json_object(Response(b"x" * 65), max_bytes=64)


def test_read_bounded_json_object_rejects_malformed_json():
    with pytest.raises(InvalidJsonResponse) as error:
        read_bounded_json_object(Response(b"not-json"), max_bytes=64)

    assert type(error.value) is InvalidJsonResponse


def test_read_bounded_json_object_rejects_a_non_object_structure():
    with pytest.raises(UnexpectedJsonStructure) as error:
        read_bounded_json_object(Response(b"[]"), max_bytes=64)

    assert type(error.value) is UnexpectedJsonStructure
