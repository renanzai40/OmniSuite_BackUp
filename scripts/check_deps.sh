#!/bin/bash
# =============================================================================
# Omni Suite — Dependency Doctor (read-only health check)
# =============================================================================
# Exits 0 on all-pass or only-warns, 1 on any hard failure.
# Usage:
#   bash scripts/check_deps.sh
#   OMNI_DOCTOR_SKIP_PDF=1 bash scripts/check_deps.sh   # skip WeasyPrint check
# =============================================================================

set -euo pipefail

# ── Colour helpers (mirrors setup_dev.sh) ────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[ERR]${NC}   %s\n" "$*"; }
info()  { printf "${CYAN}[INFO]${NC}  %s\n" "$*"; }

FAILURES=0
WARNINGS=0

# ── Resolve project root ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ═══════════════════════════════════════════════════════════════════════════════
# Check 1 — Python version >= 3.13
# ═══════════════════════════════════════════════════════════════════════════════
# 解释器统一经 scripts/pre_commit_python.sh 解析，不写裸 `python3`：
# 在 Windows/Git Bash 下，裸 `python3` 命中 Microsoft Store 的 execution-alias
# 占位程序（不执行任何代码、直接返回 49），而本脚本是 `set -e`，于是**在第一条
# 检查中途静默退出**——既没有 [ERR] 也没有退出原因（实测 2026-09-17：`make
# doctor` 打一行 [INFO] 后 exit 49）。解析器按「项目 venv（POSIX `bin/` +
# Windows `Scripts/` 两种布局）→ 系统 python/python3/py」逐个真跑 `-c ''` 探测
# （存在 ≠ 可执行）。PYTHON_BIN 仍可显式覆盖。
# 注：scripts/setup_dev.sh 不必这样改——它在 Windows 上有 OS 守卫，会先报错退出。
info "Checking Python version …"
if [ -n "${PYTHON_BIN:-}" ]; then
    PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
else
    PY_VERSION="$(bash "$SCRIPT_DIR/pre_commit_python.sh" -c \
        'import sys; print("%d.%d.%d" % sys.version_info[:3])' || true)"
fi
if [ -z "$PY_VERSION" ]; then
    err "No runnable Python interpreter found (project venvs and python/python3/py all failed)."
    err "  → Linux/macOS/WSL: bash scripts/setup_dev.sh"
    err "  → Native Windows: powershell -ExecutionPolicy Bypass -File scripts/setup_dev.ps1"
    err "  → Or point PYTHON_BIN at a Python >= 3.13."
    FAILURES=$((FAILURES + 1))
else
    PY_MAJOR="${PY_VERSION%%.*}"
    PY_MINOR="${PY_VERSION#*.}"
    PY_MINOR="${PY_MINOR%%.*}"
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 13 ]; }; then
        err "Python >= 3.13 required, found $PY_VERSION"
        FAILURES=$((FAILURES + 1))
    else
        ok "Python $PY_VERSION"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 2 — LLM API keys (at least one required for real LLM work)
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking LLM API keys …"
if [ "${OMNI_TEST_FAKE_LLM:-}" = "1" ]; then
    ok "LLM API key: skipped (OMNI_TEST_FAKE_LLM=1)"
else
    KEYS_SET=0
    for key_name in ARK_API_KEY ZHIPU_API_KEY NVIDIA_NIM_API_KEY; do
        if [ -n "${!key_name:-}" ]; then
            KEYS_SET=$((KEYS_SET + 1))
        fi
    done
    if [ "$KEYS_SET" -eq 0 ]; then
        err "No LLM API keys found. Set at least one of: ARK_API_KEY, ZHIPU_API_KEY, NVIDIA_NIM_API_KEY"
        err "  → Or set OMNI_TEST_FAKE_LLM=1 for testing."
        FAILURES=$((FAILURES + 1))
    else
        ok "LLM API key(s): $KEYS_SET set"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 3 — Pandoc (required for DOCX/ODT/EPUB/RTF/ICML output)
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking pandoc …"
if [ "${OMNI_TEST_FAKE_PANDOC:-}" = "1" ]; then
    ok "pandoc: skipped (OMNI_TEST_FAKE_PANDOC=1)"
elif command -v pandoc &>/dev/null; then
    PANDOC_VER="$(pandoc --version 2>/dev/null | head -1 || echo "unknown")"
    ok "pandoc: $(command -v pandoc) ($PANDOC_VER)"
elif [ -x "$PROJECT_ROOT/.venv_ol/bin/pandoc" ]; then
    ok "pandoc: $PROJECT_ROOT/.venv_ol/bin/pandoc (install pypandoc-binary)"
else
    warn "pandoc: not found. Install via: sudo apt-get install pandoc (Linux) or brew install pandoc (macOS)"
    warn "  → ORF apply-md requires pandoc for DOCX/ODT/EPUB/RTF/ICML output."
    WARNINGS=$((WARNINGS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 4 — WeasyPrint system libs (for PDF)
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking WeasyPrint system libs …"
if [ "${OMNI_DOCTOR_SKIP_PDF:-}" = "1" ]; then
    ok "WeasyPrint libs: skipped (OMNI_DOCTOR_SKIP_PDF=1)"
else
    OS_NAME="$(uname -s)"
    PDF_DEPS_OK=true

    case "$OS_NAME" in
        Linux*)
            for lib in libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0; do
                if ldconfig -p 2>/dev/null | grep -q "$lib"; then
                    :  # found
                else
                    PDF_DEPS_OK=false
                    warn "WeasyPrint lib '$lib' not found (ldconfig -p)"
                fi
            done
            ;;
        Darwin*)
            for lib in pango cairo gdk-pixbuf-2.0; do
                if pkg-config --exists "$lib" 2>/dev/null; then
                    :  # found
                else
                    PDF_DEPS_OK=false
                    warn "WeasyPrint pkg '$lib' not found (pkg-config)"
                fi
            done
            ;;
        *)
            warn "WeasyPrint check: unsupported OS '$OS_NAME' — skipping"
            WARNINGS=$((WARNINGS + 1))
            PDF_DEPS_OK=true
            ;;
    esac

    if [ "$PDF_DEPS_OK" = true ]; then
        ok "WeasyPrint system libs: found"
    else
        warn "WeasyPrint system libs: some missing (PDF output may fail)"
        warn "  → Set OMNI_DOCTOR_SKIP_PDF=1 to silence this check."
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 5 — md2pptx / .NET (for PPTX quality)
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking PPTX toolchain …"
MD2PPTX_FOUND=false
if command -v md2pptx &>/dev/null; then
    ok "md2pptx: $(command -v md2pptx)"
    MD2PPTX_FOUND=true
fi
if command -v dotnet &>/dev/null; then
    ok "dotnet: $(command -v dotnet)"
    MD2PPTX_FOUND=true
fi
if [ "$MD2PPTX_FOUND" = false ]; then
    warn "md2pptx/dotnet: not found. PPTX via pandoc fallback (lower quality)."
    warn "  → Install: dotnet tool install --global md2pptx"
    WARNINGS=$((WARNINGS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 6 — MCP server allowed dirs (for OPP/ORF MCP deployment)
# ═══════════════════════════════════════════════════════════════════════════════
info "Checking MCP server config …"
MCP_WARN=false
if [ -z "${OPP_MCP_ALLOWED_DIRS:-}" ]; then
    warn "OPP_MCP_ALLOWED_DIRS: not set (fine for CLI use, required for MCP server)"
    MCP_WARN=true
fi
if [ -z "${ORF_MCP_ALLOWED_DIRS:-}" ]; then
    warn "ORF_MCP_ALLOWED_DIRS: not set (fine for CLI use, required for MCP server)"
    MCP_WARN=true
fi
if [ -z "${OL_ALLOWED_DIRECTORIES:-}" ]; then
    # OL uses a different var name; warn only if running MCP
    :  # OL MCP has a separate config path — optional check
fi
if [ "$MCP_WARN" = false ]; then
    ok "MCP allowed dirs: configured"
else
    WARNINGS=$((WARNINGS + 1))
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Check 7 — Repo structure (suite self-check)
# ═══════════════════════════════════════════════════════════════════════════════
# The OPP/OL/ORF sub-repos are now separate git repos (since 2026-06-24),
# not submodules of this suite. This check validates that the suite's own
# key files are present rather than expecting sub-repo pyproject.toml files.
info "Checking repo structure …"
SUITE_FILES_OK=true
for f in "pyproject.toml" "Makefile" "scripts/setup_dev.sh" "scripts/check_deps.sh" "AGENTS.md"; do
    if [ ! -f "$PROJECT_ROOT/$f" ]; then
        err "  Suite file missing: $f"
        SUITE_FILES_OK=false
    fi
done
if [ "$SUITE_FILES_OK" = "true" ]; then
    ok "Suite structure: all key files present"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
if [ "$FAILURES" -gt 0 ]; then
    err "FAILED: $FAILURES hard failure(s), $WARNINGS warning(s)"
    exit 1
elif [ "$WARNINGS" -gt 0 ]; then
    warn "PASSED with $WARNINGS warning(s) — review above"
    exit 0
else
    ok "ALL CHECKS PASSED"
    exit 0
fi
