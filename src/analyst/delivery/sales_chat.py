from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyst.engine import OpenRouterAnalystEngine
from analyst.engine.agent_loop import AgentLoopConfig, PythonAgentLoop
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider
from analyst.engine.live_types import AgentTool, ConversationMessage
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.memory import ClientProfileUpdate, split_reply_and_profile_update
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig
from analyst.storage import SQLiteEngineStore

from .soul import SOUL_SYSTEM_PROMPT


@dataclass(frozen=True)
class SalesChatReply:
    text: str
    profile_update: ClientProfileUpdate


def build_sales_tools(engine: OpenRouterAnalystEngine) -> list[AgentTool]:
    def get_regime(arguments: dict[str, object]) -> str:
        note = engine.get_regime_summary()
        return note.body_markdown

    def get_calendar(arguments: dict[str, object]) -> str:
        items = engine.get_calendar(limit=5)
        if not items:
            return "No upcoming calendar events."
        return "\n".join(
            f"- {item.indicator} ({item.country}) | "
            f"预期 {item.expected or '待定'} | 前值 {item.previous or '未知'} | {item.notes}"
            for item in items
        )

    def get_premarket(arguments: dict[str, object]) -> str:
        note = engine.build_premarket_briefing()
        return note.body_markdown

    return [
        AgentTool(
            name="get_regime_summary",
            description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_regime,
        ),
        AgentTool(
            name="get_calendar",
            description="Fetch upcoming economic data releases (calendar events).",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_calendar,
        ),
        AgentTool(
            name="get_premarket_briefing",
            description="Fetch the pre-market briefing including overnight highlights and today's key data.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_premarket,
        ),
    ]


def build_sales_services(
    *,
    db_path: Path | None = None,
) -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore]:
    repository = FileBackedInformationRepository()
    info_service = AnalystInformationService(repository)
    or_config = OpenRouterConfig.from_env(
        model_keys=(
            "ANALYST_TELEGRAM_OPENROUTER_MODEL",
            "ANALYST_OPENROUTER_MODEL",
            "LLM_MODEL",
        ),
        default_model="google/gemini-3.1-flash-lite-preview",
    )
    runtime = OpenRouterAgentRuntime(
        provider_config=or_config,
        config=OpenRouterRuntimeConfig(
            model_keys=(
                "ANALYST_TELEGRAM_OPENROUTER_MODEL",
                "ANALYST_OPENROUTER_MODEL",
                "LLM_MODEL",
            ),
            default_model="google/gemini-3.1-flash-lite-preview",
        ),
    )
    engine = OpenRouterAnalystEngine(info_service=info_service, runtime=runtime)
    provider = OpenRouterProvider(or_config)
    agent_loop = PythonAgentLoop(
        provider=provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
    )
    tools = build_sales_tools(engine)
    store = SQLiteEngineStore(db_path=db_path)
    return agent_loop, tools, store


def system_prompt_with_memory(memory_context: str = "") -> str:
    if not memory_context:
        return SOUL_SYSTEM_PROMPT
    return (
        f"{SOUL_SYSTEM_PROMPT}\n\n"
        "下面这段是系统整理的客户上下文，只给你内部参考，不要把画像判断直接说给客户：\n"
        f"{memory_context}"
    )


def normalize_sales_reply(text: str) -> str:
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    normalized_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        for prefix in ("# ", "## ", "### ", "#### ", "##### ", "###### "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:]
        normalized_lines.append(line)
    cleaned = "\n".join(normalized_lines).strip()
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned


def generate_sales_reply(
    user_text: str,
    *,
    history: list[dict[str, str]] | None,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    memory_context: str = "",
) -> SalesChatReply:
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    result = agent_loop.run(
        system_prompt=system_prompt_with_memory(memory_context),
        user_prompt=user_text,
        tools=tools,
        history=history_messages,
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    response_text = normalize_sales_reply(response_text)
    if not response_text:
        response_text = "嗯"
    return SalesChatReply(text=response_text, profile_update=profile_update)
