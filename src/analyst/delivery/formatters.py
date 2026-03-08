from __future__ import annotations

from analyst.contracts import CalendarItem, ChannelMessage, DraftResponse, InteractionMode, ResearchNote


DISCLAIMERS = {
    InteractionMode.QA: "内部研究辅助内容，请结合最新数据和合规要求复核。",
    InteractionMode.DRAFT: "客户外发前请人工编辑并完成合规复核。",
    InteractionMode.FOLLOW_UP: "客户外发前请人工编辑并完成合规复核。",
    InteractionMode.MEETING_PREP: "仅供会前准备，正式口径请结合团队统一表述。",
    InteractionMode.REGIME: "宏观状态为研究框架，不构成投资建议。",
    InteractionMode.CALENDAR: "日历信息仅供提醒，实际发布时间以官方披露为准。",
}


class WeComFormatter:
    def format_draft(self, response: DraftResponse) -> ChannelMessage:
        disclaimer = DISCLAIMERS[response.mode]
        markdown = f"{response.markdown}\n\n### 合规提示\n{disclaimer}"
        plain_text = f"{response.plain_text}\n\n合规提示: {disclaimer}"
        return ChannelMessage(
            message_id=response.request_id,
            channel="wecom",
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
        disclaimer = DISCLAIMERS[mode]
        markdown = f"## {note.title}\n\n{note.body_markdown}\n\n### 合规提示\n{disclaimer}"
        plain_text = f"{note.title}\n\n{note.summary}\n\n合规提示: {disclaimer}"
        return ChannelMessage(
            message_id=note.note_id,
            channel="wecom",
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
        markdown = (
            "## 今日/近期数据日历\n\n"
            + "\n".join(lines)
            + f"\n\n### 合规提示\n{DISCLAIMERS[InteractionMode.CALENDAR]}"
        )
        plain_text = "近期数据日历\n" + "\n".join(lines)
        citations = [reference for item in items for reference in item.references]
        return ChannelMessage(
            message_id="calendar-reply",
            channel="wecom",
            mode=InteractionMode.CALENDAR,
            markdown=markdown,
            plain_text=plain_text,
            citations=citations,
            metadata={"items": str(len(items))},
        )
