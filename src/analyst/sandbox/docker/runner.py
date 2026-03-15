#!/usr/bin/env python3
"""In-container code executor for the analyst sandbox.

Protocol
--------
stdin  <- JSON: {"code": "...", "data": {...}}
stdout -> JSON: {"success": bool, "result": ..., "stdout": "...", "error": ""}

The executed code should store its final answer in a variable called ``result``.
Any ``print()`` output is captured separately in the ``stdout`` field.
"""

from __future__ import annotations

import io
import json
import sys
import traceback

# Force non-interactive matplotlib backend before user code can import it.
import matplotlib
matplotlib.use("Agg")


def _serialize(obj):
    """Convert numpy / pandas objects to JSON-safe Python types."""
    if obj is None:
        return None

    type_name = type(obj).__name__
    module = type(obj).__module__ or ""

    # numpy scalars
    if module.startswith("numpy") and hasattr(obj, "item"):
        return obj.item()

    # numpy ndarray
    if module.startswith("numpy") and hasattr(obj, "tolist"):
        return obj.tolist()

    # pandas DataFrame
    if type_name == "DataFrame" and hasattr(obj, "to_dict"):
        return obj.to_dict(orient="records")

    # pandas Series
    if type_name == "Series" and hasattr(obj, "to_dict"):
        return obj.to_dict()

    # plain containers — recurse
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]

    # fallback: try direct JSON encoding
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _write(success=False, error=f"Invalid JSON input: {exc}")
        return

    code = payload.get("code", "")
    data = payload.get("data", {})

    captured = io.StringIO()
    namespace: dict = {"data": data}

    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        exec(code, namespace)  # noqa: S102
        result = namespace.get("result")
        sys.stdout = old_stdout
        _write(success=True, result=_serialize(result), stdout=captured.getvalue())
    except Exception:
        sys.stdout = old_stdout
        _write(success=False, stdout=captured.getvalue(), error=traceback.format_exc())


def _write(
    *,
    success: bool,
    result=None,
    stdout: str = "",
    error: str = "",
) -> None:
    json.dump(
        {"success": success, "result": result, "stdout": stdout, "error": error},
        sys.stdout,
        ensure_ascii=False,
        default=str,
    )
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
