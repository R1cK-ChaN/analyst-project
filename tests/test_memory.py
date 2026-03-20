from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.memory import (
    ClientProfileUpdate,
    build_chat_context,
    build_group_chat_context,
    build_user_context,
    record_chat_interaction,
    record_user_interaction,
    refresh_group_member_public_inference,
)
from analyst.storage import SQLiteEngineStore


class MemoryPipelineTest(unittest.TestCase):
    def test_user_context_is_isolated_by_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_user_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                user_text="请简单一点，我最近主要看 BTC 和 Fed。",
                assistant_text="好的，我会更简洁，并优先关注加密和联储。",
            )
            record_user_interaction(
                store=store,
                client_id="client-b",
                channel_id="telegram:2",
                thread_id="main",
                user_text="我更关注 A股 的长线配置。",
                assistant_text="收到，我会优先按 A 股和中长期配置来解释。",
            )

            context_a = build_user_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="比特币今晚怎么看？",
            )
            context_b = build_user_context(
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

    def test_user_context_uses_delivery_queue_not_raw_research_artifacts(self) -> None:
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

            context_a = build_user_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="今晚 CPI 怎么看？",
            )
            context_b = build_user_context(
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

            record_user_interaction(
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

    def test_record_user_interaction_updates_structured_client_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_user_interaction(
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

            record_user_interaction(
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

            record_user_interaction(
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

            record_user_interaction(
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

            context = build_user_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="main",
                query="港股今天怎么看？",
            )
            self.assertIn("institution_type: hedge_fund", context)
            self.assertIn("hk_equities", context)
            self.assertIn("current_mood: anxious", context)

    def test_user_context_uses_delivery_history_for_future_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_user_interaction(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-1",
                user_text="我重点看 Fed 和利率，帮我之后都说得简洁一点。",
                assistant_text="收到，后续会优先按联储和利率主线，并尽量简洁。",
            )

            context = build_user_context(
                store=store,
                client_id="client-a",
                channel_id="telegram:1",
                thread_id="thread-2",
                query="Fed 今晚怎么解读？",
            )

            self.assertIn("联储和利率主线", context)

    def test_companion_context_hides_finance_profile_and_delivery_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_chat_interaction(
                store=store,
                client_id="client-companion",
                channel_id="telegram:1",
                thread_id="main",
                user_text="我最近主要看 BTC 和 Fed，但今天有点累。",
                assistant_text="那你今晚先早点休息。",
                assistant_profile_update=ClientProfileUpdate(
                    institution_type="hedge_fund",
                    watchlist_topics=["crypto", "fed"],
                    current_mood="tired",
                    personal_facts=["likes late night walks"],
                    confidence="medium",
                ),
                persona_mode="companion",
            )

            context = build_chat_context(
                store=store,
                client_id="client-companion",
                channel_id="telegram:1",
                thread_id="main",
                query="睡不着",
                persona_mode="companion",
            )

            self.assertIn("current_mood: tired", context)
            self.assertIn("likes late night walks", context)
            self.assertNotIn("institution_type", context)
            self.assertNotIn("watchlist_topics", context)
            self.assertNotIn("sent_content", context)

    def test_companion_interaction_filters_finance_dimensions_from_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_chat_interaction(
                store=store,
                client_id="client-companion",
                channel_id="telegram:1",
                thread_id="main",
                user_text="请简单一点，我最近主要看 BTC 和 Fed。",
                assistant_text="行，那我就少说点。",
                assistant_profile_update=ClientProfileUpdate(
                    institution_type="hedge_fund",
                    watchlist_topics=["crypto", "fed"],
                    response_style="concise",
                    confidence="medium",
                ),
                persona_mode="companion",
            )

            profile = store.get_client_profile("client-companion")
            self.assertEqual(profile.preferred_language, "zh")
            self.assertEqual(profile.response_style, "concise")
            self.assertEqual(profile.confidence, "medium")
            self.assertEqual(profile.institution_type, "")
            self.assertEqual(profile.watchlist_topics, [])

    def test_topic_state_prefers_current_planning_turn_over_old_meal_topic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            record_chat_interaction(
                store=store,
                client_id="client-companion",
                channel_id="telegram:1",
                thread_id="main",
                user_text="你晚饭吃了什么？",
                assistant_text="我刚吃了 char siu rice。",
                persona_mode="companion",
            )

            context = build_chat_context(
                store=store,
                client_id="client-companion",
                channel_id="telegram:1",
                thread_id="main",
                query="我们明天要不要见面？",
                current_user_text="我们明天要不要见面？",
                persona_mode="companion",
            )

            self.assertIn("### topic_state", context)
            self.assertIn("active_topic: planning / scheduling", context)
            self.assertIn("reply_focus: 我们明天要不要见面？", context)
            self.assertIn("cooling_topics: meal / food", context)

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
            context = build_user_context(
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

            context = build_user_context(
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

            record_user_interaction(
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

            context = build_user_context(
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

            record_user_interaction(
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

            context = build_user_context(
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


class GroupMemoryTest(unittest.TestCase):
    """Tests for the group chat memory and public inference system."""

    def test_group_messages_persist_and_list_chronologically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.append_group_message(group_id="grp-1", thread_id="main", user_id="u1", display_name="Alice", content="今晚吃啥")
            store.append_group_message(group_id="grp-1", thread_id="main", user_id="u2", display_name="Bob", content="我刚下班")
            store.append_group_message(group_id="grp-1", thread_id="main", user_id="u1", display_name="Alice", content="走 撸串去")

            messages = store.list_group_messages("grp-1", "main", limit=10)
            self.assertEqual(len(messages), 3)
            # Chronological order
            self.assertEqual(messages[0].display_name, "Alice")
            self.assertEqual(messages[0].content, "今晚吃啥")
            self.assertEqual(messages[2].content, "走 撸串去")

    def test_group_messages_isolated_by_group_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.append_group_message(group_id="grp-1", thread_id="main", user_id="u1", display_name="Alice", content="Group 1 msg")
            store.append_group_message(group_id="grp-2", thread_id="main", user_id="u1", display_name="Alice", content="Group 2 msg")

            msgs_1 = store.list_group_messages("grp-1", "main")
            msgs_2 = store.list_group_messages("grp-2", "main")
            self.assertEqual(len(msgs_1), 1)
            self.assertEqual(len(msgs_2), 1)
            self.assertEqual(msgs_1[0].content, "Group 1 msg")
            self.assertEqual(msgs_2[0].content, "Group 2 msg")

    def test_group_member_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.upsert_group_member(group_id="grp-1", user_id="u1", display_name="Alice")
            store.upsert_group_member(group_id="grp-1", user_id="u2", display_name="Bob")
            store.upsert_group_member(group_id="grp-1", user_id="u1", display_name="Alice")  # second message

            members = store.list_group_members("grp-1")
            self.assertEqual(len(members), 2)
            alice = next(m for m in members if m.user_id == "u1")
            self.assertEqual(alice.message_count, 2)
            self.assertEqual(alice.display_name, "Alice")

    def test_group_profile_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.upsert_group_profile(group_id="grp-1", group_name="投研群", member_count=5)
            profile = store.get_group_profile("grp-1")
            self.assertEqual(profile.group_name, "投研群")
            self.assertEqual(profile.member_count, 5)

            # Update name, keep member count
            store.upsert_group_profile(group_id="grp-1", group_name="宏观讨论群")
            profile = store.get_group_profile("grp-1")
            self.assertEqual(profile.group_name, "宏观讨论群")
            self.assertEqual(profile.member_count, 5)

    def test_group_chat_context_includes_roles_and_social_graph(self) -> None:
        """build_group_chat_context should include public-only role and relationship hints."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            # Set up speaker's user memory (from private chat)
            record_user_interaction(
                store=store,
                client_id="u1",
                channel_id="telegram:private",
                thread_id="main",
                user_text="我最近失恋了",
                assistant_text="那先别想太多",
                assistant_profile_update=ClientProfileUpdate(
                    current_mood="sad",
                    personal_facts=["recently went through a breakup"],
                ),
            )

            # Set up group messages
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="u2",
                display_name="Bob",
                content="Alice 今天市场怎么样？",
            )
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="u1",
                display_name="Alice",
                content="Bob 哈哈最近心情不好",
            )

            # Track members
            store.upsert_group_member(group_id="grp-1", user_id="u1", display_name="Alice")
            store.upsert_group_member(group_id="grp-1", user_id="u2", display_name="Bob")

            context = build_group_chat_context(
                store=store,
                group_id="grp-1",
                thread_id="main",
                speaker_user_id="u1",
            )

            # Layer 1: Group conversation should be present
            self.assertIn("group_conversation", context)
            self.assertIn("今天市场怎么样", context)
            self.assertIn("心情不好", context)

            # Layer 2: Speaker memory should be present (from private interaction)
            self.assertIn("speaker_memory", context)
            self.assertIn("current_mood: sad", context)
            self.assertIn("recently went through a breakup", context)

            # Layer 3+: Participant model and public inference should be present
            self.assertIn("group_participants", context)
            self.assertIn("group_roles", context)
            self.assertIn("group_social_graph", context)
            self.assertIn("Alice", context)
            self.assertIn("Bob", context)
            self.assertIn("(current speaker)", context)
            self.assertIn("Alice <-> Bob", context)
            self.assertIn("tone seems playful", context)
            self.assertNotIn("closely connected", context)

    def test_refresh_group_member_public_inference_updates_cache_without_bumping_message_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            def add_public_message(user_id: str, display_name: str, content: str) -> None:
                store.append_group_message(
                    group_id="grp-1",
                    thread_id="main",
                    user_id=user_id,
                    display_name=display_name,
                    content=content,
                )
                store.upsert_group_member(group_id="grp-1", user_id=user_id, display_name=display_name)

            add_public_message("u1", "Alice", "Bob can you send status?")
            add_public_message("u1", "Alice", "Charlie can you send yours too?")
            add_public_message("u2", "Bob", "not yet")
            add_public_message("u1", "Alice", "let's wrap this soon")
            add_public_message("u3", "Charlie", "haha almost there")
            add_public_message("u1", "Alice", "Bob ping me when done")
            add_public_message("u3", "Charlie", "lol okay")

            refresh_group_member_public_inference(store=store, group_id="grp-1")

            members = {member.user_id: member for member in store.list_group_members("grp-1", limit=10)}
            self.assertEqual(members["u1"].message_count, 4)
            self.assertEqual(members["u2"].message_count, 1)
            self.assertEqual(members["u3"].message_count, 2)
            self.assertEqual(members["u1"].role_in_group, "leader")
            self.assertIn("drives a lot of the chat", members["u1"].personality_notes)
            self.assertEqual(members["u3"].role_in_group, "joker")

    def test_group_social_graph_ignores_assistant_bridging_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            def add_public_message(user_id: str, display_name: str, content: str) -> None:
                store.append_group_message(
                    group_id="grp-1",
                    thread_id="main",
                    user_id=user_id,
                    display_name=display_name,
                    content=content,
                )
                store.upsert_group_member(group_id="grp-1", user_id=user_id, display_name=display_name)

            add_public_message("u1", "Alice", "Anyone around?")
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="assistant",
                display_name="陈襄",
                content="I'm here if needed.",
            )
            add_public_message("u2", "Bob", "Yep")
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="assistant",
                display_name="陈襄",
                content="Noted.",
            )
            add_public_message("u1", "Alice", "Cool")

            context = build_group_chat_context(
                store=store,
                group_id="grp-1",
                thread_id="main",
                speaker_user_id="u1",
            )

            self.assertNotIn("Alice <-> Bob", context)

    def test_group_context_does_not_leak_other_users_private_data(self) -> None:
        """Group context should only contain the SPEAKER's memory, not other members' private data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            # Bob's private chat: he shared sensitive info
            record_user_interaction(
                store=store,
                client_id="bob",
                channel_id="telegram:private-bob",
                thread_id="main",
                user_text="我老婆怀孕了",
                assistant_text="恭喜！",
                assistant_profile_update=ClientProfileUpdate(
                    personal_facts=["wife is pregnant"],
                ),
            )

            # Alice speaks in group
            store.append_group_message(group_id="grp-1", thread_id="main", user_id="alice", display_name="Alice", content="大家好")
            store.upsert_group_member(group_id="grp-1", user_id="alice", display_name="Alice")
            store.upsert_group_member(group_id="grp-1", user_id="bob", display_name="Bob")

            # Build context for Alice (the speaker)
            context = build_group_chat_context(
                store=store,
                group_id="grp-1",
                thread_id="main",
                speaker_user_id="alice",
            )

            # Bob's private info should NOT appear
            self.assertNotIn("wife is pregnant", context)
            self.assertNotIn("怀孕", context)

    def test_group_topic_state_cools_old_assistant_meal_topic_after_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")

            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="u1",
                display_name="Alice",
                content="你晚饭吃了什么？",
            )
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="assistant",
                display_name="陈襄",
                content="我刚吃了 char siu rice。",
            )
            store.append_group_message(
                group_id="grp-1",
                thread_id="main",
                user_id="u1",
                display_name="Alice",
                content="那我们明天几点碰头？",
            )
            store.upsert_group_member(group_id="grp-1", user_id="u1", display_name="Alice")

            context = build_group_chat_context(
                store=store,
                group_id="grp-1",
                thread_id="main",
                speaker_user_id="u1",
            )

            self.assertIn("### topic_state", context)
            self.assertIn("active_topic: planning / scheduling", context)
            self.assertIn("cooling_topics: meal / food", context)
            self.assertIn("topic_stack: planning / scheduling", context)
            self.assertIn("topic_stack: meal / food", context)


if __name__ == "__main__":
    unittest.main()
