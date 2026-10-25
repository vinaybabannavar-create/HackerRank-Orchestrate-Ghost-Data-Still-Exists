from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


def parse_datetime(dt_str: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime."""
    if not dt_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    cleaned = dt_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class DeletionRequest:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str
    reported_at: datetime
    audit_at: datetime
    request_text: str


@dataclass(frozen=True)
class UserIdentity:
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime


@dataclass(frozen=True)
class UserAuditLogEntry:
    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


@dataclass(frozen=True)
class SystemActivityEntry:
    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass(frozen=True)
class DeletionRule:
    rule_id: str
    data_category: str
    condition: str
    required_action: str


@dataclass(frozen=True)
class EvidenceFileManifest:
    file_id: str
    file_path: str
    origin: str
    captured_at: datetime


class EvidenceRegistry:
    def __init__(self, manifests: List[EvidenceFileManifest], base_dir: str = "dataset"):
        self.base_dir = base_dir
        self.by_id: Dict[str, EvidenceFileManifest] = {m.file_id: m for m in manifests}
        self.by_path: Dict[str, EvidenceFileManifest] = {m.file_path: m for m in manifests}
        # Sorted chronologically
        self.chronological: List[EvidenceFileManifest] = sorted(manifests, key=lambda m: m.captured_at)

    def get(self, file_id: str) -> Optional[EvidenceFileManifest]:
        return self.by_id.get(file_id)

    def files_before_or_at(self, cutoff: datetime) -> List[EvidenceFileManifest]:
        return [m for m in self.chronological if m.captured_at <= cutoff]

    def absolute_path(self, manifest: EvidenceFileManifest) -> str:
        # file_path in evidence_files.csv is relative to dataset/ e.g. "evidence/logs/..."
        return os.path.normpath(os.path.join(self.base_dir, manifest.file_path))


class DatasetLoaders:
    def __init__(self, dataset_dir: str = "dataset"):
        self.dataset_dir = dataset_dir

    def _path(self, filename: str) -> str:
        return os.path.join(self.dataset_dir, filename)

    def load_deletion_requests(self, filename: str = "deletion_requests.csv") -> List[DeletionRequest]:
        requests = []
        with open(self._path(filename), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                requests.append(
                    DeletionRequest(
                        case_id=row["case_id"].strip(),
                        email=row["email"].strip(),
                        requested_at=parse_datetime(row["requested_at"]),
                        reported_status=row["reported_status"].strip(),
                        reported_at=parse_datetime(row["reported_at"]),
                        audit_at=parse_datetime(row["audit_at"]),
                        request_text=row["request_text"].strip(),
                    )
                )
        return requests

    def load_user_identities(self) -> Dict[str, UserIdentity]:
        identities = {}
        with open(self._path("user_identities.csv"), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = row["user_id"].strip()
                identities[uid] = UserIdentity(
                    user_id=uid,
                    name=row["name"].strip(),
                    email=row["email"].strip(),
                    phone=row["phone"].strip(),
                    email_hash=row["email_hash"].strip(),
                    updated_at=parse_datetime(row["updated_at"]),
                )
        return identities

    def load_user_audit_log(self) -> List[UserAuditLogEntry]:
        entries = []
        with open(self._path("user_audit_log.csv"), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entries.append(
                    UserAuditLogEntry(
                        audit_id=row["audit_id"].strip(),
                        user_id=row["user_id"].strip(),
                        event_time=parse_datetime(row["event_time"]),
                        field_name=row["field_name"].strip(),
                        old_value=row["old_value"].strip(),
                        new_value=row["new_value"].strip(),
                    )
                )
        return entries

    def load_system_activity(self) -> List[SystemActivityEntry]:
        activities = []
        with open(self._path("system_activity.csv"), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                activities.append(
                    SystemActivityEntry(
                        activity_id=row["activity_id"].strip(),
                        event_time=parse_datetime(row["event_time"]),
                        event_type=row["event_type"].strip(),
                        source_system=row["source_system"].strip(),
                        target_system=row["target_system"].strip(),
                        resource_id=row["resource_id"].strip(),
                        reported_result=row["reported_result"].strip(),
                        details=row["details"].strip(),
                    )
                )
        return activities

    def load_deletion_rules(self) -> List[DeletionRule]:
        rules = []
        with open(self._path("deletion_rules.csv"), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rules.append(
                    DeletionRule(
                        rule_id=row["rule_id"].strip(),
                        data_category=row["data_category"].strip(),
                        condition=row["condition"].strip(),
                        required_action=row["required_action"].strip(),
                    )
                )
        return rules

    def load_evidence_manifest(self) -> EvidenceRegistry:
        manifests = []
        with open(self._path("evidence_files.csv"), "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                manifests.append(
                    EvidenceFileManifest(
                        file_id=row["file_id"].strip(),
                        file_path=row["file_path"].strip(),
                        origin=row["origin"].strip(),
                        captured_at=parse_datetime(row["captured_at"]),
                    )
                )
        return EvidenceRegistry(manifests, base_dir=self.dataset_dir)
