from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from analyst.contracts import CalendarItem, Event, Importance, SourceReference


def default_data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "demo"


@dataclass(frozen=True)
class DocumentSnippet:
    topic: str
    bullet: str
    reference: SourceReference


class InformationRepository(Protocol):
    def recent_events(self, limit: int = 8) -> list[Event]:
        ...

    def upcoming_calendar(self, limit: int = 5) -> list[CalendarItem]:
        ...

    def market_prices(self) -> dict[str, float]:
        ...

    def search_documents(self, query: str, limit: int = 3) -> list[DocumentSnippet]:
        ...


class FileBackedInformationRepository:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self._events = [self._parse_event(item) for item in self._read_json("events.json")]
        self._calendar = [self._parse_calendar(item) for item in self._read_json("calendar.json")]
        self._documents = [self._parse_document(item) for item in self._read_json("documents.json")]
        self._market_prices = self._read_json("market_prices.json")

    def recent_events(self, limit: int = 8) -> list[Event]:
        return self._events[:limit]

    def upcoming_calendar(self, limit: int = 5) -> list[CalendarItem]:
        return self._calendar[:limit]

    def market_prices(self) -> dict[str, float]:
        return dict(self._market_prices)

    def search_documents(self, query: str, limit: int = 3) -> list[DocumentSnippet]:
        query_lower = query.lower()
        ranked = [
            snippet
            for snippet in self._documents
            if any(token in query_lower for token in snippet.topic.split())
        ]
        if not ranked:
            ranked = self._documents
        return ranked[:limit]

    def _read_json(self, filename: str):
        path = self.data_dir / filename
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _parse_event(self, item: dict) -> Event:
        return Event(
            event_id=item["event_id"],
            timestamp=datetime.fromisoformat(item["timestamp"]),
            source=item["source"],
            source_type=item["source_type"],
            category=item["category"],
            title=item["title"],
            summary=item["summary"],
            country=item["country"],
            importance=Importance(item.get("importance", "medium")),
            actual=item.get("actual"),
            forecast=item.get("forecast"),
            previous=item.get("previous"),
            surprise=item.get("surprise"),
            tags=item.get("tags", []),
            references=[self._parse_reference(ref) for ref in item.get("references", [])],
        )

    def _parse_calendar(self, item: dict) -> CalendarItem:
        return CalendarItem(
            event_id=item["event_id"],
            release_time=datetime.fromisoformat(item["release_time"]),
            indicator=item["indicator"],
            country=item["country"],
            importance=Importance(item.get("importance", "medium")),
            expected=item.get("expected"),
            previous=item.get("previous"),
            notes=item.get("notes", ""),
            references=[self._parse_reference(ref) for ref in item.get("references", [])],
        )

    def _parse_document(self, item: dict) -> DocumentSnippet:
        return DocumentSnippet(
            topic=item["topic"],
            bullet=item["bullet"],
            reference=self._parse_reference(item["reference"]),
        )

    def _parse_reference(self, item: dict) -> SourceReference:
        return SourceReference(
            title=item["title"],
            url=item["url"],
            source=item["source"],
            excerpt=item.get("excerpt", ""),
        )
