# Mantis

A CLI-based cybersecurity assistant (CyberSec AI Agent).

## Capabilities

- **Website reconnaissance** — bounded, non-destructive reconnaissance of a
  website you own or are explicitly authorized to assess, with evidence-backed
  reporting. *(Under construction — see DevLogs stage plan.)*
- **Cybersecurity chatbot** — general cybersecurity Q&A powered by Gemini.
  *(Under construction.)*
- **Log analysis** — basic log text analysis through the pluggable tool system.

The current milestone ends at reconnaissance and evidence-backed reporting.
Active penetration testing is **not** part of this project.

## Requirements

- Python 3.12+
- See `requirements.txt`

## Setup

1. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Configure secrets:

   ```powershell
   Copy-Item .env.example .env
   ```

   Then edit `.env` and fill in your real Gemini API key and model name.
   Never commit `.env` to version control.

## Usage

Run the CLI from the project root:

```powershell
python src\__main__.py
```

Run the master test suite (all components + combinations):

```powershell
python test.py
```

Options:
- `python test.py --live` — also tests the real Gemini API (uses quota)
- `python test.py --skip-pytest` — skip the pytest sub-run

Run automated unit tests only:

```powershell
pytest
```

## Project Layout

```
src/
├── __main__.py       # CLI entry point
├── cli.py            # Interactive CLI menu
├── config.py         # Centralized configuration (.env loading)
├── logger.py         # Rich console + color-coded terminal logging
├── main.py           # Integration smoke test
├── llm/
│   └── comms.py      # Gemini client (OpenAI-compatible endpoint)
└── tools/
    ├── registry.py   # Allowlisted tool registry
    ├── executor.py   # Tool dispatcher
    └── log_analyzer.py
```

## Security Notes

- Only assess websites you own or have explicit written permission to assess.
- API keys live in `.env` (git-ignored); `.env.example` contains placeholders only.
- Secrets are never logged or printed.

## Limitations

- Reconnaissance engine, persistence, reporting, and chatbot are not
  implemented yet. See `DevLogs/` for the staged development plan.
- A missing check result does **not** mean a site is secure.
