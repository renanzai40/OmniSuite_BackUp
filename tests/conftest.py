"""Pytest configuration and shared fixtures for Omni_Suite E2E tests.

This module provides fixtures that enable end-to-end testing of the complete
OPP → OL → ORF localization pipeline.
"""

import os
import re
import sys
import shutil
import tempfile
import zipfile
import json
import types
from datetime import datetime
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest
from docx import Document


# 2026-06-17 round 12: skip litellm's import-time network fetch.
# ol_pool.router also setdefaults these, but conftest runs first.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DISABLE_LITELLM_TELEMETRY", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")
# 2026-06-20: ORF MCP PathValidator allowlist (must include test dirs).
# Without this, every ORF MCP tool call in tests returns PATH_NOT_ALLOWED.
# 2026-09-17 (ADR 0007): build the value with ``os.pathsep`` and real platform
# dirs. The old literal "/tmp:/mnt/d/贯维/Omni_Suite" only ever "worked" on
# Windows as an accident of the previous "always split on ':'" parser (which
# also mangled every Windows drive-letter path); OPP/ORF config now follow the
# platform separator, so the fixture must be platform-correct too. On POSIX the
# produced string is byte-identical to the old literal.
_SUITE_ROOT = Path(__file__).resolve().parents[1]
# MCP path allowlists. All three MCP servers are fail-CLOSED, so the suite
# must provide an explicit baseline instead of relying on whichever test ran
# first to leave one in the environment (e2e#56: an accidental
# ``MCP_ALLOWED_DIRECTORIES=/tmp`` set by tests/contract/test_contract_documentation.py
# used to be the only reason OL/OPP path tools worked in the combined run).
# Each module's own variable is used so the unified
# ``MCP_ALLOWED_DIRECTORIES`` stays free for tests that assert fail-closed.
_MCP_ALLOWED_DIRS = os.pathsep.join([tempfile.gettempdir(), str(_SUITE_ROOT)])
for _var in ("ORF_MCP_ALLOWED_DIRS", "OPP_MCP_ALLOWED_DIRS", "OL_MCP_ALLOWED_DIRS"):
    os.environ.setdefault(_var, _MCP_ALLOWED_DIRS)

# 2026-06-24: Dummy API keys (same set as Omni_Localizer/tests/conftest.py).
# FAKE_LLM mode creates _FakeModelPool and ignores these values; config
# validators only check that the env vars are non-empty. Without these, OL
# config validation aborts at import time and the OL MCP server fails to start.
_DUMMY_API_KEYS = {
    "ARK_API_KEY": "sk-dummy",
    "ZHIPU_API_KEY": "sk-dummy",
    "AGNES_API_KEY": "sk-dummy",
    "NVIDIA_NIM_API_KEY": "nvapi-dummy",
    "BAIDU_API_KEY": "sk-dummy",
    "BAIDU_SECRET_KEY": "sk-dummy",
    "OPENAI_API_KEY": "sk-dummy",
    "ANTHROPIC_API_KEY": "sk-dummy",
    "MINIMAX_API_KEY": "sk-dummy",
    "MINIMAX_BASE_URL": "http://localhost:8080/v1",
    "OPENCODE_GO_KEY": "sk-dummy",
    "OPENCODE_GO_BASE_URL": "http://localhost:8080/v1",
}
for _k, _v in _DUMMY_API_KEYS.items():
    os.environ.setdefault(_k, _v)


# =============================================================================
# Heavy-import blocker (ported from Omni_Localizer/tests/conftest.py)
# =============================================================================
# Several MCP test paths transitively import litellm, torch, transformers,
# sentence_transformers, keybert, yake, span_aligner via ol_mcp → ol →
# ol_pool / ol_terminology. These take 30-90s+ to import and aren't needed
# for the MCP smoke contract (FAKE_LLM seam bypasses all LLM calls). Without
# this blocker, `import ol_mcp` hangs for the full pytest-timeout window and
# the OL/ORF smoke tests fail with "Failed: Timeout" (issue #1: 28/30 fail).
#
# The mechanism: pre-populate sys.modules with lightweight stubs and use a
# meta_path blocker for submodules. Tests that need the real modules patch
# them explicitly (see tests/test_mcp_smoke.py — it uses the in-process
# fastmcp Client, not real LLM calls, so the stubs are sufficient).
#
# Ported verbatim from Omni_Localizer/tests/conftest.py (E2E-74 litellm stub
# fix from OL 0.4.6). Keeping both copies in sync is documented in
# Omni_Localizer/AGENTS.md → "Env vars" + "Tests" sections.


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        cls = type(name, (), {})
        try:
            object.__setattr__(self, name, cls)
        except (AttributeError, TypeError):
            pass
        return cls


def _make_stub(name, attrs=None):
    mod = _StubModule(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    return mod


_LITELLM_ATTRS = {
    "Router": type("Router", (), {}),
    "disable_model_name_normalization": False,
}
_LITELLM_EXC_ATTRS = {
    "AuthenticationError": type("AuthenticationError", (Exception,), {}),
    "RateLimitError": type("RateLimitError", (Exception,), {}),
    "Timeout": type("Timeout", (Exception,), {}),
}
_LITELLM_TYPES_ROUTER_ATTRS = {
    "RouterRateLimitError": type("RouterRateLimitError", (Exception,), {}),
}
_TORCH_CUDA_ATTRS = {"is_available": (lambda: False)}
_TORCH_ATTRS = {
    "cuda": None,
    "device": (lambda *a, **k: "cpu"),
    "float32": "float32",
    "no_grad": type("_NoGrad", (), {
        "__enter__": lambda s: None,
        "__exit__": lambda s, *a: None,
    }),
}
_TRANSFORMERS_ATTRS = {
    "AutoConfig": type("AutoConfig", (), {
        "from_pretrained": classmethod(lambda cls, *a, **k: type("_FakeConfig", (), {})()),
    }),
    "AutoTokenizer": type("AutoTokenizer", (), {
        "from_pretrained": classmethod(lambda cls, *a, **k: type("_FakeTokenizer", (), {})()),
    }),
    "AutoModel": type("AutoModel", (), {
        "from_pretrained": classmethod(
            lambda cls, *a, **k: type("_FakeModel", (), {
                "eval": lambda s: None,
                "to": lambda s, *a, **k: None,
                "__call__": lambda s, *a, **k: None,
            })(),
        ),
    }),
}
_SENTENCE_TRANSFORMER_ATTRS = {
    "SentenceTransformer": (lambda *a, **k: None),
}
_SPAN_ALIGNER_ATTRS = {
    "SpanProjector": type("SpanProjector", (), {
        "project": lambda self, text, *a, **k: text,
        "align": lambda self, *a, **k: [],
    }),
    "align_spans": (lambda *a, **k: []),
}
_TYPER_ATTRS = {
    "Typer": type("_TyperAppStub", (), {
        "__init__": lambda s, *a, **k: None,
        "command": lambda s, *a, **k: (lambda f: f),
        "callback": lambda s, *a, **k: (lambda f: f),
        "add_typer": lambda s, *a, **k: None,
        "__call__": lambda s, *a, **k: (lambda f: f),
    }),
    "Option": (lambda *a, **k: None),
    "Argument": (lambda *a, **k: None),
    "BadParameter": type("BadParameter", (Exception,), {"message": ""}),
    "Exit": type("Exit", (Exception,), {}),
    "echo": lambda *a, **k: None,
    "run": lambda f: f,
    "style": lambda x, **k: x,
}

sys.modules.setdefault("litellm", _make_stub("litellm", _LITELLM_ATTRS))
_litellm_stub = sys.modules["litellm"]
if not hasattr(_litellm_stub, "__path__"):
    _litellm_stub.__path__ = []
sys.modules.setdefault(
    "litellm.exceptions", _make_stub("litellm.exceptions", _LITELLM_EXC_ATTRS),
)
sys.modules.setdefault(
    "sentence_transformers",
    _make_stub("sentence_transformers", _SENTENCE_TRANSFORMER_ATTRS),
)
torch_stub = sys.modules.setdefault("torch", _make_stub("torch", _TORCH_ATTRS))
torch_cuda_stub = _make_stub("torch.cuda", _TORCH_CUDA_ATTRS)
sys.modules.setdefault("torch.cuda", torch_cuda_stub)
torch_stub.cuda = torch_cuda_stub
sys.modules.setdefault("transformers", _make_stub("transformers", _TRANSFORMERS_ATTRS))
sys.modules.setdefault("span_aligner", _make_stub("span_aligner", _SPAN_ALIGNER_ATTRS))
for _heavy in ("keybert", "yake"):
    sys.modules.setdefault(_heavy, _make_stub(_heavy))
sys.modules.setdefault("typer", _make_stub("typer", _TYPER_ATTRS))


_BLOCKED_TOPS = frozenset({
    "litellm", "torch", "transformers",
    "sentence_transformers", "keybert", "yake",
    "span_aligner", "typer",
})

_PRESET_BY_NAME = {
    "litellm": _LITELLM_ATTRS,
    "litellm.exceptions": _LITELLM_EXC_ATTRS,
    "litellm.types.router": _LITELLM_TYPES_ROUTER_ATTRS,
    "sentence_transformers": _SENTENCE_TRANSFORMER_ATTRS,
    "torch.cuda": _TORCH_CUDA_ATTRS,
    "transformers": _TRANSFORMERS_ATTRS,
    "span_aligner": _SPAN_ALIGNER_ATTRS,
    "typer": _TYPER_ATTRS,
}


class _HeavyImportBlocker:
    """Block heavy imports (litellm, torch, etc.) by returning stub specs.

    Inserted at sys.meta_path[0] so it runs before any other finder. When
    a real import would happen for a blocked module, we return a stub
    spec instead — this prevents the 30-90s+ import chain in
    `litellm.types.secret_managers.main` (the deepest hot path) and
    similar hangs in `transformers` / `torch`.
    """

    def find_spec(self, name, path, target=None):
        top = name.split(".")[0]
        if name in _BLOCKED_TOPS or top in _BLOCKED_TOPS:
            return ModuleSpec(name, self)
        return None

    def create_module(self, spec):
        return _StubModule(spec.name)

    def exec_module(self, module):
        if module.__name__ in _PRESET_BY_NAME:
            for k, v in _PRESET_BY_NAME[module.__name__].items():
                setattr(module, k, v)
        # Stubbed submodules of a blocked top-level package must look
        # like packages so Python can walk further into them. Without
        # ``__path__``, ``from litellm.types.router import X`` would
        # fail because the stubbed ``litellm.types`` is a Module, not
        # a Package.
        if "." in module.__name__ and not hasattr(module, "__path__"):
            module.__path__ = []


sys.meta_path.insert(0, _HeavyImportBlocker())


_VENV_BIN = Path(__file__).resolve().parents[1] / ".venv_ol" / "bin"
if _VENV_BIN.exists() and _VENV_BIN.is_dir():
    _venv_bin_str = str(_VENV_BIN)
    if _venv_bin_str not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _venv_bin_str + os.pathsep + os.environ.get("PATH", "")


# =============================================================================
# Test artifact directory — persistent across runs, NOT in pytest's tmp
# =============================================================================

_ARTIFACTS_ROOT = Path(__file__).resolve().parents[1] / "test_artifacts"


@pytest.fixture
def artifact_dir(request) -> Path:
    """Per-test persistent artifact directory under test_artifacts/runs/.

    Returns a path like:
        test_artifacts/runs/2026-06-03T18-00-00/test_lqa_xliff_final_docx/

    The session-level subdir is timestamped (one per pytest invocation).
    The test-level subdir is sanitized from request.node.nodeid.
    Persists across runs (not auto-cleaned like pytest's tmp_path).
    """
    session_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    safe_id = (
        request.node.nodeid
        .replace("::", "__")
        .replace("/", "_")
        .replace(".py", "")
        .replace("[", "_")
        .replace("]", "")
        .replace(" ", "")
    )
    # 上面的替换不足以让 nodeid 成为合法文件名：参数化 id 可以含任意字符
    # （实测 tests/test_doc_inventory.py 的 MODULE_DOC_STALE_CASES 带反引号与
    # 冒号），而 nodeid 直接被当作目录名。NTFS 禁止 < > : " / \ | ? * 与控制
    # 字符，也不接受以点或空格结尾 —— 于是 Linux/CI 全绿，Windows 上 mkdir
    # 直接抛 OSError WinError 123（文件名、目录名或卷标语法不正确）。
    # 统一收敛到文件系统安全字符集（\w 保留中文，产物目录本就 gitignore）。
    safe_id = re.sub(r'[<>:"\\|?*`\x00-\x1f]+', "_", safe_id).strip("._") or "test"
    test_dir = _ARTIFACTS_ROOT / "runs" / session_id / safe_id
    test_dir.mkdir(parents=True, exist_ok=True)
    return test_dir


@pytest.fixture(autouse=True)
def _copy_component_logs_to_artifact_dir(request, artifact_dir):
    """After each test, copy the most recent component log file to the test's logs/.

    Component logs are still written to their original locations
    (Omni_Pre_Processor/logs/, Omni_Localizer/logs/, Omni_Re_Formatter/logs/)
    for legacy/source-code reasons. This fixture copies the latest log
    file for each component into the test's artifact dir under logs/,
    so each test has a self-contained log snapshot.
    """
    yield
    if not isinstance(artifact_dir, Path):
        return
    logs_dest = artifact_dir / "logs"
    logs_dest.mkdir(parents=True, exist_ok=True)
    suite_root = Path(__file__).resolve().parents[1]

    component_log_specs = [
        (suite_root / "Omni_Pre_Processor" / "logs", "opp_*.log", "opp.log"),
        (suite_root / "Omni_Localizer" / "logs", "ol-*.log", "ol.log"),
        (suite_root / "Omni_Re_Formatter" / "logs", "orf_*.log", "orf.log"),
    ]
    for log_dir, glob_pattern, dest_name in component_log_specs:
        if not log_dir.exists():
            continue
        candidates = sorted(log_dir.glob(glob_pattern), key=lambda p: p.stat().st_mtime)
        if candidates:
            shutil.copy2(candidates[-1], logs_dest / dest_name)


# =============================================================================
# Cross-test isolation (e2e#56 Tier-2 inter-test pollution)
# =============================================================================
# The suite runs every module in ONE pytest process. Two kinds of process-global
# state leak between tests and make files that are green in isolation fail only
# in the combined run:
#
#   1. Environment variables. A handful of tests assign to ``os.environ``
#      directly (not via ``monkeypatch``), so the value outlives the test.
#      Observed offender: ``tests/contract/test_contract_documentation.py``
#      sets ``MCP_ALLOWED_DIRECTORIES=/tmp``, which silently widens the OL/OPP/
#      ORF path allowlists for the rest of the session — later fail-CLOSED
#      path-security assertions then see an unexpected allowed directory.
#   2. MCP token-bucket rate limiters. OPP keeps a per-tool bucket dict, the
#      suite (omni_suite.rate_limiter) and OL/ORF a single bucket; each is
#      created once and refills at 1 token/second (defaults RPM=60, burst=10).
#      A long combined run drains the burst, so a later test gets
#      ``RATE_LIMITED`` on a happy path.
#
# The fixture snapshots/restores the environment around each test and discards
# the cached MCP state, so every test starts from the same process state it
# would have had if run alone. It does NOT disable the limiter — its dedicated
# unit tests still exercise draining/refill within a single test.
_RATE_LIMITER_MODULES = (
    "omni_suite.rate_limiter",
    "opp.mcp.rate_limiter",
    "ol_mcp.rate_limiter",
    "orf.mcp.rate_limiter",
)


def _reset_mcp_process_state() -> None:
    """Drop lazily-created MCP singletons so no test inherits drained state."""
    # Token buckets (per-tool dict in OPP; single optional bucket in OL/ORF).
    for mod_name in _RATE_LIMITER_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        buckets = getattr(mod, "_buckets", None)
        if isinstance(buckets, dict):
            buckets.clear()
        if hasattr(mod, "_bucket"):
            mod._bucket = None


@pytest.fixture(autouse=True)
def _isolate_process_state():
    """Restore ``os.environ`` and reset cached MCP state around every test."""
    env_snapshot = dict(os.environ)
    _reset_mcp_process_state()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
        _reset_mcp_process_state()


@pytest.fixture(scope="session", autouse=True)
def _copy_latest_final_outputs():
    """After the session, copy the most recent LQA / E2E outputs to test_artifacts/final/.

    Provides quick-access 'latest_*' symlinks/copies in the final/ dir
    so users don't have to dig through timestamped runs/ subdirs.
    """
    yield
    final_dir = _ARTIFACTS_ROOT / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = _ARTIFACTS_ROOT / "runs"
    if not runs_dir.exists():
        return

    def find_latest(test_name_substr, *sub_path_parts):
        """Find the most recent file at runs/<run>/<test>/<sub_path>.

        Walks the tree manually because rglob's pattern matching is
        unreliable when the pattern contains `*` in a directory name.
        """
        candidates = []
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            for test_dir in run_dir.iterdir():
                if not test_dir.is_dir():
                    continue
                if test_name_substr not in test_dir.name:
                    continue
                candidate = test_dir.joinpath(*sub_path_parts)
                if candidate.is_file():
                    candidates.append(candidate)
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    output_specs = [
        ("test_lqa_xliff_final_docx", "orf", "haier_final.docx", "latest_haier_en_xliff.docx"),
        ("test_lqa_md_final_docx", "orf", "haier_final.docx", "latest_haier_en_md.docx"),
        ("test_e2e_md_html_cli", "orf", "haier_final.html", "latest_haier_en_md.html"),
    ]
    for test_name_substr, *sub_parts, dest_name in output_specs:
        latest = find_latest(test_name_substr, *sub_parts)
        if latest is not None:
            shutil.copy2(latest, final_dir / dest_name)


# =============================================================================
# Path Setup - Ensure all three components are importable
# =============================================================================

def setup_component_paths():
    """Add all three component src directories to Python path."""
    suite_root = Path(__file__).parent.parent

    opp_src = suite_root / "Omni_Pre_Processor" / "src"
    ol_src = suite_root / "Omni_Localizer" / "src"
    orf_src = suite_root / "Omni_Re_Formatter" / "src"

    for src_path in [opp_src, ol_src, orf_src]:
        if src_path.exists() and str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))


setup_component_paths()


# =============================================================================
# Sample Document Fixtures
# =============================================================================

@pytest.fixture
def sample_docx_path(tmp_path: Path) -> Path:
    """Create a sample DOCX file for E2E testing.

    Creates a realistic DOCX with:
    - Headings (H1, H2)
    - Paragraphs with mixed formatting
    - A table
    - Multiple sections
    """
    doc = Document()

    # Title
    doc.add_heading("User Manual", level=1)

    # Introduction section
    doc.add_heading("Introduction", level=2)
    doc.add_paragraph(
        "This user manual describes how to use the product effectively."
    )
    doc.add_paragraph(
        "The product supports multiple languages and formats."
    )

    # Features section
    doc.add_heading("Features", level=2)
    features_para = doc.add_paragraph()
    features_para.add_run("Key features include:").bold = True

    # Bullet list (using table for simple bullets)
    doc.add_paragraph("Multi-format support", style="List Bullet")
    doc.add_paragraph("High quality translation", style="List Bullet")
    doc.add_paragraph("Fast processing", style="List Bullet")

    # Table
    doc.add_heading("Specifications", level=2)
    table = doc.add_table(rows=3, cols=2)
    table.style = "Light Grid Accent 1"

    # Header row
    header_cells = table.rows[0].cells
    header_cells[0].text = "Specification"
    header_cells[1].text = "Value"

    # Data rows
    data_row1 = table.rows[1].cells
    data_row1[0].text = "Format"
    data_row1[1].text = "DOCX, PPTX, PDF"

    data_row2 = table.rows[2].cells
    data_row2[0].text = "Languages"
    data_row2[1].text = "EN, ZH, JA, FR"

    # Closing paragraph
    doc.add_heading("Support", level=2)
    doc.add_paragraph(
        "For technical support, please contact the support team."
    )

    output_path = tmp_path / "sample_user_manual.docx"
    doc.save(str(output_path))
    return output_path


@pytest.fixture
def sample_pptx_path(tmp_path: Path) -> Path:
    """Create a sample PPTX file for E2E testing."""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # Title slide
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_shape = title_slide.shapes.title
    title_shape.text = "Sample Presentation"

    # Content slide
    content_slide = prs.slides.add_slide(prs.slide_layouts[1])
    title_shape = content_slide.shapes.title
    title_shape.text = "Overview"

    body_shape = content_slide.placeholders[1]
    text_frame = body_shape.text_frame
    text_frame.text = "This is a sample presentation for E2E testing."

    p = text_frame.add_paragraph()
    p.text = "It contains multiple slides."
    p.level = 1

    output_path = tmp_path / "sample_presentation.pptx"
    prs.save(str(output_path))
    return output_path


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Create a minimal valid PDF for E2E testing.

    Uses reportlab; tests that consume this fixture auto-skip
    (via pytest.importorskip) when reportlab is not installed.
    """
    pytest.importorskip("reportlab")

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    output_path = tmp_path / "sample_manual.pdf"
    c = canvas.Canvas(str(output_path), pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 720, "User Manual")
    c.setFont("Helvetica", 12)
    c.drawString(72, 680, "Welcome to the user manual.")
    c.drawString(72, 660, "Chapter 1: Getting Started")
    c.drawString(72, 640, "This manual describes how to use the product.")
    c.showPage()
    c.save()
    return output_path


# =============================================================================
# OPP Pipeline Fixtures
# =============================================================================

@pytest.fixture
def opp_pipeline(tmp_path: Path):
    """Create an OPP pipeline instance with resource directory."""
    from opp.pipeline import OPPPipeline

    resource_dir = tmp_path / "opp_resources"
    resource_dir.mkdir(exist_ok=True)

    return OPPPipeline(resource_storage_dir=resource_dir)


def run_opp_extraction(pipeline, docx_path, output_dir, target_format="both",
                        source_lang="en", target_lang="zh"):
    """Run OPP extraction and generate output files.

    Returns dict with paths to generated files and the processing result.
    """
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    # Process file to extract content
    result = pipeline.process_file(docx_path)

    base_name = docx_path.stem
    output_files = {
        "md_path": output_dir / f"{base_name}.md",
        "xliff_path": output_dir / f"{base_name}.xlf",
        "manifest_path": output_dir / f"{base_name}_manifest.json",
        "skeleton_path": output_dir / f"{base_name}.skeleton.zip",
        "resources_dir": output_dir / "resources"
    }

    # Generate markdown if requested
    if target_format in ("both", "md"):
        if result.extraction_result:
            pipeline.generate_markdown(result.extraction_result, output_files["md_path"])

    # Generate XLIFF if requested
    if target_format in ("both", "xlf"):
        if result.extraction_result:
            pipeline.generate_xliff(
                result.extraction_result,
                output_files["xliff_path"],
                source_lang=source_lang,
                target_lang=target_lang
            )

    # Save skeleton if available
    if result.extraction_result and result.extraction_result.skeleton:
        pipeline.save_skeleton(result.extraction_result, base_name, output_dir)

    # Create manifest.json
    import json
    manifest = {
        "manifest_version": "1.0",
        "generated_at": "2026-05-27T00:00:00Z",
        "tool": "OPP",
        "tool_version": "0.2.0",
        "source": {
            "file_path": str(docx_path),
            "original_filename": docx_path.name,
            "format": "DOCX",
            "file_size_bytes": docx_path.stat().st_size,
        },
        "extraction": {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "outputs": {
                "markdown": {"path": str(output_files["md_path"]), "paragraph_count": 0},
                "xliff": {"path": str(output_files["xliff_path"]), "trans_unit_count": 0},
            },
            "images": [],
            "warnings": result.errors
        },
        "skeleton": {
            "path": str(output_files["skeleton_path"]),
            "format": "ZIP"
        },
        "resources": {
            "storage_dir": str(output_files["resources_dir"]),
            "image_count": result.images_stored
        }
    }

    with open(output_files["manifest_path"], "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return {
        "result": result,
        **output_files
    }


@pytest.fixture
def opp_extraction_result(opp_pipeline, sample_docx_path, tmp_path):
    """Run OPP extraction on sample DOCX and return paths to outputs.

    Returns dict with keys:
    - md_path: Path to extracted markdown
    - xliff_path: Path to extracted XLIFF
    - manifest_path: Path to manifest.json
    - skeleton_path: Path to skeleton.zip
    - resources_dir: Path to extracted resources
    - result: ProcessingResult from extraction
    """
    output_dir = tmp_path / "opp_output"
    output_dir.mkdir(exist_ok=True)

    extraction = run_opp_extraction(
        opp_pipeline,
        sample_docx_path,
        output_dir,
        target_format="both",
        source_lang="en",
        target_lang="zh"
    )

    return extraction


# =============================================================================
# Mock OL (Localizer) Fixtures
# =============================================================================

class MockOLTranslator:
    """Mock OL translator for testing - adds [ZH] prefix to simulate translation.

    This mock simulates what a real LLM-based translator would do:
    - Reads source language content
    - Produces target language content (simulated with prefix)
    - Preserves structure and formatting
    """

    def __init__(self, source_lang: str = "en", target_lang: str = "zh"):
        self.source_lang = source_lang
        self.target_lang = target_lang

    def translate_md(self, md_path: Path, output_path: Path) -> bool:
        """Translate markdown file by adding target language prefix to headings."""
        try:
            content = md_path.read_text(encoding="utf-8")

            # Simple mock translation: add [ZH] prefix to H1 headings
            lines = content.split("\n")
            translated_lines = []

            for line in lines:
                if line.startswith("# ") and not line.startswith("##"):
                    # H1 heading - add target language marker
                    line = line + f" [→{self.target_lang}]"
                translated_lines.append(line)

            translated_content = "\n".join(translated_lines)

            # Add YAML frontmatter if not present
            if not translated_content.startswith("---"):
                frontmatter = f"""---
source_lang: {self.source_lang}
target_lang: {self.target_lang}
original_file: {md_path.name}
processor: "MockOL"
version: "0.0.1"
translated_at: 2026-05-27T00:00:00Z
---

"""
                translated_content = frontmatter + translated_content

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(translated_content, encoding="utf-8")
            return True

        except Exception as e:
            print(f"Error translating MD: {e}")
            return False

    def translate_xliff(self, xliff_path: Path, output_path: Path) -> bool:
        """Translate XLIFF file by adding target content to trans-units."""
        import xml.etree.ElementTree as ET

        try:
            tree = ET.parse(xliff_path)
            root = tree.getroot()

            # Detect namespace
            ns = self._detect_ns(root)

            # Add target element to each trans-unit
            for trans_unit in root.iter(f"{{{ns}}}trans-unit"):
                source_el = trans_unit.find(f"{{{ns}}}source")
                if source_el is not None and source_el.text:
                    target_el = ET.SubElement(trans_unit, f"{{{ns}}}target")
                    target_el.text = f"[{self.target_lang}]{source_el.text}"

            # Update file element target-language
            file_el = root.find(f"{{{ns}}}file")
            if file_el is not None:
                file_el.set("target-language", self.target_lang)

            # Write output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                ET.tostring(root, encoding="unicode"),
                encoding="utf-8"
            )
            return True

        except Exception as e:
            print(f"Error translating XLIFF: {e}")
            return False

    def _detect_ns(self, root) -> str:
        """Detect XLIFF namespace from root element."""
        tag = root.tag
        if tag.startswith("{"):
            ns = tag[1:tag.index("}")]
            if "xliff" in ns.lower():
                return ns
        # Search attributes
        for uri in root.attrib.values():
            if "xliff" in uri.lower():
                return uri
        # Default namespace
        return "urn:oasis:names:tc:xliff:document:1.2"


@pytest.fixture
def mock_ol_translator():
    """Provide a MockOLTranslator instance.

    Direction: en -> zh. This is intentional and matches the
    `sample_docx_path` fixture, which creates a synthetic English DOCX
    (User Manual, Specifications, ...). Do NOT flip to zh -> en here
    without also changing sample_docx_path to a Chinese source.

    The real-LLM nightly tests in test_e2e_real_llm.py translate the
    Chinese Haier DOCX (zh -> en) — see that file for the per-test
    direction and the haier_real_docx_path fixture.
    """
    return MockOLTranslator(source_lang="en", target_lang="zh")


# =============================================================================
# ORF Fixtures
# =============================================================================

@pytest.fixture
def orf_output_dir(tmp_path: Path) -> Path:
    """Create output directory for ORF results."""
    output_dir = tmp_path / "orf_output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


# =============================================================================
# E2E Pipeline Fixtures
# =============================================================================

@pytest.fixture
def e2e_pipeline_context(sample_docx_path, tmp_path: Path) -> dict:
    """Create complete context for E2E pipeline testing.

    This fixture sets up all necessary paths and components for testing
    the full OPP → OL → ORF pipeline.

    Returns dict with:
    - input_docx: Original DOCX path
    - temp_dir: Temporary directory for all outputs
    - opp_output: OPP extraction results
    - ol_output: OL translation results
    - orf_output: ORF final results
    """
    context = {
        "input_docx": sample_docx_path,
        "temp_dir": tmp_path,
        "opp_output": None,
        "ol_md_output": None,
        "ol_xliff_output": None,
        "orf_result": None
    }

    return context


# =============================================================================
# Validation Fixtures
# =============================================================================

@pytest.fixture
def validate_docx_structure():
    """Provide a function to validate DOCX file structure."""

    def validate(docx_path: Path) -> tuple[bool, list[str]]:
        """Validate DOCX file has expected structure.

        Returns (is_valid, error_messages)
        """
        errors = []

        if not docx_path.exists():
            return False, ["File does not exist"]

        if docx_path.stat().st_size == 0:
            return False, ["File is empty"]

        # Check ZIP validity
        try:
            with zipfile.ZipFile(docx_path, 'r') as zf:
                # Check for required DOCX files
                required_files = ["word/document.xml"]
                for req_file in required_files:
                    if req_file not in zf.namelist():
                        errors.append(f"Missing required file: {req_file}")

                # Try to parse document.xml
                doc_xml = zf.read("word/document.xml")
                if b"<w:document" not in doc_xml:
                    errors.append("word/document.xml is not a valid document")

        except zipfile.BadZipFile:
            return False, ["File is not a valid ZIP/DOCX"]

        return len(errors) == 0, errors

    return validate


@pytest.fixture
def validate_xliff_structure():
    """Provide a function to validate XLIFF file structure."""

    def validate(xliff_path: Path) -> tuple[bool, list[str]]:
        """Validate XLIFF file has expected structure.

        Returns (is_valid, error_messages)
        """
        import xml.etree.ElementTree as ET

        errors = []

        if not xliff_path.exists():
            return False, ["File does not exist"]

        if xliff_path.stat().st_size == 0:
            return False, ["File is empty"]

        try:
            tree = ET.parse(xliff_path)
            root = tree.getroot()

            # Check root element
            if not root.tag.endswith("}xliff") and "xliff" not in root.tag.lower():
                errors.append("Root element is not XLIFF")

            # Check for file element
            ns = _detect_xliff_ns(root)
            file_el = root.find(f"{{{ns}}}file")
            if file_el is None:
                errors.append("Missing <file> element")
            else:
                # Check attributes
                if not file_el.get("source-language"):
                    errors.append("Missing source-language attribute")
                if not file_el.get("target-language"):
                    errors.append("Missing target-language attribute")

            # Check for trans-units with targets
            trans_units = root.findall(f".//{{{ns}}}trans-unit")
            if not trans_units:
                errors.append("No <trans-unit> elements found")

            for i, unit in enumerate(trans_units):
                source = unit.find(f"{{{ns}}}source")
                target = unit.find(f"{{{ns}}}target")

                if source is None:
                    errors.append(f"trans-unit {i} missing <source>")
                if target is None:
                    errors.append(f"trans-unit {i} missing <target>")
                elif not target.text:
                    errors.append(f"trans-unit {i} has empty <target>")

        except ET.ParseError as e:
            return False, [f"XML parse error: {e}"]

        return len(errors) == 0, errors

    def _detect_xliff_ns(root) -> str:
        tag = root.tag
        if tag.startswith("{"):
            ns = tag[1:tag.index("}")]
            if "xliff" in ns.lower():
                return ns
        for uri in root.attrib.values():
            if "xliff" in uri.lower():
                return uri
        return "urn:oasis:names:tc:xliff:document:1.2"

    return validate


@pytest.fixture
def validate_manifest():
    """Provide a function to validate manifest.json structure."""

    def validate(manifest_path: Path) -> tuple[bool, list[str]]:
        """Validate manifest.json has expected structure.

        Returns (is_valid, error_messages)
        """
        errors = []

        if not manifest_path.exists():
            return False, ["File does not exist"]

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            # Check required top-level keys
            required_keys = ["manifest_version", "generated_at", "tool", "source", "extraction"]
            for key in required_keys:
                if key not in manifest:
                    errors.append(f"Missing required key: {key}")

            # Check source info
            if "source" in manifest:
                source = manifest["source"]
                if "format" not in source:
                    errors.append("source missing 'format'")

            # Check extraction outputs
            if "extraction" in manifest:
                extraction = manifest["extraction"]
                if "outputs" in extraction:
                    outputs = extraction["outputs"]
                    if "markdown" in outputs:
                        if "path" not in outputs["markdown"]:
                            errors.append("outputs.markdown missing 'path'")
                    if "xliff" in outputs:
                        if "path" not in outputs["xliff"]:
                            errors.append("outputs.xliff missing 'path'")

        except json.JSONDecodeError as e:
            return False, [f"JSON parse error: {e}"]

        return len(errors) == 0, errors

    return validate


# =============================================================================
# Real DOCX fixture (海尔 chapter 2)
# =============================================================================

@pytest.fixture(scope="session")
def haier_real_docx_path() -> Path:
    """Path to the real 海尔 chapter-2 E2E test DOCX (447 KB, Chinese content).

    Lives in the committed fixture directory as
    ``scenarios/_fixtures/haier_ch2_zh.docx`` (moved out of the suite root on
    2026-09-17 — see docs/project-health-report-2026-09-17.md §3.7). It is the
    canonical zh→en E2E test DOCX.
    """
    path = (
        Path(__file__).parent.parent
        / "scenarios" / "_fixtures" / "haier_ch2_zh.docx"
    )
    if not path.exists():
        pytest.skip(f"海尔 E2E test DOCX not found at {path}")
    return path


@pytest.fixture(scope="session")
def meridian_english_docx_path() -> Path:
    """Path to the synthetic English source DOCX for en→zh Tier-3 LQA tests.

    Companion to haier_real_docx_path (which is zh→en). The committed
    ``scenarios/_fixtures/meridian_robotics.docx`` is a synthetic 38 KB English
    document with headings, paragraphs, and a 3-row product table. Designed to
    be the canonical en→zh test fixture so the tier-3 matrix covers both
    translation directions.
    """
    path = (
        Path(__file__).parent.parent
        / "scenarios" / "_fixtures" / "meridian_robotics.docx"
    )
    if not path.exists():
        pytest.skip(f"Meridian en→zh E2E test DOCX not found at {path}")
    return path


@pytest.fixture(scope="session")
def meridian_english_pptx_path() -> Path:
    """Path to the synthetic English source PPTX for ORF xliff→pptx Tier-1 test.

    Companion to meridian_english_docx_path. The committed
    ``scenarios/_fixtures/meridian_q1.pptx`` is a 30 KB synthetic English deck
    with 3 slides. Required because XLIFF2PPTXConverter needs a real PPTX
    skeleton to populate the slide structure (a DOCX skeleton produces a
    malformed PPTX).
    """
    path = (
        Path(__file__).parent.parent
        / "scenarios" / "_fixtures" / "meridian_q1.pptx"
    )
    if not path.exists():
        pytest.skip(f"Meridian en→zh E2E test PPTX not found at {path}")
    return path


# =============================================================================
# Golden file options (Task 3.3a)
# =============================================================================


def pytest_addoption(parser):
    """Register pytest CLI options for golden file capture/verification."""
    parser.addoption(
        "--golden-capture",
        action="store_true",
        default=False,
        help="Capture golden files (copy actual output to golden dir)",
    )
    parser.addoption(
        "--golden-verify",
        action="store_true",
        default=True,
        help="Verify output against golden files (default: on)",
    )
    parser.addoption(
        "--no-golden-verify",
        action="store_false",
        dest="golden_verify",
        help="Skip golden file verification",
    )
    parser.addoption(
        "--golden-dir",
        default="tests/golden/xliff2docx",
        help="Golden file directory (default: tests/golden/xliff2docx)",
    )


# =============================================================================
# Test Configuration
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests that exercise the full OPP→OL→ORF pipeline"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take significant time to run"
    )
    config.addinivalue_line(
        "markers", "requires_opp: Tests that require OPP component"
    )
    config.addinivalue_line(
        "markers", "requires_ol: Tests that require OL component"
    )
    config.addinivalue_line(
        "markers", "requires_orf: Tests that require ORF component"
    )
    config.addinivalue_line(
        "markers", "real_chain: Tests that exercise OPP→OL→ORF via the OMNI_TEST_FAKE_LLM/FAKE_PANDOC seams"
    )
    config.addinivalue_line(
        "markers", "failure: Failure-injection tests (LLM exception, parse error, timeout)"
    )
    config.addinivalue_line(
        "markers", "multiformat: Multi-format input coverage (PPTX, PDF, EPUB, etc.)"
    )
    config.addinivalue_line(
        "markers", "requires_api_key: Real LLM tests; ERROR (not skip) if MINIMAX/BAIDU key missing in .env"
    )
    config.addinivalue_line(
        "markers", "nightly: Real LLM tests; CI default skip, run via -m nightly"
    )
    config.addinivalue_line(
        "markers", "scene07: Multi-language E2E test scenes (3 lang pairs × 4 formats)"
    )
    config.addinivalue_line(
        "markers", "benchmark: Throughput and timing benchmarks for OPP/OL/ORF"
    )
