from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.memory.companion_self_state import (
    RelationshipStagePolicy,
    apply_tendency_modifier,
    resolve_stage_policy,
    _clamp_disagreement,
)


class StagePolicyTest(unittest.TestCase):
    def test_resolve_stage_policy_all_stages(self) -> None:
        stranger = resolve_stage_policy("stranger")
        self.assertEqual(stranger.callback_budget, 0)
        self.assertEqual(stranger.teasing, "avoid")
        self.assertEqual(stranger.self_disclosure, "surface")
        self.assertEqual(stranger.comfort_mode, "none")
        self.assertEqual(stranger.disagreement_ceiling, "low")

        acquaintance = resolve_stage_policy("acquaintance")
        self.assertEqual(acquaintance.callback_budget, 1)
        self.assertEqual(acquaintance.teasing, "avoid")
        self.assertEqual(acquaintance.self_disclosure, "moderate")
        self.assertEqual(acquaintance.disagreement_ceiling, "soft")

        familiar = resolve_stage_policy("familiar")
        self.assertEqual(familiar.callback_budget, 2)
        self.assertEqual(familiar.teasing, "light")
        self.assertEqual(familiar.self_disclosure, "moderate-personal")
        self.assertEqual(familiar.comfort_mode, "action_only")
        self.assertEqual(familiar.disagreement_ceiling, "medium")

        close = resolve_stage_policy("close")
        self.assertEqual(close.callback_budget, 3)
        self.assertEqual(close.teasing, "encouraged")
        self.assertEqual(close.self_disclosure, "personal")
        self.assertEqual(close.disagreement_ceiling, "high")

    def test_resolve_stage_policy_unknown_defaults_stranger(self) -> None:
        policy = resolve_stage_policy("unknown_stage")
        stranger = resolve_stage_policy("stranger")
        self.assertEqual(policy, stranger)

    def test_clamp_disagreement(self) -> None:
        self.assertEqual(_clamp_disagreement("medium", "low"), "low")
        self.assertEqual(_clamp_disagreement("soft", "medium"), "soft")
        self.assertEqual(_clamp_disagreement("high", "soft"), "soft")
        self.assertEqual(_clamp_disagreement("avoid", "high"), "avoid")
        self.assertEqual(_clamp_disagreement("medium", "medium"), "medium")

    def test_apply_tendency_modifier_romantic(self) -> None:
        close = resolve_stage_policy("close")
        modified = apply_tendency_modifier(close, "romantic")
        self.assertEqual(modified.comfort_mode, "action_proximity")
        # Other fields unchanged
        self.assertEqual(modified.teasing, close.teasing)
        self.assertEqual(modified.callback_budget, close.callback_budget)

    def test_apply_tendency_modifier_confidant(self) -> None:
        acquaintance = resolve_stage_policy("acquaintance")
        modified = apply_tendency_modifier(acquaintance, "confidant")
        self.assertEqual(modified.question_budget_per_10, "2-3")
        # Other fields unchanged
        self.assertEqual(modified.teasing, acquaintance.teasing)

    def test_apply_tendency_modifier_friend_no_change(self) -> None:
        familiar = resolve_stage_policy("familiar")
        modified = apply_tendency_modifier(familiar, "friend")
        self.assertEqual(modified, familiar)

    def test_apply_tendency_modifier_romantic_no_effect_on_none_comfort(self) -> None:
        stranger = resolve_stage_policy("stranger")
        modified = apply_tendency_modifier(stranger, "romantic")
        # comfort_mode is "none", romantic doesn't upgrade it
        self.assertEqual(modified.comfort_mode, "none")


if __name__ == "__main__":
    unittest.main()
