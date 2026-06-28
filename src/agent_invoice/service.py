"""Business logic / service layer for Agent Invoice."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import Client, EarningsSummary, Invoice, InvoiceStatus, LineItem
from .store import InvoiceStore


class InvoiceService:
    """High-level operations for invoice management."""

    def __init__(self, store: Optional[InvoiceStore] = None):
        self.store = store or InvoiceStore()

    # --- Client operations ---

    def add_client(self, name: str, email: Optional[str] = None, address: Optional[str] = None) -> Client:
        """Create and save a new client."""
        existing = self.store.find_client_by_name(name)
        if existing:
            raise ValueError(f"Client '{name}' already exists (ID: {existing.id})")
        client = Client(name=name, email=email, address=address)
        return self.store.save_client(client)

    def get_client(self, identifier: str) -> Optional[Client]:
        """Get a client by ID or name."""
        client = self.store.get_client(identifier)
        if client:
            return client
        return self.store.find_client_by_name(identifier)

    def list_clients(self) -> list[Client]:
        return self.store.list_clients()

    def remove_client(self, identifier: str) -> bool:
        client = self.get_client(identifier)
        if not client:
            return False
        return self.store.delete_client(client.id)

    # --- Invoice operations ---

    def create_invoice(
        self,
        client_identifier: str,
        line_items: list[dict],
        due_days: Optional[int] = 30,
        notes: Optional[str] = None,
    ) -> Invoice:
        """Create a new invoice.

        Args:
            client_identifier: Client ID or name.
            line_items: List of dicts with keys: description, quantity, unit_price.
            due_days: Number of days until due date. None means no due date.
            notes: Optional notes on the invoice.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found. Add them first with 'client add'.")

        items = []
        for item_data in line_items:
            items.append(LineItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1.0),
                unit_price=item_data["unit_price"],
            ))

        invoice_id = self.store.get_next_invoice_number()
        invoice = Invoice(
            id=invoice_id,
            client_id=client.id,
            client_name=client.name,
            line_items=items,
            status=InvoiceStatus.DRAFT,
            notes=notes,
        )
        if due_days is not None:
            invoice.set_due_date(due_days)

        return self.store.save_invoice(invoice)

    def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        return self.store.get_invoice(invoice_id)

    def list_invoices(
        self,
        status: Optional[InvoiceStatus] = None,
        client: Optional[str] = None,
    ) -> list[Invoice]:
        client_id = None
        if client:
            c = self.get_client(client)
            if c:
                client_id = c.id
        return self.store.list_invoices(status=status, client_id=client_id)

    def mark_paid(self, invoice_id: str) -> Invoice:
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status == InvoiceStatus.PAID:
            raise ValueError(f"Invoice '{invoice_id}' is already paid.")
        invoice.mark_paid()
        return self.store.save_invoice(invoice)

    def mark_sent(self, invoice_id: str) -> Invoice:
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        invoice.mark_sent()
        return self.store.save_invoice(invoice)

    def cancel_invoice(self, invoice_id: str) -> Invoice:
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status == InvoiceStatus.PAID:
            raise ValueError(f"Cannot cancel a paid invoice.")
        invoice.status = InvoiceStatus.CANCELLED
        invoice.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_invoice(invoice)

    def remove_invoice(self, invoice_id: str) -> bool:
        return self.store.delete_invoice(invoice_id)

    # --- Earnings ---

    def earnings_summary(self) -> EarningsSummary:
        invoices = self.store.list_invoices()
        summary = EarningsSummary(invoice_count=len(invoices))
        for inv in invoices:
            subtotal = inv.subtotal
            summary.total_invoiced += subtotal
            if inv.status == InvoiceStatus.PAID:
                summary.total_paid += subtotal
                summary.paid_count += 1
            elif inv.status == InvoiceStatus.OVERDUE:
                summary.total_overdue += subtotal
                summary.overdue_count += 1
                summary.total_pending += subtotal
                summary.pending_count += 1
            elif inv.status in (InvoiceStatus.SENT, InvoiceStatus.DRAFT):
                summary.total_pending += subtotal
                summary.pending_count += 1
        summary.total_invoiced = round(summary.total_invoiced, 2)
        summary.total_paid = round(summary.total_paid, 2)
        summary.total_pending = round(summary.total_pending, 2)
        summary.total_overdue = round(summary.total_overdue, 2)
        return summary
