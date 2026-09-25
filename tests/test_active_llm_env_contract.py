"""Regression lock: the active LLM env contract is the canonical trio.

The ARK/ZHIPU/NVIDIA model-pool migration (OL ``config/default.yaml``) made
three provider keys the only real-LLM credentials the suite reads:

* ``ARK_API_KEY``        — priority 1 (``ark-code-latest``)
* ``ZHIPU_API_KEY``      — priority 2 (``glm-4.7-flash``)
* ``NVIDIA_NIM_API_KEY`` — priority 3 (``minimaxai/minimax-m3``)

Two coupled *active* surfaces must agree with that pool, or the real-LLM
gates silently rot while every other test stays green:

1. ``omni_suite.cli._validate_env`` — the suite CLI's production env gate.
   It must accept every canonical key (notably ``ARK_API_KEY``, which was
   missing) and must keep failing closed when no canonical key is present.
   A retired provider key must NOT satisfy the gate.
2. The real-LLM CI workflows (``validation.yml`` nightly, ``e2e-tests.yml``,
   ``fidelity.yml``) must expose the same canonical keys and must not gate on
   retired providers (Agnes / OpenCode Go / MiniMax / Baidu / OpenAI).

Behavior-first: the CLI cases drive the real gate function, and the workflow
cases read the active workflow files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SUITE_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = SUITE_ROOT / ".github" / "workflows"

# The canonical OL model-pool provider keys (single source of truth:
# Omni_Localizer/config/default.yaml).
CANONICAL_KEYS = ("ARK_API_KEY", "ZHIPU_API_KEY", "NVIDIA_NIM_API_KEY")

# Providers retired by the migration — a workflow or the CLI gate must not
# treat any of these as the active credential.
RETIRED_KEYS = (
    "AGNES_API_KEY",
    "OPENCODE_GO_KEY",
    "OPENCODE_GO_BASE_URL",
    "MINIMAX_API_KEY",
    "MINIMAX_BASE_URL",
    "BAIDU_API_KEY",
    "BAIDU_BASE_URL",
    "BAIDU_SECRET_KEY",
    "OPENAI_API_KEY",
)

# Word-boundary token scan: avoids matching a retired name embedded inside a
# longer identifier (e.g. ``OMNI_OPENAI_API_KEY`` does not match
# ``OPENAI_API_KEY`` because ``_`` is a word character).
_ENV_TOKEN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

REAL_LLM_WORKFLOWS = ("validation.yml", "e2e-tests.yml", "fidelity.yml")


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every known provider key so the gate sees a clean slate.

    ``tests/conftest.py`` installs dummy provider keys at import time; wipe
    both canonical and retired names so each test controls the full set.
    """
    for key in (*CANONICAL_KEYS, *RETIRED_KEYS):
        monkeypatch.delenv(key, raising=False)


class TestSuiteCliKeyDetector:
    """``omni_suite.cli._validate_env`` — the production LLM env gate."""

    def test_detector_is_exactly_the_canonical_trio(self):
        from omni_suite import cli

        assert tuple(cli._LLM_API_KEYS) == CANONICAL_KEYS

    def test_detector_does_not_recognise_retired_providers(self):
        from omni_suite import cli

        overlap = set(RETIRED_KEYS) & set(cli._LLM_API_KEYS)
        assert not overlap, f"detector still recognises retired keys: {sorted(overlap)}"

    def test_full_canonical_trio_satisfies_the_real_llm_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Setting exactly the canonical trio must open the gate.

        RED before the fix: the detector still expected the retired
        AGNES/OpenCode keys, so the canonical trio alone left keys
        "unset" and the gate exited 1.
        """
        from omni_suite import cli

        _clear_llm_env(monkeypatch)
        for key in CANONICAL_KEYS:
            monkeypatch.setenv(key, "sk-regression-test")

        cli._validate_env(require_llm=True)  # must not raise SystemExit

    def test_no_canonical_key_fails_closed(self, monkeypatch: pytest.MonkeyPatch):
        from omni_suite import cli

        _clear_llm_env(monkeypatch)
        with pytest.raises(SystemExit) as excinfo:
            cli._validate_env(require_llm=True)
        assert excinfo.value.code == 1

    def test_retired_provider_keys_alone_do_not_satisfy_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Retired keys (Agnes / OpenCode Go) must not open the gate."""
        from omni_suite import cli

        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "sk-stale")
        monkeypatch.setenv("OPENCODE_GO_KEY", "sk-stale")
        with pytest.raises(SystemExit) as excinfo:
            cli._validate_env(require_llm=True)
        assert excinfo.value.code == 1


class TestRealLlmWorkflowEnvContract:
    """Real-LLM CI workflows must gate on the canonical trio only."""

    @pytest.mark.parametrize("filename", REAL_LLM_WORKFLOWS)
    def test_workflow_exports_every_canonical_key(self, filename: str):
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        present = set(_ENV_TOKEN.findall(text))
        missing = [key for key in CANONICAL_KEYS if key not in present]
        assert not missing, (
            f"{filename} does not expose canonical LLM env keys: {missing}"
        )

    @pytest.mark.parametrize("filename", REAL_LLM_WORKFLOWS)
    def test_workflow_does_not_gate_on_retired_providers(self, filename: str):
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        present = set(_ENV_TOKEN.findall(text))
        stale = [key for key in RETIRED_KEYS if key in present]
        assert not stale, (
            f"{filename} still gates on retired LLM providers: {stale}"
        )
