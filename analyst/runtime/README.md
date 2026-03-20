# runtime/

Chat orchestration and LLM execution pipeline.

## Files

| File | Status | Notes |
|------|--------|-------|
| `chat.py` | Active | Companion chat service — builds agent executor, tools, store |
| `capabilities.py` | Active | Declarative capability registry per role |
| `conversation_service.py` | Active | Conversation turn persistence & replay |
| `environment_adapter.py` | Active | CLI/Telegram input normalization |
| `platform/telegram.py` | Active | Telegram-specific message handlers |

No legacy files remain in this module.
