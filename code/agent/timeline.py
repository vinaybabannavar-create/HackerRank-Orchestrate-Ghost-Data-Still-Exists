from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

from agent.identity import ResolvedIdentity
from agent.loaders import SystemActivityEntry


@dataclass
class ResourceTimeline:
    resource_id: str
    target_system: str
    events: List[SystemActivityEntry] = field(default_factory=list)
    latest_event: Optional[SystemActivityEntry] = None
    latest_action: Optional[str] = None
    latest_result: Optional[str] = None
    is_flow_active: bool = False
    is_restore_risk: bool = False
    recreated_after_delete: bool = False

    def summarize_claim(self) -> str:
        """Summarize the claimed state based strictly on system activity events."""
        if self.is_flow_active:
            return "ACTIVE_FLOW"
        if self.is_restore_risk:
            return "RESTORE_RISK"
        if not self.latest_event:
            return "UNKNOWN"
        return f"{self.latest_action}:{self.latest_result}"


class TimelineReconstructor:
    def __init__(self, activities: List[SystemActivityEntry]):
        self.activities = activities
        # Pre-index activities by resource_id
        self.by_resource: Dict[str, List[SystemActivityEntry]] = {}
        for act in activities:
            self.by_resource.setdefault(act.resource_id, []).append(act)
        # Sort each resource's events chronologically
        for res_id in self.by_resource:
            self.by_resource[res_id].sort(key=lambda a: a.event_time)

    def find_user_linked_resources_in_activity(
        self, identity: ResolvedIdentity, audit_at: datetime
    ) -> Dict[str, str]:
        """
        Find resources directly linked to the user within system_activity.csv <= audit_at.
        Returns a dict mapping resource_id -> target_system.
        """
        linked: Dict[str, str] = {}
        for act in self.activities:
            if act.event_time > audit_at:
                continue
            # Check LINK_RESOURCE_IDENTITY or mentions of email/user_id in details
            details_lower = act.details.lower()
            matches_user = False

            if act.event_type == "LINK_RESOURCE_IDENTITY":
                # Check user_id or any email
                if identity.user_id in act.details or any(em in details_lower for em in identity.emails):
                    matches_user = True
            elif "@" in act.details or "user_" in act.details:
                if identity.user_id in act.details or any(em in details_lower for em in identity.emails):
                    matches_user = True

            if matches_user and act.resource_id:
                linked[act.resource_id] = act.target_system
        return linked

    def build_timeline_for_resource(
        self, resource_id: str, default_system: str, audit_at: datetime
    ) -> ResourceTimeline:
        """Build the chronological event timeline for a specific resource <= audit_at."""
        events = [
            a for a in self.by_resource.get(resource_id, [])
            if a.event_time <= audit_at
        ]
        timeline = ResourceTimeline(
            resource_id=resource_id,
            target_system=default_system,
            events=events,
        )
        if not events:
            return timeline

        timeline.latest_event = events[-1]
        timeline.latest_action = events[-1].event_type
        timeline.latest_result = events[-1].reported_result
        timeline.target_system = events[-1].target_system or default_system

        # Track delete vs recreate / sync / restore
        last_delete_time: Optional[datetime] = None
        for ev in events:
            if ev.event_type == "DELETE_RECORD" and ev.reported_result == "SUCCESS":
                last_delete_time = ev.event_time
            elif ev.event_type in ("SYNC_RECORD", "RESTORE_BACKUP", "INDEX_RECORD", "UPDATE_RECORD"):
                if last_delete_time and ev.event_time > last_delete_time and ev.reported_result == "SUCCESS":
                    timeline.recreated_after_delete = True

            # Data flow checks
            if ev.event_type == "CHECK_DATA_FLOW":
                if "remains enabled" in ev.details.lower():
                    timeline.is_flow_active = True
            elif ev.event_type == "DISABLE_DATA_FLOW" and ev.reported_result == "SUCCESS":
                timeline.is_flow_active = False

            # Restore risk checks
            if ev.event_type == "CHECK_RESTORE_ACCESS":
                if ev.reported_result == "SUCCESS":
                    timeline.is_restore_risk = True
            elif ev.event_type == "BLOCK_RESTORE" and ev.reported_result == "SUCCESS":
                timeline.is_restore_risk = False

        return timeline
