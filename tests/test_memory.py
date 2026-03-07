from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.memory import (
    MemoryManager,
    build_sales_memory_context,
    record_sales_interaction,
    research_global_scope,
    sales_client_scope,
)
from analyst.storage import SQLiteEngineStore


class MemoryIsolationTest(unittest.TestCase):
    def test_sales_memory_is_isolated_by_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            manager = MemoryManager(store)

            record_sales_interaction(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="请简单一点，我最近主要看 BTC 和 Fed。",
                assistant_text="好的，我会更简洁，并优先关注加密和联储。",
            )
            record_sales_interaction(
                manager=manager,
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                user_text="我更关注 A股 的长线配置。",
                assistant_text="收到，我会优先按 A 股和中长期配置来解释。",
            )

            context_a = build_sales_memory_context(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="比特币今晚怎么看？",
            )
            context_b = build_sales_memory_context(
                manager=manager,
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                query="A股怎么看？",
            )

            self.assertIn("crypto", context_a)
            self.assertIn("fed", context_a)
            self.assertNotIn("A股", context_a)
            self.assertIn("equities", context_b)
            self.assertNotIn("BTC", context_b)

            connection = sqlite3.connect(store.db_path)
            logs_count = connection.execute("SELECT COUNT(*) FROM interaction_logs").fetchone()[0]
            connection.close()
            self.assertEqual(logs_count, 2)

    def test_published_artifacts_are_queryable_and_client_safe_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            scope_key = research_global_scope().storage_key()

            store.publish_artifact(
                artifact_type="research_note",
                producer_agent="research",
                title="CPI 数据快评",
                summary="通胀高于预期，利率定价继续偏鹰。",
                content_markdown="### 一句话总结\nCPI 高于预期。",
                payload={"topic": "cpi"},
                tags=["ws1", "inflation"],
                source_scope_key=scope_key,
                client_safe=True,
                metadata={},
            )
            store.publish_artifact(
                artifact_type="performance_summary",
                producer_agent="trader",
                title="内部策略复盘",
                summary="仅供内部使用。",
                content_markdown="内部仓位细节",
                payload={"topic": "internal"},
                tags=["private"],
                source_scope_key="trader-private",
                client_safe=False,
                metadata={},
            )

            safe_results = store.search_published_artifacts(query="CPI", client_safe_only=True, limit=5)
            all_results = store.search_published_artifacts(query="内部", client_safe_only=False, limit=5)

            self.assertEqual(len(safe_results), 1)
            self.assertEqual(safe_results[0].artifact_type, "research_note")
            self.assertEqual(len(all_results), 1)
            self.assertEqual(all_results[0].artifact_type, "performance_summary")

    def test_lower_confidence_fact_does_not_overwrite_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            scope = sales_client_scope("client-a")

            store.upsert_memory_fact(
                scope,
                fact_key="risk_style",
                value="conservative",
                confidence=0.9,
                metadata={},
            )
            store.upsert_memory_fact(
                scope,
                fact_key="risk_style",
                value="aggressive",
                confidence=0.4,
                metadata={},
            )

            facts = store.list_memory_facts(scope)
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0].value, "conservative")
            self.assertEqual(facts[0].confidence, 0.9)

    def test_sales_interaction_populates_client_archival_for_future_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            manager = MemoryManager(store)

            record_sales_interaction(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-1",
                user_text="我重点看 Fed 和利率，帮我之后都说得简洁一点。",
                assistant_text="收到，后续会优先按联储和利率主线，并尽量简洁。",
            )

            context = build_sales_memory_context(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-2",
                query="Fed 今晚怎么解读？",
            )

            self.assertIn("Fed", context)

    def test_sales_archival_search_supports_short_and_natural_language_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            manager = MemoryManager(store)

            record_sales_interaction(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-1",
                user_text="我主要看通胀和利率，后面请直接一点。",
                assistant_text="收到，后续会优先沿着通胀和利率主线，表达也更直接。",
            )

            short_query_context = build_sales_memory_context(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-2",
                query="利率?",
            )
            natural_language_context = build_sales_memory_context(
                manager=manager,
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-3",
                query="今晚怎么讲通胀？",
            )

            self.assertIn("利率", short_query_context)
            self.assertIn("通胀", natural_language_context)


if __name__ == "__main__":
    unittest.main()
