"""AST-based code validation for the sandbox.

Validates Python code *before* it reaches Docker, catching dangerous
patterns early and providing clear error messages to the LLM.
"""

from __future__ import annotations

import ast

FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "os", "subprocess", "socket", "shutil", "ctypes", "sys", "signal",
    "multiprocessing", "threading", "http", "urllib", "ftplib", "smtplib",
    "telnetlib", "pathlib", "importlib", "pickle", "shelve", "webbrowser",
    "code", "codeop", "compileall",
})

FORBIDDEN_BUILTINS: frozenset[str] = frozenset({
    "exec", "eval", "compile", "__import__", "open",
    "breakpoint", "exit", "quit", "input",
})

FORBIDDEN_DUNDERS: frozenset[str] = frozenset({
    "__subclasses__", "__globals__", "__code__", "__builtins__",
    "__import__", "__loader__", "__spec__",
})


class PolicyViolation(ValueError):
    """Raised when submitted code violates the sandbox security policy."""


def validate_code(code: str) -> None:
    """Parse and validate Python code against the sandbox policy.

    Raises ``PolicyViolation`` on the first violation found.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise PolicyViolation(f"Syntax error: {exc}") from exc

    for node in ast.walk(tree):
        _check_imports(node)
        _check_calls(node)
        _check_attributes(node)


def _check_imports(node: ast.AST) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in FORBIDDEN_MODULES:
                raise PolicyViolation(f"Importing '{alias.name}' is not allowed.")
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_MODULES:
                raise PolicyViolation(f"Importing from '{node.module}' is not allowed.")


def _check_calls(node: ast.AST) -> None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in FORBIDDEN_BUILTINS:
            raise PolicyViolation(f"Calling '{node.func.id}()' is not allowed.")


def _check_attributes(node: ast.AST) -> None:
    if isinstance(node, ast.Attribute):
        if node.attr in FORBIDDEN_DUNDERS:
            raise PolicyViolation(f"Accessing '{node.attr}' is not allowed.")
