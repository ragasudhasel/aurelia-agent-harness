"""Safe file access utilities enforcing strict workspace boundaries, preventing path traversal and symlink escapes."""

import os
from pathlib import Path


class SecurityViolationError(Exception):
    """Raised when an operation violates security boundaries."""
    pass


def resolve_safe_path(workspace_root: str, relative_path: str) -> Path:
    """
    Resolve and validate that relative_path is strictly within workspace_root.
    Prevents path traversal ('../') and symlink escapes.
    Raises SecurityViolationError on escape attempt.
    """
    if not workspace_root:
        raise SecurityViolationError("workspace_root cannot be empty.")

    ws_path = Path(workspace_root).resolve()
    if not ws_path.exists():
        # Allow checking paths even if workspace root is freshly configured
        ws_path.mkdir(parents=True, exist_ok=True)

    # Sanitize input path
    cleaned_rel = relative_path.strip().lstrip("/\\")
    target_path = (ws_path / cleaned_rel).resolve()

    # Verify that target_path is within ws_path
    try:
        target_path.relative_to(ws_path)
    except ValueError:
        raise SecurityViolationError(
            f"Path traversal detected! Path '{relative_path}' resolves outside workspace root '{ws_path}'."
        )

    # Check symlinks: if target is a symlink, verify its real target is also inside workspace
    if target_path.is_symlink():
        real_target = Path(os.path.realpath(target_path)).resolve()
        try:
            real_target.relative_to(ws_path)
        except ValueError:
            raise SecurityViolationError(
                f"Symlink escape detected! Symlink '{relative_path}' points outside workspace root."
            )

    return target_path
