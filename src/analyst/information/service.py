from __future__ import annotations

from dataclasses import dataclass

from analyst.contracts import Event, MarketSnapshot, RegimeScore, RegimeState, SourceReference, utc_now

from .repository import InformationRepository


@dataclass(frozen=True)
class ContextPacket:
    bullets: list[str]
    citations: list[SourceReference]


class AnalystInformationService:
    def __init__(self, repository: InformationRepository) -> None:
        self.repository = repository

    def get_market_snapshot(self, focus: str = "global", limit: int = 4) -> MarketSnapshot:
        events = self.repository.recent_events(limit=limit)
        citations = self._collect_references(events)
        headlines = [event.title for event in events]
        return MarketSnapshot(
            as_of=utc_now(),
            focus=focus,
            headline_summary=headlines,
            key_events=events,
            market_prices=self.repository.market_prices(),
            citations=citations,
        )

    def get_calendar(self, limit: int = 5):
        return self.repository.upcoming_calendar(limit=limit)

    def get_context_packet(self, query: str, limit: int = 3) -> ContextPacket:
        snippets = self.repository.search_documents(query, limit=limit)
        return ContextPacket(
            bullets=[snippet.bullet for snippet in snippets],
            citations=[snippet.reference for snippet in snippets],
        )

    def build_regime_state(self, focus: str = "global") -> RegimeState:
        events = self.repository.recent_events(limit=6)
        scores = {
            "risk_sentiment": 50.0,
            "inflation_pressure": 50.0,
            "growth_momentum": 50.0,
            "policy_bias": 50.0,
            "liquidity_conditions": 50.0,
        }
        reasons: dict[str, list[str]] = {axis: [] for axis in scores}

        for event in events:
            self._apply_event(scores, reasons, event)

        score_objects = [
            RegimeScore(
                axis=axis,
                score=round(max(0.0, min(100.0, score)), 1),
                label=self._label_for_axis(axis, score),
                rationale="；".join(reasons[axis]) or "暂无显著驱动，维持中性。",
            )
            for axis, score in scores.items()
        ]
        summary = (
            f"当前状态偏向{self._label_for_axis('policy_bias', scores['policy_bias'])}政策叙事，"
            f"{self._label_for_axis('inflation_pressure', scores['inflation_pressure'])}通胀环境，"
            f"整体风险偏好处于{self._label_for_axis('risk_sentiment', scores['risk_sentiment'])}区间。"
        )
        return RegimeState(
            as_of=utc_now(),
            summary=summary,
            scores=score_objects,
            evidence=events[:3],
            confidence=0.72,
        )

    def _apply_event(self, scores: dict[str, float], reasons: dict[str, list[str]], event: Event) -> None:
        text = f"{event.title} {event.summary}".lower()

        if event.category == "inflation":
            hot = "高于预期" in event.title or "+" in (event.surprise or "") or "hot" in text
            if hot:
                scores["inflation_pressure"] += 14
                scores["policy_bias"] += 10
                scores["risk_sentiment"] -= 6
                reasons["inflation_pressure"].append("通胀超预期抬升价格压力。")
                reasons["policy_bias"].append("通胀黏性让宽松预期后移。")
            else:
                scores["inflation_pressure"] -= 10
                scores["policy_bias"] -= 6
                reasons["inflation_pressure"].append("通胀回落缓解政策压力。")

        if event.category == "policy":
            supportive = "支持" in event.summary or "充裕" in event.summary or "support" in text
            if supportive:
                scores["liquidity_conditions"] += 12
                scores["policy_bias"] -= 8
                scores["risk_sentiment"] += 4
                reasons["liquidity_conditions"].append("政策表态偏稳增长，流动性预期改善。")
                reasons["policy_bias"].append("政策语气更偏托底而非收紧。")

        if event.category == "growth":
            soft = "偏弱" in event.title or "slowed" in text or "有限" in event.summary
            if soft:
                scores["growth_momentum"] -= 10
                scores["risk_sentiment"] -= 5
                reasons["growth_momentum"].append("增长修复斜率仍偏缓。")
                reasons["risk_sentiment"].append("增长不强限制风险偏好上行。")
            else:
                scores["growth_momentum"] += 8
                reasons["growth_momentum"].append("增长数据改善。")

        if event.category == "market":
            stressed = "压制" in event.title or "volatility" in text or "承压" in event.summary
            if stressed:
                scores["risk_sentiment"] -= 12
                scores["liquidity_conditions"] -= 4
                reasons["risk_sentiment"].append("长端利率上行压制成长资产估值。")
                reasons["liquidity_conditions"].append("金融条件边际收紧。")

    def _label_for_axis(self, axis: str, score: float) -> str:
        if axis == "risk_sentiment":
            if score >= 65:
                return "偏强风险偏好"
            if score <= 35:
                return "偏弱风险偏好"
            return "中性风险偏好"
        if axis == "inflation_pressure":
            if score >= 65:
                return "偏热通胀"
            if score <= 35:
                return "偏冷通胀"
            return "温和通胀"
        if axis == "growth_momentum":
            if score >= 65:
                return "增长加速"
            if score <= 35:
                return "增长放缓"
            return "增长平稳"
        if axis == "policy_bias":
            if score >= 65:
                return "偏鹰"
            if score <= 35:
                return "偏鸽"
            return "中性"
        if score >= 65:
            return "流动性宽松"
        if score <= 35:
            return "流动性偏紧"
        return "流动性中性"

    def _collect_references(self, events: list[Event]) -> list[SourceReference]:
        seen: set[str] = set()
        references: list[SourceReference] = []
        for event in events:
            for reference in event.references:
                if reference.url in seen:
                    continue
                seen.add(reference.url)
                references.append(reference)
        return references
