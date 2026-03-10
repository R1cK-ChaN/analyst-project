from __future__ import annotations

import base64
import binascii
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
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
    timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> ImageGenConfig:
        api_key = get_env_value("OPENROUTER_API_KEY", "LLM_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY or LLM_API_KEY is required for image generation.")
        return cls(
            api_key=api_key,
            base_url=get_env_value("OPENROUTER_BASE_URL", "LLM_BASE_URL", default="https://openrouter.ai/api/v1"),
            model=get_env_value("ANALYST_IMAGE_GEN_MODEL", default="google/gemini-2.0-flash-exp:free"),
        )


class ImageGenHandler:
    """Stateful callable that generates images via OpenRouter chat completions."""

    def __init__(self, config: ImageGenConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        prompt = str(arguments.get("prompt", ""))
        if not prompt:
            return {"status": "error", "error": "prompt is required"}

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            response = self._session.post(
                f"{self._config.base_url}/chat/completions",
                headers=headers,
                data=json.dumps(payload),
                timeout=self._config.timeout_seconds,
            )
            if response.status_code >= 400:
                logger.warning("Image gen API error %d: %s", response.status_code, response.text[:300])
                return {"status": "error", "error": f"API error {response.status_code}"}

            try:
                body = response.json()
            except ValueError:
                logger.warning("Image gen API returned invalid JSON")
                return {"status": "error", "error": "Invalid API response"}
            choices = body.get("choices", [])
            if not choices:
                return {"status": "error", "error": "No response from image model"}

            message = choices[0].get("message", {})
            content = message.get("content")

            # content may be a string or a list of content parts
            parts: list[dict[str, Any]] = []
            if isinstance(content, list):
                parts = content
            elif isinstance(content, str):
                # Some models return a single text string; no image in that case
                parts = [{"type": "text", "text": content}]

            for part in parts:
                if part.get("type") == "image_url":
                    image_url_data = part.get("image_url", {})
                    url = image_url_data.get("url", "") if isinstance(image_url_data, dict) else str(image_url_data)
                    if url.startswith("data:"):
                        # data URI — decode base64
                        path = self._save_base64_data_uri(url)
                        if path:
                            return {"status": "ok", "image_path": path, "prompt_used": prompt}
                    elif url.startswith(("http://", "https://")):
                        return {"status": "ok", "image_url": url, "prompt_used": prompt}

                elif part.get("type") == "inline_data":
                    # Gemini-style inline_data with mime_type + data
                    mime = part.get("mime_type", "image/png")
                    b64 = part.get("data", "")
                    if b64:
                        ext = "png" if "png" in mime else "jpg"
                        path = self._save_base64(b64, ext)
                        if path:
                            return {"status": "ok", "image_path": path, "prompt_used": prompt}

            # Fallback: check if there's a base64 blob in text content
            for part in parts:
                if part.get("type") == "text":
                    text_content = part.get("text", "")
                    if "base64" in text_content and len(text_content) > 1000:
                        # Try to extract base64 from data URI in text
                        if "data:image" in text_content:
                            start = text_content.find("data:image")
                            # Find the end of base64 data
                            end = text_content.find('"', start)
                            if end == -1:
                                end = text_content.find("'", start)
                            if end == -1:
                                end = len(text_content)
                            data_uri = text_content[start:end]
                            path = self._save_base64_data_uri(data_uri)
                            if path:
                                return {"status": "ok", "image_path": path, "prompt_used": prompt}

            return {"status": "error", "error": "No image found in model response"}

        except requests.RequestException as exc:
            logger.warning("Image gen request failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _save_base64_data_uri(self, data_uri: str) -> str | None:
        """Decode a data:image/...;base64,... URI and save to a temp file."""
        try:
            # Format: data:image/png;base64,iVBOR...
            header, b64_data = data_uri.split(",", 1)
            ext = "png"
            if "jpeg" in header or "jpg" in header:
                ext = "jpg"
            elif "webp" in header:
                ext = "webp"
            return self._save_base64(b64_data, ext)
        except Exception:
            logger.warning("Failed to decode base64 data URI")
            return None

    def _save_base64(self, b64_data: str, ext: str = "png") -> str | None:
        """Decode raw base64 and save to a temp file."""
        try:
            raw = base64.b64decode(b64_data)
            filename = f"analyst_gen_{uuid.uuid4().hex[:12]}.{ext}"
            path = str(tempfile.gettempdir()) + "/" + filename
            with open(path, "wb") as f:
                f.write(raw)
            return path
        except (binascii.Error, OSError, ValueError):
            logger.warning("Failed to decode or save base64 image payload")
            return None


def build_image_gen_tool(
    config: ImageGenConfig | None = None,
    session: requests.Session | None = None,
) -> AgentTool:
    """Factory: create a generate_image AgentTool backed by OpenRouter."""
    resolved_config = config or ImageGenConfig.from_env()
    handler = ImageGenHandler(resolved_config, session=session)
    return AgentTool(
        name="generate_image",
        description=(
            "Generate an image from a text description. Use when the user asks "
            "for a picture, selfie, drawing, or any image generation request. "
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
