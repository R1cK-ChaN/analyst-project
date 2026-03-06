from __future__ import annotations

from analyst.contracts import (
    DraftResponse,
    InteractionMode,
    ResearchNote,
    SourceReference,
    utc_now,
)
from analyst.information import AnalystInformationService
from analyst.runtime import AgentRuntime, RuntimeContext


class AnalystEngine:
    def __init__(self, info_service: AnalystInformationService, runtime: AgentRuntime) -> None:
        self.info_service = info_service
        self.runtime = runtime

    def answer_question(self, question: str, user_id: str, focus: str = "global") -> DraftResponse:
        return self._generate_response(
            mode=InteractionMode.QA,
            instruction=question,
            user_id=user_id,
            audience="internal_rm",
            focus=focus,
        )

    def generate_draft(self, request: str, user_id: str, focus: str = "global") -> DraftResponse:
        return self._generate_response(
            mode=InteractionMode.DRAFT,
            instruction=request,
            user_id=user_id,
            audience="client_draft",
            focus=focus,
        )

    def generate_meeting_prep(self, request: str, user_id: str, focus: str = "global") -> DraftResponse:
        return self._generate_response(
            mode=InteractionMode.MEETING_PREP,
            instruction=request,
            user_id=user_id,
            audience="internal_rm",
            focus=focus,
        )

    def get_regime_summary(self, focus: str = "global") -> ResearchNote:
        regime_state = self.info_service.build_regime_state(focus=focus)
        snapshot = self.info_service.get_market_snapshot(focus=focus)
        score_lines = "\n".join(
            f"- {score.axis}: {score.label} ({score.score:.0f})，{score.rationale}"
            for score in regime_state.scores
        )
        body = (
            "### 状态总结\n"
            f"{regime_state.summary}\n\n"
            "### 关键驱动\n"
            + "\n".join(f"- {event.title}: {event.summary}" for event in regime_state.evidence)
            + "\n\n### 分项评分\n"
            + score_lines
            + "\n\n### 市场快照\n"
            + "\n".join(f"- {name}: {value}" for name, value in snapshot.market_prices.items())
        )
        return ResearchNote(
            note_id=f"regime-{utc_now().strftime('%Y%m%d%H%M%S')}",
            created_at=utc_now(),
            note_type="regime_summary",
            title="宏观状态摘要",
            summary=regime_state.summary,
            body_markdown=body,
            regime_state=regime_state,
            citations=self._merge_citations(snapshot.citations, []),
            tags=["regime", focus],
        )

    def build_premarket_briefing(self, focus: str = "global") -> ResearchNote:
        snapshot = self.info_service.get_market_snapshot(focus=focus)
        regime_state = self.info_service.build_regime_state(focus=focus)
        calendar = self.info_service.get_calendar(limit=3)
        body = (
            "### 隔夜重点\n"
            + "\n".join(f"- {event.title}: {event.summary}" for event in snapshot.key_events)
            + "\n\n### 今日要看\n"
            + "\n".join(
                f"- {item.indicator} ({item.country}) | 预期 {item.expected or '待定'} | {item.notes}"
                for item in calendar
            )
            + "\n\n### 当前框架\n"
            + regime_state.summary
        )
        citations = self._merge_citations(
            snapshot.citations,
            [reference for item in calendar for reference in item.references],
        )
        return ResearchNote(
            note_id=f"premarket-{utc_now().strftime('%Y%m%d%H%M%S')}",
            created_at=utc_now(),
            note_type="pre_market",
            title="早盘速递",
            summary=regime_state.summary,
            body_markdown=body,
            regime_state=regime_state,
            citations=citations,
            tags=["premarket", focus],
        )

    def get_calendar(self, limit: int = 5):
        return self.info_service.get_calendar(limit=limit)

    def _generate_response(
        self,
        mode: InteractionMode,
        instruction: str,
        user_id: str,
        audience: str,
        focus: str,
    ) -> DraftResponse:
        snapshot = self.info_service.get_market_snapshot(focus=focus)
        regime_state = self.info_service.build_regime_state(focus=focus)
        context_packet = self.info_service.get_context_packet(query=instruction, limit=3)
        context = RuntimeContext(
            mode=mode,
            user_id=user_id,
            instruction=instruction,
            focus=focus,
            audience=audience,
            market_snapshot=snapshot,
            regime_state=regime_state,
            supporting_points=context_packet.bullets or snapshot.headline_summary,
            citations=self._merge_citations(snapshot.citations, context_packet.citations),
        )
        result = self.runtime.generate(context)
        return DraftResponse(
            request_id=f"{mode.value}-{utc_now().strftime('%Y%m%d%H%M%S')}",
            created_at=utc_now(),
            mode=mode,
            audience=audience,
            markdown=result.markdown,
            plain_text=result.plain_text,
            citations=result.citations,
            metadata={"focus": focus, "user_id": user_id},
        )

    def _merge_citations(
        self,
        primary: list[SourceReference],
        secondary: list[SourceReference],
    ) -> list[SourceReference]:
        merged: list[SourceReference] = []
        seen: set[str] = set()
        for reference in [*primary, *secondary]:
            if reference.url in seen:
                continue
            seen.add(reference.url)
            merged.append(reference)
        return merged
