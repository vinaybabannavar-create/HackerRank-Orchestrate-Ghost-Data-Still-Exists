from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Set

from agent.evidence.base import Observation


def infer_system_id_from_table(table_name: str) -> str:
    tbl = table_name.lower()
    if "profile" in tbl or "account" in tbl:
        return "account_service"
    if "search" in tbl:
        return "search_service"
    if "analytics" in tbl:
        return "analytics_platform"
    if "support" in tbl:
        return "support_platform"
    if "export" in tbl:
        return "export_service"
    if "connector" in tbl or "data_flow" in tbl:
        return "integration_service"
    if "backup" in tbl or "restore" in tbl:
        return "backup_service"
    if "security" in tbl or "audit" in tbl:
        return "security_service"
    if "tombstone" in tbl or "deleted_customer" in tbl:
        return "identity_service"
    return "unknown_system"


class SqlEvidenceExtractor:
    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        conn = sqlite3.connect(":memory:")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                sql_content = f.read()
            conn.executescript(sql_content)
        except Exception:
            conn.close()
            return observations

        cur = conn.cursor()
        try:
            tables = [
                t[0]
                for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if not t[0].startswith("sqlite_")
            ]
        except Exception:
            conn.close()
            return observations

        for table_name in tables:
            default_system = infer_system_id_from_table(table_name)
            try:
                col_tuples = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
                cols = [c[1] for c in col_tuples]
                rows = cur.execute(f"SELECT * FROM {table_name}").fetchall()
            except Exception:
                continue

            for row in rows:
                row_dict = dict(zip(cols, row))
                res_id = str(row_dict.get("resource_id") or "").strip()
                if not res_id:
                    continue

                sys_id = row_dict.get("origin_system") or default_system

                # Check if row has record_json
                record_json_str = row_dict.get("record_json")
                if record_json_str and isinstance(record_json_str, str):
                    try:
                        parsed_json = json.loads(record_json_str)
                        for k, v in parsed_json.items():
                            if isinstance(v, dict):
                                for sub_k, sub_v in v.items():
                                    if sub_k not in row_dict:
                                        row_dict[sub_k] = sub_v
                            elif k not in row_dict:
                                row_dict[k] = v
                    except Exception:
                        pass

                identifiers: Set[str] = set()
                subj_ref = row_dict.get("customer_reference") or row_dict.get("subject_reference") or row_dict.get("user_id")
                if subj_ref:
                    subj_ref = str(subj_ref).strip()
                    identifiers.add(subj_ref)

                email = row_dict.get("email") or row_dict.get("owner_email") or row_dict.get("requester_email") or row_dict.get("customer_email")
                if email and isinstance(email, str) and email.strip() and email.lower() != "null":
                    identifiers.add(email.strip().lower())

                phone = row_dict.get("phone") or row_dict.get("owner_phone") or row_dict.get("requester_phone")
                if phone and isinstance(phone, str) and phone.strip() and phone.lower() != "null":
                    identifiers.add(phone.strip())

                hash_val = row_dict.get("email_hash")
                if hash_val and isinstance(hash_val, str) and hash_val.strip() and hash_val.lower() != "null":
                    identifiers.add(hash_val.strip().lower())

                # Direct PII null check
                # If email and phone and name are absent or None
                name_val = row_dict.get("full_name") or row_dict.get("display_name") or row_dict.get("requester_name")
                has_pii = bool(
                    (email and str(email).lower() not in ("null", "none", "")) or
                    (phone and str(phone).lower() not in ("null", "none", "")) or
                    (name_val and str(name_val).lower() not in ("null", "none", ""))
                )
                fields_nulled = not has_pii

                restore_allowed: Optional[bool] = None
                if "restore_allowed" in row_dict:
                    val = row_dict["restore_allowed"]
                    restore_allowed = bool(val) if val is not None else None

                flow_enabled: Optional[bool] = None
                if "enabled" in row_dict:
                    val = row_dict["enabled"]
                    flow_enabled = bool(val) if val is not None else None

                observations.append(
                    Observation(
                        evidence_id=file_id,
                        file_path=file_path,
                        captured_at=captured_at,
                        system_id=sys_id,
                        resource_id=res_id,
                        exists=True,
                        identifiers_present=identifiers,
                        fields_nulled=fields_nulled,
                        restore_allowed=restore_allowed,
                        flow_enabled=flow_enabled,
                        subject_reference=subj_ref,
                        details={"table": table_name, **row_dict},
                    )
                )

        conn.close()
        return observations
