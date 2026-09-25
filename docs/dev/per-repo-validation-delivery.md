# Per-Repo Validation Delivery

How the Omni Suite validation framework ships, runs, and delivers scenario
libraries **per component repo**. This is the canonical reference for the
per-repo delivery introduced by OPP#58. Someone reading this cold can run
every command below.

## 1. Where the scenario libraries live

The framework is agent-agnostic: every scenario dispatches through the REAL
shipped surface (no mocks, no FAKE_LLM as evidence). Each library is a plain
directory of YAML scenarios with its own `STANDARDS.md` (the citable bar,
exact anchors per step) and `_fixtures/` (committed input files the
scenarios provision).

| `--repo` value | Scenario source dir | Library | Tier | Notes |
|---|---|---|---|---|
| `suite` (default) | `scenarios/` | Agent-surface + pipeline | 1-2 | the original suite-level library |
| `opp` | `Omni_Pre_Processor/scenarios/` | 6 `opp-extraction` | 1 | hermetic, no keys |
| `ol` | `Omni_Localizer/scenarios/` | 5 `ol-translation` | 2 | `requires_env` = 3 canonical real LLM provider keys; `unconfigured` without them |
| `orf` | `Omni_Re_Formatter/scenarios/` | 6 `orf-backfill`/`orf-md`/`orf-xliff` | 1 | `requires_env: [MCP_ALLOWED_DIRECTORIES]` — ORF is fail-closed on the MCP allowlist |
| `all` | all four dirs merged | everything above | 1-2 | full cross-repo sweep |

OL's provider env vars (mirroring `config/default.yaml`): `ARK_API_KEY`,
`ZHIPU_API_KEY`, `NVIDIA_NIM_API_KEY`.

## 2. Enumerate and run

All commands run from the Omni Suite root with the shared venv:

```bash
source .venv_ol/bin/activate

# Enumerate the default (suite) library — no execution, no LLM
python scripts/validation/run_validation.py --list

# Enumerate one module's in-repo library
python scripts/validation/run_validation.py --repo opp --list
python scripts/validation/run_validation.py --repo ol --list
python scripts/validation/run_validation.py --repo orf --list

# Run a per-repo library
python scripts/validation/run_validation.py --repo opp --tier 1
python scripts/validation/run_validation.py --repo ol --tier 2      # needs real LLM keys
MCP_ALLOWED_DIRECTORIES=/tmp python scripts/validation/run_validation.py --repo orf --tier 1

# Dry-run all four repos — loads + validates + prints the plan, dispatches nothing
python scripts/validation/run_validation.py --repo all --dry-run

# Contract-lint a library (falsifiable expects, STANDARDS.md anchors)
python scripts/validation/run_validation.py --check
```

Tier semantics: 1 = hermetic (no keys), 2 = real LLM keys, 3 =
paid/external/network. A tier-2/3 scenario without its keys reports
`unconfigured` — never a pass, never a silent skip.

The old `--module opp|ol|orf|suite` filter still exists; it selects a
module's scenarios by category (its in-repo categories plus its
`tool-<module>-*` agent-surface scenarios from the suite library).

## 3. `run_meta` in persisted runs

Every persisted run (`validation-runs/<ts>/scenarios.json`) carries a
`run_meta` block, auto-collected at run time:

```json
{
  "suite_version": "0.4.0",
  "suite_sha": "<suite git sha>",
  "opp":  { "version": "0.9.1",  "sha": "<opp git sha>" },
  "ol":   { "version": "0.7.1",  "sha": "<ol git sha>" },
  "orf":  { "version": "0.4.17", "sha": "<orf git sha>" },
  "repos": ["suite", "opp", "ol", "orf"]
}
```

`repos` lists which source dirs fed the run. The diff and report tools
consume this block (see §5 and §6).

## 4. `--matrix` and `--deliver`

Both flags run **after** a persisted run and operate on the newest run
(`validation-runs/latest.txt` points at it).

```bash
# Run ORF's tier-1 library, then build the director report AND the delivery zip
MCP_ALLOWED_DIRECTORIES=/tmp python scripts/validation/run_validation.py --repo orf --tier 1 --matrix --deliver
```

- `--matrix` renders the director report into the run dir:
  `report.md` + `report.json`, prints `MATRIX: <path>`. `report.json`
  includes a `report_card` with a per-repo matrix (version + sha +
  per-scenario verdicts).
- `--deliver` builds a human-review zip at
  `04-Output/artifacts/deliverables/omni-suite/omni-suite-validation-<run_id>.zip`,
  prints `DELIVERY: <zip>`. Layout:

```
omni-suite-validation-<run_id>.zip
├── manifest.json              # what's in the package
├── 01-RAW/                    # real artifact copies from the run
├── 02-PROCESSED/
│   ├── validation-report.md   # the director report (two verdict families)
│   ├── report.json
│   ├── run_meta.json          # the run_meta block alone
│   └── verdict-summary.md
└── 03-MISSING/                # missing-artifact notes
```

You can also generate the director report manually:

```bash
cat validation-runs/latest.txt
python scripts/validation/validation_report.py validation-runs/<ts>/scenarios.json
# → report.md + report.json in the same run dir
```

The report renders TWO verdict families side by side: **agent-user
conformance** (tool-* scenarios + AGENT-SURFACE anchors) and
**human-quality conformance** (pipeline-* scenarios + HUMAN-QUALITY
anchors). Read `scenarios/STANDARDS.md` before judging a verdict.

## 5. Four-class version regression

`validation_diff.py` diffs two runs. With a version flag it selects the
base run by its `run_meta` and classifies every scenario into
`new` / `regressed` / `fixed` / `existing-failing`, rendering a
`VERSION REGRESSION (four-class)` section.

```bash
# Classic 5-kind diff (unchanged, no version flags)
python scripts/validation/validation_diff.py <runs-dir>/<ts1> <runs-dir>/<ts2>

# Four-class VERSION REGRESSION against a tagged version
python scripts/validation/validation_diff.py <runs-dir>/<newer> --against-version 0.4.0

# Four-class VERSION REGRESSION against a specific suite/repo sha
python scripts/validation/validation_diff.py <runs-dir>/<newer> --base-sha <sha>
```

**Exit-code contract**: exit 1 when `regressed > 0` OR
`existing-failing > 0`. A clean four-class run against the base exits 0.
The base selector matches `run_meta` values — any repo version, the suite
version, or the run id/timestamp prefix — and always picks the newest base
older than the head.

## 6. Coverage snapshot

`coverage_audit.py` proves every live MCP tool is exercised by a scenario.
`--out` writes a nested, diff-friendly snapshot that `validation_diff.py`
consumes:

```bash
python scripts/validation/coverage_audit.py --out validation-runs/<ts>/coverage.json
```

The snapshot shape:

```json
{
  "generated_at": "<iso timestamp>",
  "suite_sha": "<suite git sha>",
  "declared":  {...},
  "covered":   {...},
  "missing":   {...},
  "phantom":   {...},
  "totals":    {...}
}
```

When BOTH runs in a diff carry `coverage.json`, `validation_diff.py`
renders a coverage delta section. Without the snapshot on either side, the
delta is skipped with a note — never a fake green.

## 7. Reading the results

1. `validation-runs/latest.txt` → path of the newest run
   (`validation-runs/<ts>/scenarios.json`).
2. `--matrix` or `validation_report.py` → `report.md` + `report.json`
   (with `report_card`) in the same run dir.
3. `validation_diff.py` → verdict-change diff, four-class version
   regression, and optional coverage delta.

Director loop + 10-minute per-run checklist:
`docs/dev/validation-director-loop.md` (two-role model: agent validator +
human director; per-run standards conformance pass ticking both families).
