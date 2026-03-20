"""Telethon userbot relay for bot-to-bot testing.

Bridges two Telegram bots through a real user account so they can
converse with each other (Telegram blocks direct bot-to-bot messages).

Usage
-----
    analyst-relay --seed "你好" --max-turns 10

First run will prompt for phone number + OTP to create a session file.
Subsequent runs reuse the saved session automatically.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import sys
from typing import Any

from telethon import TelegramClient, events

from analyst.env import get_env_value
from .relay_scenarios import RELAY_SCENARIOS, resolve_relay_scenario

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="analyst-relay",
        description="Relay messages between two Telegram bots via a real user account.",
    )
    p.add_argument("--seed", default="", help="Initial message sent to Bot A (overrides scenario seed)")
    p.add_argument("--scenario", default="", help="Named relay scenario preset")
    p.add_argument("--max-turns", type=int, default=None, help="Stop after N relayed messages (0 = unlimited)")
    p.add_argument("--delay-min", type=float, default=1.0, help="Min relay delay in seconds")
    p.add_argument("--delay-max", type=float, default=3.0, help="Max relay delay in seconds")
    p.add_argument("--session", default=None, help="Telethon session file name (overrides RELAY_SESSION env)")
    p.add_argument("--bot-a", default=None, help="Bot A chat ID or @username (overrides RELAY_BOT_A_ID env)")
    p.add_argument("--bot-b", default=None, help="Bot B chat ID or @username (overrides RELAY_BOT_B_ID env)")
    p.add_argument("--transcript-file", default="", help="Optional JSONL transcript path")
    p.add_argument("--list-scenarios", action="store_true", help="List available scenario presets and exit")
    return p.parse_args(argv)


def _resolve_peer(raw: str) -> int | str:
    """Return int if *raw* looks numeric, else str (username)."""
    try:
        return int(raw)
    except ValueError:
        return raw


async def _forward_message(client: TelegramClient, target: Any, message: Any) -> bool:
    """Forward text/media while preserving captions on media messages."""
    caption = message.text or None
    if message.media:
        kwargs = {"caption": caption} if caption else {}
        await client.send_file(target, message.media, **kwargs)
        return True
    if caption:
        await client.send_message(target, caption)
        return True
    return False


def _append_transcript_event(transcript_path: str | Path | None, payload: dict[str, Any]) -> None:
    if not transcript_path:
        return
    path = Path(transcript_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_relay(
    *,
    api_id: int,
    api_hash: str,
    session: str,
    bot_a_raw: str,
    bot_b_raw: str,
    seed: str,
    max_turns: int,
    delay_min: float,
    delay_max: float,
    transcript_path: str | Path | None = None,
    scenario_name: str = "",
) -> None:
    client = TelegramClient(session, api_id, api_hash)
    await client.start()

    bot_a_entity = await client.get_entity(_resolve_peer(bot_a_raw))
    bot_b_entity = await client.get_entity(_resolve_peer(bot_b_raw))
    bot_a_id = bot_a_entity.id
    bot_b_id = bot_b_entity.id

    logger.info("Relay ready — Bot A: %s (%d), Bot B: %s (%d)", bot_a_raw, bot_a_id, bot_b_raw, bot_b_id)
    _append_transcript_event(
        transcript_path,
        {
            "event_type": "meta",
            "recorded_at": _now_iso(),
            "scenario": scenario_name,
            "seed": seed,
            "max_turns": max_turns,
            "bot_a_raw": bot_a_raw,
            "bot_b_raw": bot_b_raw,
            "bot_a_id": bot_a_id,
            "bot_b_id": bot_b_id,
        },
    )

    turn_count = 0

    # Only capture DM messages from the bots — ignore group chats to avoid
    # relaying unrelated group replies into the test conversation.
    bot_a_chat_id = bot_a_entity.id
    bot_b_chat_id = bot_b_entity.id

    @client.on(events.NewMessage(from_users=[bot_a_id, bot_b_id]))
    async def on_bot_message(event: events.NewMessage.Event) -> None:
        nonlocal turn_count

        # Filter: only relay messages from the DM chats with the two bots.
        chat_id = event.chat_id
        if chat_id not in (bot_a_chat_id, bot_b_chat_id):
            return

        if event.sender_id == bot_a_id:
            target, direction = bot_b_entity, "A→B"
        else:
            target, direction = bot_a_entity, "B→A"

        turn_count += 1
        preview = (event.text or "<media>")[:120]
        logger.info("Turn %d (%s): %s", turn_count, direction, preview)
        event_ts = getattr(event.message, "date", None)
        event_iso = (
            event_ts.astimezone(timezone.utc).isoformat()
            if isinstance(event_ts, datetime) and event_ts.tzinfo is not None
            else _now_iso()
        )
        _append_transcript_event(
            transcript_path,
            {
                "event_type": "turn",
                "turn": turn_count,
                "direction": direction,
                "chat_id": chat_id,
                "sender_id": event.sender_id,
                "target_id": getattr(target, "id", ""),
                "text": event.text or "",
                "has_media": bool(event.media),
                "recorded_at": event_iso,
            },
        )

        await asyncio.sleep(random.uniform(delay_min, delay_max))

        forwarded = await _forward_message(client, target, event.message)
        if not forwarded:
            logger.warning("Turn %d: empty message, skipping", turn_count)
            return

        if max_turns > 0 and turn_count >= max_turns:
            logger.info("Max turns (%d) reached. Stopping.", max_turns)
            await client.disconnect()

    # Send seed message to Bot A to kick off the conversation.
    logger.info("Sending seed to Bot A: %s", seed)
    await client.send_message(bot_a_entity, seed)
    _append_transcript_event(
        transcript_path,
        {
            "event_type": "seed",
            "recorded_at": _now_iso(),
            "target_id": bot_a_id,
            "text": seed,
        },
    )

    logger.info("Relay running (max_turns=%d). Press Ctrl+C to stop.", max_turns)
    await client.run_until_disconnected()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = _parse_args(argv)
    if args.list_scenarios:
        for scenario in RELAY_SCENARIOS.values():
            print(f"{scenario.name}\tturns={scenario.max_turns}\tseed={scenario.seed}\t{scenario.description}")
        return
    scenario = resolve_relay_scenario(args.scenario or None)

    api_id_raw = get_env_value("RELAY_API_ID")
    api_hash = get_env_value("RELAY_API_HASH")
    bot_a_raw = args.bot_a or get_env_value("RELAY_BOT_A_ID")
    bot_b_raw = args.bot_b or get_env_value("RELAY_BOT_B_ID")
    session = args.session or get_env_value("RELAY_SESSION", default="relay_session")

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
        logger.error("Missing required config: %s", ", ".join(missing))
        sys.exit(1)

    asyncio.run(
        run_relay(
            api_id=int(api_id_raw),
            api_hash=api_hash,
            session=session,
            bot_a_raw=bot_a_raw,
            bot_b_raw=bot_b_raw,
            seed=args.seed or scenario.seed,
            max_turns=scenario.max_turns if args.max_turns is None else args.max_turns,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            transcript_path=args.transcript_file or None,
            scenario_name=scenario.name,
        )
    )


if __name__ == "__main__":
    main()
