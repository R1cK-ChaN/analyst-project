# engine/

LLM provider abstraction and agent loop execution.

## Files

| File | Status | Notes |
|------|--------|-------|
| `agent_loop.py` | Active | PythonAgentLoop — 6-turn agentic loop |
| `executor.py` | Active | AgentExecutor protocol (HostLoop / ClaudeCode) |
| `live_types.py` | Active | Protocol definitions (LLMProvider, ToolHandler, etc.) |
| `live_provider.py` | Active | OpenRouterProvider, ClaudeCodeProvider |
| `backends/` | Active | Provider factories & config |

No legacy files remain in this module.
