from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyst.contracts import ChannelMessage, InteractionMode, RegimeState, ResearchNote
from analyst.storage.sqlite import StoredEventRecord
from analyst.delivery import WeComFormatter
from analyst.engine import AnalystEngine, LiveAnalystEngine
from analyst.engine.live_types import LLMProvider
from analyst.ingestion import IngestionOrchestrator
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.integration import AnalystIntegrationService
from analyst.runtime import TemplateAgentRuntime
from analyst.storage import SQLiteEngineStore


@dataclass
class AnalystApplication:
    engine: AnalystEngine
    formatter: WeComFormatter
    integration: AnalystIntegrationService

    def ask(self, question: str, user_id: str = "demo", focus: str = "global") -> ChannelMessage:
        return self.formatter.format_draft(self.engine.answer_question(question, user_id=user_id, focus=focus))

    def draft(self, request: str, user_id: str = "demo", focus: str = "global") -> ChannelMessage:
        return self.formatter.format_draft(self.engine.generate_draft(request, user_id=user_id, focus=focus))

    def meeting_prep(self, request: str, user_id: str = "demo", focus: str = "global") -> ChannelMessage:
        response = self.engine.generate_meeting_prep(request, user_id=user_id, focus=focus)
        return self.formatter.format_draft(response)

    def regime(self, focus: str = "global") -> ChannelMessage:
        note = self.engine.get_regime_summary(focus=focus)
        return self.formatter.format_research_note(note, mode=InteractionMode.REGIME)

    def calendar(self, limit: int = 5) -> ChannelMessage:
        return self.formatter.format_calendar(self.engine.get_calendar(limit=limit))

    def premarket(self, focus: str = "global") -> ResearchNote:
        return self.engine.build_premarket_briefing(focus=focus)

    def route(self, message: str, user_id: str = "demo", focus: str = "global") -> ChannelMessage:
        return self.integration.handle_wecom_message(message, user_id=user_id, focus=focus)


@dataclass
class LiveAnalystApplication:
    engine: LiveAnalystEngine

    def refresh(self) -> dict[str, int]:
        return self.engine.refresh_all_sources()

    def schedule(self) -> None:
        self.engine.run_schedule()

    def flash(self, indicator_keyword: str | None = None) -> ResearchNote:
        return self.engine.generate_flash_commentary(indicator_keyword=indicator_keyword)

    def briefing(self) -> ResearchNote:
        return self.engine.generate_morning_briefing()

    def wrap(self) -> ResearchNote:
        return self.engine.generate_after_market_wrap()

    def regime_refresh(self) -> RegimeState:
        return self.engine.refresh_regime()

    def live_calendar(
        self,
        *,
        scope: str = "today",
        country: str | None = None,
        category: str | None = None,
        importance: str | None = None,
        limit: int = 20,
    ) -> list[StoredEventRecord]:
        store = self.engine.store
        if scope == "today":
            return store.list_today_events(
                limit=limit, importance=importance, country=country, category=category,
            )
        if scope == "upcoming":
            return store.list_upcoming_events(
                limit=limit, importance=importance, country=country, category=category,
            )
        if scope == "recent":
            return store.list_recent_events(
                limit=limit, days=7, released_only=True,
                importance=importance, country=country, category=category,
            )
        if scope == "week":
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone.utc).date()
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            date_from = int(datetime(start_of_week.year, start_of_week.month, start_of_week.day, tzinfo=timezone.utc).timestamp())
            date_to = int(datetime(end_of_week.year, end_of_week.month, end_of_week.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
            return store.list_events_in_range(
                date_from=date_from, date_to=date_to, limit=limit,
                importance=importance, country=country, category=category,
            )
        return store.list_today_events(limit=limit)


def build_demo_app(data_dir: Path | None = None) -> AnalystApplication:
    repository = FileBackedInformationRepository(data_dir=data_dir)
    info_service = AnalystInformationService(repository)
    runtime = TemplateAgentRuntime()
    engine = AnalystEngine(info_service=info_service, runtime=runtime)
    formatter = WeComFormatter()
    integration = AnalystIntegrationService(engine=engine, formatter=formatter)
    return AnalystApplication(engine=engine, formatter=formatter, integration=integration)


def build_live_engine_app(
    db_path: Path | None = None,
    provider: LLMProvider | None = None,
) -> LiveAnalystApplication:
    store = SQLiteEngineStore(db_path=db_path)
    ingestion = IngestionOrchestrator(store)

    # Graceful RAG init — if Milvus unavailable, engine works without it.
    retriever = None
    try:
        from analyst.rag import MacroRetriever

        retriever = MacroRetriever.from_env()
    except Exception:
        pass

    engine = LiveAnalystEngine(
        store=store, provider=provider, ingestion=ingestion, retriever=retriever
    )
    return LiveAnalystApplication(engine=engine)
