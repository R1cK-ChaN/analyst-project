# agents/

Agent role specification registry. Only the companion role is implemented.

## Files

| File | Status | Notes |
|------|--------|-------|
| `base.py` | Active | AgentRoleSpec, RoleDependencies dataclasses |
| `companion/companion_agent.py` | Active | `build_companion_role_spec()` — assembles companion tools |
| `companion/companion_prompts.py` | Active | `build_companion_system_prompt()` — persona + web search |

No legacy files in this module.
