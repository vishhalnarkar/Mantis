def exe(tool_name, *args, **kwargs):
    """
    Executes the specified tool with the provided arguments.

    Args:
        tool_name (str): The name of the tool to execute.
        *args: Positional arguments to pass to the tool function.
        **kwargs: Keyword arguments to pass to the tool function.

    Returns:
        The result of the tool execution.

    Raises:
        ValueError: If the specified tool is not found in the registry.
    """
    from tools.registry import TOOL_REGISTRY

    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Tool '{tool_name}' not found in the registry.")

    tool_function = TOOL_REGISTRY[tool_name]
    return tool_function(*args, **kwargs)

def executor(tool_name, arguments):
    from tools.registry import TOOL_REGISTRY

    if tool_name not in TOOL_REGISTRY:
        return {
                    "status": "error", 
                    "summary": "Tool not found in the registry.", 
                    "errors": ["Tool not found."]
                }

    tool_function = TOOL_REGISTRY[tool_name]
    return tool_function(arguments)