"""MCP server for Agent Invoice — enables any MCP-compatible agent to manage billing."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ..models import InvoiceStatus
from ..service import InvoiceService
from ..store import InvoiceStore

app = Server("agent-invoice")


def _get_service() -> InvoiceService:
    return InvoiceService(InvoiceStore())


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_invoice",
            description="Create a new invoice for a client. The client must already exist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {
                        "type": "string",
                        "description": "Client ID or name",
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "quantity": {"type": "number", "default": 1},
                                "unit_price": {"type": "number"},
                            },
                            "required": ["description", "unit_price"],
                        },
                        "description": "Line items for the invoice",
                    },
                    "due_days": {
                        "type": "integer",
                        "description": "Days until due date (default: 30)",
                        "default": 30,
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes",
                    },
                },
                "required": ["client", "items"],
            },
        ),
        Tool(
            name="list_invoices",
            description="List invoices with optional filtering by status or client.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
                        "description": "Filter by invoice status",
                    },
                    "client": {
                        "type": "string",
                        "description": "Filter by client ID or name",
                    },
                },
            },
        ),
        Tool(
            name="get_invoice",
            description="Get full details of a specific invoice by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID (e.g. INV-0001)",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="mark_paid",
            description="Mark an invoice as paid.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to mark as paid",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="mark_sent",
            description="Mark an invoice as sent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to mark as sent",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="cancel_invoice",
            description="Cancel an invoice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to cancel",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="add_client",
            description="Register a new client that can be billed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Client name",
                    },
                    "email": {
                        "type": "string",
                        "description": "Client email",
                    },
                    "address": {
                        "type": "string",
                        "description": "Client address",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="list_clients",
            description="List all registered clients.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="earnings_summary",
            description="Get a summary of all earnings — total invoiced, paid, pending, and overdue.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="export_invoice",
            description="Export an invoice as markdown text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to export",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
    ]


def _json_result(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    svc = _get_service()

    if name == "create_invoice":
        try:
            inv = svc.create_invoice(
                client_identifier=arguments["client"],
                line_items=arguments["items"],
                due_days=arguments.get("due_days", 30),
                notes=arguments.get("notes"),
            )
            return _json_result({
                "id": inv.id,
                "client": inv.client_name,
                "subtotal": inv.subtotal,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "status": inv.status.value,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_invoices":
        status = InvoiceStatus(arguments["status"]) if "status" in arguments else None
        client = arguments.get("client")
        invoices = svc.list_invoices(status=status, client=client)
        result = []
        for inv in invoices:
            result.append({
                "id": inv.id,
                "client": inv.client_name,
                "status": inv.status.value,
                "subtotal": inv.subtotal,
                "due_date": str(inv.due_date) if inv.due_date else None,
            })
        return _json_result(result)

    elif name == "get_invoice":
        inv = svc.get_invoice(arguments["invoice_id"])
        if not inv:
            return _text_result(f"Invoice not found: {arguments['invoice_id']}")
        return _json_result(inv.model_dump(mode="json"))

    elif name == "mark_paid":
        try:
            inv = svc.mark_paid(arguments["invoice_id"])
            return _json_result({"id": inv.id, "status": "paid", "subtotal": inv.subtotal})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "mark_sent":
        try:
            inv = svc.mark_sent(arguments["invoice_id"])
            return _json_result({"id": inv.id, "status": "sent"})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "cancel_invoice":
        try:
            inv = svc.cancel_invoice(arguments["invoice_id"])
            return _json_result({"id": inv.id, "status": "cancelled"})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "add_client":
        try:
            c = svc.add_client(
                name=arguments["name"],
                email=arguments.get("email"),
                address=arguments.get("address"),
            )
            return _json_result({"id": c.id, "name": c.name, "email": c.email})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_clients":
        clients = svc.list_clients()
        return _json_result([{"id": c.id, "name": c.name, "email": c.email} for c in clients])

    elif name == "earnings_summary":
        summary = svc.earnings_summary()
        return _json_result(summary.model_dump())

    elif name == "export_invoice":
        inv = svc.get_invoice(arguments["invoice_id"])
        if not inv:
            return _text_result(f"Invoice not found: {arguments['invoice_id']}")
        return _text_result(inv.to_markdown())

    else:
        return _text_result(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run_server() -> None:
    """Entry point for the MCP server."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run_server()
