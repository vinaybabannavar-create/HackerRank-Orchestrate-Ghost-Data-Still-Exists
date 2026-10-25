from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Set

import pypdf

from agent.evidence.base import Observation


class PdfEvidenceExtractor:
    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        try:
            reader = pypdf.PdfReader(file_path)
            full_text = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception:
            return observations

        # Extract identifiers and resource ids
        res_ids = set(re.findall(r"\b(support_\d+|account_\d+|audit_record_\d+|export_\d+|search_\d+|analytics_\d+|object_\d+)\b", full_text))
        user_ids = set(re.findall(r"\b(user_\d+)\b", full_text))
        emails = set(em.strip().lower() for em in re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", full_text))
        phones = set(re.findall(r"\+\d{1,3}[\s\d-]{7,15}\d", full_text))

        # Infer system
        text_lower = full_text.lower()
        if "support" in text_lower or "delivery" in text_lower:
            sys_id = "support_platform"
        elif "compliance" in text_lower or "audit" in text_lower or "journal" in text_lower:
            sys_id = "security_service"
        elif "account" in text_lower or "statement" in text_lower:
            sys_id = "account_service"
        elif "export" in text_lower:
            sys_id = "export_service"
        else:
            sys_id = "unknown_system"

        all_identifiers: Set[str] = set()
        all_identifiers.update(user_ids)
        all_identifiers.update(emails)
        all_identifiers.update(phones)

        primary_uid = list(user_ids)[0] if user_ids else None

        for res_id in res_ids:
            observations.append(
                Observation(
                    evidence_id=file_id,
                    file_path=file_path,
                    captured_at=captured_at,
                    system_id=sys_id,
                    resource_id=res_id,
                    exists=True,
                    identifiers_present=all_identifiers,
                    fields_nulled=False,
                    subject_reference=primary_uid,
                    details={"file": os.path.basename(file_path), "text_sample": full_text[:400]},
                )
            )

        return observations
