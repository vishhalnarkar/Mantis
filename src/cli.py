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
        console.print("[info]3.[/] ChatBot")
        console.print("[info]4.[/] Exit")
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
            console.print("[warning]⚠ ChatBot functionality is not implemented yet.[/]")

        elif choice == "4":
            console.print("[dim]Goodbye! 👋[/]")
            should_exit = True

        else:
            console.print("[error]✘ Invalid choice. Please try again.[/]")
