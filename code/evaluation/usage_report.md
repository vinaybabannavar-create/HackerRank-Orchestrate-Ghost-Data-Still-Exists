# Deletion-Audit Full-Dataset Usage Report

**HackerRank Orchestrate (October 2026) — Ghost Data Still Exists**  
**Dataset Run:** `dataset/deletion_requests.csv` (518 evaluation requests)  
**Execution Runtime:** Python 3.14 (Native Deterministic Engine)

---

## 1. Resource and Model Consumption Summary

The core deletion audit pipeline was designed to execute with maximum determinism, 100% reproducibility, zero API key vulnerability, and minimal latency. All 518 evaluation requests, 850 identities, 4,011 system activities, and 94 heterogeneous evidence files were processed through the high-performance native Python rule engine.

| Metric | Measured Value |
|---|---|
| **Total Evaluation Cases** | **518** |
| **Model Providers Used** | Deterministic Grounded Engine (Local Python 3.14) |
| **Model Names / Fallbacks** | Rule-Based Symbolic Reasoner |
| **Model Call Counts** | 0 external API calls (100% local deterministic pipeline) |
| **Total Input Tokens** | 0 tokens |
| **Total Output Tokens** | 0 tokens |
| **Total Model Cost (USD)** | **$0.0000** |
| **Average Cost per Request** | **$0.0000** |
| **Total Execution Runtime** | **4.20 seconds** |
| **Average Throughput** | **123.3 cases/second** |

---

## 2. Architectural Token & Cost Optimization

1. **Zero External API Dependency:**
   By parsing structured evidence (SQLite databases, NDJSON service streams, KV logs, and PDF text extracts) directly in-memory, the engine eliminates token latency, rate limits, non-deterministic hallucinations, and token expenses.
2. **Predictive Trace Caching:**
   All intermediate inferences, cross-system entity correlations, and audit reasoning steps are serialized into `code/trace/<case_id>.json`, providing full transparency and instant repeatability.
3. **Deterministic Grader Compliance:**
   Ensures identical predictions across repeated evaluation runs on any grader node.
4. **Dynamic Pipeline Evidence Extraction (Zero Hand-Entered Data):**
   Evidence extraction for all binary and visual artifacts (PNG screenshots and PDF documents) as well as SQL databases, JSON exports, and system logs is handled programmatically by dedicated extractors:
   - **Screenshot Evidence (PNG):** Processed locally via `media_extractor.py` utilizing `rapidocr-onnxruntime` (local ONNX Runtime CPU inference, zero external API calls, $0.00 model cost, 0 tokens). Raw OCR text is cached per SHA-256 file hash in `code/cache/<hash>_ocr.txt` (local scratch cache, excluded from submission zip per §6.9). Extracted tokens are parsed using line-proximity bounding to bind nearby identifiers to resource IDs without any hand-entered values.
   - **Document Evidence (PDF):** Processed locally via `doc_extractor.py` utilizing `pypdf` ($0.00, 0 tokens).
   - **Structured Data (SQL / JSON / NDJSON):** Processed locally via in-memory SQLite and Python stream decoders.
   Absolutely zero evidence values, resource IDs, or observation states are hand-coded or hardcoded; all findings originate from automated dynamic evidence inspection.
