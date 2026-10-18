# Mantis

A CLI-based cybersecurity assistant (CyberSec AI Agent). Mantis performs
**bounded, passive website reconnaissance** against a target you own or are
explicitly authorized to assess, stores redacted evidence locally, optionally
interprets it with Gemini, and generates reproducible Markdown reports. It
also includes a cybersecurity Q&A chatbot and a basic log analyzer.

Active penetration testing and exploitation are **not** part of this project.

## Capabilities

| Menu | Feature | Notes |
|---|---|---|
| 1 | Analyze Logs | Line-counting log text analysis via the tool registry |
| 2 | Validate Target URL | Scope gate: scheme, IP class, DNS, redirect policy |
| 3 | Run Recon Assessment | 7 tools, serial, deadline-bounded; auto-saved to SQLite |
| 4 | ChatBot | Gemini Q&A; bounded history; never triggers scans |
| 5 | Interpret Saved Assessment (AI) | Optional Gemini interpretation of stored evidence |
| 6 | Generate Report | Deterministic Markdown report from stored evidence |
| 7 | Exit | |

Safety model:

- Only `http`/`https` targets; private, loopback, link-local, reserved,
  multicast, and unspecified IPs are blocked by default.
- Redirects are re-validated and must stay on the same origin.
- Read-only GET requests only; response sizes, page counts, and total
  assessment time are bounded.
- Sensitive headers are redacted before persistence; page bodies are never
  persisted or sent to the model.
- Chatbot mode is strictly separated from reconnaissance (no tool execution
  from chat text).

## Requirements

- Python 3.12+ (verified on 3.12.0, Windows)
- Dependencies: `rich`, `requests`, `python-dotenv`, `pytest`, `openai`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure secrets (never commit .env)
Copy-Item .env.example .env
# then edit .env: GEMINI_API_KEY=... and GEMINI_MODEL=...
```

Without a configured key, all deterministic features (options 1–3, 6) still
work; options 4 and 5 report the missing configuration clearly.

## Usage

```powershell
python src\__main__.py     # interactive CLI menu
```

## Testing

```powershell
python test.py               # master suite: integration + pytest (offline, mocked)
python test.py --live        # additionally hits the real Gemini API (uses quota)
python test.py --skip-pytest # integration checks only
pytest                       # unit tests only
```

## Project Layout

```
src/
├── __main__.py            # Entry point
├── cli.py                 # Interactive menu (options 1-7)
├── config.py              # Centralized .env-backed configuration
├── logger.py              # Rich terminal logging (no log files)
├── target.py              # Scope gate: URL/IP/DNS/redirect validation
├── llm/comms.py           # Gemini client (OpenAI-compatible endpoint)
├── tools/                 # Generic tool registry + executor + log analyzer
├── recon/                 # 7 recon tools, shared contract, orchestrator
├── storage/               # SQLite evidence store + redaction (schema v1)
├── analysis/              # Gemini evidence interpretation (prompt v1)
├── reporting/             # Deterministic Markdown report generator (format v1)
└── chatbot/               # Bounded Q&A session + versioned prompt
tests/                     # pytest unit tests (all mocked, no API key needed)
test.py                    # Master test runner (all stages)
```

## Data locations

- Evidence + interpretations: `data/evidence.db` (SQLite, WAL mode)
- Generated reports: `reports/*.md` (created on demand; git-ignored)
- Both directories are local-only and excluded from version control.

## Limitations

- Reconnaissance is passive and bounded; a missing check never proves a
  site is secure, and findings are observations, not confirmed vulnerabilities.
- AI interpretation is optional, labeled as such, and validated against the
  stored evidence; unsupported citations are flagged.
- DNS rebinding is not fully mitigated (resolution is checked at validation
  time, not pinned per request).
- No concurrency by design; assessments run serially.
- This is a project verification baseline, not a formal security audit or
  compliance certification.