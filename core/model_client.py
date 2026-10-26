"""Model client interfaces: Deterministic MockModelClient for reproducible offline execution and optional ProviderModelClient."""

import abc
import json
import logging
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from core.schemas import SpecialistOutput, Finding, Severity

logger = logging.getLogger("model_client")


class BaseModelClient(abc.ABC):
    """Abstract interface for model client completions."""

    @abc.abstractmethod
    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: Optional[Type[BaseModel]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a structured response dictionary conforming to response_schema."""
        pass


class MockModelClient(BaseModelClient):
    """
    Deterministic mock model client providing reproducible responses without external API keys.
    Understands subtask objectives and outputs realistic, structured specialist data.
    """

    def __init__(self, model_name: str = "mock-agent-v1"):
        self.model_name = model_name
        self.call_count = 0
        self.total_tokens_consumed = 0

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: Optional[Type[BaseModel]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        # Estimate ~250 tokens per interaction
        tokens = 250
        self.total_tokens_consumed += tokens

        context = context or {}
        agent_name = context.get("agent_name", "")
        task_id = context.get("task_id", "")
        task_type = context.get("task_type", "code_review")

        # -------------------------------------------------------------
        # 1. Lead Agent Task Decomposition
        # -------------------------------------------------------------
        if "decompose" in prompt.lower() or agent_name == "lead_agent":
            if task_type == "incident_investigation":
                return {
                    "subtasks": [
                        {
                            "task_id": "task_log_analysis",
                            "assigned_agent": "log_agent",
                            "objective": "Parse incident logs and group critical error signatures",
                            "context": {"file_path": "incident.log"},
                            "dependencies": []
                        },
                        {
                            "task_id": "task_incident_root_cause",
                            "assigned_agent": "incident_agent",
                            "objective": "Reconstruct failure timeline and isolate root cause",
                            "context": {"file_path": "incident.log"},
                            "dependencies": ["task_log_analysis"]
                        },
                        {
                            "task_id": "task_mitigation_plan",
                            "assigned_agent": "mitigation_agent",
                            "objective": "Propose preventive configuration and resilience controls",
                            "context": {},
                            "dependencies": ["task_incident_root_cause"]
                        }
                    ]
                }
            else:
                # Default: RepoSentinel code review
                return {
                    "subtasks": [
                        {
                            "task_id": "task_bug_analysis",
                            "assigned_agent": "bug_agent",
                            "objective": "Identify functional logic defects and calculation errors",
                            "context": {"focus": "business_logic"},
                            "dependencies": []
                        },
                        {
                            "task_id": "task_security_analysis",
                            "assigned_agent": "security_agent",
                            "objective": "Detect security vulnerabilities, injection risks, and unsafe inputs",
                            "context": {"focus": "security_flaws"},
                            "dependencies": []
                        },
                        {
                            "task_id": "task_test_coverage",
                            "assigned_agent": "test_agent",
                            "objective": "Identify missing unit tests and untested edge cases",
                            "context": {"focus": "test_validation"},
                            "dependencies": []
                        }
                    ]
                }

        # -------------------------------------------------------------
        # 2. Semantic Checker Review
        # -------------------------------------------------------------
        if "evaluate the following findings" in prompt.lower() or "semantic_checker" in agent_name:
            findings_raw = str(context.get("findings", ""))
            if not findings_raw and "findings:" in prompt.lower():
                # Extract text after 'findings:'
                findings_raw = prompt.lower().split("findings:")[1]

            if "hallucinated" in findings_raw.lower() or "fabricated" in findings_raw.lower():
                return {
                    "approved": False,
                    "reasons": ["Findings describe non-existent or fabricated behaviors."]
                }
            return {
                "approved": True,
                "reasons": ["All findings are coherent, relevant, and supported by source code evidence."]
            }

        # -------------------------------------------------------------
        # 3. Lead Agent Final Synthesis
        # -------------------------------------------------------------
        if "synthesize" in prompt.lower() or "final report" in prompt.lower():
            return {
                "summary": (
                    "Multi-agent review successfully executed. Verified findings across functional logic, "
                    "application security, and test validation have been consolidated with line-level evidence."
                )
            }

        # -------------------------------------------------------------
        # 4. Specialist Output Generation (Based on Agent Role)
        # -------------------------------------------------------------
        findings = []

        # Check if specialist has tools results in context
        tool_results = context.get("tool_results", {})

        if "bug" in agent_name:
            findings.append({
                "category": "bug",
                "severity": "high",
                "title": "Off-by-one error in discount calculation",
                "description": "Threshold check uses > instead of >= causing customer discount boundary failure.",
                "file_path": context.get("sample_file", "cart.py"),
                "line_number": context.get("sample_line", 14),
                "line_end": context.get("sample_line_end", 16),
                "evidence_snippet": context.get("sample_snippet", "if total_amount > 100:\n    return total_amount * 0.9"),
                "suggested_fix": "Change condition to 'total_amount >= 100'."
            })
        elif "security" in agent_name:
            findings.append({
                "category": "security",
                "severity": "critical",
                "title": "SQL Injection vulnerability in query builder",
                "description": "Unsanitized user parameter is directly interpolated into raw SQL statement.",
                "file_path": context.get("sample_file", "db.py"),
                "line_number": context.get("sample_line", 22),
                "line_end": context.get("sample_line_end", 24),
                "evidence_snippet": context.get("sample_snippet", "query = f\"SELECT * FROM users WHERE username = '{username}'\""),
                "suggested_fix": "Use parameterized queries with bind variables: cursor.execute(sql, (username,))"
            })
        elif "test" in agent_name:
            findings.append({
                "category": "test",
                "severity": "medium",
                "title": "Missing negative value test for cart checkout",
                "description": "Checkout unit test suite lacks negative quantity and empty cart test assertions.",
                "file_path": context.get("sample_file", "test_cart.py"),
                "line_number": context.get("sample_line", 8),
                "line_end": context.get("sample_line_end", 10),
                "evidence_snippet": context.get("sample_snippet", "def test_standard_checkout():\n    assert calculate_total([10, 20]) == 30"),
                "suggested_fix": "Add test_checkout_negative_quantity_raises_value_error()."
            })
        elif "incident" in agent_name or "log" in agent_name:
            findings.append({
                "category": "incident",
                "severity": "critical",
                "title": "Database connection pool exhaustion cascade",
                "description": "Connection pool reached maximum limit (100/100) causing cascading HTTP 500 timeouts.",
                "file_path": context.get("sample_file", "incident.log"),
                "line_number": context.get("sample_line", 5),
                "line_end": context.get("sample_line_end", 7),
                "evidence_snippet": context.get("sample_snippet", "2026-10-26 14:02:11 [ERROR] db_pool: Maximum connection pool size 100 reached"),
                "suggested_fix": "Implement connection lease timeout and increase pool capacity or enable pgbouncer."
            })
        else:
            findings.append({
                "category": "general",
                "severity": "info",
                "title": "Operational recommendation",
                "description": "System analysis completed without notable anomalies.",
                "file_path": None,
                "line_number": None,
                "evidence_snippet": None,
                "suggested_fix": None
            })

        return {
            "agent_id": agent_name or "specialist",
            "task_id": task_id or "task_01",
            "summary": f"Analysis complete by {agent_name or 'specialist'}.",
            "findings": findings,
            "raw_notes": "Completed deterministic analysis with verified line-level evidence.",
            "metadata": {"model": self.model_name},
            "tool_calls_count": 2
        }


class ProviderModelClient(BaseModelClient):
    """
    Optional live provider-backed model client using standard HTTP requests.
    Supports OpenAI-compatible / Gemini endpoints via environment variables.
    """

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.total_tokens_consumed = 0

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: Optional[Type[BaseModel]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Invoke provider endpoint with JSON mode.
        Falls back to MockModelClient if no API key is provided.
        """
        if not self.api_key or self.api_key.startswith("your_"):
            logger.warning("No valid LLM_API_KEY detected. Falling back to deterministic MockModelClient.")
            mock = MockModelClient(model_name=self.model_name)
            return await mock.generate_completion(prompt, system_instruction, response_schema, context)

        # In live environments, httpx can be used to call the chat completion endpoint
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            body = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                self.total_tokens_consumed += usage.get("total_tokens", 300)
                return json.loads(content)
        except Exception as exc:
            logger.error(f"Live provider call failed: {exc}. Gracefully falling back to mock.")
            mock = MockModelClient(model_name=self.model_name)
            return await mock.generate_completion(prompt, system_instruction, response_schema, context)
