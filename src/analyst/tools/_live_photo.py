from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

import requests

from analyst.engine.live_types import AgentTool
from analyst.env import get_env_value

from ._ffmpeg import resolve_ffmpeg_binary
from ._image_gen import ImageGenConfig, ImageGenHandler

logger = logging.getLogger(__name__)


class VideoGenProvider(Protocol):
    def generate_video(self, *, prompt: str, duration_seconds: int) -> "GeneratedVideo":
        ...


class LivePhotoError(RuntimeError):
    """Base error for motion generation and packaging failures."""


class VideoGenerationError(LivePhotoError):
    """Raised when the video provider cannot produce a motion clip."""


class LivePhotoPackagingError(LivePhotoError):
    """Raised when a video clip cannot be converted into a Live Photo bundle."""


@dataclass(frozen=True)
class SeedDanceConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 60
    poll_interval_seconds: float = 2.0
    max_wait_seconds: int = 120
    default_ratio: str = "9:16"
    default_resolution: str = "720p"

    @classmethod
    def from_env_optional(cls) -> SeedDanceConfig | None:
        provider = get_env_value("ANALYST_VIDEO_GEN_PROVIDER", default="").strip().lower()
        if provider != "seeddance":
            return None
        api_key = get_env_value("VOLCENGINE_API_KEY", "ARK_API_KEY", "SEEDDANCE_API_KEY", default="")
        if not api_key:
            logger.warning(
                "ANALYST_VIDEO_GEN_PROVIDER=seeddance but VOLCENGINE_API_KEY / ARK_API_KEY / SEEDDANCE_API_KEY is missing."
            )
            return None
        return cls(
            api_key=api_key,
            base_url=get_env_value(
                "VOLCENGINE_BASE_URL",
                "ARK_BASE_URL",
                "SEEDDANCE_BASE_URL",
                default="https://ark.cn-beijing.volces.com/api/v3",
            ),
            model=get_env_value("ANALYST_LIVE_PHOTO_MODEL", default="doubao-seedance-1-0-pro-fast-251015"),
        )

    @classmethod
    def from_env(cls) -> SeedDanceConfig:
        config = cls.from_env_optional()
        if config is None:
            raise RuntimeError(
                "ANALYST_VIDEO_GEN_PROVIDER=seeddance and a Volcengine/Ark API key are required for live photo generation."
            )
        return config


@dataclass(frozen=True)
class LivePhotoPackagingConfig:
    ffmpeg_binary: str = ""
    makelive_binary: str = "makelive"


@dataclass(frozen=True)
class GeneratedVideo:
    video_path: str
    video_url: str = ""
    mime_type: str = "video/mp4"
    duration_seconds: int = 3


@dataclass(frozen=True)
class LivePhotoArtifact:
    live_photo_image_path: str
    live_photo_video_path: str
    delivery_video_path: str
    asset_id: str
    manifest_path: str
    cleanup_paths: tuple[str, ...]


class SeedDanceVideoProvider:
    """Generate a short motion clip via a SeedDance-compatible task API."""

    def __init__(
        self,
        config: SeedDanceConfig,
        session: requests.Session | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._sleep = sleep_fn

    def generate_video(self, *, prompt: str, duration_seconds: int) -> GeneratedVideo:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._config.model,
            "content": [{"type": "text", "text": prompt}],
            "duration": duration_seconds,
            "ratio": self._config.default_ratio,
            "resolution": self._config.default_resolution,
            "generate_audio": False,
        }
        task_body = self._request_json(
            "post",
            f"{self._config.base_url}/contents/generations/tasks",
            headers=headers,
            data=json.dumps(payload),
            timeout=self._config.timeout_seconds,
        )
        task_id = self._extract_task_id(task_body)
        if not task_id:
            raise VideoGenerationError("SeedDance did not return a task id.")

        deadline = time.monotonic() + self._config.max_wait_seconds
        while True:
            status_body = self._request_json(
                "get",
                f"{self._config.base_url}/contents/generations/tasks/{task_id}",
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            status = self._extract_status(status_body)
            if status in {"succeeded", "success", "completed"}:
                video_url = self._extract_video_url(status_body)
                if not video_url:
                    raise VideoGenerationError("SeedDance finished without a video URL.")
                return GeneratedVideo(
                    video_path=self._download_video(video_url),
                    video_url=video_url,
                    duration_seconds=duration_seconds,
                )
            if status in {"failed", "error", "cancelled"}:
                raise VideoGenerationError(self._extract_error(status_body) or "SeedDance video generation failed.")
            if time.monotonic() >= deadline:
                raise VideoGenerationError("SeedDance video generation timed out.")
            self._sleep(self._config.poll_interval_seconds)

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = getattr(self._session, method)(url, **kwargs)
        except requests.RequestException as exc:
            raise VideoGenerationError(str(exc)) from exc
        if response.status_code >= 400:
            raise VideoGenerationError(f"SeedDance API error {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise VideoGenerationError("SeedDance returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise VideoGenerationError("SeedDance returned an unexpected response shape.")
        return body

    def _download_video(self, video_url: str) -> str:
        try:
            response = self._session.get(video_url, timeout=self._config.timeout_seconds)
        except requests.RequestException as exc:
            raise VideoGenerationError(str(exc)) from exc
        if response.status_code >= 400:
            raise VideoGenerationError(f"SeedDance video download failed with status {response.status_code}.")

        suffix = Path(urlparse(video_url).path).suffix or ".mp4"
        filename = f"analyst_live_video_{uuid.uuid4().hex[:12]}{suffix}"
        path = Path(tempfile.gettempdir()) / filename
        try:
            path.write_bytes(response.content)
        except OSError as exc:
            raise VideoGenerationError(str(exc)) from exc
        return str(path)

    def _extract_task_id(self, body: dict[str, Any]) -> str:
        for candidate in (
            body.get("task_id"),
            body.get("id"),
            _get_nested(body, "data", "task_id"),
            _get_nested(body, "output", "task_id"),
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        return ""

    def _extract_status(self, body: dict[str, Any]) -> str:
        for candidate in (
            body.get("status"),
            body.get("state"),
            _get_nested(body, "data", "status"),
            _get_nested(body, "output", "task_status"),
            _get_nested(body, "output", "status"),
        ):
            if isinstance(candidate, str) and candidate:
                return candidate.strip().lower()
        return ""

    def _extract_video_url(self, body: dict[str, Any]) -> str:
        candidates = [
            body.get("video_url"),
            _get_nested(body, "content", "video_url"),
            _get_nested(body, "data", "video_url"),
            _get_nested(body, "output", "video_url"),
            _get_nested(body, "output", "content", "video_url"),
            _get_nested(body, "data", "output", "video_url"),
        ]
        output_items = body.get("content") or _get_nested(body, "output", "content") or _get_nested(body, "data", "content")
        if isinstance(output_items, list):
            for item in output_items:
                if isinstance(item, dict):
                    candidates.extend([item.get("video_url"), item.get("url")])
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
        return ""

    def _extract_error(self, body: dict[str, Any]) -> str:
        for candidate in (
            body.get("error"),
            body.get("message"),
            _get_nested(body, "data", "error"),
            _get_nested(body, "output", "error"),
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        return ""


class LivePhotoPackager:
    """Package a short motion clip into a true Apple Live Photo bundle."""

    def __init__(
        self,
        config: LivePhotoPackagingConfig | None = None,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._config = config or LivePhotoPackagingConfig()
        self._runner = runner
        self._ffmpeg_binary = self._config.ffmpeg_binary or resolve_ffmpeg_binary(which)
        self._makelive_binary = _resolve_binary(
            configured=get_env_value("ANALYST_MAKELIVE_BINARY", default="").strip(),
            fallback=self._config.makelive_binary,
            which=which,
        )

    def is_available(self) -> bool:
        return platform.system() == "Darwin" and bool(self._ffmpeg_binary) and bool(self._makelive_binary)

    def package(self, generated_video: GeneratedVideo) -> LivePhotoArtifact:
        if not self.is_available():
            raise LivePhotoPackagingError("True Live Photo packaging requires macOS, ffmpeg, and makelive.")

        asset_id = str(uuid.uuid4()).upper()
        live_photo_image_path = self._temp_path("analyst_live_photo_", ".jpg")
        live_photo_video_path = self._temp_path("analyst_live_photo_", ".mov")
        manifest_path = self._temp_path("analyst_live_photo_", ".json")

        self._run_command(
            [
                self._ffmpeg_binary,
                "-y",
                "-i",
                generated_video.video_path,
                "-frames:v",
                "1",
                live_photo_image_path,
            ]
        )
        self._run_command(
            [
                self._ffmpeg_binary,
                "-y",
                "-i",
                generated_video.video_path,
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                live_photo_video_path,
            ]
        )

        self._run_command([self._makelive_binary, live_photo_image_path, live_photo_video_path])

        manifest = {
            "asset_id": asset_id,
            "live_photo_image_path": live_photo_image_path,
            "live_photo_video_path": live_photo_video_path,
            "delivery_video_path": generated_video.video_path,
            "metadata_tagged": True,
            "packager": "makelive",
        }
        try:
            Path(manifest_path).write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            raise LivePhotoPackagingError(str(exc)) from exc

        cleanup_paths = (
            generated_video.video_path,
            live_photo_image_path,
            live_photo_video_path,
            manifest_path,
        )
        return LivePhotoArtifact(
            live_photo_image_path=live_photo_image_path,
            live_photo_video_path=live_photo_video_path,
            delivery_video_path=generated_video.video_path,
            asset_id=asset_id,
            manifest_path=manifest_path,
            cleanup_paths=cleanup_paths,
        )

    def _run_command(self, command: list[str]) -> None:
        try:
            self._runner(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise LivePhotoPackagingError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc

    def _temp_path(self, prefix: str, suffix: str) -> str:
        filename = f"{prefix}{uuid.uuid4().hex[:12]}{suffix}"
        return str(Path(tempfile.gettempdir()) / filename)


class LivePhotoHandler:
    """Create a motion asset, with optional true Live Photo packaging when available."""

    def __init__(
        self,
        video_provider: VideoGenProvider,
        packager: LivePhotoPackager | None,
        image_handler: ImageGenHandler,
    ) -> None:
        self._video_provider = video_provider
        self._packager = packager
        self._image_handler = image_handler

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return {"status": "error", "error": "prompt is required"}
        duration_seconds = _clamp_duration(arguments.get("duration_seconds", 3))

        try:
            generated_video = self._video_provider.generate_video(
                prompt=prompt,
                duration_seconds=duration_seconds,
            )
        except VideoGenerationError as exc:
            logger.warning("Live photo generation failed: %s", exc)
            fallback = self._image_handler({"prompt": prompt})
            if fallback.get("status") == "ok":
                fallback["fallback_kind"] = "image"
                fallback["prompt_used"] = prompt
                fallback["warning"] = str(exc)
                return fallback
            return {"status": "error", "error": str(exc)}

        if self._packager and self._packager.is_available():
            try:
                live_photo = self._packager.package(generated_video)
                return {
                    "status": "ok",
                    "fallback_kind": "live_photo",
                    "asset_id": live_photo.asset_id,
                    "prompt_used": prompt,
                    "delivery_video_path": live_photo.delivery_video_path,
                    "live_photo_image_path": live_photo.live_photo_image_path,
                    "live_photo_video_path": live_photo.live_photo_video_path,
                    "live_photo_manifest_path": live_photo.manifest_path,
                    "cleanup_paths": list(live_photo.cleanup_paths),
                }
            except LivePhotoPackagingError as exc:
                logger.warning("True Live Photo packaging failed; returning motion video only: %s", exc)
                return self._build_video_result(
                    prompt=prompt,
                    generated_video=generated_video,
                    warning=str(exc),
                )

        return self._build_video_result(
            prompt=prompt,
            generated_video=generated_video,
            warning="True Live Photo packaging is unavailable on this runtime; returning motion video only.",
        )

    def _build_video_result(
        self,
        *,
        prompt: str,
        generated_video: GeneratedVideo,
        warning: str = "",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "ok",
            "fallback_kind": "video",
            "prompt_used": prompt,
            "delivery_video_path": generated_video.video_path,
            "cleanup_paths": [generated_video.video_path],
        }
        if generated_video.video_url:
            result["delivery_video_url"] = generated_video.video_url
        if warning:
            result["warning"] = warning
        return result


def build_live_photo_tool(
    config: SeedDanceConfig | None = None,
    *,
    session: requests.Session | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    image_config: ImageGenConfig | None = None,
) -> AgentTool:
    """Factory: create a generate_live_photo AgentTool."""
    resolved_config = config or SeedDanceConfig.from_env()
    provider = SeedDanceVideoProvider(resolved_config, session=session, sleep_fn=sleep_fn)
    packager = LivePhotoPackager(runner=runner, which=which)
    fallback_handler = ImageGenHandler(image_config or ImageGenConfig.from_env())
    handler = LivePhotoHandler(provider, packager, fallback_handler)
    return AgentTool(
        name="generate_live_photo",
        description=(
            "Generate a short motion selfie or Live Photo-style asset. "
            "Use for live photo, motion selfie, or dynamic selfie requests. "
            "When Apple Live Photo packaging is unavailable, this returns a motion video instead. "
            "The prompt should be in English and visually specific."
        ),
        parameters={
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "English text description of the motion scene. "
                        "Be specific about the subject, background, action, lighting, and framing."
                    ),
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "Length of the motion clip in seconds. Use 2-4 seconds; default is 3.",
                },
            },
        },
        handler=handler,
    )


def build_optional_live_photo_tool(
    config: SeedDanceConfig | None = None,
    *,
    session: requests.Session | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    image_config: ImageGenConfig | None = None,
) -> AgentTool | None:
    """Return a live-photo tool when the provider is configured."""
    resolved_config = config or SeedDanceConfig.from_env_optional()
    if resolved_config is None:
        return None
    packager = LivePhotoPackager(runner=runner, which=which)
    if not packager.is_available():
        logger.warning("Live photo tool running in motion-video mode; true Live Photo packaging requires macOS, ffmpeg, and makelive.")
    return build_live_photo_tool(
        config=resolved_config,
        session=session,
        sleep_fn=sleep_fn,
        runner=runner,
        which=which,
        image_config=image_config,
    )


def _clamp_duration(raw_value: Any) -> int:
    try:
        duration = int(raw_value)
    except (TypeError, ValueError):
        duration = 3
    return max(2, min(4, duration))


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _resolve_binary(
    *,
    configured: str,
    fallback: str,
    which: Callable[[str], str | None],
) -> str:
    if configured:
        return configured
    if not fallback:
        return ""
    return which(fallback) or ""
