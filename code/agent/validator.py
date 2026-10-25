from __future__ import annotations

import csv
import json
from typing import Any, Dict, List, Optional, Tuple

from agent.policy import OPERATION_SORT_ORDER, PHASE_SORT_ORDER

ALLOWED_TRIPLES = {
    # Phase: FINDING
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    # Phase: REMEDIATION
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    # Phase: VERIFICATION
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}


class OutputValidationError(Exception):
    pass


def validate_step(step: Dict[str, Any], expected_step_no: int, deletion_status: str) -> None:
    required_keys = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
    actual_keys = set(step.keys())
    if not required_keys.issubset(actual_keys):
        missing = required_keys - actual_keys
        raise OutputValidationError(f"Step {step.get('step_no')} missing required keys: {missing}")

    step_no = step["step_no"]
    if step_no != expected_step_no:
        raise OutputValidationError(f"Expected step_no {expected_step_no}, got {step_no}")

    phase = step["phase"]
    op = step["operation"]
    st = step["state"]
    triple = (phase, op, st)
    if triple not in ALLOWED_TRIPLES:
        raise OutputValidationError(f"Invalid (phase, operation, state) triple: {triple}")

    ev_id = step.get("evidence_id", "")
    if deletion_status == "COMPLETE":
        if phase != "VERIFICATION":
            raise OutputValidationError(f"COMPLETE case contains non-VERIFICATION step: {phase}")
        if not ev_id:
            raise OutputValidationError(f"COMPLETE verification step missing evidence_id: {step}")
    elif deletion_status == "INCOMPLETE":
        if phase == "FINDING":
            if not ev_id:
                raise OutputValidationError(f"INCOMPLETE finding missing evidence_id: {step}")
        else:
            if ev_id != "":
                raise OutputValidationError(f"INCOMPLETE remediation/verification must have empty evidence_id, got: {ev_id}")


def validate_steps_order(steps: List[Dict[str, Any]]) -> None:
    seen_steps = set()
    for idx, s in enumerate(steps, start=1):
        step_sig = (s["phase"], s["operation"], s["system_id"], s["resource_id"], s["state"])
        if step_sig in seen_steps:
            raise OutputValidationError(f"Duplicate step found: {step_sig}")
        seen_steps.add(step_sig)

        if idx > 1:
            prev = steps[idx - 2]
            prev_p_order = PHASE_SORT_ORDER.get(prev["phase"], 99)
            curr_p_order = PHASE_SORT_ORDER.get(s["phase"], 99)
            if curr_p_order < prev_p_order:
                raise OutputValidationError(f"Phase ordering violation: {prev['phase']} before {s['phase']}")
            elif curr_p_order == prev_p_order:
                prev_op_order = OPERATION_SORT_ORDER.get(prev["operation"], 99)
                curr_op_order = OPERATION_SORT_ORDER.get(s["operation"], 99)
                if curr_op_order < prev_op_order:
                    raise OutputValidationError(f"Operation ordering violation: {prev['operation']} before {s['operation']}")
                elif curr_op_order == prev_op_order:
                    if s["system_id"] < prev["system_id"]:
                        raise OutputValidationError(f"system_id ordering violation: {prev['system_id']} before {s['system_id']}")
                    elif s["system_id"] == prev["system_id"]:
                        if s["resource_id"] < prev["resource_id"]:
                            raise OutputValidationError(f"resource_id ordering violation: {prev['resource_id']} before {s['resource_id']}")


def validate_case_row(case_id: str, deletion_status: str, steps_json_str: str) -> None:
    if deletion_status not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
        raise OutputValidationError(f"Invalid deletion_status '{deletion_status}' for {case_id}")

    try:
        steps = json.loads(steps_json_str)
    except Exception as e:
        raise OutputValidationError(f"steps_json for {case_id} failed to parse: {e}")

    if not isinstance(steps, list):
        raise OutputValidationError(f"steps_json for {case_id} must be a JSON array")

    if deletion_status == "NOT_APPLICABLE":
        if len(steps) != 0:
            raise OutputValidationError(f"NOT_APPLICABLE case {case_id} must have empty steps_json, got {len(steps)} steps")
        return

    for idx, s in enumerate(steps, start=1):
        validate_step(s, idx, deletion_status)

    validate_steps_order(steps)


def validate_output_file(output_csv_path: str, expected_rows: int = 518) -> None:
    with open(output_csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    if not reader:
        raise OutputValidationError("output.csv is empty")

    header = reader[0]
    expected_header = ["case_id", "deletion_status", "steps_json"]
    if header != expected_header:
        raise OutputValidationError(f"Invalid header in output.csv: {header} vs {expected_header}")

    data_rows = reader[1:]
    if len(data_rows) != expected_rows:
        raise OutputValidationError(f"Expected {expected_rows} rows in output.csv, found {len(data_rows)}")

    case_ids = [r[0] for r in data_rows]
    sorted_case_ids = sorted(case_ids)
    if case_ids != sorted_case_ids:
        raise OutputValidationError("Rows in output.csv are not sorted by case_id")

    for row in data_rows:
        if len(row) != 3:
            raise OutputValidationError(f"Invalid row length ({len(row)}) for row: {row}")
        cid, status, steps_str = row
        validate_case_row(cid, status, steps_str)
