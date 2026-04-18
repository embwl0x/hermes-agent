"""On-demand MCP bridge tools.

These tools keep MCP server discovery out of the default model request while
still giving agents an explicit path to use MCP when a task needs it.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import registry


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _truncate(text: str, limit: int = 600) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _discover_mcp() -> list[str]:
    from tools.mcp_tool import discover_mcp_tools

    return discover_mcp_tools()


def _mcp_tool_entries(
    query: str = "",
    include_parameters: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = str(query or "").strip().lower()
    try:
        limit = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        limit = 50

    entries: list[dict[str, Any]] = []
    for tool_name in registry.get_all_tool_names():
        toolset = registry.get_toolset_for_tool(tool_name) or ""
        if not toolset.startswith("mcp-"):
            continue
        schema = registry.get_schema(tool_name) or {}
        description = schema.get("description", "")
        haystack = f"{tool_name} {toolset} {description}".lower()
        if query and query not in haystack:
            continue

        entry: dict[str, Any] = {
            "name": tool_name,
            "server": toolset.removeprefix("mcp-"),
            "description": _truncate(description),
        }
        parameters = schema.get("parameters")
        if include_parameters and isinstance(parameters, dict):
            entry["parameters"] = parameters
        elif isinstance(parameters, dict):
            props = parameters.get("properties")
            if isinstance(props, dict) and props:
                entry["parameter_names"] = sorted(props.keys())
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def mcp_list_tools(
    query: str = "",
    include_parameters: bool = False,
    limit: int = 50,
) -> str:
    """Discover configured MCP servers and list their tools on demand."""
    try:
        discovered = _discover_mcp()
        tools = _mcp_tool_entries(
            query=query,
            include_parameters=include_parameters,
            limit=limit,
        )
        return _json({
            "tools": tools,
            "count": len(tools),
            "discovered_count": len(discovered),
            "hint": "Call mcp_call_tool with one of these exact tool names and an arguments object.",
        })
    except Exception as exc:
        return _json({
            "error": f"MCP discovery failed: {type(exc).__name__}: {exc}",
        })


def _resolve_tool_name(args: dict[str, Any]) -> str:
    tool_name = str(args.get("tool_name") or "").strip()
    if tool_name:
        return tool_name

    server = str(args.get("server") or "").strip()
    tool = str(args.get("tool") or "").strip()
    if not server or not tool:
        return ""

    from tools.mcp_tool import sanitize_mcp_name_component

    return (
        f"mcp_{sanitize_mcp_name_component(server)}_"
        f"{sanitize_mcp_name_component(tool)}"
    )


def _matching_tools(query: str, limit: int = 10) -> list[str]:
    query = str(query or "").strip().lower()
    matches = []
    for entry in _mcp_tool_entries(query=query, limit=limit):
        name = entry.get("name")
        if isinstance(name, str):
            matches.append(name)
    return matches


def mcp_call_tool(args: dict[str, Any], **kwargs) -> str:
    """Discover MCP tools on demand and dispatch one exact MCP tool call."""
    try:
        _discover_mcp()
    except Exception as exc:
        return _json({
            "error": f"MCP discovery failed: {type(exc).__name__}: {exc}",
        })

    tool_name = _resolve_tool_name(args)
    if not tool_name:
        return _json({
            "error": "Missing MCP tool name. Call mcp_list_tools first, then pass tool_name.",
        })

    toolset = registry.get_toolset_for_tool(tool_name)
    if not toolset or not toolset.startswith("mcp-"):
        return _json({
            "error": f"Unknown MCP tool: {tool_name}",
            "matches": _matching_tools(tool_name),
            "hint": "Call mcp_list_tools with a query to find the exact MCP tool name.",
        })

    arguments = args.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _json({"error": "arguments must be an object"})

    return registry.dispatch(tool_name, arguments, task_id=kwargs.get("task_id"))


MCP_LIST_TOOLS_SCHEMA = {
    "name": "mcp_list_tools",
    "description": (
        "Discover configured MCP servers on demand and list available MCP tools. "
        "Use this only when MCP access is needed; normal chats do not preload MCP schemas."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional filter for server, tool name, or description.",
            },
            "include_parameters": {
                "type": "boolean",
                "description": "Include full parameter schemas for listed tools.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum tools to return, capped at 100.",
            },
        },
        "additionalProperties": False,
    },
}

MCP_CALL_TOOL_SCHEMA = {
    "name": "mcp_call_tool",
    "description": (
        "Call a specific MCP tool after discovering it with mcp_list_tools. "
        "Pass the exact MCP tool name plus its arguments object."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Exact tool name returned by mcp_list_tools, such as mcp_server_tool.",
            },
            "server": {
                "type": "string",
                "description": "Optional MCP server name when tool_name is not provided.",
            },
            "tool": {
                "type": "string",
                "description": "Optional raw MCP tool name when tool_name is not provided.",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments to pass to the MCP tool.",
                "additionalProperties": True,
            },
        },
        "additionalProperties": False,
    },
}

registry.register(
    name="mcp_list_tools",
    toolset="mcp",
    schema=MCP_LIST_TOOLS_SCHEMA,
    handler=lambda args, **kw: mcp_list_tools(
        query=args.get("query", ""),
        include_parameters=bool(args.get("include_parameters", False)),
        limit=args.get("limit", 50),
    ),
    emoji="MCP",
)

registry.register(
    name="mcp_call_tool",
    toolset="mcp",
    schema=MCP_CALL_TOOL_SCHEMA,
    handler=mcp_call_tool,
    emoji="MCP",
)
