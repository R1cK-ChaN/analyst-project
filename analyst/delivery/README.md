# delivery/

Persona rendering, Telegram bot integration, and delivery logic. This is the
presentation layer of the companion agent.

## Files

| File | Status | Notes |
|------|--------|-------|
| `bot.py` | Active | Main Telegram bot entry point, message routing |
| `soul.py` | Active | Core persona prompt assembly (PromptModule system) |
| `bot_companion_timing.py` | Active | Relationship check-in scheduling |
| `bot_group_chat.py` | Active | Group chat context rendering |
| `bot_media.py` | Active | Media generation decision logic |
| `bot_history.py` | Active | Conversation history retrieval |
| `bot_constants.py` | Active | Telegram limits (message length, etc.) |
| `companion_schedule.py` | Active | Schedule update extraction/application |
| `companion_reminders.py` | Active | Reminder update extraction/application |
| `image_decision.py` | Active | When/how to generate media |
| `group_intervention.py` | Active | Group tension detection & de-escalation |
| `injection_scanner.py` | Active | Prompt injection detection |
| `outreach_dedup.py` | Active | Outreach message deduplication |
| `outreach_metrics.py` | Active | Proactive outreach metrics |
| `user_chat.py` | Active | Re-exports from runtime/chat.py for backward compat |
| `relay.py` | Testing only | Telethon userbot relay for bot-to-bot testing |
| `relay_eval.py` | Testing only | Companion relay evaluation/scoring |
| `relay_scenarios.py` | Testing only | Named test scenarios for relay |

No legacy files remain in this module.
