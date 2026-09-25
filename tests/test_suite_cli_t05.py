"""T-05 regression: omni-suite CLI behavior bugs (narrow scope).

Gap register T-05 (``.omo/plans/agent-oriented-gap-register.md`` §4.1) fixes
three agent-facing CLI defects:

1. ``--fake-llm`` must satisfy the LLM env gate — before the fix only
   ``--dry-run``/``--gates-only`` were recognised, so
   ``omni-suite pipeline x --fake-llm`` exited 1 with no provider keys.
2. ``--versions`` must read the repo ``VERSION`` / ``pyproject.toml``, not
   installed importlib metadata (stale after a version bump without reinstall).
3. The missing-key warning must go to **stderr** (agents parse stdout).

Pipeline execution is deliberately NOT exercised here — the unit test drives
``cli._no_llm_needed`` directly and the integration tests are fast CLI
invocations (``--versions`` / ``--help``).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = SUITE_ROOT / "tests" / "production" / "small_fixture.docx"
VERSION_FILE = SUITE_ROOT / "VERSION"

_LLM_KEYS = ("ARK_API_KEY", "ZHIPU_API_KEY", "NVIDIA_NIM_API_KEY")

_MODULE_PYPROJECTS = {
    "opp": "Omni_Pre_Processor/pyproject.toml",
    "ol": "Omni_Localizer/pyproject.toml",
    "orf": "Omni_Re_Formatter/pyproject.toml",
}


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "omni_suite", *args],
        capture_output=True,
        text=True,
        cwd=str(SUITE_ROOT),
        env=env,
        timeout=60,
    )


def _env_without_llm_keys() -> dict[str, str]:
    env = {**os.environ}
    for key in _LLM_KEYS:
        env.pop(key, None)
    env.pop("OMNI_TEST_FAKE_LLM", None)
    return env


def _pyproject_version(rel_path: str) -> str:
    for line in (SUITE_ROOT / rel_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise AssertionError(f"no version in {rel_path}")


def _version_file_value() -> str:
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    raise AssertionError("VERSION file has no value line")


class TestNoLlmNeeded:
    """The gate decision itself — the deliverable's failing-first unit test."""

    def test_fake_llm_means_no_llm_needed(self):
        from omni_suite import cli

        assert cli._no_llm_needed([str(FIXTURE), "--fake-llm"]) is True

    def test_dry_run_means_no_llm_needed(self):
        from omni_suite import cli

        assert cli._no_llm_needed([str(FIXTURE), "--dry-run"]) is True

    def test_gates_only_means_no_llm_needed(self):
        from omni_suite import cli

        assert cli._no_llm_needed([str(FIXTURE), "--gates-only"]) is True

    def test_plain_run_needs_llm(self):
        from omni_suite import cli

        assert cli._no_llm_needed([str(FIXTURE)]) is False


class TestVersionsSourceOfTruth:
    """--versions must match repo VERSION / pyproject, not installed metadata."""

    def test_versions_suite_line_matches_version_file(self):
        result = _run("--versions")
        assert result.returncode == 0, result.stderr
        expected = _version_file_value()
        assert f"omni-suite: {expected}" in result.stdout, result.stdout

    def test_versions_module_lines_match_pyproject(self):
        result = _run("--versions")
        assert result.returncode == 0, result.stderr
        for label, rel in _MODULE_PYPROJECTS.items():
            expected = _pyproject_version(rel)
            assert f"{label}: {expected}" in result.stdout, (
                f"expected '{label}: {expected}'\n{result.stdout}"
            )


class TestWarningGoesToStderr:
    """Agents parse stdout; the missing-key warning must not pollute it."""

    def test_help_warning_is_on_stderr_not_stdout(self):
        result = _run("--help", env=_env_without_llm_keys())
        assert "No LLM provider keys found" in result.stderr, result.stderr
        assert "No LLM provider keys found" not in result.stdout, result.stdout
