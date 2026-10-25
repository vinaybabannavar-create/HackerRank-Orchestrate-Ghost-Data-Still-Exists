from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Set


@dataclass
class Observation:
    evidence_id: str
    file_path: str
    captured_at: datetime
    system_id: str
    resource_id: str
    exists: bool = True
    identifiers_present: Set[str] = field(default_factory=set)
    fields_nulled: bool = False
    restore_allowed: Optional[bool] = None
    flow_enabled: Optional[bool] = None
    subject_reference: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
