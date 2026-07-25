from agents.workflow_models import (
    ExecutionResultStatus,
    ExecutorStepResult,
    PlanStep,
    ValidationDecision,
)


class ExecutionResultValidator:
    """Validates independently of the executor's self-reported status."""

    def validate(self, step: PlanStep, result: ExecutorStepResult) -> ValidationDecision:
        if result.plan_id == "" or result.step_id != step.id:
            return ValidationDecision(False, "Result identifiers do not match the step.")
        if result.status != ExecutionResultStatus.SUCCESS:
            return ValidationDecision(
                False, f"Executor reported {result.status.value}.",
                missing_criteria=list(step.validation_criteria),
            )
        if not result.evidence:
            return ValidationDecision(
                False, "Success was reported without evidence.",
                missing_criteria=list(step.validation_criteria),
            )
        evidence_text = " ".join(
            f"{item.description} {item.value}" for item in result.evidence
        ).lower()
        missing = [
            criterion for criterion in step.validation_criteria
            if not self._criterion_supported(criterion, evidence_text)
        ]
        if missing:
            return ValidationDecision(
                False, "Evidence does not support every validation criterion.",
                checked_criteria=[
                    item for item in step.validation_criteria if item not in missing
                ],
                missing_criteria=missing,
            )
        return ValidationDecision(
            True, "Executor evidence satisfies the step.",
            checked_criteria=list(step.validation_criteria),
        )

    @staticmethod
    def _criterion_supported(criterion: str, evidence_text: str) -> bool:
        words = [word.strip(".,:;()[]").lower() for word in criterion.split()]
        meaningful = [word for word in words if len(word) > 3]
        return not meaningful or any(word in evidence_text for word in meaningful)
