"""Deterministic Markdown report generator (Stage 08).

Reads a persisted EvidenceAssessment (and optionally a validated
InterpretationResult) and renders a stable, escaped, redacted Markdown
report. Writes are atomic and confined to an approved output directory.

Design guarantees:
- Deterministic: same assessment + interpretation + generated_at =>
  identical output.
- Untrusted data (website strings, AI text) is escaped; never rendered
  as links, headings, or instructions.
- Sensitive headers are re-filtered at render time (defense in depth).
- body_text is never rendered.
- Failed/skipped tools are described honestly; missing evidence is
  never described as proof of safety.
- Path traversal is blocked; existing files are never overwritten
  (unique-name policy); writes are atomic via temp-file + os.replace.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logger import get_logger
from recon.contract import now_iso
from storage.models import EvidenceAssessment
from storage.redaction import SENSITIVE_HEADERS

log = get_logger("reporting")

REPORT_FORMAT_VERSION = 1

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPORT_DIR = _PROJECT_ROOT / "reports"

# Display bounds (report-level; storage already bounds values too).
MAX_DISPLAY_VALUE_CHARS = 300
MAX_LIST_ITEMS = 20
MAX_DICT_KEYS = 15
MAX_OBSERVATIONS_PER_TOOL = 15
MAX_ERRORS_SHOWN = 5

# Markdown punctuation that must be escaped in untrusted text.
_MD_ESCAPE_CHARS = set("\\`*_[]<>|~#")


class ReportError(Exception):
    """Base error for report generation."""
    pass


class ReportPathError(ReportError):
    """Raised when a report path is unsafe or outside the output directory."""
    pass


class ReportWriteError(ReportError):
    """Raised when a report cannot be written safely."""
    pass


def escape_md(text: Any) -> str:
    """Escape Markdown-significant characters in untrusted text.

    Newlines collapse to spaces so remote text cannot inject headings,
    lists, or block structure. Backslash escapes render as literals in
    GitHub-flavored Markdown.
    """
    out = []
    for ch in str(text):
        if ch in _MD_ESCAPE_CHARS:
            out.append("\\" + ch)
        elif ch in ("\n", "\r"):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def code_span(text: Any) -> str:
    """Sanitize text for use inside backtick code spans.

    Inside code spans, Markdown treats all characters literally except
    the backtick itself. We only need to remove backticks and collapse
    newlines — no backslash escaping needed.
    """
    s = str(text).replace("`", "'").replace("\n", " ").replace("\r", " ")
    return s


def _now_file_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_report_filename(assessment_id: str) -> str:
    """Derive a safe filename from the assessment ID and current time.

    Never uses target URLs or any remote-supplied string.
    """
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", assessment_id)[:64] or "unknown"
    return f"mantis_report_{safe_id}_{_now_file_ts()}.md"


def resolve_report_path(directory: Path | str, filename: str) -> Path:
    """Validate that `filename` resolves strictly inside `directory`.

    Rejects absolute paths, separators, and '..' traversal.
    """
    base = Path(directory).resolve()
    if not filename or filename != os.path.basename(filename):
        raise ReportPathError(f"Unsafe report filename: {filename!r}")
    if ".." in filename or filename.startswith("."):
        raise ReportPathError(f"Unsafe report filename: {filename!r}")
    candidate = (base / filename).resolve()
    if candidate.parent != base:
        raise ReportPathError("Report path escapes the output directory.")
    return candidate


def unique_report_path(directory: Path | str, filename: str) -> Path:
    """Return a non-existing path, appending _1, _2, ... if needed.

    Existing reports are never overwritten (documented policy).
    """
    base_candidate = resolve_report_path(directory, filename)
    if not base_candidate.exists():
        return base_candidate
    stem = base_candidate.stem
    suffix = base_candidate.suffix
    for i in range(1, 1000):
        alt = resolve_report_path(directory, f"{stem}_{i}{suffix}")
        if not alt.exists():
            return alt
    raise ReportWriteError("Too many existing report files; choose another directory.")


def write_report_atomic(path: Path, content: str) -> None:
    """Write content atomically: temp file in same dir, then os.replace.

    A failed write never leaves a truncated file at the final path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise ReportWriteError(f"Failed to write report: {e}") from e


def _evidence_id_for(assessment: EvidenceAssessment, tool_id: str) -> str:
    """Same deterministic scheme used by Stage 07 evidence packages."""
    return f"{assessment.assessment_id}:{tool_id}"


def _valid_evidence_ids(assessment: EvidenceAssessment) -> set[str]:
    return {_evidence_id_for(assessment, r.tool_id) for r in assessment.tool_runs}


def _filter_headers_for_render(headers: dict) -> dict:
    """Defense-in-depth: re-strip sensitive headers at render time."""
    return {
        k: str(v)[:200]
        for k, v in headers.items()
        if str(k).lower() not in SENSITIVE_HEADERS
    }


def _format_value(value: Any) -> tuple[str, bool]:
    """Format one observation value for display. Returns (text, truncated)."""
    truncated = False
    if isinstance(value, str):
        if len(value) > MAX_DISPLAY_VALUE_CHARS:
            value = value[:MAX_DISPLAY_VALUE_CHARS]
            truncated = True
        return value, truncated
    if isinstance(value, bool):
        return "yes" if value else "no", False
    if isinstance(value, (int, float)):
        return str(value), False
    if isinstance(value, list):
        shown = value[:MAX_LIST_ITEMS]
        if len(value) > MAX_LIST_ITEMS:
            truncated = True
        parts = []
        for item in shown:
            t, _ = _format_value(item)
            parts.append(t)
        return ", ".join(parts), truncated
    if isinstance(value, dict):
        items = list(value.items())[:MAX_DICT_KEYS]
        if len(value) > MAX_DICT_KEYS:
            truncated = True
        parts = []
        for k, v in items:
            t, _ = _format_value(v)
            parts.append(f"{k}={t}")
        return "; ".join(parts), truncated
    if value is None:
        return "(none)", False
    return str(value)[:MAX_DISPLAY_VALUE_CHARS], truncated


_STATUS_LABELS = {
    "success": "SUCCESS",
    "partial": "PARTIAL",
    "unavailable": "UNAVAILABLE (dependency missing)",
    "blocked": "BLOCKED (safety gate)",
    "error": "ERROR",
    "skipped": "SKIPPED (deadline/dependency)",
}


def render_report(
    assessment: EvidenceAssessment,
    interpretation=None,
    interpretation_note: str = "",
    generated_at: str | None = None,
) -> str:
    """Render the Markdown report deterministically.

    `interpretation` is included only when its status is 'completed'.
    `interpretation_note` explains an unavailable/failed/invalid AI
    interpretation without fabricating one.
    `generated_at` is injectable for deterministic tests.
    """
    if generated_at is None:
        generated_at = now_iso()

    lines: list[str] = []
    add = lines.append

    # ── 1. Header and assessment summary ──────────────────────────
    add("# Mantis Security Assessment Report")
    add("")
    add(f"- **Assessment ID:** `{code_span(assessment.assessment_id)}`")
    add(f"- **Target:** `{code_span(assessment.target_url or assessment.target_hostname or 'unknown')}`")
    add(f"- **Hostname:** `{code_span(assessment.target_hostname or 'unknown')}`")
    add(f"- **Assessment status:** {escape_md(assessment.status or 'unknown').upper()}")
    add(f"- **Started:** {escape_md(assessment.started_at or 'n/a')}")
    add(f"- **Completed:** {escape_md(assessment.completed_at or 'n/a')}")
    add(f"- **Duration:** {assessment.duration_seconds:.1f} s")
    add(f"- **Report generated:** {escape_md(generated_at)}")
    add("")
    add("> This report summarizes bounded, passive reconnaissance. It is not a "
        "penetration test, not a certification, and does not prove that the "
        "target is secure or free of vulnerabilities.")
    add("")

    success_tools = [r for r in assessment.tool_runs if r.status == "success"]
    other_tools = [r for r in assessment.tool_runs if r.status != "success"]
    add("## 1. Summary")
    add("")
    summary_bits = [
        f"{len(assessment.tool_runs)} recon tool run(s) recorded",
        f"{len(success_tools)} succeeded",
        f"{len(other_tools)} did not complete successfully" if other_tools else "all completed successfully",
    ]
    add(escape_md(", ".join(summary_bits)) + ".")
    if assessment.errors:
        add("")
        add(f"Assessment-level errors: {escape_md('; '.join(assessment.errors[:MAX_ERRORS_SHOWN]))}")
    add("")

    # ── 2. Scope and methodology ──────────────────────────────────
    add("## 2. Scope and Methodology")
    add("")
    add("Bounded passive reconnaissance only. No exploitation, no active "
        "penetration testing, no credential attacks. Tools ran in a fixed "
        "deterministic order against a single validated target origin.")
    add("")
    add("| # | Tool | Recorded status | Evidence ID |")
    add("|---|------|-----------------|-------------|")
    order = assessment.execution_order or [r.tool_id for r in assessment.tool_runs]
    run_by_id = {r.tool_id: r for r in assessment.tool_runs}
    for idx, tool_id in enumerate(order, 1):
        run = run_by_id.get(tool_id)
        if run is None:
            add(f"| {idx} | `{code_span(tool_id)}` | NOT RUN | — |")
        else:
            label = _STATUS_LABELS.get(run.status, str(run.status).upper())
            eid = _evidence_id_for(assessment, tool_id)
            add(f"| {idx} | `{code_span(tool_id)}` | {escape_md(label)} | `{code_span(eid)}` |")
    # Runs present but absent from execution_order (defensive)
    for run in assessment.tool_runs:
        if run.tool_id not in order:
            label = _STATUS_LABELS.get(run.status, str(run.status).upper())
            eid = _evidence_id_for(assessment, run.tool_id)
            add(f"| — | `{code_span(run.tool_id)}` | {escape_md(label)} | `{code_span(eid)}` |")
    add("")
    if assessment.limits_applied:
        add("Configured limits that affected coverage:")
        for lim in assessment.limits_applied[:10]:
            add(f"- `{code_span(lim)}`")
        add("")
    add("Missing or failed checks mean the check did not complete — they do "
        "not prove a control or vulnerability is absent or present.")
    add("")

    # ── 3. Observed evidence ──────────────────────────────────────
    add("## 3. Observed Evidence")
    add("")
    if not assessment.tool_runs:
        add("_No tool evidence was recorded for this assessment._")
        add("")
    for run in assessment.tool_runs:
        eid = _evidence_id_for(assessment, run.tool_id)
        add(f"### Tool: `{code_span(run.tool_id)}` — {escape_md(run.status).upper()}")
        add("")
        add(f"- **Evidence ID:** `{code_span(eid)}`")
        if run.started_at:
            add(f"- **Observed at:** {escape_md(run.started_at)}")
        add("")
        shown_keys = list(run.observations.keys())[:MAX_OBSERVATIONS_PER_TOOL]
        omitted = len(run.observations) - len(shown_keys)
        for key in shown_keys:
            if key == "body_text":
                continue  # never render page bodies
            value = run.observations[key]
            if key in ("all_headers", "selected_headers") and isinstance(value, dict):
                value = _filter_headers_for_render(value)
            text, truncated = _format_value(value)
            suffix = " _(truncated for report)_" if truncated else ""
            add(f"- `{code_span(key)}`: {escape_md(text)}{suffix}")
        if omitted > 0:
            add(f"- _({omitted} further observation key(s) omitted for report size)_")
        if run.errors:
            add("")
            add("Tool errors:")
            for e in run.errors[:MAX_ERRORS_SHOWN]:
                add(f"- {escape_md(e)}")
        if run.limits_applied:
            add("")
            add("Limits applied to this tool:")
            for lim in run.limits_applied[:5]:
                add(f"- `{code_span(lim)}`")
        add("")

    # ── 4. AI interpretation (optional) ───────────────────────────
    add("## 4. AI Interpretation (Optional)")
    add("")
    valid_ids = _valid_evidence_ids(assessment)
    if interpretation is not None and interpretation.status == "completed":
        add("_The following section is AI-generated interpretation, clearly "
            "separate from the raw observations above. Claims cite evidence IDs; "
            "hypotheses are labeled. Treat as analyst input, not ground truth._")
        add("")
        add(f"- Interpretation ID: `{code_span(interpretation.interpretation_id)}`")
        add(f"- Model: `{code_span(interpretation.model_id or 'n/a')}`")
        add(f"- Prompt version: {escape_md(interpretation.prompt_version or 'n/a')}")
        add(f"- Generated at: {escape_md(interpretation.generated_at or 'n/a')}")
        add("")
        if interpretation.summary:
            add(f"**AI summary:** {escape_md(interpretation.summary)}")
            add("")
        if interpretation.observations:
            add("**Key observations (AI):**")
            for o in interpretation.observations:
                tag = " _(hypothesis)_" if o.is_hypothesis else ""
                ids = ", ".join(f"`{code_span(i)}`" for i in o.evidence_ids)
                cite = f" [{ids}]" if o.evidence_ids else " [no citation]"
                add(f"- {escape_md(o.text)}{tag}{cite}")
            add("")
        if interpretation.interpretations:
            add("**Possible implications (interpretations, not confirmed facts):**")
            for i in interpretation.interpretations:
                ids = []
                for eid in i.evidence_ids:
                    if eid in valid_ids:
                        ids.append(f"`{code_span(eid)}`")
                    else:
                        ids.append(f"`{code_span(eid)}` _(unsupported citation)_")
                cite = f" [{', '.join(ids)}]" if ids else " [no citation]"
                add(f"- _(confidence: {escape_md(i.confidence)})_ {escape_md(i.text)}{cite}")
            add("")
        if interpretation.limitations:
            add("**AI-stated limitations:**")
            for lim in interpretation.limitations:
                add(f"- {escape_md(lim)}")
            add("")
        if interpretation.recommendations:
            add("**AI-suggested manual verification steps:**")
            for r in interpretation.recommendations:
                add(f"- {escape_md(r)}")
            add("")
        if interpretation.unsupported_citations:
            add(f"⚠ {len(interpretation.unsupported_citations)} model citation(s) "
                "referenced evidence not in this assessment and were flagged as "
                "unsupported.")
            add("")
    else:
        note = interpretation_note or (
            "No validated AI interpretation is available for this assessment. "
            "This does not affect the deterministic evidence sections above."
        )
        add(f"_{escape_md(note)}_")
        add("")

    # ── 5. Tool failures and coverage limitations ─────────────────
    add("## 5. Tool Failures and Coverage Limitations")
    add("")
    failed_runs = [r for r in assessment.tool_runs if r.status not in ("success",)]
    if failed_runs:
        add("| Tool | Status | Notes |")
        add("|------|--------|-------|")
        for run in failed_runs:
            label = _STATUS_LABELS.get(run.status, str(run.status))
            note = "; ".join(run.errors[:2]) if run.errors else "—"
            add(f"| `{code_span(run.tool_id)}` | {escape_md(label)} | {escape_md(note)[:200]} |")
        add("")
    else:
        add("All recorded tool runs completed with status `success`.")
        add("")
    add("Incomplete checks mean the check did not run to completion. Absence of "
        "findings is **not** evidence of safety; additional manual verification "
        "is required before drawing security conclusions.")
    add("")

    # ── 6. Recommended next steps ─────────────────────────────────
    add("## 6. Recommended Next Steps")
    add("")
    add("**Manual verification (safe, non-destructive):**")
    if interpretation is not None and interpretation.status == "completed" and interpretation.recommendations:
        for r in interpretation.recommendations:
            add(f"- {escape_md(r)}")
    else:
        add("- Review each observation above with the site owner or a qualified engineer.")
        add("- Re-run the assessment after any configuration change to compare results.")
    add("")
    add("**Configuration improvements suggested by observations:**")
    add("- Where security headers were observed missing, consider adding them via the web server or CDN configuration.")
    add("- Where TLS metadata was collected, compare certificate expiry and protocol support against current best practice.")
    add("")
    add("**Follow-up requiring explicit authorization:**")
    add("- Any active testing, authenticated testing, or penetration testing requires separate written authorization and is out of scope for Mantis.")
    add("")
    add("No recommendation above is a confirmed vulnerability. All are conservative, evidence-based suggestions.")
    add("")

    # ── 7. Footer ─────────────────────────────────────────────────
    add("## 7. Report Metadata")
    add("")
    add(f"- Report format version: {REPORT_FORMAT_VERSION}")
    add(f"- Evidence schema version: {assessment.schema_version}")
    if interpretation is not None and interpretation.status == "completed":
        add(f"- Interpretation schema version: {interpretation.schema_version}")
        add(f"- Interpretation prompt version: {escape_md(interpretation.prompt_version)}")
    add(f"- Generated at (UTC): {escape_md(generated_at)}")
    add("")
    add("---")
    add("_Generated by Mantis. Bounded reconnaissance only. Not a penetration "
        "test and not a guarantee of security. Website-derived and AI-derived "
        "text is quoted as untrusted data._")
    add("")

    return "\n".join(lines)


def generate_and_save_report(
    store,
    assessment_id: str,
    directory: Path | str | None = None,
    interpretation=None,
) -> Path:
    """Load assessment + best interpretation, render, and save atomically.

    - Uses the supplied `interpretation` if given; otherwise picks the
      newest interpretation with status 'completed' (if any).
    - Raises AssessmentNotFoundError / StorageError from the store,
      ReportPathError / ReportWriteError on output problems.
    - A failure here never alters the stored assessment or evidence.
    """
    assessment = store.get_assessment(assessment_id)

    note = ""
    if interpretation is None:
        try:
            interps = store.get_interpretations(assessment_id)
        except Exception:
            interps = []
            note = ("Interpretation storage could not be read; proceeding with "
                    "an evidence-only report.")
        if interps:
            completed = [i for i in interps if i.status == "completed"]
            if completed:
                interpretation = completed[0]  # newest first from the store
            else:
                newest = interps[0]
                note = (f"The most recent AI interpretation has status "
                        f"'{newest.status}' and is not included. Evidence-only "
                        f"report generated instead.")

    content = render_report(assessment, interpretation, interpretation_note=note)

    out_dir = Path(directory) if directory else DEFAULT_REPORT_DIR
    filename = safe_report_filename(assessment_id)
    path = unique_report_path(out_dir, filename)
    write_report_atomic(path, content)
    log.info("Report written to %s", path)
    return path