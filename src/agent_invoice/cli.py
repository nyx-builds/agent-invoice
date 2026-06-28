"""CLI interface for Agent Invoice."""

from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .models import CURRENCIES, InvoiceStatus, RecurrenceFrequency, format_amount, get_currency_symbol
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

@main.group("client")
def client():
    """Manage clients."""
    pass


@client.command("add")
@click.argument("name")
@click.option("--email", "-e", help="Client email address")
@click.option("--address", "-a", help="Client mailing address")
@click.option("--currency", "-c", default="USD", help="Default billing currency (default: USD)")
def client_add(name: str, email: Optional[str], address: Optional[str], currency: str):
    """Add a new client."""
    svc = get_service()
    try:
        c = svc.add_client(name=name, email=email, address=address, currency=currency)
        console.print(f"[green]✓[/green] Client created: {c.id} — {c.name} ({c.currency})")
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
    table.add_column("Currency")
    table.add_column("Created")
    for c in clients:
        table.add_row(c.id, c.name, c.email or "—", c.currency, c.created_at.strftime("%Y-%m-%d"))
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
@click.option("--item", "-i", multiple=True, help="Line item: 'description,quantity,unit_price' or 'description,quantity,unit_price,tax_rate'")
@click.option("--due", "-d", type=int, default=30, help="Days until due date")
@click.option("--notes", "-n", help="Notes on the invoice")
@click.option("--currency", help="Override currency (uses client default if not set)")
@click.option("--tax-rate", type=float, default=0.0, help="Invoice-level tax rate %% (applied to items without their own tax)")
@click.option("--discount", type=float, default=0.0, help="Flat discount amount")
def invoice_create(client: str, item: tuple, due: int, notes: Optional[str], currency: Optional[str], tax_rate: float, discount: float):
    """Create a new invoice."""
    if not item:
        console.print("[red]✗[/red] At least one --item is required.")
        sys.exit(1)

    line_items = []
    for i in item:
        parts = [p.strip() for p in i.split(",")]
        if len(parts) == 4:
            desc, qty, price, tax = parts
            line_items.append({
                "description": desc,
                "quantity": float(qty),
                "unit_price": float(price),
                "tax_rate": float(tax),
            })
        elif len(parts) == 3:
            desc, qty, price = parts
            line_items.append({"description": desc, "quantity": float(qty), "unit_price": float(price)})
        elif len(parts) == 2:
            desc, price = parts
            line_items.append({"description": desc, "unit_price": float(price)})
        else:
            console.print(f"[red]✗[/red] Invalid item format: '{i}'. Use 'description,quantity,price[,tax_rate]'")
            sys.exit(1)

    svc = get_service()
    try:
        inv = svc.create_invoice(
            client_identifier=client,
            line_items=line_items,
            due_days=due,
            notes=notes,
            currency=currency,
            tax_rate=tax_rate if tax_rate > 0 else None,
            discount_amount=discount if discount > 0 else None,
        )
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Invoice created: {inv.id}")
        console.print(f"  Client: {inv.client_name}")
        console.print(f"  Items:  {len(inv.line_items)}")
        console.print(f"  Subtotal: {sym}{inv.subtotal:.2f}")
        if inv.total_tax > 0:
            console.print(f"  Tax:      {sym}{inv.total_tax:.2f}")
        if inv.discount_amount > 0:
            console.print(f"  Discount: -{sym}{inv.discount_amount:.2f}")
        console.print(f"  [bold]Total:   {sym}{inv.total:.2f}[/bold]")
        console.print(f"  Due:    {inv.due_date}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("list")
@click.option("--status", "-s", type=click.Choice(["draft", "sent", "paid", "overdue", "cancelled"]), help="Filter by status")
@click.option("--client", "-c", help="Filter by client ID or name")
@click.option("--currency", help="Filter by currency code")
def invoice_list(status: Optional[str], client: Optional[str], currency: Optional[str]):
    """List all invoices."""
    svc = get_service()
    status_enum = InvoiceStatus(status) if status else None
    invoices = svc.list_invoices(status=status_enum, client=client, currency=currency)
    if not invoices:
        console.print("[dim]No invoices found.[/dim]")
        return

    table = Table(title="Invoices")
    table.add_column("ID", style="cyan")
    table.add_column("Client", style="bold")
    table.add_column("Currency")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Subtotal", justify="right")
    table.add_column("Tax", justify="right")
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
        sym = get_currency_symbol(inv.currency)
        table.add_row(
            inv.id,
            inv.client_name or inv.client_id,
            inv.currency,
            status_style,
            str(len(inv.line_items)),
            f"{sym}{inv.subtotal:.2f}",
            f"{sym}{inv.total_tax:.2f}" if inv.total_tax > 0 else "—",
            f"{sym}{inv.total:.2f}",
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
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Invoice {inv.id} marked as PAID ({sym}{inv.total:.2f})")
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


@main.command("discount")
@click.argument("invoice_id")
@click.argument("amount", type=float)
def invoice_discount(invoice_id: str, amount: float):
    """Apply a discount to an invoice."""
    svc = get_service()
    try:
        inv = svc.apply_discount(invoice_id, amount)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Discount of {sym}{amount:.2f} applied to {inv.id}")
        console.print(f"  New total: {sym}{inv.total:.2f}")
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
@click.option("--currency", "-c", help="Filter by currency code")
def invoice_earnings(currency: Optional[str]):
    """Show earnings summary."""
    svc = get_service()
    summary = svc.earnings_summary(currency=currency)
    sym = get_currency_symbol(summary.currency)
    console.print(f"\n[bold]Earnings Summary ({summary.currency})[/bold]\n")
    console.print(f"  Total Invoiced:  [green]{sym}{summary.total_invoiced:.2f}[/green]")
    console.print(f"  Total Paid:       [green]{sym}{summary.total_paid:.2f}[/green]")
    console.print(f"  Total Pending:    [yellow]{sym}{summary.total_pending:.2f}[/yellow]")
    console.print(f"  Total Overdue:    [red]{sym}{summary.total_overdue:.2f}[/red]")
    if summary.total_tax > 0:
        console.print(f"  Total Tax:       [dim]{sym}{summary.total_tax:.2f}[/dim]")
    if summary.total_discounts > 0:
        console.print(f"  Total Discounts: [dim]{sym}{summary.total_discounts:.2f}[/dim]")
    console.print(f"\n  Invoices: {summary.invoice_count}  |  Paid: {summary.paid_count}  |  Pending: {summary.pending_count}  |  Overdue: {summary.overdue_count}")


# --- Recurring invoice commands ---

@main.group("recurring")
def recurring():
    """Manage recurring invoices."""
    pass


@recurring.command("create")
@click.option("--client", "-c", required=True, help="Client ID or name")
@click.option("--item", "-i", multiple=True, help="Line item: 'description,quantity,unit_price[,tax_rate]'")
@click.option("--frequency", "-f", type=click.Choice(["weekly", "biweekly", "monthly", "quarterly", "yearly"]), default="monthly", help="Recurrence frequency")
@click.option("--due", "-d", type=int, default=30, help="Days until due date for generated invoices")
@click.option("--notes", "-n", help="Notes on generated invoices")
@click.option("--currency", help="Override currency")
@click.option("--tax-rate", type=float, default=0.0, help="Invoice-level tax rate %%")
@click.option("--discount", type=float, default=0.0, help="Flat discount amount")
def recurring_create(client: str, item: tuple, frequency: str, due: int, notes: Optional[str], currency: Optional[str], tax_rate: float, discount: float):
    """Create a recurring invoice template."""
    if not item:
        console.print("[red]✗[/red] At least one --item is required.")
        sys.exit(1)

    line_items = []
    for i in item:
        parts = [p.strip() for p in i.split(",")]
        if len(parts) == 4:
            desc, qty, price, tax = parts
            line_items.append({"description": desc, "quantity": float(qty), "unit_price": float(price), "tax_rate": float(tax)})
        elif len(parts) == 3:
            desc, qty, price = parts
            line_items.append({"description": desc, "quantity": float(qty), "unit_price": float(price)})
        elif len(parts) == 2:
            desc, price = parts
            line_items.append({"description": desc, "unit_price": float(price)})
        else:
            console.print(f"[red]✗[/red] Invalid item format: '{i}'")
            sys.exit(1)

    svc = get_service()
    try:
        rec = svc.create_recurring(
            client_identifier=client,
            line_items=line_items,
            frequency=frequency,
            due_days=due,
            notes=notes,
            currency=currency,
            tax_rate=tax_rate if tax_rate > 0 else None,
            discount_amount=discount if discount > 0 else None,
        )
        sym = get_currency_symbol(rec.currency)
        console.print(f"[green]✓[/green] Recurring invoice created: {rec.id}")
        console.print(f"  Client:    {rec.client_name}")
        console.print(f"  Frequency:  {rec.frequency.value}")
        console.print(f"  Total:      {sym}{rec.total:.2f}")
        console.print(f"  Next date:  {rec.next_date}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@recurring.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show paused recurring invoices too")
def recurring_list(show_all: bool):
    """List recurring invoice templates."""
    svc = get_service()
    recurrings = svc.list_recurring(active_only=not show_all)
    if not recurrings:
        console.print("[dim]No recurring invoices found.[/dim]")
        return

    table = Table(title="Recurring Invoices")
    table.add_column("ID", style="cyan")
    table.add_column("Client", style="bold")
    table.add_column("Frequency")
    table.add_column("Total")
    table.add_column("Status")
    table.add_column("Next Date")
    table.add_column("Generated")
    for rec in recurrings:
        sym = get_currency_symbol(rec.currency)
        status = "[green]Active[/green]" if rec.active else "[dim]Paused[/dim]"
        table.add_row(
            rec.id,
            rec.client_name or rec.client_id,
            rec.frequency.value,
            f"{sym}{rec.total:.2f}",
            status,
            str(rec.next_date) if rec.next_date else "—",
            str(len(rec.invoice_ids)),
        )
    console.print(table)


@recurring.command("generate")
@click.argument("recurring_id")
def recurring_generate(recurring_id: str):
    """Generate an invoice from a recurring template."""
    svc = get_service()
    try:
        inv = svc.generate_from_recurring(recurring_id)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Invoice generated: {inv.id}")
        console.print(f"  Client: {inv.client_name}")
        console.print(f"  Total:  {sym}{inv.total:.2f}")
        console.print(f"  Due:    {inv.due_date}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@recurring.command("process")
def recurring_process():
    """Generate invoices for all due recurring templates."""
    svc = get_service()
    generated = svc.process_due_recurring()
    if not generated:
        console.print("[dim]No recurring invoices are due.[/dim]")
        return
    console.print(f"[green]✓[/green] Generated {len(generated)} invoice(s):")
    for inv in generated:
        sym = get_currency_symbol(inv.currency)
        console.print(f"  {inv.id} — {inv.client_name} — {sym}{inv.total:.2f}")


@recurring.command("pause")
@click.argument("recurring_id")
def recurring_pause(recurring_id: str):
    """Pause a recurring invoice."""
    svc = get_service()
    try:
        rec = svc.pause_recurring(recurring_id)
        console.print(f"[yellow]✓[/yellow] Recurring invoice {rec.id} paused")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@recurring.command("resume")
@click.argument("recurring_id")
def recurring_resume(recurring_id: str):
    """Resume a paused recurring invoice."""
    svc = get_service()
    try:
        rec = svc.resume_recurring(recurring_id)
        console.print(f"[green]✓[/green] Recurring invoice {rec.id} resumed (next: {rec.next_date})")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@recurring.command("remove")
@click.argument("recurring_id")
def recurring_remove(recurring_id: str):
    """Remove a recurring invoice template."""
    svc = get_service()
    if svc.remove_recurring(recurring_id):
        console.print(f"[green]✓[/green] Recurring invoice removed: {recurring_id}")
    else:
        console.print(f"[red]✗[/red] Recurring invoice not found: {recurring_id}")
        sys.exit(1)


# --- Numbering config commands ---

@main.group("numbering")
def numbering():
    """Configure invoice numbering."""
    pass


@numbering.command("show")
def numbering_show():
    """Show current numbering configuration."""
    svc = get_service()
    config = svc.get_numbering_config()
    console.print(f"\n[bold]Invoice Numbering[/bold]\n")
    console.print(f"  Prefix:     {config.prefix}")
    console.print(f"  Separator:  {config.separator}")
    console.print(f"  Digits:     {config.digits}")
    console.print(f"  Next #:     {config.format_number()}")
    console.print(f"  Example:    {config.format_number(config.next_number + 5)}")


@numbering.command("set")
@click.option("--prefix", help="Invoice number prefix (e.g. INV, BIL, 2024)")
@click.option("--separator", help="Separator between prefix and number (e.g. - or /)")
@click.option("--digits", type=int, help="Number of digits (e.g. 4 for 0001)")
@click.option("--next-number", type=int, help="Set the next invoice number")
def numbering_set(prefix: Optional[str], separator: Optional[str], digits: Optional[int], next_number: Optional[int]):
    """Update numbering configuration."""
    if not any([prefix, separator, digits, next_number]):
        console.print("[red]✗[/red] Provide at least one option to update.")
        sys.exit(1)
    svc = get_service()
    config = svc.update_numbering_config(
        prefix=prefix,
        separator=separator,
        digits=digits,
        next_number=next_number,
    )
    console.print(f"[green]✓[/green] Numbering updated: {config.prefix}{config.separator}{config.next_number:0{config.digits}d}")


# --- MCP serve ---

@main.command("serve")
def serve():
    """Start the MCP server for agent integration."""
    from .mcp_server import run_server
    console.print("[bold]Starting Agent Invoice MCP server...[/bold]")
    run_server()


# --- Currencies command ---

@main.command("currencies")
def list_currencies():
    """List supported currencies."""
    table = Table(title="Supported Currencies")
    table.add_column("Code", style="cyan")
    table.add_column("Symbol")
    table.add_column("Name")
    table.add_column("Decimals", justify="right")
    for code, info in sorted(CURRENCIES.items()):
        table.add_row(code, info["symbol"], info["name"], str(info["decimals"]))
    console.print(table)


if __name__ == "__main__":
    main()
