# Ghost Data Still Exists: Audit Engine Analysis & Notes

This document records the exact reverse-engineered mechanics, data models, schema invariants, and evidence mapping rules derived from comparing `dataset/sample_deletion_requests.csv` with `dataset/sample_output.csv` and analyzing the full dataset.

---

## 1. Identity Resolution & Identifier Graph

For each audit request:
1. **Request Identity**: The request provides an email address (`email`) and `request_text`.
2. **Current Identity**: Looked up in `dataset/user_identities.csv`:
   - `user_id`: Stable identifier (e.g., `user_01`, `user_43`).
   - `name`: Full customer name.
   - `email`: Current primary email.
   - `phone`: Contact phone number.
   - `email_hash`: SHA-256 hash of the email.
   - `updated_at`: Timestamp of latest identity snapshot.
3. **Historical Identity**: Looked up in `dataset/user_audit_log.csv`:
   - Changes to `email`, `phone`, `email_hash`.
   - The request email may match a historical email rather than the current one (e.g., Case 10, Case 12).
   - If a user changed email, both old and new emails, phone numbers, and hashes belong to the same `user_id`.
4. **Linkage to Systems & Evidence**:
   - `account_service`: Matched via `email`, historical email, `user_id`, or `account_<id>`.
   - `search_service`: Matched via `email`, historical email, or `name`.
   - `analytics_platform`: Matched via `email`, `user_id`, `phone`, or `email_hash`.
   - `support_platform`: Matched via `requester_email`, `customer_reference` (`user_id`), or support ticket reference.
   - `export_service`: Matched via `owner_email` or `customer_reference`.
   - `integration_service`: Matched via `customer_email` or `customer_reference`.
   - `backup_service`: Matched via `customer_reference` (`user_id`) or `customer_email`.
   - `security_service`: Matched via `subject_reference` (`user_id`).
   - `identity_service`: Matched via `subject_reference` (`user_id`) in `tombstone_<id>`.

---

## 2. Policy Mapping: `deletion_rules.csv` to Operations

`dataset/deletion_rules.csv` specifies 15 rules across data categories and conditions:

| Rule ID | Data Category | Condition | Required Action | Finding Operation (State) | Remediation Operation (State) | Verification Operation (State) |
|---|---|---|---|---|---|---|
| `rule_01` | `USER_PROFILE` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_02` | `SECONDARY_IDENTIFIER` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_03` | `SEARCH_INDEX_ENTRY` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_04` | `CACHE_ENTRY` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_05` | `SUPPORT_MESSAGE` | Conversation contains shared context | `REDACT` | `REPORT_EXPOSED_PII` (`PRESENT`) | `REDACT_RECORD` (`REDACTED`) | `VERIFY_RECORD_REDACTED` (`REDACTED`) |
| `rule_06` | `SUPPORT_ATTACHMENT` | Belongs only to deletion subject | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_07` | `ANALYTICS_PROFILE` | Record still attributable to user | `ANONYMIZE` | `REPORT_EXPOSED_PII` (`PRESENT`) | `ANONYMIZE_RECORD` (`ANONYMIZED`) | `VERIFY_RECORD_ANONYMIZED` (`ANONYMIZED`) |
| `rule_08` | `PRODUCT_TELEMETRY` | Record still attributable to user | `ANONYMIZE` | `REPORT_EXPOSED_PII` (`PRESENT`) | `ANONYMIZE_RECORD` (`ANONYMIZED`) | `VERIFY_RECORD_ANONYMIZED` (`ANONYMIZED`) |
| `rule_09` | `USER_EXPORT` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_10` | `MARKETING_PROFILE` | Always | `DELETE` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `rule_11` | `EMAIL_DELIVERY_LOG` | Log contains user email | `REDACT` | `REPORT_EXPOSED_PII` (`PRESENT`) | `REDACT_RECORD` (`REDACTED`) | `VERIFY_RECORD_REDACTED` (`REDACTED`) |
| `rule_12` | `SECURITY_AUDIT_LOG` | Within retention period | `RETAIN` | *(None if compliant; violation if missing)* | *(None)* | `VERIFY_RECORD_PRESENT` (`PRESENT`) |
| `rule_13` | `LEGAL_HOLD_RECORD` | Active legal hold | `RETAIN` | *(None if compliant; violation if missing)* | *(None)* | `VERIFY_RECORD_PRESENT` (`PRESENT`) |
| `rule_14` | `BACKUP_ARCHIVE` | Restore access can be blocked | `RETAIN` | `REPORT_RESTORE_RISK` (`ACTIVE`) | `BLOCK_RESTORE` (`BLOCKED`) | `VERIFY_RESTORE_BLOCKED` (`BLOCKED`) |
| `rule_15` | `ACCOUNT_TOMBSTONE` | Account deleted, internal user_id kept | `REDACT` | `REPORT_EXPOSED_PII` (`PRESENT`) | `REDACT_RECORD` (`REDACTED`) | `VERIFY_RECORD_REDACTED` (`REDACTED`) |

---

## 3. System Activity: Data Flows, Restore Risks & Timeline

`dataset/system_activity.csv` provides the audit trail of workflow events.
1. **Status is a Claim, Not Proof**:
   - A `DELETE_RECORD` with `reported_result: SUCCESS` may still leave data in secondary databases, failover replicas, or search indices.
   - An activity with `reported_result: FAILED` or `PARTIAL` indicates the worker failed to delete or redact the target resource.
2. **Recreation via Active Data Flows**:
   - Event `CHECK_DATA_FLOW`: If connector status indicates `remains enabled` (`reported_result: SUCCESS`), the data flow is `ACTIVE`.
   - Event `DISABLE_DATA_FLOW`: Disables connector (`reported_result: SUCCESS` -> disabled).
   - If an active connector exists (`REPORT_ACTIVE_DATA_FLOW`), any deletion without disabling it allows data to be replicated back into search or analytics.
3. **Recreation via Restore Risks**:
   - Event `CHECK_RESTORE_ACCESS` / `RESTORE_BACKUP`: If restore access is active / allowed, backup archives can bring back deleted user profiles.
   - Event `BLOCK_RESTORE`: Blocks restore access for the archive.
4. **Time Invariant (`audit_at`)**:
   - Only events occurring at or before `audit_at` are considered.
   - Evidence captured after `audit_at` must never be cited or used to alter the audit verdict.

---

## 4. Evidence Structure & Selection of `evidence_id`

Evidence files under `dataset/evidence/` fall into distinct categories:
1. **Periodic Snapshot Bundles**:
   - `service_resource_export_*.json` (e.g., `evidence_92`): Comprehensive multi-service export including `account_service`, `analytics_platform`, `backup_service`, `export_service`, `integration_service`, `search_service`, `security_service`, `support_platform`.
   - `customer_data_inventory_*.sql` (e.g., `evidence_93`): SQLite database dump of all tables.
   - `resource_lookup_trace_*.log` (e.g., `evidence_94`): Detailed debug readback logs proving 404 (absent), hits, or nullified fields.
   - `customer_data_snapshot_bundle_*.json` (e.g., `evidence_51`): Tombstones, security audit records, customer profiles.
2. **Point-in-Time Database Snapshots**:
   - `customer_accounts_failover_replica_*.sql` (e.g., `evidence_54`): Proves lingering records in failover replicas.
   - `customer_search_primary_*.sql` (e.g., `evidence_57`): Proves search index lingering entries.
3. **Documents & Media**:
   - PDFs (e.g., `evidence_58` `delivery_correction_attachment.pdf`): Customer handover or delivery correction support attachments.
   - PNG UI screenshots (e.g., admin console, analytics profile view, backup restore console).

### Evidence Selection Rules:
- **Findings**: Must cite the exact `file_id` (or `activity_id` / `audit_id`) that proves the violation (e.g., `evidence_54` for replica finding, `evidence_92` for export finding).
- **COMPLETE Verification**: Every verification step must cite the evidence that proves the compliant state at `audit_at` (e.g., `evidence_92`, `evidence_94`, `evidence_51`).
- **INCOMPLETE Remediation & Future Verification**: Must use an empty string (`evidence_id: ""`), because they describe proposed future actions and post-remediation verification checks.

---

## 5. Resource Naming Conventions

Resource IDs follow strict deterministic conventions across all systems:
- `account_service`: `account_<id>` (e.g., `account_001`, `account_7566`)
- `search_service`: `search_<id>` (e.g., `search_001`, `search_1993`)
- `analytics_platform`: `analytics_<id>` (e.g., `analytics_901`, `analytics_5208`)
- `support_platform`: `support_<id>` (e.g., `support_001`, `support_5281`)
- `export_service`: `export_<id>` (e.g., `export_001`, `export_7364`)
- `integration_service`: `data_flow_<id>` (e.g., `data_flow_3827`, `data_flow_9522`)
- `backup_service`: `backup_<id>` (e.g., `backup_838`, `backup_3245`)
- `security_service`: `audit_record_<id>` (e.g., `audit_record_2016`, `audit_record_3737`)
- `identity_service`: `tombstone_<id>` (e.g., `tombstone_440`, `tombstone_9178`)

---

## 6. Decision Logic: COMPLETE vs INCOMPLETE vs NOT_APPLICABLE

### Case A: NOT_APPLICABLE
- Triggered when:
  1. The user's `request_text` does not ask for deletion (e.g., requests account export/download, name typo correction, billing copies, marketing preferences).
  2. The privacy intake classified the request as non-deletion (`CLASSIFY_REQUEST` in `system_activity.csv`).
- Output:
  - `deletion_status`: `NOT_APPLICABLE`
  - `steps_json`: `[]`

### Case B: COMPLETE
- Triggered when:
  1. Request authorized deletion.
  2. At `audit_at`, all required deletions are complete (primary + replicas + search + exports + attachments verified ABSENT).
  3. All analytics profiles are unlinked / ANONYMIZED.
  4. All support conversations / tombstones are REDACTED (direct PII removed, stable reference kept).
  5. All required retention records (security audit logs) remain PRESENT.
  6. All data flows are DISABLED.
  7. All restore paths are BLOCKED.
- Output:
  - `deletion_status`: `COMPLETE`
  - `steps_json`: Only `VERIFICATION` steps, all citing valid evidence captured `<= audit_at`.

### Case C: INCOMPLETE
- Triggered when:
  1. Request authorized deletion, but one or more resources or processes violate policy at `audit_at`.
- Output:
  - `deletion_status`: `INCOMPLETE`
  - `steps_json`:
    1. **FINDING** steps: One finding per violation/risk, citing the participant-visible evidence.
    2. **REMEDIATION** steps: Safe remediation plan with `evidence_id: ""`.
       - Order: `DISABLE_DATA_FLOW` -> `BLOCK_RESTORE` -> `DELETE_RECORD` -> `REDACT_RECORD` -> `ANONYMIZE_RECORD`.
    3. **VERIFICATION** steps: Future verification checks with `evidence_id: ""`.
       - Verifies that all remediated resources achieve their target state.
       - Confirms primary account record is ABSENT.
       - Confirms retained security audit records remain PRESENT.

---

## 7. Strict Ordering Rules

Within `steps_json`:
1. Phase order: `FINDING` -> `REMEDIATION` -> `VERIFICATION`.
2. Within each phase:
   - Sort by operation in the order of the Allowed Operations table:
     - Findings: `REPORT_REMAINING_RECORD` -> `REPORT_EXPOSED_PII` -> `REPORT_ACTIVE_DATA_FLOW` -> `REPORT_RESTORE_RISK`
     - Remediation: `DISABLE_DATA_FLOW` -> `BLOCK_RESTORE` -> `DELETE_RECORD` -> `REDACT_RECORD` -> `ANONYMIZE_RECORD`
     - Verification: `VERIFY_RECORD_ABSENT` -> `VERIFY_RECORD_PRESENT` -> `VERIFY_RECORD_REDACTED` -> `VERIFY_RECORD_ANONYMIZED` -> `VERIFY_DATA_FLOW_DISABLED` -> `VERIFY_RESTORE_BLOCKED`
   - Secondary sort: `system_id` ascending.
   - Tertiary sort: `resource_id` ascending.
3. Step numbering: `step_no` starts at 1 and increments consecutively (`1, 2, 3, ...`).

---

## 8. Explicit Rule Predicates, Truth Hierarchy & Evidence Citation (Phase 2 Additions)

### 8.1 Evidence as Ultimate Ground Truth vs Activity Claims
- `system_activity.csv` records claims (`SUCCESS`, `FAILED`, `PARTIAL`).
- Even a reported `SUCCESS` on a `DELETE_RECORD` can be negated if:
  1. A subsequent `SYNC_RECORD`, `RESTORE_BACKUP`, `IMPORT`, or `INDEX_RECORD` event recreated the data before `audit_at`.
  2. A secondary database replica (e.g., failover, read replica) still contains the row.
  3. A search index or export was never cleared.
- Therefore, the per-resource timeline reconstructed from `system_activity.csv` (events `<= audit_at`) must always be cross-checked against the latest evidence captured `<= audit_at`.
- When evidence proves the presence or absence of a record, evidence wins. Disagreements between system activity claims and evidence observations are logged in the case debug trace.

### 8.2 Explicit Predicates for deletion_rules.csv
Each rule's `Condition` is implemented as an explicit typed predicate evaluated on evidence observations:
1. `SUPPORT_MESSAGE` (rule_05): Condition = "Conversation contains shared context". Evaluated as: `REDACT` only if ticket contains shared context (agent/customer messages to be preserved) and still contains user direct PII (name, email, phone). If PII is already stripped (values are null), it is already redacted.
2. `SUPPORT_ATTACHMENT` (rule_06): Condition = "Attachment belongs only to the deletion subject". Verified via data catalog confirmation (`LINK_RESOURCE_IDENTITY`) or document header. If exclusively subject's attachment -> `DELETE`.
3. `ANALYTICS_PROFILE` / `PRODUCT_TELEMETRY` (rule_07/08): Condition = "Record is still attributable to a user". Evaluated as: True if `user_id`, `email`, `phone`, `email_hash`, or `name` is non-null. If all direct identifiers are null, the record is non-attributable (`ANONYMIZED`).
4. `EMAIL_DELIVERY_LOG` (rule_11): Condition = "Log contains a user email address". Evaluated as: True if any current or historical email appears in the log payload.
5. `SECURITY_AUDIT_LOG` / `LEGAL_HOLD_RECORD` (rule_12/13): Condition = "Record is within the supplied retention period". Under policy, these records must NOT be deleted; they must be verified `PRESENT`.
6. `ACCOUNT_TOMBSTONE` (rule_15): Condition = "Account is deleted and only a stable internal user_id is needed". Evaluated as: `REDACTED` if `name`, `email`, `phone`, and `email_hash` are all null, with `user_id` preserved. If any direct PII field is populated, it constitutes exposed PII requiring `REDACT_RECORD`.
7. `BACKUP_ARCHIVE` (rule_14): Condition = "Restore access can be blocked". Evaluated as: If `restore_allowed == true`, an active restore risk exists requiring `BLOCK_RESTORE`. If `restore_allowed == false`, the backup is blocked.

### 8.3 Identity Safety & Email Hash Scheme
- **Hash Scheme**: Verified empirically on `user_identities.csv`:
  `email_hash = hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest()`.
  The same formula applies to all historical emails in `user_audit_log.csv`.
- **Identity Safety Invariant**: Never link a record to a user by full name alone. Matching requires at least one strong identifier:
  - Exact `user_id`
  - Exact `email` (current or historical, case-insensitive, trimmed)
  - Exact `phone` (normalized whitespace)
  - Exact `email_hash`
  - Explicit `LINK_RESOURCE_IDENTITY` activity linking the resource to the user.
- If two users share a name, they must never be merged. Name-only candidate links without strong identifier corroboration are flagged as ambiguous in the debug trace.

### 8.4 Deterministic Evidence Citation Function
When multiple evidence files exist for a user's resources:
- Filter evidence files to those captured `<= audit_at`.
- For each resource, select the evidence file that directly contains an observation for that resource (or for that user's system record), choosing the one with the latest `captured_at <= audit_at`.
- For `INCOMPLETE` cases:
  - Findings cite the proving evidence file.
  - Proposed remediation and post-remediation verification use empty string `evidence_id: ""`.
- For `COMPLETE` cases:
  - Every verification step cites the evidence file proving the compliant state.

### 8.5 Intent Classification & NOT_APPLICABLE
- If `system_activity.csv` contains `CLASSIFY_REQUEST` with `details` stating "classified request ... as non-deletion; no destructive action was authorized", intent is unequivocally `NOT_APPLICABLE`.
- In `request_text`, non-deletion intents (access requests, data downloads/exports without deletion, name corrections, copy of invoices, marketing preferences) without any deletion intent yield `NOT_APPLICABLE`.
- Mixed requests ("export my data and then delete my account") are deletion requests: the user explicitly authorizes deletion.
- For `NOT_APPLICABLE`: `deletion_status = "NOT_APPLICABLE"`, `steps_json = []`.
