# Agent Pipeline Guide

> **Audience**: AI agents and developers orchestrating the Omni Suite
> pipeline (OPP -> OL -> ORF). This is a quick-reference aggregation.
> For detailed per-module internals, follow the links to canonical docs.

---

## 1. Architecture Overview

The Omni Suite is a 3-stage document localization pipeline. Each stage is
an independent module with its own CLI, PyPI package, and MCP server:

| Stage | Module | Role |
|-------|--------|------|
| 1 | **OPP** (Omni Pre Processor) | Extract source document to Markdown + XLIFF + skeleton.zip |
| 2 | **OL** (Omni Localizer) | Translate MD or XLIFF between languages |
| 3 | **ORF** (Omni Re Formatter) | Backfill translated content into a target format document |

```
Source file (DOCX, PPTX, PDF, ...)
        |
        v
  +------------------+
  |  OPP (Extract)   | ----> document.md, document.xlf, skeleton.zip
  +------------------+
        |
        | translated artifacts
        v
  +------------------+
  |  OL (Translate)  | ----> translated.md, translated.xlf
  +------------------+
        |
        v
  +------------------+
  |  ORF (Backfill)  | ----> result.docx (or other target format)
  +------------------+
```

For a full diagram (Mermaid + ASCII) with all artifact paths, see
`docs/ARCHITECTURE.md` (Section 2, Pipeline Diagram). The architecture
doc also covers cross-module data contracts, version compatibility, and
the extraction/translation/backfill data model.

---

## 2. Pipeline Selection Strategy (XLIFF vs MD)

The Omni Suite supports two parallel pipeline paths. Choosing the right
one is the most common agent decision.

**MD Path (text first):**
- OPP produces `.md` files
- OL translates via `translate-md`
- ORF converts via `apply-md` (supports 16 output formats)
- Best for: speed, format conversion, approximate layout

**XLIFF Path (layout faithful):**
- OPP produces `.xlf` + `skeleton.zip`
- OL translates via `translate-xliff`
- ORF backfills via `apply-xliff` (same format as source)
- Best for: pixel perfect output, contracts, branded docs

OPP also exposes a `suggested_pipeline` enum in its extraction result
(see OPP issue #11) that recommends one path based on the input format.
When the source format supports skeleton preservation, it suggests
XLIFF; for data formats (CSV, JSON, XML) it suggests MD.

For the full decision tree (with a complete ASCII diagram), see
`README.md#pipeline-selection-strategy`. Per-module decision tables
live in each sub repo's AGENTS.md:
- [OPP target format guide](https://github.com/1StepMore/Omni_Pre_Processor/blob/main/AGENTS.md)
- [OL translate-md vs translate-xliff](https://github.com/1StepMore/Omni_Localizer/blob/main/AGENTS.md)
- [ORF apply-md vs apply-xliff](https://github.com/1StepMore/Omni_Re_Formatter/blob/main/AGENTS.md)

---

## 3. Format to Pipeline Mapping

Not every input format supports both paths. This is a condensed summary.
See `README.md` for the full matrix with notes.

| Input Format | MD Path | XLIFF Path | Notes |
|-------------|---------|------------|-------|
| DOCX | Yes | Yes | Preferred path for both |
| PPTX | Yes | Yes | XLIFF preserves slide masters |
| EPUB | Yes | Yes | XLIFF preserves CSS layout |
| PDF | Yes | **No** | PDF to XLIFF intentionally blocked by OPP |
| HTML | Yes | No | No skeleton.zip produced |
| CSV / JSON / XML | Yes | No | Data formats, no layout |
| EML / MSG | Yes | No | Email formats (MSG limited) |
| Images (OCR) | Yes | No | Text extraction only |
| YouTube URL | Yes | No | Transcription only |

When unsure, use `--target-format both` in OPP. This produces MD, XLIFF,
and skeleton.zip simultaneously, keeping both paths open without
re-extraction. The extra disk space is negligible.

---

## 4. MCP Tool Reference

Each module exposes its own MCP server. The table below lists the servers
and their tool counts. For full per-tool parameter reference, see the
per-module `AGENTS.md` files or `docs/API.md`.

### Server Overview

| Server | Tool Count | CLI Start Command | MCP Name |
|--------|-----------|-------------------|----------|
| OPP MCP | 9 | `opp mcp` or `uvx opp-mcp` | `opp-mcp-server` |
| OL MCP | 21 | `ol mcp` or `uvx ol-mcp` | `ol-mcp` |
| ORF MCP | 7 | `orf mcp` or `uvx orf-mcp` | `orf-mcp-server` |
| Omni MCP | 4 (suite) | `omni-mcp` | `omni-mcp` |

Module MCP tools: **37** (9 OPP + 21 OL + 7 ORF); plus 4 suite tools
(`omni_mcp`: `translate_file`, `ping`, `list_validation_scenarios`,
`run_validation_scenario`) = **41 total**.

### Tool Lists

**OPP MCP (9 tools):**
`extract_document`, `batch_extract`, `detect_format_tool`,
`generate_markdown`, `generate_xliff`, `save_skeleton`, `ping`,
`validate_xliff`, `get_capabilities`

**OL MCP (21 tools):**
`translate_md_text`, `translate_xliff`, `judge_text`, `load_glossary`,
`get_relevant_terms`, `search_tm`, `batch_translate_texts`, `translate_file`,
`extract_terms`, `add_tm_entries`, `shield_md_text`, `unshield_md_text`,
`generate_report`, `inspect_config`, `disambiguate`, `extract_warnings`,
`get_translation_status`, `verify_terms`, `profile_doc`, `get_capabilities`,
`ping`

**ORF MCP (7 tools):**
`apply_md`, `apply_xliff`, `batch_convert`, `detect_format`, `info`, `ping`,
`get_capabilities`

**Omni MCP:** The suite-level server exposes 4 tools (`translate_file`,
`ping`, `list_validation_scenarios`, `run_validation_scenario`). Use
per-module servers for the OPP/OL/ORF tool surfaces.

### Tool Namespacing and Disambiguation

MCP tool names are **server-namespaced**: the same short name can appear on
more than one server with different semantics. Always resolve a tool by the
`(server, tool_name)` pair, never by the bare name. **No tools were renamed
for disambiguation** — the notes below document the existing names and when
to use which.

#### `translate_file` -- OL MCP vs Omni MCP

Both servers expose a tool literally named `translate_file`, and both drive
an OPP -> OL -> ORF run. They are different surfaces:

| | OL MCP (`ol-mcp`) | Omni MCP (`omni-mcp`) |
|---|---|---|
| Role | OL's file-based end-to-end entry point (shells out to `opp`/`ol`/`orf`) | Suite-level orchestrator for a one-call pipeline |
| Path security | OL's own `MCP_ALLOWED_DIRECTORIES` validator applies; intermediates live in a tempdir, `keep_temp` retains on success | Applies the suite allowlist (`MCP_ALLOWED_DIRECTORIES` / `OMNI_MCP_ALLOWED_DIRS` / sub-module names); denies with `OMNI_PATH_DENIED` |
| Extra inputs | `output_dir`, `glossary_path`, `config_path`, `keep_temp`, `timeout` | `pipeline` (`md`/`xliff`), `shared_secret`; produces `output_format` |
| Use when | You are connected to the OL server and want OL to drive the whole pipeline (with OL config/glossary) | You are connected to the suite aggregator and want a single orchestration call |

Guidance: call the `translate_file` on the server you are connected to — the
bare name does not identify its server. For per-stage control
(extract-only, translate-only, backfill-only), use the module tools instead.

#### Format detection -- OPP `detect_format_tool` vs ORF `detect_format`

- **`detect_format_tool`** (OPP MCP): identify an input document's format by
  magic bytes; returns the format name and a confidence score in `[0, 1]`.
  Use it before extraction.
- **`detect_format`** (ORF MCP): ORF's own magic-byte format detection on the
  backfill side; it returns the format name only (no confidence score).

The `_tool` suffix on OPP's name is historical (it predates MCP-standard
naming); it is not a different capability from ORF's `detect_format`.

#### ORF `info` vs ORF `detect_format`

Both live on the ORF server:

- **`detect_format`** returns just the detected format (magic bytes).
- **`info`** returns document metadata — format, size, resource count, and
  manifest status. Use `info` when you need more than the format name.

#### Cross-server parity tools

`ping` is exposed by **all four** servers (OPP, OL, ORF, and Omni MCP) as a
health check. `get_capabilities` is exposed by **OPP, OL, and ORF** (not by
the suite aggregator) and returns that module's supported formats/languages
plus its tool list — call it to discover the server's runtime surface.

### Per-Tool Parameters

This guide lists tool names, counts, and namespacing only. Detailed
parameter schemas, required fields, and type information for every tool
live in each module's `docs/API.md`:

- OPP: `Omni_Pre_Processor/docs/API.md`
- OL: `Omni_Localizer/docs/API.md`
- ORF: `Omni_Re_Formatter/docs/API.md`

---

## 5. Standard Response Format

All three MCP servers (OPP, OL, ORF) return responses in a uniform
envelope. This is defined as a frozen contract in
`docs/API_STABILITY.md` (Section 5.1, Surface #3: MCP tool I/O).

### Success Response

```json
{
  "success": true,
  "content": { ... }
}
```

### Error Response

```json
{
  "success": false,
  "error_code": "OPP_FILE_NOT_FOUND",
  "message": "A required file was not found."
}
```

OPP and ORF also include a legacy `"error"` field (a string matching
`message`) for backward compatibility with older test assertions. New
clients should switch on `error_code` only. See `docs/ERROR_CODES.md`
(Section "Response Shape", lines 15-29) for the authoritative spec.

### Error Code Catalog

The full error code catalog (shared codes + per-module codes) lives in
`docs/ERROR_CODES.md`. It covers:

- **Shared codes** (all 3 modules): `AUTH_FAILED`
- **OPP codes**: `OPP_FILE_NOT_FOUND`, `OPP_PERMISSION_DENIED`,
  `OPP_INVALID_INPUT`, `OPP_MISSING_KEY`, and others in
  `opp/mcp/_errors.py`
- **OL codes**: Defined in `ol_mcp/_errors.py`
- **ORF codes**: Defined inline in `orf/mcp/server.py`

Each code entry includes the error's meaning, when it occurs, and the
recommended caller action. New codes can be added, but existing codes
must not be renamed or removed (per the stability contract in
`docs/API_STABILITY.md`).

---

## 6. Path Configuration

Each MCP server handles file system access differently. The table below
compares their default behavior and security posture.

| Server | Env Variable | Default | Behavior if Unset | Security |
|--------|-------------|---------|-------------------|----------|
| OPP MCP | `OPP_MCP_ALLOWED_DIRS` | None | Raises `ValueError`, server refuses to start | Fail-closed |
| OL MCP | `MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`) | None | Raises `ValueError`, server refuses to start | Fail-closed |
| ORF MCP | `ORF_ALLOWED_DIRECTORIES` | `[Path.cwd()]` | Silently uses CWD | Fail-open |
| Omni MCP | N/A | N/A | Relies on underlying server config | N/A |

### OPP MCP (Fail Closed)

OPP requires explicit configuration via `OPP_MCP_ALLOWED_DIRS`
(colon-separated paths). If unset, the MCP server refuses to start:

```bash
export OPP_MCP_ALLOWED_DIRS="/data/documents:/data/output"
```

Validation includes: directory allowlist membership, symlink boundary
checks, blocked extension filtering (executables), allowed extension
whitelist, and file size limits. See
`Omni_Pre_Processor/AGENTS.md` (Path Configuration section) for details.

### ORF MCP (Fail Open)

ORF uses `ORF_ALLOWED_DIRECTORIES` (note: different variable name from
OPP). If unset, it silently falls back to `[Path.cwd()]` (the current
working directory at server start). This is a potential security gap
for production deployments:

```bash
export ORF_ALLOWED_DIRECTORIES="/data/documents:/data/output"
```

The same validation pipeline (allowlist, extensions, symlinks, size)
applies when the variable is set. See
`Omni_Re_Formatter/AGENTS.md` (Path Configuration section) for details.

### OL MCP (Fail Closed)

OL reads a comma-separated directory allowlist from
`MCP_ALLOWED_DIRECTORIES` (unified cross-module name), falling back to
`OL_MCP_ALLOWED_DIRS` (OL-specific) and then the deprecated
`OL_ALLOWED_DIRECTORIES`. If none is set, `get_default_validator()`
raises `ValueError` and the MCP server refuses to start — it no longer
silently defaults to `cwd` + `/tmp`:

```bash
export MCP_ALLOWED_DIRECTORIES="/data/documents,/data/output"
```

Note: the separator is a **comma** (OPP's `OPP_MCP_ALLOWED_DIRS` uses
colons). Path denials are reported with the stable `OL_PATH_DENIED`
error code. See `Omni_Localizer/AGENTS.md` (Env vars section) for
details.

### Omni MCP

The suite-level aggregator does not implement its own path validation.
It delegates all file operations to the underlying per-module servers.
Configure those individually using the variables above.

### Recommended Setup

Always set OPP, OL, and ORF path variables explicitly (OPP/ORF are
colon-separated; OL is comma-separated):

```bash
export OPP_MCP_ALLOWED_DIRS="/data/documents"
export MCP_ALLOWED_DIRECTORIES="/data/documents"
export ORF_ALLOWED_DIRECTORIES="/data/documents"
```

For CI/CD environments:

```bash
export OPP_MCP_ALLOWED_DIRS="${GITHUB_WORKSPACE}/test_fixtures"
export MCP_ALLOWED_DIRECTORIES="${GITHUB_WORKSPACE}/test_fixtures"
export ORF_ALLOWED_DIRECTORIES="${GITHUB_WORKSPACE}/test_fixtures"
```

### Per-Module Documentation

- OPP path config: `Omni_Pre_Processor/AGENTS.md` ->
  Path Configuration (MCP Server) section
- ORF path config: `Omni_Re_Formatter/AGENTS.md` ->
  Path Configuration (MCP Server) section
- Security model: `ARCHITECTURE.md` (cross-module),
  `Omni_Pre_Processor/AGENTS.md` -> PathValidator security model section,
  `Omni_Re_Formatter/AGENTS.md` -> PathValidator security model section
