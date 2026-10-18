from tools.registry import TOOL_REGISTRY
from logger import get_logger, console

log = get_logger("executor")


def executor(tool_name: str, arguments: dict):
    log.info("Executing tool: %s with arguments: %s", tool_name, arguments)

    if tool_name not in TOOL_REGISTRY:
        log.error("Tool '%s' not found in registry.", tool_name)
        console.print(f"[error]✘ Tool '{tool_name}' not found in registry.[/]")
        return {
            "status": "error",
            "summary": "Tool not found in the registry.",
            "errors": ["Tool not found."],
        }

    log.debug("Tool '%s' found. Executing...", tool_name)
    console.print(f"[info]⏳ Running tool: [accent]{tool_name}[/]...[/]")
    tool_function = TOOL_REGISTRY[tool_name]
    result = tool_function(**arguments)
    log.info("Tool '%s' finished with status: %s", tool_name, result.get("status"))
    return result
