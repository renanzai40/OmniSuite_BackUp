# Omni Suite Service Level Agreement (SLA)

> **Status**: baseline. Numbers below are derived from existing
> `tests/benchmarks/test_*_throughput.py` assertions. A future revision will
> replace these with P50/P95/P99 numbers from a real-world load study
> (requires Phase 3.2 real LLM integration; blocked on API keys).

## 1. Scope

This SLA covers the three Omni Suite modules:

| Module | Distribution | CLI | MCP server |
|--------|--------------|-----|------------|
| **OPP** (Omni Pre-Processor) | `omni-pre-processor` | `opp` | `python -m opp.mcp.server` |
| **OL** (Omni Localizer) | `omni-localizer` | `ol` | `python -m ol_mcp` |
| **ORF** (Omni Re-Formatter) | `omni-re-formatter` | `orf` | `python -m orf.mcp.server` |

## 2. Latency targets

All targets are measured with `OMNI_TEST_FAKE_LLM=1` and `OMNI_TEST_FAKE_PANDOC=1`
on a Linux x86_64 host with Python 3.13. Real LLM/Pandoc paths will be
significantly slower and are excluded from this SLA until Phase 3.2 is complete.

### 2.1 OPP — document extraction

| Document | Size | Target | Test |
|----------|------|--------|------|
| DOCX | 50 paragraphs + 1 table | < 30s (P100 in current run) | `tests/benchmarks/test_extraction_throughput.py::TestDOCXExtractionThroughput::test_docx_50_paragraphs` |
| DOCX | 200 paragraphs + 1 table | < 60s (P100 in current run) | `test_docx_200_paragraphs` |
| DOCX | 50 paragraphs × 3 consecutive runs | avg < 30s | `test_docx_consecutive_runs` |

### 2.2 OL — markdown translation (FAKE_LLM)

| Input | Size | Target | Test |
|-------|------|--------|------|
| Markdown | small (≤ 5KB) | < 30s (test budget) | `tests/benchmarks/test_translation_throughput.py::TestMDTranslationThroughput::test_translate_small_md` |
| Markdown | large (≥ 50KB) | < 90s (test budget) | `test_translate_large_md` |
| Markdown | small × 3 consecutive runs | avg < 30s | `test_translate_consecutive_runs` |

**Note**: real LLM latency is dominated by network round-trips to the LLM
provider; FAKE_LLM runs finish in milliseconds. Real-world OL latency is
governed by the OL model pool's provider tier (`config/default.yaml`:
`ARK_API_KEY` / `ZHIPU_API_KEY` / `NVIDIA_NIM_API_KEY`), prompt size, and
rate limits. A separate SLA for real LLM is deferred to Phase 3.2.

### 2.3 ORF — MD backfill (FAKE_PANDOC)

| Input | Output | Target | Test |
|-------|--------|--------|------|
| Markdown | DOCX (via pandoc) | < 30s | `tests/benchmarks/test_backfill_throughput.py::TestMDBackfillThroughput::test_md_to_docx` |
| Markdown | HTML (pure Python) | < 30s | `test_md_to_html` |
| Markdown | DOCX × 3 consecutive runs | avg < 30s | `test_md_backfill_consecutive_runs` |

## 3. Throughput targets

| Metric | Target | Notes |
|--------|--------|-------|
| Full MD matrix (165 cells) | < 5 min on Linux x86_64 | Measured: 72.7s for 12 PASS + 145 SKIP + 8 FAIL (pre-whitelist-fix); ~165s for 20 PASS + 145 SKIP + 0 FAIL (post-whitelist-fix). Run via `make matrix`. |
| Full MD matrix (single input format, e.g. `docx`) | < 3 min | 15 cells. Run via `make matrix-subset FMT=docx`. |
| CLI cold start | < 1s | Each CLI imports heavy deps (pymupdf, python-docx, pypandoc); cold-start budget is dominated by Python startup. |

## 4. Availability

| Metric | Target |
|--------|--------|
| CLI exit code 0 on success | 100% (caller can rely on POSIX exit code) |
| MCP server startup | < 2s (stdio transport) |
| MCP server response | < 5s for `list_tools` / `initialize` |
| MCP tool call | covered by per-tool latency in §2 |

## 5. Memory budgets

| Process | Peak RSS budget | Notes |
|---------|----------------|-------|
| OPP CLI on 50-paragraph DOCX | < 200 MB | python-docx + lxml + pymupdf |
| OPP CLI on 200-paragraph DOCX | < 400 MB | Scales linearly with paragraph count |
| OL CLI on 50KB markdown | < 500 MB | FAKE_LLM has no token memory; real LLM adds context window |
| ORF CLI on MD→DOCX | < 300 MB | pandoc subprocess + pypandoc-binary |

## 6. Determinism

| Test | Status |
|------|--------|
| `tests/observability/test_metrics_wiring.py` | ✅ All 6 modules emit identical metrics on repeated runs |
| `tests/benchmarks/test_*_throughput.py` | Timing varies; assertions are P100 budgets, not P50 |
| Tier 7 byte-identical verification (165 cells) | ✅ 131/131 byte-identical on CLI path |

## 7. How to measure

### Reproduce this SLA

```bash
# Install all 3 modules in a clean venv
bash scripts/setup_dev.sh

# Run all throughput benchmarks (uses FAKE_LLM + FAKE_PANDOC)
make test-opp   # or make test-ol / make test-orf

# Run the full MCP matrix via real MCP transport
make matrix
```

### Add a new SLA assertion

1. Add a test in `tests/benchmarks/test_<module>_throughput.py` using
   `time.perf_counter()` to measure the operation.
2. Add a row to §2 with the target and a link to the test.
3. Run the test 30+ times locally to establish a P50/P95/P99 baseline.
4. Update the target to a conservative P95.

## 8. Out of scope

- **Real LLM latency** — depends on provider tier, network, prompt size.
  Deferred to Phase 3.2.
- **Real Pandoc latency** — depends on document size and pandoc options.
  Deferred to Phase 3.3.
- **Cross-platform latency** — Linux x86_64 only. macOS/Windows baselines
  require CI runners; deferred to Phase 2.4.
- **Distributed throughput** — the suite is single-process. Multi-process
  parallelism is application-level (e.g., `xargs -P`).
- **Network-attached files** — local filesystem only. NFS/S3 latency
  excluded.

## 9. Revision history

- **v0.1 (2026-06-22)**: Initial SLA derived from existing test assertions.
  Real P50/P95/P99 numbers deferred to Phase 3.2 (real LLM) and Phase 3.3
  (real Pandoc).
