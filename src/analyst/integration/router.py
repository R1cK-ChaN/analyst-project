from __future__ import annotations

import re
from typing import Protocol

from analyst.contracts import (
    CalendarItem,
    ChannelMessage,
    DraftResponse,
    InteractionMode,
    ResearchNote,
)
from analyst.engine import AnalystEngine


PATTERNS = {
    InteractionMode.DRAFT: re.compile(r"(帮我写|帮我准备一段|起草|草拟|帮我发|写一段)"),
    InteractionMode.MEETING_PREP: re.compile(r"(准备要点|沟通要点|会议准备|客户沟通|帮我准备.*会|怎么跟客户说)"),
    InteractionMode.REGIME: re.compile(r"(宏观状态|体系状态|regime|风险偏好|现在宏观|整体怎么看)"),
    InteractionMode.CALENDAR: re.compile(r"(今天有什么|日历|数据发布|今天数据|本周数据|接下来有什么)"),
}


def detect_mode(message: str) -> InteractionMode:
    for mode, pattern in PATTERNS.items():
        if pattern.search(message):
            return mode
    return InteractionMode.QA


class ChannelFormatter(Protocol):
    def format_draft(self, response: DraftResponse) -> ChannelMessage: ...
    def format_research_note(self, note: ResearchNote, mode: InteractionMode) -> ChannelMessage: ...
    def format_calendar(self, items: list[CalendarItem]) -> ChannelMessage: ...


class AnalystIntegrationService:
    def __init__(self, engine: AnalystEngine, formatter: ChannelFormatter | None = None) -> None:
        self.engine = engine
        if formatter is None:
            from analyst.delivery import WeComFormatter
            formatter = WeComFormatter()
        self.formatter = formatter

    def handle_message(
        self,
        message: str,
        user_id: str,
        focus: str = "global",
    ) -> ChannelMessage:
        mode = detect_mode(message)
        if mode == InteractionMode.DRAFT:
            response = self.engine.generate_draft(message, user_id=user_id, focus=focus)
            return self.formatter.format_draft(response)
        if mode == InteractionMode.MEETING_PREP:
            response = self.engine.generate_meeting_prep(message, user_id=user_id, focus=focus)
            return self.formatter.format_draft(response)
        if mode == InteractionMode.REGIME:
            note = self.engine.get_regime_summary(focus=focus)
            return self.formatter.format_research_note(note, mode=InteractionMode.REGIME)
        if mode == InteractionMode.CALENDAR:
            return self.formatter.format_calendar(self.engine.get_calendar(limit=5))
        response = self.engine.answer_question(message, user_id=user_id, focus=focus)
        return self.formatter.format_draft(response)

    def handle_wecom_message(
        self,
        message: str,
        user_id: str,
        focus: str = "global",
    ) -> ChannelMessage:
        return self.handle_message(message, user_id=user_id, focus=focus)
