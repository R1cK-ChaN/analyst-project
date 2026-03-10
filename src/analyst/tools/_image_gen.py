from __future__ import annotations

import base64
import binascii
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from analyst.engine.live_types import AgentTool
from analyst.env import get_env_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageGenConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 120
    image_size: str = "2048x2048"
    response_format: str = "url"

    @classmethod
    def from_env(cls) -> ImageGenConfig:
        api_key = get_env_value("VOLCENGINE_API_KEY", "ARK_API_KEY", default="")
        if not api_key:
            raise RuntimeError("VOLCENGINE_API_KEY or ARK_API_KEY is required for image generation.")
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
        )


class ImageGenHandler:
    """Stateful callable that generates still images via Volcengine Ark."""

    def __init__(self, config: ImageGenConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return {"status": "error", "error": "prompt is required"}

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._config.model,
            "prompt": prompt,
            "size": self._config.image_size,
            "response_format": self._config.response_format,
        }

        try:
            response = self._session.post(
                f"{self._config.base_url}/images/generations",
                headers=headers,
                data=json.dumps(payload),
                timeout=self._config.timeout_seconds,
            )
        except requests.RequestException as exc:
            logger.warning("Image gen request failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        if response.status_code >= 400:
            logger.warning("Image gen API error %d: %s", response.status_code, response.text[:300])
            return {"status": "error", "error": f"API error {response.status_code}"}

        try:
            body = response.json()
        except ValueError:
            logger.warning("Image gen API returned invalid JSON")
            return {"status": "error", "error": "Invalid API response"}
        if not isinstance(body, dict):
            return {"status": "error", "error": "Invalid API response"}

        for item in self._iter_image_items(body):
            if not isinstance(item, dict):
                continue
            image_url = self._extract_image_url(item)
            if image_url:
                return {"status": "ok", "image_url": image_url, "prompt_used": prompt}

            for key in ("b64_json", "data", "image_base64"):
                raw_image = item.get(key)
                if isinstance(raw_image, str) and raw_image:
                    image_path = self._save_base64_payload(raw_image)
                    if image_path:
                        return {"status": "ok", "image_path": image_path, "prompt_used": prompt}

        return {"status": "error", "error": "No image found in model response"}

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
            "Generate an image from a text description. Use when the user asks "
            "for a picture, selfie, drawing, or any static image generation request. "
            "The prompt should be in English, detailed and specific."
        ),
        parameters={
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "English text description of the image to generate. "
                        "Be specific about scene, style, lighting, and composition."
                    ),
                },
            },
        },
        handler=handler,
    )
