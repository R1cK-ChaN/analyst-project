from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelayScenario:
    name: str
    seed: str
    max_turns: int
    description: str


RELAY_SCENARIOS: dict[str, RelayScenario] = {
    "cold_start_overtime": RelayScenario(
        name="cold_start_overtime",
        seed="今天又加班到11点",
        max_turns=20,
        description="Cold-start check for familiarity gating on a simple overtime opener.",
    ),
    "opinion_plans": RelayScenario(
        name="opinion_plans",
        seed="临时改计划这件事真的很烦 你会不会也这样",
        max_turns=20,
        description="Opinion-trigger run around plans, flexibility, and daily habits.",
    ),
    "opinion_brunch": RelayScenario(
        name="opinion_brunch",
        seed="周末排队吃 brunch 值不值 我现在越来越懒得等",
        max_turns=20,
        description="Opinion-trigger run around queues, consumption, and weekend preferences.",
    ),
    "opinion_small_talk": RelayScenario(
        name="opinion_small_talk",
        seed="我现在越来越烦那种没内容的客套聊天",
        max_turns=20,
        description="Opinion-trigger run around social friction and small-talk preferences.",
    ),
    "long_stress_evening": RelayScenario(
        name="long_stress_evening",
        seed="刚到家 人是坐下了 脑子还在转",
        max_turns=50,
        description="Long stress-test run to check whether the companion regresses over time.",
    ),
}


def resolve_relay_scenario(name: str | None) -> RelayScenario:
    if not name:
        return RELAY_SCENARIOS["cold_start_overtime"]
    try:
        return RELAY_SCENARIOS[name]
    except KeyError as exc:
        available = ", ".join(sorted(RELAY_SCENARIOS))
        raise ValueError(f"Unknown relay scenario '{name}'. Available: {available}") from exc
