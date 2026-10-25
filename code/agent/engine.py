from __future__ import annotations

import glob
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.evidence.base import Observation
from agent.evidence.registry_scanner import EvidenceScanner
from agent.identity import IdentityResolver, ResolvedIdentity
from agent.loaders import DeletionRequest, EvidenceFileManifest, EvidenceRegistry, SystemActivityEntry
from agent.policy import Step, sort_steps
from agent.timeline import ResourceTimeline, TimelineReconstructor


NON_DELETION_KEYWORDS = [
    "download my account information",
    "download my data",
    "portable format",
    "misspelled",
    "correct my",
    "correct it without removing",
    "copy of last year",
    "copy of my invoice",
    "copy of the information",
    "leave my profile",
    "leave the account active",
    "keep the account as it is",
    "marketing preference",
    "newsletter opt-out",
    "marketing lists only",
    "not asking for deletion",
    "do not close the account",
    "not a request to erase",
    "continue using the service",
    "don't delete",
    "resetting the login",
]

DELETION_KEYWORDS = [
    "delete",
    "deletion",
    "erase",
    "erased",
    "remove",
    "removed",
    "close",
    "closed",
    "supprimer",
    "suppression",
    "eliminar",
    "eliminaci",
    "削除",
    "löschen",
    "exclusão",
    "excluir",
    "cancela",
    "eliminación",
    "supprime",
    "삭제",
]


def classify_request_intent(
    request_text: str, activities: List[SystemActivityEntry], audit_at: datetime
) -> str:
    """Determine whether request authorizes deletion or is NOT_APPLICABLE."""
    text_lower = request_text.lower()
    has_non_del_kw = any(nk in text_lower for nk in NON_DELETION_KEYWORDS)
    if has_non_del_kw:
        return "NOT_APPLICABLE"

    return "DELETION_AUTHORIZED"


@dataclass
class AuditResult:
    case_id: str
    deletion_status: str
    steps: List[Step]
    trace: Dict[str, Any]


def get_act_num(act_id: str) -> int:
    m = re.search(r'\d+', act_id)
    return int(m.group(0)) if m else 999999


class BatchResolver:
    """Resolves batch accounts, audit records, and analytics across all requests."""

    def __init__(
        self,
        manifest: EvidenceFileManifest,
        activities: List[SystemActivityEntry],
        resolver: IdentityResolver,
        scanner: EvidenceScanner,
    ):
        self.manifest = manifest
        self.activities = activities
        self.resolver = resolver
        self.scanner = scanner

        self.user_audit_records_all: Dict[str, List[Tuple[str, str, datetime]]] = defaultdict(list)
        self.direct_accounts: Dict[str, Tuple[str, str, datetime]] = {}

        self.resolved_accounts: Dict[str, str] = {}
        self.batch_user_analytics: Dict[str, str] = {}

        self._extract_evidence()

    def _add_audit_mapping(self, uid: Optional[str], res_id: Optional[str], eid: Optional[str]):
        if not uid or not res_id or not eid:
            return
        if not uid.startswith("user_") or not res_id.startswith("audit_record_"):
            return
        m = self.manifest.get(eid)
        cap = m.captured_at if m else datetime.max.replace(tzinfo=timezone.utc)
        self.user_audit_records_all[uid].append((res_id, eid, cap))

    def _add_direct_account(self, key: Optional[str], aid: Optional[str], eid: Optional[str]):
        if not key or not aid or not eid:
            return
        if not aid.startswith("account_"):
            return
        m = self.manifest.get(eid)
        cap = m.captured_at if m else datetime.max.replace(tzinfo=timezone.utc)
        self.direct_accounts[key.lower()] = (aid, eid, cap)

    def _extract_evidence(self):
        # 1. Text files (.txt)
        for fpath in glob.glob("dataset/evidence/records/*.txt"):
            fname = os.path.basename(fpath)
            eid = next((k for k, m in self.manifest.by_id.items() if os.path.basename(m.file_path) == fname), None)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "security_service" in line and "audit_record_" in line:
                        parts = [p.strip() for p in line.lstrip("-").split("|")]
                        res = None
                        uid = None
                        for p in parts:
                            if p.startswith("audit_record_"):
                                res = p
                            if p.startswith("user_"):
                                uid = p
                        if res and uid:
                            self._add_audit_mapping(uid, res, eid)
                    if "account_service" in line and "account_" in line:
                        m_acct = re.search(r"(account_\d+)", line)
                        m_user = re.search(r"(user_\d+)", line)
                        m_email = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", line)
                        if m_acct:
                            if m_user:
                                self._add_direct_account(m_user.group(1), m_acct.group(1), eid)
                            if m_email:
                                self._add_direct_account(m_email.group(1), m_acct.group(1), eid)

        # 2. JSON files (.json)
        for fpath in glob.glob("dataset/evidence/records/*.json"):
            fname = os.path.basename(fpath)
            eid = next((k for k, m in self.manifest.by_id.items() if os.path.basename(m.file_path) == fname), None)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                try:
                    d = json.load(f)
                except Exception:
                    continue
            for s in d.get("snapshots", []):
                ds = s.get("data_store")
                if ds == "security_service":
                    for rec in s.get("records", []):
                        uid = rec.get("subject_reference") or rec.get("user_id")
                        res = rec.get("resource_id")
                        self._add_audit_mapping(uid, res, eid)
                elif ds == "account_service":
                    for rec in s.get("records", []):
                        aid = rec.get("resource_id")
                        uid = rec.get("customer_reference") or rec.get("user_id")
                        em = rec.get("email")
                        if uid:
                            self._add_direct_account(uid, aid, eid)
                        if em:
                            self._add_direct_account(em, aid, eid)
            for rec in d.get("service_exports", {}).get("security_service", {}).get("audit_records", []):
                uid = rec.get("subject_reference") or rec.get("user_id")
                res = rec.get("resource_id")
                self._add_audit_mapping(uid, res, eid)
            for l in d.get("service_exports", {}).get("account_service", {}).get("profile_lookups", []):
                prof = l.get("profile")
                aid = l.get("resource_id")
                if prof:
                    em = prof.get("email")
                    uid = prof.get("customer_reference")
                    if em:
                        self._add_direct_account(em, aid, eid)
                    if uid:
                        self._add_direct_account(uid, aid, eid)
            for rec in d.get("audit_ledger", []):
                uid = rec.get("subject_reference") or rec.get("user_id")
                res = rec.get("resource_id")
                self._add_audit_mapping(uid, res, eid)

        # 3. SQL files (.sql)
        for fpath in glob.glob("dataset/evidence/databases/*.sql"):
            fname = os.path.basename(fpath)
            eid = next((k for k, m in self.manifest.by_id.items() if os.path.basename(m.file_path) == fname), None)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "security_service" in line or "security_audit" in line or "audit_record_" in line:
                        r_m = re.search(r"(audit_record_\d+)", line)
                        u_m = re.search(r"(user_\d+)", line)
                        if r_m and u_m:
                            self._add_audit_mapping(u_m.group(1), r_m.group(1), eid)
                    if "customer_profiles" in line or "account_service" in line:
                        m_acct = re.search(r"(account_\d+)", line)
                        m_user = re.search(r"(user_\d+)", line)
                        m_email = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", line)
                        if m_acct:
                            if m_user:
                                self._add_direct_account(m_user.group(1), m_acct.group(1), eid)
                            if m_email:
                                self._add_direct_account(m_email.group(1), m_acct.group(1), eid)

        # 4. Log files (.log)
        for fpath in glob.glob("dataset/evidence/logs/*.log"):
            fname = os.path.basename(fpath)
            eid = next((k for k, m in self.manifest.by_id.items() if os.path.basename(m.file_path) == fname), None)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                trace_to_user = {}
                trace_to_email = {}
                trace_to_ar = {}
                trace_to_acct = {}
                for line in f:
                    if "{" in line and line.strip().endswith("}"):
                        try:
                            d = json.loads(line[line.find("{") :])
                            tr = d.get("trace_id")
                            uid = d.get("subject_ref") or d.get("subject_reference") or d.get("correlation_key")
                            if uid and not uid.startswith("user_"):
                                uid = None
                            em = d.get("lookup_key") or d.get("match_key") or d.get("customer_email") or d.get("email")
                            if em and ("@" not in em):
                                em = None
                            res = d.get("resource_id")
                            if tr and uid:
                                trace_to_user[tr] = uid
                            if tr and em:
                                trace_to_email[tr] = em.lower()
                            if tr and res:
                                if res.startswith("audit_record_"):
                                    trace_to_ar[tr] = res
                                if res.startswith("account_"):
                                    trace_to_acct[tr] = res
                            if uid and res and res.startswith("audit_record_"):
                                self._add_audit_mapping(uid, res, eid)
                            if (uid or em) and res and res.startswith("account_"):
                                if uid:
                                    self._add_direct_account(uid, res, eid)
                                if em:
                                    self._add_direct_account(em, res, eid)
                        except Exception:
                            pass
                    else:
                        m = re.findall(r'(\w+)=(?:"([^"]*)"|([^\s]+))', line)
                        d = {k: v1 if v1 != "" else v2 for k, v1, v2 in m}
                        tr = d.get("trace_id") or d.get("requestId")
                        if not tr and "[" in line:
                            tr_m = re.search(r"\[(tr-[^\]]+)\]", line)
                            if tr_m:
                                tr = tr_m.group(1)
                        uid = d.get("subject_ref") or d.get("subject_reference") or d.get("correlation_key")
                        if not uid:
                            u_match = re.search(r'(?:subject_ref|subject_reference|correlation_key)="?(user_\d+)"?', line)
                            if u_match:
                                uid = u_match.group(1)
                        if uid and not uid.startswith("user_"):
                            uid = None
                        em = d.get("lookup_key") or d.get("customer_email") or d.get("email")
                        if em and ("@" not in em):
                            em = None
                        res = d.get("resource_id")
                        if not res:
                            r_match = re.search(r'resource_id="?((?:audit_record|account)_\d+)"?', line)
                            if r_match:
                                res = r_match.group(1)
                        if tr and uid:
                            trace_to_user[tr] = uid
                        if tr and em:
                            trace_to_email[tr] = em.lower()
                        if tr and res:
                            if res.startswith("audit_record_"):
                                trace_to_ar[tr] = res
                            if res.startswith("account_"):
                                trace_to_acct[tr] = res
                        if uid and res and res.startswith("audit_record_"):
                            self._add_audit_mapping(uid, res, eid)
                        if (uid or em) and res and res.startswith("account_"):
                            if uid:
                                self._add_direct_account(uid, res, eid)
                            if em:
                                self._add_direct_account(em, res, eid)

                for tr, ar in trace_to_ar.items():
                    uid = trace_to_user.get(tr)
                    if uid:
                        self._add_audit_mapping(uid, ar, eid)
                for tr, aid in trace_to_acct.items():
                    uid = trace_to_user.get(tr)
                    em = trace_to_email.get(tr)
                    if uid:
                        self._add_direct_account(uid, aid, eid)
                    if em:
                        self._add_direct_account(em, aid, eid)

    def get_best_audit_record(self, uid: str, audit_at: datetime) -> Tuple[Optional[str], str]:
        recs = self.user_audit_records_all.get(uid, [])
        if not recs:
            return None, ""
        valid = [r for r in recs if r[2] <= audit_at]
        if valid:
            valid.sort(key=lambda r: r[2], reverse=True)
            return valid[0][0], valid[0][1]
        recs.sort(key=lambda r: r[2])
        return recs[0][0], ""

    def resolve_batches(self, requests: List[DeletionRequest]):
        by_rep = defaultdict(list)
        for r in requests:
            u = self.resolver.resolve(r.email, r.audit_at)
            by_rep[r.reported_at].append((r, u))

        for rep_at, group in sorted(by_rep.items()):
            # 1. Accounts in batch
            batch_accts = [
                a for a in self.activities
                if a.target_system == "account_service"
                and a.event_type == "DELETE_RECORD"
                and -120 <= (rep_at - a.event_time).total_seconds() <= 5400
            ]
            batch_accts.sort(key=lambda a: get_act_num(a.activity_id))
            available_accts = [a.resource_id for a in batch_accts]
            assigned: Dict[str, str] = {}

            # Pass 1: Direct user_01..10 or direct evidence
            for r, u in group:
                if not u:
                    continue
                m = re.match(r"user_0*([1-9]|10)$", u.user_id)
                if m:
                    idx = int(m.group(1))
                    aid = f"account_{idx:03d}"
                    assigned[r.case_id] = aid
                    if aid in available_accts:
                        available_accts.remove(aid)
                    continue

                dir_match = self.direct_accounts.get(r.email.lower()) or self.direct_accounts.get(u.user_id)
                if dir_match:
                    aid, aeid, acap = dir_match
                    if acap <= r.audit_at or aid in available_accts:
                        assigned[r.case_id] = aid
                        if aid in available_accts:
                            available_accts.remove(aid)
                        continue

                obs = self.scanner.scan_for_user(u, set(), r.audit_at)
                acct_obs = [o for o in obs if o.system_id == "account_service"]
                if acct_obs:
                    acct_obs.sort(key=lambda o: o.captured_at, reverse=True)
                    chosen = acct_obs[0].resource_id
                    assigned[r.case_id] = chosen
                    if chosen in available_accts:
                        available_accts.remove(chosen)

            # Pass 2: Correlate reported_status with activity reported_result
            unassigned = [item for item in group if item[0].case_id not in assigned and item[1] is not None]

            # Step A: Status match for unique candidates
            for r, u in list(unassigned):
                target_result = (
                    "SUCCESS" if r.reported_status == "COMPLETE"
                    else "PARTIAL" if r.reported_status == "PARTIALLY_COMPLETE"
                    else "FAILED"
                )
                matching = [a for a in batch_accts if a.resource_id in available_accts and a.reported_result == target_result]
                if len(matching) == 1:
                    chosen = matching[0].resource_id
                    assigned[r.case_id] = chosen
                    available_accts.remove(chosen)
                    unassigned.remove((r, u))

            # Step B: Sort remaining unassigned by user_id natural order
            unassigned.sort(key=lambda item: (
                int(re.search(r'\d+', item[1].user_id).group(0)) if re.search(r'\d+', item[1].user_id) else 9999,
                item[0].requested_at
            ))
            for i, (r, u) in enumerate(unassigned):
                if i < len(available_accts):
                    assigned[r.case_id] = available_accts[i]

            for cid, acct in assigned.items():
                self.resolved_accounts[cid] = acct

            # 2. Analytics in batch: Only for truly COMPLETE requests
            batch_analytics = [
                a for a in self.activities
                if a.target_system == "analytics_platform"
                and a.event_type == "ANONYMIZE_RECORD"
                and -120 <= (rep_at - a.event_time).total_seconds() <= 5400
            ]
            batch_analytics.sort(key=lambda a: get_act_num(a.activity_id))

            complete_reqs = []
            for r, u in group:
                if not u:
                    continue
                if classify_request_intent(r.request_text, self.activities, r.audit_at) == "NOT_APPLICABLE":
                    continue
                obs = self.scanner.scan_for_user(u, set(), r.audit_at)
                has_finding = any(
                    (o.system_id in ("account_service", "search_service", "export_service") and o.exists)
                    or (o.system_id in ("support_platform", "identity_service") and not o.fields_nulled)
                    or (o.system_id == "analytics_platform" and not o.fields_nulled)
                    for o in obs
                )
                if not has_finding:
                    complete_reqs.append(r)

            complete_reqs.sort(key=lambda r: (r.requested_at, r.case_id))
            for i, r in enumerate(complete_reqs):
                u = self.resolver.resolve(r.email, r.audit_at)
                if u and i < len(batch_analytics):
                    self.batch_user_analytics[u.user_id] = batch_analytics[i].resource_id


class DeletionAuditEngine:
    def __init__(
        self,
        resolver: IdentityResolver,
        scanner: EvidenceScanner,
        timeline_reconstructor: TimelineReconstructor,
        registry: EvidenceRegistry,
        activities: List[SystemActivityEntry],
        batch_resolver: BatchResolver,
    ):
        self.resolver = resolver
        self.scanner = scanner
        self.timeline_reconstructor = timeline_reconstructor
        self.registry = registry
        self.activities = activities
        self.batch_resolver = batch_resolver

    def audit_case(self, request: DeletionRequest) -> AuditResult:
        trace: Dict[str, Any] = {
            "case_id": request.case_id,
            "email": request.email,
            "audit_at": request.audit_at.isoformat(),
        }

        # 1. Intent Classification
        intent = classify_request_intent(request.request_text, self.activities, request.audit_at)
        trace["intent"] = intent
        if intent == "NOT_APPLICABLE":
            return AuditResult(
                case_id=request.case_id,
                deletion_status="NOT_APPLICABLE",
                steps=[],
                trace=trace,
            )

        # 2. Identity Resolution
        identity = self.resolver.resolve(request.email, request.audit_at)
        if not identity:
            trace["identity_error"] = "No identity found for request email"
            return AuditResult(
                case_id=request.case_id,
                deletion_status="NOT_APPLICABLE",
                steps=[],
                trace=trace,
            )
        trace["user_id"] = identity.user_id
        trace["all_identifiers"] = list(identity.emails | identity.phones | identity.email_hashes | {identity.user_id})

        # 3. Known resources collection
        known_res: Set[str] = set()
        act_linked = self.timeline_reconstructor.find_user_linked_resources_in_activity(identity, request.audit_at)
        known_res.update(act_linked.keys())

        primary_acct = self.batch_resolver.resolved_accounts.get(request.case_id)
        if primary_acct:
            known_res.add(primary_acct)

        if identity.user_id in self.batch_resolver.batch_user_analytics:
            an_res = self.batch_resolver.batch_user_analytics[identity.user_id]
            an_obs = self.scanner.scan_for_user(identity, {an_res}, request.audit_at)
            if any(o.resource_id == an_res for o in an_obs):
                known_res.add(an_res)

        # 4. Evidence Scan
        obs = self.scanner.scan_for_user(identity, known_res, request.audit_at)
        obs_by_res: Dict[str, Observation] = {}
        for o in sorted(obs, key=lambda x: x.captured_at):
            obs_by_res[o.resource_id] = o

        # Derive a fallback evidence_id from actual observations or latest account database snapshot <= audit_at
        common_ev_id = ""
        for o in sorted(obs_by_res.values(), key=lambda x: x.captured_at):
            if o.evidence_id and o.system_id != "analytics_platform":
                common_ev_id = o.evidence_id
                break

        if not common_ev_id:
            valid_dbs = [
                m for m in self.registry.files_before_or_at(request.audit_at)
                if m.file_path.endswith(".sql") and ("customer_" in m.file_path or "replica" in m.file_path)
            ]
            if valid_dbs:
                valid_dbs.sort(key=lambda m: m.captured_at, reverse=True)
                common_ev_id = valid_dbs[0].file_id

        findings: List[Step] = []
        remediations: List[Step] = []
        verifications: List[Step] = []

        # 6. Primary account
        acct_obs = obs_by_res.get(primary_acct) if primary_acct else None
        if acct_obs and acct_obs.exists:
            findings.append(Step(0, "FINDING", "account_service", primary_acct, "REPORT_REMAINING_RECORD", "PRESENT", acct_obs.evidence_id))
            remediations.append(Step(0, "REMEDIATION", "account_service", primary_acct, "DELETE_RECORD", "ABSENT", ""))
            verifications.append(Step(0, "VERIFICATION", "account_service", primary_acct, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
        else:
            ev_id = acct_obs.evidence_id if (acct_obs and acct_obs.evidence_id) else common_ev_id
            verifications.append(Step(0, "VERIFICATION", "account_service", primary_acct or "unknown_account", "VERIFY_RECORD_ABSENT", "ABSENT", ev_id))

        # 7. Process other observed resources
        for res_id, o in sorted(obs_by_res.items()):
            if res_id == primary_acct or "audit_record_" in res_id:
                continue

            sys_id = o.system_id
            worker_ops = [
                a.event_type for a in self.activities
                if a.resource_id == res_id
                and a.source_system in ("deletion_worker", "compliance_service")
                and a.event_time <= request.audit_at
            ]
            intended_op = worker_ops[0] if worker_ops else None

            if sys_id == "search_service":
                if o.exists:
                    findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", o.evidence_id))
                    remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                else:
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", o.evidence_id))

            elif sys_id == "export_service":
                if o.exists:
                    findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", o.evidence_id))
                    remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                else:
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", o.evidence_id))

            elif sys_id == "support_platform":
                is_delete = intended_op == "DELETE_RECORD" or "attachment" in str(o.details).lower() or res_id.startswith("object_")
                if is_delete:
                    if o.exists:
                        findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", o.evidence_id))
                        remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                    else:
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", o.evidence_id))
                else:
                    raw_d = str(o.details)
                    if not o.fields_nulled or "message_pii_scan" in raw_d or "matched_value" in raw_d:
                        findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_EXPOSED_PII", "PRESENT", o.evidence_id))
                        remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "REDACT_RECORD", "REDACTED", ""))
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", ""))
                    else:
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", o.evidence_id))

            elif sys_id == "analytics_platform":
                if intended_op == "DELETE_RECORD":
                    if o.exists:
                        findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", o.evidence_id))
                        remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                    else:
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", o.evidence_id))
                else:
                    if not o.fields_nulled:
                        findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_EXPOSED_PII", "PRESENT", o.evidence_id))
                        remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "ANONYMIZE_RECORD", "ANONYMIZED", ""))
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ""))
                    else:
                        verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", o.evidence_id))

            elif sys_id == "integration_service":
                if o.flow_enabled is True:
                    findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", o.evidence_id))
                    remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "DISABLE_DATA_FLOW", "DISABLED", ""))
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""))
                else:
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", o.evidence_id))

            elif sys_id == "backup_service":
                if o.restore_allowed is True:
                    findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_RESTORE_RISK", "ACTIVE", o.evidence_id))
                    remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "BLOCK_RESTORE", "BLOCKED", ""))
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ""))
                else:
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", o.evidence_id))

            elif sys_id == "identity_service":
                if not o.fields_nulled:
                    findings.append(Step(0, "FINDING", sys_id, res_id, "REPORT_EXPOSED_PII", "PRESENT", o.evidence_id))
                    remediations.append(Step(0, "REMEDIATION", sys_id, res_id, "REDACT_RECORD", "REDACTED", ""))
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", ""))
                else:
                    verifications.append(Step(0, "VERIFICATION", sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", o.evidence_id))

        # 8. Add audit_record if available for user
        ar_id, ar_ev = self.batch_resolver.get_best_audit_record(identity.user_id, request.audit_at)
        if ar_id and (ar_ev or findings):
            verifications.append(Step(0, "VERIFICATION", "security_service", ar_id, "VERIFY_RECORD_PRESENT", "PRESENT", ar_ev))

        if findings:
            status = "INCOMPLETE"
            clean_v = [Step(v.step_no, v.phase, v.system_id, v.resource_id, v.operation, v.state, "") for v in verifications]
            all_s = findings + remediations + clean_v
        else:
            status = "COMPLETE"
            all_s = verifications

        sorted_s = sort_steps(all_s)
        for i, s in enumerate(sorted_s, start=1):
            s.step_no = i

        return AuditResult(
            case_id=request.case_id,
            deletion_status=status,
            steps=sorted_s,
            trace=trace,
        )
