# AGENTS.md — Omni Suite

This file guides AI agents (Claude, Cursor, OpenCode, etc.) on how to work with the Omni Suite. It is an **index + invariants** file: detail lives in on-demand docs (linked below), not here. If you need tool signatures, MCP configs, or testing procedures, follow the links.

## What is this?

A 3-stage document localization pipeline: **OPP** (extract) → **OL** (translate) → **ORF** (backfill). Each module is a standalone sub-repo with its own CLI, MCP server, and test suite.

## Current Versions

| Component | Version | Status |
|---|---|---|
| Omni_Suite | v0.4.0 | Suite-level orchestration + E2E tests |
| OPP | v0.9.1 | 13+ input formats, MCP with path security |
| OL | v0.7.1 | 21 MCP tools, 4-layer repair pipeline, StyleGuide injection, --polish pass, 8 quality gates |
| ORF | v0.4.17 | 16 backfill formats, Foreman/Specialist |

v0.9.1 · v0.7.1 · v0.4.17 · v0.4.0. Changelog: `CHANGELOG.md`; compatibility matrix: `COMPATIBILITY.md`.

> **Prerequisite:** Python >= 3.13. Verify with `python3 --version`.

## Quick Start

```bash
# Install (one command)
bash scripts/setup_dev.sh

# Verify without installing
bash scripts/setup_dev.sh --check-only

# Check version
omni-suite --version
```

## Per-Module Cheat Sheet

| Module | Role | CLI (key subcommand) | MCP tools | Source |
|--------|------|---------------------|-----------|--------|
| **OPP** | Extract documents → MD + XLIFF + skeleton | `opp <file> --target-format both --output-dir <dir>` | 9 tools (`extract_document`, `batch_extract`…) | `Omni_Pre_Processor/src/` |
| **OL** | Translate MD/XLIFF between languages | `ol translate-md <file> -s <src> -t <tgt> -o <dir>` | 21 tools (`translate_md_text`, `judge_text`…) | `Omni_Localizer/src/` |
| **ORF** | Backfill translated content → target format | `orf apply-md <file> --target-format <fmt> -o <out>` | 7 tools (`apply_md`, `apply_xliff`…) | `Omni_Re_Formatter/src/` |
| **Validation** | Agent-agnostic validation — scenario library + standards + director loop | `python scripts/validation/run_validation.py --list` | 2 tools (`list_validation_scenarios`, `run_validation_scenario`) | `scripts/validation/` + `omni_mcp/validation/` |

Full MCP server/tool inventory and namespacing (all 37 tools): [`docs/agent-pipeline-guide.md`](docs/agent-pipeline-guide.md) — full per-tool parameter signatures live in each module's `docs/API.md` (e.g. [`Omni_Pre_Processor/docs/API.md`](Omni_Pre_Processor/docs/API.md)). Per-module internals: each sub-repo's own `AGENTS.md`.

## Common Tasks

### Translate a DOCX end-to-end

```bash
# CLI smoke/contract runs only: FAKE_LLM gives deterministic, zero-cost output
# (plumbing / schema / exit-code checks). Do NOT use it as human-quality
# validation evidence — see "Critical Notes" #1.
export OMNI_TEST_FAKE_LLM=1

# 1. Extract
opp document.docx --target-format both --source-lang en --target-lang zh --output-dir /tmp/opp

# 2. Translate
ol translate-md /tmp/opp/document.md -s en -t zh -o /tmp/ol

# 3. Backfill
orf apply-md /tmp/ol/document.md --target-format docx -o result.docx
```

### Run the suite pipeline in one shot (N1 enhancement, 2026-09-04)

`omni-suite pipeline <file>` chains the 3 steps above behind a single CLI.
Three flags (see `omni-suite pipeline --help`):

```bash
omni-suite pipeline document.docx --dry-run            # print the OPP→OL→ORF commands without executing (no LLM keys)
omni-suite pipeline document.docx --gates-only         # OPP + OL (8 quality gates) + `ol extract-warnings`; skip ORF backfill
omni-suite pipeline document.docx --keep-intermediate  # keep /tmp/omni-suite-pipeline/<stem>/ after the run
```

### Run validation

The agent-agnostic validation framework runs real scenarios against the shipped surface (no mocks, no FAKE_LLM as evidence — a fallback-active human-quality run is `invalid`, see [`scenarios/STANDARDS.md#fallbacks-never-evidence`](scenarios/STANDARDS.md#fallbacks-never-evidence)). Tier-1 scenarios are hermetic — no LLM keys needed.

```bash
source .venv_ol/bin/activate

# Enumerate the library — no execution, no LLM
python scripts/validation/run_validation.py --list

# Run one hermetic scenario (tier 1 = no LLM keys needed; --scenario is a
# case-insensitive substring match on the file stem: tool-, opp, orf-md,
# orf-xliff, pipeline, regression)
python scripts/validation/run_validation.py --scenario regression --tier 1

# Contract-lint the library itself (falsifiable expects, STANDARDS.md anchors)
python scripts/validation/run_validation.py --check

# Coverage audit — every live MCP tool must be exercised by a scenario
python scripts/validation/coverage_audit.py

# Read the newest run and generate the director report (two verdict families)
cat validation-runs/latest.txt
python scripts/validation/validation_report.py validation-runs/<ts>/scenarios.json

# Per-repo scenario libraries (OPP#58): --repo opp|ol|orf|suite|all
MCP_ALLOWED_DIRECTORIES=/tmp python scripts/validation/run_validation.py --repo orf --tier 1

# Run everything, then build the report card + delivery package
python scripts/validation/run_validation.py --repo all --dry-run            # plan only
python scripts/validation/run_validation.py --repo orf --tier 1 --matrix --deliver
#   --matrix  -> report.md + report.json (with report_card per-repo matrix) in the run dir
#   --deliver -> zip at 04-Output/artifacts/deliverables/omni-suite/ (01-RAW/ real
#                artifacts, 02-PROCESSED/ reports, manifest.json)

# Artifact-assertion matrix (e2e-test-suite#44): deterministic P0/P1 assertions
# on the ACTUAL PRODUCED FILES. --artifacts implies --matrix; P0/P1 failures -> exit 1.
# Full reference: docs/dev/artifact-assertion-matrix.md
MCP_ALLOWED_DIRECTORIES=/tmp python scripts/validation/run_validation.py --repo orf --tier 1 \
  --matrix --artifacts /tmp/omni_val/orf-backfill-html --module orf
#   -> artifact-report.json in the run dir, prints "ARTIFACT MATRIX: <path>"
python scripts/validation/artifact_matrix.py /tmp/omni_val/orf-backfill-html \
  --module orf --out /tmp/omni_val/artifact-report.json   # standalone (dir or delivery .zip)

# Four-class diffs (new/regressed/fixed/existing-failing); exit 1 when regressed>0
python scripts/validation/artifact_diff.py <base-artifact-report.json> <head-artifact-report.json>
python scripts/validation/validation_diff.py <newer> --against-version 0.4.0
python scripts/validation/validation_diff.py <newer> --base-sha <sha-prefix>
python scripts/validation/coverage_audit.py --out validation-runs/<ts>/coverage.json
```

Every run persists `run_meta` (suite/opp/ol/orf versions + git SHAs). Full reference: [docs/dev/per-repo-validation-delivery.md](docs/dev/per-repo-validation-delivery.md). Artifact assertions (P0/P1 groups, report JSON shape, exit-code contract): [docs/dev/artifact-assertion-matrix.md](docs/dev/artifact-assertion-matrix.md).

Tier semantics: 1 = hermetic (no keys), 2 = real LLM keys, 3 = paid/external/network. A tier-2/3 scenario without its keys reports `unconfigured` — never a fake green. The citable bar is `scenarios/STANDARDS.md` (two families: AGENT-SURFACE + HUMAN-QUALITY); the human director loop is `docs/dev/validation-director-loop.md`.

#### Validation 循环治理规范（2026-08-15）

跨项目通用规范见全局 skill `validation-framework-execution` → `references/validation-run-governance.md`。

**开始前必读**：STANDARDS.md（判定基准）、坑清单（`docs/` 下 LOOP-LOG，如无则本循环创建）、上次 run（`validation-runs/latest.txt`）。

**结束后必形成**：run 记录（`validation-runs/<ts>/`）、坑清单更新（新坑当天追加）、issue + PR（代码层 bug）、validation 报告、交付包（→ `04-Output/artifacts/deliverables/omni-suite/`）。
每轮 validation 无论是否有新失败，都要在 LOOP-LOG 循环事件记一行结果（日期 + 范围 + 结果 + 结论），保持基线连续（关闭 issue #2）；
验证证据中的 lint/测试声称必须可复现：附工具版本（如 ruff --version）+ 完整命令（含 select/文件范围）+ 原始输出（error 规则码 + 行号），"pre-existing N errors" 须列具体规则码与行号并确认位于未触碰行（关闭 issue #1）。

**失败定性**：任何 failed 先单独复现定性（LLM 波动 / 场景断言漂移 / 代码 bug / 数据漂移 / 环境），不直接报"回归"。**LLM 门禁**：tier-2 全量跑前短探测；波动时段结果不作回归依据。**归档**：run 记录 → repo `validation-runs/`；交付包 → `04-Output/artifacts/deliverables/omni-suite/`；中间件/log → `99-Tools/validation-scratch/omni-suite/`（不是 /tmp）。**验收**：打开产物审查（非空/相关性/无 VAGUE），不是数字。

## MCP Servers

Each module exposes its own MCP server. Server/tool inventory, response envelope, namespacing, and client config notes: [`docs/agent-pipeline-guide.md`](docs/agent-pipeline-guide.md). Full per-tool parameter signatures: each module's `docs/API.md`.

### OPP MCP Server (9 tools)
### OL MCP Server (21 tools)
### ORF MCP Server (7 tools)

> **Note**: Server names are not uniform — OPP/ORF use `-server` suffix (`opp-mcp-server`, `orf-mcp-server`), OL omits it (`ol-mcp`). Historical inconsistency; all three follow the same protocol.

## Format Support Matrix

ORF `apply-md` supports 16 output formats: DOCX, ODT, EPUB, HTML, RTF, PDF, PPTX, ICML, SRT, CSV, XLSX, XML, IPYNB, EML, MSG, JSON.

See `README.md` → "Cross-Format Production-Readiness" for the full 36-path verified matrix.

## Critical Notes

1. **FAKE_LLM — two distinct uses** — `OMNI_TEST_FAKE_LLM=1` is a deterministic fallback seam. **(i) CLI smoke/contract runs: allowed** (plumbing, schema/exit-code checks, zero-cost dry runs). **(ii) Validation runs: forbidden for human-quality evidence** — in a human-quality scenario (`pipeline-*` prefix or any step citing a HUMAN-QUALITY anchor) a fallback-active run reports `invalid`, never `passed`; fallbacks are never quality evidence. `--allow-fake` is the contract-only escape hatch (all-AGENT-SURFACE scenarios only). Citable bar: [`scenarios/STANDARDS.md#fallbacks-never-evidence`](scenarios/STANDARDS.md#fallbacks-never-evidence).
2. **pandoc dependency** — DOCX, ODT, EPUB, RTF, ICML outputs require pandoc (auto-installed via `pypandoc-binary`).
3. **MSG → use .eml** — MSG output requires commercial Aspose.Email. Use `.eml` instead (open standard, fully supported).
4. **Cross-format XLIFF** — Converting DOCX XLIFF → PPTX needs `orf apply-xliff --force`.
5. **PDF XLIFF blocked** — OPP intentionally blocks PDF → XLIFF generation (unsupported).
6. **Docs are gate-enforced** — `python3 scripts/doc_inventory.py --check` verifies doc truth (tool counts, scenario counts, canonical numbers, archive markers, link/path integrity, skill line-claims). Regenerate with `python3 scripts/doc_inventory.py` after any `docs/` change; wired into pre-commit. Full reference: `.opencode/skills/omni-docmap/SKILL.md`.

## Agent Tips

- **FAKE_LLM scope**: use `OMNI_TEST_FAKE_LLM=1` for CLI smoke/contract runs only — it is forbidden as human-quality validation evidence and forces an `invalid` verdict (see Critical Notes #1; [`scenarios/STANDARDS.md#fallbacks-never-evidence`](scenarios/STANDARDS.md#fallbacks-never-evidence)).
- **Glossary**: see [CONTEXT.md](CONTEXT.md) — shared pipeline terminology (Ubiquitous Language).
- `omni_suite/cli.py` is print-only — use per-module CLIs for real work.
- Per-sub-repo `AGENTS.md` files (in each sub-repo root) cover dev/agent context: architecture, CLI, MCP tools, env vars, test patterns, known gotchas.
- **OL E2E-65 (prompt injection strip)**: `translate_md_text` output is post-processed to strip `CRITICAL/IMPORTANT/NOTE: Output ONLY...` echoes. Don't strip these patterns yourself; OL handles it.
- **OL quality gates**: configurable via `quality_gates:` in OL config. Tune with `OL_LENGTH_RATIO_MIN` / `OL_LENGTH_RATIO_MAX`; `OL_TARGET_LOCALE` enforces locale checks.
- **OPP E2E-15 (orphan image filter)**: `extract_document --target-format both` won't double-embed images already output inline; `images.json` reflects this.
- **ORF E2E-07 (fuzzy match)**: `apply_xliff` to DOCX tolerates small text mismatches (5-char length diff, 0.85 ratio). Retry previously-`SKIPPED` units.
- **`opp -v` writes to stderr** (as of v0.6.2). Use `--detect-format -v file.docx` to see the detected format.

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml` at the project root. Install: `pip install pre-commit && pre-commit install`. Run all: `pre-commit run --all-files` (or `make lint`). Hooks: gitleaks, check-added-large-files, check-merge-conflict, detect-private-key, end-of-file-fixer, trailing-whitespace, omni-doc-inventory (doc-truth gate, runs on commit), omni-contract-smoke (manual stage — run explicitly via `make smoke`).

## Where Things Live (Doc Map)

| Need | Go to |
|------|-------|
| Pipeline selection (MD vs XLIFF path) | `README.md` → Pipeline Selection Strategy |
| MCP server/tool inventory + namespacing / local testing | `docs/agent-pipeline-guide.md` |
| Architecture / data flow | `docs/ARCHITECTURE.md` |
| OPP→OL→ORF handoff contract | `CONTRACT.md` |
| Shared glossary | `CONTEXT.md` |
| Decision records (ADR 0001–0006) | `docs/DECISIONS.md` |
| Setup (real LLM keys) | `SETUP.md` |
| Test instructions | `TESTS.md` |
| Retired docs (archive) | `docs/archive/` |
| Full change-impact map | `.opencode/skills/omni-docmap/SKILL.md` |

## How to validate (any agent)

Generic instructions — applies to Hermes, Claude, Cursor, Codex, opencode, or any agent. Every scenario dispatches through the REAL shipped surface (no mocks, no FAKE_LLM as evidence — `OMNI_TEST_FAKE_LLM=1` is allowed only for CLI smoke/contract runs, never for validation evidence; a fallback-active human-quality run is `invalid` per [`scenarios/STANDARDS.md#fallbacks-never-evidence`](scenarios/STANDARDS.md#fallbacks-never-evidence)); tier-1 scenarios are hermetic and need no LLM keys.

```bash
source .venv_ol/bin/activate

# 1. See what exists (no execution, no LLM)
python scripts/validation/run_validation.py --list

# 2. Run one hermetic scenario (tier 1 = no LLM keys needed)
python scripts/validation/run_validation.py --scenario <name> --tier 1

# 3. Lint the library itself (falsifiable expects, standard anchors)
python scripts/validation/run_validation.py --check

# 4. Coverage audit — every live MCP tool must be exercised by a scenario
python scripts/validation/coverage_audit.py
python scripts/validation/coverage_audit.py --out validation-runs/<ts>/coverage.json

# 5. Diff two runs (verdict changes + regression detection)
python scripts/validation/validation_diff.py <runs-dir>/<ts1> <runs-dir>/<ts2>
python scripts/validation/validation_diff.py <newer> --against-version 0.4.0
python scripts/validation/validation_diff.py <newer> --base-sha <sha-prefix>
```

**Reading results**: `validation-runs/latest.txt` → newest run (`validation-runs/<ts>/scenarios.json`); `python scripts/validation/validation_report.py validation-runs/<ts>/scenarios.json` → `report.md` + `report.json` in the run dir. `report.md` renders TWO verdict families side by side — judge both:

| Family | What it proves |
|---|---|
| **agent-user conformance** | every agent-facing tool/CLI works as an agent would use it (tool-* scenarios + AGENT-SURFACE anchors: `#tool-contract`, `#json-parseable`, `#error-clarity`, `#path-security`, `#exit-codes`) |
| **human-quality conformance** | pipeline output satisfies human end-users (pipeline-* scenarios + HUMAN-QUALITY anchors: `#lqa-threshold`, `#para-ratio`, `#cjk-density`, `#punct-hygiene`, `#drawing-count`, `#opens-docx`) |

`unconfigured` (missing env, e.g. no LLM keys) is a distinct status — never a pass, never a silent skip. **Standards**: `scenarios/STANDARDS.md` is the single citable bar — every step's `expect` cites `standard: STANDARDS.md#<anchor>`. Read it before judging a verdict; never invent thresholds. **Director checklist**: `docs/dev/validation-director-loop.md` (two-role model, 10-minute per-run loop).
