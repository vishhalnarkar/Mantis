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
        console.print("[info]5.[/] Exit")
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

        elif choice == "4":
            from config import config as app_config
            from llm.comms import send_message

            if not app_config.gemini.is_configured:
                console.print("[error]✘ Gemini is not configured. Set GEMINI_API_KEY and GEMINI_MODEL in .env[/]")
                continue

            console.print("[accent]🤖 CyberSec ChatBot[/] [dim](type 'exit' or 'quit' to leave)[/]")
            console.print("[dim]System: You are a professional cybersecurity assistant. Answer questions about security concepts, best practices, and general cybersecurity knowledge. Do not provide exploitation instructions.[/]\n")

            system_msg = {
                "role": "system",
                "content": (
                    "You are a professional cybersecurity assistant. "
                    "Answer questions about security concepts, best practices, defensive security, "
                    "and general cybersecurity knowledge. Be helpful, accurate, and safety-conscious. "
                    "Do not provide exploitation instructions, malware code, or attack techniques. "
                    "Focus on defense, education, and awareness."
                ),
            }
            chat_history = [system_msg]

            while True:
                try:
                    user_input = console.input("[info]You: [/]").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Exiting chatbot.[/]")
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    console.print("[dim]Exiting chatbot.[/]")
                    break

                chat_history.append({"role": "user", "content": user_input})

                try:
                    reply = send_message(chat_history)
                    chat_history.append({"role": "assistant", "content": reply})
                    console.print(f"\n[success]Mantis: {reply}[/]\n")
                except Exception as e:
                    console.print(f"[error]✘ LLM error: {e}[/]")
                    # Remove the failed user message so retry works cleanly
                    chat_history.pop()
                    break

        elif choice == "5":
            console.print("[dim]Goodbye! 👋[/]")
            should_exit = True

        else:
            console.print("[error]✘ Invalid choice. Please try again.[/]")
