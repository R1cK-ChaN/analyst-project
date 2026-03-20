# memory/

Three-layer memory system: profile, relationship state, topic state.

## Files

| File | Status | Notes |
|------|--------|-------|
| `service.py` | Active | Core memory context builder (`build_chat_context`) |
| `profile.py` | Active | ClientProfileUpdate extraction/merging |
| `relationship.py` | Active | Relationship state machine (intimacy, stages, tendencies) |
| `companion_self_state.py` | Active | Companion behavioral policies by relationship stage |
| `topic_state.py` | Active | Conversation topic tracking |
| `render.py` | Active | Memory context rendering utilities |

No legacy files remain in this module.
