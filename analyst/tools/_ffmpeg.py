from __future__ import annotations

import shutil
from typing import Callable

from analyst.env import get_env_value


def resolve_ffmpeg_binary(which: Callable[[str], str | None] = shutil.which) -> str:
    configured = get_env_value("ANALYST_FFMPEG_BINARY", "FFMPEG_BINARY", default="").strip()
    if configured:
        return configured

    system_binary = which("ffmpeg")
    if system_binary:
        return system_binary

    try:
        import imageio_ffmpeg
    except ImportError:
        return ""

    try:
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return ""
