from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.delivery.relay_eval import (
    fetch_candidate_telemetry,
    load_relay_events,
    summarize_relay_events,
)
from analyst.storage import SQLiteEngineStore


class RelayEvalParsingTest(unittest.TestCase):
    def test_load_relay_events_supports_jsonl_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "relay.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"event_type": "meta", "bot_b_id": 42}),
                        json.dumps({"event_type": "turn", "turn": 1, "direction": "A→B", "text": "hello", "recorded_at": "2026-03-19T13:00:00+00:00"}),
                        json.dumps({"event_type": "turn", "turn": 2, "direction": "B→A", "text": "hi", "recorded_at": "2026-03-19T13:00:03+00:00"}),
                    ]
                ),
                encoding="utf-8",
            )
            events = load_relay_events(path)

        self.assertEqual(events[0]["event_type"], "meta")
        self.assertEqual(events[1]["direction"], "A→B")

    def test_summarize_relay_events_counts_lengths_and_bursts(self) -> None:
        events = [
            {"event_type": "meta", "bot_b_id": 42},
            {"event_type": "turn", "turn": 1, "direction": "A→B", "text": "我刚到家", "recorded_at": "2026-03-19T13:00:00+00:00"},
            {"event_type": "turn", "turn": 2, "direction": "B→A", "text": "嗯", "recorded_at": "2026-03-19T13:00:02+00:00"},
            {"event_type": "turn", "turn": 3, "direction": "B→A", "text": "再说一句", "recorded_at": "2026-03-19T13:00:04+00:00"},
            {"event_type": "turn", "turn": 4, "direction": "A→B", "text": "先瘫五分钟再说", "recorded_at": "2026-03-19T13:00:06+00:00"},
        ]

        summary = summarize_relay_events(events)

        self.assertEqual(summary["A"]["turns"], 2)
        self.assertEqual(summary["B"]["turns"], 2)
        self.assertEqual(summary["b_multi_turn_bursts"], 1)
        self.assertGreater(summary["A"]["avg_length"], 0)


class RelayEvalTelemetryTest(unittest.TestCase):
    def test_fetch_candidate_telemetry_reads_reply_selection_and_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "engine.db")
            store.record_user_interaction(
                client_id="42",
                channel="telegram:42",
                thread_id="main",
                user_text="hi",
                assistant_text="我刚到家",
                tool_audit=[
                    {
                        "telemetry_kind": "reply_candidate",
                        "slot_id": "A",
                        "score": 1.6,
                        "reasons": ["short_fit"],
                        "text": "我刚到家",
                        "selected": True,
                    },
                    {
                        "telemetry_kind": "reply_selection",
                        "selected_slot": "A",
                        "selected_score": 1.6,
                        "selection_summary": "A:1.60:short_fit | B:0.00:none | C:-1.00:too_long",
                    },
                ],
                profile_updates={},
            )

            telemetry = fetch_candidate_telemetry(
                db_path=Path(td) / "engine.db",
                client_id="42",
            )

        self.assertEqual(telemetry["selection_count"], 1)
        self.assertEqual(telemetry["selected_slot_counts"]["A"], 1)
        self.assertEqual(telemetry["reason_counts"]["short_fit"], 1)


if __name__ == "__main__":
    unittest.main()
