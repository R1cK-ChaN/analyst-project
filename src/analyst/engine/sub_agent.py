from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .agent_loop import AgentLoopConfig, PythonAgentLoop
from .live_types import AgentTool, LLMProvider

logger = logging.getLogger(__name__)

_SUB_AGENT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "required": ["task"],
    "properties": {
        "task": {"type": "string", "description": "Clear description of what to investigate."},
        "context": {"type": "string", "description": "Optional relevant data or constraints."},
    },
}

SubAgentPromptBuilder = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    system_prompt: str
    tools: list[AgentTool]
    config: AgentLoopConfig = field(default_factory=lambda: AgentLoopConfig(max_turns=3, max_tokens=1200, temperature=0.2))
    parameters: dict[str, Any] = field(default_factory=lambda: dict(_SUB_AGENT_PARAMETERS))
    build_user_prompt: SubAgentPromptBuilder | None = None


class SubAgentHandler:
    def __init__(
        self,
        spec: SubAgentSpec,
        provider: LLMProvider,
        *,
        store: Any | None = None,
        parent_agent: str = "",
    ) -> None:
        self.spec = spec
        self.provider = provider
        self.store = store
        self.parent_agent = parent_agent

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = str(arguments.get("task", ""))
        if not task:
            return {"status": "error", "error": "Missing required 'task' argument."}

        try:
            if self.spec.build_user_prompt is not None:
                user_prompt = self.spec.build_user_prompt(arguments)
            else:
                context = str(arguments.get("context", ""))
                user_prompt_parts = [task]
                if context:
                    user_prompt_parts.append(f"\n\nAdditional context:\n{context}")
                user_prompt = "".join(user_prompt_parts)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        # Build scoped memory if store is available
        memory = ""
        scope_tags = _extract_scope_tags(task)
        if self.store is not None:
            try:
                from analyst.memory.subagent import build_subagent_memory
                memory = build_subagent_memory(self.store, scope_tags=scope_tags, parent_agent=self.spec.name)
            except Exception:
                logger.debug("Failed to build sub-agent memory", exc_info=True)

        if memory:
            user_prompt = f"{user_prompt}\n\nRelevant background:\n{memory}"
        task_id = uuid.uuid4().hex[:12]
        start = time.monotonic()

        try:
            loop = PythonAgentLoop(self.provider, self.spec.config)
            result = loop.run(
                system_prompt=self.spec.system_prompt,
                user_prompt=user_prompt,
                tools=self.spec.tools,
            )
            elapsed = time.monotonic() - start
            turns_used = 0
            for event in result.events:
                if event.event_type == "agent_end":
                    turns_used = event.payload.get("turns", 0)
            final = result.final_text.strip()
            if not final:
                final = "(sub-agent produced no output)"

            self._record_audit(task_id, task, "ok", final[:500], elapsed, scope_tags)
            return {"status": "ok", "result": final, "turns_used": turns_used}

        except Exception as exc:
            elapsed = time.monotonic() - start
            error_msg = str(exc)
            logger.warning("Sub-agent %s failed: %s", self.spec.name, error_msg)
            self._record_audit(task_id, task, "error", error_msg[:500], elapsed, scope_tags)
            return {"status": "error", "error": error_msg}

    def _record_audit(self, task_id: str, objective: str, status: str, summary: str, elapsed: float, scope_tags: list[str] | None = None) -> None:
        if self.store is None:
            return
        try:
            from analyst.memory.subagent import record_subagent_run
            record_subagent_run(
                store=self.store,
                task_id=task_id,
                parent_agent=self.parent_agent or self.spec.name,
                task_type=self.spec.name,
                objective=objective,
                scope_tags=scope_tags or [],
                result_status=status,
                summary=summary,
                elapsed_seconds=elapsed,
            )
        except Exception:
            logger.debug("Failed to record sub-agent audit", exc_info=True)


def build_sub_agent_tool(
    spec: SubAgentSpec,
    provider: LLMProvider,
    store: Any | None = None,
    *,
    parent_agent: str = "",
) -> AgentTool:
    handler = SubAgentHandler(spec, provider, store=store, parent_agent=parent_agent)
    return AgentTool(
        name=spec.name,
        description=spec.description,
        parameters=spec.parameters,
        handler=handler,
    )


def _extract_scope_tags(task: str) -> list[str]:
    """Extract keyword tags from task text using word-boundary matching."""
    keywords = [
        "cpi", "ppi", "nfp", "gdp", "pce", "fomc", "fed", "ecb", "boj",
        "inflation", "employment", "growth", "rates", "dollar", "treasury",
        "equity", "bonds", "commodities", "oil", "gold", "crypto",
        "vix", "risk", "regime", "china", "us", "eu", "japan",
    ]
    lower_task = task.lower()
    return [kw for kw in keywords if re.search(rf"\b{kw}\b", lower_task)]
