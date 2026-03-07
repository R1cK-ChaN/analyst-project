"""Telegram-specific formatter.

Converts engine output (DraftResponse, ResearchNote, CalendarItem list)
into ChannelMessage objects with channel="telegram" and Telegram-friendly
Markdown (MarkdownV2 is too fragile; we use plain Markdown parse_mode).
"""

from __future__ import annotations

from analyst.contracts import (
    CalendarItem,
    ChannelMessage,
    DraftResponse,
    InteractionMode,
    ResearchNote,
)

DISCLAIMERS: dict[InteractionMode, str] = {
    InteractionMode.QA: "内部研究辅助内容，请结合最新数据和合规要求复核。",
    InteractionMode.DRAFT: "客户外发前请人工编辑并完成合规复核。",
    InteractionMode.MEETING_PREP: "仅供会前准备，正式口径请结合团队统一表述。",
    InteractionMode.REGIME: "宏观状态为研究框架，不构成投资建议。",
    InteractionMode.CALENDAR: "日历信息仅供提醒，实际发布时间以官方披露为准。",
    InteractionMode.PREMARKET: "宏观状态为研究框架，不构成投资建议。",
}

MAX_TELEGRAM_MESSAGE_LENGTH = 4096


def _truncate(text: str, limit: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 4] + "\n..."


class TelegramFormatter:
    """Format engine output for Telegram delivery."""

    def format_draft(self, response: DraftResponse) -> ChannelMessage:
        disclaimer = DISCLAIMERS.get(response.mode, DISCLAIMERS[InteractionMode.QA])
        markdown = f"{response.markdown}\n\n*合规提示*\n{disclaimer}"
        plain_text = f"{response.plain_text}\n\n合规提示: {disclaimer}"
        return ChannelMessage(
            message_id=response.request_id,
            channel="telegram",
            mode=response.mode,
            markdown=_truncate(markdown),
            plain_text=_truncate(plain_text),
            citations=response.citations,
            metadata=response.metadata,
        )

    def format_research_note(
        self,
        note: ResearchNote,
        mode: InteractionMode = InteractionMode.REGIME,
    ) -> ChannelMessage:
        disclaimer = DISCLAIMERS.get(mode, DISCLAIMERS[InteractionMode.REGIME])
        markdown = f"*{note.title}*\n\n{note.body_markdown}\n\n*合规提示*\n{disclaimer}"
        plain_text = f"{note.title}\n\n{note.summary}\n\n合规提示: {disclaimer}"
        return ChannelMessage(
            message_id=note.note_id,
            channel="telegram",
            mode=mode,
            markdown=_truncate(markdown),
            plain_text=_truncate(plain_text),
            citations=note.citations,
            metadata={"note_type": note.note_type},
        )

    def format_calendar(self, items: list[CalendarItem]) -> ChannelMessage:
        lines = [
            f"- {item.indicator} | {item.country} | 预期 {item.expected or '待定'} | {item.notes}"
            for item in items
        ]
        disclaimer = DISCLAIMERS[InteractionMode.CALENDAR]
        markdown = (
            "*今日/近期数据日历*\n\n"
            + "\n".join(lines)
            + f"\n\n*合规提示*\n{disclaimer}"
        )
        plain_text = "近期数据日历\n" + "\n".join(lines)
        citations = [ref for item in items for ref in item.references]
        return ChannelMessage(
            message_id="calendar-reply",
            channel="telegram",
            mode=InteractionMode.CALENDAR,
            markdown=_truncate(markdown),
            plain_text=_truncate(plain_text),
            citations=citations,
            metadata={"items": str(len(items))},
        )
