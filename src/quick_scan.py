"""Quick Scan: end-to-end pipeline.

Chains target validation -> recon assessment -> persistence -> AI analysis
into a single seamless flow. Individual CLI menu options for each step
remain available for advanced/manual use, but Quick Scan is the primary
user-facing workflow.
"""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from logger import console, get_logger
from target import validate_target, TargetValidationError, ValidatedTarget
from recon.orchestrator import run_assessment
from recon.assessment import AssessmentResult, AssessmentStatus
from recon.contract import ToolStatus
from storage.store import EvidenceStore, assessment_result_to_evidence, StorageError
from storage.models import EvidenceAssessment
from analysis.analyzer import GeminiAnalyzer
from analysis.models import InterpretationResult, InterpretationStatus
from config import config

log = get_logger("quick_scan")


def run_quick_scan(url: str) -> bool:
    """Execute the full quick-scan pipeline against *url*.

    Returns True if the pipeline completed (even partially),
    False if it was aborted before recon could start.
    """
    console.print()
    console.print(
        Panel(
            Text.assemble(("🦗 Quick Scan", "accent")),
            border_style="magenta",
            expand=False,
        )
    )
    console.print(f"[info]Target:[/] {url}\n")

    # ── Step 1: Validate ────────────────────────────────────────────
    console.print("[accent]━━━ Step 1/4: Target Validation ━━━[/]")
    validated = _step_validate(url)
    if validated is None:
        return False

    # ── Step 2: Recon ───────────────────────────────────────────────
    console.print("\n[accent]━━━ Step 2/4: Reconnaissance ━━━[/]")
    assessment = _step_recon(validated)
    if assessment is None:
        return False

    # ── Step 3: Persist ─────────────────────────────────────────────
    console.print("\n[accent]━━━ Step 3/4: Saving Evidence ━━━[/]")
    evidence = _step_persist(assessment)
    if evidence is None:
        return False

    # ── Step 4: AI Analysis ─────────────────────────────────────────
    console.print("\n[accent]━━━ Step 4/4: AI Analysis ━━━[/]")
    interpretation = _step_analyze(evidence)

    # ── Summary ─────────────────────────────────────────────────────
    _print_summary(assessment, evidence, interpretation)
    return True


# ── Pipeline steps ────────────────────────────────────────────────────


def _step_validate(url: str) -> ValidatedTarget | None:
    """Validate the target URL. Returns None on failure."""
    result = validate_target(url)

    if isinstance(result, TargetValidationError):
        console.print(f"[error]✘ Validation failed: {result.message}[/]")
        if result.detail:
            console.print(f"[dim]  Detail: {result.detail}[/]")
        log.error("Target validation failed: %s", result.message)
        return None

    console.print("[success]✔ Target validated.[/]")
    console.print(f"  [info]Hostname:[/] {result.parsed.hostname}")
    console.print(f"  [info]Port:[/]     {result.parsed.port}")
    ips = ", ".join(result.resolution.addresses) if result.resolution.addresses else "none"
    console.print(f"  [info]Resolved:[/] {ips}")
    log.info("Target validated: %s -> %s", result.parsed.hostname, ips)
    return result


def _step_recon(target: ValidatedTarget) -> AssessmentResult | None:
    """Run the bounded recon assessment. Returns None on hard failure."""
    console.print(f"[info]Running recon on [accent]{target.parsed.hostname}[/]...[/]")
    try:
        with console.status("[accent]Scanning...[/]", spinner="dots"):
            assessment = run_assessment(target)
    except KeyboardInterrupt:
        console.print("\n[warning]⚠ Scan interrupted by user.[/]")
        log.warning("Recon assessment interrupted by user.")
        return None
    except Exception as e:
        console.print(f"\n[error]✘ Recon failed unexpectedly: {e}[/]")
        log.exception("Recon assessment crashed: %s", e)
        return None

    _print_recon_table(assessment)
    log.info(
        "Recon finished: %s (%d tools)",
        assessment.status.value,
        len(assessment.tool_results),
    )
    return assessment


def _step_persist(assessment: AssessmentResult) -> EvidenceAssessment | None:
    """Save the assessment to the local store. Returns None on failure."""
    try:
        evidence = assessment_result_to_evidence(assessment)
        store = EvidenceStore()
        store.save_assessment(evidence)
        console.print(
            f"[success]✔ Evidence saved.[/] "
            f"[dim](id: {evidence.assessment_id})[/]"
        )
        log.info("Evidence persisted: %s", evidence.assessment_id)
        return evidence
    except StorageError as e:
        console.print(f"[warning]⚠ Could not save evidence: {e}[/]")
        console.print(
            "[dim]  Continuing without persistence — "
            "AI analysis will use in-memory data.[/]"
        )
        log.warning("Evidence persistence failed: %s", e)
        return assessment_result_to_evidence(assessment)
    except Exception as e:
        console.print(f"[warning]⚠ Unexpected save error: {e}[/]")
        log.warning("Unexpected persistence error: %s", e)
        return assessment_result_to_evidence(assessment)


def _step_analyze(evidence: EvidenceAssessment) -> InterpretationResult | None:
    """Run AI analysis if Gemini is configured. Returns None otherwise."""
    if not config.gemini.is_configured:
        console.print("[warning]⚠ Gemini not configured — skipping AI analysis.[/]")
        console.print(
            "[dim]  Set GEMINI_API_KEY and GEMINI_MODEL in .env to enable.[/]"
        )
        log.info("AI analysis skipped: Gemini not configured.")
        return None

    console.print("[info]Sending evidence to AI for analysis...[/]")
    try:
        with console.status("[accent]AI is thinking...[/]", spinner="dots"):
            analyzer = GeminiAnalyzer()
            interpretation = analyzer.analyze(evidence)
    except KeyboardInterrupt:
        console.print("\n[warning]⚠ AI analysis interrupted.[/]")
        log.warning("AI analysis interrupted by user.")
        return None
    except Exception as e:
        console.print(f"[error]✘ AI analysis failed: {e}[/]")
        log.exception("AI analysis crashed: %s", e)
        return None

    _print_interpretation(interpretation)

    # Try to persist the interpretation
    try:
        store = EvidenceStore()
        store.save_interpretation(interpretation)
        console.print(
            f"[dim]💾 Interpretation {interpretation.interpretation_id} saved.[/]"
        )
    except Exception as e:
        console.print(f"[dim]⚠ Could not save interpretation: {e}[/]")

    log.info("AI analysis completed: %s", interpretation.status)
    return interpretation


# ── Display helpers ───────────────────────────────────────────────────


def _print_recon_table(assessment: AssessmentResult) -> None:
    """Render a rich table of per-tool results."""
    status_style = {
        AssessmentStatus.COMPLETED: "success",
        AssessmentStatus.PARTIAL: "warning",
        AssessmentStatus.FAILED: "error",
        AssessmentStatus.CANCELLED: "warning",
    }
    color = status_style.get(assessment.status, "info")
    console.print(
        f"\n[{color}]Assessment {assessment.status.value.upper()}[/] "
        f"[dim](id: {assessment.assessment_id})[/]"
    )

    table = Table(show_header=True, header_style="accent", expand=False, padding=(0, 1))
    table.add_column("Tool", style="info", min_width=18)
    table.add_column("Status", min_width=10)
    table.add_column("Details", style="dim", max_width=50)

    icon_map = {
        ToolStatus.SUCCESS: "[success]✔ success[/]",
        ToolStatus.PARTIAL: "[warning]◐ partial[/]",
        ToolStatus.ERROR: "[error]✘ error[/]",
        ToolStatus.UNAVAILABLE: "[dim]○ unavailable[/]",
        ToolStatus.BLOCKED: "[error]⊘ blocked[/]",
        ToolStatus.SKIPPED: "[dim]→ skipped[/]",
    }

    for tool_id in assessment.execution_order:
        tr = assessment.tool_results.get(tool_id)
        if tr is None:
            table.add_row(tool_id, "[dim]— not run[/]", "")
            continue
        status_cell = icon_map.get(tr.status, f"[dim]? {tr.status.value}[/]")
        detail = ""
        if tr.errors:
            detail = tr.errors[0][:50]
        elif tr.observations:
            keys = list(tr.observations.keys())[:3]
            detail = ", ".join(keys)
        table.add_row(tool_id, status_cell, detail)

    console.print(table)

    if assessment.warnings:
        for w in assessment.warnings:
            console.print(f"  [warning]⚠ {w}[/]")


def _print_interpretation(interp: InterpretationResult) -> None:
    """Render AI analysis results."""
    status_style = {
        InterpretationStatus.COMPLETED.value: "success",
        InterpretationStatus.UNAVAILABLE.value: "warning",
        InterpretationStatus.INVALID_OUTPUT.value: "warning",
        InterpretationStatus.FAILED.value: "error",
    }
    color = status_style.get(interp.status, "info")
    console.print(f"\n[{color}]AI Analysis: {interp.status}[/]")

    if interp.summary:
        console.print(f"\n[info]Summary:[/]\n{interp.summary}")

    if interp.observations:
        console.print("\n[info]Observations:[/]")
        for o in interp.observations:
            tag = " [warning](hypothesis)[/]" if o.is_hypothesis else ""
            evid = (
                f" [dim]← {', '.join(o.evidence_ids)}[/]"
                if o.evidence_ids
                else ""
            )
            console.print(f"  • {o.text}{tag}{evid}")

    if interp.interpretations:
        console.print("\n[warning]Implications:[/]")
        for i in interp.interpretations:
            conf = f"[dim][{i.confidence}][/ ]" if i.confidence else ""
            evid = (
                f" [dim]← {', '.join(i.evidence_ids)}[/]"
                if i.evidence_ids
                else ""
            )
            console.print(f"  • {conf} {i.text}{evid}")

    if interp.recommendations:
        console.print("\n[info]Recommendations:[/]")
        for r in interp.recommendations:
            console.print(f"  • {r}")

    if interp.limitations:
        console.print("\n[dim]Limitations:[/]")
        for lim in interp.limitations:
            console.print(f"  [dim]• {lim}[/]")

    if interp.unsupported_citations:
        console.print(
            f"\n[warning]⚠ {len(interp.unsupported_citations)} citation(s) "
            f"referenced evidence not in this assessment.[/]"
        )

    if interp.errors:
        console.print("\n[error]Errors:[/]")
        for e in interp.errors:
            console.print(f"  [error]• {e}[/]")


def _print_summary(
    assessment: AssessmentResult | None,
    evidence: EvidenceAssessment | None,
    interpretation: InterpretationResult | None,
) -> None:
    """Print a final summary panel."""
    console.print()
    parts = []
    if assessment:
        parts.append(f"Recon: [info]{assessment.status.value}[/]")
    if evidence:
        parts.append(f"Evidence ID: [accent]{evidence.assessment_id}[/]")
    if interpretation:
        parts.append(f"AI: [info]{interpretation.status}[/]")
    elif config.gemini.is_configured:
        parts.append("AI: [warning]skipped[/]")
    else:
        parts.append("AI: [dim]not configured[/]")

    summary_text = "  |  ".join(parts) if parts else "[dim]No results[/]"
    console.print(
        Panel(
            Text.from_markup(summary_text),
            title="🦗 Quick Scan Complete",
            border_style="magenta",
            expand=False,
        )
    )
