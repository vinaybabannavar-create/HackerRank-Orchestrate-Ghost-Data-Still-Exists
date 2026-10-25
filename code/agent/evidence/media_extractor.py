from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from agent.evidence.base import Observation

try:
    from rapidocr_onnxruntime import RapidOCR
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False


def get_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


class MediaEvidenceExtractor:
    def __init__(self, cache_dir: str = "code/cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._ocr_engine = None

    def _get_ocr_engine(self):
        if self._ocr_engine is None and _OCR_AVAILABLE:
            self._ocr_engine = RapidOCR()
        return self._ocr_engine

    def extract(
        self, file_path: str, file_id: str, captured_at: datetime
    ) -> List[Observation]:
        observations: List[Observation] = []
        if not os.path.exists(file_path):
            return observations

        file_hash = get_file_sha256(file_path)
        ocr_text_cache = os.path.join(self.cache_dir, f"{file_hash}_ocr.txt")
        cache_path = os.path.join(self.cache_dir, f"{file_hash}.json")

        # 1. Check parsed observations cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    for item in cached_data:
                        observations.append(
                            Observation(
                                evidence_id=file_id,
                                file_path=file_path,
                                captured_at=captured_at,
                                system_id=item["system_id"],
                                resource_id=item["resource_id"],
                                exists=item.get("exists", True),
                                identifiers_present=set(item.get("identifiers_present", [])),
                                fields_nulled=item.get("fields_nulled", False),
                                restore_allowed=item.get("restore_allowed"),
                                flow_enabled=item.get("flow_enabled"),
                                subject_reference=item.get("subject_reference"),
                                details=item.get("details", {}),
                            )
                        )
                    return observations
            except Exception:
                pass

        # 2. Get OCR text (from text cache or run engine)
        full_ocr_text = ""
        if os.path.exists(ocr_text_cache):
            try:
                with open(ocr_text_cache, "r", encoding="utf-8") as f:
                    full_ocr_text = f.read()
            except Exception:
                pass

        if not full_ocr_text:
            engine = self._get_ocr_engine()
            if engine:
                try:
                    results, _ = engine(file_path)
                    if results:
                        lines = [r[1] for r in results]
                        full_ocr_text = "\n".join(lines)
                        with open(ocr_text_cache, "w", encoding="utf-8") as f:
                            f.write(full_ocr_text)
                except Exception:
                    pass

        # 3. Generic line-by-line parsing of OCR text
        base_name = os.path.basename(file_path).lower()
        sys_id = "unknown_system"
        if "account" in base_name:
            sys_id = "account_service"
        elif "search" in base_name:
            sys_id = "search_service"
        elif "analytic" in base_name:
            sys_id = "analytics_platform"
        elif "support" in base_name or "ticket" in base_name:
            sys_id = "support_platform"
        elif "export" in base_name:
            sys_id = "export_service"
        elif "connector" in base_name or "data_flow" in base_name:
            sys_id = "integration_service"
        elif "backup" in base_name:
            sys_id = "backup_service"
        elif "security" in base_name or "audit" in base_name:
            sys_id = "security_service"
        elif "marketing" in base_name:
            sys_id = "marketing_platform"
        elif "deleted_account" in base_name:
            sys_id = "identity_service"
        elif "object_storage" in base_name:
            sys_id = "support_platform"

        lines = full_ocr_text.splitlines()

        # Extract all identifiers in the whole document as fallback
        all_doc_emails = set(em.lower() for em in re.findall(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", full_ocr_text))
        all_doc_uids = set(re.findall(r"\buser_\d+\b", full_ocr_text))
        all_doc_phones = set(re.findall(r"\+\d{1,3}[\s\d-]{7,15}\d", full_ocr_text))

        # Find resources and their line numbers
        res_matches_by_line: List[Tuple[int, str]] = []
        for line_idx, line_text in enumerate(lines):
            # Normalize common OCR typos in prefixes and digits
            norm_line = line_text
            norm_line = re.sub(r"^acc0unt_", "account_", norm_line)
            norm_line = re.sub(r"^audit_rec0rd_", "audit_record_", norm_line)
            norm_line = re.sub(r"^exp0rt_", "export_", norm_line)
            norm_line = re.sub(r"^supp0rt_", "support_", norm_line)
            norm_line = re.sub(r"^data_fl0w_", "data_flow_", norm_line)
            
            # Find resources even with leading digits or typos
            matches = re.findall(r"(?:^|[^\w])((?:acc0unt|account|search|analytics|supp0rt|support|exp0rt|export|data_fl0w|data_flow|backup|audit_rec0rd|audit_record|tombstone|object|marketing)_[oO0-9]+)\b", norm_line)
            for m_raw in matches:
                pfx, num_part = m_raw.split("_", 1)
                num_part = num_part.replace("o", "0").replace("O", "0")
                pfx = pfx.replace("acc0unt", "account").replace("audit_rec0rd", "audit_record").replace("exp0rt", "export").replace("supp0rt", "support").replace("data_fl0w", "data_flow")
                clean_id = f"{pfx}_{num_part}"
                res_matches_by_line.append((line_idx, clean_id))

        # State extraction
        text_lower = full_ocr_text.lower()
        restore_allowed = None
        if sys_id == "backup_service":
            if "restore allowed" in text_lower or "healthy" in text_lower or "archive" in text_lower:
                restore_allowed = True
            elif "blocked" in text_lower or "restore disabled" in text_lower:
                restore_allowed = False
            else:
                restore_allowed = True

        flow_enabled = None
        if sys_id == "integration_service":
            if "enabled" in text_lower or "active" in text_lower or "connected" in text_lower:
                flow_enabled = True
            elif "disabled" in text_lower or "paused" in text_lower:
                flow_enabled = False
            else:
                flow_enabled = True

        fields_nulled = False
        if "redacted" in text_lower or "masked" in text_lower or "***" in text_lower:
            fields_nulled = True

        # Group by resource_id and associate with nearest line identifiers
        res_to_idents: Dict[str, Set[str]] = defaultdict(set)
        for line_idx, clean_id in res_matches_by_line:
            clean_id = (
                clean_id.replace("fl0w", "flow")
                .replace("acc0unt", "account")
                .replace("supp0rt", "support")
                .replace("exp0rt", "export")
                .replace("rec0rd", "record")
            )
            # Look in nearby lines window (-4 to +4)
            nearby_idents: List[Tuple[int, str]] = []
            for j in range(max(0, line_idx - 4), min(len(lines), line_idx + 5)):
                dist = abs(j - line_idx)
                em_j = re.findall(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", lines[j])
                u_j = re.findall(r"\buser_\d+\b", lines[j])
                p_j = re.findall(r"\+\d{1,3}[\s\d-]{7,15}\d", lines[j])
                for e in em_j: nearby_idents.append((dist, e.lower()))
                for u in u_j: nearby_idents.append((dist, u))
                for p in p_j: nearby_idents.append((dist, p))
            
            if nearby_idents:
                min_dist = min(item[0] for item in nearby_idents)
                closest = {item[1] for item in nearby_idents if item[0] == min_dist}
                res_to_idents[clean_id].update(closest)
            # If no nearby identifier found, leave empty — do NOT fall back to
            # all_doc_emails, which would incorrectly assign every person in the
            # document to this resource.

        cached_items = []
        for r_id in sorted(res_to_idents.keys()):
            r_sys = sys_id
            if r_id.startswith("audit_record_"):
                r_sys = "security_service"
            elif r_id.startswith("account_"):
                r_sys = "account_service"
            elif r_id.startswith("search_"):
                r_sys = "search_service"
            elif r_id.startswith("analytics_"):
                r_sys = "analytics_platform"
            elif r_id.startswith("data_flow_"):
                r_sys = "integration_service"
            elif r_id.startswith("backup_"):
                r_sys = "backup_service"
            elif r_id.startswith("support_"):
                r_sys = "support_platform"
            elif r_id.startswith("export_"):
                r_sys = "export_service"
            elif r_id.startswith("tombstone_"):
                r_sys = "identity_service"

            bound_idents = res_to_idents[r_id]
            subj_ref = next((i for i in bound_idents if i.startswith("user_")), None)

            obs = Observation(
                evidence_id=file_id,
                file_path=file_path,
                captured_at=captured_at,
                system_id=r_sys,
                resource_id=r_id,
                exists=True,
                identifiers_present=bound_idents,
                fields_nulled=fields_nulled,
                restore_allowed=restore_allowed,
                flow_enabled=flow_enabled,
                subject_reference=subj_ref,
                details={"file": os.path.basename(file_path), "ocr_sample": full_ocr_text[:300]},
            )
            observations.append(obs)
            cached_items.append({
                "system_id": r_sys,
                "resource_id": r_id,
                "exists": True,
                "identifiers_present": list(bound_idents),
                "fields_nulled": fields_nulled,
                "restore_allowed": restore_allowed,
                "flow_enabled": flow_enabled,
                "subject_reference": subj_ref,
                "details": {"file": os.path.basename(file_path)},
            })

        if cached_items:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cached_items, f, indent=2)
            except Exception:
                pass

        return observations
