from __future__ import annotations

import base64
from io import BytesIO
import logging
import os
import shutil
import tempfile
from typing import Any

from PIL import Image, ImageOps
from telegram import Update
from telegram.ext import ContextTypes

from analyst.tools._request_context import RequestImageInput

from .bot_constants import MANAGED_MEDIA_PREFIXES, MAX_INBOUND_IMAGE_EDGE

logger = logging.getLogger(__name__)

def _is_managed_generated_media(path: str) -> bool:
    """Only delete temp files created by the image generation tool."""
    temp_dir = os.path.abspath(tempfile.gettempdir())
    abs_path = os.path.abspath(path)
    return (
        os.path.dirname(abs_path) == temp_dir
        and os.path.basename(abs_path).startswith(MANAGED_MEDIA_PREFIXES)
    )

def _cleanup_generated_media(path: str) -> None:
    if not _is_managed_generated_media(path):
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
            return
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Failed to remove generated media file: %s", path)

def _image_summary_marker(image: RequestImageInput | None) -> str:
    if image is None:
        return ""
    if image.source == "reply":
        return "[Referenced image]"
    return "[Image attached]"

def _summarize_user_message(text: str, *, image: RequestImageInput | None = None) -> str:
    marker = _image_summary_marker(image)
    if marker and text:
        return f"{text}\n{marker}"
    if marker:
        return marker
    return text

def _render_image_instruction(text: str, *, image: RequestImageInput | None = None) -> str:
    base = text.strip() or "The user sent an image without caption. Analyze it and respond naturally."
    relation = "attached" if image is None or image.source != "reply" else "referenced in the replied-to message"
    return (
        f"{base}\n\n"
        f"[The user provided an image ({relation}). You can inspect it directly. "
        "If they ask for a variation or edit of the attached image, call generate_image with "
        "use_attached_image=true. If they ask to animate the attached image, call "
        "generate_live_photo with use_attached_image=true.]"
    )

def _encode_image_data_uri(raw_bytes: bytes, mime_type: str) -> RequestImageInput:
    normalized_mime_type = mime_type or "image/jpeg"
    payload = raw_bytes
    try:
        with Image.open(BytesIO(raw_bytes)) as source_image:
            image = ImageOps.exif_transpose(source_image)
            if image.mode not in {"RGB", "L"}:
                alpha_image = image.convert("RGBA")
                background = Image.new("RGBA", alpha_image.size, (255, 255, 255, 255))
                background.alpha_composite(alpha_image)
                image = background.convert("RGB")
            else:
                image = image.convert("RGB")
            longest_edge = max(image.size)
            if longest_edge > MAX_INBOUND_IMAGE_EDGE:
                scale = MAX_INBOUND_IMAGE_EDGE / float(longest_edge)
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            payload = buffer.getvalue()
            normalized_mime_type = "image/jpeg"
    except Exception:
        logger.warning("Failed to normalize inbound image; falling back to original bytes.")
    encoded = base64.b64encode(payload).decode("ascii")
    return RequestImageInput(data_uri=f"data:{normalized_mime_type};base64,{encoded}", mime_type=normalized_mime_type)

def _image_file_ref(message: Any) -> tuple[str, str, str] | None:
    file_id = ""
    mime_type = "image/jpeg"
    filename = ""
    photo_items = getattr(message, "photo", None)
    if isinstance(photo_items, (list, tuple)) and photo_items:
        photo = photo_items[-1]
        raw_file_id = getattr(photo, "file_id", "")
        if not isinstance(raw_file_id, str) or not raw_file_id:
            return None
        file_id = raw_file_id
        filename = f"{file_id}.jpg"
    else:
        document = getattr(message, "document", None)
        mime_type = getattr(document, "mime_type", "") if document is not None else ""
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            return None
        raw_file_id = getattr(document, "file_id", "")
        if not isinstance(raw_file_id, str) or not raw_file_id:
            return None
        file_id = raw_file_id
        raw_filename = getattr(document, "file_name", "")
        filename = raw_filename if isinstance(raw_filename, str) and raw_filename else f"{file_id}.jpg"
    if not file_id:
        return None
    return file_id, mime_type, filename

async def _extract_message_image(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    source: str,
) -> RequestImageInput | None:
    if message is None:
        return None
    image_ref = _image_file_ref(message)
    if image_ref is None:
        return None
    file_id, mime_type, filename = image_ref

    telegram_file = await context.bot.get_file(file_id)
    raw_bytes = bytes(await telegram_file.download_as_bytearray())
    request_image = _encode_image_data_uri(raw_bytes, mime_type)
    return RequestImageInput(
        data_uri=request_image.data_uri,
        mime_type=request_image.mime_type,
        filename=filename,
        source=source,
    )

async def _extract_attached_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> RequestImageInput | None:
    message = update.effective_message
    if message is None:
        return None
    direct_image = await _extract_message_image(message, context, source="message")
    if direct_image is not None:
        return direct_image
    reply_message = getattr(message, "reply_to_message", None)
    return await _extract_message_image(reply_message, context, source="reply")

