from __future__ import annotations

import base64
import binascii
import json
import logging
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from analyst.engine.live_types import AgentTool
from analyst.env import get_env_value

from ._request_context import get_request_image
from ._selfie_persona import BackCameraPhotoService, SelfiePromptService

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ImageGenConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 120
    image_size: str = "2048x2048"
    response_format: str = "url"
    max_retries: int = 2
    retry_backoff_seconds: float = 1.5
    watermark: bool = False

    @classmethod
    def from_env(cls) -> ImageGenConfig:
        api_key = get_env_value("VOLCENGINE_API_KEY", "ARK_API_KEY", default="")
        if not api_key:
            raise RuntimeError("VOLCENGINE_API_KEY or ARK_API_KEY is required for image generation.")
        try:
            max_retries = max(0, int(get_env_value("ANALYST_IMAGE_GEN_MAX_RETRIES", default="2")))
        except ValueError:
            max_retries = 2
        return cls(
            api_key=api_key,
            base_url=get_env_value(
                "VOLCENGINE_BASE_URL",
                "ARK_BASE_URL",
                default="https://ark.cn-beijing.volces.com/api/v3",
            ),
            model=get_env_value("ANALYST_IMAGE_GEN_MODEL", default="doubao-seedream-5-0-260128"),
            image_size=get_env_value("ANALYST_IMAGE_GEN_SIZE", default="2048x2048"),
            response_format=get_env_value("ANALYST_IMAGE_GEN_RESPONSE_FORMAT", default="url"),
            max_retries=max_retries,
            watermark=get_env_value("ANALYST_IMAGE_GEN_WATERMARK", default="false").strip().lower() in {"1", "true", "yes", "on"},
        )


@dataclass(frozen=True)
class GeneratedImage:
    image_path: str = ""
    image_url: str = ""


class SeedreamImageClient:
    """Low-level Volcengine Ark image-generation client."""

    def __init__(
        self,
        config: ImageGenConfig,
        session: requests.Session | None = None,
        *,
        sleep_fn: Any = time.sleep,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._sleep = sleep_fn

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        image_input: str = "",
    ) -> GeneratedImage:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._config.model,
            "prompt": prompt,
            "size": self._config.image_size,
            "response_format": self._config.response_format,
            "watermark": self._config.watermark,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if image_input:
            payload["image"] = image_input

        response = self._post_with_retries(headers=headers, payload=payload)

        try:
            body = response.json()
        except ValueError as exc:
            raise ImageGenerationError("Invalid API response") from exc
        if not isinstance(body, dict):
            raise ImageGenerationError("Invalid API response")

        for item in self._iter_image_items(body):
            if not isinstance(item, dict):
                continue
            image_url = self._extract_image_url(item)
            if image_url:
                return GeneratedImage(image_url=image_url)
            for key in ("b64_json", "data", "image_base64"):
                raw_image = item.get(key)
                if isinstance(raw_image, str) and raw_image:
                    image_path = self._save_base64_payload(raw_image)
                    if image_path:
                        return GeneratedImage(image_path=image_path)

        raise ImageGenerationError("No image found in model response")

    def materialize_image(self, generated: GeneratedImage, target_path: Path) -> str:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if generated.image_path:
            source = Path(generated.image_path)
            if source.resolve() != target_path.resolve():
                shutil.copyfile(source, target_path)
            return str(target_path)
        if generated.image_url:
            self._download_image(generated.image_url, target_path)
            return str(target_path)
        raise ImageGenerationError("No image source is available to materialize.")

    def _download_image(self, image_url: str, target_path: Path) -> None:
        max_attempts = self._config.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._session.get(image_url, timeout=self._config.timeout_seconds)
            except requests.RequestException as exc:
                retryable = self._is_retryable_exception(exc)
                if retryable and attempt < max_attempts:
                    logger.warning(
                        "Image download attempt %s/%s failed transiently: %s",
                        attempt,
                        max_attempts,
                        exc,
                    )
                    self._sleep(self._config.retry_backoff_seconds * attempt)
                    continue
                raise ImageGenerationError(str(exc), retryable=retryable) from exc
            if response.status_code < 400:
                target_path.write_bytes(response.content)
                return
            retryable = self._is_retryable_status(response.status_code)
            if retryable and attempt < max_attempts:
                logger.warning(
                    "Image download attempt %s/%s returned %s; retrying.",
                    attempt,
                    max_attempts,
                    response.status_code,
                )
                self._sleep(self._config.retry_backoff_seconds * attempt)
                continue
            raise ImageGenerationError(
                f"Image download failed with status {response.status_code}.",
                retryable=retryable,
            )

    def _iter_image_items(self, body: dict[str, Any]) -> list[Any]:
        candidates = body.get("data")
        if isinstance(candidates, list):
            return candidates
        if isinstance(candidates, dict):
            return [candidates]
        return []

    def _extract_image_url(self, item: dict[str, Any]) -> str:
        for key in ("url", "image_url", "uri"):
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://", "data:image/")):
                return candidate
        return ""

    def _save_base64_payload(self, raw_image: str) -> str | None:
        if raw_image.startswith("data:image/"):
            return self._save_base64_data_uri(raw_image)
        return self._save_base64(raw_image)

    def _save_base64_data_uri(self, data_uri: str) -> str | None:
        try:
            header, b64_data = data_uri.split(",", 1)
        except ValueError:
            logger.warning("Failed to decode base64 data URI")
            return None

        ext = "png"
        if "jpeg" in header or "jpg" in header:
            ext = "jpg"
        elif "webp" in header:
            ext = "webp"
        return self._save_base64(b64_data, ext=ext)

    def _save_base64(self, b64_data: str, ext: str = "png") -> str | None:
        try:
            raw = base64.b64decode(b64_data)
            path = Path(tempfile.gettempdir()) / f"analyst_gen_{uuid.uuid4().hex[:12]}.{ext}"
            path.write_bytes(raw)
            return str(path)
        except (binascii.Error, OSError, ValueError):
            logger.warning("Failed to decode or save base64 image payload")
            return None

    def _post_with_retries(self, *, headers: dict[str, str], payload: dict[str, Any]) -> requests.Response:
        max_attempts = self._config.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._session.post(
                    f"{self._config.base_url}/images/generations",
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=self._config.timeout_seconds,
                )
            except requests.RequestException as exc:
                retryable = self._is_retryable_exception(exc)
                if retryable and attempt < max_attempts:
                    logger.warning(
                        "Image generation attempt %s/%s failed transiently: %s",
                        attempt,
                        max_attempts,
                        exc,
                    )
                    self._sleep(self._config.retry_backoff_seconds * attempt)
                    continue
                raise ImageGenerationError(str(exc), retryable=retryable) from exc
            if response.status_code < 400:
                return response
            retryable = self._is_retryable_status(response.status_code)
            if retryable and attempt < max_attempts:
                logger.warning(
                    "Image generation attempt %s/%s returned %s; retrying.",
                    attempt,
                    max_attempts,
                    response.status_code,
                )
                self._sleep(self._config.retry_backoff_seconds * attempt)
                continue
            raise ImageGenerationError(
                f"API error {response.status_code}",
                retryable=retryable,
            )
        raise ImageGenerationError("Image generation failed without a response.")

    def _is_retryable_exception(self, exc: requests.RequestException) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in ("timed out", "timeout", "connection aborted", "temporarily unavailable")
        )

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code == 429 or status_code >= 500


class ImageGenHandler:
    """Stateful callable that generates still images via Volcengine Ark."""

    def __init__(
        self,
        config: ImageGenConfig,
        session: requests.Session | None = None,
        *,
        image_client: SeedreamImageClient | None = None,
        selfie_service: SelfiePromptService | None = None,
        back_camera_service: BackCameraPhotoService | None = None,
    ) -> None:
        self._config = config
        self._image_client = image_client or SeedreamImageClient(config, session=session)
        self._selfie_service = selfie_service or SelfiePromptService()
        self._back_camera_service = back_camera_service or BackCameraPhotoService()

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._selfie_service.is_selfie_request(arguments):
            return self._handle_selfie(arguments)
        if self._back_camera_service.is_back_camera_request(arguments):
            return self._handle_back_camera(arguments)

        prompt = str(arguments.get("prompt", "")).strip()
        use_attached_image = bool(arguments.get("use_attached_image"))
        attached_image = get_request_image() if use_attached_image else None
        if use_attached_image and attached_image is None:
            return {"status": "error", "error": "No attached image is available for this request."}
        if not prompt and attached_image is not None:
            prompt = "Create a photorealistic variation of the attached image while preserving the main subject."
        if not prompt:
            return {"status": "error", "error": "prompt is required"}

        try:
            generated = self._image_client.generate_image(
                prompt=prompt,
                image_input=attached_image.data_uri if attached_image is not None else "",
            )
        except RuntimeError as exc:
            logger.warning("Image gen request failed: %s", exc)
            return {"status": "error", "error": str(exc)}
        result = self._result_from_generated_image(generated, prompt=prompt)
        if attached_image is not None and result.get("status") == "ok":
            result["used_attached_image"] = True
        return result

    def _handle_selfie(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            generated = self._selfie_service.generate_selfie(arguments, self._image_client)
        except RuntimeError as exc:
            logger.warning("Selfie image generation failed: %s", exc)
            fallback = self._fallback_selfie_generation(arguments, exc)
            if fallback is not None:
                return fallback
            return {"status": "error", "error": str(exc)}

        result = {
            "status": "ok",
            "image_path": generated.image_path,
            "prompt_used": generated.prompt_used,
            "mode": "selfie",
        }
        if generated.scene_key:
            result["scene_key"] = generated.scene_key
        result["scene_prompt"] = generated.scene_prompt
        result["negative_prompt_used"] = generated.negative_prompt
        return result

    def _fallback_selfie_generation(
        self,
        arguments: dict[str, Any],
        exc: RuntimeError,
    ) -> dict[str, Any] | None:
        if not self._is_retryable_error(exc):
            return None
        draft = self._selfie_service.build_prompt_draft(arguments)
        try:
            generated = self._image_client.generate_image(
                prompt=draft.fallback_prompt,
                negative_prompt=draft.negative_prompt,
            )
        except RuntimeError as fallback_exc:
            logger.warning("Selfie fallback image generation failed: %s", fallback_exc)
            return None

        result = self._result_from_generated_image(generated, prompt=draft.fallback_prompt)
        if result.get("status") != "ok":
            return None
        result["fallback_kind"] = "generic_image"
        result["warning"] = str(exc)
        result["mode"] = "selfie"
        if draft.scene_key:
            result["scene_key"] = draft.scene_key
        result["scene_prompt"] = draft.scene_prompt
        result["negative_prompt_used"] = draft.negative_prompt
        return result

    def _handle_back_camera(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            generated = self._back_camera_service.generate_photo(arguments, self._image_client)
        except RuntimeError as exc:
            logger.warning("Back camera image generation failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        result = {
            "status": "ok",
            "image_path": generated.image_path,
            "prompt_used": generated.prompt_used,
            "mode": "back_camera",
            "scene_prompt": generated.scene_prompt,
            "negative_prompt_used": generated.negative_prompt,
        }
        if generated.scene_key:
            result["scene_key"] = generated.scene_key
        return result

    def _is_retryable_error(self, exc: RuntimeError) -> bool:
        if isinstance(exc, ImageGenerationError):
            return exc.retryable
        message = str(exc).lower()
        return any(token in message for token in ("timed out", "timeout", "connection aborted"))

    def _result_from_generated_image(self, generated: GeneratedImage, *, prompt: str) -> dict[str, Any]:
        if generated.image_path:
            return {"status": "ok", "image_path": generated.image_path, "prompt_used": prompt}
        if generated.image_url:
            return {"status": "ok", "image_url": generated.image_url, "prompt_used": prompt}
        return {"status": "error", "error": "No image found in model response"}


def build_image_gen_tool(
    config: ImageGenConfig | None = None,
    session: requests.Session | None = None,
) -> AgentTool:
    """Factory: create a generate_image AgentTool backed by Volcengine Ark."""
    resolved_config = config or ImageGenConfig.from_env()
    handler = ImageGenHandler(resolved_config, session=session)
    return AgentTool(
        name="generate_image",
        description=(
            "Generate an image from a text description. Use mode='selfie' for persona selfies so the backend "
            "can enforce consistent but natural phone-camera selfie prompts with scene_key / scene_prompt. "
            "Use mode='back_camera' for rear-camera POV photos of what the persona is seeing, such as lunch, coffee, desk, "
            "home, or street views, with back_camera_scene_key / scene_prompt. "
            "Only use mode='selfie' when the user explicitly wants to see the persona/agent in frame. "
            "For back_camera mode, the persona must not appear in frame. For objects, food, drinks, desks, rooms, scenery, or environment shots without persona context, use generic prompt-only mode."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Free-form English image prompt for generic images, or a short fallback scene description "
                        "for selfie mode when scene_prompt is omitted."
                    ),
                },
                "mode": {
                    "type": "string",
                    "description": "Set to 'selfie' for explicit front-camera selfies, or 'back_camera' for rear-camera POV photos.",
                },
                "scene_key": {
                    "type": "string",
                    "description": (
                        "Optional shared selfie-scene key, only for mode='selfie', "
                        "e.g. coffee_shop, lazy_sunday_home, night_walk, gym_mirror, "
                        "airport_waiting, bedroom_late_night, rainy_day_window, or weekend_street."
                    ),
                },
                "scene_prompt": {
                    "type": "string",
                    "description": "Optional short English scene detail appended to the selected selfie or back-camera scene.",
                },
                "back_camera_scene_key": {
                    "type": "string",
                    "description": (
                        "Optional shared back-camera scene key, only for mode='back_camera', "
                        "e.g. lunch_table_food, coffee_table_pov, desk_midday_pov, "
                        "home_window_view, or street_walk_view."
                    ),
                },
                "back_camera_scene_prompt": {
                    "type": "string",
                    "description": "Optional short English detail appended to the selected back-camera scene.",
                },
                "use_attached_image": {
                    "type": "boolean",
                    "description": (
                        "Set true only when the user attached an image and wants a variation or edit based on it."
                    ),
                },
            },
        },
        handler=handler,
    )
