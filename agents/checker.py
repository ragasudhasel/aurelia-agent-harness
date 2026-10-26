"""Two-layer Output Checker: Layer 1 Deterministic Verification and Layer 2 Semantic Review."""

import logging
from typing import List, Optional
from core.config import CheckerConfig
from core.schemas import SpecialistOutput, CheckerDecision, FailedCheckDetail, Finding
from core.model_client import BaseModelClient
from tools.safe_file_access import resolve_safe_path, SecurityViolationError

logger = logging.getLogger("output_checker")


class OutputChecker:
    """
    Dedicated checker enforcing evidence fidelity before Lead Agent uses findings.
    Fails closed on missing evidence or validation errors.
    """

    def __init__(
        self,
        workspace_root: str,
        config: CheckerConfig,
        model_client: BaseModelClient
    ):
        self.workspace_root = workspace_root
        self.config = config
        self.model_client = model_client

    def validate_deterministic(self, output: SpecialistOutput) -> List[FailedCheckDetail]:
        """
        Layer 1: Deterministic check of file paths, line bounds, and evidence snippets against physical files.
        """
        failed_checks: List[FailedCheckDetail] = []

        if not output.findings and not output.summary:
            failed_checks.append(FailedCheckDetail(
                rule="empty_output",
                message="Specialist produced neither findings nor summary.",
                offending_value=None,
                suggested_action="Provide at least an executive summary or identified findings."
            ))

        for idx, finding in enumerate(output.findings, start=1):
            # If finding points to a file, verify physical existence and content
            if finding.file_path:
                try:
                    safe_path = resolve_safe_path(self.workspace_root, finding.file_path)
                    if not safe_path.is_file():
                        failed_checks.append(FailedCheckDetail(
                            rule="nonexistent_file_path",
                            message=f"Finding '{finding.title}' references non-existent file: '{finding.file_path}'",
                            offending_value=finding.file_path,
                            suggested_action="Verify file path against workspace root."
                        ))
                        continue

                    # Read actual file lines
                    with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                        file_lines = f.readlines()
                    total_lines = len(file_lines)

                    # Validate line number bounds
                    if finding.line_number is not None:
                        if finding.line_number < 1 or finding.line_number > total_lines:
                            failed_checks.append(FailedCheckDetail(
                                rule="invalid_line_number",
                                message=(
                                    f"Line number {finding.line_number} is out of bounds for file '{finding.file_path}' "
                                    f"(total lines: {total_lines})."
                                ),
                                offending_value=str(finding.line_number),
                                suggested_action=f"Ensure line_number is between 1 and {total_lines}."
                            ))
                            continue

                    # Validate line_end
                    if finding.line_end is not None and finding.line_end > total_lines:
                        failed_checks.append(FailedCheckDetail(
                            rule="invalid_line_end",
                            message=f"line_end {finding.line_end} exceeds total lines ({total_lines}).",
                            offending_value=str(finding.line_end),
                            suggested_action=f"Adjust line_end to <= {total_lines}."
                        ))

                    # Validate evidence snippet against file contents
                    if finding.evidence_snippet:
                        snippet_clean = "\n".join(
                            line.strip() for line in finding.evidence_snippet.splitlines() if line.strip()
                        )
                        file_content_clean = "\n".join(
                            line.strip() for line in file_lines if line.strip()
                        )

                        # Substring check with normalized whitespace
                        if snippet_clean not in file_content_clean:
                            failed_checks.append(FailedCheckDetail(
                                rule="mismatched_evidence_snippet",
                                message=(
                                    f"Evidence snippet in finding '{finding.title}' does not match the actual contents "
                                    f"of '{finding.file_path}'."
                                ),
                                offending_value=finding.evidence_snippet[:100],
                                suggested_action="Provide exact, verbatim code snippet from the file."
                            ))

                except SecurityViolationError as sec_err:
                    failed_checks.append(FailedCheckDetail(
                        rule="security_path_violation",
                        message=str(sec_err),
                        offending_value=finding.file_path,
                        suggested_action="File path must be strictly inside the workspace."
                    ))
                except Exception as exc:
                    failed_checks.append(FailedCheckDetail(
                        rule="unexpected_validation_error",
                        message=f"Error inspecting file '{finding.file_path}': {exc}",
                        offending_value=finding.file_path,
                        suggested_action="Ensure file is readable."
                    ))

        return failed_checks

    async def validate_semantic(self, output: SpecialistOutput) -> List[FailedCheckDetail]:
        """
        Layer 2: Semantic review using model client to check relevance and consistency.
        Fails closed on model failure.
        """
        if not self.config.semantic_enabled or not output.findings:
            return []

        prompt = (
            f"Evaluate the following findings reported by specialist '{output.agent_id}':\n"
            f"Summary: {output.summary}\n"
            f"Findings: {[f.model_dump() for f in output.findings]}\n\n"
            f"Are these findings coherent, relevant, and not hallucinated? Respond in JSON with "
            f"{{'approved': bool, 'reasons': list[str]}}."
        )

        try:
            findings_dicts = [f.model_dump() for f in output.findings]
            res = await self.model_client.generate_completion(
                prompt=prompt,
                system_instruction="You are a strict code quality and security auditor.",
                context={"agent_name": "semantic_checker", "findings": findings_dicts}
            )
            approved = res.get("approved", False)
            if not approved:
                reasons = res.get("reasons", ["Findings failed semantic consistency review."])
                return [
                    FailedCheckDetail(
                        rule="semantic_inconsistency",
                        message=r,
                        offending_value=None,
                        suggested_action="Revise findings to be consistent with task objective."
                    )
                    for r in reasons
                ]
            return []
        except Exception as exc:
            logger.error(f"Semantic checker call failed: {exc}")
            if self.config.fail_closed:
                return [FailedCheckDetail(
                    rule="semantic_checker_failure",
                    message=f"Semantic review could not complete: {exc}. Failing closed.",
                    offending_value=None,
                    suggested_action="Retry review or check model provider."
                )]
            return []

    async def check_output(self, output: SpecialistOutput, current_cycle: int = 0) -> CheckerDecision:
        """
        Execute both Layer 1 and Layer 2 validation.
        Returns a structured CheckerDecision.
        """
        all_failures: List[FailedCheckDetail] = []

        # 1. Deterministic checks
        if self.config.deterministic_enabled:
            det_failures = self.validate_deterministic(output)
            all_failures.extend(det_failures)

        # 2. Semantic checks (only if deterministic checks passed)
        if not all_failures and self.config.semantic_enabled:
            sem_failures = await self.validate_semantic(output)
            all_failures.extend(sem_failures)

        approved = len(all_failures) == 0

        decision = CheckerDecision(
            approved=approved,
            rejection_cycle=current_cycle,
            failed_checks=all_failures,
            semantic_notes="Validation passed all checks." if approved else f"Failed {len(all_failures)} checks."
        )

        if not approved:
            logger.warning(
                f"Output from '{output.agent_id}' REJECTED on cycle {current_cycle}: "
                f"{[f.message for f in all_failures]}"
            )
        else:
            logger.info(f"Output from '{output.agent_id}' APPROVED by checker on cycle {current_cycle}.")

        return decision
