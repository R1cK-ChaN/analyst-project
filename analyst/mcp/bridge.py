from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analyst.env import PROJECT_ROOT


@dataclass(frozen=True)
class ClaudeCodeMcpConfig:
    tool_names: tuple[str, ...]
    db_path: str | None = None
    server_name: str = "analyst"
    strict: bool = True

    def to_json(self) -> dict[str, Any]:
        validated = _normalize_tool_names(self.tool_names)
        src_path = str(PROJECT_ROOT / "src")
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = src_path if not existing_pythonpath else f"{src_path}{os.pathsep}{existing_pythonpath}"
        env = {
            "PYTHONPATH": pythonpath,
            "PYTHONUNBUFFERED": "1",
            "ANALYST_MCP_TOOL_NAMES": ",".join(validated),
        }
        if self.db_path:
            env["ANALYST_MCP_DB_PATH"] = self.db_path
        return {
            "mcpServers": {
                self.server_name: {
                    "command": sys.executable,
                    "args": ["-m", "analyst.mcp.server"],
                    "env": env,
                }
            }
        }

    def write_temp_file(self) -> tuple[str, str]:
        temp_dir = tempfile.mkdtemp(prefix="analyst-mcp-config-")
        config_path = Path(temp_dir) / "analyst.mcp.json"
        config_path.write_text(
            json.dumps(self.to_json(), ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return str(config_path), temp_dir


def _normalize_tool_names(tool_names: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for name in tool_names:
        normalized = str(name).strip()
        if not normalized or normalized in ordered:
            continue
        ordered.append(normalized)
    return tuple(ordered)
