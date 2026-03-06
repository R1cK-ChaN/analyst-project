from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from analyst_shared import CalendarItem, Event, Importance, SourceReference, utc_now


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


class DemoInformationRepository:
    def __init__(self) -> None:
        now = utc_now()
        self._events = [
            Event(
                event_id="us-cpi-hot",
                timestamp=now - timedelta(hours=3),
                source="gov_report",
                source_type="official_release",
                category="inflation",
                title="美国CPI高于预期",
                summary="核心通胀继续偏黏，市场对美联储降息时点重新定价。",
                country="US",
                importance=Importance.HIGH,
                actual="3.4%",
                forecast="3.2%",
                previous="3.1%",
                surprise="+0.2pp",
                tags=["cpi", "inflation", "fed"],
                references=[
                    SourceReference(
                        title="US CPI release",
                        url="https://example.com/us-cpi",
                        source="gov_report",
                        excerpt="核心通胀高于预期，利率路径重新定价。",
                    )
                ],
            ),
            Event(
                event_id="pboc-support",
                timestamp=now - timedelta(hours=6),
                source="gov_report",
                source_type="official_release",
                category="policy",
                title="人民银行释放稳增长信号",
                summary="公开市场操作维持流动性平稳，政策语气偏支持实体经济。",
                country="CN",
                importance=Importance.HIGH,
                tags=["pboc", "liquidity", "china"],
                references=[
                    SourceReference(
                        title="PBOC policy note",
                        url="https://example.com/pboc-policy",
                        source="gov_report",
                        excerpt="政策表态强调流动性合理充裕。",
                    )
                ],
            ),
            Event(
                event_id="eu-pmi-soft",
                timestamp=now - timedelta(hours=10),
                source="news",
                source_type="market_news",
                category="growth",
                title="欧洲制造业景气仍偏弱",
                summary="制造业景气改善有限，全球需求复苏斜率仍然偏缓。",
                country="EU",
                importance=Importance.MEDIUM,
                tags=["pmi", "growth"],
                references=[
                    SourceReference(
                        title="PMI coverage",
                        url="https://example.com/eu-pmi",
                        source="news",
                        excerpt="全球制造业复苏节奏仍不稳。",
                    )
                ],
            ),
            Event(
                event_id="rates-volatility",
                timestamp=now - timedelta(hours=1),
                source="news",
                source_type="market_news",
                category="market",
                title="美债收益率上行压制风险偏好",
                summary="10年期美债收益率走高，成长资产估值承压。",
                country="US",
                importance=Importance.MEDIUM,
                tags=["rates", "risk"],
                references=[
                    SourceReference(
                        title="Rates market wrap",
                        url="https://example.com/rates-wrap",
                        source="news",
                        excerpt="长端利率上行带来估值压力。",
                    )
                ],
            ),
        ]
        self._calendar = [
            CalendarItem(
                event_id="us-nfp-upcoming",
                release_time=now + timedelta(hours=8),
                indicator="美国非农就业",
                country="US",
                importance=Importance.HIGH,
                expected="18.5万",
                previous="16.7万",
                notes="若就业和薪资同时偏强，市场会继续交易降息推后。",
                references=[
                    SourceReference(
                        title="Payroll calendar",
                        url="https://example.com/nfp-calendar",
                        source="calendar",
                        excerpt="非农是今晚最关键的数据点。",
                    )
                ],
            ),
            CalendarItem(
                event_id="cn-cpi-upcoming",
                release_time=now + timedelta(days=1, hours=2),
                indicator="中国CPI",
                country="CN",
                importance=Importance.MEDIUM,
                expected="0.4%",
                previous="0.3%",
                notes="关注内需修复和政策预期的交叉验证。",
                references=[],
            ),
        ]
        self._documents = [
            DocumentSnippet(
                topic="nonfarm payrolls",
                bullet="非农若明显强于预期，通常先推升美债收益率和美元，再压缩高估值资产风险偏好。",
                reference=SourceReference(
                    title="Payroll playbook",
                    url="https://example.com/payroll-playbook",
                    source="doc_parser",
                    excerpt="强非农先影响利率预期，再影响风险资产。",
                ),
            ),
            DocumentSnippet(
                topic="cpi inflation",
                bullet="通胀高于预期时，市场最先重定价的是政策路径，其次才是增长解释框架。",
                reference=SourceReference(
                    title="Inflation framework",
                    url="https://example.com/inflation-framework",
                    source="doc_parser",
                    excerpt="先看政策路径，再看资产映射。",
                ),
            ),
            DocumentSnippet(
                topic="pboc china liquidity",
                bullet="如果国内政策语气偏稳增长，A股和信用风险偏好往往得到边际托底，但外需变量仍是上限约束。",
                reference=SourceReference(
                    title="China liquidity note",
                    url="https://example.com/china-liquidity",
                    source="doc_parser",
                    excerpt="国内流动性托底，但外需约束仍在。",
                ),
            ),
        ]

    def recent_events(self, limit: int = 8) -> list[Event]:
        return self._events[:limit]

    def upcoming_calendar(self, limit: int = 5) -> list[CalendarItem]:
        return self._calendar[:limit]

    def market_prices(self) -> dict[str, float]:
        return {
            "US10Y": 4.28,
            "DXY": 104.60,
            "SPX": 5092.0,
            "CSI300": 3658.0,
            "USD/CNH": 7.18,
            "Gold": 2176.0,
        }

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
