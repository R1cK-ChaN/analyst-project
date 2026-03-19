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
)
from analyst.runtime.chat import generate_chat_reply
from analyst.storage import SQLiteEngineStore


class _DummyExecutor:
    backend = ExecutorBackend.HOST_LOOP
    provider = None
    config = AgentLoopConfig(max_turns=2, max_tokens=256, temperature=0.2)
    mcp_tool_names = ()

    def __init__(self) -> None:
        self.calls: list[AgentRunRequest] = []

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        self.calls.append(request)
        prompt = request.system_prompt
        if "[CANDIDATE SLOT A]" in prompt:
            final = "累不累<profile_update>{}</profile_update>"
        elif "[CANDIDATE SLOT B]" in prompt:
            final = "又？上次不也是<profile_update>{}</profile_update>"
        elif "[CANDIDATE SLOT C]" in prompt:
            final = "听起来你今天真的很累了<profile_update>{}</profile_update>"
        else:
            final = "Treasury yields rose after the CPI surprise.<profile_update>{}</profile_update>"
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
            context, _, policy, _ = build_companion_turn_context_enrichment(
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
            _, self_state, _, callbacks = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="在工位发呆",
                history=[],
                memory_context="active_topic: work / office",
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
            _, _, _, callbacks_after = build_companion_turn_context_enrichment(
                store,
                client_id="u1",
                channel_id="telegram:1",
                thread_id="main",
                user_text="还是有点困",
                history=[{"role": "assistant", "content": "嗯"}] * 6,
                memory_context="active_topic: work / office",
                routine_state="work",
                now=datetime(2026, 3, 19, 5, 0, tzinfo=timezone.utc),
            )

        self.assertNotIn("interview on Friday", callbacks_after)


class CandidateSelectionTest(unittest.TestCase):
    def test_generate_chat_reply_prefers_medium_edge_candidate(self) -> None:
        executor = _DummyExecutor()

        reply = generate_chat_reply(
            "今天又加班到11点",
            history=[],
            agent_loop=executor,
            tools=[],
            companion_local_context=(
                "engagement_reply_length: short\n"
                "engagement_follow_up: avoid\n"
                "engagement_self_topic: soft\n"
                "engagement_disagreement: medium\n"
                "engagement_low_energy: avoid"
            ),
        )

        self.assertEqual(reply.text, "又？上次不也是")
        self.assertEqual(len(executor.calls), 3)

    def test_generate_chat_reply_skips_candidate_selection_for_live_research(self) -> None:
        executor = _DummyExecutor()

        reply = generate_chat_reply(
            "What moved Treasury yields today?",
            history=[],
            agent_loop=executor,
            tools=[],
            companion_local_context="engagement_reply_length: short",
        )

        self.assertIn("Treasury yields rose", reply.text)
        self.assertEqual(len(executor.calls), 1)


if __name__ == "__main__":
    unittest.main()
