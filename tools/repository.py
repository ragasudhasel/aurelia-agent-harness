"""Repository inspection tools with safe boundary verification."""

import os
from typing import List, Dict, Any
from tools.safe_file_access import resolve_safe_path


def list_repository_files(workspace_root: str, pattern: str = "*") -> List[str]:
    """
    List permitted files in the workspace matching the specified pattern.
    Excludes hidden files, git metadata, and virtual environments.
    """
    ws = resolve_safe_path(workspace_root, ".")
    matches = []

    ignored_dirs = {".git", ".pytest_cache", "__pycache__", "venv", ".venv", "runs"}

    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, ws).replace("\\", "/")
            matches.append(rel_path)

    return sorted(matches)


def read_repository_file(workspace_root: str, file_path: str) -> str:
    """Read the complete text of a file within the permitted workspace."""
    safe_path = resolve_safe_path(workspace_root, file_path)
    if not safe_path.is_file():
        raise FileNotFoundError(f"File not found: '{file_path}' in workspace.")

    with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def get_line_numbered_snippet(
    workspace_root: str,
    file_path: str,
    start_line: int,
    end_line: int
) -> Dict[str, Any]:
    """
    Retrieve an exact snippet with line numbers (1-indexed, inclusive).
    Returns dict containing lines, raw snippet, and validity.
    """
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line < start_line:
        raise ValueError("end_line cannot be less than start_line")

    safe_path = resolve_safe_path(workspace_root, file_path)
    if not safe_path.is_file():
        raise FileNotFoundError(f"File not found: '{file_path}'")

    with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    total_lines = len(all_lines)
    if start_line > total_lines:
        raise IndexError(f"start_line {start_line} exceeds total file lines ({total_lines})")

    actual_end = min(end_line, total_lines)
    selected = all_lines[start_line - 1 : actual_end]

    numbered_lines = [
        f"{idx}: {line.rstrip()}"
        for idx, line in enumerate(selected, start=start_line)
    ]

    return {
        "file_path": file_path,
        "start_line": start_line,
        "end_line": actual_end,
        "total_file_lines": total_lines,
        "numbered_snippet": "\n".join(numbered_lines),
        "raw_snippet": "".join(selected),
    }


def run_permitted_test_command(workspace_root: str, command: str) -> Dict[str, Any]:
    """
    Mock runner for permitted unit tests or static analysis commands.
    Classified as RISKY in tool registry; requires explicit human approval.
    """
    # Enforce safe command allowlist
    permitted_commands = ["pytest", "python -m pytest", "flake8", "mypy", "ruff check"]
    if not any(command.strip().startswith(prefix) for prefix in permitted_commands):
        raise ValueError(f"Command '{command}' is not in the permitted static analysis or test allowlist.")

    return {
        "command": command,
        "status": "simulated_success",
        "output": f"[Simulated execution of '{command}' within {workspace_root}] All checks passed.",
        "return_code": 0
    }
