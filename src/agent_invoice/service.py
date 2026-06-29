"""Business logic / service layer for Agent Invoice."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import (
    CURRENCIES,
    BUILTIN_TEMPLATES,
    Client,
    DunningAction,
    DunningConfig,
    DunningLevel,
    EarningsSummary,
    Invoice,
    InvoiceStatus,
    InvoiceTemplate,
    LineItem,
    NumberingConfig,
    Payment,
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

    def update_client(
        self,
        identifier: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> Client:
        """Update a client's details."""
        client = self.get_client(identifier)
        if not client:
            raise ValueError(f"Client '{identifier}' not found.")
        if name is not None:
            # Check name uniqueness (excluding self)
            existing = self.store.find_client_by_name(name)
            if existing and existing.id != client.id:
                raise ValueError(f"Client name '{name}' already in use by {existing.id}.")
            client.name = name
        if email is not None:
            client.email = email
        if address is not None:
            client.address = address
        if currency is not None:
            if currency.upper() not in CURRENCIES:
                raise ValueError(f"Unsupported currency: {currency}. Supported: {', '.join(sorted(CURRENCIES.keys()))}")
            client.currency = currency.upper()
        return self.store.save_client(client)

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

    def add_line_item(self, invoice_id: str, item_data: dict) -> Invoice:
        """Add a line item to a draft invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status not in (InvoiceStatus.DRAFT,):
            raise ValueError(f"Cannot modify items on a {invoice.status.value} invoice. Only DRAFT invoices can be edited.")
        item_tax = item_data.get("tax_rate", None)
        effective_tax = item_tax if item_tax is not None else invoice.tax_rate
        item = LineItem(
            description=item_data["description"],
            quantity=item_data.get("quantity", 1.0),
            unit_price=item_data["unit_price"],
            tax_rate=effective_tax,
        )
        invoice.line_items.append(item)
        invoice.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_invoice(invoice)

    def remove_line_item(self, invoice_id: str, index: int) -> Invoice:
        """Remove a line item by index from a draft invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status not in (InvoiceStatus.DRAFT,):
            raise ValueError(f"Cannot modify items on a {invoice.status.value} invoice. Only DRAFT invoices can be edited.")
        if index < 0 or index >= len(invoice.line_items):
            raise ValueError(f"Invalid item index {index}. Invoice has {len(invoice.line_items)} items.")
        invoice.line_items.pop(index)
        invoice.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_invoice(invoice)

    # --- Payment operations ---

    def record_payment(
        self,
        invoice_id: str,
        amount: float,
        method: Optional[str] = None,
        reference: Optional[str] = None,
        notes: Optional[str] = None,
        payment_date: Optional[date] = None,
    ) -> Invoice:
        """Record a payment against an invoice.

        Args:
            invoice_id: The invoice to apply the payment to.
            amount: Payment amount.
            method: Payment method (e.g. "bank_transfer", "credit_card", "crypto", "cash").
            reference: External payment reference / transaction ID.
            notes: Payment notes.
            payment_date: Date of payment (defaults to today).

        Returns:
            The updated invoice.
        """
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status == InvoiceStatus.CANCELLED:
            raise ValueError("Cannot record payment against a cancelled invoice.")
        if invoice.status == InvoiceStatus.PAID:
            raise ValueError(f"Invoice '{invoice_id}' is already fully paid.")

        amount = round(amount, 2)
        if amount <= 0:
            raise ValueError("Payment amount must be positive.")

        # Check for overpayment
        remaining = invoice.amount_remaining
        if amount > remaining + 0.01:  # Small tolerance for rounding
            raise ValueError(
                f"Payment amount ({amount}) exceeds remaining balance ({remaining}). "
                f"Use amount {remaining} or less."
            )

        payment = Payment(
            amount=amount,
            method=method,
            reference=reference,
            notes=notes,
            payment_date=payment_date or date.today(),
        )
        invoice.add_payment(payment)
        return self.store.save_invoice(invoice)

    def list_payments(self, invoice_id: str) -> list[Payment]:
        """List all payments for an invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        return invoice.payments

    def remove_payment(self, invoice_id: str, payment_id: str) -> Invoice:
        """Remove a payment from an invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if not invoice.remove_payment(payment_id):
            raise ValueError(f"Payment '{payment_id}' not found on invoice '{invoice_id}'.")
        return self.store.save_invoice(invoice)

    # --- PDF Export ---

    def export_pdf(
        self,
        invoice_id: str,
        output_path: Optional[str] = None,
        company_name: Optional[str] = None,
        company_address: Optional[str] = None,
        company_email: Optional[str] = None,
    ) -> str:
        """Export an invoice as a PDF file.

        Args:
            invoice_id: The invoice ID to export.
            output_path: Path to save the PDF. Auto-generated if None.
            company_name: Your company name for the header.
            company_address: Your company address.
            company_email: Your company email.

        Returns:
            The path to the generated PDF file.
        """
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")

        from .pdf import generate_pdf
        return generate_pdf(
            invoice=invoice,
            output_path=output_path,
            company_name=company_name,
            company_address=company_address,
            company_email=company_email,
        )

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
            summary.total_payments += inv.amount_paid
            if inv.status == InvoiceStatus.PAID:
                summary.total_paid += inv.total  # Use grand total for paid
                summary.paid_count += 1
            elif inv.status == InvoiceStatus.PARTIALLY_PAID:
                summary.total_paid += inv.amount_paid
                summary.partially_paid_count += 1
                summary.total_pending += inv.amount_remaining
                summary.pending_count += 1
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
        summary.total_payments = round(summary.total_payments, 2)
        return summary

    # --- Invoice Template operations ---

    def list_templates(self, category: Optional[str] = None) -> list[InvoiceTemplate]:
        """List all templates (built-in + custom)."""
        # Load built-in templates
        built_in = []
        for tpl_data in BUILTIN_TEMPLATES:
            items = [LineItem(**li) for li in tpl_data["line_items"]]
            tpl = InvoiceTemplate(
                id=tpl_data["id"],
                name=tpl_data["name"],
                description=tpl_data.get("description"),
                line_items=items,
                tax_rate=tpl_data.get("tax_rate", 0.0),
                discount_amount=tpl_data.get("discount_amount", 0.0),
                due_days=tpl_data.get("due_days", 30),
                currency=tpl_data.get("currency", "USD"),
                notes=tpl_data.get("notes"),
                category=tpl_data.get("category"),
            )
            if category and tpl.category != category:
                continue
            built_in.append(tpl)

        # Load custom templates
        custom = self.store.list_templates(category=category)

        return built_in + custom

    def get_template(self, template_id: str) -> Optional[InvoiceTemplate]:
        """Get a template by ID (checks built-in first, then custom)."""
        # Check built-in
        for tpl_data in BUILTIN_TEMPLATES:
            if tpl_data["id"] == template_id:
                items = [LineItem(**li) for li in tpl_data["line_items"]]
                return InvoiceTemplate(
                    id=tpl_data["id"],
                    name=tpl_data["name"],
                    description=tpl_data.get("description"),
                    line_items=items,
                    tax_rate=tpl_data.get("tax_rate", 0.0),
                    discount_amount=tpl_data.get("discount_amount", 0.0),
                    due_days=tpl_data.get("due_days", 30),
                    currency=tpl_data.get("currency", "USD"),
                    notes=tpl_data.get("notes"),
                    category=tpl_data.get("category"),
                )
        # Check custom
        return self.store.get_template(template_id)

    def create_template(
        self,
        name: str,
        line_items: list[dict],
        description: Optional[str] = None,
        tax_rate: Optional[float] = None,
        discount_amount: Optional[float] = None,
        due_days: int = 30,
        currency: str = "USD",
        notes: Optional[str] = None,
        category: Optional[str] = None,
    ) -> InvoiceTemplate:
        """Create a custom invoice template."""
        if currency.upper() not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}. Supported: {', '.join(sorted(CURRENCIES.keys()))}")

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

        template = InvoiceTemplate(
            name=name,
            description=description,
            line_items=items,
            tax_rate=inv_tax_rate,
            discount_amount=discount_amount or 0.0,
            due_days=due_days,
            currency=currency.upper(),
            notes=notes,
            category=category,
        )
        return self.store.save_template(template)

    def remove_template(self, template_id: str) -> bool:
        """Remove a custom template (cannot remove built-in)."""
        if any(t["id"] == template_id for t in BUILTIN_TEMPLATES):
            raise ValueError("Cannot remove built-in templates.")
        return self.store.delete_template(template_id)

    def create_invoice_from_template(
        self,
        template_id: str,
        client_identifier: str,
        overrides: Optional[dict] = None,
    ) -> Invoice:
        """Create an invoice from a template, applying optional overrides."""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template '{template_id}' not found.")

        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        overrides = overrides or {}

        # Determine currency: override > template > client
        inv_currency = (overrides.get("currency") or template.currency or client.currency).upper()
        if inv_currency not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {inv_currency}.")

        # Build line items from template, allowing overrides
        items = [item.model_copy() for item in template.line_items]

        invoice_id = self.store.get_next_invoice_number()
        invoice = Invoice(
            id=invoice_id,
            client_id=client.id,
            client_name=client.name,
            line_items=items,
            status=InvoiceStatus.DRAFT,
            currency=inv_currency,
            tax_rate=template.tax_rate,
            discount_amount=overrides.get("discount_amount", template.discount_amount),
            notes=overrides.get("notes", template.notes),
        )
        due_days = overrides.get("due_days", template.due_days)
        if due_days is not None:
            invoice.set_due_date(due_days)

        return self.store.save_invoice(invoice)

    # --- Dunning operations ---

    def get_dunning_config(self) -> DunningConfig:
        """Get the current dunning configuration."""
        return self.store.get_dunning_config()

    def update_dunning_config(
        self,
        first_reminder_days: Optional[int] = None,
        second_reminder_days: Optional[int] = None,
        final_notice_days: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> DunningConfig:
        """Update the dunning configuration."""
        config = self.store.get_dunning_config()
        if first_reminder_days is not None:
            config.first_reminder_days = first_reminder_days
        if second_reminder_days is not None:
            config.second_reminder_days = second_reminder_days
        if final_notice_days is not None:
            config.final_notice_days = final_notice_days
        if enabled is not None:
            config.enabled = enabled

        # Validate
        if config.first_reminder_days >= config.second_reminder_days:
            raise ValueError("first_reminder_days must be less than second_reminder_days")
        if config.second_reminder_days >= config.final_notice_days:
            raise ValueError("second_reminder_days must be less than final_notice_days")

        return self.store.save_dunning_config(config)

    def send_dunning_reminder(self, invoice_id: str, level: Optional[str] = None, message: Optional[str] = None) -> DunningAction:
        """Send a dunning reminder for an overdue invoice."""
        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if not invoice.is_overdue:
            raise ValueError(f"Invoice '{invoice_id}' is not overdue.")

        assert invoice.due_date is not None  # guaranteed by is_overdue check
        days_overdue = (date.today() - invoice.due_date).days
        config = self.store.get_dunning_config()

        # Determine level
        if level:
            try:
                dunning_level = DunningLevel(level)
            except ValueError:
                raise ValueError(f"Invalid dunning level: {level}. Use: first_reminder, second_reminder, final_notice")
        else:
            dunning_level = config.get_level_for_days_overdue(days_overdue)
            if not dunning_level:
                raise ValueError(
                    f"Invoice is {days_overdue} days overdue, which doesn't meet the minimum "
                    f"dunning threshold of {config.first_reminder_days} days."
                )

        # Generate message
        if not message:
            message = config.get_message_for_level(
                level=dunning_level,
                invoice_id=invoice_id,
                days_overdue=days_overdue,
                amount=invoice.amount_remaining,
                currency=invoice.currency,
            )

        action = DunningAction(
            invoice_id=invoice_id,
            level=dunning_level,
            message=message,
            days_overdue=days_overdue,
        )
        return self.store.save_dunning_action(action)

    def process_overdue_dunning(self) -> list[DunningAction]:
        """Check all overdue invoices and send appropriate dunning reminders.
        Only sends a reminder if one hasn't already been sent at this level for the invoice."""
        config = self.store.get_dunning_config()
        if not config.enabled:
            return []

        actions = []
        overdue_invoices = self.store.list_invoices(status=InvoiceStatus.OVERDUE)
        # Also include partially_paid invoices that are overdue
        for inv in self.store.list_invoices(status=InvoiceStatus.PARTIALLY_PAID):
            if inv.is_overdue and inv not in overdue_invoices:
                overdue_invoices.append(inv)

        for inv in overdue_invoices:
            if not inv.due_date:
                continue
            days_overdue = (date.today() - inv.due_date).days
            level = config.get_level_for_days_overdue(days_overdue)
            if not level:
                continue

            # Check if we already sent this level for this invoice
            existing_actions = self.store.list_dunning_actions(invoice_id=inv.id)
            already_sent_at_level = any(a.level == level for a in existing_actions)

            if not already_sent_at_level:
                msg = config.get_message_for_level(
                    level=level,
                    invoice_id=inv.id,
                    days_overdue=days_overdue,
                    amount=inv.amount_remaining,
                    currency=inv.currency,
                )
                action = DunningAction(
                    invoice_id=inv.id,
                    level=level,
                    message=msg,
                    days_overdue=days_overdue,
                )
                self.store.save_dunning_action(action)
                actions.append(action)

        return actions

    def list_dunning_actions(self, invoice_id: Optional[str] = None) -> list[DunningAction]:
        """List dunning actions, optionally filtered by invoice."""
        return self.store.list_dunning_actions(invoice_id=invoice_id)

    def remove_dunning_action(self, action_id: str) -> bool:
        """Remove a dunning action record."""
        return self.store.delete_dunning_action(action_id)
