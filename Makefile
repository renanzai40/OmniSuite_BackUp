# =============================================================================
# Omni Suite — Developer Makefile
# =============================================================================
#
# Targets:
#   setup         — Full dev environment setup (venv, install, smoke test)
#   test          — Run all CI-mode tests (OPP + OL + ORF + suite e2e)
#   test-quick    — Run root suite only (pytest tests/ -m "not nightly" -q)
#   test-opp      — Run OPP CI-mode tests
#   test-ol       — Run OL CI-mode tests
#   test-orf      — Run ORF CI-mode tests
#   test-contract       — Run CLI + MCP contract tests (Section 7.5 + Phase 4.7)
#   test-contract-cli   — Run CLI --help contract tests only
#   test-contract-mcp   — Run MCP tool-schema contract tests only (21 tools)
#   smoke         — Run contract smoke test
#   lint          — Run ruff + mypy on parent + submodules
#   matrix        — Run full MD matrix via real MCP (165 cells)
#   matrix-subset — Run MD matrix on a single input format
#   validate      — Hermetic validation: tier-1 scenarios + coverage audit
#   validate-nightly — Full validation library (all tiers; needs LLM keys)
#   validate-coverage — Coverage audit only (every live MCP tool scenario-used)
#   clean         — Remove __pycache__, .pytest_cache, build artifacts
#
# =============================================================================

.PHONY: setup test test-quick test-opp test-ol test-orf test-contract test-contract-cli test-contract-mcp test-logs test-metrics test-tracing test-distributed-tracing test-health test-error-scenarios fidelity fidelity-unit fidelity-nightly smoke security-scan lint matrix matrix-subset validate validate-nightly validate-coverage clean clean-artifacts doctor help e2e e2e-help doc-inventory doc-inventory-check entry-check

PYTHON := .venv_ol/bin/python
PYTEST := $(PYTHON) -m pytest
FAKE_ENV := OMNI_TEST_FAKE_LLM=1 OMNI_TEST_FAKE_PANDOC=1
# E2E tests use real LLM calls — never set FAKE_LLM. Still bypass pandoc
# since we only produce text artifacts (no actual DOCX rendering).
E2E_ENV := OMNI_TEST_FAKE_PANDOC=1

help:
	@echo "Omni Suite targets:"
	@echo "  setup         — bash scripts/setup_dev.sh"
	@echo "  doctor        — Run dependency health check (read-only)"
	@echo "  test          — Run all CI-mode tests (OPP + OL + ORF + suite e2e)"
	@echo "  test-quick    — pytest tests/ -m \"not nightly\" -q"
	@echo "  test-opp      — Run OPP CI-mode tests"
	@echo "  test-ol       — Run OL CI-mode tests"
	@echo "  test-orf      — Run ORF CI-mode tests"
	@echo "  test-contract       — Run CLI + MCP contract tests (10 currently PASS)"
	@echo "  test-contract-cli   — Run CLI --help contract tests only (Section 7.5)"
	@echo "  test-contract-mcp   — Run MCP tool-schema contract tests only (21 tools)"
	@echo "  test-logs           — Run structured JSON logging tests (Phase 4.1, OMNI_LOG_FORMAT=json)"
	@echo "  test-metrics        — Run metrics + prometheus wiring tests"
	@echo "  test-tracing        — Run OTel tracing tests (Phase 4.5, OMNI_TRACING_ENABLED=1)"
	@echo "  test-distributed-tracing — Run W3C trace context propagation tests (Phase 4.5)"
	@echo "  test-health         — Spawn MCP servers with /health endpoint, assert 200 OK"
	@echo "  test-error-scenarios — Run the 11 exit-code matrix tests (plan § 6.4)"
	@echo "  fidelity      — Run fidelity scoring on existing Alice ch1 translation; gate on char_cosine >= 0.9 (CI gate)"
	@echo "  fidelity-unit — Run FidelityScorer unit tests only (no scoring)"
	@echo "  fidelity-nightly — Regenerate candidate via real LLM, then score (requires ZHIPU_API_KEY in .env)"
	@echo "  smoke         — Run contract smoke test"
	@echo "  e2e           — Run real-LLM E2E pipeline tests (19 tests, nightly)"
	@echo "  e2e-help      — Show E2E setup instructions"
	@echo "  security-scan — Run gitleaks + bandit + pip-audit"
	@echo "  lint          — ruff check + mypy on parent + submodules"
	@echo "  matrix        — Run full MD matrix (165 cells, ~3min, real MCP)"
	@echo "  matrix-subset FMT=<fmt> — Run MD matrix on one input format (e.g. FMT=docx)"
	@echo "  validate      — Hermetic validation: tier-1 scenarios + coverage audit (0 missing)"
	@echo "  validate-nightly — Full validation library (all tiers; requires real LLM keys)"
	@echo "  validate-coverage — Coverage audit only (exit 1 while any MCP tool is missing)"
	@echo "  doc-inventory          Regenerate docs/dev/doc-inventory.md"
	@echo "  doc-inventory-check    Verify doc freshness (exit 0 = clean)"
	@echo "  entry-check            Fail-loud module-entry consistency (symlink/.git/.pth)"
	@echo "  clean         — Remove __pycache__, .pytest_cache, build artifacts"

setup:
	bash scripts/setup_dev.sh

doctor:
	bash scripts/check_deps.sh
	@bash scripts/pre_commit_python.sh scripts/check_module_entry.py

test: test-opp test-ol test-orf
	$(FAKE_ENV) $(PYTEST) tests/ -m "not nightly" --tb=short -q --no-header

test-quick:
	$(FAKE_ENV) $(PYTEST) tests/ -m "not nightly" -q

test-opp:
	$(FAKE_ENV) $(PYTEST) Omni_Pre_Processor/tests/ -m "not nightly" --tb=short -q --no-header

test-ol:
	$(FAKE_ENV) $(PYTEST) Omni_Localizer/tests/ -m "not nightly" --tb=short -q --no-header

test-orf:
	$(FAKE_ENV) $(PYTEST) Omni_Re_Formatter/tests/ --tb=short -q --no-header

test-contract:
	$(FAKE_ENV) $(PYTEST) tests/contract/ --tb=short -v

test-contract-cli:
	$(FAKE_ENV) $(PYTEST) tests/contract/test_cli_help.py --tb=short -v

test-contract-mcp:
	$(FAKE_ENV) $(PYTEST) tests/contract/test_mcp_schemas.py --tb=short -v

test-coverage:
	$(FAKE_ENV) $(PYTEST) tests/ -m "not nightly" --tb=short -q --no-header --cov=Omni_Pre_Processor/src --cov=Omni_Localizer/src --cov=Omni_Re_Formatter/src --cov-report=term-missing --cov-report=html:test_artifacts/coverage-html --cov-fail-under=80

test-metrics:
	$(FAKE_ENV) $(PYTEST) tests/observability/test_metrics.py tests/observability/test_metrics_wiring.py Omni_Pre_Processor/tests/mcp/test_opp_metrics.py Omni_Localizer/tests/test_ol_metrics.py Omni_Re_Formatter/tests/test_orf_metrics.py -v --tb=short

test-logs:
	$(FAKE_ENV) OMNI_LOG_FORMAT=json $(PYTEST) tests/observability/test_json_logging.py tests/observability/test_request_id_opp.py -v --tb=short

test-tracing:
	$(FAKE_ENV) OMNI_TRACING_ENABLED=1 $(PYTEST) tests/observability/tracing_health/test_tracing.py -v --tb=short --timeout=30

test-distributed-tracing:
	$(FAKE_ENV) OMNI_TRACING_ENABLED=1 $(PYTEST) tests/distributed_tracing/test_distributed_tracing.py -v --tb=short --timeout=120

test-health:
	$(FAKE_ENV) $(PYTEST) tests/observability/tracing_health/test_health.py -v --tb=short --timeout=60

test-error-scenarios:
	$(FAKE_ENV) $(PYTEST) tests/error_scenarios/ -v --tb=short --timeout=30

fidelity:
	$(PYTHON) tests/fidelity/run_fidelity.py

fidelity-unit:
	$(FAKE_ENV) $(PYTEST) tests/fidelity/test_fidelity_scorer.py -v --tb=short

fidelity-nightly:
	@test -n "$$ZHIPU_API_KEY" || (echo "FAIL: ZHIPU_API_KEY not set; fidelity-nightly requires real LLM"; exit 1)
	@echo "fidelity-nightly: regenerate candidate via Zhipu (para-by-para, ~30 LLM calls)"
	@echo "Run: .venv_ol/bin/python tests/fidelity/regenerate_candidate.py"
	@.venv_ol/bin/python tests/fidelity/regenerate_candidate.py
	$(MAKE) fidelity

security-scan:
	@echo "Running security scans (gitleaks + bandit + pip-audit)..."
	@command -v gitleaks >/dev/null 2>&1 && gitleaks detect --no-banner || echo "  [skip] gitleaks not installed"
	@command -v bandit >/dev/null 2>&1 && .venv_ol/bin/python -m bandit -r scripts/ tests/observability/ tests/error_scenarios/ tests/contract/ -ll || echo "  [skip] bandit not installed"
	@command -v pip-audit >/dev/null 2>&1 && (cd .venv_ol && bin/pip-audit 2>&1 | tail -30) || echo "  [skip] pip-audit not installed"
	@echo "See docs/SECURITY_AUDIT.md for the full audit roadmap."
	@echo "See docs/SECURITY_FINDINGS.md for the latest CVE list."

smoke:
	$(FAKE_ENV) $(PYTEST) tests/test_pipeline_contract_smoke.py --tb=short -v

# ---------------------------------------------------------------------------
# E2E nightly tests — run the full OPP → OL → ORF pipeline with REAL LLMs.
# These are excluded from `make test` (which uses FAKE_LLM) and require at
# least one API key. Without a key, tests are SKIPPED (not failed) so
# developers can run `make e2e` without polluting CI.
# ---------------------------------------------------------------------------
e2e:
	@if [ -z "$$ARK_API_KEY" ] && [ -z "$$ZHIPU_API_KEY" ] && [ -z "$$NVIDIA_NIM_API_KEY" ]; then \
		echo ""; \
		echo "  No real LLM API keys detected."; \
		echo ""; \
		echo "  E2E tests require at least one of:"; \
		echo "    - ARK_API_KEY        (Volcengine Ark, priority 1)"; \
		echo "    - ZHIPU_API_KEY      (Zhipu BigModel, priority 2)"; \
		echo "    - NVIDIA_NIM_API_KEY (NVIDIA NIM, priority 3)"; \
		echo ""; \
		echo "  Set them in Omni_Localizer/.env or export in your shell."; \
		echo "  Run 'make e2e-help' for detailed setup instructions."; \
		echo ""; \
		echo "  All 19 tests will SKIP gracefully (not fail)."; \
		echo ""; \
	fi
	$(E2E_ENV) $(PYTEST) tests/test_e2e_real_llm.py -v -m "nightly" --tb=short

e2e-help:
	@echo ""
	@echo "E2E Nightly Tests — Setup Guide"
	@echo "================================"
	@echo ""
	@echo "These tests run the full OPP→OL→ORF pipeline with REAL LLM calls."
	@echo "They are NOT run by 'make test' (which uses FAKE_LLM)."
	@echo ""
	@echo "Prerequisites:"
	@echo "  1. Python 3.13+ installed (make doctor to verify)"
	@echo "  2. At least one of these API keys in the environment"
	@echo "     (canonical OL model pool, see CONTRACT.md):"
	@echo "       ARK_API_KEY        (Volcengine Ark, ark-code-latest)"
	@echo "       ZHIPU_API_KEY      (Zhipu BigModel, glm-4.7-flash)"
	@echo "       NVIDIA_NIM_API_KEY (NVIDIA NIM, minimaxai/minimax-m3)"
	@echo ""
	@echo "Setup:"
	@echo "  1. Copy Omni_Localizer/.env.example to Omni_Localizer/.env (if needed)"
	@echo "  2. Add your API key(s) to .env"
	@echo "  3. Run: make e2e"
	@echo ""
	@echo "What you get:"
	@echo "  - 19 tests across 4 tiers (per-component smoke, full E2E, LQA, formats)"
	@echo "  - Full OPP→OL→ORF pipeline with REAL translations"
	@echo "  - Estimated runtime: 25-40 minutes (depends on LLM latency)"
	@echo ""
	@echo "Options:"
	@echo "  make e2e              # Run all nightly tests (skips if no key)"
	@echo "  make e2e-help         # Show this help"
	@echo ""

lint: smoke
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy . --no-incremental || true

matrix:
	$(FAKE_ENV) $(PYTHON) scripts/mcp_matrix_verifier.py --out-dir /tmp/mcp-matrix-full --path-filter md --corpus minimal

matrix-subset:
	@test -n "$(FMT)" || (echo "Usage: make matrix-subset FMT=docx"; exit 1)
	$(FAKE_ENV) $(PYTHON) scripts/mcp_matrix_verifier.py --out-dir /tmp/mcp-matrix-$(FMT) --path-filter md --subset $(FMT) --corpus minimal

# ---------------------------------------------------------------------------
# Validation framework (plan todo 25, D7/D11) — agent-agnostic scenarios.
# Strict no-mocks: NEVER set OMNI_TEST_FAKE_LLM here (D4). OMNI_RATE_LIMIT_RPM=0
# disables the shared OPP/OL/ORF token bucket for full runs (infra, not a mock).
# ---------------------------------------------------------------------------
validate:
	OMNI_RATE_LIMIT_RPM=0 $(PYTHON) scripts/validation/run_validation.py --tier 1
	$(PYTHON) scripts/validation/coverage_audit.py

validate-nightly:
	@echo "validate-nightly: full library (all tiers) — requires real LLM keys;"
	@echo "keyed scenarios report 'unconfigured' (never fake-green) without them."
	OMNI_RATE_LIMIT_RPM=0 $(PYTHON) scripts/validation/run_validation.py
	$(PYTHON) scripts/validation/validation_report.py

validate-coverage:
	$(PYTHON) scripts/validation/coverage_audit.py

doc-inventory:
	@bash scripts/pre_commit_python.sh scripts/doc_inventory.py

doc-inventory-check:
	@bash scripts/pre_commit_python.sh scripts/doc_inventory.py --check

entry-check:
	@bash scripts/pre_commit_python.sh scripts/check_module_entry.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info

clean-artifacts:
	rm -rf mcp_resources/ resources/ logs/ final-out/ test_artifacts/ validation-runs/
