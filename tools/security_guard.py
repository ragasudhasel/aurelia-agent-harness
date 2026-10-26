"""Tool registry, permission enforcement, prompt-injection defense, and secret redaction."""

import inspect
import logging
import re
from typing import Callable, Dict, Any, List, Optional, Tuple
from tools.safe_file_access import SecurityViolationError

logger = logging.getLogger("security_guard")


class PermissionDeniedError(Exception):
    """Raised when an agent attempts an unauthorized tool action."""
    pass


class HumanApprovalDeniedError(PermissionDeniedError):
    """Raised when a risky tool action is rejected by human approval."""
    pass


# Deterministic prompt-injection signatures
INJECTION_SIGNATURES = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"override\s+(all\s+)?permissions",
    r"grant\s+(root|admin|superuser)\s+access",
    r"system\s+prompt\s+leak",
    r"reveal\s+(the\s+)?(api_key|secret|password|credentials)",
    r"exfiltrate\s+(to|data)",
    r"bypass\s+(safety|security|policy)",
    r"drop\s+database",
    r"rm\s+-rf\s+/",
    r"you\s+are\s+now\s+in\s+unrestricted\s+mode",
]

# Sensitive pattern regexes for redaction
REDACTION_PATTERNS = [
    (re.compile(r"(sk-[a-zA-Z0-9_-]{20,})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9\._\-]{20,}", re.IGNORECASE), r"\1[REDACTED_BEARER_TOKEN]"),
    (re.compile(r"(password\s*[:=]\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1[REDACTED_PASSWORD]\2"),
    (re.compile(r"(secret\s*[:=]\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1[REDACTED_SECRET]\2"),
]


def detect_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
    """
    Deterministically scan text for prompt injection, jailbreak attempts, or unauthorized instruction overrides.
    Returns (is_injected, matched_pattern).
    """
    if not text:
        return False, None

    for pattern in INJECTION_SIGNATURES:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return True, match.group(0)

    return False, None


def redact_sensitive_data(text: str) -> str:
    """Redact API keys, tokens, and credentials from logs, traces, and model prompts."""
    if not isinstance(text, str):
        return text

    redacted = text
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class ToolRegistry:
    """
    Central tool registry enforcing:
      1. Per-agent tool allowlists.
      2. Human approval for operations classified as risky.
      3. Automatic audit logging.
    """

    def __init__(self, human_approval_callback: Optional[Callable[[str, str, Dict[str, Any]], bool]] = None):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self.human_approval_callback = human_approval_callback
        self.invocation_log: List[Dict[str, Any]] = []
        self.trace_logger: Optional[Any] = None

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        is_risky: bool = False
    ) -> None:
        """Register a tool with metadata and risk classification."""
        self._tools[name] = {
            "name": name,
            "func": func,
            "description": description,
            "is_risky": is_risky,
            "signature": inspect.signature(func),
        }
        logger.debug(f"Registered tool '{name}' (risky={is_risky})")

    def is_tool_registered(self, name: str) -> bool:
        return name in self._tools

    async def execute_tool(
        self,
        agent_id: str,
        permitted_tools: List[str],
        tool_name: str,
        **kwargs
    ) -> Any:
        """
        Execute a tool after verifying agent permissions and required human approvals.
        """
        # 1. Verify tool exists
        if tool_name not in self._tools:
            if self.trace_logger:
                self.trace_logger.log_event("tool_permission_denied", agent_id=agent_id, details={"tool_name": tool_name, "reason": "unregistered"})
            raise PermissionDeniedError(f"Tool '{tool_name}' is not registered in the system.")

        tool_meta = self._tools[tool_name]

        # 2. Verify agent permission allowlist
        if tool_name not in permitted_tools:
            logger.warning(f"SECURITY ALERT: Agent '{agent_id}' denied access to unauthorized tool '{tool_name}'")
            if self.trace_logger:
                self.trace_logger.log_event("tool_permission_denied", agent_id=agent_id, details={"tool_name": tool_name, "reason": "unauthorized"})
            raise PermissionDeniedError(
                f"Agent '{agent_id}' does not have permission to execute tool '{tool_name}'. "
                f"Permitted tools: {permitted_tools}"
            )

        # 3. Handle risky tools requiring human approval
        if tool_meta["is_risky"]:
            approved = False
            if self.human_approval_callback:
                approved = self.human_approval_callback(agent_id, tool_name, kwargs)
            if not approved:
                logger.warning(f"HUMAN APPROVAL DENIED: Risky tool '{tool_name}' rejected for agent '{agent_id}'")
                if self.trace_logger:
                    self.trace_logger.log_event("tool_approval_denied", agent_id=agent_id, details={"tool_name": tool_name, "reason": "human_approval_denied"})
                raise HumanApprovalDeniedError(
                    f"Execution of risky tool '{tool_name}' was denied by human supervisor or approval was unavailable."
                )

        # 4. Execute tool safely
        func = tool_meta["func"]
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                result = func(**kwargs)

            self.invocation_log.append({
                "agent_id": agent_id,
                "tool_name": tool_name,
                "status": "success",
                "args": redact_sensitive_data(str(kwargs)),
            })
            if self.trace_logger:
                self.trace_logger.log_event("tool_call", agent_id=agent_id, details={"tool_name": tool_name, "status": "success", "args": redact_sensitive_data(str(kwargs))})
            return result
        except SecurityViolationError:
            self.invocation_log.append({
                "agent_id": agent_id,
                "tool_name": tool_name,
                "status": "security_violation",
                "args": redact_sensitive_data(str(kwargs)),
            })
            if self.trace_logger:
                self.trace_logger.log_event("tool_security_violation", agent_id=agent_id, details={"tool_name": tool_name, "args": redact_sensitive_data(str(kwargs))})
            raise
        except Exception as exc:
            self.invocation_log.append({
                "agent_id": agent_id,
                "tool_name": tool_name,
                "status": "error",
                "error": str(exc),
            })
            if self.trace_logger:
                self.trace_logger.log_event("tool_error", agent_id=agent_id, details={"tool_name": tool_name, "error": str(exc)})
            raise
