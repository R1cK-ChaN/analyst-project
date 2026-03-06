from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyst.contracts import ChannelMessage, InteractionMode, ResearchNote
from analyst.delivery import WeComFormatter
from analyst.engine import AnalystEngine
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.integration import AnalystIntegrationService
from analyst.runtime import TemplateAgentRuntime


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


def build_demo_app(data_dir: Path | None = None) -> AnalystApplication:
    repository = FileBackedInformationRepository(data_dir=data_dir)
    info_service = AnalystInformationService(repository)
    runtime = TemplateAgentRuntime()
    engine = AnalystEngine(info_service=info_service, runtime=runtime)
    formatter = WeComFormatter()
    integration = AnalystIntegrationService(engine=engine, formatter=formatter)
    return AnalystApplication(engine=engine, formatter=formatter, integration=integration)
