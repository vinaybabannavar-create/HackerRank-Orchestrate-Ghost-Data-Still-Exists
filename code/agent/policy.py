from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

OPERATION_SORT_ORDER = {
    # Phase 1: FINDING
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
    # Phase 2: REMEDIATION
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,
    # Phase 3: VERIFICATION
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}

PHASE_SORT_ORDER = {
    "FINDING": 1,
    "REMEDIATION": 2,
    "VERIFICATION": 3,
}


@dataclass
class Step:
    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_no": self.step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


def sort_steps(steps: List[Step]) -> List[Step]:
    """Sort steps strictly according to problem_statement.md:
    1. phase order: FINDING -> REMEDIATION -> VERIFICATION
    2. operation order within phase (from Allowed Operations table)
    3. system_id ascending
    4. resource_id ascending
    Then re-number step_no starting at 1.
    """
    def sort_key(s: Step):
        p_order = PHASE_SORT_ORDER.get(s.phase, 99)
        op_order = OPERATION_SORT_ORDER.get(s.operation, 99)
        return (p_order, op_order, s.system_id, s.resource_id)

    sorted_list = sorted(steps, key=sort_key)
    renumbered = []
    for idx, s in enumerate(sorted_list, start=1):
        renumbered.append(
            Step(
                step_no=idx,
                phase=s.phase,
                system_id=s.system_id,
                resource_id=s.resource_id,
                operation=s.operation,
                state=s.state,
                evidence_id=s.evidence_id,
            )
        )
    return renumbered
