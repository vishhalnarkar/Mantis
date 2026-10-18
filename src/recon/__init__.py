"""Reconnaissance tool package.

Each module exposes one tool that accepts a ValidatedTarget and returns
a ToolResult. Tools are independently testable and do not print to the
terminal; they return structured data for the orchestrator (Stage 05).
"""
