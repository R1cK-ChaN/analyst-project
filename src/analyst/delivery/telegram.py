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
    InteractionMode.FOLLOW_UP: "客户外发前请人工编辑并完成合规复核。",
    InteractionMode.MEETING_PREP: "仅供会前准备，正式口径请结合团队统一表述。",
    InteractionMode.REGIME: "宏观状态为研究框架，不构成投资建议。",
    InteractionMode.CALENDAR: "日历信息仅供提醒，实际发布时间以官方披露为准。",
    InteractionMode.PREMARKET: "宏观状态为研究框架，不构成投资建议。",
}

MAX_TELEGRAM_MESSAGE_LENGTH = 4096


def _strip_markdown(text: str) -> str:
    """Remove lightweight markdown markers for plain-text output."""
    return text.replace("#", "").replace("*", "").replace("`", "").strip()


def _truncate_body(body: str, suffix: str, limit: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> str:
    """Truncate *body* so that body + suffix fits within *limit*.

    The suffix (compliance disclaimer) is never truncated.
    """
    available = limit - len(suffix)
    if available < 0:
        return suffix[:limit]
    if len(body) <= available:
        return body + suffix
    return body[: available - 4] + "\n..." + suffix


class TelegramFormatter:
    """Format engine output for Telegram delivery."""

    def format_draft(self, response: DraftResponse) -> ChannelMessage:
        disclaimer = DISCLAIMERS.get(response.mode, DISCLAIMERS[InteractionMode.QA])
        md_suffix = f"\n\n*合规提示*\n{disclaimer}"
        pt_suffix = f"\n\n合规提示: {disclaimer}"
        markdown = _truncate_body(response.markdown, md_suffix)
        plain_text = _truncate_body(response.plain_text, pt_suffix)
        return ChannelMessage(
            message_id=response.request_id,
            channel="telegram",
            mode=response.mode,
            markdown=markdown,
            plain_text=plain_text,
            citations=response.citations,
            metadata=response.metadata,
        )

    def format_research_note(
        self,
        note: ResearchNote,
        mode: InteractionMode = InteractionMode.REGIME,
    ) -> ChannelMessage:
        disclaimer = DISCLAIMERS.get(mode, DISCLAIMERS[InteractionMode.REGIME])
        md_suffix = f"\n\n*合规提示*\n{disclaimer}"
        pt_suffix = f"\n\n合规提示: {disclaimer}"
        md_body = f"*{note.title}*\n\n{note.body_markdown}"
        pt_body = f"{note.title}\n\n{_strip_markdown(note.body_markdown)}"
        markdown = _truncate_body(md_body, md_suffix)
        plain_text = _truncate_body(pt_body, pt_suffix)
        return ChannelMessage(
            message_id=note.note_id,
            channel="telegram",
            mode=mode,
            markdown=markdown,
            plain_text=plain_text,
            citations=note.citations,
            metadata={"note_type": note.note_type},
        )

    def format_calendar(self, items: list[CalendarItem]) -> ChannelMessage:
        lines = [
            f"- {item.indicator} | {item.country} | 预期 {item.expected or '待定'} | {item.notes}"
            for item in items
        ]
        disclaimer = DISCLAIMERS[InteractionMode.CALENDAR]
        md_suffix = f"\n\n*合规提示*\n{disclaimer}"
        pt_suffix = f"\n\n合规提示: {disclaimer}"
        md_body = "*今日/近期数据日历*\n\n" + "\n".join(lines)
        pt_body = "近期数据日历\n" + "\n".join(lines)
        markdown = _truncate_body(md_body, md_suffix)
        plain_text = _truncate_body(pt_body, pt_suffix)
        citations = [ref for item in items for ref in item.references]
        return ChannelMessage(
            message_id="calendar-reply",
            channel="telegram",
            mode=InteractionMode.CALENDAR,
            markdown=markdown,
            plain_text=plain_text,
            citations=citations,
            metadata={"items": str(len(items))},
        )
