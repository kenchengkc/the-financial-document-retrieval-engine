import pytest
from pydantic import ValidationError

from apps.api.app.schemas.answer import AnswerRequest
from apps.api.app.schemas.search import SearchRequest

MAX_REQUEST_TEXT_LENGTH = 4096


@pytest.mark.parametrize(
    ("request_type", "field_name"),
    [
        (AnswerRequest, "question"),
        (SearchRequest, "query"),
    ],
)
def test_public_request_text_accepts_configured_maximum(
    request_type: type[AnswerRequest] | type[SearchRequest],
    field_name: str,
) -> None:
    payload = {field_name: "x" * MAX_REQUEST_TEXT_LENGTH}

    request_type.model_validate(payload)


@pytest.mark.parametrize(
    ("request_type", "field_name"),
    [
        (AnswerRequest, "question"),
        (SearchRequest, "query"),
    ],
)
def test_public_request_text_rejects_oversized_input(
    request_type: type[AnswerRequest] | type[SearchRequest],
    field_name: str,
) -> None:
    payload = {field_name: "x" * (MAX_REQUEST_TEXT_LENGTH + 1)}

    with pytest.raises(ValidationError):
        request_type.model_validate(payload)
