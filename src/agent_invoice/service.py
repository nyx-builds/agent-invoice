"""Business logic / service layer for Agent Invoice."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import (
    CURRENCIES,
    Client,
    EarningsSummary,
    Invoice,
    InvoiceStatus,
    LineItem,
    NumberingConfig,
    RecurrenceFrequency,
    RecurringInvoice,
    format_amount,
)
from .store import InvoiceStore


class InvoiceService:
    """High-level operations for invoice management."""

    def __init__(self, store: Optional[InvoiceStore] = None):
        self.store = store or InvoiceStore()

    # --- Client operations ---

    def add_client(
        self,
        name: str,
        email: Optional[str] = None,
        address: Optional[str] = None,
        currency: str = "USD",
    ) -> Client:
        """Create and save a new client."""
        existing = self.store.find_client_by_name(name)
        if existing:
            raise ValueError(f"Client '{name}' already exists (ID: {existing.id})")
        if currency.upper() not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}. Supported: {', '.join(sorted(CURRENCIES.keys()))}")
        client = Client(name=name, email=email, address=address, currency=currency.upper())
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

    # --- Numbering config ---

    def get_numbering_config(self) -> NumberingConfig:
        return self.store.get_numbering_config()

    def update_numbering_config(
        self,
        prefix: Optional[str] = None,
        separator: Optional[str] = None,
        digits: Optional[int] = None,
        next_number: Optional[int] = None,
    ) -> NumberingConfig:
        """Update the numbering configuration."""
        config = self.store.get_numbering_config()
        if prefix is not None:
            config.prefix = prefix
        if separator is not None:
            config.separator = separator
        if digits is not None:
            config.digits = digits
        if next_number is not None:
            config.next_number = next_number
        return self.store.save_numbering_config(config)

    # --- Invoice operations ---

    def create_invoice(
        self,
        client_identifier: str,
        line_items: list[dict],
        due_days: Optional[int] = 30,
        notes: Optional[str] = None,
        currency: Optional[str] = None,
        tax_rate: Optional[float] = None,
        discount_amount: Optional[float] = None,
    ) -> Invoice:
        """Create a new invoice.

        Args:
            client_identifier: Client ID or name.
            line_items: List of dicts with keys: description, quantity, unit_price, tax_rate.
            due_days: Number of days until due date. None means no due date.
            notes: Optional notes on the invoice.
            currency: Override currency (uses client default if not specified).
            tax_rate: Invoice-level default tax rate for items without their own.
            discount_amount: Flat discount to apply.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found. Add them first with 'client add'.")

        # Determine currency
        inv_currency = (currency or client.currency).upper()
        if inv_currency not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {inv_currency}. Supported: {', '.join(sorted(CURRENCIES.keys()))}")

        # Determine invoice-level tax rate
        inv_tax_rate = tax_rate if tax_rate is not None else 0.0

        items = []
        for item_data in line_items:
            item_tax = item_data.get("tax_rate", None)
            # If item has no tax_rate and invoice has one, apply invoice-level tax
            effective_tax = item_tax if item_tax is not None else inv_tax_rate
            items.append(LineItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1.0),
                unit_price=item_data["unit_price"],
                tax_rate=effective_tax,
            ))

        invoice_id = self.store.get_next_invoice_number()
        invoice = Invoice(
            id=invoice_id,
            client_id=client.id,
            client_name=client.name,
            line_items=items,
            status=InvoiceStatus.DRAFT,
            notes=notes,
            currency=inv_currency,
            tax_rate=inv_tax_rate,
            discount_amount=discount_amount or 0.0,
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
        currency: Optional[str] = None,
    ) -> list[Invoice]:
        client_id = None
        if client:
            c = self.get_client(client)
            if c:
                client_id = c.id
        return self.store.list_invoices(status=status, client_id=client_id, currency=currency)

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

    def apply_discount(self, invoice_id: str, discount_amount: float) -> Invoice:
        """Apply a flat discount to an invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status == InvoiceStatus.PAID:
            raise ValueError("Cannot apply discount to a paid invoice.")
        invoice.discount_amount = round(discount_amount, 2)
        invoice.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_invoice(invoice)

    # --- Recurring invoice operations ---

    def create_recurring(
        self,
        client_identifier: str,
        line_items: list[dict],
        frequency: str = "monthly",
        due_days: int = 30,
        notes: Optional[str] = None,
        currency: Optional[str] = None,
        tax_rate: Optional[float] = None,
        discount_amount: Optional[float] = None,
    ) -> RecurringInvoice:
        """Create a recurring invoice template."""
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        inv_currency = (currency or client.currency).upper()
        inv_tax_rate = tax_rate if tax_rate is not None else 0.0

        items = []
        for item_data in line_items:
            item_tax = item_data.get("tax_rate", None)
            effective_tax = item_tax if item_tax is not None else inv_tax_rate
            items.append(LineItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1.0),
                unit_price=item_data["unit_price"],
                tax_rate=effective_tax,
            ))

        try:
            freq = RecurrenceFrequency(frequency.lower())
        except ValueError:
            raise ValueError(f"Invalid frequency: {frequency}. Use: weekly, biweekly, monthly, quarterly, yearly")

        recurring = RecurringInvoice(
            client_id=client.id,
            client_name=client.name,
            line_items=items,
            frequency=freq,
            currency=inv_currency,
            tax_rate=inv_tax_rate,
            discount_amount=discount_amount or 0.0,
            due_days=due_days,
            notes=notes,
            next_date=date.today(),
        )

        return self.store.save_recurring(recurring)

    def list_recurring(self, active_only: bool = False) -> list[RecurringInvoice]:
        return self.store.list_recurring(active_only=active_only)

    def get_recurring(self, recurring_id: str) -> Optional[RecurringInvoice]:
        return self.store.get_recurring(recurring_id)

    def pause_recurring(self, recurring_id: str) -> RecurringInvoice:
        """Pause a recurring invoice."""
        rec = self.store.get_recurring(recurring_id)
        if not rec:
            raise ValueError(f"Recurring invoice '{recurring_id}' not found.")
        rec.active = False
        rec.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_recurring(rec)

    def resume_recurring(self, recurring_id: str) -> RecurringInvoice:
        """Resume a paused recurring invoice."""
        rec = self.store.get_recurring(recurring_id)
        if not rec:
            raise ValueError(f"Recurring invoice '{recurring_id}' not found.")
        rec.active = True
        rec.next_date = date.today()
        rec.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_recurring(rec)

    def remove_recurring(self, recurring_id: str) -> bool:
        return self.store.delete_recurring(recurring_id)

    def generate_from_recurring(self, recurring_id: str) -> Invoice:
        """Generate an invoice from a recurring template."""
        rec = self.store.get_recurring(recurring_id)
        if not rec:
            raise ValueError(f"Recurring invoice '{recurring_id}' not found.")
        if not rec.active:
            raise ValueError(f"Recurring invoice '{recurring_id}' is paused. Resume it first.")
        invoice_id = self.store.get_next_invoice_number()
        invoice = rec.generate_invoice(invoice_id)
        self.store.save_recurring(rec)
        return self.store.save_invoice(invoice)

    def process_due_recurring(self) -> list[Invoice]:
        """Generate invoices for all recurring templates that are due."""
        generated = []
        for rec in self.store.list_recurring(active_only=True):
            if rec.next_date and rec.next_date <= date.today():
                invoice_id = self.store.get_next_invoice_number()
                invoice = rec.generate_invoice(invoice_id)
                self.store.save_recurring(rec)
                self.store.save_invoice(invoice)
                generated.append(invoice)
        return generated

    # --- Earnings ---

    def earnings_summary(self, currency: Optional[str] = None) -> EarningsSummary:
        invoices = self.store.list_invoices()
        if currency:
            invoices = [inv for inv in invoices if inv.currency == currency.upper()]
        summary_currency = currency.upper() if currency else "USD"
        summary = EarningsSummary(invoice_count=len(invoices), currency=summary_currency)
        for inv in invoices:
            subtotal = inv.subtotal
            summary.total_invoiced += subtotal
            summary.total_tax += inv.total_tax
            summary.total_discounts += inv.discount_amount
            if inv.status == InvoiceStatus.PAID:
                summary.total_paid += inv.total  # Use grand total for paid
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
        summary.total_tax = round(summary.total_tax, 2)
        summary.total_discounts = round(summary.total_discounts, 2)
        return summary
