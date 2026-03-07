from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from analyst.contracts import Event, Importance, RegimeScore, RegimeState, ResearchNote, utc_now
from analyst.ingestion import IngestionOrchestrator
from analyst.memory import build_research_context
from analyst.storage import NewsArticleRecord, SQLiteEngineStore, StoredEventRecord

from .agent_loop import AgentLoopConfig, PythonAgentLoop
from .live_prompts import SYSTEM_PROMPT, briefing_prompt, flash_prompt, regime_prompt, wrap_prompt
from .live_provider import OpenRouterConfig, OpenRouterProvider
from .live_types import AgentTool, LLMProvider


def clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, value))


def event_to_contract(event: StoredEventRecord) -> Event:
    return Event(
        event_id=event.event_id,
        timestamp=datetime.fromisoformat(event.datetime_utc),
        source=event.source,
        source_type="calendar_event",
        category=event.category,
        title=f"{event.country} {event.indicator}",
        summary=(
            f"实际 {event.actual or '待公布'}，预期 {event.forecast or '未知'}，前值 {event.previous or '未知'}。"
        ),
        country=event.country,
        importance=Importance(event.importance if event.importance in Importance._value2member_map_ else "medium"),
        actual=event.actual,
        forecast=event.forecast,
        previous=event.previous,
        surprise=str(event.surprise) if event.surprise is not None else None,
    )


@dataclass(frozen=True)
class LiveEngineConfig:
    max_turns: int = 6
    max_tokens: int = 1800
    temperature: float = 0.2


class LiveAnalystEngine:
    def __init__(
        self,
        store: SQLiteEngineStore,
        *,
        provider: LLMProvider | None = None,
        ingestion: IngestionOrchestrator | None = None,
        config: LiveEngineConfig | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.ingestion = ingestion or IngestionOrchestrator(store)
        self.config = config or LiveEngineConfig()

    def refresh_all_sources(self) -> dict[str, int]:
        return self.ingestion.refresh_all()

    def run_schedule(self) -> None:
        self.ingestion.run_schedule()

    def generate_flash_commentary(self, indicator_keyword: str | None = None) -> ResearchNote:
        trigger_event = self.store.latest_released_event(indicator_keyword=indicator_keyword)
        if trigger_event is None:
            raise RuntimeError("No released calendar event available. Run `refresh --once` first.")
        baseline_regime = self._baseline_regime(trigger_event)
        result = self._loop().run(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._with_research_context(flash_prompt(trigger_event, baseline_regime)),
            tools=self._build_tools(),
        )
        return self._finalize_note(
            note_type="flash_commentary",
            title=f"数据快评 | {trigger_event.country} {trigger_event.indicator}",
            markdown=result.final_text,
            trigger_event=trigger_event,
            metadata={"mode": "flash", "indicator_keyword": indicator_keyword or ""},
        )

    def generate_morning_briefing(self) -> ResearchNote:
        upcoming_events = self.store.list_upcoming_events(limit=5)
        baseline_regime = self._baseline_regime()
        prompt = self._with_research_context(briefing_prompt(self._render_event_lines(upcoming_events), baseline_regime))
        result = self._loop().run(system_prompt=SYSTEM_PROMPT, user_prompt=prompt, tools=self._build_tools())
        return self._finalize_note(
            note_type="pre_market",
            title="早盘速递",
            markdown=result.final_text,
            trigger_event=upcoming_events[0] if upcoming_events else None,
            metadata={"mode": "briefing"},
        )

    def generate_after_market_wrap(self) -> ResearchNote:
        recent_events = self.store.list_recent_events(limit=5, days=1, released_only=True)
        baseline_regime = self._baseline_regime()
        prompt = self._with_research_context(wrap_prompt(self._render_event_lines(recent_events), baseline_regime))
        result = self._loop().run(system_prompt=SYSTEM_PROMPT, user_prompt=prompt, tools=self._build_tools())
        return self._finalize_note(
            note_type="after_market_wrap",
            title="收盘点评",
            markdown=result.final_text,
            trigger_event=recent_events[0] if recent_events else None,
            metadata={"mode": "wrap"},
        )

    def refresh_regime(self) -> RegimeState:
        baseline_regime = self._baseline_regime()
        result = self._loop().run(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._with_research_context(regime_prompt(baseline_regime)),
            tools=self._build_tools(),
        )
        regime_payload = self._extract_regime_payload(result.final_text, baseline_regime, None)
        snapshot = self.store.save_regime_snapshot(
            regime_json=regime_payload,
            trigger_event=regime_payload["trigger"],
            summary=regime_payload["dominant_narrative"],
        )
        self._publish_research_output(
            source_kind="regime_snapshot",
            source_id=snapshot.snapshot_id,
            title="宏观状态刷新",
            body_markdown=result.final_text,
            summary=regime_payload["dominant_narrative"],
            artifact_type="regime_snapshot",
            payload=regime_payload,
            tags=["ws1", "regime_refresh"],
        )
        return self._regime_to_contract(snapshot.regime_json)

    def _finalize_note(
        self,
        *,
        note_type: str,
        title: str,
        markdown: str,
        trigger_event: StoredEventRecord | None,
        metadata: dict[str, Any],
    ) -> ResearchNote:
        baseline_regime = self._baseline_regime(trigger_event)
        regime_payload = self._extract_regime_payload(markdown, baseline_regime, trigger_event)
        body_markdown = self._strip_json_blocks(markdown).strip()
        snapshot = self.store.save_regime_snapshot(
            regime_json=regime_payload,
            trigger_event=regime_payload["trigger"],
            summary=regime_payload["dominant_narrative"],
        )
        saved_note = self.store.save_generated_note(
            note_type=note_type,
            title=title,
            summary=regime_payload["dominant_narrative"],
            body_markdown=body_markdown,
            regime_json=regime_payload,
            metadata=metadata,
        )
        self._publish_research_output(
            source_kind="generated_note",
            source_id=saved_note.note_id,
            title=title,
            body_markdown=body_markdown,
            summary=regime_payload["dominant_narrative"],
            artifact_type="research_note",
            payload={
                "note_type": note_type,
                "note_id": saved_note.note_id,
                "snapshot_id": snapshot.snapshot_id,
                "regime": regime_payload,
                "metadata": metadata,
            },
            tags=["ws1", note_type],
        )
        return ResearchNote(
            note_id=f"live-note-{saved_note.note_id}",
            created_at=datetime.fromisoformat(saved_note.created_at),
            note_type=note_type,
            title=title,
            summary=saved_note.summary,
            body_markdown=body_markdown,
            regime_state=self._regime_to_contract(snapshot.regime_json),
            citations=[],
            tags=["ws1", note_type],
        )

    def _build_tools(self) -> list[AgentTool]:
        return [
            AgentTool(
                name="get_recent_releases",
                description="Retrieve recent released macro events from the local SQLite store.",
                parameters={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 7},
                        "limit": {"type": "integer", "default": 10},
                        "importance": {"type": "string"},
                        "country": {"type": "string", "description": "Filter by country code, e.g. US, JP, EU"},
                        "category": {"type": "string", "description": "Filter by category, e.g. inflation, growth, employment"},
                    },
                },
                handler=self._tool_recent_releases,
            ),
            AgentTool(
                name="get_upcoming_calendar",
                description="Retrieve upcoming scheduled macro events from the local SQLite store.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                    },
                },
                handler=self._tool_upcoming_calendar,
            ),
            AgentTool(
                name="get_market_snapshot",
                description="Retrieve the latest cross-asset market snapshot from the local SQLite store.",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_market_snapshot,
            ),
            AgentTool(
                name="get_recent_fed_comms",
                description="Retrieve recent Fed communications from the local SQLite store.",
                parameters={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 14},
                        "limit": {"type": "integer", "default": 5},
                    },
                },
                handler=self._tool_recent_fed_comms,
            ),
            AgentTool(
                name="get_indicator_history",
                description="Retrieve recent FRED history for a known series id.",
                parameters={
                    "type": "object",
                    "required": ["series_id"],
                    "properties": {
                        "series_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 12},
                    },
                },
                handler=self._tool_indicator_history,
            ),
            AgentTool(
                name="get_latest_regime_state",
                description="Retrieve the latest persisted macro regime state.",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_latest_regime_state,
            ),
            AgentTool(
                name="get_today_calendar",
                description="Retrieve today's scheduled and released economic calendar events.",
                parameters={
                    "type": "object",
                    "properties": {
                        "importance": {"type": "string"},
                        "country": {"type": "string"},
                        "category": {"type": "string"},
                    },
                },
                handler=self._tool_today_calendar,
            ),
            AgentTool(
                name="get_indicator_trend",
                description="Retrieve historical releases for a specific indicator keyword to track trends over time.",
                parameters={
                    "type": "object",
                    "required": ["indicator_keyword"],
                    "properties": {
                        "indicator_keyword": {"type": "string", "description": "Keyword to match indicator names, e.g. CPI, NFP, GDP"},
                        "limit": {"type": "integer", "default": 12},
                    },
                },
                handler=self._tool_indicator_trend,
            ),
            AgentTool(
                name="get_surprise_summary",
                description="Summarize recent data surprises grouped by category with beat/miss counts.",
                parameters={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 14},
                    },
                },
                handler=self._tool_surprise_summary,
            ),
            AgentTool(
                name="get_recent_news",
                description="Retrieve recent news articles ranked by time-decay and impact. Supports filtering by impact level, feed category, finance category, country, and asset class.",
                parameters={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 3},
                        "limit": {"type": "integer", "default": 15},
                        "impact_level": {"type": "string", "description": "critical, high, medium, low, info"},
                        "feed_category": {"type": "string", "description": "markets, forex, bonds, centralbanks, china, etc."},
                        "finance_category": {"type": "string", "description": "monetary_policy, inflation, rates, etc."},
                        "country": {"type": "string", "description": "Country code, e.g. US, CN, EU, Global"},
                        "asset_class": {"type": "string", "description": "Asset class, e.g. Macro, Fixed Income, Equity, FX, Commodity"},
                    },
                },
                handler=self._tool_recent_news,
            ),
            AgentTool(
                name="search_news",
                description="Search news articles by keyword using full-text search, ranked by time-decay and impact.",
                parameters={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 15},
                        "days": {"type": "integer", "default": 7},
                        "country": {"type": "string", "description": "Country code, e.g. US, CN, EU"},
                        "asset_class": {"type": "string", "description": "Asset class filter"},
                    },
                },
                handler=self._tool_search_news,
            ),
        ]

    def _loop(self) -> PythonAgentLoop:
        provider = self.provider or OpenRouterProvider(OpenRouterConfig.from_env())
        return PythonAgentLoop(
            provider,
            AgentLoopConfig(
                max_turns=self.config.max_turns,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            ),
        )

    def _tool_recent_releases(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self.store.list_recent_events(
            limit=int(arguments.get("limit", 10)),
            days=int(arguments.get("days", 7)),
            released_only=True,
            importance=arguments.get("importance"),
            country=arguments.get("country"),
            category=arguments.get("category"),
        )
        return {"events": [self._stored_event_to_dict(event) for event in events]}

    def _tool_upcoming_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self.store.list_upcoming_events(limit=int(arguments.get("limit", 10)))
        return {"events": [self._stored_event_to_dict(event) for event in events]}

    def _tool_market_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        prices = self.store.latest_market_prices()
        return {
            "prices": [
                {
                    "symbol": price.symbol,
                    "name": price.name,
                    "asset_class": price.asset_class,
                    "price": price.price,
                    "change_pct": price.change_pct,
                    "datetime_utc": price.datetime_utc,
                }
                for price in prices
            ]
        }

    def _tool_recent_fed_comms(self, arguments: dict[str, Any]) -> dict[str, Any]:
        communications = self.store.list_recent_central_bank_comms(
            days=int(arguments.get("days", 14)),
            limit=int(arguments.get("limit", 5)),
        )
        return {
            "communications": [
                {
                    "title": communication.title,
                    "published_at": communication.published_at,
                    "speaker": communication.speaker,
                    "content_type": communication.content_type,
                    "summary": communication.summary,
                    "url": communication.url,
                }
                for communication in communications
            ]
        }

    def _tool_indicator_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        series_id = str(arguments["series_id"])
        observations = self.store.get_indicator_history(series_id, limit=int(arguments.get("limit", 12)))
        return {
            "series_id": series_id,
            "observations": [
                {
                    "date": observation.date,
                    "value": observation.value,
                    "metadata": observation.metadata,
                }
                for observation in observations
            ],
        }

    def _tool_latest_regime_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        snapshot = self.store.latest_regime_snapshot()
        if snapshot is None:
            return {"regime": None}
        return {"regime": snapshot.regime_json}

    def _tool_today_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self.store.list_today_events(
            importance=arguments.get("importance"),
            country=arguments.get("country"),
            category=arguments.get("category"),
        )
        return {"events": [self._stored_event_to_dict(event) for event in events]}

    def _tool_indicator_trend(self, arguments: dict[str, Any]) -> dict[str, Any]:
        keyword = str(arguments["indicator_keyword"])
        limit = int(arguments.get("limit", 12))
        events = self.store.list_indicator_releases(indicator_keyword=keyword, limit=limit)
        return {
            "indicator_keyword": keyword,
            "releases": [
                {
                    "datetime_utc": event.datetime_utc,
                    "country": event.country,
                    "indicator": event.indicator,
                    "actual": event.actual,
                    "forecast": event.forecast,
                    "previous": event.previous,
                    "surprise": event.surprise,
                }
                for event in events
            ],
        }

    def _tool_surprise_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        days = int(arguments.get("days", 14))
        events = self.store.list_recent_events(limit=200, days=days, released_only=True)
        by_category: dict[str, list[float]] = {}
        for event in events:
            if event.surprise is not None:
                by_category.setdefault(event.category, []).append(event.surprise)
        summary = []
        for category, surprises in sorted(by_category.items()):
            beats = sum(1 for s in surprises if s > 0)
            misses = sum(1 for s in surprises if s < 0)
            avg = round(sum(surprises) / len(surprises), 4) if surprises else 0.0
            summary.append({
                "category": category,
                "count": len(surprises),
                "beats": beats,
                "misses": misses,
                "avg_surprise": avg,
            })
        return {"summary": summary}

    def _tool_recent_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        articles = self.store.get_news_context(
            days=int(arguments.get("days", 3)),
            limit=int(arguments.get("limit", 15)),
            impact_level=arguments.get("impact_level"),
            feed_category=arguments.get("feed_category"),
            finance_category=arguments.get("finance_category"),
            country=arguments.get("country"),
            asset_class=arguments.get("asset_class"),
        )
        return {"articles": articles}

    def _tool_search_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        articles = self.store.get_news_context(
            query=str(arguments["query"]),
            days=int(arguments.get("days", 7)),
            limit=int(arguments.get("limit", 15)),
            country=arguments.get("country"),
            asset_class=arguments.get("asset_class"),
        )
        return {"articles": articles}

    def _news_article_to_dict(self, article: NewsArticleRecord) -> dict[str, Any]:
        desc = article.description
        if len(desc) > 500:
            desc = desc[:500] + "..."
        return {
            "source_feed": article.source_feed,
            "title": article.title,
            "url": article.url,
            "published_at": article.published_at,
            "description": desc,
            "impact_level": article.impact_level,
            "finance_category": article.finance_category,
            "country": article.country,
            "asset_class": article.asset_class,
            "subject": article.subject,
            "event_type": article.event_type,
        }

    def _stored_event_to_dict(self, event: StoredEventRecord) -> dict[str, Any]:
        return {
            "source": event.source,
            "event_id": event.event_id,
            "datetime_utc": event.datetime_utc,
            "country": event.country,
            "indicator": event.indicator,
            "category": event.category,
            "importance": event.importance,
            "actual": event.actual,
            "forecast": event.forecast,
            "previous": event.previous,
            "surprise": event.surprise,
        }

    def _baseline_regime(self, trigger_event: StoredEventRecord | None = None) -> dict[str, Any]:
        latest_snapshot = self.store.latest_regime_snapshot()
        if latest_snapshot is not None:
            baseline = dict(latest_snapshot.regime_json)
        else:
            baseline = {
                "risk_appetite": 0.5,
                "fed_hawkishness": 0.5,
                "growth_momentum": 0.5,
                "inflation_trend": "stable",
                "liquidity_conditions": "neutral",
                "dominant_narrative": "市场等待新的宏观证据，当前框架偏中性。",
                "narrative_risk": "若核心通胀和就业同时再度走强，市场会重新定价 higher-for-longer。",
                "regime_label": "neutral",
                "confidence": 0.55,
                "cross_asset_implications": {
                    "rates": "利率在区间内等待下一组关键数据。",
                    "dollar": "美元缺少新的单边驱动。",
                    "a_shares": "A股更依赖国内政策和北向资金节奏。",
                    "hk_stocks": "港股对美债利率和美元方向更敏感。",
                    "us_equities": "美股估值仍受利率路径影响。",
                    "commodities": "大宗走势取决于增长和美元的相对强弱。",
                    "crypto": "加密资产继续交易全球流动性和风险偏好。",
                },
                "last_updated": utc_now().isoformat(),
                "trigger": trigger_event.indicator if trigger_event else "baseline",
            }

        recent_events = self.store.list_recent_events(limit=6, days=30, released_only=True)
        for event in recent_events:
            if event.category == "inflation" and event.surprise is not None:
                if event.surprise > 0:
                    baseline["fed_hawkishness"] = clamp_unit_interval(float(baseline["fed_hawkishness"]) + 0.12)
                    baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) - 0.08)
                    baseline["inflation_trend"] = "accelerating"
                elif event.surprise < 0:
                    baseline["fed_hawkishness"] = clamp_unit_interval(float(baseline["fed_hawkishness"]) - 0.08)
                    baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) + 0.05)
                    baseline["inflation_trend"] = "decelerating"
            elif event.category == "growth" and event.surprise is not None:
                if event.surprise > 0:
                    baseline["growth_momentum"] = clamp_unit_interval(float(baseline["growth_momentum"]) + 0.1)
                elif event.surprise < 0:
                    baseline["growth_momentum"] = clamp_unit_interval(float(baseline["growth_momentum"]) - 0.1)
                    baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) - 0.05)
            elif event.category == "policy":
                summary_text = json.dumps(event.raw_json, ensure_ascii=True)
                if "support" in summary_text.lower() or "liquidity" in summary_text.lower():
                    baseline["liquidity_conditions"] = "easing"
                    baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) + 0.04)

        market_snapshot = {price.symbol: price for price in self.store.latest_market_prices()}
        vix = market_snapshot.get("^VIX")
        ten_year = market_snapshot.get("^TNX")
        dollar = market_snapshot.get("DX-Y.NYB")
        if vix and vix.price >= 20:
            baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) - 0.1)
        if ten_year and ten_year.price >= 4.5:
            baseline["fed_hawkishness"] = clamp_unit_interval(float(baseline["fed_hawkishness"]) + 0.08)
        if dollar and dollar.change_pct and dollar.change_pct > 0.5:
            baseline["risk_appetite"] = clamp_unit_interval(float(baseline["risk_appetite"]) - 0.05)

        risk_appetite = float(baseline["risk_appetite"])
        if risk_appetite >= 0.6:
            baseline["regime_label"] = "risk_on"
        elif risk_appetite <= 0.4:
            baseline["regime_label"] = "risk_off"
        else:
            baseline["regime_label"] = "neutral"

        if trigger_event:
            baseline["trigger"] = trigger_event.indicator
            baseline["dominant_narrative"] = (
                f"最新主线围绕 {trigger_event.country} {trigger_event.indicator} 展开，"
                "市场继续在增长韧性与政策路径重定价之间寻找平衡。"
            )
        baseline["last_updated"] = utc_now().isoformat()
        baseline["confidence"] = clamp_unit_interval(float(baseline.get("confidence", 0.6)))
        return baseline

    def _extract_regime_payload(
        self,
        markdown: str,
        fallback: dict[str, Any],
        trigger_event: StoredEventRecord | None,
    ) -> dict[str, Any]:
        payload = dict(fallback)
        matches = re.findall(r"```json\s*(\{.*?\})\s*```", markdown, flags=re.DOTALL)
        for raw_json in reversed(matches):
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            payload.update(parsed)
            break
        payload["risk_appetite"] = clamp_unit_interval(float(payload.get("risk_appetite", fallback["risk_appetite"])))
        payload["fed_hawkishness"] = clamp_unit_interval(
            float(payload.get("fed_hawkishness", fallback["fed_hawkishness"]))
        )
        payload["growth_momentum"] = clamp_unit_interval(
            float(payload.get("growth_momentum", fallback["growth_momentum"]))
        )
        payload["confidence"] = clamp_unit_interval(float(payload.get("confidence", fallback["confidence"])))
        payload["inflation_trend"] = payload.get("inflation_trend", fallback["inflation_trend"])
        payload["liquidity_conditions"] = payload.get("liquidity_conditions", fallback["liquidity_conditions"])
        payload["dominant_narrative"] = str(payload.get("dominant_narrative", fallback["dominant_narrative"]))
        payload["narrative_risk"] = str(payload.get("narrative_risk", fallback["narrative_risk"]))
        payload["regime_label"] = payload.get("regime_label", fallback["regime_label"])
        payload["cross_asset_implications"] = {
            **fallback.get("cross_asset_implications", {}),
            **dict(payload.get("cross_asset_implications", {})),
        }
        payload["last_updated"] = utc_now().isoformat()
        payload["trigger"] = payload.get("trigger") or (trigger_event.indicator if trigger_event else "regime_refresh")
        return payload

    def _strip_json_blocks(self, markdown: str) -> str:
        return re.sub(r"```json\s*\{.*?\}\s*```", "", markdown, flags=re.DOTALL)

    def _render_event_lines(self, events: list[StoredEventRecord]) -> str:
        if not events:
            return "- 暂无事件。"
        return "\n".join(
            f"- {event.datetime_utc} | {event.country} {event.indicator} | 实际 {event.actual or '待公布'} | "
            f"预期 {event.forecast or '未知'} | 前值 {event.previous or '未知'}"
            for event in events
        )

    def _with_research_context(self, prompt: str) -> str:
        context = build_research_context(self.store)
        if not context:
            return prompt
        return f"## 已知研究上下文\n{context}\n\n{prompt}"

    def _publish_research_output(
        self,
        *,
        source_kind: str,
        source_id: int,
        title: str,
        body_markdown: str,
        summary: str,
        artifact_type: str,
        payload: dict[str, Any],
        tags: list[str],
    ):
        self.store.add_analytical_observation(
            observation_type="published_output",
            summary=summary,
            detail=title,
            source_kind=source_kind,
            source_id=source_id,
            metadata={"artifact_type": artifact_type, "payload": payload},
        )
        return self.store.publish_research_artifact(
            artifact_type=artifact_type,
            title=title,
            summary=summary,
            content_markdown=body_markdown,
            source_kind=source_kind,
            source_id=source_id,
            tags=tags,
            metadata={"source": "live_engine", "payload": payload},
        )

    def _regime_to_contract(self, regime_json: dict[str, Any]) -> RegimeState:
        evidence_events = [event_to_contract(event) for event in self.store.list_recent_events(limit=3, days=7, released_only=True)]
        scores = [
            RegimeScore(
                axis="risk_appetite",
                score=round(float(regime_json["risk_appetite"]) * 100, 1),
                label=self._risk_label(float(regime_json["risk_appetite"])),
                rationale=regime_json["dominant_narrative"],
            ),
            RegimeScore(
                axis="fed_hawkishness",
                score=round(float(regime_json["fed_hawkishness"]) * 100, 1),
                label=self._hawkish_label(float(regime_json["fed_hawkishness"])),
                rationale=regime_json["narrative_risk"],
            ),
            RegimeScore(
                axis="growth_momentum",
                score=round(float(regime_json["growth_momentum"]) * 100, 1),
                label=self._growth_label(float(regime_json["growth_momentum"])),
                rationale=regime_json["cross_asset_implications"].get("us_equities", ""),
            ),
            RegimeScore(
                axis="inflation_trend",
                score=self._categorical_score(str(regime_json["inflation_trend"])),
                label=str(regime_json["inflation_trend"]),
                rationale=regime_json["cross_asset_implications"].get("rates", ""),
            ),
            RegimeScore(
                axis="liquidity_conditions",
                score=self._categorical_score(str(regime_json["liquidity_conditions"])),
                label=str(regime_json["liquidity_conditions"]),
                rationale=regime_json["cross_asset_implications"].get("crypto", ""),
            ),
        ]
        return RegimeState(
            as_of=utc_now(),
            summary=regime_json["dominant_narrative"],
            scores=scores,
            evidence=evidence_events,
            confidence=float(regime_json["confidence"]),
        )

    def _risk_label(self, value: float) -> str:
        if value >= 0.6:
            return "偏强风险偏好"
        if value <= 0.4:
            return "偏弱风险偏好"
        return "中性风险偏好"

    def _hawkish_label(self, value: float) -> str:
        if value >= 0.6:
            return "偏鹰"
        if value <= 0.4:
            return "偏鸽"
        return "中性"

    def _growth_label(self, value: float) -> str:
        if value >= 0.6:
            return "增长加速"
        if value <= 0.4:
            return "增长放缓"
        return "增长平稳"

    def _categorical_score(self, value: str) -> float:
        mapping = {
            "accelerating": 75.0,
            "stable": 50.0,
            "decelerating": 25.0,
            "tightening": 75.0,
            "neutral": 50.0,
            "easing": 25.0,
        }
        return mapping.get(value, 50.0)
