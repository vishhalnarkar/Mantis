from rich.panel import Panel
from rich.text import Text
from logger import console


def cli():
    should_exit = False
    while not should_exit:
        console.print()
        banner = Text.assemble(
            ("🦗 Mantis", "accent"),
            (" CLI", "info"),
        )
        console.print(Panel(banner, border_style="magenta", expand=False))
        console.print("[info]1.[/] Analyze Logs")
        console.print("[info]2.[/] Validate Target URL")
        console.print("[info]3.[/] Run Recon Assessment")
        console.print("[info]4.[/] ChatBot")
        console.print("[info]5.[/] Interpret Saved Assessment (AI)")
        console.print("[info]6.[/] Generate Report")
        console.print("[info]7.[/] Exit")
        console.print()

        choice = console.input("[accent]> Enter your choice: [/]").strip()

        if choice == "1":
            from tools.log_analyzer import analyze_logs
            log_text = console.input("[info]Paste or type your log text below (press Enter when done):\n> [/]")
            result = analyze_logs(log_text)

            if result["status"] == "success":
                console.print(f"[success]✔ {result['summary']}[/]")
                console.print(f"[info]  Lines processed: {result['line_count']}[/]")
            else:
                console.print(f"[error]✘ {result['summary']}[/]")
                for err in result.get("errors", []):
                    console.print(f"[error]  • {err}[/]")

        elif choice == "2":
            from target import validate_target, TargetValidationError, ValidatedTarget
            url = console.input("[info]Enter target URL (http/https): [/]").strip()
            if not url:
                console.print("[error]✘ No URL provided.[/]")
                continue

            console.print("[dim]Validating target...[/]")
            result = validate_target(url)

            if isinstance(result, TargetValidationError):
                console.print(f"[error]✘ Validation failed: {result.message}[/]")
                if result.detail:
                    console.print(f"[dim]  Detail: {result.detail}[/]")
            elif isinstance(result, ValidatedTarget):
                console.print("[success]✔ Target validated successfully.[/]")
                console.print(f"[info]  Scheme:    {result.parsed.scheme}[/]")
                console.print(f"[info]  Hostname:  {result.parsed.hostname}[/]")
                console.print(f"[info]  Port:      {result.parsed.port}[/]")
                console.print(f"[info]  Origin:    {result.parsed.scheme}://{result.parsed.hostname}:{result.parsed.port}[/]")
                console.print(f"[info]  Resolved:  {', '.join(result.resolution.addresses)}[/]")
                console.print(f"[dim]  Normalized: {result.parsed.normalized_url}[/]")

        elif choice == "3":
            from target import validate_target, TargetValidationError, ValidatedTarget
            from recon.orchestrator import run_assessment
            from recon.assessment import AssessmentStatus
            from recon.contract import ToolStatus

            url = console.input("[info]Enter target URL for recon (http/https): [/]").strip()
            if not url:
                console.print("[error]✘ No URL provided.[/]")
                continue

            console.print("[dim]Validating target...[/]")
            vt = validate_target(url)

            if isinstance(vt, TargetValidationError):
                console.print(f"[error]✘ Validation failed: {vt.message}[/]")
                if vt.detail:
                    console.print(f"[dim]  Detail: {vt.detail}[/]")
                continue

            console.print(f"[info]Running bounded recon assessment on {vt.parsed.hostname}...[/]")
            try:
                with console.status("[accent]Running recon tools...[/]", spinner="dots"):
                    assessment = run_assessment(vt)
            except KeyboardInterrupt:
                console.print("\n[warning]⚠ Assessment interrupted by user.[/]")
                continue

            # Display results
            status_color = {
                AssessmentStatus.COMPLETED: "success",
                AssessmentStatus.PARTIAL: "warning",
                AssessmentStatus.FAILED: "error",
                AssessmentStatus.CANCELLED: "warning",
            }
            color = status_color.get(assessment.status, "info")
            console.print(f"\n[{color}]Assessment {assessment.assessment_id}: {assessment.status.value.upper()}[/]")
            console.print(f"[dim]Target: {assessment.target_url}[/]")
            console.print(f"[dim]Duration: {assessment.started_at} → {assessment.completed_at}[/]\n")

            for tool_id in assessment.execution_order:
                tr = assessment.tool_results.get(tool_id)
                if tr is None:
                    console.print(f"  [dim]• {tool_id}: not run[/]")
                    continue
                icon = {
                    ToolStatus.SUCCESS: "[success]✔[/]",
                    ToolStatus.PARTIAL: "[warning]◐[/]",
                    ToolStatus.ERROR: "[error]✘[/]",
                    ToolStatus.UNAVAILABLE: "[dim]○[/]",
                    ToolStatus.BLOCKED: "[error]⊘[/]",
                    ToolStatus.SKIPPED: "[dim]→[/]",
                }.get(tr.status, "[dim]?[/]")
                console.print(f"  {icon} {tool_id}: {tr.status.value}")
                for err in tr.errors[:2]:
                    console.print(f"    [dim]{err}[/]")

            if assessment.errors:
                console.print("\n[error]Assessment errors:[/]")
                for e in assessment.errors:
                    console.print(f"  [error]• {e}[/]")
            if assessment.warnings:
                console.print("\n[warning]Warnings:[/]")
                for w in assessment.warnings:
                    console.print(f"  [warning]• {w}[/]")

            # Persist the assessment
            try:
                from storage.store import EvidenceStore, assessment_result_to_evidence
                evidence = assessment_result_to_evidence(assessment)
                store = EvidenceStore()
                store.save_assessment(evidence)
                console.print(f"\n[dim]💾 Assessment saved to local database.[/]")
            except Exception as e:
                console.print(f"\n[warning]⚠ Could not save assessment: {e}[/]")
                console.print("[dim]  In-memory results are still valid.[/]")
            else:
                console.print("[dim]  Tip: use option 5 for an optional AI interpretation.[/]")

        elif choice == "5":
            from storage.store import EvidenceStore, AssessmentNotFoundError, StorageError
            from analysis.analyzer import GeminiAnalyzer
            from analysis.models import InterpretationStatus

            try:
                store = EvidenceStore()
                listed = store.list_assessments(limit=10)
            except StorageError as e:
                console.print(f"[error]✘ Could not read assessment store: {e}[/]")
                continue

            if not listed:
                console.print("[warning]No saved assessments found. Run a recon assessment first (option 3).[/]")
                continue

            console.print("[info]Saved assessments (most recent first):[/]")
            for i, a in enumerate(listed, 1):
                console.print(
                    f"  [info]{i}.[/] {a['assessment_id']} — {a['target_hostname']} "
                    f"[dim]({a['status']}) saved {a['saved_at']}[/]"
                )

            idx = console.input("[info]Enter assessment number to interpret (blank to cancel): [/]").strip()
            if not idx:
                continue
            if not idx.isdigit() or not (1 <= int(idx) <= len(listed)):
                console.print("[error]✘ Invalid selection.[/]")
                continue

            target_id = listed[int(idx) - 1]["assessment_id"]
            try:
                assessment = store.get_assessment(target_id)
            except (AssessmentNotFoundError, StorageError) as e:
                console.print(f"[error]✘ {e}[/]")
                continue

            console.print("[dim]Interpreting evidence with Gemini (all website content is treated as untrusted data)...[/]")
            try:
                with console.status("[accent]Analyzing evidence...[/]", spinner="dots"):
                    interpretation = GeminiAnalyzer().analyze(assessment)
            except KeyboardInterrupt:
                console.print("\n[warning]⚠ Interpretation interrupted. Evidence is unchanged.[/]")
                continue

            status_style = {
                InterpretationStatus.COMPLETED.value: "success",
                InterpretationStatus.UNAVAILABLE.value: "warning",
                InterpretationStatus.INVALID_OUTPUT.value: "warning",
                InterpretationStatus.FAILED.value: "error",
            }.get(interpretation.status, "info")
            console.print(f"\n[{status_style}]Interpretation status: {interpretation.status}[/]")
            console.print(
                f"[dim]Prompt v{interpretation.prompt_version} | "
                f"output schema v{interpretation.schema_version} | "
                f"model: {interpretation.model_id or 'n/a'}[/]"
            )

            if interpretation.summary:
                console.print(f"\n[info]Summary:[/] {interpretation.summary}")

            if interpretation.observations:
                console.print("\n[info]Key observations:[/]")
                for o in interpretation.observations:
                    tag = " [warning](hypothesis)[/]" if o.is_hypothesis else ""
                    ids = f" [dim](evidence: {', '.join(o.evidence_ids)})[/]" if o.evidence_ids else " [dim](no citation)[/]"
                    console.print(f"  • {o.text}{tag}{ids}")

            if interpretation.interpretations:
                console.print("\n[warning]Possible implications (interpretations, not confirmed facts):[/]")
                for i in interpretation.interpretations:
                    ids = f" [dim](evidence: {', '.join(i.evidence_ids)})[/]" if i.evidence_ids else " [dim](no citation)[/]"
                    console.print(f"  • [confidence {i.confidence}] {i.text}{ids}")

            if interpretation.unsupported_citations:
                console.print(
                    f"\n[warning]⚠ {len(interpretation.unsupported_citations)} citation(s) "
                    f"referenced evidence not in this assessment and were flagged as unsupported.[/]"
                )

            if interpretation.limitations:
                console.print("\n[dim]Limitations:[/]")
                for l in interpretation.limitations:
                    console.print(f"  [dim]• {l}[/]")

            if interpretation.recommendations:
                console.print("\n[info]Safe manual verification steps:[/]")
                for r in interpretation.recommendations:
                    console.print(f"  • {r}")

            if interpretation.errors:
                console.print("\n[error]Details:[/]")
                for e in interpretation.errors:
                    console.print(f"  [error]• {e}[/]")

            # Persist the interpretation separately from raw evidence.
            try:
                store.save_interpretation(interpretation)
                console.print(f"\n[dim]💾 Interpretation {interpretation.interpretation_id} saved.[/]")
            except Exception as e:
                console.print(f"\n[warning]⚠ Could not save interpretation: {e}[/]")
                console.print("[dim]  The interpretation shown above is still valid in memory.[/]")

        elif choice == "6":
            from storage.store import EvidenceStore, AssessmentNotFoundError, StorageError
            from reporting.generator import generate_and_save_report, ReportPathError, ReportWriteError

            try:
                store = EvidenceStore()
                listed = store.list_assessments(limit=10)
            except StorageError as e:
                console.print(f"[error]✘ Could not read assessment store: {e}[/]")
                continue

            if not listed:
                console.print("[warning]No saved assessments found. Run a recon assessment first (option 3).[/]")
                continue

            console.print("[info]Saved assessments (most recent first):[/]")
            for i, a in enumerate(listed, 1):
                console.print(
                    f"  [info]{i}.[/] {a['assessment_id']} — {a['target_hostname']} "
                    f"[dim]({a['status']}) saved {a['saved_at']}[/]"
                )

            idx = console.input("[info]Enter assessment number to report (blank to cancel): [/]").strip()
            if not idx:
                continue
            if not idx.isdigit() or not (1 <= int(idx) <= len(listed)):
                console.print("[error]✘ Invalid selection.[/]")
                continue

            target_id = listed[int(idx) - 1]["assessment_id"]
            console.print("[dim]Generating Markdown report from persisted evidence...[/]")
            try:
                with console.status("[accent]Rendering report...[/]", spinner="dots"):
                    report_path = generate_and_save_report(store, target_id)
                console.print(f"[success]✔ Report saved to: {report_path}[/]")
            except AssessmentNotFoundError:
                console.print("[error]✘ Assessment not found.[/]")
            except ReportPathError as e:
                console.print(f"[error]✘ Invalid report path: {e}[/]")
            except ReportWriteError as e:
                console.print(f"[error]✘ Could not write report: {e}[/]")
            except StorageError as e:
                console.print(f"[error]✘ Storage error during report generation: {e}[/]")

        elif choice == "4":
            from config import config as app_config
            from chatbot.prompt import build_chatbot_system_prompt, CHATBOT_PROMPT_VERSION
            from chatbot.session import ChatSession, MAX_HISTORY_TURNS, MAX_USER_INPUT_CHARS

            if not app_config.gemini.is_configured:
                console.print("[error]✘ Gemini is not configured. Set GEMINI_API_KEY and GEMINI_MODEL in .env[/]")
                continue

            session = ChatSession(build_chatbot_system_prompt())
            # Defense in depth: never echo the configured key into errors.
            session.set_redact_secret(app_config.gemini.api_key)

            console.print("[accent]🤖 CyberSec ChatBot[/] [dim](prompt v" + CHATBOT_PROMPT_VERSION + ")[/]")
            console.print(
                "[dim]Q&A mode only — this chat never runs scans or tools. "
                "Type 'help' for commands, 'exit' to leave.[/]\n"
            )

            while True:
                try:
                    user_input = console.input("[info]You: [/]").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Exiting chatbot.[/]")
                    break

                if not user_input:
                    continue

                lowered = user_input.lower()
                if lowered in ("exit", "quit", "q"):
                    console.print("[dim]Exiting chatbot.[/]")
                    break
                if lowered in ("help", "?"):
                    console.print(
                        "[info]Commands:[/] exit|quit|q — leave · "
                        "help — this message · clear — forget conversation so far"
                    )
                    console.print(
                        f"[dim]History keeps the last {MAX_HISTORY_TURNS} exchanges "
                        f"and each message is capped at {MAX_USER_INPUT_CHARS} chars. "
                        "Nothing you type is saved to disk.[/]"
                    )
                    continue
                if lowered == "clear":
                    session.clear()
                    console.print("[dim]Conversation cleared.[/]")
                    continue

                result = session.ask(user_input)
                if result.ok:
                    console.print(f"\n[success]Mantis: {result.reply}[/]\n")
                else:
                    # Failed turn leaves history untouched — user can retry.
                    console.print(f"[error]✘ {result.error}[/]")
                    console.print("[dim]  (conversation state unchanged; you can retry)[/]")

        elif choice == "7":
            console.print("[dim]Goodbye! 👋[/]")
            should_exit = True

        else:
            console.print("[error]✘ Invalid choice. Please try again.[/]")
