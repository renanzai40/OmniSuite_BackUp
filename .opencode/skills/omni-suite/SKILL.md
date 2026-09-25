---
name: omni-suite
description: Orchestrate the 3-stage Omni Suite document localization pipeline (OPP extract → OL translate → ORF backfill). Current versions: opp 0.9.1, ol 0.7.1, orf 0.4.17, suite 0.4.0.
---

# Omni Suite — Document Localization Pipeline

A 3-stage pipeline for translating documents between formats and languages.

## 30-second bootstrap (run first)

```bash
make doctor          # 7-check health (Python ≥3.13, keys, pandoc, WeasyPrint, md2pptx, MCP, sub-repos)
make smoke           # Pipeline contract smoke test (pre-commit gate)
make test-quick      # pytest tests/ -m "not nightly" -q
```

If `make doctor` fails, the pipeline won't work. Fix those issues first.

## Current versions (2026-09-05)

| Component | Version | Path | CLI Framework |
|---|---|---|---|
| OPP | **0.9.1** | `Omni_Pre_Processor/` | argparse |
| OL | **0.7.1** | `Omni_Localizer/` | typer |
| ORF | **0.4.17** | `Omni_Re_Formatter/` | click |
| Suite | **0.4.0** | `./` | — |

Test matrix status: **131 PASS, 64 SKIP, 0 FAIL** across 195 cells (verified 2026-09-05).
False-positive rate: **0/200** (was 48/200 before the 2026-06-29 quality_checks.py fix).

> **CLI framework note**: Flag names are uniform (`--kebab-case`), but help-text styles differ. See `../docs/DECISIONS.md` ADR 0001.

## When to use this skill

- User asks to translate a document (DOCX, PPTX, PDF, etc.) between languages
- User asks to convert a document between formats (e.g., DOCX → EPUB)
- User asks to batch-translate or batch-convert multiple files
- User asks to detect a file's format (use `opp -v` to see the result in stderr)

## The 3 stages

### 1. Extract (OPP)

```bash
opp <file> --target-format both --source-lang en --target-lang zh --output-dir /tmp/opp
```

Add `-v` to see progress + detected format in stderr (e.g. `[INFO] Detected: docx (confidence: 1.0)`).
Output (for `both`): `*.md` + `*.xlf` + `skeleton.zip` + `manifest.json`.

### 2. Translate (OL)

```bash
OMNI_TEST_FAKE_LLM=1 ol translate-md /tmp/opp/file.md -s en -t zh -o /tmp/ol
```

`OMNI_TEST_FAKE_LLM=1` is **required** unless you have real LLM API keys.
The E2E-65 prompt-injection strip is auto-applied to LLM output (don't strip `CRITICAL/IMPORTANT/NOTE: Output ONLY...` yourself — OL handles it).

### 3. Backfill (ORF)

```bash
orf apply-md /tmp/ol/file.md --target-format <format> -o result.<format>
```

The E2E-07 fuzzy paragraph match handles XLIFF source ↔ DOCX paragraph mismatches (up to 5-char length diff, ratio ≥ 0.85).

### Alternative: XLIFF path (layout-preserving)

When you need the output to look exactly like the source:

```bash
opp <file> --target-format xlf --source-lang en --target-lang zh --output-dir /tmp/opp
OMNI_TEST_FAKE_LLM=1 ol translate-xliff /tmp/opp/file.xlf -s en -t zh -o /tmp/ol
orf apply-xliff <original.docx> --xliff /tmp/ol/file.xlf --output result.docx
```

Requires `skeleton.zip` (only produced for DOCX/PPTX/EPUB inputs).

### Choosing a pipeline path

| If you need... | Use... | Why |
|---|---|---|
| Fast text output, any of 16 formats | MD path | `apply-md` supports DOCX/ODT/EPUB/HTML/RTF/PDF/PPTX/ICML/SRT/CSV/XLSX/XML/IPYNB/EML/MSG/JSON |
| Exact original layout (fonts, styles, floating images) | XLIFF path | `apply-xliff` reuses skeleton.zip |
| Both options (recommended default) | Extract with `both` | Produces MD + XLIFF + skeleton in one pass |

### Suite pipeline one-shot (`omni-suite pipeline`)

`omni-suite pipeline <file>` chains the 3 stages above behind a single CLI
(`<file> [--source-lang en] [--target-lang zh] [--target-format docx]
[--output <path>]`). Three flags (see `omni-suite pipeline --help`):

```bash
omni-suite pipeline document.docx --dry-run            # print the OPP→OL→ORF commands without executing (no LLM keys)
omni-suite pipeline document.docx --gates-only         # OPP + OL (8 quality gates) + `ol extract-warnings`; skip ORF backfill
omni-suite pipeline document.docx --keep-intermediate  # keep /tmp/omni-suite-pipeline/<stem>/ after the run
```

`--dry-run` and `--gates-only` need no LLM keys at the CLI level
(`--fake-llm`/FAKE_LLM seam applies to the translated output); a full run
still requires real LLM keys or `OMNI_TEST_FAKE_LLM=1` unless the pipeline
is invoked with `--fake-llm`.

## Output formats (16, ORF `apply-md`)

DOCX, ODT, EPUB, HTML, RTF, PDF, PPTX, ICML, SRT, CSV, XLSX, XML, IPYNB, EML, MSG, JSON.

| Format group | Engine | Dependency |
|---|---|---|
| DOCX/ODT/EPUB/RTF/ICML | pandoc | auto-installed via `pypandoc-binary` |
| PDF | WeasyPrint (pure Python) | `[weasyprint]` extra + system libs (pango, cairo) |
| PPTX | `md2pptx` CLI (.NET tool) | `dotnet tool install --global md2pptx` |
| HTML | `markdown` lib | none |
| CSV/XLSX/JSON/XML/IPYNB/SRT/EML/MSG | stdlib / pure Python | optional extras per format |

**Special cases**:
- **MSG** requires commercial `aspose-email-foss` (GPLv3). **Use `.eml` instead** (open standard, fully supported).
- **PDF→XLIFF is intentionally blocked** by OPP. Use the MD path.

## MCP vs CLI — when to use which

| Surface | Use when... |
|---|---|
| **CLI** | Ad-hoc one-off conversions, scripts, debugging, manual pipelines |
| **MCP server** | Inside an MCP-compatible agent (Claude, Cursor, OpenCode), want text-in/text-out, want tool-level validation |

**MCP tool counts**: OPP 9 / OL 21 / ORF 7 (37 total). Names + signatures in "MCP tool quick reference" below.

> **⚠️ FastMCP stdio bug**: If MCP servers fail to respond to stdio (silent, no JSON-RPC handshake), use the `scripts/mcp_bridge.py` workaround (raw JSON-RPC over stdin/stdout, no `mcp` library needed). See `../ACCEPTED_GAPS.md` line 18.

## Environment variables cheatsheet

| Variable | Required? | Purpose |
|---|---|---|
| `OMNI_TEST_FAKE_LLM=1` | **Yes (tests/offline)** | Mock LLM responses. Without this, OL tries real API calls. |
| `OMNI_TEST_FAKE_PANDOC=1` | **Yes (tests with DOCX/PPTX/EPUB)** | Bypass pandoc subprocess (use `markdown` lib). |
| `MCP_ALLOWED_DIRECTORIES` | **Yes (all MCP)** | Unified path allowlist for OPP/OL/ORF MCP servers. Per-module vars below act as overrides. |
| `OPP_MCP_ALLOWED_DIRS` | Override (OPP MCP) | Colon-separated path allowlist. Falls back to `MCP_ALLOWED_DIRECTORIES`. |
| `ORF_MCP_ALLOWED_DIRS` | Override (ORF MCP) | Colon-separated path allowlist. Falls back to `MCP_ALLOWED_DIRECTORIES`. |
| `OL_ALLOWED_DIRECTORIES` | Override (OL MCP) | Comma-separated path allowlist. Falls back to `MCP_ALLOWED_DIRECTORIES`. |
| `MCP_SHARED_SECRET` | Optional | Shared-secret auth for MCP requests. |
| `OMNI_LOG_FORMAT` | Optional | `json` for structured logs (default: `console`). |
| `OPP_OCR_LANG` | Optional | Tesseract OCR language code (e.g. `chi_sim`, `jpn`, `fra`). |
| `OL_CONFIG_PATH` | Optional | Override OL LLM config path (default `config/default.yaml`). |
| `OMNI_METRICS_DIR` | Optional | Prometheus metrics directory (default `/tmp/omni-metrics`). |

## Critical constraints

**Backup mirrors (renanzai40) — disaster recovery + writable remote when origin is down:**
- Every repo has a `backup` remote → `renanzai40/{OmniSuite,OPP,OL,ORF}_BackUp.git`, authenticated via SSH key `~/.ssh/id_ed25519_renanzai40` (host alias `github.com-renanzai40`, port 443). See `omni-issue-pr` skill → "Backup mirrors" for the full table, SSH incantation, and sync discipline.
- **When `origin` (1StepMore) is unreachable** (account suspended / deploy-key read-only / TLS failure), use `backup` for all writes: `git push backup main:main`.
- After `main` changes, keep the mirror in sync (`git push backup main:main`); if the mirror has commits local main lacks (e.g. externally pushed fixes/security series), **merge them into local main** rather than force-overwriting.
- Offline full-history bundles: `.backup-bundles/*.bundle` at suite root (OPP/OL/ORF bundles clone cleanly; suite bundle is a shallow artifact — use `refs/backup/*` for suite recovery).

- **Python ≥ 3.13** is required for all components. Verify with `python3 --version`.
- **Always set `OMNI_TEST_FAKE_LLM=1`** unless real LLM API keys are configured.
- **For DOCX/PPTX ORF tests, also set `OMNI_TEST_FAKE_PANDOC=1`** — without this, pandoc is invoked as a subprocess and tests fail.
- **For MSG output, use `.eml`** — MSG requires commercial Aspose.Email.
- **For cross-format XLIFF** (e.g., DOCX → PPTX), use `orf apply-xliff --force`.
- **PDF → XLIFF is intentionally blocked** by OPP. Use the MD path.
- **PDF text+image positions**: OPP#28 fixed 552pt offset. Use OPP v0.9.0+ for PDF translation.
- **CLI framework divergence**: OPP uses argparse, OL uses typer, ORF uses click. Flag names are consistent but help styles differ (see ADR 0001).

## Common errors (top 5)

1. **"Tool not found" in MCP** → Check `CLAUDE.md` / `.cursorrules` for correct tool names. ORF has **7** tools (incl. `get_capabilities`).
2. **"ValueError: allowed_directories cannot be empty"** → Set `OPP_MCP_ALLOWED_DIRS` (NOT `OPP_ALLOWED_DIRECTORIES`). OPP is fail-closed.
3. **"PDF → XLIFF blocked"** → Use MD path. PDF→XLIFF is intentionally not supported.
4. **OL real LLM timeout** → Set `OMNI_TEST_FAKE_LLM=1` for testing, or set API keys in `.env`.
5. **"MCP server not responding to stdio"** → Use `scripts/mcp_bridge.py` (FastMCP 3.4.2 stdio bug). See `../ACCEPTED_GAPS.md`.

## MCP tool quick reference (37 total across modules)

### OPP — `opp-mcp-server` (9 tools)
- `extract_document` — Extract single file (13 input formats)
- `batch_extract` — Process multiple files
- `detect_format_tool` — Magic-bytes detection
- `generate_markdown` — MD only
- `generate_xliff` — XLIFF only
- `save_skeleton` — Save skeleton.zip (required by ORF `apply-xliff`)
- `validate_xliff` — XLIFF structural validation
- `get_capabilities` — Server capability advertisement
- `ping` — Health check

### OL — `ol-mcp` (21 tools, **no `-server` suffix**)
- `translate_md_text` — Translate MD (text-in/text-out, primary agent tool)
- `translate_xliff` — Translate XLIFF
- `judge_text` — LQA quality scoring (0-100)
- `load_glossary` — Load JSON glossary
- `get_relevant_terms` — Extract relevant terms
- `search_tm` — Search TMX translation memory
- `batch_translate_texts` — Parallel batch translate
- `ping` — Health check

> Full 21-tool registry: see the OL MCP tool table in `Omni_Localizer/AGENTS.md` (21 tools total).

### ORF — `orf-mcp-server` (7 tools)
- `apply_md` — MD → 16 formats (accepts inline `content` OR path `input_md`)
- `apply_xliff` — Backfill XLIFF into source (needs skeleton.zip)
- `batch_convert` — Batch convert directory
- `detect_format` — Magic-bytes detection
- `info` — Document metadata
- `get_capabilities` — Server capability advertisement
- `ping` — Health check

For per-tool parameter signatures, see each module's `docs/API.md` (e.g. `../Omni_Pre_Processor/docs/API.md`); `../docs/agent-pipeline-guide.md` lists tool names, counts, and namespacing.

## Recent fixes (since 2026-06-01)

| Date | Module | Fix |
|---|---|---|
| 2026-06-29 | Suite | `make doctor` 7-check health gate. Matrix false-positive fix (0/200). `check_deps.sh` sub-repo check fix. |
| 2026-06-29 | Suite | `scripts/sync_version_docs.py` regex backreference bug fix (root cause of AGENTS.md version table corruption). |
| 2026-06-28 | OPP | **#28 CRITICAL** — PDF text + image positions. Fixed 552pt offset (wrong bottom-left origin assumption). |
| 2026-06-27 | OPP | **#26** — PDF zero body margin in `DEFAULT_PDF2HTML_CSS` (eliminates +12pt Y image offset). |
| 2026-06-26 | OPP | **#24** — PDF image position via `page.get_image_info()` bbox + `doc.extract_image()`. |
| 2026-06-24 | OPP/ORF | **#20/21/22** — PDF2HTML integration, skeleton `<head>`+page-break, base64 filter. |
| 2026-06-23 | OL | **E2E-83** — litellm pre-call check removed (no more 50KB rejection). |
| 2026-06-22 | OL | **E2E-77/78** — math regex + HTML shield marker format (`[OL:HTML:NNNN]` ASCII-delimited). |
| 2026-06-22 | OL/OPP | **E2E-81/82** — CSV quoted multi-line cells, HTML docling fallback. |
| 2026-06-22 | ORF | **E2E-79** — `md2pptx` pre-flight check + actionable install hint. |
| 2026-06-22 | ORF | **E2E-80** — PathValidator adds csv/tsv/xlsx/json/ipynb/eml/msg/srt/icml/rtf/pdf. |
| 2026-06-21 | OL | **E2E-74** — `ModelPool.translate(context=...)` supports dict/str. |
| 2026-06-21 | Suite | **`scripts/mcp_bridge.py`** — FastMCP 3.4.2 stdio bug workaround. **Required for MCP to work.** |
| 2026-06-20 | Suite | v0.2.0 — initial agent-onboarding docs, `omni-suite` CLI, 36-path matrix (W4). |

Full changelog: `../CHANGELOG.md`. Compatibility matrix: `../COMPATIBILITY.md`.

## Submodule skills (defer here for deep work inside one module)

> **⚠️ Caveat**: These submodule skills were created at Suite v0.2.0 (CHANGELOG line 48-50) and have **not been kept in sync** with the per-submodule AGENTS.md files. They are tool-level references, not authoritative; for current MCP tool signatures, env vars, and known issues, defer to:
> - OPP → `Omni_Pre_Processor/AGENTS.md`
> - OL → `Omni_Localizer/AGENTS.md`
> - ORF → `Omni_Re_Formatter/AGENTS.md`

The actual skill file locations (note the `src/` prefix that CHANGELOG got wrong):

- **OPP** (OpenCode) → `Omni_Pre_Processor/src/opp_agent/SKILL.md` (66 lines, 5 of 9 MCP tools listed — defer to `Omni_Pre_Processor/AGENTS.md`)
- **OPP** (Hermes) → `Omni_Pre_Processor/src/opp_hermes/SKILL.md` (108 lines, alternative agent target)
- **OL** (OpenCode) → `Omni_Localizer/src/.opencode/skills/ol-localizer/SKILL.md` (76 lines, CLI-focused)
- **OL** (Hermes) → `Omni_Localizer/src/.hermes/skills/ol-localizer/SKILL.md` (76 lines, CLI-focused)
- **ORF** (OpenCode) → `Omni_Re_Formatter/src/.opencode/skills/orf-formatter/SKILL.md` (75 lines, CLI-focused)

## Canonical docs (pointers to the project's real files)

These are the project's canonical agent-context files. Read these for depth.
If the local `references/` symlinks exist (see bottom of this section), you can
use the short `references/<name>.md` form; otherwise use the full path.

| Doc | Path (if no symlinks) | Purpose | Size |
|---|---|---|---|
| Comprehensive agent guide | `../AGENTS.md` | Per-module cheat sheet, MCP config, env vars | 17KB |
| MCP tool inventory & namespacing | `../docs/agent-pipeline-guide.md` | All 37 MCP tool names + counts (full params in module `docs/API.md`) | 9KB |
| Cross-module architecture | `../docs/ARCHITECTURE.md` | 3-stage pipeline internals | 25KB |
| ADRs | `../docs/DECISIONS.md` | CLI framework divergence, etc. | 3KB |
| Cross-repo release notes | `../docs/RELEASE_NOTES.md` | Monthly aggregated changes | 1KB |
| Version matrix | `../COMPATIBILITY.md` | Suite↔submodule versions | 2KB |
| Known gaps & workarounds | `../ACCEPTED_GAPS.md` | Limitations + fixes (e.g., mcp_bridge.py) | 5KB |
| Error code reference | `../docs/ERROR_CODES.md` | Exit codes, error codes | 7KB |
| Security model | `../docs/SECURITY.md` | PathValidator, MCP auth, rate limits | 12KB |
| Suite changelog | `../CHANGELOG.md` | Last 208 lines of history | 16KB |
| API stability | `../docs/API_STABILITY.md` | API stability guarantees | 16KB |
| Project status (snapshot) | `../PROJECT_STATUS.md` | "First file to read" 1-2 page summary | ~7KB |

**Local convenience**: the `references/` subdir may contain 9 symlinks pointing
to these same files. These are **git-ignored** (root `.gitignore:27` excludes
`.opencode/`), so they're only present in your local checkout. Use `git add -f
.opencode/skills/omni-suite/references/` if you want to commit them. The
absolute paths above work regardless.

## Example

Translate `report.docx` from English to Chinese, output as DOCX:

```bash
export OMNI_TEST_FAKE_LLM=1
make doctor && make smoke       # verify health

opp report.docx --target-format both --source-lang en --target-lang zh --output-dir /tmp/opp
ol translate-md /tmp/opp/report.md -s en -t zh -o /tmp/ol
orf apply-md /tmp/ol/report.md --target-format docx -o report_zh.docx

# Verify
ls -la report_zh.docx            # file exists
make smoke                       # contract still holds
```
