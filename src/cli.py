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
        console.print("[info]2.[/] ChatBot")
        console.print("[info]3.[/] Exit")
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
            console.print("[warning]⚠ ChatBot functionality is not implemented yet.[/]")

        elif choice == "3":
            console.print("[dim]Goodbye! 👋[/]")
            should_exit = True

        else:
            console.print("[error]✘ Invalid choice. Please try again.[/]")
