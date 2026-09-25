# Setup — Real LLM Integration Tests

> **Prerequisite:** Python >= 3.13. All Omni Suite components require Python 3.13+.
> Verify with `python3 --version` before proceeding.

> **Goal:** Wire your real LLM provider keys so the nightly `pytest -m nightly`
> tests can hit real LLMs (instead of the fake LLM that runs in CI).
>
> **Time:** ~10 minutes.
>
> **What you do:** 3 steps. Copy-paste ready.
>
> **Prereq:** You have active API keys for the canonical OL model pool:
> - **Volcengine Ark** (`ARK_API_KEY`) — https://console.volcengine.com/ark/
> - **Zhipu BigModel** (`ZHIPU_API_KEY`) — https://open.bigmodel.cn/
> - **NVIDIA NIM** (`NVIDIA_NIM_API_KEY`) — https://build.nvidia.com/
>
> If you don't have these, get them first. Tests will be skipped (not failed)
> without them.
>
> **Venv prereq (one-time):** The suite ships with a single consolidated venv at
> `.venv_ol/` that contains all three components (OPP, OL, ORF) installed in
> editable mode. An older `.venv/` may still be present on disk but is
> **DEPRECATED** — see `.venv/DEPRECATED.md`. All commands below use
> `.venv_ol/bin/python`.
>
> If you ever need to rebuild the venv from scratch, run:
> ```bash
> cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
> "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"/.venv_ol/bin/pip install -e Omni_Pre_Processor/ -e Omni_Localizer/ -e Omni_Re_Formatter/
> ```
> Do **not** add new dependencies to `.venv/` — they will not be visible to the test suite.

---

## Step 1 — Fill your API keys

The canonical model pool is defined in
`Omni_Localizer/config/default.yaml`: **ark-code-latest** (Volcengine Ark,
priority 1) → **glm-4.7-flash** (Zhipu, priority 2) →
**minimaxai/minimax-m3** (NVIDIA NIM, priority 3), shared by every role.

Copy the template and fill in the three keys:

```bash
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
cp .env.example Omni_Localizer/.env
```

Open `Omni_Localizer/.env` and replace the placeholders (keep the variable
names, no quotes, no spaces around `=`):

```env
ARK_API_KEY=your-real-ark-key
ZHIPU_API_KEY=your-real-zhipu-key
NVIDIA_NIM_API_KEY=<your-nvidia-nim-api-key>
```

**Note on location:** the nightly E2E fixture and the `.github/workflows`
nightly jobs read `Omni_Localizer/.env`. The OL CLI also auto-discovers a
`.env` in the current directory or any parent directory (and honours
`OL_DOTENV`), so a root `.env` works when you run commands from the suite root.

> **Safety:** both `.env` locations are git-ignored (root `.gitignore` and
> `Omni_Localizer/.gitignore`). You will never accidentally commit them.

---

## Step 2 — Configure the model pool

`Omni_Localizer/config/default.yaml` is the **tracked canonical template** and
already contains the 3-provider unified pool with `${ENV_VAR}` references; it is
safe to use directly. For a machine-local override, copy it to the gitignored
`config/local.yaml` and edit that instead:

```bash
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"/Omni_Localizer
cp config/default.yaml config/local.yaml
git check-ignore -v config/local.yaml   # should print config/local.yaml
```

The pool shape (all four roles — translation / judging / restoration /
profiling — carry the same three priorities):

```yaml
llm_pool:
  translation:
    - provider: "openai"
      model: "ark-code-latest"        # Volcengine Ark — priority-1 primary
      priority: 1
      role: "translation"
      api_key: "${ARK_API_KEY}"
      base_url: "https://ark.cn-beijing.volces.com/api/coding/v3"
      timeout: 120.0
    - provider: "openai"
      model: "glm-4.7-flash"          # Zhipu — priority-2 fallback
      priority: 2
      role: "translation"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
    - provider: "openai"
      model: "minimaxai/minimax-m3"   # NVIDIA NIM — priority-3 fallback
      priority: 3
      role: "translation"
      api_key: "${NVIDIA_NIM_API_KEY}"
      base_url: "https://integrate.api.nvidia.com/v1"
      timeout: 120.0
  # judging: / restoration: / profiling: mirror the same three priorities.
```

**Why this shape:**
- Schema requires **≥ 2 models per role** (`LLMPoolConfig.check_min_models_per_role` in `Omni_Localizer/src/ol_config/schema.py`).
- `api_key` and `base_url` use `${VAR}` syntax — the loader (`Omni_Localizer/src/ol_config/loader.py`) auto-resolves from the environment at config-load time, and the schema validator (`schema.py:_check_env_vars`) warns if the env var is missing.
- `provider: "openai"` selects the OpenAI-compatible client for all three endpoints; litellm falls back along priority (`priority 1` → `2` → `3`) automatically.

Validate the config with the doctor command:

```bash
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
.venv_ol/bin/ol doctor -c Omni_Localizer/config/local.yaml
# (or -c Omni_Localizer/config/default.yaml)
```

---

## Step 3 — Verify the real LLM works

Run these commands from the repo root. Export the keys into your shell (or use
the `.env` auto-discovery described above), and point `--config` at the pool you
validated in Step 2.

### 3a. Quick smoke test (CLI, MD path)

```bash
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
.venv_ol/bin/python -m ol_cli translate-md \
    Omni_Localizer/tests/fixtures/sample.md \
    -c Omni_Localizer/config/local.yaml \
    -o /tmp/ol-smoke \
    -s en -t zh
```

Expected output (last line):

```
Translated: sample.md -> /tmp/ol-smoke/sample.md (en -> zh)
```

Should finish in **< 30 seconds** (real network round-trip to Ark/Zhipu/NVIDIA).

### 3b. Quick smoke test (CLI, XLIFF path)

```bash
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
.venv_ol/bin/python -m ol_cli translate-xliff \
    Omni_Localizer/tests/fixtures/sample-xliff12.xlf \
    -c Omni_Localizer/config/local.yaml \
    -o /tmp/ol-smoke \
    -s en -t zh
```

Expected output (last line):

```
Translated: sample-xliff12.xlf -> /tmp/ol-smoke/sample-xliff12.xlf (en -> zh)
```

Same ~30s target.

### 3c. If you have the Haier DOCX converted to XLIFF (24-image stress test)

The full Haier DOCX (24 images, 9 paragraphs) is the committed fixture `scenarios/_fixtures/haier_ch2_zh.docx`. To convert it to XLIFF first:

```bash
# (Optional) Convert DOCX → XLIFF via OPP
cd "${OMNI_ROOT:-/mnt/d/贯维/Omni_Suite}"
.venv_ol/bin/python -m opp_cli extract "scenarios/_fixtures/haier_ch2_zh.docx" \
    -o /tmp/ol-haier-xliff
```

Then translate the XLIFF:

```bash
.venv_ol/bin/python -m ol_cli translate-xliff \
    /tmp/ol-haier-xliff/*.xlf \
    -c Omni_Localizer/config/local.yaml \
    -o /tmp/ol-smoke-haier \
    -s en -t zh
```

Expected: translated XLIFF with all 9 paragraphs + 24 image placeholders preserved. This is the smoke test the nightly suite exercises end-to-end (`tests/test_e2e_real_llm.py`).

---

## Common errors & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `Environment variable 'ARK_API_KEY' not set` | `.env` not loaded | Check Step 1 — make sure the line has no leading space, no quote, the `=` is direct. |
| `AuthenticationError: Invalid API key` (401/403) | Key typo / wrong project | Re-paste the key from the provider console. For NVIDIA, copy the full `nvapi-...` string verbatim. |
| `Model not found` (404) | Wrong model name | The canonical ids are `ark-code-latest`, `glm-4.7-flash`, `minimaxai/minimax-m3`; if a provider rotates, update `config/local.yaml`. |
| `RateLimitError` (429) | Hit free-tier cap | Wait 60s and re-run; the Router retries down the priority chain. |
| Test `SKIPPED: no ... key` | `.env` not visible to pytest | Confirm the file is at `Omni_Localizer/.env`. The `use_real_llm` fixture (`tests/test_e2e_real_llm.py`) reads it from there via `Path(__file__).resolve().parents[1] / "Omni_Localizer" / ".env"`. |
| `Error: --output-dir is required` | CLI requires `-o` flag | Add `-o /tmp/ol-smoke` (or any writable dir) to every `translate-md` / `translate-xliff` command. |
| CLI uses the wrong pool | Forgot `--config` flag | Add `-c Omni_Localizer/config/local.yaml` to every command. |

---

## Confirmation checklist (tick all before saying "done")

- [ ] `Omni_Localizer/.env` has real `ARK_API_KEY`, `ZHIPU_API_KEY`, and `NVIDIA_NIM_API_KEY` values (no quotes, no spaces).
- [ ] `Omni_Localizer/config/local.yaml` exists (a copy of the canonical `default.yaml`) with the 3-provider pool and `${VAR}` env refs.
- [ ] `Omni_Localizer/.gitignore` ignores `config/local.yaml` (verified with `git check-ignore -v config/local.yaml`).
- [ ] `.venv_ol/bin/ol doctor -c Omni_Localizer/config/local.yaml` passes its 5 checks.
- [ ] Step 3a prints `Translated: sample.md -> ...`.
- [ ] Step 3b prints `Translated: sample-xliff12.xlf -> ...`.
- [ ] `git status` in `Omni_Localizer/` does NOT list `local.yaml` and does NOT show `.env` as modified.

---

## What's next (you don't do this; I do)

After setup, the nightly real-LLM runs are:
- **`make e2e`** — 19 tests in `tests/test_e2e_real_llm.py` (skips gracefully without keys).
- **`.github/workflows/validation.yml` nightly** — full validation library against the canonical pool secrets (`ARK_API_KEY` / `ZHIPU_API_KEY` / `NVIDIA_NIM_API_KEY`); keyed scenarios report `unconfigured` when a secret is absent, never a fake green.
- **`.github/workflows/e2e-tests.yml` nightly-llm** — real-LLM E2E matrix.
