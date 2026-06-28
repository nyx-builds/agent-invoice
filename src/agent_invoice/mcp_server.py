"""MCP server for Agent Invoice — enables any MCP-compatible agent to manage billing."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .models import CURRENCIES, InvoiceStatus, RecurrenceFrequency, format_amount
from .service import InvoiceService
from .store import InvoiceStore

app = Server("agent-invoice")


def _get_service() -> InvoiceService:
    return InvoiceService(InvoiceStore())


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_invoice",
            description="Create a new invoice for a client. The client must already exist. Supports tax rates per line item, currency, and discounts.",
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
                                "tax_rate": {"type": "number", "description": "Tax rate as percentage (e.g. 8.5 for 8.5%)"},
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
                    "currency": {
                        "type": "string",
                        "description": "Currency code (e.g. USD, EUR, GBP). Uses client default if not specified.",
                    },
                    "tax_rate": {
                        "type": "number",
                        "description": "Invoice-level default tax rate % for items without their own tax",
                    },
                    "discount_amount": {
                        "type": "number",
                        "description": "Flat discount amount to apply",
                    },
                },
                "required": ["client", "items"],
            },
        ),
        Tool(
            name="list_invoices",
            description="List invoices with optional filtering by status, client, or currency.",
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
                    "currency": {
                        "type": "string",
                        "description": "Filter by currency code",
                    },
                },
            },
        ),
        Tool(
            name="get_invoice",
            description="Get full details of a specific invoice by ID, including tax, discounts, and totals.",
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
            name="apply_discount",
            description="Apply a flat discount to an invoice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Discount amount",
                    },
                },
                "required": ["invoice_id", "amount"],
            },
        ),
        Tool(
            name="add_client",
            description="Register a new client that can be billed. Supports default currency.",
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
                    "currency": {
                        "type": "string",
                        "description": "Default billing currency code (default: USD)",
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
            description="Get a summary of all earnings — total invoiced, paid, pending, overdue, tax, and discounts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "description": "Filter by currency code",
                    },
                },
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
        Tool(
            name="create_recurring",
            description="Create a recurring invoice template that can generate invoices on a schedule.",
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
                                "tax_rate": {"type": "number"},
                            },
                            "required": ["description", "unit_price"],
                        },
                    },
                    "frequency": {
                        "type": "string",
                        "enum": ["weekly", "biweekly", "monthly", "quarterly", "yearly"],
                        "description": "Recurrence frequency (default: monthly)",
                    },
                    "due_days": {
                        "type": "integer",
                        "description": "Days until due date for generated invoices (default: 30)",
                    },
                    "notes": {"type": "string"},
                    "currency": {"type": "string"},
                    "tax_rate": {"type": "number", "description": "Invoice-level tax rate %"},
                    "discount_amount": {"type": "number"},
                },
                "required": ["client", "items"],
            },
        ),
        Tool(
            name="list_recurring",
            description="List recurring invoice templates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "active_only": {
                        "type": "boolean",
                        "description": "Only show active recurring invoices (default: false)",
                    },
                },
            },
        ),
        Tool(
            name="generate_from_recurring",
            description="Generate an invoice from a recurring template.",
            inputSchema={
                "type": "object",
                "properties": {
                    "recurring_id": {
                        "type": "string",
                        "description": "The recurring invoice ID",
                    },
                },
                "required": ["recurring_id"],
            },
        ),
        Tool(
            name="pause_recurring",
            description="Pause a recurring invoice template.",
            inputSchema={
                "type": "object",
                "properties": {
                    "recurring_id": {
                        "type": "string",
                        "description": "The recurring invoice ID to pause",
                    },
                },
                "required": ["recurring_id"],
            },
        ),
        Tool(
            name="resume_recurring",
            description="Resume a paused recurring invoice template.",
            inputSchema={
                "type": "object",
                "properties": {
                    "recurring_id": {
                        "type": "string",
                        "description": "The recurring invoice ID to resume",
                    },
                },
                "required": ["recurring_id"],
            },
        ),
        Tool(
            name="process_due_recurring",
            description="Generate invoices for all recurring templates that are due. Call this periodically (e.g. daily) to auto-generate invoices.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_numbering_config",
            description="Get the current invoice numbering configuration.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="update_numbering_config",
            description="Update the invoice numbering configuration (prefix, separator, digits).",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Invoice number prefix (e.g. INV, BIL, 2024)",
                    },
                    "separator": {
                        "type": "string",
                        "description": "Separator between prefix and number (e.g. - or /)",
                    },
                    "digits": {
                        "type": "integer",
                        "description": "Number of digits (e.g. 4 for 0001)",
                    },
                    "next_number": {
                        "type": "integer",
                        "description": "Set the next invoice number",
                    },
                },
            },
        ),
        Tool(
            name="list_currencies",
            description="List all supported currency codes, symbols, and decimal places.",
            inputSchema={
                "type": "object",
                "properties": {},
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
                currency=arguments.get("currency"),
                tax_rate=arguments.get("tax_rate"),
                discount_amount=arguments.get("discount_amount"),
            )
            return _json_result({
                "id": inv.id,
                "client": inv.client_name,
                "currency": inv.currency,
                "subtotal": inv.subtotal,
                "tax": inv.total_tax,
                "discount": inv.discount_amount,
                "total": inv.total,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "status": inv.status.value,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_invoices":
        status = InvoiceStatus(arguments["status"]) if "status" in arguments else None
        client = arguments.get("client")
        currency = arguments.get("currency")
        invoices = svc.list_invoices(status=status, client=client, currency=currency)
        result = []
        for inv in invoices:
            result.append({
                "id": inv.id,
                "client": inv.client_name,
                "currency": inv.currency,
                "status": inv.status.value,
                "subtotal": inv.subtotal,
                "tax": inv.total_tax,
                "total": inv.total,
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
            return _json_result({"id": inv.id, "status": "paid", "total": inv.total, "currency": inv.currency})
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

    elif name == "apply_discount":
        try:
            inv = svc.apply_discount(arguments["invoice_id"], arguments["amount"])
            return _json_result({"id": inv.id, "discount": inv.discount_amount, "total": inv.total})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "add_client":
        try:
            c = svc.add_client(
                name=arguments["name"],
                email=arguments.get("email"),
                address=arguments.get("address"),
                currency=arguments.get("currency", "USD"),
            )
            return _json_result({"id": c.id, "name": c.name, "email": c.email, "currency": c.currency})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_clients":
        clients = svc.list_clients()
        return _json_result([{"id": c.id, "name": c.name, "email": c.email, "currency": c.currency} for c in clients])

    elif name == "earnings_summary":
        summary = svc.earnings_summary(currency=arguments.get("currency"))
        return _json_result(summary.model_dump())

    elif name == "export_invoice":
        inv = svc.get_invoice(arguments["invoice_id"])
        if not inv:
            return _text_result(f"Invoice not found: {arguments['invoice_id']}")
        return _text_result(inv.to_markdown())

    elif name == "create_recurring":
        try:
            rec = svc.create_recurring(
                client_identifier=arguments["client"],
                line_items=arguments["items"],
                frequency=arguments.get("frequency", "monthly"),
                due_days=arguments.get("due_days", 30),
                notes=arguments.get("notes"),
                currency=arguments.get("currency"),
                tax_rate=arguments.get("tax_rate"),
                discount_amount=arguments.get("discount_amount"),
            )
            return _json_result({
                "id": rec.id,
                "client": rec.client_name,
                "frequency": rec.frequency.value,
                "currency": rec.currency,
                "total": rec.total,
                "next_date": str(rec.next_date) if rec.next_date else None,
                "active": rec.active,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_recurring":
        active_only = arguments.get("active_only", False)
        recurrings = svc.list_recurring(active_only=active_only)
        result = []
        for rec in recurrings:
            result.append({
                "id": rec.id,
                "client": rec.client_name,
                "frequency": rec.frequency.value,
                "currency": rec.currency,
                "total": rec.total,
                "active": rec.active,
                "next_date": str(rec.next_date) if rec.next_date else None,
                "generated_count": len(rec.invoice_ids),
            })
        return _json_result(result)

    elif name == "generate_from_recurring":
        try:
            inv = svc.generate_from_recurring(arguments["recurring_id"])
            return _json_result({
                "id": inv.id,
                "client": inv.client_name,
                "currency": inv.currency,
                "total": inv.total,
                "status": inv.status.value,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "pause_recurring":
        try:
            rec = svc.pause_recurring(arguments["recurring_id"])
            return _json_result({"id": rec.id, "active": False})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "resume_recurring":
        try:
            rec = svc.resume_recurring(arguments["recurring_id"])
            return _json_result({"id": rec.id, "active": True, "next_date": str(rec.next_date)})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "process_due_recurring":
        generated = svc.process_due_recurring()
        result = []
        for inv in generated:
            result.append({
                "id": inv.id,
                "client": inv.client_name,
                "currency": inv.currency,
                "total": inv.total,
            })
        return _json_result({"generated_count": len(result), "invoices": result})

    elif name == "get_numbering_config":
        config = svc.get_numbering_config()
        return _json_result({
            "prefix": config.prefix,
            "separator": config.separator,
            "digits": config.digits,
            "next_number": config.next_number,
            "next_formatted": config.format_number(),
        })

    elif name == "update_numbering_config":
        config = svc.update_numbering_config(
            prefix=arguments.get("prefix"),
            separator=arguments.get("separator"),
            digits=arguments.get("digits"),
            next_number=arguments.get("next_number"),
        )
        return _json_result({
            "prefix": config.prefix,
            "separator": config.separator,
            "digits": config.digits,
            "next_number": config.next_number,
            "next_formatted": config.format_number(),
        })

    elif name == "list_currencies":
        result = []
        for code, info in sorted(CURRENCIES.items()):
            result.append({
                "code": code,
                "symbol": info["symbol"],
                "name": info["name"],
                "decimals": info["decimals"],
            })
        return _json_result(result)

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
