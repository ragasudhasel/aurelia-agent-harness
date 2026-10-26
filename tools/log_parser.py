"""Application incident log parsing, error grouping, and timeline reconstruction tools."""

import re
from typing import List, Dict, Any
from tools.safe_file_access import resolve_safe_path

# Standard log line pattern: YYYY-MM-DD HH:MM:SS [LEVEL] Component: Message
LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"\[(?P<level>[A-Z]+)\]\s+"
    r"(?:(?P<component>[\w\.\-]+):\s+)?"
    r"(?P<message>.*)$"
)


def parse_log_file(workspace_root: str, file_path: str) -> List[Dict[str, Any]]:
    """
    Parse an incident log file into structured event objects.
    Extracts timestamps, severity levels, components, and messages.
    """
    safe_path = resolve_safe_path(workspace_root, file_path)
    if not safe_path.is_file():
        raise FileNotFoundError(f"Log file not found: '{file_path}'")

    parsed_events = []
    current_event = None

    with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.rstrip("\r\n")
            match = LOG_PATTERN.match(line_str)
            if match:
                if current_event:
                    parsed_events.append(current_event)
                current_event = {
                    "line_number": line_num,
                    "timestamp": match.group("timestamp"),
                    "level": match.group("level").upper(),
                    "component": match.group("component") or "system",
                    "message": match.group("message"),
                    "stack_trace": [],
                }
            elif current_event:
                # Continuation or stack trace line
                current_event["stack_trace"].append(line_str)
            else:
                # Unstructured prefix line
                parsed_events.append({
                    "line_number": line_num,
                    "timestamp": "UNKNOWN",
                    "level": "INFO",
                    "component": "raw",
                    "message": line_str,
                    "stack_trace": [],
                })

    if current_event:
        parsed_events.append(current_event)

    return parsed_events


def group_errors(parsed_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Group log errors by message signature / error category, tracking counts and affected components.
    """
    grouped: Dict[str, Any] = {}

    for event in parsed_logs:
        if event.get("level") in ("ERROR", "CRITICAL", "FATAL"):
            msg = event.get("message", "")
            # Normalize error key by stripping variable numbers/hex ids
            signature = re.sub(r"0x[0-9a-fA-F]+|\b\d+\b", "<ID>", msg[:100])

            if signature not in grouped:
                grouped[signature] = {
                    "signature": signature,
                    "count": 0,
                    "first_seen": event.get("timestamp"),
                    "last_seen": event.get("timestamp"),
                    "component": event.get("component"),
                    "sample_line": event.get("line_number"),
                    "sample_message": msg,
                }
            grouped[signature]["count"] += 1
            grouped[signature]["last_seen"] = event.get("timestamp")

    return grouped


def reconstruct_timeline(parsed_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reconstruct a chronological timeline of warning and error events.
    """
    notable = [
        e for e in parsed_logs
        if e.get("level") in ("WARN", "WARNING", "ERROR", "CRITICAL")
    ]
    # Stable sort by line_number preserving occurrence order
    notable.sort(key=lambda x: x.get("line_number", 0))
    return notable
