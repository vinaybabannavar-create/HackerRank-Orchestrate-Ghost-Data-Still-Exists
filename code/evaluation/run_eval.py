from __future__ import annotations

import csv
import json
import os
import sys

# Ensure code is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
code_dir = os.path.dirname(current_dir)
parent_dir = os.path.dirname(code_dir)
cwd = os.getcwd()

for p in [code_dir, parent_dir, cwd]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

def find_dataset_dir() -> str:
    for c in [cwd, parent_dir, code_dir]:
        ds = os.path.join(c, "dataset")
        if os.path.isdir(ds) and os.path.exists(os.path.join(ds, "sample_deletion_requests.csv")):
            return ds
    return "dataset"

from agent.engine import BatchResolver, DeletionAuditEngine
from agent.evidence.registry_scanner import EvidenceScanner
from agent.identity import IdentityResolver
from agent.loaders import DatasetLoaders
from agent.timeline import TimelineReconstructor


def run_evaluation(
    dataset_dir: str | None = None,
    requests_filename: str = "sample_deletion_requests.csv",
    golden_filename: str = "sample_output.csv",
    verbose: bool = True,
):
    if dataset_dir is None:
        dataset_dir = find_dataset_dir()
    loaders = DatasetLoaders(dataset_dir)
    idents = loaders.load_user_identities()
    audit_log = loaders.load_user_audit_log()
    acts = loaders.load_system_activity()
    registry = loaders.load_evidence_manifest()

    resolver = IdentityResolver(idents, audit_log)
    timeline_rec = TimelineReconstructor(acts)
    scanner = EvidenceScanner(registry)
    batch_resolver = BatchResolver(registry, acts, resolver, scanner)

    requests = loaders.load_deletion_requests(requests_filename)
    try:
        full_requests = loaders.load_deletion_requests("deletion_requests.csv")
    except Exception:
        full_requests = []
    
    all_reqs_map = {r.case_id: r for r in full_requests}
    for r in requests:
        all_reqs_map[r.case_id] = r
    batch_resolver.resolve_batches(list(all_reqs_map.values()))

    engine = DeletionAuditEngine(resolver, scanner, timeline_rec, registry, acts, batch_resolver)

    # Load golden
    golden_path = os.path.join(dataset_dir, golden_filename)
    golden_data = {}
    with open(golden_path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            golden_data[r["case_id"]] = {
                "deletion_status": r["deletion_status"].strip(),
                "steps": json.loads(r["steps_json"]),
            }

    # Evaluate
    total_cases = len(requests)
    status_matches = 0
    confusion_matrix = {"COMPLETE": {}, "INCOMPLETE": {}, "NOT_APPLICABLE": {}}
    for k in confusion_matrix:
        confusion_matrix[k] = {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0}

    total_golden_steps = 0
    total_pred_steps = 0
    exact_step_matches = 0

    field_correct = {
        "step_no": 0,
        "phase": 0,
        "system_id": 0,
        "resource_id": 0,
        "operation": 0,
        "state": 0,
        "evidence_id": 0,
    }
    field_total = 0

    sequence_matches = 0
    failing_cases = []

    for req in requests:
        res = engine.audit_case(req)
        golden = golden_data.get(req.case_id)
        if not golden:
            continue

        pred_status = res.deletion_status
        gold_status = golden["deletion_status"]
        confusion_matrix[gold_status][pred_status] += 1

        is_status_correct = (pred_status == gold_status)
        if is_status_correct:
            status_matches += 1

        pred_steps = [s.to_dict() for s in res.steps]
        gold_steps = golden["steps"]

        total_golden_steps += len(gold_steps)
        total_pred_steps += len(pred_steps)

        # Check sequence match
        is_seq_match = True
        min_len = min(len(pred_steps), len(gold_steps))
        for i in range(min_len):
            field_total += 1
            ps = pred_steps[i]
            gs = gold_steps[i]
            step_exact = True
            for fld in field_correct:
                if ps.get(fld) == gs.get(fld):
                    field_correct[fld] += 1
                else:
                    step_exact = False
            if step_exact:
                exact_step_matches += 1
            else:
                is_seq_match = False

        if len(pred_steps) != len(gold_steps):
            is_seq_match = False

        if is_seq_match and is_status_correct:
            sequence_matches += 1
        else:
            failing_cases.append({
                "case_id": req.case_id,
                "email": req.email,
                "pred_status": pred_status,
                "gold_status": gold_status,
                "pred_steps": pred_steps,
                "gold_steps": gold_steps,
            })

    status_acc = status_matches / total_cases if total_cases > 0 else 0
    step_exact_acc = exact_step_matches / max(total_golden_steps, 1)
    seq_acc = sequence_matches / total_cases if total_cases > 0 else 0

    print("=" * 60)
    print(f"EVALUATION RESULTS ({requests_filename})")
    print("=" * 60)
    print(f"Total Cases: {total_cases}")
    print(f"Status Accuracy: {status_matches}/{total_cases} ({status_acc:.2%})")
    print(f"Sequence Accuracy: {sequence_matches}/{total_cases} ({seq_acc:.2%})")
    print(f"Step Exact Matches: {exact_step_matches}/{total_golden_steps} ({step_exact_acc:.2%})")
    print("Confusion Matrix (Gold -> Pred):")
    for g_stat, preds in confusion_matrix.items():
        print(f"  Gold {g_stat:15s} -> {preds}")
    print("Per-Field Accuracy:")
    for fld, corr in field_correct.items():
        acc = corr / max(field_total, 1)
        print(f"  {fld:15s}: {corr}/{field_total} ({acc:.2%})")

    if failing_cases:
        print("=" * 60)
        print(f"FAILING CASES ({len(failing_cases)} total):")
        for fcase in failing_cases[:5]:
            print(f"\n--- [{fcase['case_id']}] {fcase['email']} ---")
            print(f"Status: Pred={fcase['pred_status']} vs Gold={fcase['gold_status']}")
            print(f"Pred Steps ({len(fcase['pred_steps'])}):")
            for ps in fcase['pred_steps']:
                print(f"   [{ps['phase']}] {ps['operation']} sys={ps['system_id']} res={ps['resource_id']} st={ps['state']} ev={ps['evidence_id']}")
            print(f"Gold Steps ({len(fcase['gold_steps'])}):")
            for gs in fcase['gold_steps']:
                print(f"   [{gs['phase']}] {gs['operation']} sys={gs['system_id']} res={gs['resource_id']} st={gs['state']} ev={gs['evidence_id']}")
    else:
        print("\nALL CASES PASSED PERFECTLY (100% MATCH)!")

    return {
        "status_accuracy": status_acc,
        "step_accuracy": step_exact_acc,
        "sequence_accuracy": seq_acc,
        "failing_cases": failing_cases,
    }


if __name__ == "__main__":
    run_evaluation()
