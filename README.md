# Agent Invoice

**MCP server + CLI + REST API for autonomous agents to generate, track, and manage invoices.**

Built for the agentic economy — by [Nyx Builds](https://github.com/nyx-builds).

## Why?

Agents do work. Agents need to get paid. But there's no standard way for an autonomous agent to:

- Generate an invoice for completed work
- Track payment status across clients
- Maintain a ledger of earnings
- Integrate billing into their workflow via MCP
- Bill in multiple currencies with tax calculations
- Set up recurring invoices for retainer clients
- Chase overdue payments automatically
- Issue credit notes and refunds
- Generate client statements

**Agent Invoice** fixes this. It's a self-contained billing system designed for AI agents.

## Features

- 📄 **Invoice Generation** — Create professional invoices with line items, due dates, and client info
- 💰 **Tax Calculation** — Per-line-item and invoice-level tax rates with automatic computation
- 💱 **Multi-Currency** — 15+ currencies (USD, EUR, GBP, JPY, etc.) with proper symbols and decimal handling
- 💳 **Partial Payments** — Record multiple payments against an invoice, track remaining balance
- 📝 **Credit Notes** — Issue credits/refunds, apply them to invoices, track applications
- 📊 **Client Statements** — Period financial statements with opening/closing balances
- 🔄 **Recurring Invoices** — Set up weekly, biweekly, monthly, quarterly, or yearly billing templates
- ⏰ **Dunning Automation** — Automated overdue reminders with configurable escalation levels
- 🔍 **Invoice Search** — Search by text, date range, amount range, status, client, currency
- 📋 **Invoice Templates** — Built-in and custom templates for quick invoice creation
- 🏷️ **Custom Numbering** — Configurable invoice numbering (prefix, separator, digits)
- 📊 **Payment Tracking** — Monitor which invoices are pending, paid, partially paid, or overdue
- 📒 **Earnings Ledger** — Running total of all income, tax, and discounts across invoices
- 📤 **Export** — Export invoices as PDF, JSON, or Markdown
- 🔌 **MCP Server** — 35+ tools for full billing integration via Model Context Protocol
- 🌐 **REST API** — Full HTTP API with FastAPI for web integration
- 💻 **CLI** — Command-line interface with 30+ commands for direct use or scripting
- 💾 **JSON Storage** — Simple file-based storage, no database required

## Quick Start

### CLI Usage

```bash
# Create a client (with EUR as default billing currency)
agent-invoice client add "Acme Corp" --email billing@acme.com --currency EUR

# Create an invoice with tax
agent-invoice create \
  --client "Acme Corp" \
  --item "Code review,40,150.00,8.5" \
  --item "Bug fixes,10,200.00" \
  --tax-rate 8.5 \
  --due 30

# Apply a discount
agent-invoice discount INV-0001 50.00

# Record a partial payment
agent-invoice payment add INV-0001 --amount 500.00 --method bank_transfer

# List all invoices in EUR
agent-invoice list --currency EUR

# Search invoices
agent-invoice list --search "consulting" --min-amount 500.0
agent-invoice list --status overdue
agent-invoice list --date-from 2026-01-01 --date-to 2026-06-30

# Mark an invoice as paid
agent-invoice pay INV-0001

# Show earnings summary
agent-invoice earnings

# Export to PDF
agent-invoice export INV-0001 --format pdf --company-name "My Agent Co"

# --- Recurring invoices ---
agent-invoice recurring create \
  --client "Acme Corp" \
  --item "Retainer,1,500.00" \
  --frequency monthly

agent-invoice recurring generate REC-ABC123
agent-invoice recurring process    # Generate all due

# --- Credit notes ---
agent-invoice credit create --client "Acme Corp" --amount 250.00 --reason "overpayment"
agent-invoice credit apply CN-ABC123 --invoice INV-0001
agent-invoice credit list --status open

# --- Client statements ---
agent-invoice statement "Acme Corp" 2026-01-01 2026-06-30

# --- Dunning (overdue reminders) ---
agent-invoice dunning config
agent-invoice dunning send INV-0001
agent-invoice dunning process    # Auto-send reminders for all overdue

# --- Templates ---
agent-invoice template list
agent-invoice template use TPL-HOURLY --client "Acme Corp"

# --- Numbering ---
agent-invoice numbering set --prefix BIL --separator / --digits 3

# List supported currencies
agent-invoice currencies
```

### MCP Server

Start the MCP server for integration with any MCP-compatible agent:

```bash
agent-invoice serve
```

The server exposes **35+ tools**:

**Invoices & Line Items:**
- `create_invoice` — Generate a new invoice (with tax, currency, discounts)
- `list_invoices` — List invoices with filtering (status, client, currency)
- `get_invoice` — Get details of a specific invoice
- `mark_paid` / `mark_sent` / `cancel_invoice` — Status management
- `apply_discount` — Apply a discount
- `add_line_item` / `remove_line_item` — Edit draft invoices
- `search_invoices` — Search by text, date range, amount range
- `export_invoice` — Export as markdown, JSON, or PDF

**Payments:**
- `record_payment` — Record a payment (full or partial)
- `list_payments` / `remove_payment` — Payment management

**Clients:**
- `add_client` — Register a client (with default currency)
- `update_client` / `list_clients` — Client management
- `client_statement` — Generate period financial statements

**Credit Notes:**
- `create_credit_note` — Issue a credit/refund
- `list_credit_notes` / `get_credit_note` — View credit notes
- `apply_credit_note` — Apply credit to an invoice
- `void_credit_note` / `remove_credit_note` — Void or delete

**Recurring:**
- `create_recurring` — Create a recurring invoice template
- `list_recurring` / `generate_from_recurring`
- `pause_recurring` / `resume_recurring` / `process_due_recurring`

**Templates:**
- `list_templates` / `get_template` / `create_template`
- `create_invoice_from_template` / `remove_template`

**Dunning:**
- `get_dunning_config` / `update_dunning_config`
- `send_dunning_reminder` — Send a reminder for an overdue invoice
- `process_overdue_dunning` — Auto-process all overdue
- `list_dunning_actions` / `remove_dunning_action`

**Config & Utilities:**
- `get_numbering_config` / `update_numbering_config`
- `earnings_summary` / `list_currencies`

### REST API

Start the HTTP server:

```bash
uvicorn agent_invoice.api:create_app --factory --port 8000
```

Full CRUD API with endpoints for invoices, payments, clients, credit notes, statements, recurring, templates, dunning, earnings, and currencies.

```bash
# Create a client
curl -X POST http://localhost:8000/clients \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "currency": "USD"}'

# Create an invoice
curl -X POST http://localhost:8000/invoices \
  -H "Content-Type: application/json" \
  -d '{"client": "CLT-...", "items": [{"description": "Work", "quantity": 10, "unit_price": 100}]}'

# Record a payment
curl -X POST http://localhost:8000/invoices/INV-0001/payments \
  -H "Content-Type: application/json" \
  -d '{"amount": 500.00, "method": "bank_transfer"}'
```

## Tax Calculation

Agent Invoice supports two levels of tax:

1. **Line-item tax** — Set a tax rate on individual items: `--item "Consulting,10,200.00,8.5"`
2. **Invoice-level tax** — Set a default tax rate for items without their own: `--tax-rate 8.5`

Items with their own tax rate override the invoice-level rate. The grand total is computed as:

```
Subtotal + Total Tax - Discount = Grand Total
```

## Credit Notes

Issue credits for overpayments, refunds, or billing errors:

```bash
# Create a credit note
agent-invoice credit create --client "Acme Corp" --amount 250.00 --reason "overpayment"

# Apply to an invoice (reduces balance)
agent-invoice credit apply CN-ABC123 --invoice INV-0001

# Apply partial amount
agent-invoice credit apply CN-ABC123 --invoice INV-0001 --amount 100.00

# Void a credit note (only if unapplied)
agent-invoice credit void CN-ABC123
```

## Client Statements

Generate financial statements showing all activity for a period:

```bash
agent-invoice statement "Acme Corp" 2026-01-01 2026-06-30
```

Shows opening balance, period invoices, payments, credit notes, and closing balance.

## Dunning (Overdue Management)

Automated escalation reminders for overdue invoices:

```bash
# Configure dunning thresholds (days after due date)
agent-invoice dunning config --first 7 --second 14 --final 30

# Send a reminder for a specific invoice
agent-invoice dunning send INV-0001

# Auto-process all overdue invoices (run daily via cron)
agent-invoice dunning process
```

## Multi-Currency

Set a default currency per client, or override per invoice:

```bash
# Client with EUR default
agent-invoice client add "Berlin GmbH" --currency EUR

# Override to GBP for a specific invoice
agent-invoice create --client "Berlin GmbH" --currency GBP --item "Work,100.00"
```

Supported currencies: USD, EUR, GBP, JPY, CAD, AUD, CHF, CNY, INR, BRL, KRW, MXN, SGD, SEK, NZD

## Invoice Search

Find invoices by text, amount, or date:

```bash
# Text search (matches ID, client name, notes, line item descriptions)
agent-invoice list --search "consulting"

# Amount range
agent-invoice list --min-amount 500.0 --max-amount 5000.0

# Date range
agent-invoice list --date-from 2026-01-01 --date-to 2026-06-30

# Combined filters
agent-invoice list --search "API" --status overdue --min-amount 100.0
```

## Installation

```bash
pip install agent-invoice
```

Or with uv:

```bash
uv pip install agent-invoice
```

## Architecture

```
agent-invoice/
├── src/agent_invoice/
│   ├── __init__.py
│   ├── models.py       # Pydantic models (Invoice, Client, CreditNote, DunningConfig, etc.)
│   ├── store.py        # JSON file storage with numbering config
│   ├── service.py      # Business logic layer (35+ methods)
│   ├── cli.py          # Click CLI with 30+ commands
│   ├── mcp_server.py   # MCP server with 35+ tools
│   ├── api.py          # FastAPI REST API
│   └── pdf.py          # PDF export with reportlab
├── tests/              # 286 tests (models, store, service, CLI, API, credit notes, search, statements)
└── data/               # Default storage location
```

## Data Storage

Invoices, clients, recurring templates, credit notes, dunning actions, and templates are stored as JSON files in `~/.agent-invoice/` by default. Set the `AGENT_INVOICE_DIR` environment variable to customize the location.

## License

MIT
