from registry import TOOL_REGISTRY
def executor(tool_name, arguments):
    print(f"Executing tool: {tool_name} with arguments: {arguments}")
    if tool_name not in TOOL_REGISTRY:
        return {
                    "status": "error", 
                    "summary": "Tool not found in the registry.", 
                    "errors": ["Tool not found."]
                }
    print(f"Tool {tool_name} found in registry. Executing...")
    tool_function = TOOL_REGISTRY[tool_name]
    return tool_function(**arguments)

print(executor("analyze_logs", {"log_text": "Your log text here"}))