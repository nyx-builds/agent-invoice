# Agent Invoice

**MCP server + CLI for autonomous agents to generate, track, and manage invoices.**

Built for the agentic economy — by [Nyx Builds](https://github.com/nyx-builds).

## Why?

Agents do work. Agents need to get paid. But there's no standard way for an autonomous agent to:

- Generate an invoice for completed work
- Track payment status across clients
- Maintain a ledger of earnings
- Integrate billing into their workflow via MCP
- Bill in multiple currencies with tax calculations
- Set up recurring invoices for retainer clients

**Agent Invoice** fixes this. It's a self-contained billing system designed for AI agents.

## Features

- 📄 **Invoice Generation** — Create professional invoices with line items, due dates, and client info
- 💰 **Tax Calculation** — Per-line-item and invoice-level tax rates with automatic computation
- 💱 **Multi-Currency** — 15+ currencies (USD, EUR, GBP, JPY, etc.) with proper symbols and decimal handling
- 🔄 **Recurring Invoices** — Set up weekly, biweekly, monthly, quarterly, or yearly billing templates
- 🏷️ **Custom Numbering** — Configurable invoice numbering (prefix, separator, digits)
- 📊 **Payment Tracking** — Monitor which invoices are pending, paid, or overdue
- 📒 **Earnings Ledger** — Running total of all income, tax, and discounts across invoices
- 🔌 **MCP Server** — Full Model Context Protocol integration so any agent can bill via their standard tool interface
- 💻 **CLI** — Command-line interface for direct use or scripting
- 💾 **JSON Storage** — Simple file-based storage, no database required
- 📤 **Export** — Export invoices as JSON or Markdown

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

# List all invoices in EUR
agent-invoice list --currency EUR

# Mark an invoice as paid
agent-invoice pay INV-0001

# Show earnings summary
agent-invoice earnings

# Set up a recurring monthly invoice
agent-invoice recurring create \
  --client "Acme Corp" \
  --item "Retainer,1,500.00" \
  --frequency monthly

# Generate an invoice from a recurring template
agent-invoice recurring generate REC-ABC123

# Process all due recurring invoices
agent-invoice recurring process

# Configure invoice numbering
agent-invoice numbering set --prefix BIL --separator / --digits 3

# List supported currencies
agent-invoice currencies
```

### MCP Server

Start the MCP server for integration with any MCP-compatible agent:

```bash
agent-invoice serve
```

The server exposes these tools:
- `create_invoice` — Generate a new invoice (with tax, currency, discounts)
- `list_invoices` — List all invoices with optional filtering by status, client, or currency
- `get_invoice` — Get details of a specific invoice
- `mark_paid` — Mark an invoice as paid
- `mark_sent` — Mark an invoice as sent
- `cancel_invoice` — Cancel an invoice
- `apply_discount` — Apply a discount to an invoice
- `add_client` — Register a new client (with default currency)
- `list_clients` — List all clients
- `earnings_summary` — Get earnings breakdown (with tax and discount totals)
- `export_invoice` — Export an invoice as markdown
- `create_recurring` — Create a recurring invoice template
- `list_recurring` — List recurring invoice templates
- `generate_from_recurring` — Generate an invoice from a recurring template
- `pause_recurring` — Pause a recurring invoice
- `resume_recurring` — Resume a paused recurring invoice
- `process_due_recurring` — Generate invoices for all due recurring templates
- `get_numbering_config` — Get the current invoice numbering configuration
- `update_numbering_config` — Update invoice numbering (prefix, separator, digits)
- `list_currencies` — List all supported currencies

## Tax Calculation

Agent Invoice supports two levels of tax:

1. **Line-item tax** — Set a tax rate on individual items: `--item "Consulting,10,200.00,8.5"`
2. **Invoice-level tax** — Set a default tax rate for items without their own: `--tax-rate 8.5`

Items with their own tax rate override the invoice-level rate. The grand total is computed as:

```
Subtotal + Total Tax - Discount = Grand Total
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

## Recurring Invoices

Create templates that generate invoices on a schedule:

```bash
# Monthly retainer
agent-invoice recurring create --client "Acme" --item "Retainer,1,500.00" --frequency monthly

# Weekly support
agent-invoice recurring create --client "Beta" --item "Support,1,200.00" --frequency weekly

# Generate manually
agent-invoice recurring generate REC-ABC123

# Process all due (run daily via cron)
agent-invoice recurring process

# Pause/resume
agent-invoice recurring pause REC-ABC123
agent-invoice recurring resume REC-ABC123
```

## Custom Invoice Numbering

```bash
# View current config
agent-invoice numbering show

# Change prefix and format
agent-invoice numbering set --prefix BIL --separator / --digits 3
# Generates: BIL/001, BIL/002, ...

# Year-based numbering
agent-invoice numbering set --prefix 2026 --separator - --digits 5
# Generates: 2026-00001, 2026-00002, ...
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
│   ├── models.py       # Pydantic data models (Invoice, Client, RecurringInvoice, etc.)
│   ├── store.py        # JSON file storage with numbering config
│   ├── service.py      # Business logic (tax, currency, recurring, discounts)
│   ├── cli.py          # Click CLI with 20+ commands
│   └── mcp_server.py   # MCP server with 20 tools
├── tests/
│   ├── test_models.py
│   ├── test_store.py
│   ├── test_service.py
│   └── test_cli.py
└── data/               # Default storage location
```

## Data Storage

Invoices, clients, and recurring templates are stored as JSON files in `~/.agent-invoice/` by default. Set the `AGENT_INVOICE_DIR` environment variable to customize the location.

## License

MIT
