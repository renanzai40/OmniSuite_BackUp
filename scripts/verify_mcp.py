#!/usr/bin/env python3
"""MCP smoke test orchestrator for Omni Suite.

Runs the comprehensive MCP smoke test suite and reports per-module results.
Exit 0 only if all MCP tests pass.
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Individual MCP test categories within test_mcp_smoke.py
MCP_GROUPS: list[tuple[str, str]] = [
    ("OPP MCP",  "TestMCPSmokeOPP"),
    ("OL MCP",   "TestMCPSmokeOL"),
    ("ORF MCP",  "TestMCPSmokeORF"),
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

TIMEOUT = 300  # 5 min per group


def main() -> None:
    failed: list[str] = []
    for name, marker in MCP_GROUPS:
        cmd = [sys.executable, "-m", "pytest",
               "tests/test_mcp_smoke.py", f"-k={marker}",
               "-q", "--tb=line", "--no-header"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=TIMEOUT, env=ENV, cwd=PROJECT_ROOT)
            output = proc.stdout + "\n" + proc.stderr
            # Parse summary line like "12 passed, 0 failed in 45.23s"
            for line in output.splitlines():
                if "passed" in line and "failed" in line:
                    icon = "✅" if "0 failed" in line else "❌"
                    print(f"  {icon} {name}: {line.strip()}")
                    if "0 failed" not in line:
                        failed.append(name)
                    break
            else:
                # Fallback: use return code
                icon = "✅" if proc.returncode == 0 else "❌"
                print(f"  {icon} {name}: exit {proc.returncode}")
                if proc.returncode != 0:
                    failed.append(name)
        except subprocess.TimeoutExpired:
            print(f"  [⚠️] {name}: TIMEOUT after {TIMEOUT}s")
            failed.append(name)

    print()
    if failed:
        print(f"❌ MCP groups FAILED: {', '.join(failed)}")
        sys.exit(1)
    print("✅ All MCP tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
