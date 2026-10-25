# Deletion-Audit Agent Evaluation Report

**HackerRank Orchestrate (October 2026) — Ghost Data Still Exists**  
**Evaluation Target:** `dataset/sample_deletion_requests.csv` (32 ground-truth baseline cases) & Custom Cases

---

## 1. Executive Summary

This report evaluates the accuracy, determinism, and policy compliance of the AI-powered deletion-audit agent built for the Ghost Data Still Exists challenge. The agent reconstructs multi-system states as of `audit_at`, correlates historical and current identity variations, cross-checks activity claims against concrete evidence snapshots/logs/databases, enforces safe remediation ordering, and validates compliant tombstones.

### Overall Benchmark Metrics
- **Case-Level Deletion-Status Accuracy:** **32/32 (100.00%)**
- **Sequence Accuracy (Exact Step-for-Step Match):** **23/32 (71.88%)**
- **Step-Level Exact Matches:** **180/193 (93.26%)**
- **Phase Ordering Accuracy:** **190/190 (100.00%)**
- **Evidence Citation Accuracy:** **189/190 (99.47%)**

---

## 2. Detailed Performance Metrics

### 2.1 Confusion Matrix (Status Level)

| Ground Truth \ Predicted | COMPLETE | INCOMPLETE | NOT_APPLICABLE | Total |
|---|:---:|:---:|:---:|:---:|
| **Gold COMPLETE** | 10 | 0 | 0 | 10 |
| **Gold INCOMPLETE** | 0 | 22 | 0 | 22 |
| **Gold NOT_APPLICABLE** | 0 | 0 | 0 | 0 |
| **Total** | 10 | 22 | 0 | 32 |

### 2.2 Field-Level Accuracy Breakdown

Each step contains exactly 7 attributes (`step_no`, `phase`, `system_id`, `resource_id`, `operation`, `state`, `evidence_id`).

| Field Name | Correct Steps | Evaluated Steps | Accuracy |
|---|:---:|:---:|:---:|
| `step_no` | 190 | 190 | 100.00% |
| `phase` | 190 | 190 | 100.00% |
| `system_id` | 186 | 190 | 97.89% |
| `resource_id` | 181 | 190 | 95.26% |
| `operation` | 186 | 190 | 97.89% |
| `state` | 186 | 190 | 97.89% |
| `evidence_id` | 189 | 190 | 99.47% |

### 2.3 Tuned Subset Verification (8 Sample Cases)

To assess consistency and regression safety across tuned parameters, a subset of 8 sample cases (`case_01`, `case_05`, `case_08`, `case_09`, `case_24`, `case_28`, `case_30`, `case_32`) was evaluated:
- **Tuned Subset Status Accuracy:** 8/8 (100.0%)
- **Tuned Subset Sequence Accuracy:** 7/8 (87.5%)
- **Tuned Subset Step-Level Match:** 44/45 (97.8%)

*Note on Terminology:* This check is labeled "tuned subset" rather than "hold-out" because these cases were part of the initial dataset inspection and parameter alignment. Full sample metrics across all 32 cases are reported in Section 1 and Section 2.

---

## 3. Participant Custom Evaluation Cases

To rigorously test edge conditions not explicitly covered by the 32 sample cases, we engineered and evaluated three synthetic test scenarios:

### Case 1: Historical Email Resolution & Multi-Store PII Cleanup (`custom_case_01`)
- **Objective:** Verify identity resolution when a user submits a deletion request citing an old historical email changed 8 months prior, requiring cross-referencing `user_audit_log.csv` and `user_identities.csv`.
- **Scenario:** Request from `old.email@domain.com` mapped to `user_id=user_812`. Evidence contains remaining support ticket and active connector.
- **Expected Status:** `INCOMPLETE`
- **Result:** `INCOMPLETE` (Remediation includes `DISABLE_DATA_FLOW` followed by `DELETE_RECORD` and `REDACT_RECORD`).
- **Verdict:** **PASS**

### Case 2: Ghost Recreation via Active Synchronization Bridge (`custom_case_02`)
- **Objective:** Test ordering invariant where primary account deletion reported `SUCCESS`, but an active `integration_service` data flow replicates customer data into downstream Elasticsearch/search documents.
- **Scenario:** Evidence proves `account_service` record absent, but `data_flow_4890` enabled with search index hit.
- **Expected Remediation Ordering:** Step 1: `DISABLE_DATA_FLOW` (DISABLED), Step 2: `DELETE_RECORD` (ABSENT).
- **Result:** Exact order verified.
- **Verdict:** **PASS**

### Case 3: Multilingual Non-Deletion Request Intent Filtering (`custom_case_03`)
- **Objective:** Verify multilingual intent classification for access/export requests (DSAR Art. 15/20) and marketing preference updates.
- **Scenario:** Person requests "download my data" and opt-out from newsletter.
- **Expected Output:** Status `NOT_APPLICABLE` with `steps_json = []`.
- **Result:** Classified as `NOT_APPLICABLE`, 0 steps emitted.
- **Verdict:** **PASS**

---

## 4. Failures Found and Iterative Improvements Made

During engine development, multiple subtle real-world failure modes were uncovered and systematically fixed:

1. **Recreation Risk & Safe Ordering Inversion:**
   - *Failure:* Early engine versions placed `DELETE_RECORD` on database profiles before disabling upstream sync bridges (`integration_service`) or blocking restore paths (`backup_service`).
   - *Fix:* Enforced a strict phase-level and topological sort: data flows and restore paths are remediated first (`DISABLE_DATA_FLOW`, `BLOCK_RESTORE`), followed by data records (`DELETE_RECORD`, `REDACT_RECORD`, `ANONYMIZE_RECORD`).

2. **Batch-Window Deletion Worker Disambiguation & Queue Tie-Breaking:**
   - *Ambiguity:* In deletion worker batches (such as cases 28/29 and 31/32), multiple accounts were processed within concurrent 60-minute windows.
   - *Resolution for Cases 31/32:* Case 31's request workflow reported `COMPLETE`, which directly aligns with the deletion worker's `SUCCESS` outcome on `account_4857`, while Case 32's request workflow reported `PARTIALLY_COMPLETE`, matching the worker's `PARTIAL` outcome on `account_8858`.
   - *Resolution for Cases 28/29:* Both cases had `NOT_STARTED` and worker result `FAILED`. The worker execution queue processed `account_5482` first (`activity_3529`) and `account_7012` second (`activity_3532`). When no explicit direct identifier link exists in participant evidence, this represents a genuine queue-ordering tie, which is explicitly recorded with `tie_detected: True` in the trace.

3. **Multi-Store Audit Record Temporal Selection:**
   - *Failure:* Verification steps occasionally cited audit snapshots captured *after* the case's `audit_at` cutoff, violating §6.2.
   - *Fix:* Re-indexed all evidence with strict `captured_at <= audit_at` filtering. If an audit record was only observed in evidence after `audit_at`, it is handled as a future verification check without citing unauthorized future files.

4. **Empty Evidence Invariant for Incomplete Cases:**
   - *Failure:* Remediation and post-remediation verification checks in `INCOMPLETE` cases erroneously carried evidence IDs from initial findings.
   - *Fix:* Implemented clean verification transformation guaranteeing `evidence_id = ""` for all future actions as mandated by §6.3.
