"""CLI interface for Agent Invoice."""

from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .models import InvoiceStatus
from .service import InvoiceService
from .store import InvoiceStore

console = Console()


def get_service() -> InvoiceService:
    return InvoiceService(InvoiceStore())


@click.group()
@click.version_option()
def main():
    """Agent Invoice — Billing for autonomous agents."""
    pass


# --- Client commands ---

@main.group()
def client():
    """Manage clients."""
    pass


@client.command("add")
@click.argument("name")
@click.option("--email", "-e", help="Client email address")
@click.option("--address", "-a", help="Client mailing address")
def client_add(name: str, email: Optional[str], address: Optional[str]):
    """Add a new client."""
    svc = get_service()
    try:
        c = svc.add_client(name=name, email=email, address=address)
        console.print(f"[green]✓[/green] Client created: {c.id} — {c.name}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@client.command("list")
def client_list():
    """List all clients."""
    svc = get_service()
    clients = svc.list_clients()
    if not clients:
        console.print("[dim]No clients found.[/dim]")
        return
    table = Table(title="Clients")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Email")
    table.add_column("Created")
    for c in clients:
        table.add_row(c.id, c.name, c.email or "—", c.created_at.strftime("%Y-%m-%d"))
    console.print(table)


@client.command("remove")
@click.argument("identifier")
def client_remove(identifier: str):
    """Remove a client by ID or name."""
    svc = get_service()
    if svc.remove_client(identifier):
        console.print(f"[green]✓[/green] Client removed: {identifier}")
    else:
        console.print(f"[red]✗[/red] Client not found: {identifier}")
        sys.exit(1)


# --- Invoice commands ---

@main.command("create")
@click.option("--client", "-c", required=True, help="Client ID or name")
@click.option("--item", "-i", multiple=True, help="Line item: 'description,quantity,unit_price'")
@click.option("--due", "-d", type=int, default=30, help="Days until due date")
@click.option("--notes", "-n", help="Notes on the invoice")
def invoice_create(client: str, item: tuple, due: int, notes: Optional[str]):
    """Create a new invoice."""
    if not item:
        console.print("[red]✗[/red] At least one --item is required.")
        sys.exit(1)

    line_items = []
    for i in item:
        parts = [p.strip() for p in i.split(",")]
        if len(parts) == 3:
            desc, qty, price = parts
            line_items.append({"description": desc, "quantity": float(qty), "unit_price": float(price)})
        elif len(parts) == 2:
            desc, price = parts
            line_items.append({"description": desc, "unit_price": float(price)})
        else:
            console.print(f"[red]✗[/red] Invalid item format: '{i}'. Use 'description,quantity,price'")
            sys.exit(1)

    svc = get_service()
    try:
        inv = svc.create_invoice(
            client_identifier=client,
            line_items=line_items,
            due_days=due,
            notes=notes,
        )
        console.print(f"[green]✓[/green] Invoice created: {inv.id}")
        console.print(f"  Client: {inv.client_name}")
        console.print(f"  Items:  {len(inv.line_items)}")
        console.print(f"  Total:  ${inv.subtotal:.2f}")
        console.print(f"  Due:    {inv.due_date}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("list")
@click.option("--status", "-s", type=click.Choice(["draft", "sent", "paid", "overdue", "cancelled"]), help="Filter by status")
@click.option("--client", "-c", help="Filter by client ID or name")
def invoice_list(status: Optional[str], client: Optional[str]):
    """List all invoices."""
    svc = get_service()
    status_enum = InvoiceStatus(status) if status else None
    invoices = svc.list_invoices(status=status_enum, client=client)
    if not invoices:
        console.print("[dim]No invoices found.[/dim]")
        return

    table = Table(title="Invoices")
    table.add_column("ID", style="cyan")
    table.add_column("Client", style="bold")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Total", justify="right", style="green")
    table.add_column("Due Date")
    for inv in invoices:
        status_style = {
            "paid": "[green]PAID[/green]",
            "overdue": "[red]OVERDUE[/red]",
            "sent": "[yellow]SENT[/yellow]",
            "draft": "[dim]DRAFT[/dim]",
            "cancelled": "[dim]CANCELLED[/dim]",
        }.get(inv.status.value, inv.status.value)
        table.add_row(
            inv.id,
            inv.client_name or inv.client_id,
            status_style,
            str(len(inv.line_items)),
            f"${inv.subtotal:.2f}",
            str(inv.due_date) if inv.due_date else "—",
        )
    console.print(table)


@main.command("show")
@click.argument("invoice_id")
def invoice_show(invoice_id: str):
    """Show invoice details."""
    svc = get_service()
    inv = svc.get_invoice(invoice_id)
    if not inv:
        console.print(f"[red]✗[/red] Invoice not found: {invoice_id}")
        sys.exit(1)
    console.print(inv.to_markdown())


@main.command("pay")
@click.argument("invoice_id")
def invoice_pay(invoice_id: str):
    """Mark an invoice as paid."""
    svc = get_service()
    try:
        inv = svc.mark_paid(invoice_id)
        console.print(f"[green]✓[/green] Invoice {inv.id} marked as PAID (${inv.subtotal:.2f})")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("send")
@click.argument("invoice_id")
def invoice_send(invoice_id: str):
    """Mark an invoice as sent."""
    svc = get_service()
    try:
        inv = svc.mark_sent(invoice_id)
        console.print(f"[green]✓[/green] Invoice {inv.id} marked as SENT")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("cancel")
@click.argument("invoice_id")
def invoice_cancel(invoice_id: str):
    """Cancel an invoice."""
    svc = get_service()
    try:
        inv = svc.cancel_invoice(invoice_id)
        console.print(f"[yellow]✓[/yellow] Invoice {inv.id} CANCELLED")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("export")
@click.argument("invoice_id")
@click.option("--format", "-f", type=click.Choice(["markdown", "json"]), default="markdown", help="Export format")
def invoice_export(invoice_id: str, format: str):
    """Export an invoice."""
    svc = get_service()
    inv = svc.get_invoice(invoice_id)
    if not inv:
        console.print(f"[red]✗[/red] Invoice not found: {invoice_id}")
        sys.exit(1)
    if format == "markdown":
        console.print(inv.to_markdown())
    else:
        console.print(inv.model_dump_json(indent=2))


@main.command("earnings")
def invoice_earnings():
    """Show earnings summary."""
    svc = get_service()
    summary = svc.earnings_summary()
    console.print("\n[bold]Earnings Summary[/bold]\n")
    console.print(f"  Total Invoiced:  [green]${summary.total_invoiced:.2f}[/green]")
    console.print(f"  Total Paid:       [green]${summary.total_paid:.2f}[/green]")
    console.print(f"  Total Pending:    [yellow]${summary.total_pending:.2f}[/yellow]")
    console.print(f"  Total Overdue:    [red]${summary.total_overdue:.2f}[/red]")
    console.print(f"\n  Invoices: {summary.invoice_count}  |  Paid: {summary.paid_count}  |  Pending: {summary.pending_count}  |  Overdue: {summary.overdue_count}")


@main.command("serve")
def serve():
    """Start the MCP server for agent integration."""
    from .mcp_server import run_server
    console.print("[bold]Starting Agent Invoice MCP server...[/bold]")
    run_server()


if __name__ == "__main__":
    main()
