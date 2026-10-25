from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from agent.evidence.base import Observation


KV_REGEX = re.compile(r'(\w+)=(?:"([^"]*)"|([^\s]+))')


def normalize_log_system(svc_name: str) -> str:
    s = svc_name.lower().strip()
    if "support" in s:
        return "support_platform"
    if "account" in s or "profile" in s:
        return "account_service"
    if "search" in s:
        return "search_service"
    if "analytic" in s:
        return "analytics_platform"
    if "integration" in s or "connector" in s:
        return "integration_service"
    if "backup" in s:
        return "backup_service"
    if "security" in s:
        return "security_service"
    if "export" in s:
        return "export_service"
    if "tombstone" in s:
        return "identity_service"
    return s


class LogEvidenceExtractor:
    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        # Track observations per resource_id across lines in the log
        # Because one line might start lookup (lookup_key) and next line complete it (http_status)
        recent_lookups: Dict[str, Dict[str, str]] = {}
        completed_obs: Dict[str, Observation] = {}

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return observations

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            matches = {}
            json_start = line_str.find("{")
            if json_start != -1 and line_str.endswith("}"):
                try:
                    matches = json.loads(line_str[json_start:])
                except Exception:
                    pass
            if not matches:
                matches = {
                    m[0]: m[1] if m[1] != "" else m[2]
                    for m in KV_REGEX.findall(line_str)
                }

            res_id = matches.get("resource_id") or matches.get("resource")
            lookup_key = matches.get("lookup_key") or matches.get("correlation_key") or matches.get("subject_key") or matches.get("subject_ref")
            trace_id = matches.get("trace_id")

            # Associate trace_id with lookup_key
            if trace_id and lookup_key:
                recent_lookups[trace_id] = {"lookup_key": lookup_key}

            if not res_id:
                continue

            svc = matches.get("service") or matches.get("system") or matches.get("function") or "unknown_system"
            sys_id = normalize_log_system(svc)

            # Check existence clues
            rows_str = matches.get("rows")
            http_status = str(matches.get("http_status", ""))
            result_str = str(matches.get("result", "")).lower()

            exists = True
            if rows_str is not None and str(rows_str).isdigit():
                if int(rows_str) == 0:
                    exists = False
                elif int(rows_str) > 0:
                    exists = True
            if http_status == "404":
                exists = False
            elif http_status == "200":
                exists = True
            if result_str == "miss":
                exists = False
            elif result_str == "hit":
                exists = True

            identifiers: Set[str] = set()
            subj_ref = matches.get("subject_reference") or matches.get("customer_reference") or matches.get("user_id") or matches.get("subject_ref")
            if subj_ref and str(subj_ref).lower() not in ("null", "none"):
                subj_ref = str(subj_ref).strip()
                identifiers.add(subj_ref)

            email = matches.get("email") or matches.get("customer_email") or matches.get("requester_email")
            if email and str(email).lower() not in ("null", "none"):
                identifiers.add(str(email).strip().lower())

            phone = matches.get("phone") or matches.get("requester_phone")
            if phone and str(phone).lower() not in ("null", "none"):
                identifiers.add(str(phone).strip())

            # Any lookup key or correlation key is a potential strong identifier (email, user_id, hash, phone)
            if lookup_key and str(lookup_key).lower() not in ("null", "none"):
                k_val = str(lookup_key).strip()
                identifiers.add(k_val.lower())
                if k_val.startswith("user_") and not subj_ref:
                    subj_ref = k_val

            # If there was a preceding lookup started for this trace
            if trace_id and trace_id in recent_lookups:
                prior_key = recent_lookups[trace_id].get("lookup_key")
                if prior_key and str(prior_key).lower() not in ("null", "none"):
                    pk_val = str(prior_key).strip()
                    identifiers.add(pk_val.lower())
                    if pk_val.startswith("user_") and not subj_ref:
                        subj_ref = pk_val

            has_pii = bool(
                (email and str(email).lower() not in ("null", "none", "")) or
                (phone and str(phone).lower() not in ("null", "none", "")) or
                (matches.get("requester_name") and str(matches.get("requester_name")).lower() not in ("null", "none", ""))
            )
            fields_nulled = not has_pii

            flow_enabled: Optional[bool] = None
            if "enabled" in matches:
                flow_enabled = str(matches["enabled"]).lower() == "true"
            elif matches.get("last_delivery_status") == "delivered":
                flow_enabled = True
            elif matches.get("last_delivery_status") == "stopped":
                flow_enabled = False

            restore_allowed: Optional[bool] = None
            if "restore_allowed" in matches:
                restore_allowed = str(matches["restore_allowed"]).lower() == "true"
            elif "deletion_block" in matches:
                restore_allowed = str(matches["deletion_block"]).lower() == "false"
            elif matches.get("event") == "restore_candidate_evaluated":
                eligible = str(matches.get("eligible", "")).lower() == "true"
                del_block = str(matches.get("deletion_block", "")).lower() == "true"
                restore_allowed = eligible and not del_block
            elif matches.get("decision") == "deny":
                restore_allowed = False
            elif matches.get("decision") == "allow":
                restore_allowed = True

            # Merge or store observation for this resource
            if res_id in completed_obs:
                existing = completed_obs[res_id]
                existing.identifiers_present.update(identifiers)
                if not exists:
                    existing.exists = False
                if flow_enabled is not None:
                    existing.flow_enabled = flow_enabled
                if restore_allowed is not None:
                    existing.restore_allowed = restore_allowed
                if subj_ref:
                    existing.subject_reference = subj_ref
                if not fields_nulled:
                    existing.fields_nulled = False
                existing.details.update(matches)
            else:
                obs = Observation(
                    evidence_id=file_id,
                    file_path=file_path,
                    captured_at=captured_at,
                    system_id=sys_id,
                    resource_id=res_id,
                    exists=exists,
                    identifiers_present=identifiers,
                    fields_nulled=fields_nulled,
                    restore_allowed=restore_allowed,
                    flow_enabled=flow_enabled,
                    subject_reference=subj_ref,
                    details=matches,
                )
                completed_obs[res_id] = obs

        return list(completed_obs.values())
