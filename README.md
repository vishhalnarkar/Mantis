# Mantis

A CLI-based cybersecurity reconnaissance tool that validates targets, runs bounded passive recon, persists evidence, and uses AI to interpret findings.

## Quick Start

```bash
# 1. Set up environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
cp .env.example .env
# Edit .env with your GEMINI_API_KEY and GEMINI_MODEL

# 4. Run
python -m src
```

## Project Structure

```
Mantis/
├── src/
│   ├── __main__.py          # Entry point (python -m src)
│   ├── cli.py               # Interactive CLI menu
│   ├── config.py            # Centralized configuration from .env
│   ├── logger.py            # Color-coded terminal logging via rich
│   ├── target.py            # URL validation, DNS resolution, scope control
│   ├── quick_scan.py        # End-to-end pipeline (validate → recon → save → AI)
│   │
│   ├── analysis/            # AI evidence interpretation (Stage 07)
│   │   ├── analyzer.py      # Gemini-based evidence analyzer
│   │   ├── evidence_package.py  # Bounded evidence packaging for LLM
│   │   ├── models.py        # InterpretationResult, KeyObservation, etc.
│   │   └── prompt.py        # Versioned system/user prompts
│   │
│   ├── chatbot/             # Cybersecurity Q&A chatbot (Stage 09)
│   │   ├── prompt.py        # Chatbot system prompt
│   │   └── session.py       # Conversation state management
│   │
│   ├── llm/                 # LLM communication layer
│   │   └── comms.py         # OpenAI-compatible client (Gemini)
│   │
│   ├── recon/               # Reconnaissance toolkit (Stages 04-05)
│   │   ├── orchestrator.py  # Bounded assessment runner
│   │   ├── registry.py      # Tool registry (7 recon tools)
│   │   ├── context.py       # Assessment limits & deadlines
│   │   ├── contract.py      # ToolResult data contract
│   │   ├── assessment.py    # AssessmentResult model
│   │   ├── http_utils.py    # Shared HTTP helpers
│   │   ├── dns_info.py      # DNS record collection
│   │   ├── http_metadata.py # HTTP response inspection
│   │   ├── link_discovery.py# Same-origin link discovery
│   │   ├── robots_sitemap.py# robots.txt & sitemap parsing
│   │   ├── security_headers.py # Security header analysis
│   │   ├── tech_fingerprint.py # Technology fingerprinting
│   │   └── tls_metadata.py  # TLS certificate inspection
│   │
│   ├── reporting/           # Markdown report generation (Stage 08)
│   │   └── generator.py     # Deterministic, escaped report renderer
│   │
│   └── storage/             # SQLite evidence persistence (Stage 06)
│       ├── models.py        # EvidenceAssessment, EvidenceToolRun
│       ├── redaction.py     # Secret/header redaction utilities
│       └── store.py         # SQLite-backed evidence store
│
├── tests/                   # Pytest test suite
├── DevLogs/                 # Stage-by-stage development documentation
├── .env.example             # Template for environment variables
├── pytest.ini               # Pytest configuration
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## Features

- **Quick Scan** — One command runs the full pipeline: target validation → 7 recon tools → evidence persistence → AI analysis
- **Bounded Recon** — Time-limited, depth-limited, page-limited passive reconnaissance
- **Safety Gates** — Blocks private/loopback targets, validates redirects, never follows instructions in untrusted web content
- **AI Interpretation** — Gemini analyzes evidence with citation tracking and hypothesis labeling
- **Evidence Persistence** — SQLite storage with automatic secret redaction
- **Report Generation** — Deterministic Markdown reports with escaped untrusted content
- **Cybersecurity Chatbot** — Q&A mode that never triggers scans

## Testing

```bash
pytest                    # Run all tests
pytest tests/test_target.py -v  # Run specific test file
```

## License

Private project. Not a penetration testing tool — bounded passive reconnaissance only.
