from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.engine import AgentRunRequest, ExecutorBackend
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.live_types import AgentLoopResult, ConversationMessage
from analyst.memory.companion_self_state import (
    build_companion_turn_context_enrichment,
    detect_used_callback,
    ensure_companion_self_state,
    mark_callback_used,
    resolve_stage_policy,
    apply_tendency_modifier,
    _clamp_disagreement,
)
from analyst.runtime.chat import generate_chat_reply
from analyst.storage import SQLiteEngineStore


class _MappedDummyExecutor:
    backend = ExecutorBackend.HOST_LOOP
    provider = None
    config = AgentLoopConfig(max_turns=2, max_tokens=256, temperature=0.2)
    mcp_tool_names = ()

    def __init__(self, *, slot_texts: dict[str, str] | None = None, fallback_text: str | None = None) -> None:
        self.calls: list[AgentRunRequest] = []
        self.slot_texts = slot_texts or {}
        self.fallback_text = fallback_text or "Treasury yields rose after the CPI surprise.<profile_update>{}</profile_update>"

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        self.calls.append(request)
        prompt = request.system_prompt
        final = self.fallback_text
        for slot_id, text in self.slot_texts.items():
            if f"[CANDIDATE SLOT {slot_id}]" in prompt:
                final = text
                break
        return AgentLoopResult(
            messages=[ConversationMessage(role="assistant", content=final)],
            final_text=final,
            events=[],
        )


class CompanionSelfStateTest(unittest.TestCase):
    def test_daily_self_state_is_stable_with_authored_internal_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            now = datetime(2026, 3, 19, 1, 15, tzinfo=timezone.utc)
            first = ensure_companion_self_state(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                now=now,
                routine_state="morning",
            )
            second = ensure_companion_self_state(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                now=now,
                routine_state="morning",
            )

        self.assertEqual(first.internal_state, second.internal_state)
        self.assertEqual(first.opinion_profile, second.opinion_profile)
        self.assertEqual(len(first.internal_state), 2)
        self.assertEqual(len(first.opinion_profile), 3)

    def test_emotion_priority_overrides_low_energy_engagement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            context, _, policy, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="i feel overwhelmed and i can't sleep",
                history=[],
                memory_context="active_topic: mood / emotional\nstress_level: high",
                routine_state="late_night",
                now=datetime(2026, 3, 19, 15, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(policy.mode, "attentive")
        self.assertIn("policy_priority: user_emotion > engagement > relationship_stage", context or "[missing]")
        self.assertIn("engagement_disagreement: avoid", context)

    def test_callback_fact_is_marked_and_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            store.upsert_client_profile(
                "u1",
                personal_facts=["interview on Friday", "cat named Mochi"],
                interaction_increment=1,
            )
            _, self_state, _, callbacks, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="在工位发呆",
                history=[],
                memory_context="relationship_stage: familiar\nactive_topic: work / office",
                routine_state="work",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
            self.assertIn("interview on Friday", callbacks)

            used = detect_used_callback(
                "对了 你那个 interview on Friday 后来怎么样",
                callbacks,
            )
            self.assertEqual(used, "interview on Friday")
            updated = mark_callback_used(store, self_state=self_state, callback_fact=used)
            store.upsert_companion_self_state(
                client_id=updated.client_id,
                channel=updated.channel,
                thread_id=updated.thread_id,
                state_date=updated.state_date,
                used_callback_facts=updated.used_callback_facts,
                last_callback_fact="",
                last_callback_at="",
            )
            _, _, _, callbacks_after, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="还是有点困",
                history=[{"role": "assistant", "content": "嗯"}] * 6,
                memory_context="relationship_stage: familiar\nactive_topic: work / office",
                routine_state="work",
                now=datetime(2026, 3, 19, 5, 0, tzinfo=timezone.utc),
            )

        self.assertNotIn("interview on Friday", callbacks_after)

    def test_callback_candidates_blocked_when_relationship_stage_is_cold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            store.upsert_client_profile(
                "u1",
                personal_facts=["interview on Friday", "cat named Mochi"],
                interaction_increment=1,
            )
            context, _, _, callbacks, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="在工位发呆",
                history=[],
                memory_context="relationship_stage: acquaintance\nactive_topic: work / office",
                routine_state="work",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(callbacks, ())
        self.assertIn("shared_history_gate: locked", context)
        self.assertIn("engagement_inference_scope: own_or_stated_only", context)


class UserDisengagementTest(unittest.TestCase):
    def test_user_disengagement_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            history = [
                {"role": "assistant", "content": "我今天看了一部电影"},
                {"role": "user", "content": "好的"},
                {"role": "assistant", "content": "是一个关于机器人的故事"},
                {"role": "user", "content": "嗯"},
                {"role": "assistant", "content": "里面有个角色特别有意思"},
                {"role": "user", "content": "ok"},
            ]
            _, _, policy, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="ok",
                history=history,
                memory_context="relationship_stage: familiar\nactive_topic: general",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("user_disengaging", policy.reasons)
        self.assertEqual(policy.follow_up_style, "topic_invite")

    def test_single_self_focus_plus_low_engagement_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            history = [
                {"role": "assistant", "content": "我今天在公司开了三个会"},
                {"role": "user", "content": "ok"},
            ]
            _, _, policy, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="ok",
                history=history,
                memory_context="relationship_stage: familiar\nactive_topic: general",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("reciprocity_redirect", policy.reasons)

    def test_consecutive_self_focus_triggers_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            history = [
                {"role": "assistant", "content": "我今天在公司开了三个会"},
                {"role": "user", "content": "哦 那挺累的"},
                {"role": "assistant", "content": "我还得加班到九点"},
                {"role": "user", "content": "那你辛苦了"},
            ]
            _, _, policy, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="那你辛苦了",
                history=history,
                memory_context="relationship_stage: familiar\nactive_topic: general",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("reciprocity_redirect", policy.reasons)

    def test_stage_policy_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            context, _, _, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="hello",
                history=[],
                memory_context="relationship_stage: stranger",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("stage_teasing: avoid", context)
        self.assertIn("stage_self_disclosure: surface", context)

    def test_stage_policy_close(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            context, _, _, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="hello",
                history=[],
                memory_context="relationship_stage: close",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("stage_teasing: encouraged", context)
        self.assertIn("stage_self_disclosure: personal", context)

    def test_disagreement_clamped_by_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            # shared_interest would normally set disagreement to medium
            # but stranger ceiling should clamp it to low
            _, _, policy, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="奶茶大多就是糖水",
                history=[],
                memory_context="relationship_stage: stranger\nactive_topic: meal / food",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(policy.disagreement_style, "low")

    def test_callback_budget_zero_for_stranger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            store.upsert_client_profile(
                "u1",
                personal_facts=["interview on Friday", "cat named Mochi"],
                interaction_increment=1,
            )
            _, _, policy, callbacks, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="hello",
                history=[],
                memory_context="relationship_stage: stranger",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(callbacks, ())
        self.assertEqual(policy.callback_style, "none")

    def test_tendency_modifier_romantic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            _, _, _, _, stage_policy = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="hello",
                history=[],
                memory_context="relationship_stage: close\ntendency_dominant: romantic",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(stage_policy.comfort_mode, "action_proximity")

    def test_generation_hint_appended_for_topic_invite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            history = [
                {"role": "assistant", "content": "我今天看了一部电影"},
                {"role": "user", "content": "好的"},
                {"role": "assistant", "content": "是一个关于机器人的故事"},
                {"role": "user", "content": "嗯"},
                {"role": "assistant", "content": "里面有个角色特别有意思"},
                {"role": "user", "content": "ok"},
            ]
            context, _, _, _, _ = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="ok",
                history=history,
                memory_context="relationship_stage: familiar\nactive_topic: general",
                now=datetime(2026, 3, 19, 4, 0, tzinfo=timezone.utc),
            )
        self.assertIn("[GENERATION HINT]", context)


class SinglePassReplyTest(unittest.TestCase):
    """Test generate_chat_reply in single-pass mode (candidate selection disabled)."""

    def test_generate_chat_reply_single_pass(self) -> None:
        executor = _MappedDummyExecutor()

        reply = generate_chat_reply(
            "今天又加班到11点",
            history=[],
            agent_loop=executor,
            tools=[],
            memory_context="relationship_stage: familiar",
            companion_local_context="engagement_reply_length: short",
        )

        # Single pass: exactly 1 LLM call
        self.assertEqual(len(executor.calls), 1)
        self.assertTrue(len(reply.text) > 0)


class ScoringFunctionTest(unittest.TestCase):
    """Unit tests for _score_candidate_reply and related scoring helpers."""

    def test_fragment_style_not_penalized(self) -> None:
        from analyst.runtime.chat import _sentence_completeness_penalty
        self.assertEqual(_sentence_completeness_penalty("嗯")[0], 0.0)
        self.assertEqual(_sentence_completeness_penalty("那也太亏了")[0], 0.0)
        self.assertEqual(_sentence_completeness_penalty("sales又不是不用开会")[0], 0.0)

    def test_formal_connector_penalized(self) -> None:
        from analyst.runtime.chat import _sentence_completeness_penalty
        penalty, reasons = _sentence_completeness_penalty("客户会议和内部协调本来就是工作的一部分")
        self.assertLess(penalty, 0)
        self.assertTrue(any("formal" in r or "explanatory" in r for r in reasons))

    def test_compound_clause_penalized(self) -> None:
        from analyst.runtime.chat import _sentence_completeness_penalty
        penalty, _ = _sentence_completeness_penalty("要是真能排上这号人物的见面，我这会儿大概就在白宫门口了")
        self.assertLess(penalty, 0)

    def test_comma_dense_penalized(self) -> None:
        from analyst.runtime.chat import _sentence_completeness_penalty
        penalty, reasons = _sentence_completeness_penalty("这几个同事在讨论下周的排期，声音大得像在吵架，听得我头疼")
        self.assertLess(penalty, 0)
        self.assertIn("comma_dense", reasons)

    def test_tool_artifact_stripping(self) -> None:
        from analyst.runtime.chat import _strip_tool_artifacts
        # research_agent XML block
        text = '<research_agent>\n{"query": "TSLA closing"}\n</research_agent>'
        self.assertEqual(_strip_tool_artifacts(text), "")
        # Mixed text + tool block
        text2 = '让我查一下 <research_agent>{"query": "TSLA"}</research_agent>'
        self.assertNotIn("research_agent", _strip_tool_artifacts(text2))
        # Generic XML tool pattern
        text3 = 'hello <some_tool>{"a": 1}</some_tool> world'
        self.assertNotIn("some_tool", _strip_tool_artifacts(text3))
        # Normal text untouched
        self.assertEqual(_strip_tool_artifacts("这么晚 还在加班"), "这么晚 还在加班")


if __name__ == "__main__":
    unittest.main()
