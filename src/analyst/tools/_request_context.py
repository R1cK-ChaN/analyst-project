from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class RequestImageInput:
    data_uri: str
    mime_type: str
    filename: str = ""
    source: str = "message"


_REQUEST_IMAGE: ContextVar[RequestImageInput | None] = ContextVar(
    "analyst_request_image",
    default=None,
)


@contextmanager
def bind_request_image(image: RequestImageInput | None) -> Iterator[None]:
    token = _REQUEST_IMAGE.set(image)
    try:
        yield
    finally:
        _REQUEST_IMAGE.reset(token)


def get_request_image() -> RequestImageInput | None:
    return _REQUEST_IMAGE.get()
