# STAGE 01 — Repository Inspection Report

**Project:** Mantis (CyberSec AI Agent)
**Date:** 2026-10-18
**Inspector:** AI Agent
**Stage:** 01 of 10 — Inspection & Baseline Verification

---

## A. Repository Summary

| Attribute | Value |
|-----------|-------|
| Language / Runtime | Python 3.12.0 (Windows) |
| Package manager | pip + `requirements.txt` (no pyproject.toml or setup.py) |
| Virtual environment | `.venv/` (git-ignored) |
| CLI entry point | `src/cli.py` → `cli()` function (interactive menu loop) |
| Test entry point | `src/main.py` (integration smoke test, not a proper app entry) |
| Config / secrets | `.env` loaded via `python-dotenv` in `src/llm/comms.py` |
| Version control | Git, branch `main`, up to date with `origin/main` |

### Directory Layout

```
Mantis/
├── .env                  # API keys (git-ignored)
├── .gitignore
├── .venv/
├── cmd.txt               # Dev notes (git-ignored)
├── DevLogs/              # Stage planning docs (git-ignored)
├── README.md             # Only contains "# Mantis"
├── requirements.txt      # 5 active deps (cleaned this session)
├── STAGE_01_INSPECTION_REPORT.md  ← this file
└── src/
    ├── main.py           # Smoke test suite (13 checks)
    ├── cli.py            # Interactive CLI menu
    ├── logger.py         # Rich console + terminal logging
    ├── llm/
    │   ├── __init__.py   # empty
    │   └── comms.py      # Gemini via OpenAI-compatible SDK
    └── tools/
        ├── __init__.py   # empty
        ├── registry.py   # TOOL_REGISTRY dict
        ├── executor.py   # Dispatches tool by name
        └── log_analyzer.py  # Stub: counts lines
```

### Actual Data Flow (as implemented today)

```
User runs: python src/main.py  (smoke test)
  or manually: python -c "from cli import cli; cli()"

cli.py
  └─> user picks "1" → imports tools.log_analyzer.analyze_logs
  └─> user picks "2" → prints "not implemented yet"
  └─> user picks "3" → exits

tools/executor.py (not wired into CLI menu)
  └─> looks up TOOL_REGISTRY[name] → calls function(**args)

tools/registry.py
  └─> maps "analyze_logs" → log_analyzer.analyze_logs

llm/comms.py (standalone, not wired into CLI)
  └─> OpenAI SDK → Gemini API → returns text response
  └─> Rich spinner shown during request
```

---

## B. Current Status

| Component / Feature | Status | Evidence | Recommended Next Action |
|---|---|---|---|
| CLI starts and handles input | **Partial** | `cli.py` menu works; no `__main__.py` or console-script entry | Stage 02: add proper entry point |
| Website target URL accepted & validated | **Missing** | No URL validation code exists anywhere | Stage 03 |
| Target scope & redirect protections | **Missing** | No scope/IP validation code | Stage 03 |
| Recon tools return structured results | **Missing** | Only `log_analyzer` stub (counts lines) | Stage 04 |
| Multiple recon checks coordinated by orchestrator | **Missing** | No orchestrator code | Stage 05 |
| Request/time/page/depth/size limits | **Missing** | No limit configuration | Stage 02–03 |
| Results & errors represented consistently | **Partial** | `log_analyzer` returns dict with `status/summary/errors`; no formal schema | Stage 04 |
| Assessment data persisted | **Missing** | No database, no file storage | Stage 06 |
| Gemini client configured & handles API failures | **Partial** | `comms.py` works, catches exceptions, raises `RuntimeError`; not integrated into any workflow | Stage 02, 07 |
| AI interpretation grounded in evidence | **Missing** | No interpretation layer | Stage 07 |
| Markdown report generation | **Missing** | No report code | Stage 08 |
| Cybersecurity chatbot (separate from recon) | **Missing** | Menu option 2 prints "not implemented yet" | Stage 09 |
| Tests exist and can be executed | **Missing** | No `tests/` dir, no `conftest.py`, no pytest config; `main.py` is a manual smoke test only | Stage 02+ |
| Setup & usage documentation accurate | **Partial** | `README.md` has only "# Mantis"; `DevLogs/` has full stage plans | Stage 02 |

---

## C. Baseline Test Results

| # | Command | Executed? | Result |
|---|---------|-----------|--------|
| 1 | `python src/main.py` (with `PYTHONUTF8=1`) | ✅ Yes | **13/13 passed**, exit code 0 |
| 2 | `python -c "from cli import cli; print('OK')"` | ✅ Yes | Import OK |
| 3 | `pytest` | ❌ Not run | No test files exist |
| 4 | Linter / formatter | ❌ Not run | None configured |
| 5 | CLI interactive menu | ❌ Not run | Would require stdin interaction; verified via import + smoke test |
| 6 | Live recon / scan | ❌ Not run | Not applicable; no recon code exists |

**Note:** The smoke test (`main.py`) exercises Logger, Registry, Log Analyzer, Executor, and LLM Communication. All passed including a real Gemini API call (model responded "OK").

---

## D. Configuration & Dependency Findings

### Environment Variables Expected

| Variable | Used In | Present in `.env`? |
|----------|---------|---------------------|
| `GEMINI_API_KEY` | `src/llm/comms.py` | ✅ Yes (value not shown) |
| `GEMINI_MODEL` | `src/llm/comms.py` | ✅ Yes (value not shown) |
| `DEEPSEEK_API_KEY` | *(unused in code)* | ✅ Yes (leftover) |
| `DEEPSEEK_MODEL` | *(unused in code)* | ✅ Yes (leftover) |

### Secrets & .gitignore

- `.env` is correctly git-ignored.
- **No `.env.example` exists** — should be created in Stage 02.
- `.gitignore` is missing: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `reports/`, `*.db`, `mantis.log`.
- `DevLogs/` is git-ignored (planning docs stay local).

### Dependencies

**`requirements.txt` (current, cleaned):**
```
rich
requests
python-dotenv
pytest
openai
```

**Actually installed in `.venv` (extras from prior iterations still present):**
`fastapi`, `uvicorn`, `pandas`, `typer`, `pydantic`, `groq` — installed but no longer in requirements.txt. Harmless but should be uninstalled or left alone.

**Missing from `.venv`:** Nothing required is missing. All 5 listed deps import successfully.

---

## E. Risks & Blockers

| # | Risk / Blocker | Severity | Notes |
|---|---------------|----------|-------|
| 1 | No proper application entry point (`__main__.py` or console script) | Low | Stage 02 will address |
| 2 | No centralized configuration module | Medium | API keys, timeouts, limits are scattered / hardcoded |
| 3 | No target validation or scope control | **High** | Critical safety layer; must exist before any recon code (Stage 03) |
| 4 | No test infrastructure | Medium | No pytest config, no test directory, no mocks |
| 5 | `llm/comms.py` creates OpenAI client at module import time | Low | Will fail if `.env` is missing; should defer or handle gracefully |
| 6 | `tools/` modules use bare imports (`from logger import ...`) | Low | Works only when `src/` is on `sys.path`; fragile for packaging |
| 7 | README is effectively empty | Low | Stage 02 |
| 8 | DeepSeek env vars are dead config | Low | Remove in Stage 02 cleanup |

No blockers prevent starting Stage 02.

---

## F. Recommended Next-Stage Plan (Stage 02)

Based on actual findings, the smallest sensible set of changes for Stage 02:

1. **Create a proper CLI entry point** (`src/__main__.py` or wire `cli()` as the app runner).
2. **Centralize configuration** — a small `src/config.py` that loads `.env`, exposes validated settings, and provides clear errors for missing keys.
3. **Create `.env.example`** with placeholder values.
4. **Update `.gitignore`** to cover `__pycache__`, `.pytest_cache`, reports, DB files.
5. **Remove dead DeepSeek env vars** from `.env` (or document them as unused).
6. **Defer OpenAI client creation** in `comms.py` so import doesn't fail without `.env`.
7. **Update `README.md`** with setup instructions and project description.
8. **Add minimal pytest config** (`pytest.ini` or section in a future `pyproject.toml`) and one smoke test to establish the test convention.

No recon engine, no new tools, no persistence — those belong to Stages 03+.

---

## Acceptance Criteria — Stage 01

- [x] Repository structure and entry points documented.
- [x] Actual architecture and data flow summarized.
- [x] Relevant existing code inspected.
- [x] Safe baseline test/startup attempt made (13/13 passed).
- [x] Test results distinguish passed, failed, skipped, and not-run checks.
- [x] Configuration and secret-handling inspected without revealing secret values.
- [x] Current features classified with evidence.
- [x] Bugs and blockers documented (not patched).
- [x] `STAGE_01_INSPECTION_REPORT.md` created.
- [x] Small Stage 02 proposal included.
- [x] No broad refactor or feature implementation performed.

---

*Stage 01 complete. Awaiting user review and approval to proceed to Stage 02.*
