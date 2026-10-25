from __future__ import annotations

import csv
import json
import os
import sys
import time

# Ensure current, parent, and working directories are in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
cwd = os.getcwd()

for p in [current_dir, parent_dir, cwd]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

# Robust dataset and repo root discovery across all evaluation environments
def find_dataset_and_root() -> tuple[str, str]:
    candidates = [
        parent_dir,
        cwd,
        current_dir,
    ]
    for c in candidates:
        ds = os.path.join(c, "dataset")
        if os.path.isdir(ds) and os.path.exists(os.path.join(ds, "deletion_requests.csv")):
            return ds, c
    # Fallback default
    return os.path.join(parent_dir, "dataset"), parent_dir

dataset_dir, repo_root = find_dataset_and_root()

from agent.engine import BatchResolver, DeletionAuditEngine
from agent.evidence.registry_scanner import EvidenceScanner
from agent.identity import IdentityResolver
from agent.loaders import DatasetLoaders
from agent.timeline import TimelineReconstructor
from agent.validator import validate_output_file


def main():
    start_time = time.time()
    print("==================================================================")
    print("HackerRank Orchestrate: Ghost Data Still Exists")
    print("AI-Powered Deletion Audit Engine")
    print("==================================================================")

    dataset_dir = os.path.join(repo_root, "dataset")
    loaders = DatasetLoaders(dataset_dir)

    print("1. Loading dataset files...")
    idents = loaders.load_user_identities()
    audit_log = loaders.load_user_audit_log()
    acts = loaders.load_system_activity()
    manifest = loaders.load_evidence_manifest()
    rules = loaders.load_deletion_rules()

    print(f"   Loaded {len(idents)} user identities, {len(audit_log)} audit log entries, "
          f"{len(acts)} system activities, {len(manifest.by_id)} evidence files.")

    print("2. Initializing core engine components...")
    resolver = IdentityResolver(idents, audit_log)
    timeline_rec = TimelineReconstructor(acts)
    scanner = EvidenceScanner(manifest)

    print("3. Building BatchResolver and extracting evidence across repositories...")
    batch_resolver = BatchResolver(manifest, acts, resolver, scanner)
    print(f"   Discovered {len(batch_resolver.user_audit_records_all)} users with audit records.")
    print(f"   Discovered {len(batch_resolver.direct_accounts)} direct account mappings.")

    print("4. Loading evaluation requests from dataset/deletion_requests.csv...")
    requests = loaders.load_deletion_requests("deletion_requests.csv")
    print(f"   Loaded {len(requests)} evaluation requests.")

    print("5. Resolving batch windows across evaluation requests...")
    batch_resolver.resolve_batches(requests)
    print(f"   Resolved accounts for {len(batch_resolver.resolved_accounts)} requests.")
    print(f"   Resolved batch analytics profiles for {len(batch_resolver.batch_user_analytics)} users.")

    print("6. Executing deletion audit across all cases...")
    engine = DeletionAuditEngine(resolver, scanner, timeline_rec, manifest, acts, batch_resolver)

    trace_dir = os.path.join(current_dir, "trace")
    os.makedirs(trace_dir, exist_ok=True)

    results = []
    status_counts = defaultdict_int = {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0}
    total_steps = 0

    for idx, req in enumerate(requests, start=1):
        res = engine.audit_case(req)
        results.append(res)
        status_counts[res.deletion_status] += 1
        total_steps += len(res.steps)

        # Write debug trace per case
        trace_path = os.path.join(trace_dir, f"{req.case_id}.json")
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump({
                "case_id": res.case_id,
                "deletion_status": res.deletion_status,
                "steps": [s.to_dict() for s in res.steps],
                "trace": res.trace,
            }, f, indent=2)

        if idx % 100 == 0 or idx == len(requests):
            print(f"   Processed {idx}/{len(requests)} cases...")

    print("7. Writing final predictions to output.csv at repository root...")
    output_path = os.path.join(repo_root, "output.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for res in sorted(results, key=lambda x: x.case_id):
            steps_json_str = json.dumps([s.to_dict() for s in res.steps], separators=(",", ":"))
            writer.writerow([res.case_id, res.deletion_status, steps_json_str])

    print(f"   Successfully wrote {len(results)} rows to {output_path}.")

    print("8. Validating output.csv with strict schema validator...")
    validate_output_file(output_path, expected_rows=518)
    print("   Output validation PASSED: Schema, enums, step ordering, and invariants verified.")

    elapsed = time.time() - start_time
    print("\n==================================================================")
    print("AUDIT SUMMARY:")
    print(f"   Total requests evaluated : {len(results)}")
    print(f"   COMPLETE cases          : {status_counts['COMPLETE']}")
    print(f"   INCOMPLETE cases        : {status_counts['INCOMPLETE']}")
    print(f"   NOT_APPLICABLE cases    : {status_counts['NOT_APPLICABLE']}")
    print(f"   Total steps emitted     : {total_steps} (avg {total_steps / len(results):.1f}/case)")
    print(f"   Total execution time    : {elapsed:.2f} seconds")
    print("==================================================================")


if __name__ == "__main__":
    main()
