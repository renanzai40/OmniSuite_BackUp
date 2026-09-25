#!/usr/bin/env python3
"""Thin pytest orchestrator for Omni Suite usability verification.

Runs focused test suites per module and reports a pass/fail matrix.
Exit 0 only if ALL groups pass.
"""

import os
import re
import subprocess
import sys

# --- Constants ----------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEST_GROUPS: list[tuple[str, list[str]]] = [
    ("OPP", ["tests/test_e2e_opp_all_formats.py"]),
    ("OL", ["tests/test_e2e_ol_cli.py", "tests/test_e2e_ol_mcp.py"]),
    ("ORF", ["tests/test_e2e_orf_all_formats.py"]),
    ("MCP", ["tests/test_mcp_smoke.py"]),
    ("Pipeline", ["tests/test_e2e_pipeline.py", "tests/test_pipeline_contract_smoke.py"]),
]

ENV = os.environ.copy()
ENV.update({
    "OMNI_TEST_FAKE_LLM": "1",
    "OMNI_TEST_FAKE_PANDOC": "1",
    "ARK_API_KEY": "sk-dummy",
    "ZHIPU_API_KEY": "sk-dummy",
    "AGNES_API_KEY": "sk-dummy",
    "NVIDIA_NIM_API_KEY": "nvapi-dummy",
})

TIMEOUT = 600  # seconds per group


# --- Helpers ------------------------------------------------------------------

def _parse_summary(output: str) -> dict[str, int] | None:
    """Extract passed/failed/skipped counts from pytest summary line.

    Handles formats like:
        "27 passed, 1 skipped, 1 xfailed in 129.52s"
        "4 failed, 16 passed, 1 skipped in 182.95s"
        "36 passed, 6 failed in 279.84s"
    """
    for line in output.splitlines():
        if re.search(r"\d+ passed|\d+ failed", line) and re.search(r"in \d+\.?\d*s", line):
            counts: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0}
            for m in re.finditer(r"(\d+)\s+(passed|failed|skipped)", line):
                counts[m.group(2)] = int(m.group(1))
            return counts
    return None


def _run_group(name: str, test_files: list[str]) -> tuple[int, int, int, bool]:
    """Run a test group via subprocess. Returns (passed, failed, skipped, timed_out)."""
    cmd = [sys.executable, "-m", "pytest", "--tb=line", "--no-header", "-q"] + test_files
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=ENV,
            cwd=PROJECT_ROOT,
        )
        output = proc.stdout + "\n" + proc.stderr
        counts = _parse_summary(output)
        if counts is not None:
            # Surface per-test failures so CI logs identify the culprit
            # instead of only the group summary: print the FAILED/ERROR
            # headers plus the first error body line after each.
            lines = output.splitlines()
            for i, ln in enumerate(lines):
                if ("FAILED" in ln or "ERROR" in ln) and not ln.startswith("  "):
                    print(f"  {name} detail: {ln.strip()}")
                    for j in range(i + 1, min(i + 3, len(lines))):
                        body = lines[j].strip()
                        if not body:
                            break
                        print(f"  {name} detail:   {body[:200]}")
                    if i > 40:
                        break
            return counts["passed"], counts["failed"], counts["skipped"], False

        # Fallback: when output has no parseable summary (e.g. import errors)
        if proc.returncode != 0:
            print(f"  --- {name} raw output (last 30 lines) ---")
            for line in output.splitlines()[-30:]:
                print(f"  {line}")
            print(f"  --- end {name} output ---")
            return 0, 1, 0, False
        return 0, 0, 0, False
    except subprocess.TimeoutExpired:
        return 0, 0, 0, True


# --- Main ---------------------------------------------------------------------

def main() -> None:
    failed_groups: list[str] = []

    for name, test_files in TEST_GROUPS:
        passed, failed, skipped, timed_out = _run_group(name, test_files)
        if timed_out:
            print(f"[⚠️] {name}: TIMEOUT after {TIMEOUT}s")
            failed_groups.append(name)
        else:
            icon = "✅" if failed == 0 else "❌"
            print(f"[{icon}] {name}: {passed} passed, {failed} failed, {skipped} skipped")
            if failed > 0:
                failed_groups.append(name)

    print()
    if failed_groups:
        print(f"❌ {len(failed_groups)} group(s) FAILED: {', '.join(failed_groups)}")
        sys.exit(1)
    print("✅ All groups passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
