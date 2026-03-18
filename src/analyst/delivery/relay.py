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
import logging
import random
import sys

from telethon import TelegramClient, events

from analyst.env import get_env_value

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="analyst-relay",
        description="Relay messages between two Telegram bots via a real user account.",
    )
    p.add_argument("--seed", default="你好", help="Initial message sent to Bot A (default: 你好)")
    p.add_argument("--max-turns", type=int, default=20, help="Stop after N relayed messages (0 = unlimited)")
    p.add_argument("--delay-min", type=float, default=1.0, help="Min relay delay in seconds")
    p.add_argument("--delay-max", type=float, default=3.0, help="Max relay delay in seconds")
    p.add_argument("--session", default=None, help="Telethon session file name (overrides RELAY_SESSION env)")
    p.add_argument("--bot-a", default=None, help="Bot A chat ID or @username (overrides RELAY_BOT_A_ID env)")
    p.add_argument("--bot-b", default=None, help="Bot B chat ID or @username (overrides RELAY_BOT_B_ID env)")
    return p.parse_args(argv)


def _resolve_peer(raw: str) -> int | str:
    """Return int if *raw* looks numeric, else str (username)."""
    try:
        return int(raw)
    except ValueError:
        return raw


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
) -> None:
    client = TelegramClient(session, api_id, api_hash)
    await client.start()

    bot_a_entity = await client.get_entity(_resolve_peer(bot_a_raw))
    bot_b_entity = await client.get_entity(_resolve_peer(bot_b_raw))
    bot_a_id = bot_a_entity.id
    bot_b_id = bot_b_entity.id

    logger.info("Relay ready — Bot A: %s (%d), Bot B: %s (%d)", bot_a_raw, bot_a_id, bot_b_raw, bot_b_id)

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

        await asyncio.sleep(random.uniform(delay_min, delay_max))

        if event.message.text:
            await client.send_message(target, event.message.text)
        elif event.message.media:
            await client.send_file(target, event.message.media)
        else:
            logger.warning("Turn %d: empty message, skipping", turn_count)
            return

        if max_turns > 0 and turn_count >= max_turns:
            logger.info("Max turns (%d) reached. Stopping.", max_turns)
            await client.disconnect()

    # Send seed message to Bot A to kick off the conversation.
    logger.info("Sending seed to Bot A: %s", seed)
    await client.send_message(bot_a_entity, seed)

    logger.info("Relay running (max_turns=%d). Press Ctrl+C to stop.", max_turns)
    await client.run_until_disconnected()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = _parse_args(argv)

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
            seed=args.seed,
            max_turns=args.max_turns,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
        )
    )


if __name__ == "__main__":
    main()
