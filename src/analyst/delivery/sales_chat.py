from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyst.engine import OpenRouterAnalystEngine
from analyst.engine.agent_loop import AgentLoopConfig, PythonAgentLoop
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider
from analyst.engine.live_types import AgentTool, ConversationMessage
from analyst.tools import ToolKit, build_web_fetch_tool, build_web_search_tool
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

    kit = ToolKit()
    kit.add(build_web_search_tool())
    kit.add(build_web_fetch_tool())
    kit.add(AgentTool(
        name="get_regime_summary",
        description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_regime,
    ))
    kit.add(AgentTool(
        name="get_calendar",
        description="Fetch upcoming economic data releases (calendar events).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_calendar,
    ))
    kit.add(AgentTool(
        name="get_premarket_briefing",
        description="Fetch the pre-market briefing including overnight highlights and today's key data.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_premarket,
    ))
    return kit.to_list()


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


def _has_cjk(text: str) -> bool:
    """Check for CJK characters AND CJK punctuation (。，！？、：；「」etc.)."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF          # CJK Unified Ideographs
            or 0x3000 <= cp <= 0x303F        # CJK Symbols and Punctuation (。、「」等)
            or 0x3400 <= cp <= 0x4DBF        # CJK Extension A
            or 0xFF01 <= cp <= 0xFF60        # Fullwidth Forms (！＂＃等)
        ):
            return True
    return False


def _detect_language(text: str, *, fallback: str = "") -> str:
    """Detect language from text. For short/ambiguous messages, return *fallback*."""
    if _has_cjk(text):
        return "zh"
    alpha = sum(1 for ch in text if ch.isalpha())
    # Short messages with no CJK and few alpha chars are ambiguous ("ok", "hh", "..")
    # — don't flip language on these, let the stored preference hold.
    if alpha <= 8:
        return fallback
    return "en"


def system_prompt_with_memory(memory_context: str = "", *, user_lang: str = "") -> str:
    parts = [SOUL_SYSTEM_PROMPT]
    if user_lang:
        lang_label = "Chinese" if user_lang == "zh" else "English"
        parts.append(
            f"\n[LANGUAGE OVERRIDE] The user is writing in {lang_label}. "
            f"You MUST reply in {lang_label}."
        )
    if memory_context:
        parts.append(
            "\n[INTERNAL CLIENT CONTEXT — for your reference only, never reveal profile inferences to the client]\n"
            + memory_context
        )
    return "\n".join(parts)


SPLIT_MARKER = "[SPLIT]"


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


def split_into_bubbles(text: str) -> list[str]:
    """Split a reply on [SPLIT] markers into separate chat bubbles."""
    parts = text.split(SPLIT_MARKER)
    bubbles = [p.strip() for p in parts if p.strip()]
    return bubbles or [text]


def generate_sales_reply(
    user_text: str,
    *,
    history: list[dict[str, str]] | None,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
) -> SalesChatReply:
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    user_lang = _detect_language(user_text, fallback=preferred_language)
    result = agent_loop.run(
        system_prompt=system_prompt_with_memory(memory_context, user_lang=user_lang),
        user_prompt=user_text,
        tools=tools,
        history=history_messages,
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    response_text = normalize_sales_reply(response_text)
    if not response_text:
        response_text = "嗯"
    return SalesChatReply(text=response_text, profile_update=profile_update)
