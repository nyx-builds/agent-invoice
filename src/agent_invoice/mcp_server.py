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
        Tool(
            name="search_invoices",
            description="Search invoices by text, date range, or amount range. Text search covers invoice ID, client name, notes, and line item descriptions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Text to search for (case-insensitive, matches invoice ID, client name, notes, line item descriptions)",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Filter invoices issued on or after this date (YYYY-MM-DD)",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Filter invoices issued on or before this date (YYYY-MM-DD)",
                    },
                    "min_amount": {
                        "type": "number",
                        "description": "Filter invoices with total >= this amount",
                    },
                    "max_amount": {
                        "type": "number",
                        "description": "Filter invoices with total <= this amount",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "sent", "paid", "overdue", "cancelled", "partially_paid"],
                        "description": "Filter by status",
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
            name="create_credit_note",
            description="Create a credit note for a client. Credit notes represent refunds, overpayments, or billing corrections that can be applied to invoices.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {
                        "type": "string",
                        "description": "Client ID or name",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Credit amount (must be positive)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the credit (e.g. refund, overpayment, billing error)",
                    },
                    "invoice_id": {
                        "type": "string",
                        "description": "Original invoice this credit relates to (optional)",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Currency code (defaults to client's currency)",
                    },
                },
                "required": ["client", "amount"],
            },
        ),
        Tool(
            name="list_credit_notes",
            description="List credit notes, optionally filtered by client and status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {
                        "type": "string",
                        "description": "Filter by client ID or name",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "applied", "void"],
                        "description": "Filter by credit note status",
                    },
                },
            },
        ),
        Tool(
            name="get_credit_note",
            description="Get full details of a credit note by ID, including applications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "credit_id": {
                        "type": "string",
                        "description": "The credit note ID",
                    },
                },
                "required": ["credit_id"],
            },
        ),
        Tool(
            name="apply_credit_note",
            description="Apply a credit note to an invoice. This creates a payment record on the invoice and reduces the credit note's remaining balance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "credit_id": {
                        "type": "string",
                        "description": "The credit note ID to apply",
                    },
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice ID to apply the credit to",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount to apply (defaults to remaining credit or remaining balance, whichever is less)",
                    },
                },
                "required": ["credit_id", "invoice_id"],
            },
        ),
        Tool(
            name="void_credit_note",
            description="Void a credit note. Only open credit notes with no applications can be voided.",
            inputSchema={
                "type": "object",
                "properties": {
                    "credit_id": {
                        "type": "string",
                        "description": "The credit note ID to void",
                    },
                },
                "required": ["credit_id"],
            },
        ),
        Tool(
            name="client_statement",
            description="Generate a financial statement for a client over a period. Shows all invoices, payments, credit notes, and opening/closing balances.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {
                        "type": "string",
                        "description": "Client ID or name",
                    },
                    "period_start": {
                        "type": "string",
                        "description": "Start of the statement period (YYYY-MM-DD)",
                    },
                    "period_end": {
                        "type": "string",
                        "description": "End of the statement period (YYYY-MM-DD)",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Filter by currency code (defaults to client's currency)",
                    },
                },
                "required": ["client", "period_start", "period_end"],
            },
        ),
        Tool(
            name="remove_credit_note",
            description="Remove a credit note. Only voided credit notes (or open ones with no applications) can be removed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "credit_id": {
                        "type": "string",
                        "description": "The credit note ID to remove",
                    },
                },
                "required": ["credit_id"],
            },
        ),
        # --- A/R Aging ---
        Tool(
            name="generate_ar_aging_report",
            description="Generate an A/R (Accounts Receivable) aging report. Groups outstanding invoice balances into aging buckets (0-30, 31-60, 61-90, 90+ days) to help identify which clients are late paying and by how much.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "description": "Filter by currency code (e.g. USD, EUR). Omit for all currencies.",
                    },
                },
            },
        ),
        # --- Revenue Analytics ---
        Tool(
            name="get_revenue_analytics",
            description="Generate revenue analytics for a period. Includes monthly invoicing/collection trends, collection rate (%), average days to pay, fastest/slowest payments, and top clients by revenue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period_start": {
                        "type": "string",
                        "description": "Period start date (YYYY-MM-DD)",
                    },
                    "period_end": {
                        "type": "string",
                        "description": "Period end date (YYYY-MM-DD)",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Filter by currency. Omit for default.",
                    },
                },
                "required": ["period_start", "period_end"],
            },
        ),
        # --- Estimates ---
        Tool(
            name="create_estimate",
            description="Create a new estimate/quote for a client. Estimates can be sent, accepted/declined, and converted into invoices once accepted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {
                        "type": "string",
                        "description": "Client ID or name",
                    },
                    "line_items": {
                        "type": "array",
                        "description": "List of line items for the estimate",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"},
                                "tax_rate": {"type": "number"},
                            },
                            "required": ["description", "unit_price"],
                        },
                    },
                    "currency": {"type": "string"},
                    "notes": {"type": "string"},
                    "terms": {"type": "string", "description": "Payment terms or scope description"},
                    "expiry_days": {"type": "integer", "description": "Days until quote expires (default 30)"},
                    "tax_rate": {"type": "number"},
                    "discount_amount": {"type": "number"},
                },
                "required": ["client", "line_items"],
            },
        ),
        Tool(
            name="list_estimates",
            description="List estimates/quotes with optional filters by status or client.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["draft", "sent", "accepted", "declined", "expired", "converted"],
                        "description": "Filter by status",
                    },
                    "client": {"type": "string", "description": "Filter by client ID or name"},
                },
            },
        ),
        Tool(
            name="get_estimate",
            description="Get details of a specific estimate by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                },
                "required": ["estimate_id"],
            },
        ),
        Tool(
            name="send_estimate",
            description="Mark an estimate as sent to the client.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                },
                "required": ["estimate_id"],
            },
        ),
        Tool(
            name="accept_estimate",
            description="Mark an estimate as accepted by the client.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                },
                "required": ["estimate_id"],
            },
        ),
        Tool(
            name="decline_estimate",
            description="Mark an estimate as declined by the client.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                },
                "required": ["estimate_id"],
            },
        ),
        Tool(
            name="convert_estimate_to_invoice",
            description="Convert an estimate into an invoice. The estimate must be in draft, sent, or accepted status. Creates a new invoice and marks the estimate as converted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                    "due_days": {"type": "integer", "description": "Days until due date for the new invoice (default 30)"},
                },
                "required": ["estimate_id"],
            },
        ),
        Tool(
            name="remove_estimate",
            description="Remove an estimate. Cannot remove converted estimates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string", "description": "The estimate ID"},
                },
                "required": ["estimate_id"],
            },
        ),
        # --- v0.7.0: Expenses ---
        Tool(
            name="create_expense",
            description="Record a business expense (cost incurred by the agent). Tracks costs like software subscriptions, API calls, contractors, infrastructure, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Description of the expense"},
                    "amount": {"type": "number", "description": "Expense amount (must be positive)"},
                    "currency": {"type": "string", "description": "Currency code (default USD)"},
                    "category": {"type": "string", "description": "Category: software, api_costs, infrastructure, contractors, marketing, travel, office, legal, insurance, bank_fees, taxes, other", "default": "other"},
                    "vendor": {"type": "string", "description": "Who the expense was paid to"},
                    "expense_date": {"type": "string", "description": "Date in YYYY-MM-DD format (defaults to today)"},
                    "payment_method": {"type": "string", "description": "e.g. credit_card, bank_transfer, crypto"},
                    "reference": {"type": "string", "description": "External reference number"},
                    "notes": {"type": "string"},
                    "tax_deductible": {"type": "boolean", "default": "true"},
                },
                "required": ["description", "amount"],
            },
        ),
        Tool(
            name="list_expenses",
            description="List expenses with optional filters (category, currency, date range, vendor).",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by category"},
                    "currency": {"type": "string"},
                    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "vendor": {"type": "string", "description": "Filter by vendor name (partial match)"},
                },
            },
        ),
        Tool(
            name="get_expense",
            description="Get details of a specific expense by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expense_id": {"type": "string"},
                },
                "required": ["expense_id"],
            },
        ),
        Tool(
            name="update_expense",
            description="Update an existing expense.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expense_id": {"type": "string"},
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "vendor": {"type": "string"},
                    "payment_method": {"type": "string"},
                    "notes": {"type": "string"},
                    "tax_deductible": {"type": "boolean"},
                },
                "required": ["expense_id"],
            },
        ),
        Tool(
            name="remove_expense",
            description="Remove an expense.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expense_id": {"type": "string"},
                },
                "required": ["expense_id"],
            },
        ),
        Tool(
            name="expense_summary",
            description="Get a summary of expenses broken down by category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
            },
        ),
        # --- v0.7.0: Profit Analysis ---
        Tool(
            name="get_profit_analysis",
            description="Analyze profitability: revenue from collected payments minus expenses. Includes per-client profitability breakdown and expense breakdown by category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "description": "Start date (YYYY-MM-DD). Default: all-time"},
                    "period_end": {"type": "string", "description": "End date (YYYY-MM-DD). Default: today"},
                    "currency": {"type": "string", "description": "Currency to analyze (default USD)"},
                },
            },
        ),
        # --- v0.7.0: Tax Summary ---
        Tool(
            name="generate_tax_summary",
            description="Generate a tax summary report for a period: total invoiced, tax collected (all and from paid invoices), effective rate, breakdown by tax rate, and deductible expenses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "period_end": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "currency": {"type": "string", "description": "Filter by currency (default: all)"},
                },
                "required": ["period_start", "period_end"],
            },
        ),
        # --- v0.7.0: Bulk Operations ---
        Tool(
            name="bulk_mark_sent",
            description="Mark multiple invoices as sent at once. Only draft invoices can be sent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["invoice_ids"],
            },
        ),
        Tool(
            name="bulk_mark_paid",
            description="Mark multiple invoices as paid at once.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["invoice_ids"],
            },
        ),
        Tool(
            name="bulk_cancel",
            description="Cancel multiple invoices at once.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["invoice_ids"],
            },
        ),
        Tool(
            name="bulk_export",
            description="Export multiple invoices at once (markdown or JSON).",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_ids": {"type": "array", "items": {"type": "string"}},
                    "format": {"type": "string", "description": "markdown or json", "default": "markdown"},
                },
                "required": ["invoice_ids"],
            },
        ),
        Tool(
            name="export_estimate_pdf",
            description="Export an estimate/quote as a professional PDF file. Returns the file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_id": {"type": "string"},
                    "output_path": {"type": "string", "description": "Custom output path (optional)"},
                    "company_name": {"type": "string"},
                    "company_address": {"type": "string"},
                    "company_email": {"type": "string"},
                },
                "required": ["estimate_id"],
            },
        ),

        # --- v0.8.0: Usage Metering & Agent Billing ---

        Tool(
            name="record_usage",
            description="Record a usage event for AI/API consumption. Tracks tokens, cost, provider, and model for metering and client billing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Description of the usage (e.g. 'Claude inference', 'API gateway requests')"},
                    "cost": {"type": "number", "description": "Dollar cost of this usage"},
                    "client": {"type": "string", "description": "Client ID or name to attribute usage to (optional)"},
                    "provider": {"type": "string", "description": "AI provider (openai, anthropic, google, custom)", "default": "openai"},
                    "model": {"type": "string", "description": "Model used (e.g. gpt-4, claude-3-opus)"},
                    "input_tokens": {"type": "integer", "description": "Input/prompt tokens", "default": 0},
                    "output_tokens": {"type": "integer", "description": "Output/completion tokens", "default": 0},
                    "cache_read_tokens": {"type": "integer", "description": "Cache read tokens", "default": 0},
                    "cache_write_tokens": {"type": "integer", "description": "Cache write tokens", "default": 0},
                    "request_count": {"type": "integer", "description": "Number of API requests", "default": 1},
                    "currency": {"type": "string", "description": "Currency code (default: USD)"},
                    "metadata": {"type": "object", "description": "Arbitrary key-value tags (project, task, agent_id)"},
                },
                "required": ["description", "cost"],
            },
        ),
        Tool(
            name="list_usage",
            description="List usage events with optional filters by client, provider, model, billed status, and date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Filter by client ID or name"},
                    "provider": {"type": "string", "description": "Filter by provider"},
                    "model": {"type": "string", "description": "Filter by model"},
                    "billed": {"type": "boolean", "description": "Filter by billed status"},
                    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                },
            },
        ),
        Tool(
            name="get_usage_summary",
            description="Get aggregated usage summary — totals, billed vs unbilled, breakdowns by provider/model/client/daily.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Filter by client ID or name"},
                    "provider": {"type": "string", "description": "Filter by provider"},
                    "model": {"type": "string", "description": "Filter by model"},
                    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "currency": {"type": "string", "description": "Filter by currency"},
                },
            },
        ),
        Tool(
            name="aggregate_usage",
            description="Aggregate unbilled usage events for a client into a structured record with line items ready for invoicing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Client ID or name"},
                    "period_start": {"type": "string", "description": "Period start date (YYYY-MM-DD)"},
                    "period_end": {"type": "string", "description": "Period end date (YYYY-MM-DD)"},
                    "currency": {"type": "string", "description": "Currency code (default: USD)"},
                    "include_billed": {"type": "boolean", "description": "Include already-billed events (default: false)"},
                },
                "required": ["client", "period_start", "period_end"],
            },
        ),
        Tool(
            name="invoice_from_usage",
            description="Create an invoice from accumulated usage events for a client. Aggregates unbilled usage, creates invoice with line items per provider/model, and marks events as billed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Client ID or name"},
                    "period_start": {"type": "string", "description": "Usage period start (YYYY-MM-DD)"},
                    "period_end": {"type": "string", "description": "Usage period end (YYYY-MM-DD)"},
                    "currency": {"type": "string", "description": "Currency code (default: USD)"},
                    "due_days": {"type": "integer", "description": "Days until due (default: 30)"},
                    "markup_percent": {"type": "number", "description": "Markup percentage on usage cost (e.g. 20 for 20% markup)"},
                    "notes": {"type": "string", "description": "Additional notes on the invoice"},
                },
                "required": ["client", "period_start", "period_end"],
            },
        ),
        Tool(
            name="remove_usage_event",
            description="Delete a usage event. Cannot delete events that have already been billed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "The usage event ID"},
                },
                "required": ["event_id"],
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

    elif name == "search_invoices":
        from datetime import date as date_type
        date_from = None
        date_to = None
        if "date_from" in arguments:
            try:
                date_from = date_type.fromisoformat(arguments["date_from"])
            except ValueError:
                return _text_result(f"Error: Invalid date_from format. Use YYYY-MM-DD.")
        if "date_to" in arguments:
            try:
                date_to = date_type.fromisoformat(arguments["date_to"])
            except ValueError:
                return _text_result(f"Error: Invalid date_to format. Use YYYY-MM-DD.")
        status = InvoiceStatus(arguments["status"]) if "status" in arguments else None
        invoices = svc.list_invoices(
            status=status,
            client=arguments.get("client"),
            currency=arguments.get("currency"),
            date_from=date_from,
            date_to=date_to,
            min_amount=arguments.get("min_amount"),
            max_amount=arguments.get("max_amount"),
            search=arguments.get("search"),
        )
        result = []
        for inv in invoices:
            result.append({
                "id": inv.id,
                "client": inv.client_name,
                "currency": inv.currency,
                "status": inv.status.value,
                "total": inv.total,
                "amount_paid": inv.amount_paid,
                "amount_remaining": inv.amount_remaining,
                "issue_date": str(inv.issue_date),
                "due_date": str(inv.due_date) if inv.due_date else None,
            })
        return _json_result({"count": len(result), "invoices": result})

    elif name == "create_credit_note":
        try:
            credit = svc.create_credit_note(
                client_identifier=arguments["client"],
                amount=arguments["amount"],
                reason=arguments.get("reason"),
                invoice_id=arguments.get("invoice_id"),
                currency=arguments.get("currency"),
            )
            return _json_result({
                "id": credit.id,
                "client": credit.client_name,
                "amount": credit.amount,
                "currency": credit.currency,
                "reason": credit.reason,
                "status": credit.status.value,
                "remaining": credit.remaining_amount,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_credit_notes":
        try:
            credits = svc.list_credit_notes(
                client=arguments.get("client"),
                status=arguments.get("status"),
            )
            result = []
            for credit in credits:
                result.append({
                    "id": credit.id,
                    "client": credit.client_name,
                    "amount": credit.amount,
                    "currency": credit.currency,
                    "applied_amount": credit.applied_amount,
                    "remaining_amount": credit.remaining_amount,
                    "status": credit.status.value,
                    "reason": credit.reason,
                    "issue_date": str(credit.issue_date),
                })
            return _json_result(result)
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "get_credit_note":
        credit = svc.get_credit_note(arguments["credit_id"])
        if not credit:
            return _text_result(f"Credit note not found: {arguments['credit_id']}")
        data = credit.model_dump(mode="json")
        data["applied_amount"] = credit.applied_amount
        data["remaining_amount"] = credit.remaining_amount
        return _json_result(data)

    elif name == "apply_credit_note":
        try:
            credit, invoice = svc.apply_credit_note(
                credit_id=arguments["credit_id"],
                invoice_id=arguments["invoice_id"],
                amount=arguments.get("amount"),
            )
            return _json_result({
                "credit_note": {
                    "id": credit.id,
                    "applied_amount": credit.applied_amount,
                    "remaining_amount": credit.remaining_amount,
                    "status": credit.status.value,
                },
                "invoice": {
                    "id": invoice.id,
                    "status": invoice.status.value,
                    "amount_paid": invoice.amount_paid,
                    "amount_remaining": invoice.amount_remaining,
                },
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "void_credit_note":
        try:
            credit = svc.void_credit_note(arguments["credit_id"])
            return _json_result({"id": credit.id, "status": credit.status.value})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_credit_note":
        try:
            if svc.remove_credit_note(arguments["credit_id"]):
                return _json_result({"removed": True, "credit_id": arguments["credit_id"]})
            return _text_result(f"Credit note not found: {arguments['credit_id']}")
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "client_statement":
        from datetime import date as date_type
        try:
            period_start = date_type.fromisoformat(arguments["period_start"])
            period_end = date_type.fromisoformat(arguments["period_end"])
        except ValueError:
            return _text_result("Error: Invalid date format. Use YYYY-MM-DD.")
        try:
            statement = svc.generate_client_statement(
                client_identifier=arguments["client"],
                period_start=period_start,
                period_end=period_end,
                currency=arguments.get("currency"),
            )
            return _json_result(statement.model_dump(mode="json"))
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "generate_ar_aging_report":
        try:
            report = svc.generate_ar_aging_report(currency=arguments.get("currency"))
            return _json_result(report.model_dump(mode="json"))
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "get_revenue_analytics":
        from datetime import date as date_type
        try:
            period_start = date_type.fromisoformat(arguments["period_start"])
            period_end = date_type.fromisoformat(arguments["period_end"])
        except ValueError:
            return _text_result("Error: Invalid date format. Use YYYY-MM-DD.")
        try:
            analytics = svc.get_revenue_analytics(period_start, period_end, currency=arguments.get("currency"))
            return _json_result(analytics.model_dump(mode="json"))
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "create_estimate":
        try:
            estimate = svc.create_estimate(
                client_identifier=arguments["client"],
                line_items=arguments["line_items"],
                currency=arguments.get("currency"),
                notes=arguments.get("notes"),
                terms=arguments.get("terms"),
                expiry_days=arguments.get("expiry_days", 30),
                tax_rate=arguments.get("tax_rate"),
                discount_amount=arguments.get("discount_amount"),
            )
            return _json_result({
                "id": estimate.id,
                "client": estimate.client_name,
                "status": estimate.status.value,
                "currency": estimate.currency,
                "subtotal": estimate.subtotal,
                "tax": estimate.total_tax,
                "discount": estimate.discount_amount,
                "total": estimate.total,
                "expiry_date": str(estimate.expiry_date) if estimate.expiry_date else None,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_estimates":
        try:
            estimates = svc.list_estimates(status=arguments.get("status"), client=arguments.get("client"))
            return _json_result([
                {
                    "id": e.id,
                    "client": e.client_name or e.client_id,
                    "status": e.status.value,
                    "currency": e.currency,
                    "total": e.total,
                    "issue_date": str(e.issue_date),
                    "expiry_date": str(e.expiry_date) if e.expiry_date else None,
                    "converted_invoice_id": e.converted_invoice_id,
                }
                for e in estimates
            ])
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "get_estimate":
        est = svc.get_estimate(arguments["estimate_id"])
        if not est:
            return _text_result(f"Estimate '{arguments['estimate_id']}' not found")
        return _json_result(est.model_dump(mode="json"))

    elif name == "send_estimate":
        try:
            est = svc.send_estimate(arguments["estimate_id"])
            return _json_result({"id": est.id, "status": est.status.value})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "accept_estimate":
        try:
            est = svc.accept_estimate(arguments["estimate_id"])
            return _json_result({"id": est.id, "status": est.status.value})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "decline_estimate":
        try:
            est = svc.decline_estimate(arguments["estimate_id"])
            return _json_result({"id": est.id, "status": est.status.value})
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "convert_estimate_to_invoice":
        try:
            est, inv = svc.convert_estimate_to_invoice(
                arguments["estimate_id"],
                due_days=arguments.get("due_days", 30),
            )
            return _json_result({
                "estimate_id": est.id,
                "estimate_status": est.status.value,
                "invoice_id": inv.id,
                "invoice_total": inv.total,
                "invoice_currency": inv.currency,
                "invoice_due_date": str(inv.due_date) if inv.due_date else None,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_estimate":
        try:
            if svc.remove_estimate(arguments["estimate_id"]):
                return _text_result(f"Estimate '{arguments['estimate_id']}' removed.")
            return _text_result(f"Estimate '{arguments['estimate_id']}' not found.")
        except ValueError as e:
            return _text_result(f"Error: {e}")

    # --- v0.7.0: Expenses ---

    elif name == "create_expense":
        try:
            from datetime import date as date_type
            exp_date = None
            if "expense_date" in arguments:
                try:
                    exp_date = date_type.fromisoformat(arguments["expense_date"])
                except ValueError:
                    return _text_result(f"Error: Invalid date format: {arguments['expense_date']}. Use YYYY-MM-DD.")
            exp = svc.create_expense(
                description=arguments["description"],
                amount=arguments["amount"],
                currency=arguments.get("currency", "USD"),
                category=arguments.get("category", "other"),
                vendor=arguments.get("vendor"),
                expense_date=exp_date,
                payment_method=arguments.get("payment_method"),
                reference=arguments.get("reference"),
                notes=arguments.get("notes"),
                tax_deductible=arguments.get("tax_deductible", True),
            )
            return _json_result({
                "id": exp.id,
                "description": exp.description,
                "amount": exp.amount,
                "currency": exp.currency,
                "category": exp.category.value,
                "vendor": exp.vendor,
                "expense_date": str(exp.expense_date),
                "tax_deductible": exp.tax_deductible,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_expenses":
        from datetime import date as date_type
        date_from = None
        date_to = None
        if "date_from" in arguments:
            date_from = date_type.fromisoformat(arguments["date_from"])
        if "date_to" in arguments:
            date_to = date_type.fromisoformat(arguments["date_to"])
        expenses = svc.list_expenses(
            category=arguments.get("category"),
            currency=arguments.get("currency"),
            date_from=date_from,
            date_to=date_to,
            vendor=arguments.get("vendor"),
        )
        result = []
        for e in expenses:
            result.append({
                "id": e.id,
                "description": e.description,
                "amount": e.amount,
                "currency": e.currency,
                "category": e.category.value,
                "vendor": e.vendor,
                "expense_date": str(e.expense_date),
                "tax_deductible": e.tax_deductible,
            })
        return _json_result(result)

    elif name == "get_expense":
        exp = svc.get_expense(arguments["expense_id"])
        if not exp:
            return _text_result(f"Expense not found: {arguments['expense_id']}")
        return _json_result(exp.model_dump(mode="json"))

    elif name == "update_expense":
        try:
            exp = svc.update_expense(
                expense_id=arguments["expense_id"],
                description=arguments.get("description"),
                amount=arguments.get("amount"),
                category=arguments.get("category"),
                vendor=arguments.get("vendor"),
                payment_method=arguments.get("payment_method"),
                notes=arguments.get("notes"),
                tax_deductible=arguments.get("tax_deductible"),
            )
            return _json_result({
                "id": exp.id,
                "description": exp.description,
                "amount": exp.amount,
                "category": exp.category.value,
                "updated": True,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_expense":
        if svc.remove_expense(arguments["expense_id"]):
            return _text_result(f"Expense '{arguments['expense_id']}' removed.")
        return _text_result(f"Expense '{arguments['expense_id']}' not found.")

    elif name == "expense_summary":
        from datetime import date as date_type
        date_from = date_type.fromisoformat(arguments["date_from"]) if "date_from" in arguments else None
        date_to = date_type.fromisoformat(arguments["date_to"]) if "date_to" in arguments else None
        summary = svc.expense_summary(
            currency=arguments.get("currency"),
            date_from=date_from,
            date_to=date_to,
        )
        return _json_result(summary)

    # --- v0.7.0: Profit Analysis ---

    elif name == "get_profit_analysis":
        from datetime import date as date_type
        period_start = date_type.fromisoformat(arguments["period_start"]) if "period_start" in arguments else None
        period_end = date_type.fromisoformat(arguments["period_end"]) if "period_end" in arguments else None
        analysis = svc.get_profit_analysis(
            period_start=period_start,
            period_end=period_end,
            currency=arguments.get("currency", "USD"),
        )
        return _json_result(analysis.model_dump(mode="json"))

    # --- v0.7.0: Tax Summary ---

    elif name == "generate_tax_summary":
        from datetime import date as date_type
        try:
            period_start = date_type.fromisoformat(arguments["period_start"])
            period_end = date_type.fromisoformat(arguments["period_end"])
        except (ValueError, KeyError) as e:
            return _text_result(f"Error: Invalid date format. Use YYYY-MM-DD. ({e})")
        report = svc.generate_tax_summary(
            period_start=period_start,
            period_end=period_end,
            currency=arguments.get("currency"),
        )
        return _json_result(report.model_dump(mode="json"))

    # --- v0.7.0: Bulk Operations ---

    elif name == "bulk_mark_sent":
        results = svc.bulk_mark_sent(arguments["invoice_ids"])
        return _json_result(results)

    elif name == "bulk_mark_paid":
        results = svc.bulk_mark_paid(arguments["invoice_ids"])
        return _json_result(results)

    elif name == "bulk_cancel":
        results = svc.bulk_cancel(arguments["invoice_ids"])
        return _json_result(results)

    elif name == "bulk_export":
        results = svc.bulk_export(arguments["invoice_ids"], arguments.get("format", "markdown"))
        return _json_result(results)

    # --- v0.7.0: Estimate PDF Export ---

    elif name == "export_estimate_pdf":
        path = svc.export_estimate_pdf(
            arguments["estimate_id"],
            output_path=arguments.get("output_path"),
            company_name=arguments.get("company_name"),
            company_address=arguments.get("company_address"),
            company_email=arguments.get("company_email"),
        )
        return _json_result({"estimate_id": arguments["estimate_id"], "pdf_path": path})

    # --- v0.8.0: Usage Metering & Agent Billing ---

    elif name == "record_usage":
        try:
            event = svc.record_usage(
                description=arguments["description"],
                cost=arguments["cost"],
                client_identifier=arguments.get("client"),
                provider=arguments.get("provider", "openai"),
                model=arguments.get("model"),
                input_tokens=arguments.get("input_tokens", 0),
                output_tokens=arguments.get("output_tokens", 0),
                cache_read_tokens=arguments.get("cache_read_tokens", 0),
                cache_write_tokens=arguments.get("cache_write_tokens", 0),
                request_count=arguments.get("request_count", 1),
                currency=arguments.get("currency", "USD"),
                metadata=arguments.get("metadata", {}),
            )
            return _json_result({
                "id": event.id,
                "client": event.client_name or event.client_id,
                "description": event.description,
                "provider": event.provider,
                "model": event.model,
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
                "total_tokens": event.total_tokens,
                "cost": event.cost,
                "currency": event.currency,
                "billed": event.billed,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "list_usage":
        from datetime import date as date_type
        date_from = date_type.fromisoformat(arguments["date_from"]) if "date_from" in arguments else None
        date_to = date_type.fromisoformat(arguments["date_to"]) if "date_to" in arguments else None
        events = svc.list_usage_events(
            client_identifier=arguments.get("client"),
            provider=arguments.get("provider"),
            model=arguments.get("model"),
            billed=arguments.get("billed"),
            date_from=date_from,
            date_to=date_to,
        )
        return _json_result([
            {
                "id": e.id,
                "client": e.client_name or e.client_id,
                "description": e.description,
                "provider": e.provider,
                "model": e.model,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "total_tokens": e.total_tokens,
                "cost": e.cost,
                "currency": e.currency,
                "billed": e.billed,
                "invoice_id": e.invoice_id,
                "recorded_at": str(e.recorded_at),
            }
            for e in events
        ])

    elif name == "get_usage_summary":
        from datetime import date as date_type
        date_from = date_type.fromisoformat(arguments["date_from"]) if "date_from" in arguments else None
        date_to = date_type.fromisoformat(arguments["date_to"]) if "date_to" in arguments else None
        summary = svc.get_usage_summary(
            client_identifier=arguments.get("client"),
            provider=arguments.get("provider"),
            model=arguments.get("model"),
            date_from=date_from,
            date_to=date_to,
            currency=arguments.get("currency"),
        )
        return _json_result(summary.model_dump(mode="json"))

    elif name == "aggregate_usage":
        from datetime import date as date_type
        try:
            period_start = date_type.fromisoformat(arguments["period_start"])
            period_end = date_type.fromisoformat(arguments["period_end"])
        except ValueError:
            return _text_result("Error: Invalid date format. Use YYYY-MM-DD.")
        try:
            record = svc.aggregate_usage_to_record(
                client_identifier=arguments["client"],
                period_start=period_start,
                period_end=period_end,
                currency=arguments.get("currency", "USD"),
                include_billed=arguments.get("include_billed", False),
            )
            return _json_result(record)
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "invoice_from_usage":
        from datetime import date as date_type
        try:
            period_start = date_type.fromisoformat(arguments["period_start"])
            period_end = date_type.fromisoformat(arguments["period_end"])
        except ValueError:
            return _text_result("Error: Invalid date format. Use YYYY-MM-DD.")
        try:
            invoice, record = svc.create_invoice_from_usage(
                client_identifier=arguments["client"],
                period_start=period_start,
                period_end=period_end,
                currency=arguments.get("currency", "USD"),
                due_days=arguments.get("due_days", 30),
                markup_percent=arguments.get("markup_percent", 0.0),
                notes=arguments.get("notes"),
            )
            return _json_result({
                "invoice_id": invoice.id,
                "client": invoice.client_name,
                "total": invoice.total,
                "currency": invoice.currency,
                "line_item_count": len(invoice.line_items),
                "usage_events_billed": record["event_count"],
                "usage_cost": record["total_cost"],
                "due_date": str(invoice.due_date) if invoice.due_date else None,
            })
        except ValueError as e:
            return _text_result(f"Error: {e}")

    elif name == "remove_usage_event":
        try:
            if svc.remove_usage_event(arguments["event_id"]):
                return _json_result({"removed": True, "event_id": arguments["event_id"]})
            return _text_result(f"Usage event not found: {arguments['event_id']}")
        except ValueError as e:
            return _text_result(f"Error: {e}")

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
