# Ghost Data Still Exists: Deletion Audit Agent

HackerRank Orchestrate, October 2026.

An evidence-grounded agent that audits deletion requests for the fictional company Northstar Shop. For each request it answers one question: **is this person's data really gone, or is it still exposed somewhere?** It returns a verdict (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`) plus the ordered findings, remediation steps and verification checks the problem statement requires.

**Approach in one paragraph.** The required output is rigid (a fixed set of operations, an exact ordering, an exact grader), so every decision is made by a deterministic rule engine in plain Python. Workflow statuses and "SUCCESS" results are treated as claims, never as proof. The truth is rebuilt from evidence (SQL snapshots, JSON exports, logs, PDFs and screenshots) as of `audit_at`. There are no LLM or API calls at runtime: screenshots are read with a local OCR model and PDFs with `pypdf`. The pipeline is reproducible, runs in seconds on CPU, and costs nothing per run.

---

## 1. Results at a glance

| Measure | Result |
|---|---|
| Requests audited | 518 (one row each, sorted by `case_id`) |
| Verdicts | 185 COMPLETE, 323 INCOMPLETE, 10 NOT_APPLICABLE |
| Output validation | Passed (schema, enums, ordering, step numbering, evidence rules) |
| Sample status accuracy | 32/32 |
| Sample step exact match (all 7 fields) | 180/193 (93.3%) |
| Sample sequence accuracy | 23/32 (71.9%) |
| Runtime for all 518 cases | a few seconds on CPU |
| Model calls, tokens, cost | 0, 0, $0.00 (see `evaluation/usage_report.md`) |

Honest reading of these numbers: the verdicts on the samples are all correct, and most remaining misses are two kinds of case where the provided evidence does not separate two candidates (section 7). The details are in `evaluation/evaluation_report.md`.

---

## 2. How the agent reasons

For every row of `dataset/deletion_requests.csv`:

1. **Intent.** Did the person actually ask for deletion? The signal is the privacy-intake `CLASSIFY_REQUEST` activity, cross-checked by a multilingual keyword rule on `request_text` (English, French, Spanish, Japanese and Korean appear in the data). Exports, access requests, corrections, billing copies and marketing opt-outs become `NOT_APPLICABLE` with `steps_json = []`.
2. **Identity resolution.** From the request email, collect every identifier of the same `user_id` as of `audit_at`: current and historical emails, phones and SHA-256 email hashes (`user_identities.csv`, `user_audit_log.csv`). Audit-log rows after `audit_at` are ignored. Records link to a person by a strong identifier or an explicit `LINK_RESOURCE_IDENTITY` activity, never by name alone.
3. **Timeline.** Rebuild each resource's event history from `system_activity.csv`, using only events at or before `audit_at`.
4. **Evidence extraction.** Parse every evidence file captured at or before `audit_at` into one common `Observation` structure.
5. **Policy.** Apply `deletion_rules.csv` to each record (DELETE, REDACT, ANONYMIZE or RETAIN), evaluating each rule's condition on the evidence instead of assuming "always".
6. **Verdict.** `COMPLETE` only if every copy has its required treatment, no active sync, import or restore path can recreate the data, retained records hold only permitted identifiers, and required-retention records still exist. Otherwise `INCOMPLETE`.
7. **Steps.** Build findings, remediation and verification, sort them exactly as specified, number them, and validate.

### Claims are not proof
`reported_status` and activity results such as `SUCCESS` are claims. A deletion marked successful can still leave a record in a replica, a search index or a console screenshot, and a later sync or restore can bring it back. The state at `audit_at` is taken from evidence; when a claim and the evidence disagree, the evidence wins.

### Step structure and ordering
- **COMPLETE:** verification steps only, each citing evidence captured at or before `audit_at`.
- **INCOMPLETE:** findings (with evidence), then the full remediation plan, then the checks that must pass afterwards. Proposed remediation and future verification steps carry an empty `evidence_id`.
- **NOT_APPLICABLE:** an empty array.
- **Ordering** follows the specification: phase (FINDING, REMEDIATION, VERIFICATION), then the operation order of the Allowed Operations table, then `system_id`, then `resource_id`, ascending. Steps are numbered from 1 with no gaps. A consequence of that table is that `DISABLE_DATA_FLOW` and `BLOCK_RESTORE` come before any `DELETE_RECORD`, which is also the safe order: otherwise a sync or restore could recreate data right after it is deleted.

A step looks like this (schema from the problem statement):

```json
{"step_no": 1, "phase": "FINDING", "system_id": "account_service",
 "resource_id": "account_005", "operation": "REPORT_REMAINING_RECORD",
 "state": "PRESENT", "evidence_id": "evidence_01"}
```

### Policy mapping (`deletion_rules.csv`)

| Data category | Treatment | Finding | Remediation | Verification |
|---|---|---|---|---|
| USER_PROFILE, SECONDARY_IDENTIFIER, SEARCH_INDEX_ENTRY, CACHE_ENTRY, USER_EXPORT, MARKETING_PROFILE, SUPPORT_ATTACHMENT (only the subject's) | DELETE | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| SUPPORT_MESSAGE (shared context), EMAIL_DELIVERY_LOG (contains the email), ACCOUNT_TOMBSTONE | REDACT | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| ANALYTICS_PROFILE, PRODUCT_TELEMETRY (still attributable) | ANONYMIZE | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD | RETAIN | | | VERIFY_RECORD_PRESENT |
| BACKUP_ARCHIVE (restore access) | block restore | REPORT_RESTORE_RISK | BLOCK_RESTORE | VERIFY_RESTORE_BLOCKED |
| Active connector or sync job | disable | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |

Account tombstones may keep the stable `user_id`, but name, email, phone and email hash must be removed.

---

## 3. How we built it, step by step

### Step 1. Understand the problem and the data
We read the problem statement and profiled every input before writing any logic: 850 users, 306 identity-change events, 4,011 system activities across 17 event types, 15 policy rules, and 94 evidence files (24 SQL snapshots, 28 JSON exports, 26 logs, 4 PDFs, 11 PNG screenshots, 1 text note). The 32 sample requests with answers were treated as the only ground truth.

### Step 2. Reverse-engineer the conventions into `NOTES.md`
Comparing each sample request with its answer, we documented how identifiers map to evidence, how rules map to operations, how resources are named per system, how evidence is cited, and when each verdict applies. The agent was required to show this document for review before the engine was built, so wrong assumptions were caught early.

### Step 3. Review the plan for gaps before coding
The review found six weaknesses, each fixed in the design:
- **No sample covered `NOT_APPLICABLE`.** We added our own cases and a multilingual intent rule cross-checked against `CLASSIFY_REQUEST`.
- **Rule conditions were being skipped.** Each rule's condition became an explicit predicate on the evidence.
- **`SUCCESS` was treated as partly trustworthy.** All reported results became claims checked against evidence.
- **Name-only matching is unsafe** (two people can share a name). Linking now requires a strong identifier.
- **Evidence citation was vague.** The citation choice became an explicit function measured against the samples.
- **Overfitting risk** (32 samples, 518 hidden cases). The engine was kept rule-driven, with sanity checks on the full run.

### Step 4. Build the engine in layers
Loaders, then identity resolver, then timeline, then one extractor per evidence type, then policy, then engine, then a strict validator. Each layer was tested before the next was built.

### Step 5. Build the evaluation harness
`run_eval.py` compares the agent with the sample answers and reports status accuracy with a confusion matrix, step-level exact match, per-field accuracy and sequence accuracy, with a per-case diff for every failure.

### Step 6. Iterate on root causes, not on single cases
The main improvements, in the order we found them:

| Finding | Fix |
|---|---|
| Only 3 requests came out `NOT_APPLICABLE`; the keyword rule missed some phrasings, including Korean deletion wording | Extended the multilingual rule; the final run found 10, each agreeing with its `CLASSIFY_REQUEST` activity |
| The 11 PNG screenshots were never actually read (their text is compressed inside the image) | Added local OCR (`rapidocr-onnxruntime`, results cached by file hash). The change altered 8 output rows, exposing active connectors and restorable backups visible only in screenshots |
| OCR bound a resource to every email on the screen, causing a false positive | Each resource now binds only to its nearest identifier; if none is nearby it stays unbound and is linked only through activities |
| Hardcoded fallbacks to a specific evidence file and account existed in the engine | Replaced with dynamic lookup of the snapshots available at the case's `audit_at` |
| Two cases pointed at the same candidate accounts | Added a principled tie-break (worker activity order, correlated with the reported status) and record the tie in the trace instead of hiding it |
| A subset check was labelled "hold-out" although its cases were used while tuning | Relabelled it a tuned subset in the report |

### Step 7. Clean and verify the submission
Debug and scratch scripts were removed from the zip, along with caches, traces and secrets. We then verified: the engine never reads sample answers or references case IDs, emails or resource IDs (searched with zero matches); `output.csv` has 518 sorted rows; the zip layout matches the required contents; and the reports match the final run.

---

## 4. Evidence extraction

| Evidence | Method |
|---|---|
| SQL snapshots | Loaded into in-memory SQLite; tables and columns discovered dynamically |
| JSON exports and bundles | Normalised into the common observation structure |
| Logs | Regex and NDJSON parsers for traces, read-back lookups and service events |
| PDFs | Text extraction with `pypdf` |
| PNG screenshots | Local OCR; nearest-identifier binding prevents mixing tenants |
| Activity links | `LINK_RESOURCE_IDENTITY` activities connect screenshots and documents to resources |

Only evidence captured at or before a case's `audit_at` is ever used or cited.

---

## 5. Repository layout

```
main.py                      Entry point: all requests -> output.csv, then validation
requirements.txt             Dependencies (rapidocr-onnxruntime, pypdf, Pillow)
.env.example                 Environment template (no key needed)
NOTES.md                     Data model, rule mapping, decisions
prompts/                     Reference design specs (not called at runtime)
agent/
  loaders.py                 Typed loaders for CSVs, activities, identities, evidence manifest
  identity.py                Identity graph resolver
  timeline.py                Timeline at audit_at
  policy.py                  Rule predicates, step mapping, sorting
  engine.py                  Audit engine and batch resolver
  validator.py               Strict output validator
  evidence/                  base, registry_scanner, sql, json, log, pdf, txt, media (OCR)
evaluation/
  run_eval.py                Benchmark against the sample answers
  generate_reports.py        Regenerates the two reports
  evaluation_report.md       Metrics, custom cases, failures and fixes
  usage_report.md            Token, cost and latency report
```

A local `cache/` (OCR results) and `trace/` (per-case debug traces) are produced when the pipeline runs and are not part of the submission.

---

## 6. Run it

Python 3.10 or newer. From the repository root, with this `code/` folder inside it:

```powershell
pip install -r code/requirements.txt
py code/main.py                        # writes output.csv at the repo root and validates it
py code/evaluation/run_eval.py         # benchmark on the sample set
py code/evaluation/generate_reports.py
```

On macOS or Linux use `python3` instead of `py`.

---

## 7. Evaluation, and where it falls short

The evaluation report covers case-level status accuracy, step-level and field-level accuracy, sequence accuracy, three custom cases we wrote ourselves, and the failures found with the improvements made. The remaining sample misses fall into two groups:

- **Two security audit records that are not in the evidence.** Two sample cases expect verification of audit records that do not appear in any evidence file, including the OCR text of every screenshot. The agent does not cite evidence it cannot find.
- **Concurrent-batch ties.** A few sample cases involve several deletion-worker tasks in the same window with nothing in the evidence saying which task belongs to which request. The engine resolves them by worker activity order and records `tie_detected` in the trace. That is a heuristic, not proof.

Other limits:
- **Evidence citation:** when several snapshots prove the same fact, a fixed rule picks one; an equally valid file can differ from the reference in one field.
- **`NOT_APPLICABLE`:** no sample covers it. The 10 cases came from two independent signals that agreed, but there is no ground truth to measure them against.
- **OCR:** a misread character could hide a resource ID.
- **No model at runtime:** results are reproducible and free, but the rules would need updating for new evidence formats.

---

## 8. How this maps to the judging criteria

| Criterion | Where to look |
|---|---|
| Correct statuses and steps | `output.csv`, sample metrics in section 1, `evaluation/evaluation_report.md` |
| Identity resolution | `agent/identity.py`: historical emails, phones and hashes as of `audit_at`, no name-only matching |
| Evidence and policy decisions | `agent/evidence/`, `agent/policy.py`, `NOTES.md` |
| No hardcoded answers | Sections 3 (step 6, step 7) and 4; the engine reads no sample answers |
| Evaluation workflow | `evaluation/run_eval.py`, custom cases and failure log in the report |
| Cost and token reporting | `evaluation/usage_report.md` (local OCR and `pypdf`, no API calls) |
| Reproducibility | One command in section 6, deterministic output |

---

## 9. How AI was used

The code was implemented with **Antigravity**. **Claude** (chat) was used for planning, the build prompts, reviewing results and finding gaps, such as the unread screenshots and the over-fitted tie-breaks. The full conversation is in `log.txt` at the repository root.
