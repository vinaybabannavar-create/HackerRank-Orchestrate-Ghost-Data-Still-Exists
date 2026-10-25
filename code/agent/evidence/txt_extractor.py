from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Set

from agent.evidence.base import Observation


class TxtEvidenceExtractor:
    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return observations

        for line in lines:
            line_str = line.strip()
            if not line_str or "|" not in line_str:
                continue

            parts = [p.strip() for p in line_str.lstrip("-").split("|")]
            if len(parts) < 5:
                continue

            # Format: timestamp | system_id | resource_id | record_type | status | identifier_or_note
            sys_id = parts[1]
            res_id = parts[2]
            status_token = parts[4].upper()
            note = parts[5] if len(parts) > 5 else ""

            exists = True
            if status_token in ("NOT_FOUND", "ABSENT", "DELETED"):
                exists = False

            fields_nulled = False
            if status_token in ("ANONYMIZED", "REDACTED") or "no direct identifier" in note.lower():
                fields_nulled = True

            flow_enabled = None
            if status_token == "ACTIVE" and "integration" in sys_id:
                flow_enabled = True
            elif status_token == "DISABLED" and "integration" in sys_id:
                flow_enabled = False

            restore_allowed = None
            if status_token == "ACTIVE" and "backup" in sys_id:
                restore_allowed = True
            elif status_token == "BLOCKED" and "backup" in sys_id:
                restore_allowed = False

            identifiers: Set[str] = set()
            subj_ref = None

            # Find emails, user_ids in note
            emails = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", note)
            for em in emails:
                identifiers.add(em.strip().lower())

            uids = re.findall(r"\b(user_\d+)\b", note)
            for uid in uids:
                identifiers.add(uid)
                subj_ref = uid

            observations.append(
                Observation(
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
                    details={"raw_line": line_str, "status": status_token, "note": note},
                )
            )

        return observations
