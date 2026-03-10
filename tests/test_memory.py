from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.memory import (
    ClientProfileUpdate,
    build_research_context,
    build_sales_context,
    build_trading_context,
    record_sales_interaction,
)
from analyst.storage import SQLiteEngineStore


class MemoryPipelineTest(unittest.TestCase):
    def test_sales_context_is_isolated_by_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="请简单一点，我最近主要看 BTC 和 Fed。",
                assistant_text="好的，我会更简洁，并优先关注加密和联储。",
            )
            record_sales_interaction(
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                user_text="我更关注 A股 的长线配置。",
                assistant_text="收到，我会优先按 A 股和中长期配置来解释。",
            )

            context_a = build_sales_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="比特币今晚怎么看？",
            )
            context_b = build_sales_context(
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                query="A股怎么看？",
            )

            self.assertIn("crypto", context_a)
            self.assertIn("fed", context_a)
            self.assertNotIn("equities", context_a)
            self.assertIn("equities", context_b)
            self.assertNotIn("BTC", context_b)

            connection = sqlite3.connect(store.db_path)
            messages_count = connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0]
            deliveries_count = connection.execute("SELECT COUNT(*) FROM delivery_queue").fetchone()[0]
            connection.close()
            self.assertEqual(messages_count, 4)
            self.assertEqual(deliveries_count, 2)

    def test_sales_uses_delivery_queue_not_raw_research_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            raw_artifact = store.publish_research_artifact(
                artifact_type="flash_commentary",
                title="CPI 数据快评",
                summary="通胀高于预期。",
                content_markdown="### 结论\nCPI 高于预期，利率定价转鹰。",
                source_kind="generated_note",
                source_id=1,
                tags=["cpi"],
                metadata={},
            )
            store.enqueue_delivery(
                client_id="client-a",
                channel="telegram:1",
                thread_id="main",
                source_type="research_artifact",
                source_artifact_id=raw_artifact.artifact_id,
                content_rendered="CPI 高于预期，先按利率重新定价来理解。",
                status="delivered",
                delivered_at="2026-03-07T12:00:00+00:00",
                metadata={"artifact_type": raw_artifact.artifact_type},
            )

            context_a = build_sales_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="今晚 CPI 怎么看？",
            )
            context_b = build_sales_context(
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                query="今晚 CPI 怎么看？",
            )

            self.assertIn("CPI 高于预期", context_a)
            self.assertNotIn("CPI 高于预期", context_b)

    def test_tool_audit_is_persisted_on_assistant_message_and_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="看看咖啡",
                assistant_text="图来了",
                tool_audit=[
                    {
                        "tool_name": "generate_image",
                        "arguments": {"prompt": "coffee on a cafe table"},
                        "status": "ok",
                        "image_url": "https://example.com/coffee.jpg",
                    }
                ],
            )

            messages = store.list_conversation_messages(
                client_id="client-a",
                channel="telegram:1",
                thread_id="main",
            )
            deliveries = store.list_recent_deliveries(
                client_id="client-a",
                channel="telegram:1",
                thread_id="main",
            )

            self.assertEqual(messages[-1].role, "assistant")
            self.assertEqual(messages[-1].metadata["tool_audit"][0]["tool_name"], "generate_image")
            self.assertEqual(deliveries[0].metadata["tool_audit"][0]["status"], "ok")

    def test_record_sales_interaction_updates_structured_client_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="我偏保守，做长线，后面尽量简洁一点，重点看 Fed 和利率。",
                assistant_text="收到，我会按更简洁的方式说明联储和利率主线。",
            )

            profile = store.get_client_profile("client-a")
            self.assertEqual(profile.preferred_language, "zh")
            self.assertEqual(profile.response_style, "concise")
            self.assertEqual(profile.risk_appetite, "conservative")
            self.assertEqual(profile.investment_horizon, "long_term")
            self.assertIn("fed", profile.watchlist_topics)
            self.assertIn("rates", profile.watchlist_topics)
            self.assertEqual(profile.total_interactions, 1)

    def test_client_profile_accumulates_across_multiple_interactions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="我看好黄金。",
                assistant_text="收到，先按黄金主线跟踪。",
            )
            profile = store.get_client_profile("client-a")
            self.assertEqual(profile.preferred_language, "zh")
            self.assertIn("gold", profile.watchlist_topics)

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="What about gold and oil?",
                assistant_text="Gold still matters, and I will also track oil.",
            )
            profile = store.get_client_profile("client-a")
            self.assertEqual(profile.preferred_language, "en")
            self.assertIn("gold", profile.watchlist_topics)
            self.assertIn("oil", profile.watchlist_topics)
            self.assertEqual(profile.total_interactions, 2)

    def test_assistant_profile_update_is_merged_and_hidden_from_storage_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="最近市场太难做了，我主要看港股。",
                assistant_text="先别急，我晚点把图发你。",
                assistant_profile_update=ClientProfileUpdate(
                    institution_type="hedge_fund",
                    market_focus=["hk_equities"],
                    current_mood="anxious",
                    confidence="medium",
                    notes="More focused on HK equities and sentiment turning points.",
                ),
            )

            profile = store.get_client_profile("client-a")
            self.assertEqual(profile.institution_type, "hedge_fund")
            self.assertIn("hk_equities", profile.market_focus)
            self.assertEqual(profile.current_mood, "anxious")
            self.assertEqual(profile.confidence, "medium")
            self.assertIn("sentiment", profile.notes)

            context = build_sales_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="港股今天怎么看？",
            )
            self.assertIn("institution_type: hedge_fund", context)
            self.assertIn("hk_equities", context)
            self.assertIn("current_mood: anxious", context)

    def test_sales_context_uses_delivery_history_for_future_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-1",
                user_text="我重点看 Fed 和利率，帮我之后都说得简洁一点。",
                assistant_text="收到，后续会优先按联储和利率主线，并尽量简洁。",
            )

            context = build_sales_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-2",
                query="Fed 今晚怎么解读？",
            )

            self.assertIn("联储和利率主线", context)

    def test_research_and_trading_context_builders_use_typed_stores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            snapshot = store.save_regime_snapshot(
                regime_json={"dominant_narrative": "通胀黏性压制降息预期。"},
                trigger_event="CPI",
                summary="通胀黏性压制降息预期。",
            )
            note = store.save_generated_note(
                note_type="flash_commentary",
                title="数据快评 | CPI",
                summary="利率定价继续偏鹰。",
                body_markdown="### 一句话总结\nCPI 高于预期。",
                regime_json={"dominant_narrative": "通胀黏性压制降息预期。"},
                metadata={},
            )
            store.add_analytical_observation(
                observation_type="pattern",
                summary="CPI 已连续三个月高于预期。",
                detail="说明通胀下行速度慢于市场预期。",
                source_kind="generated_note",
                source_id=note.note_id,
                metadata={},
            )
            research_artifact = store.publish_research_artifact(
                artifact_type="flash_commentary",
                title=note.title,
                summary=note.summary,
                content_markdown=note.body_markdown,
                source_kind="generated_note",
                source_id=note.note_id,
                tags=["ws1"],
                metadata={},
            )
            decision = store.log_trading_decision(
                decision_type="allocation_shift",
                title="降低久期",
                summary="在更久高利率路径下缩短久期。",
                rationale_markdown="久期敏感资产先降风险。",
                research_artifact_id=research_artifact.artifact_id,
                signal_id=None,
                metadata={},
            )
            store.upsert_position_state(
                symbol="US10Y",
                exposure=-0.25,
                direction="short",
                thesis="更久高利率压制长端利率下行空间。",
                metadata={},
            )
            store.record_performance(
                metric_name="pnl",
                metric_value=1.8,
                period_label="1w",
                metadata={},
            )
            store.publish_trading_artifact(
                artifact_type="recommendation",
                title="短久期建议",
                summary="先控制利率敏感资产久期。",
                rationale_markdown="通胀与联储路径仍偏鹰。",
                research_artifact_id=research_artifact.artifact_id,
                decision_log_id=decision.decision_id,
                signal={"instrument": "US10Y", "action": "short"},
                confidence=0.74,
                tags=["rates"],
                metadata={},
            )

            research_context = build_research_context(store)
            trading_context = build_trading_context(store)

            self.assertIn(snapshot.summary, research_context)
            self.assertIn("CPI 已连续三个月高于预期", research_context)
            self.assertIn("短久期建议", trading_context)
            self.assertIn("US10Y", trading_context)

    def test_days_since_last_active_handles_naive_timestamp(self) -> None:
        """Naive ISO timestamps (no tzinfo) must not crash the context builder."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            # Upsert with a naive timestamp (no +00:00 suffix).
            store.upsert_client_profile(
                "client-naive",
                preferred_language="en",
                last_active_at="2026-01-15T10:00:00",
                interaction_increment=1,
            )

            # This must not raise TypeError / ValueError.
            context = build_sales_context(
                store=store,
                client_id="client-naive",
                channel_id="telegram:99",
                thread_id="main",
                query="hello",
            )
            self.assertIn("days_since_last_active", context)

    def test_days_since_last_active_handles_aware_timestamp(self) -> None:
        """Aware ISO timestamps (with +00:00) should also work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.upsert_client_profile(
                "client-aware",
                preferred_language="en",
                last_active_at="2026-01-15T10:00:00+00:00",
                interaction_increment=1,
            )

            context = build_sales_context(
                store=store,
                client_id="client-aware",
                channel_id="telegram:99",
                thread_id="main",
                query="hello",
            )
            self.assertIn("days_since_last_active", context)

    def test_personal_facts_persisted_via_assistant_profile_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-pf",
                channel_id="telegram:1",
                thread_id="main",
                user_text="我老婆下个月预产期。",
                assistant_text="恭喜！",
                assistant_profile_update=ClientProfileUpdate(
                    personal_facts=["wife expecting next month"],
                ),
            )

            profile = store.get_client_profile("client-pf")
            self.assertIn("wife expecting next month", profile.personal_facts)

            context = build_sales_context(
                store=store,
                client_id="client-pf",
                channel_id="telegram:1",
                thread_id="main",
                query="hello",
            )
            self.assertIn("wife expecting next month", context)

    def test_personal_facts_rementioned_refreshes_recency(self) -> None:
        """Re-mentioning a fact should move it to the end so it survives the 20-item cap."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            # Seed 20 facts.
            initial_facts = [f"fact-{i}" for i in range(20)]
            store.upsert_client_profile(
                "client-cap",
                personal_facts=initial_facts,
            )
            profile = store.get_client_profile("client-cap")
            self.assertEqual(len(profile.personal_facts), 20)

            # Re-mention fact-0 and add a brand-new fact.
            store.upsert_client_profile(
                "client-cap",
                personal_facts=["fact-0", "brand-new"],
            )
            profile = store.get_client_profile("client-cap")
            self.assertEqual(len(profile.personal_facts), 20)
            self.assertIn("fact-0", profile.personal_facts)
            self.assertIn("brand-new", profile.personal_facts)
            # fact-1 should be evicted (oldest unrementioned).
            self.assertNotIn("fact-1", profile.personal_facts)
            # fact-0 should be near the end (refreshed recency).
            self.assertGreater(
                profile.personal_facts.index("fact-0"),
                profile.personal_facts.index("fact-2"),
            )

    def test_emotional_trend_and_stress_level_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_sales_interaction(
                store=store,
                client_id="client-emo",
                channel_id="telegram:1",
                thread_id="main",
                user_text="最近太难做了。",
                assistant_text="确实难。",
                assistant_profile_update=ClientProfileUpdate(
                    emotional_trend="declining",
                    stress_level="high",
                ),
            )

            profile = store.get_client_profile("client-emo")
            self.assertEqual(profile.emotional_trend, "declining")
            self.assertEqual(profile.stress_level, "high")

            context = build_sales_context(
                store=store,
                client_id="client-emo",
                channel_id="telegram:1",
                thread_id="main",
                query="hello",
            )
            self.assertIn("emotional_trend: declining", context)
            self.assertIn("stress_level: high", context)

    def test_trading_artifact_requires_research_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            with self.assertRaises(sqlite3.IntegrityError):
                store.publish_trading_artifact(
                    artifact_type="recommendation",
                    title="无来源策略",
                    summary="缺少研究来源。",
                    rationale_markdown="这应该失败。",
                    research_artifact_id=999,
                    signal={"instrument": "SPX", "action": "sell"},
                    confidence=0.4,
                    tags=["equities"],
                    metadata={},
                )


if __name__ == "__main__":
    unittest.main()
