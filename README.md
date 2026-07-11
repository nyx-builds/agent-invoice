<div align="center">

# Agent Invoice

**Invoicing, billing, and payment tracking for autonomous AI agents**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests: 493](https://img.shields.io/badge/tests-493%20passing-brightgreen.svg)](#testing)
[![MCP](https://img.shields.io/badge/MCP-server-7c3aed)](https://modelcontextprotocol.io)
[![Version: 0.7.0](https://img.shields.io/badge/version-0.7.0-blue.svg)](#changelog)

</div>

---

**MCP server + CLI + REST API for autonomous agents to generate, track, and manage invoices.**

Built for the agentic economy — by [Nyx Builds](https://github.com/nyx-builds).

### MCP Server Setup

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agent-invoice": {
      "command": "uvx",
      "args": ["agent-invoice", "serve"]
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "agent-invoice": {
      "command": "uvx",
      "args": ["agent-invoice", "serve"]
    }
  }
}
```

**Any MCP host:** `command: uvx`, `args: ["agent-invoice", "serve"]`

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
- 📑 **Estimates & Quotes** — Create quotes, send, accept/decline, and convert to invoices
- 📊 **A/R Aging Reports** — Track outstanding receivables by aging buckets (0-30, 31-60, 61-90, 90+ days)
- 📈 **Revenue Analytics** — Monthly revenue trends, collection rate, avg days to pay, top clients
- 🏷️ **Custom Numbering** — Configurable invoice numbering (prefix, separator, digits)
- 📊 **Payment Tracking** — Monitor which invoices are pending, paid, partially paid, or overdue
- 📒 **Earnings Ledger** — Running total of all income, tax, and discounts across invoices
- 📤 **Export** — Export invoices as PDF, JSON, or Markdown
- 🤖 **Usage Metering** (v0.8.0) — Track AI/API consumption (tokens, cost, provider, model) and bill clients based on actual usage
- 💸 **Usage-Based Billing** (v0.8.0) — Aggregate usage events into invoices with per-provider/model line items and optional markup
- 🔌 **MCP Server** — 74 tools for full billing integration via Model Context Protocol
- 🌐 **REST API** — Full HTTP API with FastAPI for web integration
- 💻 **CLI** — Command-line interface with 40+ commands for direct use or scripting
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

# --- Estimates & Quotes ---
agent-invoice estimate create "Acme Corp" --description "Website redesign" --quantity 1 --price 5000.00 --terms "Net 30"
agent-invoice estimate create "Acme Corp" --description "Monthly support" --price 2000.00 --expiry 15 --tax-rate 8.5
agent-invoice estimate list --status draft
agent-invoice estimate show EST-ABC123
agent-invoice estimate send EST-ABC123
agent-invoice estimate accept EST-ABC123
agent-invoice estimate convert EST-ABC123 --due-days 30

# --- A/R Aging Report ---
agent-invoice ar-aging
agent-invoice ar-aging --currency USD

# --- Revenue Analytics ---
agent-invoice revenue
agent-invoice revenue --months 12 --currency USD

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

The server exposes **55 tools**:

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

**Estimates & Quotes:**
- `create_estimate` — Create a quote with line items, tax, discount, and expiry
- `list_estimates` — List quotes with optional status/client filters
- `get_estimate` — Get full details of a specific quote
- `send_estimate` — Mark a quote as sent to the client
- `accept_estimate` / `decline_estimate` — Client decision tracking
- `convert_estimate_to_invoice` — Convert an accepted quote into an invoice
- `remove_estimate` — Delete a quote (cannot delete converted ones)

**Reports & Analytics:**
- `generate_ar_aging_report` — A/R aging with per-client bucket breakdown
- `get_revenue_analytics` — Monthly trends, collection rate, days to pay, top clients

### REST API

Start the HTTP server:

```bash
uvicorn agent_invoice.api:create_app --factory --port 8000
```

Full CRUD API with endpoints for invoices, payments, clients, credit notes, statements, recurring, templates, dunning, estimates, reports, earnings, and currencies.

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

# Create an estimate
curl -X POST http://localhost:8000/estimates \
  -H "Content-Type: application/json" \
  -d '{"client": "CLT-...", "line_items": [{"description": "Project", "quantity": 1, "unit_price": 5000}]}'

# Convert an estimate to invoice
curl -X POST http://localhost:8000/estimates/EST-ABC123/convert?due_days=30

# Get A/R aging report
curl http://localhost:8000/reports/ar-aging?currency=USD

# Get revenue analytics
curl http://localhost:8000/reports/revenue?period_start=2026-01-01&period_end=2026-06-30
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

## Estimates & Quotes

Send quotes before work begins, then convert accepted quotes into invoices:

```bash
# Create an estimate with tax and expiry
agent-invoice estimate create "Acme Corp" \
  --description "Website redesign" \
  --quantity 1 \
  --price 5000.00 \
  --tax-rate 8.5 \
  --expiry 30 \
  --terms "Net 30"

# Send the quote to the client
agent-invoice estimate send EST-ABC123

# Client accepts
agent-invoice estimate accept EST-ABC123

# Convert to a real invoice
agent-invoice estimate convert EST-ABC123 --due-days 30

# List all estimates by status
agent-invoice estimate list --status accepted
```

Estimates have a full lifecycle: **draft → sent → accepted/declined → converted**. Expired quotes are auto-detected. Converted estimates link back to the invoice they became.

## A/R Aging Reports

Track outstanding receivables grouped by how long they've been overdue:

```bash
# Full aging report
agent-invoice ar-aging

# Filter by currency
agent-invoice ar-aging --currency USD
```

Groups outstanding balances into standard aging buckets: **0-30, 31-60, 61-90, 90+ days**. Shows per-client breakdown with invoice-level detail (days overdue, amount remaining).

## Revenue Analytics

Analyze revenue trends over time:

```bash
# Last 6 months (default)
agent-invoice revenue

# Last 12 months
agent-invoice revenue --months 12
```

Shows monthly invoicing vs. collection trends, overall collection rate (%), average days to pay, fastest/slowest payments, and top clients by revenue.

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
│   ├── models.py       # Pydantic models (Invoice, Client, CreditNote, Estimate, ARAging, RevenueAnalytics, etc.)
│   ├── store.py        # JSON file storage with numbering config
│   ├── service.py      # Business logic layer (50+ methods)
│   ├── cli.py          # Click CLI with 40+ commands
│   ├── mcp_server.py   # MCP server with 55 tools
│   ├── api.py          # FastAPI REST API
│   └── pdf.py          # PDF export with reportlab
├── tests/              # 413 tests (models, store, service, CLI, API, MCP, estimates, reports)
└── data/               # Default storage location
```

## Data Storage

Invoices, clients, recurring templates, credit notes, dunning actions, and templates are stored as JSON files in `~/.agent-invoice/` by default. Set the `AGENT_INVOICE_DIR` environment variable to customize the location.

## License

MIT
