from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

from agent.loaders import UserAuditLogEntry, UserIdentity


def compute_email_hash(email: str) -> str:
    """Compute the standard SHA-256 hash of a lowercased, trimmed email."""
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class ResolvedIdentity:
    user_id: str
    name: str
    primary_email: str
    emails: Set[str] = field(default_factory=set)
    phones: Set[str] = field(default_factory=set)
    email_hashes: Set[str] = field(default_factory=set)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None

    def matches_identifier(self, val: Optional[str]) -> bool:
        """Check if any field value matches a strong identifier of this user."""
        if not val or not isinstance(val, str):
            return False
        cleaned = val.strip()
        cleaned_lower = cleaned.lower()
        if cleaned == self.user_id:
            return True
        if cleaned_lower in self.emails:
            return True
        if cleaned in self.phones:
            return True
        if cleaned_lower in self.email_hashes:
            return True
        return False


class IdentityResolver:
    def __init__(self, identities: Dict[str, UserIdentity], audit_log: List[UserAuditLogEntry]):
        self.identities = identities
        self.audit_log = audit_log

    def resolve(self, request_email: str, audit_at: datetime) -> Optional[ResolvedIdentity]:
        req_norm = request_email.strip().lower()

        # Step 1: Find candidate user_ids matching the request email as of audit_at
        # Candidate from current identities
        candidates: Set[str] = set()
        for uid, ident in self.identities.items():
            if ident.email.strip().lower() == req_norm:
                candidates.add(uid)

        # Candidates from historical audit log (events <= audit_at)
        for entry in self.audit_log:
            if entry.event_time <= audit_at and entry.field_name == "email":
                if entry.old_value.strip().lower() == req_norm or entry.new_value.strip().lower() == req_norm:
                    candidates.add(entry.user_id)

        if not candidates:
            # No user matches this email
            return None

        if len(candidates) > 1:
            # Multiple users share this email!
            primary_uid = sorted(candidates)[0]
            ident = self.identities.get(primary_uid)
            return ResolvedIdentity(
                user_id=primary_uid,
                name=ident.name if ident else "Unknown",
                primary_email=request_email,
                is_ambiguous=True,
                ambiguity_reason=f"Request email '{request_email}' matches multiple users: {sorted(candidates)}",
            )

        user_id = list(candidates)[0]
        ident = self.identities.get(user_id)
        if not ident:
            return None

        # Step 2: Collect all identifiers for this user_id as of audit_at
        emails: Set[str] = {ident.email.strip().lower(), req_norm}
        phones: Set[str] = {ident.phone.strip()} if ident.phone else set()
        hashes: Set[str] = {ident.email_hash.strip().lower()} if ident.email_hash else set()

        # Add computed hash of current & request email
        hashes.add(compute_email_hash(ident.email))
        hashes.add(compute_email_hash(req_norm))

        # Check audit log for historical values <= audit_at
        for entry in self.audit_log:
            if entry.user_id == user_id and entry.event_time <= audit_at:
                if entry.field_name == "email":
                    if entry.old_value:
                        old_em = entry.old_value.strip().lower()
                        emails.add(old_em)
                        hashes.add(compute_email_hash(old_em))
                    if entry.new_value:
                        new_em = entry.new_value.strip().lower()
                        emails.add(new_em)
                        hashes.add(compute_email_hash(new_em))
                elif entry.field_name == "phone":
                    if entry.old_value:
                        phones.add(entry.old_value.strip())
                    if entry.new_value:
                        phones.add(entry.new_value.strip())
                elif entry.field_name == "email_hash":
                    if entry.old_value:
                        hashes.add(entry.old_value.strip().lower())
                    if entry.new_value:
                        hashes.add(entry.new_value.strip().lower())

        return ResolvedIdentity(
            user_id=user_id,
            name=ident.name,
            primary_email=ident.email,
            emails=emails,
            phones=phones,
            email_hashes=hashes,
        )
