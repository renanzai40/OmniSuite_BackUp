"""omni-suite — suite-level CLI for the Omni document localization pipeline."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import run_manifest

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
_COMPAT_FILE = Path(__file__).parent.parent / "COMPATIBILITY.md"
_VENV_BIN = Path(__file__).parent.parent / ".venv_ol" / "bin"

# Canonical LLM provider keys OL uses for translation/judging/restoration —
# the three priorities in Omni_Localizer/config/default.yaml
# (ark-code-latest, glm-4.7-flash, minimaxai/minimax-m3).
_LLM_API_KEYS = [
    "ARK_API_KEY",
    "ZHIPU_API_KEY",
    "NVIDIA_NIM_API_KEY",
]

# Optional but commonly expected env vars
_OPTIONAL_VARS = [
    "OL_CONFIG_PATH",
    "OL_LOG_LEVEL",
    "OPP_LOG_LEVEL",
    "ORF_LOG_LEVEL",
    "OMNI_CACHE_DIR",
    "OMNI_LOG_FORMAT",
    "MCP_SHARED_SECRET",
    "MCP_ALLOWED_DIRECTORIES",
    "OPP_MCP_ALLOWED_DIRS",
    "ORF_MCP_ALLOWED_DIRS",
    "OL_ALLOWED_DIRECTORIES",
]


def _validate_env(require_llm: bool = False) -> None:
    """Warn or error on missing environment variables.

    Args:
        require_llm: If True, exit with error when no LLM key is found
                     (used for 'pipeline' and real translation commands).
    """
    missing_keys: list[str] = []
    for key in _LLM_API_KEYS:
        if not os.environ.get(key):
            missing_keys.append(key)

    if missing_keys:
        all_missing = len(missing_keys) == len(_LLM_API_KEYS)
        if all_missing:
            msg = (
                "⚠️  No LLM provider keys found. Set at least one of:\n"
                f"       {', '.join(_LLM_API_KEYS)}\n"
                "   Copy .env.example → .env and fill in your keys.\n"
                "   For testing, set OMNI_TEST_FAKE_LLM=1 to bypass LLM calls."
            )
        else:
            missing_list = ", ".join(missing_keys)
            msg = f"⚠️  Some LLM provider keys are unset: {missing_list}"
        if require_llm:
            print(msg, file=sys.stderr)
            sys.exit(1)
        # T-05: agents parse stdout — the warning belongs on stderr.
        print(msg, file=sys.stderr)

    missing_optional = [k for k in _OPTIONAL_VARS if not os.environ.get(k)]
    if missing_optional and not os.environ.get("OMNI_TEST_FAKE_LLM"):
        pass  # silence optional warnings — .env.example documents them


def _no_llm_needed(args: list[str]) -> bool:
    """True when a pipeline invocation needs no LLM provider key.

    ``--dry-run`` executes nothing; ``--gates-only`` skips ORF and
    ``--fake-llm`` selects the fake seam — all three satisfy the env gate.
    """
    return "--dry-run" in args or "--gates-only" in args or "--fake-llm" in args


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        _validate_env(require_llm=False)
        _print_usage()
        return
    cmd = sys.argv[1]
    if cmd == "--version":
        print(_VERSION_FILE.read_text(encoding="utf-8").strip())
    elif cmd == "--versions":
        _print_versions()
    elif cmd == "--compatibility":
        print(_COMPAT_FILE.read_text(encoding="utf-8"))
    elif cmd in ("pipeline", "translate"):
        remaining = sys.argv[2:]
        # Show help without requiring API keys
        if not remaining or remaining[0] in ("--help", "-h"):
            _run_pipeline(["--help"])
        else:
            # Non-obvious: gates-only/fake-llm run real OPP/OL subprocesses,
            # yet none of the three bypass flags needs an LLM key at this boundary.
            _validate_env(require_llm=not _no_llm_needed(remaining))
            _run_pipeline(remaining)
    elif cmd == "check":
        _run_check(sys.argv[2:])
    elif cmd == "status":
        _run_status(sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        _print_usage()
        sys.exit(1)


def _resolve_tool(name: str) -> str:
    """Prefer the suite venv's tool: pip-installed copies (e.g. ~/.local/bin)
    run without the repo config context and fail on config resolution."""
    venv_tool = _VENV_BIN / name
    if venv_tool.exists():
        return str(venv_tool)
    return shutil.which(name) or name


def _run_pipeline(args: list[str]) -> None:
    """Orchestrate OPP → OL → ORF on a single file.

    Usage: omni-suite pipeline <file> [--source-lang en] [--target-lang zh] [--target-format docx] [--fake-llm] [--resume-from opp|ol|orf] [--run-id ID] [--output <path>]
    """
    if not args or args[0] in ("--help", "-h"):
        print("Usage: omni-suite pipeline <file> [--source-lang en] [--target-lang zh] [--target-format docx] [--fake-llm] [--resume-from opp|ol|orf] [--run-id ID] --output <path>")
        return

    # Parse args
    file_path, kwargs = _parse_pipeline_args(args)
    src = kwargs.get("source-lang", "en")
    tgt = kwargs.get("target-lang", "zh")
    fmt = kwargs.get("target-format", "docx")
    output = kwargs.get("output")
    dry_run = bool(kwargs.get("dry-run"))
    gates_only = bool(kwargs.get("gates-only"))
    keep_intermediate = bool(kwargs.get("keep-intermediate"))
    resume_from = kwargs.get("resume-from")
    run_id = kwargs.get("run-id") or Path(file_path).stem

    if resume_from is True or (resume_from is not None and resume_from not in run_manifest.STAGES):
        print(
            f"❌ Invalid --resume-from {resume_from!r}; expected one of {', '.join(run_manifest.STAGES)}",
            file=sys.stderr,
        )
        sys.exit(2)

    suite_root = Path(__file__).parent.parent
    opp = _resolve_tool("opp")
    ol = _resolve_tool("ol")
    orf = _resolve_tool("orf")
    env = {**os.environ,
           "OL_CONFIG_PATH": str(suite_root / "Omni_Localizer" / "config" / "test_universal.yaml")}
    if kwargs.get("fake-llm"):
        env["OMNI_TEST_FAKE_LLM"] = "1"

    stem = Path(file_path).stem
    temp_dir = Path("/tmp/omni-suite-pipeline") / run_id
    opp_dir = temp_dir / "opp"
    ol_dir = temp_dir / "ol"
    # T-02: the auto-generated output must NOT live inside temp_dir — the
    # finally block removes that dir, which would delete the artifact we
    # report at exit. Place it as a sibling of the temp dir instead.
    out_path = output or str(temp_dir.parent / f"{stem}.result.{fmt}")

    opp_cmd = [opp, file_path, "--target-format", "both",
               "--source-lang", src, "--target-lang", tgt,
               "--output-dir", str(opp_dir)]

    if dry_run:
        print(f"[1/3] OPP would run: {shlex.join(opp_cmd)}")
        print(f"[2/3] OL would run: {shlex.join([ol, 'translate-md', str(opp_dir / f'{stem}.md'), '-s', src, '-t', tgt, '-o', str(ol_dir)])}")
        print(f"[3/3] ORF would run: {shlex.join([orf, 'apply-md', str(ol_dir / f'{stem}.md'), '--target-format', fmt, '-o', out_path])}")
        return

    # R-01: decide which stages to reuse BEFORE touching the filesystem. A
    # missing intermediate (or a stale manifest whose artifacts were deleted)
    # means the requested resume cannot be honoured — fall back to a full run.
    skip_stages = run_manifest.plan_resume(resume_from, opp_dir, ol_dir)
    resumed = bool(skip_stages)

    manifest_path = temp_dir / run_manifest.MANIFEST_NAME
    prior_manifest = None
    if manifest_path.exists():
        try:
            prior_manifest = run_manifest.RunManifest.load(manifest_path)
        except (OSError, ValueError):
            prior_manifest = None

    manifest = run_manifest.RunManifest(
        run_id=run_id,
        input_file=str(Path(file_path).resolve()),
        temp_dir=str(temp_dir),
        output=str(out_path),
        source_lang=src,
        target_lang=tgt,
        target_format=fmt,
    )
    if prior_manifest is not None:
        manifest.created_at = prior_manifest.created_at
        manifest.stages = prior_manifest.stages

    opp_dir.mkdir(parents=True, exist_ok=True)
    ol_dir.mkdir(exist_ok=True)

    failed = False
    current_stage = "opp"
    manifest.save(manifest_path)

    try:
        # Step 1: OPP extract
        if "opp" in skip_stages:
            print(f"[1/3] OPP reuse existing intermediates ({opp_dir})")
            manifest.mark("opp", run_manifest.REUSED, str(opp_dir))
        else:
            print(f"[1/3] OPP extracting {file_path} → {opp_dir}")
            manifest.mark("opp", run_manifest.RUNNING)
            manifest.save(manifest_path)
            subprocess.run(opp_cmd, check=True, env=env, timeout=120)
            manifest.mark("opp", run_manifest.COMPLETE, str(opp_dir))
            manifest.save(manifest_path)

        md_file = next(opp_dir.glob("*.md"), None)
        if not md_file:
            raise RuntimeError("OPP did not produce .md output")

        # Step 2: OL translate
        current_stage = "ol"
        if "ol" in skip_stages:
            print(f"[2/3] OL reuse existing intermediates ({ol_dir})")
            manifest.mark("ol", run_manifest.REUSED, str(ol_dir))
        else:
            print(f"[2/3] OL translating {md_file}")
            manifest.mark("ol", run_manifest.RUNNING)
            manifest.save(manifest_path)
            ol_cmd = [ol, "translate-md", str(md_file), "-s", src, "-t", tgt, "-o", str(ol_dir)]
            ol_result = None
            if gates_only:
                ol_result = subprocess.run(ol_cmd, check=True, env=env, timeout=300,
                                           capture_output=True, text=True)
            else:
                subprocess.run(ol_cmd, check=True, env=env, timeout=300)
            manifest.mark("ol", run_manifest.COMPLETE, str(ol_dir))
            manifest.save(manifest_path)

        ol_md = next(ol_dir.glob("*.md"), None)
        if not ol_md:
            raise RuntimeError("OL did not produce translated output")

        if gates_only:
            manifest.mark("orf", run_manifest.SKIPPED, "gates-only")
            manifest.status = run_manifest.RUN_COMPLETE
            manifest.save(manifest_path)
            print("[gates-only] Skipping ORF backfill — extracting OL quality-gate warnings")
            warnings_run = subprocess.run([ol, "extract-warnings", str(ol_md)],
                                          capture_output=True, text=True,
                                          env=env, timeout=120)
            print(warnings_run.stdout, end="")
            if warnings_run.returncode != 0:
                tail = (ol_result.stdout or "")[-2000:] if ol_result else ""
                if tail.strip():
                    print("--- OL translate-md stdout (tail) ---")
                    print(tail)
                print("(ol extract-warnings unavailable — showing OL stdout tail instead)")
            return

        # Step 3: ORF backfill
        current_stage = "orf"
        print(f"[3/3] ORF backfilling → {out_path}")
        manifest.mark("orf", run_manifest.RUNNING)
        manifest.save(manifest_path)
        subprocess.run([orf, "apply-md", str(ol_md), "--target-format", fmt, "-o", out_path],
                      check=True, env=env, timeout=120)
        manifest.mark("orf", run_manifest.COMPLETE, out_path)
        manifest.status = run_manifest.RUN_COMPLETE
        manifest.save(manifest_path)

        print(f"✅ Pipeline complete: {out_path}")
    except KeyboardInterrupt:
        failed = True
        manifest.mark(current_stage, run_manifest.FAILED, "interrupted")
        manifest.save(manifest_path)
        _print_partial(manifest)
        print("❌ Interrupted — intermediates kept for --resume-from", file=sys.stderr)
        sys.exit(130)
    except subprocess.TimeoutExpired:
        failed = True
        manifest.mark(current_stage, run_manifest.FAILED, "timeout")
        manifest.save(manifest_path)
        _print_partial(manifest)
        print("❌ Timeout: a pipeline step exceeded its time limit", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        failed = True
        manifest.mark(current_stage, run_manifest.FAILED, f"exit {e.returncode}")
        manifest.save(manifest_path)
        _print_partial(manifest)
        print(f"❌ Pipeline step failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        failed = True
        manifest.mark(current_stage, run_manifest.FAILED, type(e).__name__)
        manifest.save(manifest_path)
        _print_partial(manifest)
        print(f"❌ Pipeline error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if keep_intermediate or gates_only:
            print(f"Intermediate files kept at: {temp_dir}")
        elif Path(out_path).resolve().is_relative_to(temp_dir.resolve()):
            print(f"Intermediate files kept at: {temp_dir}")
        elif failed or resumed:
            label = "kept for --resume-from" if failed else "kept as run record"
            print(f"Intermediate files {label} at: {temp_dir}",
                  file=sys.stderr if failed else sys.stdout)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _print_partial(manifest) -> None:
    """Machine-readable partial-run report (R-01) — one JSON object on stdout."""
    print(json.dumps(manifest.summary(), ensure_ascii=False))


def _parse_pipeline_args(args: list[str]) -> tuple[str, dict]:
    """Parse key=value or --key value style pipeline args."""
    file_path = args[0]
    kwargs: dict[str, str | bool] = {}
    i = 1
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = True
                i += 1
        elif "=" in args[i]:
            k, v = args[i].split("=", 1)
            kwargs[k] = v
            i += 1
        else:
            i += 1
    return file_path, kwargs


def _run_check(args: list[str]) -> None:
    """Run all 3 module test suites or readiness checks."""
    readiness = "--readiness" in args
    quick = "--quick" in args
    suite_root = Path(__file__).parent.parent

    if readiness:
        _run_readiness_check(args)
        return

    modules = [
        ("OPP", suite_root / "Omni_Pre_Processor"),
        ("OL", suite_root / "Omni_Localizer"),
        ("ORF", suite_root / "Omni_Re_Formatter"),
    ]

    if quick:
        print("Quick check: dependencies and env")
        # Check pandoc
        pandoc = shutil.which("pandoc")
        print(f"  pandoc: {'✅' if pandoc else '❌'} {pandoc or 'not found'}")
        # WeasyPrint
        try:
            import weasyprint  # noqa
            print("  weasyprint: ✅")
        except ImportError:
            print("  weasyprint: ❌ not installed")
        # FAKE_LLM
        print(f"  OMNI_TEST_FAKE_LLM: {'✅' if os.environ.get('OMNI_TEST_FAKE_LLM') else '❌'} set={bool(os.environ.get('OMNI_TEST_FAKE_LLM'))}")
        return

    for name, path in modules:
        if not (path / "tests").exists():
            print(f"  {name}: tests/ not found — skip")
            continue
        print(f"  Running {name} tests...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(path / "tests"), "-q", "--no-header"],
            capture_output=True, text=True, timeout=600, cwd=str(suite_root),
        )
        lines = result.stdout.strip().split("\n")
        last = lines[-1] if lines else "(no output)"
        passed = " passed" in last
        print(f"  {name}: {'✅' if passed else '❌'} {last}")


def _run_status(args: list[str]) -> None:
    """Show env, dependency, and version status."""
    suite_root = Path(__file__).parent.parent

    print(f"Omni Suite: {_VERSION_FILE.read_text(encoding='utf-8').strip()}")
    print()

    # Module versions
    for name, path in [
        ("OPP", suite_root / "Omni_Pre_Processor"),
        ("OL", suite_root / "Omni_Localizer"),
        ("ORF", suite_root / "Omni_Re_Formatter"),
    ]:
        pyproject = path / "pyproject.toml"
        version = "?"
        if pyproject.exists():
            for line in pyproject.read_text().splitlines():
                if line.startswith("version ="):
                    version = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        print(f"  {name}: {version}")

    print()
    print("Dependencies:")
    print(f"  pandoc:       {shutil.which('pandoc') or '❌ not found'}")
    try:
        import weasyprint; del weasyprint; print("  weasyprint:   ✅")
    except ImportError:
        print("  weasyprint:   ❌ not installed")
    try:
        import aspose.email; del aspose.email; print("  aspose.email: ✅ (.msg available)")
    except ImportError:
        print("  aspose.email: ❌ not installed (.msg requires)")
    print(f"  FAKE_LLM:     {'set' if os.environ.get('OMNI_TEST_FAKE_LLM') else 'not set'}")


def _run_readiness_check(args: list[str]) -> None:
    """Run the production-readiness checker."""
    checker = Path(__file__).parent.parent / "scripts" / "check_readiness.py"
    if not checker.exists():
        print("❌ Production-readiness checker not found at scripts/check_readiness.py")
        sys.exit(1)
    cmd = [sys.executable, str(checker)]
    if "--verbose" in args or "-v" in args:
        cmd.append("--verbose")
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
    sys.exit(result.returncode)


_VERSION_SOURCES = [
    ("omni-suite", _VERSION_FILE),
    ("opp", Path(__file__).parent.parent / "Omni_Pre_Processor" / "pyproject.toml"),
    ("ol", Path(__file__).parent.parent / "Omni_Localizer" / "pyproject.toml"),
    ("orf", Path(__file__).parent.parent / "Omni_Re_Formatter" / "pyproject.toml"),
]


def _read_repo_version(path: Path) -> str:
    """Read a component version from a repo ``VERSION`` or ``pyproject.toml``.

    Installed importlib metadata goes stale whenever a version is bumped
    without reinstalling; the repo files are the source of truth (T-05).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "N/A (not found)"
    if path.name == "VERSION":
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return "N/A (not found)"
    for line in text.splitlines():
        if line.startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "N/A (not found)"


def _print_versions() -> None:
    """Print all 4 component versions from the repo source of truth."""
    for label, path in _VERSION_SOURCES:
        print(f"{label}: {_read_repo_version(path)}")


def _print_usage() -> None:
    print("Usage: omni-suite <command> [options]")
    print("")
    print("Commands:")
    print("  --version              Print suite version")
    print("  --versions             Print all component versions")
    print("  --compatibility        Print version compatibility matrix")
    print("  translate|pipeline <file>")
    print("                         Run OPP→OL→ORF pipeline on a file")
    print("    --source-lang LANG   Source language (default: en)")
    print("    --target-lang LANG   Target language (default: zh)")
    print("    --target-format FMT  Output format (default: docx)")
    print("                         Supports any of ORF's 16 formats")
    print("    --fake-llm           Use fake LLM mode (bypasses API keys)")
    print("    --output PATH        Output file path (auto-generated if omitted)")
    print("    --dry-run            Print the 3 pipeline commands and exit")
    print("                         (executes nothing, creates no files)")
    print("    --gates-only         Run OPP+OL (incl. 8 quality gates) and")
    print("                         print extract-warnings; skips ORF backfill")
    print("    --resume-from STAGE  Resume a partial run (opp|ol|orf): reuse")
    print("                         intermediates of prior stages and continue")
    print("    --run-id ID          Run directory name under /tmp/omni-suite-pipeline")
    print("                         (default: input file stem); targets a prior run")
    print("    --keep-intermediate  Keep /tmp/omni-suite-pipeline/<stem> after run")
    print("")
    print("  Pipeline path selection:")
    print("    MD path (default):   omni-suite translate <file> --target-format <fmt>")
    print("                         Uses OPP→OL(translate-md)→ORF(apply-md).")
    print("                         Best for text-first output in any of 16 formats.")
    print("                         See --target-format for supported formats.")
    print("    XLIFF path (manual): opp <file> --target-format xlf ...")
    print("                         Then: ol translate-xliff ...")
    print("                         Then: orf apply-xliff ...")
    print("                         Best for exact original layout preservation.")
    print("")
    print("  check [--quick|--readiness[ --verbose]]")
    print("                         Run all module tests, quick-env check,")
    print("                         or production-readiness check")
    print("  status                 Show env, dependency, and version status")


if __name__ == "__main__":
    main()
