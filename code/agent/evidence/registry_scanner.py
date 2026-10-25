from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional, Set

from agent.evidence.base import Observation
from agent.evidence.json_extractor import JsonEvidenceExtractor
from agent.evidence.log_extractor import LogEvidenceExtractor
from agent.evidence.media_extractor import MediaEvidenceExtractor
from agent.evidence.pdf_extractor import PdfEvidenceExtractor
from agent.evidence.sql_extractor import SqlEvidenceExtractor
from agent.evidence.txt_extractor import TxtEvidenceExtractor
from agent.identity import ResolvedIdentity
from agent.loaders import EvidenceFileManifest, EvidenceRegistry


class EvidenceScanner:
    def __init__(self, registry: EvidenceRegistry):
        self.registry = registry
        self.sql_extractor = SqlEvidenceExtractor()
        self.json_extractor = JsonEvidenceExtractor()
        self.log_extractor = LogEvidenceExtractor()
        self.pdf_extractor = PdfEvidenceExtractor()
        self.txt_extractor = TxtEvidenceExtractor()
        self.media_extractor = MediaEvidenceExtractor()
        # In-memory cache of parsed file observations: file_id -> List[Observation]
        self._parsed_cache: Dict[str, List[Observation]] = {}

    def parse_file(self, manifest: EvidenceFileManifest) -> List[Observation]:
        if manifest.file_id in self._parsed_cache:
            return self._parsed_cache[manifest.file_id]

        abs_path = self.registry.absolute_path(manifest)
        ext = os.path.splitext(abs_path)[1].lower()

        if ext == ".sql":
            obs = self.sql_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        elif ext == ".json":
            obs = self.json_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        elif ext == ".log":
            obs = self.log_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        elif ext == ".pdf":
            obs = self.pdf_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        elif ext == ".txt":
            obs = self.txt_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        elif ext == ".png":
            obs = self.media_extractor.extract(abs_path, manifest.file_id, manifest.captured_at)
        else:
            obs = []

        self._parsed_cache[manifest.file_id] = obs
        return obs

    def scan_for_user(
        self,
        identity: ResolvedIdentity,
        known_resources: Set[str],
        audit_at: datetime,
    ) -> List[Observation]:
        """
        Scan all evidence captured <= audit_at for observations matching the user's
        strong identifiers or known resources.
        """
        valid_manifests = self.registry.files_before_or_at(audit_at)
        matching_obs: List[Observation] = []

        for m in valid_manifests:
            file_obs = self.parse_file(m)
            for obs in file_obs:
                is_match = False
                # 1. Matches by known resource ID
                if obs.resource_id in known_resources:
                    is_match = True
                # 2. Matches by subject reference
                elif obs.subject_reference and obs.subject_reference == identity.user_id:
                    is_match = True
                # 3. Matches by strong identifiers present in observation
                elif any(identity.matches_identifier(ident) for ident in obs.identifiers_present):
                    is_match = True

                if is_match:
                    matching_obs.append(obs)

        return matching_obs
