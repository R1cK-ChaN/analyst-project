"""Tests for the 4 stored-data tools: search_news, get_fed_communications,
get_indicator_history, search_research_notes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analyst.storage.sqlite import (
    CentralBankCommunicationRecord,
    IndicatorObservationRecord,
    NewsArticleRecord,
    SQLiteEngineStore,
)
from analyst.tools._stored_news import StoredNewsHandler, build_stored_news_tool
from analyst.tools._stored_fed_comms import FedCommsHandler, build_fed_comms_tool
from analyst.tools._stored_indicators import IndicatorHistoryHandler, build_indicator_history_tool
from analyst.tools._stored_research import ResearchSearchHandler, build_research_search_tool


class _StoreTestMixin:
    """Create a temp store and seed test data."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.store = SQLiteEngineStore(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()


class TestStoredNewsHandler(_StoreTestMixin, unittest.TestCase):
    def _seed_news(self, *, title: str = "CPI surges past expectations",
                   feed_category: str = "markets", finance_category: str = "inflation",
                   impact_level: str = "high", country: str = "US") -> None:
        import hashlib, time
        url = f"https://example.com/{hashlib.md5(title.encode()).hexdigest()}"
        article = NewsArticleRecord(
            url_hash=hashlib.md5(url.encode()).hexdigest(),
            source_feed="test_feed",
            feed_category=feed_category,
            title=title,
            url=url,
            timestamp=int(time.time()) - 3600,
            description=f"Description of: {title}",
            content_markdown="",
            impact_level=impact_level,
            finance_category=finance_category,
            confidence=0.9,
            content_fetched=False,
            country=country,
        )
        self.store.upsert_news_article(article)

    def test_build_tool_returns_agent_tool(self) -> None:
        tool = build_stored_news_tool(self.store)
        self.assertEqual(tool.name, "search_news")
        self.assertIn("news archive", tool.description)

    def test_search_with_query(self) -> None:
        self._seed_news()
        handler = StoredNewsHandler(self.store)
        result = handler({"query": "CPI"})
        self.assertGreaterEqual(result["total"], 1)
        self.assertEqual(result["articles"][0]["title"], "CPI surges past expectations")

    def test_search_with_filters(self) -> None:
        self._seed_news(title="Fed raises rates", finance_category="monetary_policy", impact_level="critical")
        self._seed_news(title="China GDP slows", country="CN", finance_category="growth")
        handler = StoredNewsHandler(self.store)

        result = handler({"country": "CN"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["articles"][0]["country"], "CN")

        result = handler({"impact_level": "critical"})
        self.assertEqual(result["total"], 1)

    def test_empty_results(self) -> None:
        handler = StoredNewsHandler(self.store)
        result = handler({"query": "nonexistent"})
        self.assertEqual(result["total"], 0)

    def test_days_and_limit_clamped(self) -> None:
        handler = StoredNewsHandler(self.store)
        result = handler({"days": 999, "limit": 999})
        self.assertEqual(result["days"], 30)
        self.assertEqual(result["total"], 0)


class TestFedCommsHandler(_StoreTestMixin, unittest.TestCase):
    def _seed_comm(self, *, title: str = "Powell Speech on Inflation",
                   speaker: str = "Powell", content_type: str = "speech") -> None:
        import time
        comm = CentralBankCommunicationRecord(
            source="fed",
            title=title,
            url=f"https://fed.gov/{title.replace(' ', '-').lower()}",
            timestamp=int(time.time()) - 3600,
            content_type=content_type,
            speaker=speaker,
            summary=f"Summary of {title}",
            full_text=f"Full text of {title}",
        )
        self.store.upsert_central_bank_comm(comm)

    def test_build_tool_returns_agent_tool(self) -> None:
        tool = build_fed_comms_tool(self.store)
        self.assertEqual(tool.name, "get_fed_communications")

    def test_query_all(self) -> None:
        self._seed_comm()
        self._seed_comm(title="Waller on rates", speaker="Waller")
        handler = FedCommsHandler(self.store)
        result = handler({})
        self.assertEqual(result["total"], 2)

    def test_filter_by_speaker(self) -> None:
        self._seed_comm()
        self._seed_comm(title="Waller on rates", speaker="Waller")
        handler = FedCommsHandler(self.store)
        result = handler({"speaker": "Powell"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["communications"][0]["speaker"], "Powell")

    def test_filter_by_content_type(self) -> None:
        self._seed_comm()
        self._seed_comm(title="FOMC Statement", speaker="", content_type="statement")
        handler = FedCommsHandler(self.store)
        result = handler({"content_type": "statement"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["communications"][0]["content_type"], "statement")

    def test_days_clamped(self) -> None:
        handler = FedCommsHandler(self.store)
        result = handler({"days": 999})
        self.assertEqual(result["days"], 60)


class TestIndicatorHistoryHandler(_StoreTestMixin, unittest.TestCase):
    def _seed_indicators(self) -> None:
        for i in range(5):
            obs = IndicatorObservationRecord(
                series_id="CPIAUCSL",
                source="fred",
                date=f"2025-{12-i:02d}-01",
                value=300.0 + i,
            )
            self.store.upsert_indicator_observation(obs)

    def test_build_tool_returns_agent_tool(self) -> None:
        tool = build_indicator_history_tool(self.store)
        self.assertEqual(tool.name, "get_indicator_history")
        self.assertIn("series_id", json.dumps(tool.parameters))

    def test_query_series(self) -> None:
        self._seed_indicators()
        handler = IndicatorHistoryHandler(self.store)
        result = handler({"series_id": "CPIAUCSL"})
        self.assertEqual(result["series_id"], "CPIAUCSL")
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["observations"][0]["series_id"], "CPIAUCSL")

    def test_missing_series_id(self) -> None:
        handler = IndicatorHistoryHandler(self.store)
        result = handler({})
        self.assertIn("error", result)

    def test_unknown_series(self) -> None:
        handler = IndicatorHistoryHandler(self.store)
        result = handler({"series_id": "NONEXISTENT"})
        self.assertEqual(result["total"], 0)

    def test_limit_clamped(self) -> None:
        self._seed_indicators()
        handler = IndicatorHistoryHandler(self.store)
        result = handler({"series_id": "CPIAUCSL", "limit": 2})
        self.assertEqual(result["total"], 2)


class TestResearchSearchHandler(_StoreTestMixin, unittest.TestCase):
    def _seed_artifact(self, *, title: str = "CPI Flash Commentary",
                       artifact_type: str = "flash_commentary") -> None:
        self.store.publish_research_artifact(
            artifact_type=artifact_type,
            title=title,
            summary=f"Summary about {title}",
            content_markdown=f"Full content of {title}",
            source_kind="test",
            source_id=1,
            tags=["cpi", "inflation"],
        )

    def test_build_tool_returns_agent_tool(self) -> None:
        tool = build_research_search_tool(self.store)
        self.assertEqual(tool.name, "search_research_notes")

    def test_search_by_keyword(self) -> None:
        self._seed_artifact()
        handler = ResearchSearchHandler(self.store)
        result = handler({"query": "CPI"})
        self.assertGreaterEqual(result["total"], 1)
        self.assertIn("CPI", result["artifacts"][0]["title"])

    def test_filter_by_type(self) -> None:
        self._seed_artifact()
        self._seed_artifact(title="Deep Dive on Rates", artifact_type="deep_dive")
        handler = ResearchSearchHandler(self.store)
        result = handler({"query": "Rates", "artifact_type": "deep_dive"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["artifacts"][0]["artifact_type"], "deep_dive")

    def test_missing_query(self) -> None:
        handler = ResearchSearchHandler(self.store)
        result = handler({})
        self.assertIn("error", result)

    def test_no_results(self) -> None:
        handler = ResearchSearchHandler(self.store)
        result = handler({"query": "nonexistent_topic_xyz"})
        self.assertEqual(result["total"], 0)


class TestToolsWiredInBuildChatTools(unittest.TestCase):
    """Verify companion chat tools are returned by build_chat_tools."""

    def test_companion_tools_present(self) -> None:
        from unittest.mock import MagicMock
        from analyst.delivery.user_chat import build_chat_tools

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "test.db")
            tools = build_chat_tools(store=store, provider=MagicMock())
            tool_names = {t.name for t in tools}
            self.assertIn("research_agent", tool_names)
            self.assertIn("generate_image", tool_names)


if __name__ == "__main__":
    unittest.main()
