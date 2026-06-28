# Agent Invoice

**MCP server + CLI for autonomous agents to generate, track, and manage invoices.**

Built for the agentic economy — by [Nyx Builds](https://github.com/nyx-builds).

## Why?

Agents do work. Agents need to get paid. But there's no standard way for an autonomous agent to:

- Generate an invoice for completed work
- Track payment status across clients
- Maintain a ledger of earnings
- Integrate billing into their workflow via MCP

**Agent Invoice** fixes this. It's a self-contained billing system designed for AI agents.

## Features

- 📄 **Invoice Generation** — Create professional invoices with line items, due dates, and client info
- 📊 **Payment Tracking** — Monitor which invoices are pending, paid, or overdue
- 📒 **Earnings Ledger** — Running total of all income across invoices
- 🔌 **MCP Server** — Full Model Context Protocol integration so any agent can bill via their standard tool interface
- 💻 **CLI** — Command-line interface for direct use or scripting
- 💾 **JSON Storage** — Simple file-based storage, no database required
- 🔄 **Export** — Export invoices as JSON or Markdown

## Quick Start

### CLI Usage

```bash
# Create a client
agent-invoice client add "Acme Corp" --email billing@acme.com

# Create an invoice
agent-invoice create \
  --client "Acme Corp" \
  --item "Code review,40 hours,150.00" \
  --item "Bug fixes,10 hours,200.00" \
  --due 30

# List all invoices
agent-invoice list

# Mark an invoice as paid
agent-invoice pay INV-001

# Show earnings summary
agent-invoice earnings
```

### MCP Server

Start the MCP server for integration with any MCP-compatible agent:

```bash
agent-invoice serve
```

The server exposes these tools:
- `create_invoice` — Generate a new invoice
- `list_invoices` — List all invoices with optional filtering
- `get_invoice` — Get details of a specific invoice
- `mark_paid` — Mark an invoice as paid
- `add_client` — Register a new client
- `list_clients` — List all clients
- `earnings_summary` — Get earnings breakdown
- `export_invoice` — Export an invoice as markdown

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
│   ├── models.py       # Pydantic data models
│   ├── store.py        # JSON file storage
│   ├── service.py      # Business logic
│   ├── cli.py          # Click CLI
│   └── mcp/
│       ├── __init__.py
│       └── server.py   # MCP server
├── tests/
│   ├── test_models.py
│   ├── test_store.py
│   ├── test_service.py
│   └── test_cli.py
└── data/               # Default storage location
```

## Data Storage

Invoices and clients are stored as JSON files in `~/.agent-invoice/` by default. Set the `AGENT_INVOICE_DIR` environment variable to customize the location.

## License

MIT
