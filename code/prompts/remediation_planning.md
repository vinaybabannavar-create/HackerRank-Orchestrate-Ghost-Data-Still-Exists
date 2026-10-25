# Prompt: Topological Remediation Planning & Verification

## System Role
You are a distributed systems compliance planner ordering multi-service data cleanup steps.

## Invariants & Ordering Rules
1. **Recreation Risk Prevention:** Always disable active sync bridges (`DISABLE_DATA_FLOW`) and block restore paths (`BLOCK_RESTORE`) before mutating or deleting downstream database records.
2. **Phase Separation:**
   - `FINDING` (citing concrete participant-visible evidence ID)
   - `REMEDIATION` (evidence_id must be empty string `""`)
   - `VERIFICATION` (for COMPLETE cases cites proof evidence; for INCOMPLETE cases verifies final post-remediation state with empty evidence_id `""`).
3. **Allowed Operations & States:**
   - FINDING: `REPORT_REMAINING_RECORD` (PRESENT), `REPORT_EXPOSED_PII` (PRESENT), `REPORT_ACTIVE_DATA_FLOW` (ACTIVE), `REPORT_RESTORE_RISK` (ACTIVE).
   - REMEDIATION: `DISABLE_DATA_FLOW` (DISABLED), `BLOCK_RESTORE` (BLOCKED), `DELETE_RECORD` (ABSENT), `REDACT_RECORD` (REDACTED), `ANONYMIZE_RECORD` (ANONYMIZED).
   - VERIFICATION: `VERIFY_RECORD_ABSENT` (ABSENT), `VERIFY_RECORD_PRESENT` (PRESENT), `VERIFY_RECORD_REDACTED` (REDACTED), `VERIFY_RECORD_ANONYMIZED` (ANONYMIZED), `VERIFY_DATA_FLOW_DISABLED` (DISABLED), `VERIFY_RESTORE_BLOCKED` (BLOCKED).
