"""Tests validating Fixes 1-5 for agent not calling tools on current-events questions."""
from __future__ import annotations

import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.sales_chat import system_prompt_with_memory, build_chat_tools, resolve_chat_persona_mode
from analyst.delivery.soul import (
    COMPANION_SYSTEM_PROMPT,
    SOUL_SYSTEM_PROMPT,
    PromptAssemblyContext,
    assemble_persona_system_prompt,
)
from analyst.memory.service import _format_age, _render_delivery_history, build_sales_context
from analyst.memory import record_sales_interaction
from analyst.storage import DeliveryQueueRecord, SQLiteEngineStore


# ------------------------------------------------------------------ #
# Fix 1: Staleness warning on memory context header                   #
# ------------------------------------------------------------------ #

class Fix1StalenessWarningTest(unittest.TestCase):
    """system_prompt_with_memory must inject a staleness warning when memory_context is present."""

    def test_staleness_warning_present_when_memory_context_given(self) -> None:
        prompt = system_prompt_with_memory("sent_content: old Iran analysis")
        self.assertIn("WARNING", prompt)
        self.assertIn("PAST data", prompt)
        self.assertIn("MUST call a live tool", prompt)

    def test_no_warning_when_memory_context_empty(self) -> None:
        prompt = system_prompt_with_memory("")
        self.assertNotIn("WARNING", prompt)
        self.assertNotIn("PAST data", prompt)

    def test_warning_mentions_time_sensitive_keywords(self) -> None:
        prompt = system_prompt_with_memory("some context")
        self.assertIn("最新", prompt)
        self.assertIn("现在", prompt)
        self.assertIn("今天", prompt)


# ------------------------------------------------------------------ #
# Fix 2: Broadened system prompt tool instruction                     #
# ------------------------------------------------------------------ #

class Fix2BroadenedToolInstructionTest(unittest.TestCase):
    """SOUL_SYSTEM_PROMPT tool section must cover news/events/time-sensitive queries."""

    def test_prompt_covers_news_and_events(self) -> None:
        self.assertIn("新闻", SOUL_SYSTEM_PROMPT)
        self.assertIn("事件", SOUL_SYSTEM_PROMPT)
        self.assertIn("战争", SOUL_SYSTEM_PROMPT)
        self.assertIn("政治", SOUL_SYSTEM_PROMPT)

    def test_prompt_covers_time_keywords(self) -> None:
        self.assertIn("最新", SOUL_SYSTEM_PROMPT)
        self.assertIn("最近", SOUL_SYSTEM_PROMPT)
        self.assertIn("今天", SOUL_SYSTEM_PROMPT)
        self.assertIn("目前", SOUL_SYSTEM_PROMPT)

    def test_prompt_warns_about_sent_content_staleness(self) -> None:
        self.assertIn("sent_content", SOUL_SYSTEM_PROMPT)
        self.assertIn("过时", SOUL_SYSTEM_PROMPT)

    def test_prompt_covers_specific_website_requests(self) -> None:
        # The instruction mentions fetching data from specific sites
        self.assertIn("investing.com", SOUL_SYSTEM_PROMPT)


class PromptAssemblySelectionTest(unittest.TestCase):
    """The modular prompt assembler should stage heavy rules only when needed."""

    def test_sales_default_prompt_is_materially_smaller_than_old_monolith(self) -> None:
        self.assertLess(len(SOUL_SYSTEM_PROMPT), 4000)

    def test_companion_default_prompt_remains_small(self) -> None:
        self.assertLess(len(COMPANION_SYSTEM_PROMPT), 2500)

    def test_companion_prompt_reflects_sunny_snt_companion_identity(self) -> None:
        self.assertIn("sunny、cheerful", COMPANION_SYSTEM_PROMPT)
        self.assertIn("SnT team", COMPANION_SYSTEM_PROMPT)
        self.assertIn("Shawn Chan", COMPANION_SYSTEM_PROMPT)
        self.assertIn("不要主动聊金融", COMPANION_SYSTEM_PROMPT)

    def test_chat_mode_resolution_defaults_to_companion(self) -> None:
        self.assertEqual(resolve_chat_persona_mode(None).value, "companion")

    def test_sales_neutral_turn_does_not_load_emotional_support_module(self) -> None:
        result = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="sales", user_text="PMI 怎么看")
        )
        self.assertNotIn("sales_emotional_support", result.module_ids)

    def test_sales_stressed_turn_loads_emotional_support_module(self) -> None:
        result = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="sales", user_text="不行了 我快爆仓了 现在很焦虑")
        )
        self.assertIn("sales_emotional_support", result.module_ids)
        self.assertIn("情绪支持优先于分析", result.prompt)

    def test_profile_memory_module_only_loads_when_profile_fields_present(self) -> None:
        neutral = assemble_persona_system_prompt(PromptAssemblyContext(mode="sales", memory_context=""))
        profiled = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="sales", memory_context="- personal_facts: runs every morning")
        )
        self.assertNotIn("sales_profile_memory", neutral.module_ids)
        self.assertIn("sales_profile_memory", profiled.module_ids)

    def test_reengagement_module_loads_for_inactive_user(self) -> None:
        result = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="sales", memory_context="- days_since_last_active: 9")
        )
        self.assertIn("re_engagement", result.module_ids)
        self.assertIn("好久没聊了", result.prompt)

    def test_group_module_only_loads_for_group_context(self) -> None:
        direct = assemble_persona_system_prompt(PromptAssemblyContext(mode="sales"))
        grouped = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="sales", group_context="### group_conversation\n- A: hi")
        )
        self.assertNotIn("group_chat", direct.module_ids)
        self.assertIn("group_chat", grouped.module_ids)
        self.assertIn("GROUP CHAT MODE", grouped.prompt)

    def test_topic_state_module_loads_when_active_topic_present(self) -> None:
        result = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="companion", memory_context="- active_topic: planning / scheduling")
        )
        self.assertIn("topic_state_focus", result.module_ids)
        self.assertIn("active_topic 是当前默认焦点", result.prompt)

    def test_reminder_module_loads_for_reminder_request(self) -> None:
        result = assemble_persona_system_prompt(
            PromptAssemblyContext(mode="companion", user_text="明天下午三点提醒我喝水")
        )
        self.assertIn("companion_reminder_rules", result.module_ids)
        self.assertIn("reminder_update", result.prompt)


# ------------------------------------------------------------------ #
# Fix 3: fetch_live_calendar wired into main agent                    #
# ------------------------------------------------------------------ #

class Fix3LiveCalendarToolTest(unittest.TestCase):
    """build_chat_tools must include fetch_live_calendar when store is provided."""

    def test_fetch_live_calendar_in_tool_list_with_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            engine = _make_dummy_engine()
            tools = build_chat_tools(engine, store, persona_mode="sales")
            tool_names = [t.name for t in tools]
            self.assertIn("fetch_live_calendar", tool_names)

    def test_fetch_live_calendar_absent_without_store(self) -> None:
        engine = _make_dummy_engine()
        tools = build_chat_tools(engine, None, persona_mode="sales")
        tool_names = [t.name for t in tools]
        self.assertNotIn("fetch_live_calendar", tool_names)

    def test_get_calendar_description_mentions_cache(self) -> None:
        engine = _make_dummy_engine()
        tools = build_chat_tools(engine, None, persona_mode="sales")
        cal_tool = next((t for t in tools if t.name == "get_calendar"), None)
        self.assertIsNotNone(cal_tool)
        self.assertIn("cache", cal_tool.description.lower())

    def test_soul_prompt_documents_fetch_live_calendar(self) -> None:
        self.assertIn("fetch_live_calendar", SOUL_SYSTEM_PROMPT)


# ------------------------------------------------------------------ #
# Fix 4: Timestamps on sent_content delivery rendering                #
# ------------------------------------------------------------------ #

class Fix4FormatAgeTest(unittest.TestCase):
    """_format_age must produce human-readable relative timestamps."""

    def test_minutes_ago(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        self.assertEqual(_format_age(ts), "15m ago")

    def test_hours_ago(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(_format_age(ts), "3h ago")

    def test_yesterday(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self.assertEqual(_format_age(ts), "yesterday")

    def test_days_ago(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        self.assertEqual(_format_age(ts), "5d ago")

    def test_just_now(self) -> None:
        ts = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        self.assertEqual(_format_age(ts), "just now")

    def test_invalid_timestamp_returns_empty(self) -> None:
        self.assertEqual(_format_age("not-a-date"), "")

    def test_naive_timestamp_handled(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        result = _format_age(ts)
        self.assertIn("h ago", result)


class Fix4DeliveryRenderingTest(unittest.TestCase):
    """_render_delivery_history must prepend age labels to each line."""

    def test_delivery_lines_contain_age_prefix(self) -> None:
        from analyst.memory.render import RenderBudget

        now = datetime.now(timezone.utc)
        deliveries = [
            _make_delivery(created_at=(now - timedelta(hours=2)).isoformat(), content="Iran war update"),
            _make_delivery(created_at=(now - timedelta(days=3)).isoformat(), content="CPI analysis"),
        ]
        lines = _render_delivery_history(deliveries, limits=RenderBudget())
        self.assertIn("[2h ago]", lines[0])
        self.assertIn("[3d ago]", lines[1])

    def test_delivery_age_visible_in_full_sales_context(self) -> None:
        """Integration: build_sales_context should include age labels in sent_content."""
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            record_sales_interaction(
                store=store,
                client_id="client-a",
                channel_id="tg:1",
                thread_id="main",
                user_text="伊朗战争最新进展",
                assistant_text="这是昨天的分析。",
            )
            context = build_sales_context(
                store=store,
                client_id="client-a",
                channel_id="tg:1",
                thread_id="main",
                query="伊朗最新",
            )
            # The delivery was just created, so age should be "1m ago" or similar
            self.assertRegex(context, r"\[\d+m ago\]")


# ------------------------------------------------------------------ #
# Fix 5: Recency decay in delivery search scoring                     #
# ------------------------------------------------------------------ #

class Fix5RecencyDecayTest(unittest.TestCase):
    """search_delivery_queue must apply recency decay to keyword scores."""

    def test_recency_decay_function_values(self) -> None:
        now_ts = datetime.now(timezone.utc).isoformat()
        one_day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        three_days_ago = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()

        decay_now = SQLiteEngineStore._recency_decay(now_ts)
        decay_1d = SQLiteEngineStore._recency_decay(one_day_ago)
        decay_3d = SQLiteEngineStore._recency_decay(three_days_ago)

        # Now should be ~1.0
        self.assertAlmostEqual(decay_now, 1.0, places=1)
        # 24h ago should be ~0.5
        self.assertAlmostEqual(decay_1d, 0.5, places=1)
        # 72h ago should be ~0.125
        self.assertAlmostEqual(decay_3d, 0.125, places=1)

    def test_recency_decay_invalid_timestamp(self) -> None:
        self.assertEqual(SQLiteEngineStore._recency_decay("garbage"), 0.5)

    def test_search_prefers_recent_over_old_with_same_keywords(self) -> None:
        """Given two deliveries with identical keyword match, the newer one should score higher."""
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            now = datetime.now(timezone.utc)

            # Enqueue old delivery (3 days ago)
            _enqueue_delivery_at(
                store,
                client_id="c1",
                content="伊朗战争局势分析：最新进展",
                created_at=(now - timedelta(days=3)).isoformat(),
            )
            # Enqueue recent delivery (1 hour ago)
            _enqueue_delivery_at(
                store,
                client_id="c1",
                content="伊朗战争最新动态速报",
                created_at=(now - timedelta(hours=1)).isoformat(),
            )

            results = store.search_delivery_queue(
                client_id="c1",
                query="伊朗战争",
                limit=2,
            )
            self.assertEqual(len(results), 2)
            # The newer one should be ranked first
            newer_idx = next(i for i, r in enumerate(results) if "速报" in r.content_rendered)
            older_idx = next(i for i, r in enumerate(results) if "局势" in r.content_rendered)
            self.assertLess(newer_idx, older_idx, "Recent delivery should rank higher than old one")

    def test_very_old_delivery_may_be_excluded_by_low_score(self) -> None:
        """A very old delivery with marginal keyword match should get a near-zero score."""
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            now = datetime.now(timezone.utc)

            # Fresh delivery with strong match
            _enqueue_delivery_at(
                store,
                client_id="c1",
                content="CPI 数据 CPI 分析 CPI 预期",
                created_at=(now - timedelta(hours=1)).isoformat(),
            )
            # Ancient delivery with weak match
            _enqueue_delivery_at(
                store,
                client_id="c1",
                content="CPI 略有提及",
                created_at=(now - timedelta(days=10)).isoformat(),
            )

            results = store.search_delivery_queue(client_id="c1", query="CPI", limit=5)
            # Both should match on keyword, but the fresh one scores much higher
            if len(results) == 2:
                self.assertIn("CPI 数据", results[0].content_rendered)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_dummy_engine():
    """Create a minimal engine for build_chat_tools (no network calls)."""
    from analyst.engine import OpenRouterAnalystEngine
    from analyst.information import AnalystInformationService, FileBackedInformationRepository
    from analyst.engine.live_provider import OpenRouterConfig
    from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig

    repo = FileBackedInformationRepository()
    info = AnalystInformationService(repo)
    or_config = OpenRouterConfig(api_key="fake", model="fake")
    runtime = OpenRouterAgentRuntime(
        provider_config=or_config,
        config=OpenRouterRuntimeConfig(default_model="fake"),
        tools=[],
    )
    return OpenRouterAnalystEngine(info_service=info, runtime=runtime)


def _make_delivery(
    *,
    created_at: str,
    content: str,
    delivery_id: int = 1,
) -> DeliveryQueueRecord:
    return DeliveryQueueRecord(
        delivery_id=delivery_id,
        client_id="test",
        channel="tg:1",
        thread_id="main",
        source_type="research_artifact",
        source_artifact_id=None,
        content_rendered=content,
        status="delivered",
        delivered_at=None,
        client_reaction="",
        created_at=created_at,
    )


def _enqueue_delivery_at(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    content: str,
    created_at: str,
) -> None:
    """Enqueue a delivery and then patch its created_at via raw SQL."""
    store.enqueue_delivery(
        client_id=client_id,
        channel="tg:1",
        thread_id="main",
        source_type="research_artifact",
        source_artifact_id=None,
        content_rendered=content,
        status="delivered",
        delivered_at=None,
        metadata={},
    )
    # Patch created_at to simulate an older delivery
    import sqlite3
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "UPDATE delivery_queue SET created_at = ? WHERE content_rendered = ?",
        (created_at, content),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    unittest.main()
