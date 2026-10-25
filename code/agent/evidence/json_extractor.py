from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agent.evidence.base import Observation


class JsonEvidenceExtractor:
    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return observations

        if not isinstance(data, dict):
            return observations

        # Format 1: Multi-service export (service_resource_export_*.json)
        if "service_exports" in data and isinstance(data["service_exports"], dict):
            exports = data["service_exports"]
            # account_service
            for item in exports.get("account_service", {}).get("profile_lookups", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                status_code = item.get("status_code", 200)
                exists = (status_code == 200)
                profile = item.get("profile") or {}
                identifiers = set()
                uid = profile.get("user_id") or profile.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                em = profile.get("email")
                if em:
                    identifiers.add(str(em).strip().lower())
                ph = profile.get("phone")
                if ph:
                    identifiers.add(str(ph).strip())

                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="account_service",
                        resource_id=res_id,
                        exists=exists,
                        identifiers_present=identifiers,
                        fields_nulled=not bool(em or ph or profile.get("full_name")),
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # analytics_platform
            for item in exports.get("analytics_platform", {}).get("profiles", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("customer_reference") or item.get("user_id")
                if uid and str(uid).lower() not in ("null", "none"):
                    identifiers.add(str(uid).strip())
                em = item.get("email")
                if em and str(em).lower() not in ("null", "none"):
                    identifiers.add(str(em).strip().lower())
                ph = item.get("phone")
                if ph and str(ph).lower() not in ("null", "none"):
                    identifiers.add(str(ph).strip())
                h = item.get("email_hash")
                if h and str(h).lower() not in ("null", "none"):
                    identifiers.add(str(h).strip().lower())

                has_pii = bool(em or ph or h or uid)
                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="analytics_platform",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        fields_nulled=not has_pii,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # backup_service
            for item in exports.get("backup_service", {}).get("restore_entries", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                em = item.get("customer_email")
                if em:
                    identifiers.add(str(em).strip().lower())
                rest_allowed = item.get("restore_allowed")

                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="backup_service",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        restore_allowed=bool(rest_allowed) if rest_allowed is not None else None,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # export_service
            for item in exports.get("export_service", {}).get("exports", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                em = item.get("owner_email")
                if em:
                    identifiers.add(str(em).strip().lower())

                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="export_service",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # integration_service
            for item in exports.get("integration_service", {}).get("connectors", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                em = item.get("customer_email")
                if em:
                    identifiers.add(str(em).strip().lower())
                flow_en = item.get("enabled")

                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="integration_service",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        flow_enabled=bool(flow_en) if flow_en is not None else None,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # search_service
            for query in exports.get("search_service", {}).get("index_queries", []):
                hits = query.get("hits", {})
                for doc in hits.get("documents", []):
                    res_id = doc.get("resource_id")
                    if not res_id:
                        continue
                    identifiers = set()
                    uid = doc.get("customer_reference")
                    if uid:
                        identifiers.add(str(uid).strip())
                    em = doc.get("email")
                    if em:
                        identifiers.add(str(em).strip().lower())
                    observations.append(
                        Observation(
                            evidence_id=file_id,
                            file_path=file_path,
                            captured_at=captured_at,
                            system_id="search_service",
                            resource_id=res_id,
                            exists=True,
                            identifiers_present=identifiers,
                            subject_reference=str(uid) if uid else None,
                            details=doc,
                        )
                    )

            # security_service
            for item in exports.get("security_service", {}).get("audit_records", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("subject_reference") or item.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="security_service",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

            # support_platform
            for item in exports.get("support_platform", {}).get("tickets", []):
                res_id = item.get("resource_id")
                if not res_id:
                    continue
                identifiers = set()
                uid = item.get("customer_reference")
                if uid:
                    identifiers.add(str(uid).strip())
                em = item.get("requester_email")
                if em and str(em).lower() not in ("null", "none"):
                    identifiers.add(str(em).strip().lower())
                ph = item.get("requester_phone")
                if ph and str(ph).lower() not in ("null", "none"):
                    identifiers.add(str(ph).strip())
                name_val = item.get("requester_name")
                has_pii = bool(
                    (em and str(em).lower() not in ("null", "none", "")) or
                    (ph and str(ph).lower() not in ("null", "none", "")) or
                    (name_val and str(name_val).lower() not in ("null", "none", ""))
                )
                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id="support_platform",
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        fields_nulled=not has_pii,
                        subject_reference=str(uid) if uid else None,
                        details=item,
                    )
                )

        # Format 2: Snapshots bundle (customer_data_snapshot_bundle_*.json)
        elif "snapshots" in data and isinstance(data["snapshots"], list):
            for snap in data["snapshots"]:
                store = snap.get("data_store", "unknown_system")
                for rec in snap.get("records", []):
                    res_id = rec.get("resource_id")
                    if not res_id:
                        continue
                    identifiers = set()
                    uid = rec.get("subject_reference") or rec.get("customer_reference") or rec.get("user_id")
                    if uid and str(uid).lower() not in ("null", "none"):
                        identifiers.add(str(uid).strip())
                    em = rec.get("email")
                    if em and str(em).lower() not in ("null", "none"):
                        identifiers.add(str(em).strip().lower())
                    ph = rec.get("phone")
                    if ph and str(ph).lower() not in ("null", "none"):
                        identifiers.add(str(ph).strip())
                    h = rec.get("email_hash")
                    if h and str(h).lower() not in ("null", "none"):
                        identifiers.add(str(h).strip().lower())

                    name_val = rec.get("name") or rec.get("full_name")
                    has_pii = bool(
                        (em and str(em).lower() not in ("null", "none", "")) or
                        (ph and str(ph).lower() not in ("null", "none", "")) or
                        (name_val and str(name_val).lower() not in ("null", "none", "")) or
                        (h and str(h).lower() not in ("null", "none", ""))
                    )

                    restore_allowed: Optional[bool] = None
                    if "restore_allowed" in rec:
                        val = rec["restore_allowed"]
                        restore_allowed = bool(val) if val is not None else None

                    flow_enabled: Optional[bool] = None
                    if "enabled" in rec:
                        val = rec["enabled"]
                        flow_enabled = bool(val) if val is not None else None

                    exists = True
                    if store != "identity_service" and not res_id.startswith("tombstone_"):
                        if rec.get("account_status") == "DELETED" or rec.get("status") == "DELETED":
                            exists = False

                    observations.append(
                        Observation(
                            evidence_id=file_id,
                            file_path=file_path,
                            captured_at=captured_at,
                            system_id=store,
                            resource_id=res_id,
                            exists=exists,
                            identifiers_present=identifiers,
                            fields_nulled=not has_pii,
                            restore_allowed=restore_allowed,
                            flow_enabled=flow_enabled,
                            subject_reference=str(uid) if uid else None,
                            details=rec,
                        )
                    )

        # Format 3: Flat record collections (e.g. customer_export_jobs_*.json, customer_analytics_report_*.json)
        elif "records" in data and isinstance(data["records"], list):
            src = data.get("source", "").lower()
            coll = data.get("collection", "").lower()
            default_sys = "unknown_system"
            if "export" in src or "export" in coll:
                default_sys = "export_service"
            elif "analytic" in src or "analytic" in coll:
                default_sys = "analytics_platform"
            elif "support" in src or "ticket" in coll:
                default_sys = "support_platform"
            elif "account" in src or "profile" in coll:
                default_sys = "account_service"

            for rec in data["records"]:
                res_id = rec.get("resource_id")
                if not res_id:
                    continue
                sys_id = rec.get("system") or default_sys
                identifiers = set()
                uid = rec.get("user_id") or rec.get("customer_reference") or rec.get("subject_reference")
                if uid and str(uid).lower() not in ("null", "none"):
                    identifiers.add(str(uid).strip())
                em = rec.get("email") or rec.get("owner_email") or rec.get("customer_email")
                if em and str(em).lower() not in ("null", "none"):
                    identifiers.add(str(em).strip().lower())
                ph = rec.get("phone") or rec.get("owner_phone")
                if ph and str(ph).lower() not in ("null", "none"):
                    identifiers.add(str(ph).strip())
                h = rec.get("email_hash")
                if h and str(h).lower() not in ("null", "none"):
                    identifiers.add(str(h).strip().lower())

                res_result = rec.get("result")
                exists = (res_result != "NOT_FOUND")

                has_pii = bool(em or ph or (h and str(h).lower() not in ("null", "none")))
                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id=sys_id,
                        resource_id=res_id,
                        exists=exists,
                        identifiers_present=identifiers,
                        fields_nulled=not has_pii,
                        subject_reference=str(uid) if uid else None,
                        details=rec,
                    )
                )

        return observations
