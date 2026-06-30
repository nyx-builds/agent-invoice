"""CLI interface for Agent Invoice."""

from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .models import CURRENCIES, BUILTIN_TEMPLATES, DunningLevel, InvoiceStatus, RecurrenceFrequency, format_amount, get_currency_symbol
from .service import InvoiceService
from .store import InvoiceStore
from . import __version__

console = Console()


def get_service() -> InvoiceService:
    return InvoiceService(InvoiceStore())


@click.group()
@click.version_option(__version__)
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


@client.command("update")
@click.argument("identifier")
@click.option("--name", "-n", help="New name")
@click.option("--email", "-e", help="New email")
@click.option("--address", "-a", help="New address")
@click.option("--currency", "-c", help="New default currency")
def client_update(identifier: str, name: Optional[str], email: Optional[str], address: Optional[str], currency: Optional[str]):
    """Update a client's details."""
    svc = get_service()
    try:
        c = svc.update_client(identifier, name=name, email=email, address=address, currency=currency)
        console.print(f"[green]✓[/green] Client updated: {c.id} — {c.name}")
        if email:
            console.print(f"  Email: {c.email}")
        if currency:
            console.print(f"  Currency: {c.currency}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
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
@click.option("--status", "-s", type=click.Choice(["draft", "sent", "paid", "overdue", "cancelled", "partially_paid"]), help="Filter by status")
@click.option("--client", "-c", help="Filter by client ID or name")
@click.option("--currency", help="Filter by currency code")
@click.option("--date-from", help="Invoices issued on or after this date (YYYY-MM-DD)")
@click.option("--date-to", help="Invoices issued on or before this date (YYYY-MM-DD)")
@click.option("--min-amount", type=float, help="Minimum total amount")
@click.option("--max-amount", type=float, help="Maximum total amount")
@click.option("--search", help="Text search (matches ID, client, notes, items)")
def invoice_list(status: Optional[str], client: Optional[str], currency: Optional[str], date_from: Optional[str], date_to: Optional[str], min_amount: Optional[float], max_amount: Optional[float], search: Optional[str]):
    """List all invoices with optional filters."""
    svc = get_service()
    status_enum = InvoiceStatus(status) if status else None
    from datetime import date as date_type
    parsed_from = None
    parsed_to = None
    if date_from:
        try:
            parsed_from = date_type.fromisoformat(date_from)
        except ValueError:
            console.print(f"[red]✗[/red] Invalid date_from format: {date_from}. Use YYYY-MM-DD.")
            sys.exit(1)
    if date_to:
        try:
            parsed_to = date_type.fromisoformat(date_to)
        except ValueError:
            console.print(f"[red]✗[/red] Invalid date_to format: {date_to}. Use YYYY-MM-DD.")
            sys.exit(1)
    invoices = svc.list_invoices(
        status=status_enum, client=client, currency=currency,
        date_from=parsed_from, date_to=parsed_to,
        min_amount=min_amount, max_amount=max_amount,
        search=search,
    )
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
    table.add_column("Paid", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Due Date")
    for inv in invoices:
        status_style = {
            "paid": "[green]PAID[/green]",
            "overdue": "[red]OVERDUE[/red]",
            "sent": "[yellow]SENT[/yellow]",
            "draft": "[dim]DRAFT[/dim]",
            "cancelled": "[dim]CANCELLED[/dim]",
            "partially_paid": "[cyan]PARTIAL[/cyan]",
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
            f"{sym}{inv.amount_paid:.2f}" if inv.amount_paid > 0 else "—",
            f"{sym}{inv.amount_remaining:.2f}" if inv.amount_remaining > 0 and inv.amount_paid > 0 else "—",
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
@click.option("--amount", "-a", type=float, default=None, help="Partial payment amount (if not specified, marks as fully paid)")
@click.option("--method", "-m", help="Payment method (e.g. bank_transfer, credit_card, crypto, cash)")
@click.option("--reference", "-r", help="Payment reference / transaction ID")
@click.option("--date", "payment_date", help="Payment date (YYYY-MM-DD, defaults to today)")
def invoice_pay(invoice_id: str, amount: Optional[float], method: Optional[str], reference: Optional[str], payment_date: Optional[str]):
    """Mark an invoice as paid, or record a partial payment."""
    svc = get_service()
    inv = svc.get_invoice(invoice_id)
    if not inv:
        console.print(f"[red]✗[/red] Invoice not found: {invoice_id}")
        sys.exit(1)

    if amount is not None:
        # Partial payment
        parsed_date = None
        if payment_date:
            from datetime import date as date_type
            try:
                parsed_date = date_type.fromisoformat(payment_date)
            except ValueError:
                console.print(f"[red]✗[/red] Invalid date format: {payment_date}. Use YYYY-MM-DD.")
                sys.exit(1)
        try:
            inv = svc.record_payment(
                invoice_id=invoice_id,
                amount=amount,
                method=method,
                reference=reference,
                payment_date=parsed_date,
            )
            sym = get_currency_symbol(inv.currency)
            console.print(f"[green]✓[/green] Payment of {sym}{amount:.2f} recorded for {inv.id}")
            console.print(f"  Status:    {inv.status.value.replace('_', ' ').upper()}")
            console.print(f"  Paid:      {sym}{inv.amount_paid:.2f}")
            console.print(f"  Remaining: {sym}{inv.amount_remaining:.2f}")
        except ValueError as e:
            console.print(f"[red]✗[/red] {e}")
            sys.exit(1)
    else:
        # Full payment (legacy behavior)
        if method or reference:
            # If method/reference provided, record a payment for the full amount
            parsed_date = None
            if payment_date:
                from datetime import date as date_type
                try:
                    parsed_date = date_type.fromisoformat(payment_date)
                except ValueError:
                    console.print(f"[red]✗[/red] Invalid date format: {payment_date}. Use YYYY-MM-DD.")
                    sys.exit(1)
            try:
                inv = svc.record_payment(
                    invoice_id=invoice_id,
                    amount=inv.amount_remaining,
                    method=method,
                    reference=reference,
                    payment_date=parsed_date,
                )
                sym = get_currency_symbol(inv.currency)
                console.print(f"[green]✓[/green] Invoice {inv.id} marked as PAID ({sym}{inv.total:.2f})")
            except ValueError as e:
                console.print(f"[red]✗[/red] {e}")
                sys.exit(1)
        else:
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


# --- Line item commands ---

@main.group("items")
def items():
    """Manage invoice line items."""
    pass


@items.command("add")
@click.argument("invoice_id")
@click.option("--description", "-d", required=True, help="Item description")
@click.option("--quantity", "-q", type=float, default=1.0, help="Quantity (default: 1)")
@click.option("--price", "-p", type=float, required=True, help="Unit price")
@click.option("--tax-rate", "-t", type=float, default=None, help="Tax rate %")
def items_add(invoice_id: str, description: str, quantity: float, price: float, tax_rate: Optional[float]):
    """Add a line item to a draft invoice."""
    svc = get_service()
    item_data = {"description": description, "quantity": quantity, "unit_price": price}
    if tax_rate is not None:
        item_data["tax_rate"] = tax_rate
    try:
        inv = svc.add_line_item(invoice_id, item_data)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Item added to {inv.id}")
        console.print(f"  Items:  {len(inv.line_items)}")
        console.print(f"  Total:  {sym}{inv.total:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@items.command("remove")
@click.argument("invoice_id")
@click.argument("index", type=int)
def items_remove(invoice_id: str, index: int):
    """Remove a line item by index (0-based) from a draft invoice."""
    svc = get_service()
    try:
        inv = svc.remove_line_item(invoice_id, index)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Item {index} removed from {inv.id}")
        console.print(f"  Items:  {len(inv.line_items)}")
        console.print(f"  Total:  {sym}{inv.total:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@main.command("export")
@click.argument("invoice_id")
@click.option("--format", "-f", type=click.Choice(["markdown", "json", "pdf"]), default="markdown", help="Export format")
@click.option("--output", "-o", help="Output file path (for PDF)")
@click.option("--company", help="Company name for PDF header")
@click.option("--company-address", help="Company address for PDF")
@click.option("--company-email", help="Company email for PDF")
def invoice_export(invoice_id: str, format: str, output: Optional[str], company: Optional[str], company_address: Optional[str], company_email: Optional[str]):
    """Export an invoice."""
    svc = get_service()
    inv = svc.get_invoice(invoice_id)
    if not inv:
        console.print(f"[red]✗[/red] Invoice not found: {invoice_id}")
        sys.exit(1)
    if format == "markdown":
        console.print(inv.to_markdown())
    elif format == "json":
        console.print(inv.model_dump_json(indent=2))
    elif format == "pdf":
        try:
            pdf_path = svc.export_pdf(
                invoice_id=invoice_id,
                output_path=output,
                company_name=company,
                company_address=company_address,
                company_email=company_email,
            )
            console.print(f"[green]✓[/green] PDF exported: {pdf_path}")
        except ValueError as e:
            console.print(f"[red]✗[/red] {e}")
            sys.exit(1)


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
    if summary.total_payments > 0:
        console.print(f"  Total Payments:  [dim]{sym}{summary.total_payments:.2f}[/dim]")
    parts = [f"Invoices: {summary.invoice_count}", f"Paid: {summary.paid_count}", f"Pending: {summary.pending_count}", f"Overdue: {summary.overdue_count}"]
    if summary.partially_paid_count > 0:
        parts.append(f"Partial: {summary.partially_paid_count}")
    console.print(f"\n  {'  |  '.join(parts)}")


# --- Payment commands ---

@main.group("payments")
def payments():
    """Manage invoice payments."""
    pass


@payments.command("list")
@click.argument("invoice_id")
def payments_list(invoice_id: str):
    """List all payments for an invoice."""
    svc = get_service()
    try:
        pay_list = svc.list_payments(invoice_id)
        if not pay_list:
            console.print("[dim]No payments found for this invoice.[/dim]")
            return

        inv = svc.get_invoice(invoice_id)
        sym = get_currency_symbol(inv.currency) if inv else "$"

        table = Table(title=f"Payments for {invoice_id}")
        table.add_column("ID", style="cyan")
        table.add_column("Date")
        table.add_column("Amount", justify="right", style="green")
        table.add_column("Method")
        table.add_column("Reference")
        table.add_column("Notes")
        for p in pay_list:
            table.add_row(
                p.id,
                str(p.payment_date),
                f"{sym}{p.amount:.2f}",
                p.method or "—",
                p.reference or "—",
                p.notes or "—",
            )
        console.print(table)
        if inv:
            console.print(f"  Total: {sym}{inv.total:.2f}  |  Paid: {sym}{inv.amount_paid:.2f}  |  Remaining: {sym}{inv.amount_remaining:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@payments.command("remove")
@click.argument("invoice_id")
@click.argument("payment_id")
def payments_remove(invoice_id: str, payment_id: str):
    """Remove a payment from an invoice."""
    svc = get_service()
    try:
        inv = svc.remove_payment(invoice_id, payment_id)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Payment {payment_id} removed from {invoice_id}")
        console.print(f"  Status:    {inv.status.value.replace('_', ' ').upper()}")
        console.print(f"  Paid:      {sym}{inv.amount_paid:.2f}")
        console.print(f"  Remaining: {sym}{inv.amount_remaining:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


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


# --- Template commands ---

@main.group("template")
def template():
    """Manage invoice templates."""
    pass


@template.command("list")
@click.option("--category", help="Filter by category")
def template_list(category: Optional[str]):
    """List available invoice templates (built-in + custom)."""
    svc = get_service()
    templates = svc.list_templates(category=category)
    if not templates:
        console.print("[dim]No templates found.[/dim]")
        return

    table = Table(title="Invoice Templates")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Category")
    table.add_column("Items", justify="right")
    table.add_column("Total")
    table.add_column("Due Days", justify="right")
    table.add_column("Type")
    for tpl in templates:
        sym = get_currency_symbol(tpl.currency)
        tpl_type = "Built-in" if tpl.id.startswith("TPL-") and any(t["id"] == tpl.id for t in BUILTIN_TEMPLATES) else "Custom"
        table.add_row(
            tpl.id,
            tpl.name,
            tpl.category or "—",
            str(len(tpl.line_items)),
            f"{sym}{tpl.total:.2f}",
            str(tpl.due_days),
            tpl_type,
        )
    console.print(table)


@template.command("show")
@click.argument("template_id")
def template_show(template_id: str):
    """Show template details."""
    svc = get_service()
    tpl = svc.get_template(template_id)
    if not tpl:
        console.print(f"[red]✗[/red] Template not found: {template_id}")
        sys.exit(1)
    sym = get_currency_symbol(tpl.currency)
    console.print(f"\n[bold]Template: {tpl.name}[/bold] ({tpl.id})")
    if tpl.description:
        console.print(f"  {tpl.description}")
    console.print(f"  Category: {tpl.category or '—'}")
    console.print(f"  Currency: {tpl.currency}")
    console.print(f"  Due Days: {tpl.due_days}")
    console.print(f"  Tax Rate: {tpl.tax_rate}%")
    if tpl.discount_amount > 0:
        console.print(f"  Discount: {sym}{tpl.discount_amount:.2f}")
    if tpl.notes:
        console.print(f"  Notes: {tpl.notes}")
    console.print(f"\n  [bold]Line Items:[/bold]")
    for i, item in enumerate(tpl.line_items):
        tax_str = f" ({item.tax_rate}% tax)" if item.tax_rate > 0 else ""
        console.print(f"    {i}. {item.description} — qty {item.quantity} × {sym}{item.unit_price:.2f}{tax_str}")
    console.print(f"\n  [bold]Total: {sym}{tpl.total:.2f}[/bold]")


@template.command("create")
@click.option("--name", "-n", required=True, help="Template name")
@click.option("--item", "-i", multiple=True, help="Line item: 'description,quantity,unit_price[,tax_rate]'")
@click.option("--description", "-d", help="Template description")
@click.option("--category", help="Template category")
@click.option("--due-days", type=int, default=30, help="Days until due date")
@click.option("--currency", default="USD", help="Currency (default: USD)")
@click.option("--tax-rate", type=float, default=0.0, help="Invoice-level tax rate %%")
@click.option("--discount", type=float, default=0.0, help="Flat discount amount")
@click.option("--notes", help="Notes for generated invoices")
def template_create(name: str, item: tuple, description: Optional[str], category: Optional[str], due_days: int, currency: str, tax_rate: float, discount: float, notes: Optional[str]):
    """Create a custom invoice template."""
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
        tpl = svc.create_template(
            name=name,
            line_items=line_items,
            description=description,
            tax_rate=tax_rate if tax_rate > 0 else None,
            discount_amount=discount if discount > 0 else None,
            due_days=due_days,
            currency=currency,
            notes=notes,
            category=category,
        )
        sym = get_currency_symbol(tpl.currency)
        console.print(f"[green]✓[/green] Template created: {tpl.id} — {tpl.name}")
        console.print(f"  Items:  {len(tpl.line_items)}")
        console.print(f"  Total:  {sym}{tpl.total:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@template.command("use")
@click.argument("template_id")
@click.option("--client", "-c", required=True, help="Client ID or name")
@click.option("--due-days", type=int, default=None, help="Override due days")
@click.option("--discount", type=float, default=None, help="Override discount amount")
@click.option("--notes", help="Override notes")
@click.option("--currency", help="Override currency")
def template_use(template_id: str, client: str, due_days: Optional[int], discount: Optional[float], notes: Optional[str], currency: Optional[str]):
    """Create an invoice from a template."""
    svc = get_service()
    overrides = {}
    if due_days is not None:
        overrides["due_days"] = due_days
    if discount is not None:
        overrides["discount_amount"] = discount
    if notes is not None:
        overrides["notes"] = notes
    if currency is not None:
        overrides["currency"] = currency

    try:
        inv = svc.create_invoice_from_template(template_id, client, overrides=overrides)
        sym = get_currency_symbol(inv.currency)
        console.print(f"[green]✓[/green] Invoice created from template: {inv.id}")
        console.print(f"  Client: {inv.client_name}")
        console.print(f"  Items:  {len(inv.line_items)}")
        console.print(f"  Total:  {sym}{inv.total:.2f}")
        console.print(f"  Due:    {inv.due_date}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@template.command("remove")
@click.argument("template_id")
def template_remove(template_id: str):
    """Remove a custom template (cannot remove built-in)."""
    svc = get_service()
    try:
        if svc.remove_template(template_id):
            console.print(f"[green]✓[/green] Template removed: {template_id}")
        else:
            console.print(f"[red]✗[/red] Template not found: {template_id}")
            sys.exit(1)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


# --- Dunning commands ---

@main.group("dunning")
def dunning():
    """Manage overdue dunning reminders."""
    pass


@dunning.command("config")
def dunning_config_show():
    """Show current dunning configuration."""
    svc = get_service()
    config = svc.get_dunning_config()
    console.print(f"\n[bold]Dunning Configuration[/bold]\n")
    console.print(f"  Enabled:              {'[green]Yes[/green]' if config.enabled else '[red]No[/red]'}")
    console.print(f"  First Reminder:      {config.first_reminder_days} days overdue")
    console.print(f"  Second Reminder:     {config.second_reminder_days} days overdue")
    console.print(f"  Final Notice:        {config.final_notice_days} days overdue")


@dunning.command("set-config")
@click.option("--first-reminder-days", type=int, help="Days overdue for first reminder")
@click.option("--second-reminder-days", type=int, help="Days overdue for second reminder")
@click.option("--final-notice-days", type=int, help="Days overdue for final notice")
@click.option("--enabled/--disabled", default=None, help="Enable or disable dunning")
def dunning_config_set(first_reminder_days: Optional[int], second_reminder_days: Optional[int], final_notice_days: Optional[int], enabled: Optional[bool]):
    """Update dunning configuration."""
    svc = get_service()
    try:
        config = svc.update_dunning_config(
            first_reminder_days=first_reminder_days,
            second_reminder_days=second_reminder_days,
            final_notice_days=final_notice_days,
            enabled=enabled,
        )
        console.print(f"[green]✓[/green] Dunning config updated")
        console.print(f"  First Reminder:  {config.first_reminder_days} days")
        console.print(f"  Second Reminder: {config.second_reminder_days} days")
        console.print(f"  Final Notice:    {config.final_notice_days} days")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@dunning.command("send")
@click.argument("invoice_id")
@click.option("--level", "-l", type=click.Choice(["first_reminder", "second_reminder", "final_notice"]), default=None, help="Override dunning level")
@click.option("--message", "-m", help="Custom reminder message")
def dunning_send(invoice_id: str, level: Optional[str], message: Optional[str]):
    """Send a dunning reminder for an overdue invoice."""
    svc = get_service()
    try:
        action = svc.send_dunning_reminder(invoice_id, level=level, message=message)
        console.print(f"[green]✓[/green] Dunning reminder sent: {action.id}")
        console.print(f"  Level:  {action.level.value.replace('_', ' ').title()}")
        console.print(f"  Days Overdue: {action.days_overdue}")
        if action.message:
            console.print(f"  Message: {action.message}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@dunning.command("process")
def dunning_process():
    """Auto-send dunning reminders for all overdue invoices."""
    svc = get_service()
    actions = svc.process_overdue_dunning()
    if not actions:
        console.print("[dim]No dunning reminders needed.[/dim]")
        return
    console.print(f"[green]✓[/green] Sent {len(actions)} dunning reminder(s):")
    for action in actions:
        level_str = action.level.value.replace("_", " ").title()
        console.print(f"  {action.id} — {action.invoice_id} — {level_str} — {action.days_overdue} days overdue")


@dunning.command("list")
@click.option("--invoice", help="Filter by invoice ID")
def dunning_list(invoice: Optional[str]):
    """List dunning actions/reminders."""
    svc = get_service()
    actions = svc.list_dunning_actions(invoice_id=invoice)
    if not actions:
        console.print("[dim]No dunning actions found.[/dim]")
        return

    table = Table(title="Dunning Actions")
    table.add_column("ID", style="cyan")
    table.add_column("Invoice", style="bold")
    table.add_column("Level")
    table.add_column("Days Overdue", justify="right")
    table.add_column("Sent At")
    for action in actions:
        level_str = action.level.value.replace("_", " ").title()
        table.add_row(
            action.id,
            action.invoice_id,
            level_str,
            str(action.days_overdue),
            action.sent_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@dunning.command("remove")
@click.argument("action_id")
def dunning_remove(action_id: str):
    """Remove a dunning action record."""
    svc = get_service()
    if svc.remove_dunning_action(action_id):
        console.print(f"[green]✓[/green] Dunning action removed: {action_id}")
    else:
        console.print(f"[red]✗[/red] Dunning action not found: {action_id}")
        sys.exit(1)


# --- Credit note commands ---

@main.group("credit")
def credit():
    """Manage credit notes."""
    pass


@credit.command("create")
@click.option("--client", "-c", required=True, help="Client ID or name")
@click.option("--amount", "-a", type=float, required=True, help="Credit amount")
@click.option("--reason", "-r", help="Reason for the credit (e.g. refund, overpayment)")
@click.option("--invoice", help="Original invoice this credit relates to")
@click.option("--currency", help="Currency code (defaults to client's)")
def credit_create(client: str, amount: float, reason: Optional[str], invoice: Optional[str], currency: Optional[str]):
    """Create a credit note for a client."""
    svc = get_service()
    try:
        credit_note = svc.create_credit_note(
            client_identifier=client,
            amount=amount,
            reason=reason,
            invoice_id=invoice,
            currency=currency,
        )
        sym = get_currency_symbol(credit_note.currency)
        console.print(f"[green]✓[/green] Credit note created: {credit_note.id}")
        console.print(f"  Client:   {credit_note.client_name}")
        console.print(f"  Amount:   {sym}{credit_note.amount:.2f}")
        if credit_note.reason:
            console.print(f"  Reason:   {credit_note.reason}")
        if credit_note.invoice_id:
            console.print(f"  Invoice:  {credit_note.invoice_id}")
        console.print(f"  Status:   {credit_note.status.value}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@credit.command("list")
@click.option("--client", "-c", help="Filter by client ID or name")
@click.option("--status", "-s", type=click.Choice(["open", "applied", "void"]), help="Filter by status")
def credit_list(client: Optional[str], status: Optional[str]):
    """List credit notes."""
    svc = get_service()
    try:
        credits = svc.list_credit_notes(client=client, status=status)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)
    if not credits:
        console.print("[dim]No credit notes found.[/dim]")
        return
    table = Table(title="Credit Notes")
    table.add_column("ID", style="cyan")
    table.add_column("Client", style="bold")
    table.add_column("Amount", justify="right")
    table.add_column("Applied", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Status")
    table.add_column("Reason")
    table.add_column("Date")
    for credit_note in credits:
        sym = get_currency_symbol(credit_note.currency)
        status_style = {
            "open": "[green]OPEN[/green]",
            "applied": "[blue]APPLIED[/blue]",
            "void": "[dim]VOID[/dim]",
        }.get(credit_note.status.value, credit_note.status.value)
        table.add_row(
            credit_note.id,
            credit_note.client_name or credit_note.client_id,
            f"{sym}{credit_note.amount:.2f}",
            f"{sym}{credit_note.applied_amount:.2f}",
            f"{sym}{credit_note.remaining_amount:.2f}",
            status_style,
            credit_note.reason or "—",
            str(credit_note.issue_date),
        )
    console.print(table)


@credit.command("show")
@click.argument("credit_id")
def credit_show(credit_id: str):
    """Show credit note details."""
    svc = get_service()
    credit_note = svc.get_credit_note(credit_id)
    if not credit_note:
        console.print(f"[red]✗[/red] Credit note not found: {credit_id}")
        sys.exit(1)
    sym = get_currency_symbol(credit_note.currency)
    console.print(f"\n[bold]Credit Note: {credit_note.id}[/bold]")
    console.print(f"  Client:    {credit_note.client_name} ({credit_note.client_id})")
    console.print(f"  Amount:    {sym}{credit_note.amount:.2f} {credit_note.currency}")
    console.print(f"  Applied:   {sym}{credit_note.applied_amount:.2f}")
    console.print(f"  Remaining: {sym}{credit_note.remaining_amount:.2f}")
    console.print(f"  Status:    {credit_note.status.value}")
    if credit_note.reason:
        console.print(f"  Reason:    {credit_note.reason}")
    if credit_note.invoice_id:
        console.print(f"  Invoice:   {credit_note.invoice_id}")
    if credit_note.applications:
        console.print(f"\n  [bold]Applications:[/bold]")
        for app in credit_note.applications:
            console.print(f"    {app['invoice_id']}: {sym}{app['amount']:.2f}")


@credit.command("apply")
@click.argument("credit_id")
@click.argument("invoice_id")
@click.option("--amount", "-a", type=float, default=None, help="Amount to apply (defaults to remaining credit or balance)")
def credit_apply(credit_id: str, invoice_id: str, amount: Optional[float]):
    """Apply a credit note to an invoice."""
    svc = get_service()
    try:
        credit_note, invoice = svc.apply_credit_note(credit_id, invoice_id, amount=amount)
        sym = get_currency_symbol(invoice.currency)
        console.print(f"[green]✓[/green] Applied credit note {credit_note.id} to invoice {invoice.id}")
        console.print(f"  Credit remaining: {sym}{credit_note.remaining_amount:.2f}")
        console.print(f"  Invoice status:   {invoice.status.value}")
        console.print(f"  Invoice paid:     {sym}{invoice.amount_paid:.2f}")
        console.print(f"  Invoice remaining:{sym}{invoice.amount_remaining:.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@credit.command("void")
@click.argument("credit_id")
def credit_void(credit_id: str):
    """Void a credit note."""
    svc = get_service()
    try:
        credit_note = svc.void_credit_note(credit_id)
        console.print(f"[yellow]✓[/yellow] Credit note {credit_note.id} voided")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


@credit.command("remove")
@click.argument("credit_id")
def credit_remove(credit_id: str):
    """Remove a credit note (must be voided first)."""
    svc = get_service()
    try:
        if svc.remove_credit_note(credit_id):
            console.print(f"[green]✓[/green] Credit note removed: {credit_id}")
        else:
            console.print(f"[red]✗[/red] Credit note not found: {credit_id}")
            sys.exit(1)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)


# --- Statement command ---

@main.command("statement")
@click.argument("client")
@click.option("--from", "date_from_str", required=True, help="Period start date (YYYY-MM-DD)")
@click.option("--to", "date_to_str", required=True, help="Period end date (YYYY-MM-DD)")
@click.option("--currency", help="Filter by currency")
def client_statement(client: str, date_from_str: str, date_to_str: str, currency: Optional[str]):
    """Generate a financial statement for a client."""
    from datetime import date as date_type
    try:
        period_start = date_type.fromisoformat(date_from_str)
        period_end = date_type.fromisoformat(date_to_str)
    except ValueError:
        console.print(f"[red]✗[/red] Invalid date format. Use YYYY-MM-DD.")
        sys.exit(1)
    svc = get_service()
    try:
        stmt = svc.generate_client_statement(
            client_identifier=client,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)

    sym = get_currency_symbol(stmt.currency)
    console.print(f"\n[bold]Statement: {stmt.client_name}[/bold]")
    console.print(f"  Period:   {stmt.period_start} to {stmt.period_end}")
    console.print(f"  Currency: {stmt.currency}")
    console.print(f"\n  Opening Balance: {sym}{stmt.opening_balance:.2f}")
    console.print(f"  Invoiced:        {sym}{stmt.total_invoiced:.2f}")
    console.print(f"  Paid:           -{sym}{stmt.total_paid:.2f}")
    console.print(f"  Credits:        -{sym}{stmt.total_credits:.2f}")
    console.print(f"  [bold]Closing Balance:  {sym}{stmt.closing_balance:.2f}[/bold]")

    if stmt.invoices:
        console.print(f"\n  [bold]Invoices ({len(stmt.invoices)}):[/bold]")
        for inv in stmt.invoices:
            console.print(f"    {inv['id']} — {inv['issue_date']} — {sym}{inv['total']:.2f} — {inv['status']}")

    if stmt.payments:
        console.print(f"\n  [bold]Payments ({len(stmt.payments)}):[/bold]")
        for p in stmt.payments:
            console.print(f"    {p['date']} — {p['invoice_id']} — {sym}{p['amount']:.2f} — {p.get('method', '—')}")

    if stmt.credit_notes:
        console.print(f"\n  [bold]Credit Notes ({len(stmt.credit_notes)}):[/bold]")
        for cn in stmt.credit_notes:
            console.print(f"    {cn['id']} — {cn['date']} — {sym}{cn['amount']:.2f} — {cn.get('reason', '—')}")


# --- A/R Aging Report ---

@main.command("ar-aging")
@click.option("--currency", default=None, help="Filter by currency")
def ar_aging(currency):
    """Show A/R (Accounts Receivable) aging report.

    Groups outstanding invoice balances into aging buckets:
    0-30, 31-60, 61-90, and 90+ days past due.
    """
    svc = get_service()
    report = svc.generate_ar_aging_report(currency=currency)

    console.print(f"\n[bold]A/R Aging Report — As of {report.as_of_date}[/bold]")
    if report.currency:
        console.print(f"  Currency: {report.currency}")
    console.print(f"  Total Outstanding: {report.total_outstanding:.2f}")
    console.print(f"  Clients with Balances: {report.client_count}")

    if not report.clients:
        console.print("\n  [green]No outstanding balances. All caught up![/green]")
        return

    # Summary table
    console.print(f"\n[bold]Aging Buckets (Totals):[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Bucket")
    table.add_column("Invoices", justify="right")
    table.add_column("Outstanding", justify="right")
    for b in report.bucket_totals:
        table.add_row(b.label, str(b.invoice_count), f"{b.total_outstanding:.2f}")
    console.print(table)

    # Per-client detail
    console.print(f"\n[bold]By Client:[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Client")
    table.add_column("Total", justify="right")
    for b in report.bucket_totals:
        table.add_column(b.label, justify="right")
    table.add_column("Details", justify="left")
    for c in report.clients:
        # Build bucket amounts map
        bucket_amounts = {b.label: b.total_outstanding for b in c.buckets}
        details = ", ".join(f"{d['id']} ({d['days_overdue']}d)" for d in c.invoice_details[:3])
        if len(c.invoice_details) > 3:
            details += f" +{len(c.invoice_details) - 3} more"
        row = [c.client_name or c.client_id, f"{c.total_outstanding:.2f}"]
        for b in report.bucket_totals:
            amt = bucket_amounts.get(b.label, 0.0)
            row.append(f"{amt:.2f}" if amt > 0 else "—")
        row.append(details)
        table.add_row(*row)
    console.print(table)


# --- Revenue Analytics ---

@main.command("revenue")
@click.option("--months", type=int, default=6, help="Number of months to analyze (default: 6)")
@click.option("--currency", default=None, help="Filter by currency")
def revenue_analytics(months: int, currency: str):
    """Show revenue analytics for the last N months.

    Displays monthly revenue trends, collection rate, average days to pay,
    and top clients.
    """
    from datetime import date, timedelta

    svc = get_service()
    today = date.today()
    # Compute start date: first day of the month N-1 months ago (pure stdlib)
    start_month = today.month - (months - 1)
    start_year = today.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)

    analytics = svc.get_revenue_analytics(start, today, currency=currency)

    console.print(f"\n[bold]Revenue Analytics — {analytics.period_start} to {analytics.period_end}[/bold]")
    console.print(f"  Currency: {analytics.currency}")
    console.print(f"  Total Invoiced:  {analytics.total_invoiced:.2f}")
    console.print(f"  Total Collected: {analytics.total_collected:.2f}")
    console.print(f"  Collection Rate: {analytics.collection_rate:.1f}%")
    console.print(f"  Avg Days to Pay: {analytics.avg_days_to_pay:.1f}")
    if analytics.fastest_payment_days is not None:
        console.print(f"  Fastest Payment: {analytics.fastest_payment_days} days")
        console.print(f"  Slowest Payment: {analytics.slowest_payment_days} days")

    if analytics.months:
        console.print(f"\n[bold]Monthly Breakdown:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Month")
        table.add_column("Invoiced", justify="right")
        table.add_column("Collected", justify="right")
        table.add_column("Outstanding", justify="right")
        table.add_column("Invoices", justify="right")
        table.add_column("Paid", justify="right")
        for m in analytics.months:
            table.add_row(
                m.period,
                f"{m.invoiced:.2f}",
                f"{m.collected:.2f}",
                f"{m.outstanding:.2f}",
                str(m.invoice_count),
                str(m.paid_invoice_count),
            )
        console.print(table)

    if analytics.top_clients:
        console.print(f"\n[bold]Top Clients:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Client")
        table.add_column("Invoiced", justify="right")
        table.add_column("Paid", justify="right")
        for tc in analytics.top_clients[:5]:
            table.add_row(
                tc.get("client_name", tc.get("client_id", "?")),
                f"{tc['total_invoiced']:.2f}",
                f"{tc['total_paid']:.2f}",
            )
        console.print(table)


# --- Estimates ---

@main.group("estimate")
def estimate_group():
    """Manage estimates and quotes."""
    pass


@estimate_group.command("create")
@click.argument("client")
@click.option("--description", required=True, help="Description of the line item")
@click.option("--quantity", type=float, default=1.0, help="Quantity")
@click.option("--price", type=float, required=True, help="Unit price")
@click.option("--currency", default=None, help="Currency (default: client's)")
@click.option("--notes", default=None, help="Notes")
@click.option("--terms", default=None, help="Terms or scope description")
@click.option("--expiry", type=int, default=30, help="Days until expiry (default: 30)")
@click.option("--tax-rate", type=float, default=None, help="Tax rate %")
@click.option("--discount", type=float, default=None, help="Discount amount")
def estimate_create(client, description, quantity, price, currency, notes, terms, expiry, tax_rate, discount):
    """Create a new estimate/quote for a client."""
    svc = get_service()
    line_items = [{"description": description, "quantity": quantity, "unit_price": price, "tax_rate": tax_rate or 0}]
    estimate = svc.create_estimate(
        client_identifier=client,
        line_items=line_items,
        currency=currency,
        notes=notes,
        terms=terms,
        expiry_days=expiry,
        tax_rate=tax_rate,
        discount_amount=discount,
    )
    sym = get_currency_symbol(estimate.currency)
    console.print(f"[green]✓ Estimate {estimate.id} created[/green]")
    console.print(f"  Client:   {estimate.client_name or estimate.client_id}")
    console.print(f"  Status:   {estimate.status.value}")
    console.print(f"  Total:    {sym}{estimate.total:.2f}")
    console.print(f"  Expires:  {estimate.expiry_date}")


@estimate_group.command("list")
@click.option("--status", default=None, help="Filter by status (draft, sent, accepted, declined, expired, converted)")
@click.option("--client", default=None, help="Filter by client")
def estimate_list(status, client):
    """List estimates."""
    svc = get_service()
    estimates = svc.list_estimates(status=status, client=client)
    if not estimates:
        console.print("[yellow]No estimates found.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Total", justify="right")
    table.add_column("Issue Date")
    table.add_column("Expires")
    for est in estimates:
        sym = get_currency_symbol(est.currency)
        table.add_row(
            est.id,
            est.client_name or est.client_id,
            est.status.value,
            f"{sym}{est.total:.2f}",
            str(est.issue_date),
            str(est.expiry_date) if est.expiry_date else "—",
        )
    console.print(table)


@estimate_group.command("show")
@click.argument("estimate_id")
def estimate_show(estimate_id):
    """Show estimate details."""
    svc = get_service()
    est = svc.get_estimate(estimate_id)
    if not est:
        console.print(f"[red]Estimate '{estimate_id}' not found.[/red]")
        sys.exit(1)
    console.print(est.to_markdown())


@estimate_group.command("send")
@click.argument("estimate_id")
def estimate_send(estimate_id):
    """Mark an estimate as sent."""
    svc = get_service()
    est = svc.send_estimate(estimate_id)
    console.print(f"[green]✓ Estimate {est.id} marked as sent.[/green]")


@estimate_group.command("accept")
@click.argument("estimate_id")
def estimate_accept(estimate_id):
    """Mark an estimate as accepted."""
    svc = get_service()
    est = svc.accept_estimate(estimate_id)
    console.print(f"[green]✓ Estimate {est.id} accepted.[/green]")


@estimate_group.command("decline")
@click.argument("estimate_id")
def estimate_decline(estimate_id):
    """Mark an estimate as declined."""
    svc = get_service()
    est = svc.decline_estimate(estimate_id)
    console.print(f"[yellow]✓ Estimate {est.id} declined.[/yellow]")


@estimate_group.command("convert")
@click.argument("estimate_id")
@click.option("--due-days", type=int, default=30, help="Days until due for the new invoice")
def estimate_convert(estimate_id, due_days):
    """Convert an estimate to an invoice."""
    svc = get_service()
    est, inv = svc.convert_estimate_to_invoice(estimate_id, due_days=due_days)
    console.print(f"[green]✓ Estimate {est.id} converted to Invoice {inv.id}[/green]")
    console.print(f"  Invoice Total: {inv.currency} {inv.total:.2f}")
    console.print(f"  Due Date:      {inv.due_date}")


@estimate_group.command("delete")
@click.argument("estimate_id")
def estimate_delete(estimate_id):
    """Delete an estimate."""
    svc = get_service()
    if svc.remove_estimate(estimate_id):
        console.print(f"[green]✓ Estimate {estimate_id} deleted.[/green]")
    else:
        console.print(f"[red]Estimate '{estimate_id}' not found.[/red]")
        sys.exit(1)


# --- REST API serve ---

@main.command("api")
@click.option("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
@click.option("--port", type=int, default=8000, help="Port to bind (default: 8000)")
def api_serve(host: str, port: int):
    """Start the REST API server."""
    from .api import create_app
    import uvicorn
    console.print(f"[bold]Starting Agent Invoice REST API on {host}:{port}...[/bold]")
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
