from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from analyst.env import get_env_value
from .relay_scenarios import RELAY_SCENARIOS, RelayScenario, resolve_relay_scenario

_STEERING_TOKENS = ("可以", "应该", "先", "记得", "最好", "不如", "建议")


def build_default_transcript_path(scenario: RelayScenario, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return Path(f"relay_eval_{stamp}_{scenario.name}.jsonl")


def load_relay_events(path: str | Path) -> list[dict[str, Any]]:
    resolved = Path(path).expanduser()
    events: list[dict[str, Any]] = []
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("{"):
            payload = json.loads(line)
            if isinstance(payload, dict):
                events.append(payload)
            continue
        match = re.search(
            r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] __main__: Turn (?P<turn>\d+) \((?P<direction>A→B|B→A)\): (?P<text>.*)",
            line,
        )
        if match:
            events.append(
                {
                    "event_type": "turn",
                    "turn": int(match.group("turn")),
                    "direction": match.group("direction"),
                    "text": match.group("text"),
                    "recorded_at": match.group("ts").replace(" ", "T") + "+00:00",
                }
            )
            continue
        ready = re.search(
            r"Relay ready — Bot A: (?P<a_raw>.+) \((?P<a_id>\d+)\), Bot B: (?P<b_raw>.+) \((?P<b_id>\d+)\)",
            line,
        )
        if ready:
            events.append(
                {
                    "event_type": "meta",
                    "bot_a_raw": ready.group("a_raw"),
                    "bot_b_raw": ready.group("b_raw"),
                    "bot_a_id": int(ready.group("a_id")),
                    "bot_b_id": int(ready.group("b_id")),
                }
            )
            continue
        seed = re.search(r"Sending seed to Bot A: (?P<seed>.*)", line)
        if seed:
            events.append({"event_type": "seed", "text": seed.group("seed")})
    return events


def summarize_relay_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [event for event in events if event.get("event_type") == "turn"]
    meta = next((event for event in events if event.get("event_type") == "meta"), {})

    def _direction_summary(direction: str) -> dict[str, Any]:
        messages = [str(event.get("text", "")) for event in turns if event.get("direction") == direction]
        if not messages:
            return {"turns": 0}
        lengths = [len(msg) for msg in messages]
        return {
            "turns": len(messages),
            "avg_length": round(sum(lengths) / len(lengths), 2),
            "max_length": max(lengths),
            "queshi_count": sum("确实" in msg for msg in messages),
            "question_end_count": sum(msg.endswith(("?", "？")) for msg in messages),
            "self_ref_count": sum(("我" in msg) or msg.lower().startswith("i ") for msg in messages),
            "steering_like_count": sum(any(token in msg for token in _STEERING_TOKENS) for msg in messages),
            "messages": messages,
        }

    b_bursts = 0
    previous_direction = ""
    current_burst = 0
    for event in turns:
        direction = str(event.get("direction", ""))
        if direction == "B→A":
            current_burst = current_burst + 1 if previous_direction == "B→A" else 1
        else:
            if current_burst >= 2:
                b_bursts += 1
            current_burst = 0
        previous_direction = direction
    if current_burst >= 2:
        b_bursts += 1

    return {
        "meta": meta,
        "turn_count": len(turns),
        "A": _direction_summary("A→B"),
        "B": _direction_summary("B→A"),
        "b_multi_turn_bursts": b_bursts,
    }


def fetch_candidate_telemetry(
    *,
    db_path: str | Path,
    client_id: str,
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    connection = sqlite3.connect(str(Path(db_path).expanduser()))
    connection.row_factory = sqlite3.Row
    conditions = ["client_id = ?", "role = 'assistant'"]
    params: list[Any] = [client_id]
    if since:
        conditions.append("created_at >= ?")
        params.append(since)
    if until:
        conditions.append("created_at <= ?")
        params.append(until)
    rows = connection.execute(
        f"""
        SELECT content, metadata_json, created_at
        FROM conversation_messages
        WHERE {' AND '.join(conditions)}
        ORDER BY id ASC
        """
        ,
        params,
    ).fetchall()
    selection_rows: list[dict[str, Any]] = []
    slot_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        tool_audit = metadata.get("tool_audit", [])
        selection = next((item for item in tool_audit if item.get("telemetry_kind") == "reply_selection"), None)
        candidates = [item for item in tool_audit if item.get("telemetry_kind") == "reply_candidate"]
        if selection is None:
            continue
        slot = str(selection.get("selected_slot", ""))
        if slot:
            slot_counts[slot] += 1
        for candidate in candidates:
            for reason in candidate.get("reasons", []):
                reason_counts[str(reason)] += 1
        selection_rows.append(
            {
                "created_at": row["created_at"],
                "content": row["content"],
                "selection": selection,
                "candidates": candidates,
            }
        )
    connection.close()
    return {
        "selection_count": len(selection_rows),
        "selected_slot_counts": dict(slot_counts),
        "reason_counts": dict(reason_counts),
        "rows": selection_rows,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="analyst-relay-eval",
        description="Run or summarize relay-based chatbot evaluations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scenarios", help="List available relay evaluation scenarios")

    run_parser = sub.add_parser("run", help="Run a relay evaluation scenario")
    run_parser.add_argument("--scenario", default="cold_start_overtime")
    run_parser.add_argument("--seed", default="")
    run_parser.add_argument("--max-turns", type=int, default=None)
    run_parser.add_argument("--delay-min", type=float, default=1.0)
    run_parser.add_argument("--delay-max", type=float, default=3.0)
    run_parser.add_argument("--session", default=None)
    run_parser.add_argument("--bot-a", default=None)
    run_parser.add_argument("--bot-b", default=None)
    run_parser.add_argument("--transcript-file", default="")

    summarize = sub.add_parser("summarize", help="Summarize a relay transcript and optional candidate telemetry")
    summarize.add_argument("transcript_file")
    summarize.add_argument("--db-path", default="")
    summarize.add_argument("--client-id", default="")
    summarize.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _resolve_runtime_env(bot_a: str | None, bot_b: str | None, session: str | None) -> tuple[int, str, str, str, str]:
    api_id_raw = get_env_value("RELAY_API_ID")
    api_hash = get_env_value("RELAY_API_HASH")
    bot_a_raw = bot_a or get_env_value("RELAY_BOT_A_ID")
    bot_b_raw = bot_b or get_env_value("RELAY_BOT_B_ID")
    session_name = session or get_env_value("RELAY_SESSION", default="relay_session")
    missing: list[str] = []
    if not api_id_raw:
        missing.append("RELAY_API_ID")
    if not api_hash:
        missing.append("RELAY_API_HASH")
    if not bot_a_raw:
        missing.append("RELAY_BOT_A_ID (or --bot-a)")
    if not bot_b_raw:
        missing.append("RELAY_BOT_B_ID (or --bot-b)")
    if missing:
        raise SystemExit("Missing required config: " + ", ".join(missing))
    return int(api_id_raw), api_hash, bot_a_raw, bot_b_raw, session_name


def _run_command(args: argparse.Namespace) -> None:
    from .relay import run_relay

    scenario = resolve_relay_scenario(args.scenario)
    transcript = Path(args.transcript_file) if args.transcript_file else build_default_transcript_path(scenario)
    api_id, api_hash, bot_a_raw, bot_b_raw, session_name = _resolve_runtime_env(
        args.bot_a,
        args.bot_b,
        args.session,
    )
    asyncio.run(
        run_relay(
            api_id=api_id,
            api_hash=api_hash,
            session=session_name,
            bot_a_raw=bot_a_raw,
            bot_b_raw=bot_b_raw,
            seed=args.seed or scenario.seed,
            max_turns=scenario.max_turns if args.max_turns is None else args.max_turns,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            transcript_path=transcript,
            scenario_name=scenario.name,
        )
    )
    print(transcript)


def _summarize_command(args: argparse.Namespace) -> None:
    transcript_path = Path(args.transcript_file).expanduser()
    events = load_relay_events(transcript_path)
    summary = summarize_relay_events(events)
    telemetry: dict[str, Any] | None = None
    db_path = args.db_path
    meta = summary.get("meta", {})
    if db_path:
        turns = [event for event in events if event.get("event_type") == "turn"]
        if turns:
            since = turns[0].get("recorded_at", "")
            until_dt = datetime.fromisoformat(turns[-1].get("recorded_at", "").replace("Z", "+00:00"))
            until = (until_dt + timedelta(minutes=10)).isoformat()
        else:
            since = ""
            until = ""
        client_id = args.client_id or str(meta.get("bot_b_id", ""))
        if client_id:
            telemetry = fetch_candidate_telemetry(
                db_path=db_path,
                client_id=client_id,
                since=since,
                until=until,
            )
    payload = {"summary": summary, "telemetry": telemetry}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"turn_count: {summary['turn_count']}")
    print(f"A_turns: {summary['A'].get('turns', 0)}")
    print(f"B_turns: {summary['B'].get('turns', 0)}")
    print(f"A_avg_len: {summary['A'].get('avg_length', 0)}")
    print(f"A_queshi: {summary['A'].get('queshi_count', 0)}")
    print(f"A_question_end: {summary['A'].get('question_end_count', 0)}")
    print(f"A_steering_like: {summary['A'].get('steering_like_count', 0)}")
    print(f"B_multi_turn_bursts: {summary['b_multi_turn_bursts']}")
    if telemetry is not None:
        print(f"selection_count: {telemetry['selection_count']}")
        print("selected_slot_counts:", telemetry["selected_slot_counts"])
        print("reason_counts:", telemetry["reason_counts"])


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "scenarios":
        for scenario in RELAY_SCENARIOS.values():
            print(f"{scenario.name}\tturns={scenario.max_turns}\tseed={scenario.seed}\t{scenario.description}")
        return
    if args.command == "run":
        _run_command(args)
        return
    _summarize_command(args)


if __name__ == "__main__":
    main()
