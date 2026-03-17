"""Image decision layer — frequency control, emotional filtering, and scene coherence.

Pure-logic module: no I/O, no LLM calls. All state comes in via parameters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageDecision:
    allowed: bool
    recommended: bool
    mode: str | None = None        # "selfie" / "back_camera" / None
    scene_hint: str | None = None  # suggested scene_key
    block_reason: str | None = None


# ---------------------------------------------------------------------------
# Daily image limits per relationship stage
# ---------------------------------------------------------------------------
DAILY_LIMITS: dict[str, int] = {
    "stranger": 0,
    "acquaintance": 1,
    "familiar": 3,
    "close": 5,
}

# Minimum turns between images (per stage)
MIN_TURN_GAP: dict[str, int] = {
    "stranger": 999,
    "acquaintance": 5,
    "familiar": 3,
    "close": 3,
}

# Proactive image caps
MAX_PROACTIVE_IMAGES_PER_DAY = 1
MAX_WARMUP_IMAGES_PER_5_DAYS = 1


# ---------------------------------------------------------------------------
# Explicit image request detection
# ---------------------------------------------------------------------------
_EXPLICIT_IMAGE_PATTERNS: tuple[str, ...] = (
    "发个自拍",
    "发张自拍",
    "拍张照片",
    "拍个照",
    "让我看看",
    "看看你",
    "发张照片",
    "发你照片",
    "send me a photo",
    "send a photo",
    "send me a selfie",
    "send a selfie",
    "take a photo",
    "take a selfie",
    "穿了什么",
    "你长什么样",
    "看看自拍",
    "发照片",
    "来张自拍",
    "来个自拍",
    "给我看看",
    "show me",
    "send me a pic",
    "send a pic",
    "your photo",
    "your selfie",
    "拍一张",
)

_EXPLICIT_RE = re.compile(
    "|".join(re.escape(p) for p in _EXPLICIT_IMAGE_PATTERNS),
    re.IGNORECASE,
)


def detect_explicit_image_request(text: str) -> bool:
    """Return True if user text contains an explicit image/selfie request."""
    return bool(_EXPLICIT_RE.search(text))


# ---------------------------------------------------------------------------
# Visual scene extraction
# ---------------------------------------------------------------------------
_VISUAL_SCENE_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("coffee_table_pov", ("咖啡", "coffee", "cafe", "café", "拿铁", "latte", "cappuccino")),
    ("lunch_table_food", ("吃", "eating", "午饭", "午餐", "晚饭", "晚餐", "lunch", "dinner", "meal", "food")),
    ("home_window_view", ("下雨", "rain", "rainy", "窗外", "window")),
    ("street_walk_view", ("散步", "walk", "walking", "路上", "street")),
    ("desk_midday_pov", ("办公", "desk", "office", "working", "在干嘛")),
    ("home_window_view", ("猫", "cat", "kitty")),
)


def extract_visual_scene(text: str) -> str | None:
    """Extract a scene_key from text based on keyword matching. Returns None if no match."""
    lowered = text.lower()
    for scene_key, keywords in _VISUAL_SCENE_MAP:
        if any(kw in lowered for kw in keywords):
            return scene_key
    return None


# ---------------------------------------------------------------------------
# Scene coherence validation (Phase 3)
# ---------------------------------------------------------------------------
_LOCATION_KEYWORD_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("library_desk", ("图书馆", "library")),
    ("coffee_table_pov", ("咖啡店", "咖啡厅", "café", "cafe", "coffee shop", "starbucks")),
    ("home_window_view", ("家里", "家中", "在家", "home", "my place", "apartment")),
    ("desk_midday_pov", ("办公室", "office", "公司", "workplace")),
    ("street_walk_view", ("街上", "路上", "street", "outside", "walking")),
    ("lunch_table_food", ("餐厅", "restaurant", "食堂", "canteen", "hawker")),
    ("park_bench", ("公园", "park", "garden")),
    ("subway_commute", ("地铁", "subway", "metro", "mrt")),
    ("rainy_window", ("下雨", "rain", "rainy")),
    ("night_desk", ("深夜", "late night", "熬夜", "midnight")),
)


def validate_scene_coherence(
    reply_text: str,
    requested_scene_prompt: str,
    mode: str,
) -> tuple[bool, str | None]:
    """Check if reply_text location keywords match the requested scene.

    Returns (is_coherent, corrected_scene_key or None).
    """
    lowered_reply = reply_text.lower()
    lowered_scene = requested_scene_prompt.lower()

    matched_key: str | None = None
    for scene_key, keywords in _LOCATION_KEYWORD_MAP:
        if any(kw in lowered_reply for kw in keywords):
            matched_key = scene_key
            break

    if matched_key is None:
        # No location keywords found in reply — allow freestyle
        return True, None

    # Check if matched location is consistent with scene prompt
    for _, keywords in _LOCATION_KEYWORD_MAP:
        if any(kw in lowered_scene for kw in keywords):
            # Scene prompt has location keywords too — check if they match
            scene_match_key: str | None = None
            for sk, kws in _LOCATION_KEYWORD_MAP:
                if any(kw in lowered_scene for kw in kws):
                    scene_match_key = sk
                    break
            if scene_match_key == matched_key:
                return True, None
            # Conflict — override to reply's location
            return False, matched_key

    # Scene prompt has no location keywords — allow
    return True, None


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def should_generate_image(
    *,
    reply_text: str,
    relationship_stage: str,
    active_topic: str = "",
    topic_engagement: float = 0.0,
    stress_level: str = "",
    images_sent_today: int,
    turns_since_last_image: int,
    current_hour: int,
    is_proactive: bool = False,
    outreach_kind: str = "",
    user_text: str = "",
    proactive_images_today: int = 0,
    warmup_images_last_5_days: int = 0,
) -> ImageDecision:
    """Decide whether image generation should be allowed/recommended for this turn."""

    explicit_request = detect_explicit_image_request(user_text)

    # --- Hard blocks ---

    # Stage gate: strangers never get images
    if relationship_stage == "stranger":
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="stage_stranger",
        )

    # Daily limit
    daily_limit = DAILY_LIMITS.get(relationship_stage, 1)
    if images_sent_today >= daily_limit and not explicit_request:
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="daily_limit_reached",
        )

    # Turn gap (explicit request overrides)
    min_gap = MIN_TURN_GAP.get(relationship_stage, 5)
    if turns_since_last_image < min_gap and not explicit_request:
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="turn_gap_too_small",
        )

    # Late night block (explicit request overrides)
    if (current_hour >= 23 or current_hour < 7) and not explicit_request:
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="late_night",
        )

    # Emotional distress block (explicit request overrides)
    if (
        not explicit_request
        and active_topic in ("mood / emotional", "mood/emotional", "emotional")
        and topic_engagement > 0.5
    ):
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="emotional_distress",
        )

    # High stress block (explicit request overrides)
    if (
        not explicit_request
        and stress_level in ("high", "critical")
    ):
        return ImageDecision(
            allowed=False,
            recommended=False,
            block_reason="user_stress_high",
        )

    # Proactive frequency caps
    if is_proactive:
        if proactive_images_today >= MAX_PROACTIVE_IMAGES_PER_DAY:
            return ImageDecision(
                allowed=False,
                recommended=False,
                block_reason="proactive_daily_limit",
            )
        if outreach_kind == "warm_up_share" and warmup_images_last_5_days >= MAX_WARMUP_IMAGES_PER_5_DAYS:
            return ImageDecision(
                allowed=False,
                recommended=False,
                block_reason="warmup_5day_limit",
            )

    # --- Explicit request: always allowed past hard blocks ---
    if explicit_request:
        scene = extract_visual_scene(user_text)
        mode = "selfie"
        # Detect back_camera intent
        back_camera_keywords = ("在干嘛", "在做什么", "吃什么", "午饭", "晚饭", "咖啡", "日常", "现在",
                                "what are you eating", "what are you doing", "lunch", "dinner", "coffee")
        if any(kw in user_text.lower() for kw in back_camera_keywords):
            mode = "back_camera"
        return ImageDecision(
            allowed=True,
            recommended=True,
            mode=mode,
            scene_hint=scene,
        )

    # --- Soft recommendations ---

    # Proactive outreach hints
    if is_proactive and outreach_kind:
        if outreach_kind == "warm_up_share":
            scene = extract_visual_scene(reply_text)
            return ImageDecision(
                allowed=True,
                recommended=True,
                mode="back_camera",
                scene_hint=scene or "street_walk_view",
            )
        if outreach_kind == "stage_milestone":
            return ImageDecision(
                allowed=True,
                recommended=True,
                mode="selfie",
                scene_hint=None,
            )
        # Other proactive kinds: allow but don't recommend strongly
        scene = extract_visual_scene(reply_text)
        if scene:
            return ImageDecision(
                allowed=True,
                recommended=True,
                mode="back_camera",
                scene_hint=scene,
            )
        return ImageDecision(allowed=True, recommended=False)

    # Reply mentions a visual scene
    scene = extract_visual_scene(reply_text)
    if scene:
        return ImageDecision(
            allowed=True,
            recommended=True,
            mode="back_camera",
            scene_hint=scene,
        )

    # Default: allowed but not recommended
    return ImageDecision(allowed=True, recommended=False)
