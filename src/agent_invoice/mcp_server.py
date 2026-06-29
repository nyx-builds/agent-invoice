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
                        "enum": ["draft", "sent", "paid", "overdue", "cancelled", "partially_paid"],
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
            description="Get full details of a specific invoice by ID, including tax, discounts, payments, and totals.",
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
            description="Mark an invoice as fully paid. For partial payments, use record_payment instead.",
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
            name="record_payment",
            description="Record a payment against an invoice. Supports partial payments. If the payment covers the full remaining balance, the invoice is automatically marked as paid.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to record the payment against",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Payment amount",
                    },
                    "method": {
                        "type": "string",
                        "description": "Payment method (e.g. bank_transfer, credit_card, crypto, cash)",
                    },
                    "reference": {
                        "type": "string",
                        "description": "External payment reference or transaction ID",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Payment notes",
                    },
                    "payment_date": {
                        "type": "string",
                        "description": "Payment date in YYYY-MM-DD format (defaults to today)",
                    },
                },
                "required": ["invoice_id", "amount"],
            },
        ),
        Tool(
            name="list_payments",
            description="List all payments recorded against an invoice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="remove_payment",
            description="Remove a payment from an invoice. The invoice status will be recalculated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID",
                    },
                    "payment_id": {
                        "type": "string",
                        "description": "The payment ID to remove",
                    },
                },
                "required": ["invoice_id", "payment_id"],
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
            description="Export an invoice as markdown text, JSON, or PDF. PDF export returns the file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to export",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "json", "pdf"],
                        "description": "Export format (default: markdown)",
                        "default": "markdown",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (for PDF). Auto-generated if not specified.",
                    },
                    "company_name": {
                        "type": "string",
                        "description": "Company name for PDF header",
                    },
                    "company_address": {
                        "type": "string",
                        "description": "Company address for PDF",
                    },
                    "company_email": {
                        "type": "string",
                        "description": "Company email for PDF",
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
        Tool(
            name="update_client",
            description="Update a client's details (name, email, address, currency).",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Client ID or name to update",
                    },
                    "name": {
                        "type": "string",
                        "description": "New name",
                    },
                    "email": {
                        "type": "string",
                        "description": "New email",
                    },
                    "address": {
                        "type": "string",
                        "description": "New address",
                    },
                    "currency": {
                        "type": "string",
                        "description": "New default currency code",
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="add_line_item",
            description="Add a line item to a draft invoice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID",
                    },
                    "description": {
                        "type": "string",
                        "description": "Item description",
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Quantity (default: 1)",
                        "default": 1,
                    },
                    "unit_price": {
                        "type": "number",
                        "description": "Unit price",
                    },
                    "tax_rate": {
                        "type": "number",
                        "description": "Tax rate % for this item",
                    },
                },
                "required": ["invoice_id", "description", "unit_price"],
            },
        ),
        Tool(
            name="remove_line_item",
            description="Remove a line item from a draft invoice by its index (0-based).",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID",
                    },
                    "index": {
                        "type": "integer",
                        "description": "0-based index of the line item to remove",
                    },
                },
                "required": ["invoice_id", "index"],
            },
        ),
        Tool(
            name="list_templates",
            description="List available invoice templates (built-in and custom). Templates let you quickly create invoices with pre-defined line items.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category",
                    },
                },
            },
        ),
        Tool(
            name="get_template",
            description="Get full details of an invoice template by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "Template ID (e.g. TPL-service-retainer)",
                    },
                },
                "required": ["template_id"],
            },
        ),
        Tool(
            name="create_template",
            description="Create a custom invoice template with pre-defined line items, tax, and discount.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Template name",
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
                        "description": "Line items for the template",
                    },
                    "description": {
                        "type": "string",
                        "description": "Template description",
                    },
                    "category": {
                        "type": "string",
                        "description": "Template category (e.g. consulting, subscription)",
                    },
                    "due_days": {
                        "type": "integer",
                        "description": "Days until due date (default: 30)",
                        "default": 30,
                    },
                    "currency": {
                        "type": "string",
                        "description": "Currency code (default: USD)",
                        "default": "USD",
                    },
                    "tax_rate": {
                        "type": "number",
                        "description": "Invoice-level tax rate %",
                    },
                    "discount_amount": {
                        "type": "number",
                        "description": "Flat discount amount",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notes for generated invoices",
                    },
                },
                "required": ["name", "items"],
            },
        ),
        Tool(
            name="create_invoice_from_template",
            description="Create an invoice from a template, with optional overrides for due days, discount, notes, or currency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "Template ID to use",
                    },
                    "client": {
                        "type": "string",
                        "description": "Client ID or name",
                    },
                    "due_days": {
                        "type": "integer",
                        "description": "Override due days",
                    },
                    "discount_amount": {
                        "type": "number",
                        "description": "Override discount amount",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Override notes",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Override currency",
                    },
                },
                "required": ["template_id", "client"],
            },
        ),
        Tool(
            name="remove_template",
            description="Remove a custom template. Built-in templates cannot be removed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "Template ID to remove",
                    },
                },
                "required": ["template_id"],
            },
        ),
        Tool(
            name="get_dunning_config",
            description="Get the current dunning (overdue reminder) configuration.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="update_dunning_config",
            description="Update the dunning configuration — set days overdue thresholds for first reminder, second reminder, and final notice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "first_reminder_days": {
                        "type": "integer",
                        "description": "Days overdue for first reminder",
                    },
                    "second_reminder_days": {
                        "type": "integer",
                        "description": "Days overdue for second reminder",
                    },
                    "final_notice_days": {
                        "type": "integer",
                        "description": "Days overdue for final notice",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Enable or disable dunning",
                    },
                },
            },
        ),
        Tool(
            name="send_dunning_reminder",
            description="Send a dunning (overdue) reminder for a specific invoice. Optionally specify the level and custom message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The overdue invoice ID",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["first_reminder", "second_reminder", "final_notice"],
                        "description": "Dunning level (auto-determined if not specified)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Custom reminder message",
                    },
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="process_overdue_dunning",
            description="Auto-check all overdue invoices and send appropriate dunning reminders. Call this periodically (e.g. daily) to handle overdue accounts.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="list_dunning_actions",
            description="List all dunning actions/reminders sent, optionally filtered by invoice.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "Filter by invoice ID",
                    },
                },
            },
        ),
        Tool(
            name="remove_dunning_action",
            description="Remove a dunning action record.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "string",
                        "description": "The dunning action ID to remove",
                    },
                },
                "required": ["action_id"],
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
                "amount_paid": inv.amount_paid,
                "amount_remaining": inv.amount_remaining,
                "due_date": str(inv.due_date) if inv.due_date else None,
            })
        return _json_result(result)

    elif name == "get_invoice":
        inv = svc.get_invoice(arguments["invoice_id"])
        if not inv:
            return _text_result(f"Invoice not found: {arguments['invoice_id']}")
        data = inv.model_dump(mode="json")
        # Add computed fields
        data["amount_paid"] = inv.amount_paid
        data["amount_remaining"] = inv.amount_remaining
        return _json_result(data)

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

    elif name == "record_payment":
        try:
            from datetime import date as date_type
            payment_date = None
            if "payment_date" in arguments:
                try:
                    payment_date = date_type.fromisoformat(arguments["payment_date"])
                except ValueError:
                    return _text_result(f"Error: Invalid date format: {arguments['payment_date']}. Use YYYY-MM-DD.")
            inv = svc.record_payment(
                invoice_id=arguments["invoice_id"],
                amount=arguments["amount"],
                method=arguments.get("method"),
                reference=arguments.get("reference"),
                notes=arguments.get("notes"),
                payment_date=payment_date,
            )
            return _json_result({
                "id": inv.id,
                "status": inv.status.value,
                "amount_paid": inv.amount_paid,
                "amount_remaining": inv.amount_remaining,
                "total": inv.total,
                "currency": inv.currency,
                "payment_count": len(inv.payments),
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_payments":
        try:
            payments = svc.list_payments(arguments["invoice_id"])
            result = []
            for p in payments:
                result.append({
                    "id": p.id,
                    "amount": p.amount,
                    "method": p.method,
                    "reference": p.reference,
                    "notes": p.notes,
                    "date": str(p.payment_date),
                })
            return _json_result(result)
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_payment":
        try:
            inv = svc.remove_payment(arguments["invoice_id"], arguments["payment_id"])
            return _json_result({
                "id": inv.id,
                "status": inv.status.value,
                "amount_paid": inv.amount_paid,
                "amount_remaining": inv.amount_remaining,
            })
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
        fmt = arguments.get("format", "markdown")
        if fmt == "markdown":
            return _text_result(inv.to_markdown())
        elif fmt == "json":
            return _text_result(inv.model_dump_json(indent=2))
        elif fmt == "pdf":
            try:
                pdf_path = svc.export_pdf(
                    invoice_id=arguments["invoice_id"],
                    output_path=arguments.get("output_path"),
                    company_name=arguments.get("company_name"),
                    company_address=arguments.get("company_address"),
                    company_email=arguments.get("company_email"),
                )
                return _json_result({"path": pdf_path, "format": "pdf"})
            except ValueError as e:
                return _text_result(f"Error: {e}")

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

    elif name == "update_client":
        try:
            c = svc.update_client(
                identifier=arguments["identifier"],
                name=arguments.get("name"),
                email=arguments.get("email"),
                address=arguments.get("address"),
                currency=arguments.get("currency"),
            )
            return _json_result({"id": c.id, "name": c.name, "email": c.email, "currency": c.currency})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "add_line_item":
        try:
            item_data = {
                "description": arguments["description"],
                "quantity": arguments.get("quantity", 1.0),
                "unit_price": arguments["unit_price"],
            }
            if "tax_rate" in arguments:
                item_data["tax_rate"] = arguments["tax_rate"]
            inv = svc.add_line_item(arguments["invoice_id"], item_data)
            return _json_result({
                "id": inv.id, "items": len(inv.line_items),
                "subtotal": inv.subtotal, "total": inv.total,
                "currency": inv.currency,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_line_item":
        try:
            inv = svc.remove_line_item(arguments["invoice_id"], arguments["index"])
            return _json_result({
                "id": inv.id, "items": len(inv.line_items),
                "subtotal": inv.subtotal, "total": inv.total,
                "currency": inv.currency,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_templates":
        templates = svc.list_templates(category=arguments.get("category"))
        result = []
        for tpl in templates:
            result.append({
                "id": tpl.id, "name": tpl.name, "description": tpl.description,
                "category": tpl.category, "currency": tpl.currency,
                "total": tpl.total, "due_days": tpl.due_days,
                "items": len(tpl.line_items),
            })
        return _json_result(result)

    elif name == "get_template":
        tpl = svc.get_template(arguments["template_id"])
        if not tpl:
            return _text_result(f"Template not found: {arguments['template_id']}")
        data = tpl.model_dump(mode="json")
        data["subtotal"] = tpl.subtotal
        data["total_tax"] = tpl.total_tax
        data["total"] = tpl.total
        return _json_result(data)

    elif name == "create_template":
        try:
            items = arguments["items"]
            tpl = svc.create_template(
                name=arguments["name"],
                line_items=items,
                description=arguments.get("description"),
                category=arguments.get("category"),
                due_days=arguments.get("due_days", 30),
                currency=arguments.get("currency", "USD"),
                tax_rate=arguments.get("tax_rate"),
                discount_amount=arguments.get("discount_amount"),
                notes=arguments.get("notes"),
            )
            return _json_result({
                "id": tpl.id, "name": tpl.name, "currency": tpl.currency,
                "total": tpl.total, "items": len(tpl.line_items),
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "create_invoice_from_template":
        try:
            overrides = {}
            if "due_days" in arguments:
                overrides["due_days"] = arguments["due_days"]
            if "discount_amount" in arguments:
                overrides["discount_amount"] = arguments["discount_amount"]
            if "notes" in arguments:
                overrides["notes"] = arguments["notes"]
            if "currency" in arguments:
                overrides["currency"] = arguments["currency"]
            inv = svc.create_invoice_from_template(
                template_id=arguments["template_id"],
                client_identifier=arguments["client"],
                overrides=overrides,
            )
            return _json_result({
                "id": inv.id, "client": inv.client_name, "currency": inv.currency,
                "total": inv.total, "status": inv.status.value,
                "due_date": str(inv.due_date) if inv.due_date else None,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_template":
        try:
            if svc.remove_template(arguments["template_id"]):
                return _json_result({"removed": True, "template_id": arguments["template_id"]})
            return _text_result(f"Template not found: {arguments['template_id']}")
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "get_dunning_config":
        config = svc.get_dunning_config()
        return _json_result({
            "enabled": config.enabled,
            "first_reminder_days": config.first_reminder_days,
            "second_reminder_days": config.second_reminder_days,
            "final_notice_days": config.final_notice_days,
        })

    elif name == "update_dunning_config":
        try:
            config = svc.update_dunning_config(
                first_reminder_days=arguments.get("first_reminder_days"),
                second_reminder_days=arguments.get("second_reminder_days"),
                final_notice_days=arguments.get("final_notice_days"),
                enabled=arguments.get("enabled"),
            )
            return _json_result({
                "enabled": config.enabled,
                "first_reminder_days": config.first_reminder_days,
                "second_reminder_days": config.second_reminder_days,
                "final_notice_days": config.final_notice_days,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "send_dunning_reminder":
        try:
            action = svc.send_dunning_reminder(
                invoice_id=arguments["invoice_id"],
                level=arguments.get("level"),
                message=arguments.get("message"),
            )
            return _json_result({
                "id": action.id,
                "invoice_id": action.invoice_id,
                "level": action.level.value,
                "days_overdue": action.days_overdue,
                "message": action.message,
                "sent_at": str(action.sent_at),
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "process_overdue_dunning":
        actions = svc.process_overdue_dunning()
        result = []
        for action in actions:
            result.append({
                "id": action.id,
                "invoice_id": action.invoice_id,
                "level": action.level.value,
                "days_overdue": action.days_overdue,
                "message": action.message,
            })
        return _json_result({"processed_count": len(result), "actions": result})

    elif name == "list_dunning_actions":
        actions = svc.list_dunning_actions(invoice_id=arguments.get("invoice_id"))
        result = []
        for action in actions:
            result.append({
                "id": action.id,
                "invoice_id": action.invoice_id,
                "level": action.level.value,
                "days_overdue": action.days_overdue,
                "message": action.message,
                "sent_at": str(action.sent_at),
            })
        return _json_result(result)

    elif name == "remove_dunning_action":
        if svc.remove_dunning_action(arguments["action_id"]):
            return _json_result({"removed": True, "action_id": arguments["action_id"]})
        return _text_result(f"Dunning action not found: {arguments['action_id']}")

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
