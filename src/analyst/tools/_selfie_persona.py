from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from analyst.env import PROJECT_ROOT, get_env_value

logger = logging.getLogger(__name__)

_DEFAULT_CHARACTER_DNA = (
    "young Chinese male",
    "mid 20s",
    "short black hair",
    "sharp jawline",
    "bright expressive eyes",
    "clean casual style",
    "warm friendly smile",
    "slim athletic build",
)

_DEFAULT_CAMERA_STYLE = (
    "phone selfie",
    "slightly wide lens",
    "natural lighting",
    "realistic smartphone photo",
    "casual everyday style",
)

_DEFAULT_QUALITY_MODIFIERS = (
    "photorealistic",
    "high detail skin texture",
    "natural shadows",
    "cinematic lighting",
)

_DEFAULT_NEGATIVE_PROMPT = (
    "old man",
    "beard",
    "bald",
    "long hair",
    "female",
    "different person",
    "cartoon",
)


@dataclass(frozen=True)
class SelfieScene:
    scene_prompt: str
    motion_prompt: str


_SCENE_CATALOG: dict[str, SelfieScene] = {
    "trading_desk": SelfieScene(
        scene_prompt=(
            "taking a selfie at a trading desk\n"
            "multiple monitors glowing\n"
            "late night work atmosphere"
        ),
        motion_prompt=(
            "holding a phone selfie at a trading desk\n"
            "multiple monitors glowing behind him\n"
            "subtle blinking and a small confident smile\n"
            "gentle handheld phone motion"
        ),
    ),
    "coffee_shop": SelfieScene(
        scene_prompt=(
            "sitting in a coffee shop\n"
            "holding a coffee cup\n"
            "window daylight"
        ),
        motion_prompt=(
            "holding a phone selfie in a coffee shop\n"
            "lifting a coffee cup slightly toward the camera\n"
            "soft blinking and a relaxed smile\n"
            "gentle handheld phone motion"
        ),
    ),
    "airport_lounge": SelfieScene(
        scene_prompt=(
            "taking a selfie in an airport lounge\n"
            "carry-on luggage nearby\n"
            "soft travel-day lighting"
        ),
        motion_prompt=(
            "holding a phone selfie in an airport lounge\n"
            "slight head turn and soft smile\n"
            "gentle handheld phone motion"
        ),
    ),
    "gym_mirror": SelfieScene(
        scene_prompt=(
            "mirror selfie in a gym\n"
            "wearing sportswear\n"
            "gym equipment background"
        ),
        motion_prompt=(
            "mirror selfie in a gym\n"
            "slight pose adjustment and natural blinking\n"
            "subtle body movement with a relaxed smile"
        ),
    ),
    "late_night_work": SelfieScene(
        scene_prompt=(
            "taking a selfie during late night work\n"
            "desk lamp glow\n"
            "quiet office atmosphere"
        ),
        motion_prompt=(
            "taking a phone selfie during late night work\n"
            "soft desk lamp glow\n"
            "small tired smile and subtle blinking\n"
            "gentle handheld phone motion"
        ),
    ),
}


@dataclass(frozen=True)
class SelfiePromptConfig:
    media_root: Path
    bootstrap_count: int = 4
    neutral_scene: SelfieScene = SelfieScene(
        scene_prompt=(
            "taking a casual phone selfie in a modern office\n"
            "soft daylight\n"
            "relaxed friendly expression"
        ),
        motion_prompt=(
            "taking a casual phone selfie in a modern office\n"
            "soft daylight\n"
            "subtle blinking and a relaxed friendly smile\n"
            "gentle handheld phone motion"
        ),
    )
    character_dna: tuple[str, ...] = _DEFAULT_CHARACTER_DNA
    camera_style: tuple[str, ...] = _DEFAULT_CAMERA_STYLE
    quality_modifiers: tuple[str, ...] = _DEFAULT_QUALITY_MODIFIERS
    negative_prompt: tuple[str, ...] = _DEFAULT_NEGATIVE_PROMPT

    @classmethod
    def from_env(cls) -> SelfiePromptConfig:
        media_root_raw = get_env_value("ANALYST_SELFIE_MEDIA_ROOT", default="")
        if media_root_raw:
            media_root = Path(media_root_raw)
        else:
            media_root = PROJECT_ROOT / ".analyst" / "media" / "persona"
        try:
            bootstrap_count = int(get_env_value("ANALYST_SELFIE_BOOTSTRAP_COUNT", default="4"))
        except ValueError:
            bootstrap_count = 4
        bootstrap_count = max(3, min(5, bootstrap_count))
        return cls(
            media_root=media_root,
            bootstrap_count=bootstrap_count,
        )


@dataclass(frozen=True)
class PersonaSelfieState:
    version: int
    character_anchor_path: str
    latest_selfie_path: str
    bootstrap_paths: list[str]
    character_dna: list[str]
    camera_style: list[str]
    quality_modifiers: list[str]
    negative_prompt: list[str]
    created_at: str
    updated_at: str
    last_prompt_used: str
    last_scene_key: str
    last_scene_prompt: str


@dataclass(frozen=True)
class GeneratedSelfie:
    image_path: str
    image_data_uri: str
    prompt_used: str
    negative_prompt: str
    scene_key: str
    scene_prompt: str
    motion_prompt: str


@dataclass(frozen=True)
class SelfiePromptDraft:
    prompt_used: str
    fallback_prompt: str
    negative_prompt: str
    scene_key: str
    scene_prompt: str
    motion_prompt: str


class SelfiePromptService:
    def __init__(self, config: SelfiePromptConfig | None = None) -> None:
        self._config = config or SelfiePromptConfig.from_env()

    def is_selfie_request(self, arguments: dict[str, Any]) -> bool:
        mode = str(arguments.get("mode", "")).strip().lower()
        if mode == "selfie":
            return True
        if any(str(arguments.get(key, "")).strip() for key in ("scene_key", "scene_prompt")):
            return True
        return False

    def generate_selfie(self, arguments: dict[str, Any], image_client: Any) -> GeneratedSelfie:
        state = self._ensure_state(image_client)
        draft = self.build_prompt_draft(arguments)
        generated = image_client.generate_image(
            prompt=draft.prompt_used,
            negative_prompt=draft.negative_prompt,
            image_input=self._build_reference_image_data_uri(state),
        )
        image_path = image_client.materialize_image(generated, self._next_selfie_path())
        updated_state = PersonaSelfieState(
            version=state.version,
            character_anchor_path=state.character_anchor_path,
            latest_selfie_path=image_path,
            bootstrap_paths=list(state.bootstrap_paths),
            character_dna=list(state.character_dna),
            camera_style=list(state.camera_style),
            quality_modifiers=list(state.quality_modifiers),
            negative_prompt=list(state.negative_prompt),
            created_at=state.created_at,
            updated_at=_now_iso(),
            last_prompt_used=draft.prompt_used,
            last_scene_key=draft.scene_key,
            last_scene_prompt=draft.scene_prompt,
        )
        self._save_state(updated_state)
        return GeneratedSelfie(
            image_path=image_path,
            image_data_uri=self._path_to_data_uri(Path(image_path)),
            prompt_used=draft.prompt_used,
            negative_prompt=draft.negative_prompt,
            scene_key=draft.scene_key,
            scene_prompt=draft.scene_prompt,
            motion_prompt=draft.motion_prompt,
        )

    @property
    def negative_prompt_text(self) -> str:
        return "\n".join(self._config.negative_prompt)

    def build_prompt_draft(self, arguments: dict[str, Any]) -> SelfiePromptDraft:
        scene_key, scene_prompt, motion_prompt = self._resolve_scene(arguments)
        return SelfiePromptDraft(
            prompt_used=self._assemble_prompt(scene_prompt, include_character_dna=True),
            fallback_prompt=self._assemble_prompt(scene_prompt, include_character_dna=False),
            negative_prompt=self.negative_prompt_text,
            scene_key=scene_key,
            scene_prompt=scene_prompt,
            motion_prompt=motion_prompt,
        )

    def _ensure_state(self, image_client: Any) -> PersonaSelfieState:
        state = self._load_state()
        if state is not None:
            return state

        bootstrap_prompt = self._assemble_prompt(
            self._config.neutral_scene.scene_prompt,
            include_character_dna=True,
        )
        bootstrap_paths: list[str] = []
        max_attempts = self._config.bootstrap_count * 2
        attempts = 0
        while len(bootstrap_paths) < self._config.bootstrap_count and attempts < max_attempts:
            attempts += 1
            try:
                generated = image_client.generate_image(
                    prompt=bootstrap_prompt,
                    negative_prompt=self.negative_prompt_text,
                )
                bootstrap_paths.append(
                    image_client.materialize_image(generated, self._next_bootstrap_path())
                )
            except RuntimeError as exc:
                logger.warning("Persona bootstrap image attempt %s failed: %s", attempts, exc)

        if len(bootstrap_paths) < 2:
            raise RuntimeError("Failed to bootstrap enough persona selfie images.")

        created_at = _now_iso()
        character_anchor_path = bootstrap_paths[0]
        latest_selfie_path = bootstrap_paths[1]
        state = PersonaSelfieState(
            version=1,
            character_anchor_path=character_anchor_path,
            latest_selfie_path=latest_selfie_path,
            bootstrap_paths=bootstrap_paths,
            character_dna=list(self._config.character_dna),
            camera_style=list(self._config.camera_style),
            quality_modifiers=list(self._config.quality_modifiers),
            negative_prompt=list(self._config.negative_prompt),
            created_at=created_at,
            updated_at=created_at,
            last_prompt_used=bootstrap_prompt,
            last_scene_key="",
            last_scene_prompt=self._config.neutral_scene.scene_prompt,
        )
        self._save_state(state)
        return state

    def _resolve_scene(self, arguments: dict[str, Any]) -> tuple[str, str, str]:
        scene_key = str(arguments.get("scene_key", "")).strip().lower()
        free_text = str(arguments.get("scene_prompt", "")).strip()
        fallback_prompt = str(arguments.get("prompt", "")).strip()
        scene = _SCENE_CATALOG.get(scene_key)

        if scene is None and scene_key:
            free_text = "\n".join(part for part in (scene_key.replace("_", " "), free_text, fallback_prompt) if part)
        elif not free_text:
            free_text = fallback_prompt

        if scene is None and not free_text:
            raise RuntimeError("scene_prompt or prompt is required for selfie generation.")

        if scene is None:
            scene_prompt = free_text
            motion_prompt = self._default_motion_prompt(free_text)
            return "", scene_prompt, motion_prompt

        scene_prompt = scene.scene_prompt
        motion_prompt = scene.motion_prompt
        if free_text:
            scene_prompt = f"{scene_prompt}\n{free_text}"
            motion_prompt = f"{motion_prompt}\n{free_text}"
        return scene_key, scene_prompt, motion_prompt

    def _assemble_prompt(self, scene_prompt: str, *, include_character_dna: bool) -> str:
        blocks = []
        if include_character_dna:
            blocks.append("\n".join(self._config.character_dna))
        blocks.extend(
            (
                "\n".join(self._config.camera_style),
                scene_prompt,
                "\n".join(self._config.quality_modifiers),
            )
        )
        return "\n\n".join(block.strip() for block in blocks if block.strip())

    def _default_motion_prompt(self, scene_prompt: str) -> str:
        return (
            f"{scene_prompt}\n"
            "subtle blinking\n"
            "small warm smile\n"
            "gentle handheld phone motion"
        )

    def _build_reference_image_data_uri(self, state: PersonaSelfieState) -> str:
        anchor = Path(state.character_anchor_path)
        latest = Path(state.latest_selfie_path)
        if not anchor.exists():
            raise RuntimeError(f"Persona anchor image is missing: {anchor}")
        if not latest.exists():
            raise RuntimeError(f"Persona latest selfie is missing: {latest}")
        if anchor.resolve() == latest.resolve():
            return self._path_to_data_uri(anchor)

        with Image.open(anchor) as anchor_open:
            anchor_img = ImageOps.exif_transpose(anchor_open).convert("RGB")
        with Image.open(latest) as latest_open:
            latest_img = ImageOps.exif_transpose(latest_open).convert("RGB")
        target_height = max(anchor_img.height, latest_img.height)
        anchor_img = self._resize_to_height(anchor_img, target_height)
        latest_img = self._resize_to_height(latest_img, target_height)
        gutter = 24
        combined = Image.new(
            "RGB",
            (anchor_img.width + latest_img.width + gutter, target_height),
            color=(245, 245, 245),
        )
        combined.paste(anchor_img, (0, 0))
        combined.paste(latest_img, (anchor_img.width + gutter, 0))
        buffer = BytesIO()
        combined.save(buffer, format="JPEG", quality=95)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _load_state(self) -> PersonaSelfieState | None:
        path = self._state_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Failed to read persona selfie state from %s", path)
            return None
        if isinstance(payload, dict):
            payload = self._migrate_state_payload(payload)
        try:
            return PersonaSelfieState(**payload)
        except TypeError:
            logger.warning("Persona selfie state is malformed: %s", path)
            return None

    def _save_state(self, state: PersonaSelfieState) -> None:
        self._config.media_root.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(asdict(state), ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )

    @property
    def _state_path(self) -> Path:
        return self._config.media_root / "persona_selfie_state.json"

    def _next_bootstrap_path(self) -> Path:
        bootstrap_dir = self._config.media_root / "bootstrap"
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        return bootstrap_dir / f"bootstrap_{uuid.uuid4().hex[:12]}.jpg"

    def _next_selfie_path(self) -> Path:
        selfie_dir = self._config.media_root / "selfies"
        selfie_dir.mkdir(parents=True, exist_ok=True)
        return selfie_dir / f"selfie_{uuid.uuid4().hex[:12]}.jpg"

    def _path_to_data_uri(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        else:
            mime = "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _resize_to_height(self, image: Image.Image, height: int) -> Image.Image:
        if image.height == height:
            return image
        width = max(1, round(image.width * (height / image.height)))
        return image.resize((width, height))

    def _migrate_state_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        migrated = dict(payload)
        updated_at = str(migrated.get("updated_at") or _now_iso())
        migrated.setdefault("character_dna", list(self._config.character_dna))
        migrated.setdefault("camera_style", list(self._config.camera_style))
        migrated.setdefault("quality_modifiers", list(self._config.quality_modifiers))
        migrated.setdefault("negative_prompt", list(self._config.negative_prompt))
        migrated.setdefault("created_at", updated_at)
        migrated.setdefault("updated_at", updated_at)
        migrated.setdefault("last_prompt_used", "")
        migrated.setdefault("last_scene_key", "")
        migrated.setdefault("last_scene_prompt", "")
        return migrated


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
