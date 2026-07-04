"""Business logic / service layer for Agent Invoice."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import (
    ARAgingBucket,
    ARAgingReport,
    BUILTIN_TEMPLATES,
    CURRENCIES,
    Client,
    ClientARAging,
    ClientProfitability,
    ClientStatement,
    CreditNote,
    CreditNoteStatus,
    DunningAction,
    DunningConfig,
    DunningLevel,
    EarningsSummary,
    Estimate,
    EstimateStatus,
    Expense,
    ExpenseCategory,
    Invoice,
    InvoiceStatus,
    InvoiceTemplate,
    LineItem,
    MonthlyRevenue,
    NumberingConfig,
    Payment,
    ProfitAnalysis,
    RecurrenceFrequency,
    RecurringInvoice,
    RevenueAnalytics,
    TaxLineItemSummary,
    TaxSummaryReport,
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

    def create_client(
        self,
        name: str,
        email: Optional[str] = None,
        address: Optional[str] = None,
        currency: str = "USD",
    ) -> Client:
        """Alias for add_client — create and save a new client."""
        return self.add_client(name=name, email=email, address=address, currency=currency)

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
        status: Optional[InvoiceStatus | str] = None,
        client: Optional[str] = None,
        currency: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        search: Optional[str] = None,
    ) -> list[Invoice]:
        """List invoices with optional filtering by status, client, currency, date range, amount range, and text search."""
        # Normalize status to enum if a string was passed
        if status is not None and isinstance(status, str):
            try:
                status = InvoiceStatus(status.lower())
            except ValueError:
                raise ValueError(f"Invalid status: {status}. Use: {', '.join(s.value for s in InvoiceStatus)}")
        client_id = None
        if client:
            c = self.get_client(client)
            if c:
                client_id = c.id
        invoices = self.store.list_invoices(status=status, client_id=client_id, currency=currency)

        # Date range filtering
        if date_from:
            invoices = [inv for inv in invoices if inv.issue_date >= date_from]
        if date_to:
            invoices = [inv for inv in invoices if inv.issue_date <= date_to]

        # Amount range filtering (on total)
        if min_amount is not None:
            invoices = [inv for inv in invoices if inv.total >= min_amount]
        if max_amount is not None:
            invoices = [inv for inv in invoices if inv.total <= max_amount]

        # Text search (case-insensitive across id, client_name, notes, line item descriptions)
        if search:
            search_lower = search.lower()
            matched = []
            for inv in invoices:
                # Check ID, client name, notes
                haystack_parts = [inv.id.lower(), (inv.client_name or "").lower(), (inv.notes or "").lower()]
                # Check line item descriptions
                for item in inv.line_items:
                    haystack_parts.append(item.description.lower())
                if any(search_lower in part for part in haystack_parts):
                    matched.append(inv)
            invoices = matched

        return invoices

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

    def add_payment(
        self,
        invoice_id: str,
        amount: float,
        method: Optional[str] = None,
        reference: Optional[str] = None,
        notes: Optional[str] = None,
        payment_date: Optional[date] = None,
    ) -> Invoice:
        """Alias for record_payment — add a payment to an invoice."""
        return self.record_payment(
            invoice_id=invoice_id,
            amount=amount,
            method=method,
            reference=reference,
            notes=notes,
            payment_date=payment_date,
        )

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

    # --- Credit note operations ---

    def create_credit_note(
        self,
        client_identifier: str,
        amount: float,
        reason: Optional[str] = None,
        invoice_id: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> CreditNote:
        """Create a credit note for a client.

        Args:
            client_identifier: Client ID or name.
            amount: Credit amount (must be positive).
            reason: Reason for the credit (e.g. "overpayment", "refund", "billing error").
            invoice_id: Optional original invoice this credit relates to.
            currency: Currency override (defaults to client's currency).

        Returns:
            The created CreditNote.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        amount = round(amount, 2)
        if amount <= 0:
            raise ValueError("Credit note amount must be positive.")

        inv_currency = (currency or client.currency).upper()
        if inv_currency not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {inv_currency}.")

        # If linking to an invoice, verify it exists and belongs to this client
        if invoice_id:
            inv = self.store.get_invoice(invoice_id)
            if not inv:
                raise ValueError(f"Invoice '{invoice_id}' not found.")
            if inv.client_id != client.id:
                raise ValueError(f"Invoice '{invoice_id}' does not belong to client '{client.name}'.")

        credit = CreditNote(
            client_id=client.id,
            client_name=client.name,
            amount=amount,
            currency=inv_currency,
            reason=reason,
            invoice_id=invoice_id,
        )
        return self.store.save_credit_note(credit)

    def get_credit_note(self, credit_id: str) -> Optional[CreditNote]:
        """Get a credit note by ID."""
        return self.store.get_credit_note(credit_id)

    def list_credit_notes(
        self,
        client: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[CreditNote]:
        """List credit notes, optionally filtered by client and status."""
        client_id = None
        if client:
            c = self.get_client(client)
            if c:
                client_id = c.id
        status_enum = None
        if status:
            try:
                status_enum = CreditNoteStatus(status.lower())
            except ValueError:
                raise ValueError(f"Invalid credit note status: {status}. Use: open, applied, void.")
        return self.store.list_credit_notes(client_id=client_id, status=status_enum)

    def apply_credit_note(
        self,
        credit_id: str,
        invoice_id: str,
        amount: Optional[float] = None,
    ) -> tuple[CreditNote, Invoice]:
        """Apply a credit note to an invoice as a payment.

        Args:
            credit_id: The credit note to apply.
            invoice_id: The invoice to apply it to.
            amount: Amount to apply (defaults to remaining credit or remaining balance, whichever is less).

        Returns:
            Tuple of (updated credit note, updated invoice).
        """
        credit = self.store.get_credit_note(credit_id)
        if not credit:
            raise ValueError(f"Credit note '{credit_id}' not found.")
        if credit.status == CreditNoteStatus.VOID:
            raise ValueError(f"Credit note '{credit_id}' is voided and cannot be applied.")
        if credit.remaining_amount <= 0:
            raise ValueError(f"Credit note '{credit_id}' has no remaining balance.")

        invoice = self.store.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' not found.")
        if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
            raise ValueError(f"Invoice '{invoice_id}' has status {invoice.status.value} — cannot apply credit.")
        if invoice.currency != credit.currency:
            raise ValueError(
                f"Currency mismatch: credit note is in {credit.currency}, invoice is in {invoice.currency}."
            )

        # Determine amount
        if amount is None:
            amount = min(credit.remaining_amount, invoice.amount_remaining)
        else:
            amount = round(amount, 2)

        if amount <= 0:
            raise ValueError("Application amount must be positive.")

        # Apply credit to the credit note record
        credit.apply(invoice_id=invoice_id, amount=amount)

        # Create a payment record for the invoice
        payment = Payment(
            amount=amount,
            method="credit_note",
            reference=credit_id,
            notes=f"Applied from credit note {credit_id}",
        )
        invoice.add_payment(payment)

        self.store.save_credit_note(credit)
        self.store.save_invoice(invoice)
        return credit, invoice

    def void_credit_note(self, credit_id: str) -> CreditNote:
        """Void a credit note. Only open credit notes with no applications can be voided."""
        credit = self.store.get_credit_note(credit_id)
        if not credit:
            raise ValueError(f"Credit note '{credit_id}' not found.")
        if credit.status != CreditNoteStatus.OPEN:
            raise ValueError(f"Cannot void credit note in '{credit.status.value}' status. Only open credit notes can be voided.")
        if credit.applied_amount > 0:
            raise ValueError(f"Cannot void credit note with applied amount of {credit.applied_amount}.")
        credit.status = CreditNoteStatus.VOID
        credit.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_credit_note(credit)

    def remove_credit_note(self, credit_id: str) -> bool:
        """Remove a credit note. Only voided credit notes can be removed."""
        credit = self.store.get_credit_note(credit_id)
        if not credit:
            return False
        if credit.status == CreditNoteStatus.OPEN and credit.applied_amount > 0:
            raise ValueError("Cannot remove a credit note that has been partially applied. Void it first.")
        if credit.status == CreditNoteStatus.APPLIED:
            raise ValueError("Cannot remove an applied credit note. Void it first.")
        return self.store.delete_credit_note(credit_id)

    # --- Client statement ---

    def generate_client_statement(
        self,
        client_identifier: str,
        period_start: date,
        period_end: date,
        currency: Optional[str] = None,
    ) -> ClientStatement:
        """Generate a financial statement for a client over a period.

        Includes all invoices, payments, and credit notes within the date range,
        with opening and closing balances.

        Args:
            client_identifier: Client ID or name.
            period_start: Start of the statement period.
            period_end: End of the statement period.
            currency: Filter by currency (defaults to client's currency).

        Returns:
            A ClientStatement with all activity and balances.
        """
        if period_start > period_end:
            raise ValueError("period_start must be before or equal to period_end.")

        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        stmt_currency = (currency or client.currency).upper()

        # Get all invoices for this client in this currency
        all_invoices = self.store.list_invoices(client_id=client.id, currency=stmt_currency)
        # Get all credit notes for this client in this currency
        all_credits = self.store.list_credit_notes(client_id=client.id)

        # --- Calculate opening balance ---
        # Opening balance = all invoiced before period_start - all payments before period_start - all credits before period_start
        opening_invoiced = 0.0
        opening_paid = 0.0
        opening_credits = 0.0

        for inv in all_invoices:
            if inv.issue_date < period_start:
                opening_invoiced += inv.total
                for p in inv.payments:
                    if p.payment_date < period_start:
                        opening_paid += p.amount

        for credit in all_credits:
            if credit.currency != stmt_currency:
                continue
            if credit.issue_date < period_start:
                opening_credits += credit.applied_amount

        opening_balance = round(opening_invoiced - opening_paid - opening_credits, 2)

        # --- Collect period activity ---
        period_invoices = []
        period_payments = []
        period_credits = []
        total_invoiced = 0.0
        total_paid = 0.0
        total_credits = 0.0

        for inv in all_invoices:
            if period_start <= inv.issue_date <= period_end:
                period_invoices.append({
                    "id": inv.id,
                    "issue_date": str(inv.issue_date),
                    "total": inv.total,
                    "status": inv.status.value,
                    "due_date": str(inv.due_date) if inv.due_date else None,
                })
                total_invoiced += inv.total
            # Collect payments within the period (may be on invoices from any date)
            for p in inv.payments:
                if period_start <= p.payment_date <= period_end:
                    period_payments.append({
                        "id": p.id,
                        "invoice_id": inv.id,
                        "amount": p.amount,
                        "date": str(p.payment_date),
                        "method": p.method,
                    })
                    total_paid += p.amount

        for credit in all_credits:
            if credit.currency != stmt_currency:
                continue
            if period_start <= credit.issue_date <= period_end:
                period_credits.append({
                    "id": credit.id,
                    "amount": credit.amount,
                    "reason": credit.reason,
                    "status": credit.status.value,
                    "date": str(credit.issue_date),
                    "applied_amount": credit.applied_amount,
                })
                total_credits += credit.amount

        # --- Calculate closing balance ---
        closing_balance = round(
            opening_balance + total_invoiced - total_paid - total_credits, 2
        )

        statement = ClientStatement(
            client_id=client.id,
            client_name=client.name,
            currency=stmt_currency,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_balance,
            invoices=period_invoices,
            payments=period_payments,
            credit_notes=period_credits,
            total_invoiced=round(total_invoiced, 2),
            total_paid=round(total_paid, 2),
            total_credits=round(total_credits, 2),
            closing_balance=closing_balance,
        )
        return statement

    # -----------------------------------------------------------------------
    # A/R Aging Report
    # -----------------------------------------------------------------------

    def generate_ar_aging_report(
        self,
        currency: Optional[str] = None,
        bucket_ranges: Optional[list[tuple[int, Optional[int]]]] = None,
    ) -> ARAgingReport:
        """Generate an Accounts Receivable aging report.

        Groups outstanding invoice balances into aging buckets
        (0-30, 31-60, 61-90, 90+ days by default).

        Args:
            currency: Filter by currency (None = all currencies).
            bucket_ranges: Custom bucket ranges as (low, high) tuples.
                high=None means open-ended. Default: 0-30, 31-60, 61-90, 90+.

        Returns:
            ARAgingReport with per-client and per-bucket breakdowns.
        """
        if bucket_ranges is None:
            bucket_ranges = [(0, 30), (31, 60), (61, 90), (91, None)]

        today = date.today()

        # Gather all invoices with outstanding balances
        invoices = self.store.list_invoices(currency=currency)
        # Include partially_paid and overdue invoices that have remaining balance
        outstanding = [inv for inv in invoices if inv.amount_remaining > 0.01]

        # Group by client
        client_map: dict[str, list[Invoice]] = {}
        for inv in outstanding:
            client_map.setdefault(inv.client_id, []).append(inv)

        # Build per-client aging
        client_agings: list[ClientARAging] = []
        grand_bucket_totals: dict[str, ARAgingBucket] = {}

        for client_id, invs in sorted(client_map.items()):
            # Get client name
            client_name = None
            client_obj = self.store.get_client(client_id)
            if not client_obj:
                # Try finding by name in case client_id is actually a name
                client_obj = self.store.find_client_by_name(client_id)
            if client_obj:
                client_name = client_obj.name

            # Initialize buckets for this client
            client_buckets: dict[str, ARAgingBucket] = {}
            for low, high in bucket_ranges:
                label = f"{low}-{high}" if high is not None else f"{low}+"
                client_buckets[label] = ARAgingBucket(label=label, days_low=low, days_high=high)
                grand_bucket_totals.setdefault(label, ARAgingBucket(label=label, days_low=low, days_high=high))

            client_total = 0.0
            invoice_details = []

            for inv in invs:
                # Calculate days past due
                if inv.due_date:
                    days_overdue = (today - inv.due_date).days
                else:
                    # No due date — age from issue date
                    days_overdue = (today - inv.issue_date).days

                # Only count as overdue if positive
                days_overdue = max(0, days_overdue)

                remaining = inv.amount_remaining
                client_total += remaining

                # Find which bucket this falls into
                bucket_label = None
                for low, high in bucket_ranges:
                    if high is None:
                        if days_overdue >= low:
                            bucket_label = f"{low}-{high}" if high is not None else f"{low}+"
                            break
                    elif low <= days_overdue <= high:
                        bucket_label = f"{low}-{high}"
                        break

                if bucket_label and bucket_label in client_buckets:
                    client_buckets[bucket_label].invoice_count += 1
                    client_buckets[bucket_label].total_outstanding += remaining
                    grand_bucket_totals[bucket_label].invoice_count += 1
                    grand_bucket_totals[bucket_label].total_outstanding += remaining

                invoice_details.append({
                    "id": inv.id,
                    "total": inv.total,
                    "amount_remaining": remaining,
                    "days_overdue": days_overdue,
                    "bucket": bucket_label,
                    "due_date": str(inv.due_date) if inv.due_date else None,
                    "issue_date": str(inv.issue_date),
                    "status": inv.status.value,
                })

            client_agings.append(ClientARAging(
                client_id=client_id,
                client_name=client_name,
                total_outstanding=round(client_total, 2),
                buckets=list(client_buckets.values()),
                invoice_details=invoice_details,
            ))

        # Sort clients by total_outstanding descending
        client_agings.sort(key=lambda c: c.total_outstanding, reverse=True)

        grand_total = sum(c.total_outstanding for c in client_agings)

        return ARAgingReport(
            as_of_date=today,
            currency=currency,
            total_outstanding=round(grand_total, 2),
            client_count=len(client_agings),
            bucket_totals=list(grand_bucket_totals.values()),
            clients=client_agings,
        )

    # -----------------------------------------------------------------------
    # Revenue Analytics
    # -----------------------------------------------------------------------

    def get_revenue_analytics(
        self,
        period_start: date,
        period_end: date,
        currency: Optional[str] = None,
    ) -> RevenueAnalytics:
        """Generate revenue analytics for a period.

        Includes monthly breakdown, collection rate, average days to pay,
        and top clients.

        Args:
            period_start: Start of the analytics period.
            period_end: End of the analytics period.
            currency: Filter by currency (default: USD for reporting).

        Returns:
            RevenueAnalytics with monthly trends and metrics.
        """
        if period_start > period_end:
            raise ValueError("period_start must be before or equal to period_end.")

        analytics_currency = currency.upper() if currency else "USD"

        invoices = self.store.list_invoices(currency=currency)

        # Filter invoices to those issued within the period
        period_invoices = [inv for inv in invoices if period_start <= inv.issue_date <= period_end]

        # Build monthly breakdown
        months_data: dict[str, dict] = {}
        for inv in period_invoices:
            month_key = inv.issue_date.strftime("%Y-%m")
            if month_key not in months_data:
                months_data[month_key] = {
                    "invoiced": 0.0,
                    "collected": 0.0,
                    "outstanding": 0.0,
                    "invoice_count": 0,
                    "paid_invoice_count": 0,
                }
            months_data[month_key]["invoiced"] += inv.total
            months_data[month_key]["invoice_count"] += 1
            months_data[month_key]["collected"] += inv.amount_paid
            months_data[month_key]["outstanding"] += inv.amount_remaining
            if inv.status == InvoiceStatus.PAID:
                months_data[month_key]["paid_invoice_count"] += 1

        # Collect payments received during the period (for collection timing)
        # and add them to the respective months
        for inv in invoices:
            for p in inv.payments:
                if period_start <= p.payment_date <= period_end:
                    month_key = p.payment_date.strftime("%Y-%m")
                    if month_key not in months_data:
                        months_data[month_key] = {
                            "invoiced": 0.0,
                            "collected": 0.0,
                            "outstanding": 0.0,
                            "invoice_count": 0,
                            "paid_invoice_count": 0,
                        }
                    months_data[month_key]["collected"] += p.amount

        # Build MonthlyRevenue objects
        months = []
        for month_key in sorted(months_data.keys()):
            data = months_data[month_key]
            avg_inv_val = round(data["invoiced"] / data["invoice_count"], 2) if data["invoice_count"] > 0 else 0.0
            months.append(MonthlyRevenue(
                period=month_key,
                invoiced=round(data["invoiced"], 2),
                collected=round(data["collected"], 2),
                outstanding=round(data["outstanding"], 2),
                invoice_count=data["invoice_count"],
                paid_invoice_count=data["paid_invoice_count"],
                avg_invoice_value=avg_inv_val,
            ))

        total_invoiced = sum(m.invoiced for m in months)
        total_collected = sum(m.collected for m in months)

        # Calculate average days to pay (from issue to paid_date)
        days_to_pay = []
        for inv in invoices:
            if inv.status == InvoiceStatus.PAID and inv.paid_date and period_start <= inv.paid_date <= period_end:
                days = (inv.paid_date - inv.issue_date).days
                if days >= 0:
                    days_to_pay.append(days)

        avg_days_to_pay = round(sum(days_to_pay) / len(days_to_pay), 1) if days_to_pay else 0.0
        fastest = min(days_to_pay) if days_to_pay else None
        slowest = max(days_to_pay) if days_to_pay else None

        collection_rate = round(total_collected / total_invoiced * 100, 1) if total_invoiced > 0 else 0.0

        # Top clients by total invoiced
        client_totals: dict[str, dict] = {}
        for inv in period_invoices:
            cid = inv.client_id
            if cid not in client_totals:
                client_totals[cid] = {
                    "client_id": cid,
                    "client_name": inv.client_name or cid,
                    "total_invoiced": 0.0,
                    "total_paid": 0.0,
                }
            client_totals[cid]["total_invoiced"] += inv.total
            client_totals[cid]["total_paid"] += inv.amount_paid

        top_clients = sorted(client_totals.values(), key=lambda x: x["total_invoiced"], reverse=True)[:10]
        for tc in top_clients:
            tc["total_invoiced"] = round(tc["total_invoiced"], 2)
            tc["total_paid"] = round(tc["total_paid"], 2)

        return RevenueAnalytics(
            currency=analytics_currency,
            period_start=str(period_start),
            period_end=str(period_end),
            months=months,
            total_invoiced=round(total_invoiced, 2),
            total_collected=round(total_collected, 2),
            avg_days_to_pay=avg_days_to_pay,
            collection_rate=collection_rate,
            fastest_payment_days=fastest,
            slowest_payment_days=slowest,
            top_clients=top_clients,
        )

    # -----------------------------------------------------------------------
    # Estimates / Quotes
    # -----------------------------------------------------------------------

    def create_estimate(
        self,
        client_identifier: str,
        line_items: list[dict],
        due_days: Optional[int] = 30,
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        currency: Optional[str] = None,
        tax_rate: Optional[float] = None,
        discount_amount: Optional[float] = None,
        expiry_days: Optional[int] = 30,
    ) -> Estimate:
        """Create a new estimate/quote for a client.

        Args:
            client_identifier: Client ID or name.
            line_items: List of dicts with keys: description, quantity, unit_price, tax_rate.
            due_days: Days until due date (for the eventual invoice).
            notes: Notes on the estimate.
            terms: Payment terms or scope description.
            currency: Override currency (uses client default if not specified).
            tax_rate: Estimate-level default tax rate.
            discount_amount: Flat discount.
            expiry_days: Days until the quote expires (default: 30).

        Returns:
            The created Estimate.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        est_currency = (currency or client.currency).upper()
        if est_currency not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {est_currency}.")

        est_tax_rate = tax_rate if tax_rate is not None else 0.0

        items = []
        for item_data in line_items:
            item_tax = item_data.get("tax_rate", None)
            effective_tax = item_tax if item_tax is not None else est_tax_rate
            items.append(LineItem(
                description=item_data["description"],
                quantity=item_data.get("quantity", 1.0),
                unit_price=item_data["unit_price"],
                tax_rate=effective_tax,
            ))

        estimate = Estimate(
            client_id=client.id,
            client_name=client.name,
            line_items=items,
            currency=est_currency,
            tax_rate=est_tax_rate,
            discount_amount=discount_amount or 0.0,
            notes=notes,
            terms=terms,
        )
        if expiry_days is not None:
            estimate.set_expiry(expiry_days)

        return self.store.save_estimate(estimate)

    def get_estimate(self, estimate_id: str) -> Optional[Estimate]:
        """Get an estimate by ID."""
        return self.store.get_estimate(estimate_id)

    def list_estimates(
        self,
        status: Optional[str] = None,
        client: Optional[str] = None,
    ) -> list[Estimate]:
        """List estimates with optional filters."""
        # Normalize status
        status_enum = None
        if status:
            try:
                status_enum = EstimateStatus(status.lower())
            except ValueError:
                raise ValueError(f"Invalid estimate status: {status}. Use: draft, sent, accepted, declined, expired, converted.")

        client_id = None
        if client:
            c = self.get_client(client)
            if c:
                client_id = c.id

        return self.store.list_estimates(
            status=status_enum.value if status_enum else None,
            client_id=client_id,
        )

    def send_estimate(self, estimate_id: str) -> Estimate:
        """Mark an estimate as sent."""
        est = self.store.get_estimate(estimate_id)
        if not est:
            raise ValueError(f"Estimate '{estimate_id}' not found.")
        est.mark_sent()
        return self.store.save_estimate(est)

    def accept_estimate(self, estimate_id: str) -> Estimate:
        """Mark an estimate as accepted by the client."""
        est = self.store.get_estimate(estimate_id)
        if not est:
            raise ValueError(f"Estimate '{estimate_id}' not found.")
        if est.status in (EstimateStatus.DECLINED, EstimateStatus.EXPIRED, EstimateStatus.CONVERTED):
            raise ValueError(f"Cannot accept estimate in '{est.status.value}' status.")
        est.mark_accepted()
        return self.store.save_estimate(est)

    def decline_estimate(self, estimate_id: str) -> Estimate:
        """Mark an estimate as declined by the client."""
        est = self.store.get_estimate(estimate_id)
        if not est:
            raise ValueError(f"Estimate '{estimate_id}' not found.")
        if est.status == EstimateStatus.CONVERTED:
            raise ValueError("Cannot decline an already-converted estimate.")
        est.mark_declined()
        return self.store.save_estimate(est)

    def convert_estimate_to_invoice(
        self,
        estimate_id: str,
        due_days: Optional[int] = 30,
    ) -> tuple[Estimate, Invoice]:
        """Convert an accepted (or sent) estimate into an invoice.

        Args:
            estimate_id: The estimate to convert.
            due_days: Days until due date for the new invoice.

        Returns:
            Tuple of (updated estimate, new invoice).
        """
        est = self.store.get_estimate(estimate_id)
        if not est:
            raise ValueError(f"Estimate '{estimate_id}' not found.")
        if est.status == EstimateStatus.CONVERTED:
            raise ValueError(f"Estimate '{estimate_id}' has already been converted to invoice '{est.converted_invoice_id}'.")
        if est.status == EstimateStatus.DECLINED:
            raise ValueError("Cannot convert a declined estimate.")
        if est.status == EstimateStatus.EXPIRED:
            raise ValueError("Cannot convert an expired estimate.")

        # Create the invoice from the estimate's line items
        line_item_dicts = []
        for item in est.line_items:
            d = {"description": item.description, "quantity": item.quantity, "unit_price": item.unit_price}
            if item.tax_rate > 0:
                d["tax_rate"] = item.tax_rate
            line_item_dicts.append(d)

        invoice_id = self.store.get_next_invoice_number()
        invoice = Invoice(
            id=invoice_id,
            client_id=est.client_id,
            client_name=est.client_name,
            line_items=[item.model_copy() for item in est.line_items],
            status=InvoiceStatus.DRAFT,
            currency=est.currency,
            tax_rate=est.tax_rate,
            discount_amount=est.discount_amount,
            notes=est.notes,
        )
        if due_days is not None:
            invoice.set_due_date(due_days)

        saved_invoice = self.store.save_invoice(invoice)

        # Update the estimate
        est.status = EstimateStatus.CONVERTED
        est.converted_invoice_id = saved_invoice.id
        est.updated_at = datetime.now(tz=timezone.utc)
        self.store.save_estimate(est)

        return est, saved_invoice

    def remove_estimate(self, estimate_id: str) -> bool:
        """Remove an estimate. Cannot remove converted estimates."""
        est = self.store.get_estimate(estimate_id)
        if not est:
            return False
        if est.status == EstimateStatus.CONVERTED:
            raise ValueError("Cannot remove a converted estimate.")
        return self.store.delete_estimate(estimate_id)

    def export_estimate_pdf(
        self,
        estimate_id: str,
        output_path: Optional[str] = None,
        company_name: Optional[str] = None,
        company_address: Optional[str] = None,
        company_email: Optional[str] = None,
    ) -> str:
        """Export an estimate/quote as a PDF file.

        Args:
            estimate_id: The estimate ID to export.
            output_path: Path to save the PDF. Auto-generated if None.
            company_name: Your company name for the header.
            company_address: Your company address.
            company_email: Your company email.

        Returns:
            The path to the generated PDF file.
        """
        est = self.store.get_estimate(estimate_id)
        if not est:
            raise ValueError(f"Estimate '{estimate_id}' not found.")

        from .pdf import generate_estimate_pdf
        return generate_estimate_pdf(
            estimate=est,
            output_path=output_path,
            company_name=company_name,
            company_address=company_address,
            company_email=company_email,
        )

    # -----------------------------------------------------------------------
    # Expenses (v0.7.0)
    # -----------------------------------------------------------------------

    def create_expense(
        self,
        description: str,
        amount: float,
        currency: str = "USD",
        category: ExpenseCategory | str = ExpenseCategory.OTHER,
        vendor: Optional[str] = None,
        expense_date: Optional[date] = None,
        payment_method: Optional[str] = None,
        reference: Optional[str] = None,
        notes: Optional[str] = None,
        tax_deductible: bool = True,
    ) -> Expense:
        """Create and save a new expense."""
        if amount <= 0:
            raise ValueError("Expense amount must be positive.")
        if currency.upper() not in CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}. Supported: {', '.join(sorted(CURRENCIES.keys()))}")
        # Normalize category
        if isinstance(category, str):
            try:
                category = ExpenseCategory(category.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid category '{category}'. Valid: {', '.join(c.value for c in ExpenseCategory)}"
                )
        expense = Expense(
            description=description,
            amount=round(amount, 2),
            currency=currency.upper(),
            category=category,
            vendor=vendor,
            expense_date=expense_date or date.today(),
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            tax_deductible=tax_deductible,
        )
        return self.store.save_expense(expense)

    def get_expense(self, expense_id: str) -> Optional[Expense]:
        """Get an expense by ID."""
        return self.store.get_expense(expense_id)

    def list_expenses(
        self,
        category: Optional[ExpenseCategory | str] = None,
        currency: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        vendor: Optional[str] = None,
    ) -> list[Expense]:
        """List expenses with optional filters."""
        return self.store.list_expenses(
            category=category,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            vendor=vendor,
        )

    def update_expense(
        self,
        expense_id: str,
        description: Optional[str] = None,
        amount: Optional[float] = None,
        category: Optional[ExpenseCategory | str] = None,
        vendor: Optional[str] = None,
        payment_method: Optional[str] = None,
        notes: Optional[str] = None,
        tax_deductible: Optional[bool] = None,
    ) -> Expense:
        """Update an existing expense."""
        expense = self.store.get_expense(expense_id)
        if not expense:
            raise ValueError(f"Expense '{expense_id}' not found.")
        if description is not None:
            expense.description = description
        if amount is not None:
            if amount <= 0:
                raise ValueError("Expense amount must be positive.")
            expense.amount = round(amount, 2)
        if category is not None:
            if isinstance(category, str):
                try:
                    category = ExpenseCategory(category.lower())
                except ValueError:
                    raise ValueError(
                        f"Invalid category '{category}'. Valid: {', '.join(c.value for c in ExpenseCategory)}"
                    )
            expense.category = category
        if vendor is not None:
            expense.vendor = vendor
        if payment_method is not None:
            expense.payment_method = payment_method
        if notes is not None:
            expense.notes = notes
        if tax_deductible is not None:
            expense.tax_deductible = tax_deductible
        expense.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_expense(expense)

    def remove_expense(self, expense_id: str) -> bool:
        """Remove an expense."""
        return self.store.delete_expense(expense_id)

    def expense_summary(
        self,
        currency: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        """Get a summary of expenses broken down by category."""
        expenses = self.list_expenses(currency=currency, date_from=date_from, date_to=date_to)
        total = round(sum(e.amount for e in expenses), 2)
        by_category: dict[str, dict] = {}
        for e in expenses:
            cat = e.category.value
            if cat not in by_category:
                by_category[cat] = {"amount": 0.0, "count": 0}
            by_category[cat]["amount"] = round(by_category[cat]["amount"] + e.amount, 2)
            by_category[cat]["count"] += 1
        # Add percentage
        breakdown = []
        for cat, data in sorted(by_category.items(), key=lambda x: -x[1]["amount"]):
            pct = round(data["amount"] / total * 100, 1) if total > 0 else 0.0
            breakdown.append({"category": cat, "amount": data["amount"], "count": data["count"], "percentage": pct})
        return {
            "total": total,
            "expense_count": len(expenses),
            "currency": currency or "ALL",
            "breakdown": breakdown,
        }

    # -----------------------------------------------------------------------
    # Profit Analysis (v0.7.0)
    # -----------------------------------------------------------------------

    def get_profit_analysis(
        self,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        currency: Optional[str] = "USD",
    ) -> ProfitAnalysis:
        """Analyze profitability: revenue from collected invoices minus expenses.

        Args:
            period_start: Start date filter (None = all-time).
            period_end: End date filter (None = today).
            currency: Filter by currency. Defaults to USD.
        """
        period_end = period_end or date.today()
        currency = (currency or "USD").upper()

        # Revenue: sum of all payments received within the period
        invoices = self.list_invoices(currency=currency)
        total_revenue = 0.0
        for inv in invoices:
            for pmt in inv.payments:
                if period_start and pmt.payment_date < period_start:
                    continue
                if pmt.payment_date > period_end:
                    continue
                total_revenue += pmt.amount
        total_revenue = round(total_revenue, 2)

        # Expenses: sum of all expenses in the period
        expenses = self.list_expenses(currency=currency, date_from=period_start, date_to=period_end)
        total_expenses = round(sum(e.amount for e in expenses), 2)

        # Expense breakdown by category
        by_category: dict[str, dict] = {}
        for e in expenses:
            cat = e.category.value
            if cat not in by_category:
                by_category[cat] = {"amount": 0.0, "count": 0}
            by_category[cat]["amount"] = round(by_category[cat]["amount"] + e.amount, 2)
            by_category[cat]["count"] += 1
        expense_breakdown = []
        for cat, data in sorted(by_category.items(), key=lambda x: -x[1]["amount"]):
            pct = round(data["amount"] / total_expenses * 100, 1) if total_expenses > 0 else 0.0
            expense_breakdown.append({"category": cat, "amount": data["amount"], "count": data["count"], "percentage": pct})

        # Gross profit and margin
        gross_profit = round(total_revenue - total_expenses, 2)
        gross_margin = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0.0

        # Per-client profitability
        client_profitability = self._compute_client_profitability(
            invoices=invoices,
            expenses=expenses,
            period_start=period_start,
            period_end=period_end,
        )

        return ProfitAnalysis(
            currency=currency,
            period_start=period_start,
            period_end=period_end,
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
            expense_breakdown=expense_breakdown,
            client_profitability=client_profitability,
        )

    def _compute_client_profitability(
        self,
        invoices: list[Invoice],
        expenses: list[Expense],
        period_start: Optional[date],
        period_end: date,
    ) -> list[ClientProfitability]:
        """Compute per-client profitability."""
        # Group invoices by client
        client_map: dict[str, list[Invoice]] = {}
        for inv in invoices:
            client_map.setdefault(inv.client_id, []).append(inv)

        # Build expense link map (by invoice_id if present)
        expenses_by_invoice: dict[str, list[Expense]] = {}
        for e in expenses:
            if e.invoice_id:
                expenses_by_invoice.setdefault(e.invoice_id, []).append(e)

        results = []
        for client_id, client_invs in client_map.items():
            client_name = client_invs[0].client_name
            total_invoiced = round(sum(inv.total for inv in client_invs), 2)
            total_collected = 0.0
            for inv in client_invs:
                for pmt in inv.payments:
                    if period_start and pmt.payment_date < period_start:
                        continue
                    if pmt.payment_date > period_end:
                        continue
                    total_collected += pmt.amount
            total_collected = round(total_collected, 2)
            total_outstanding = round(total_invoiced - sum(inv.amount_paid for inv in client_invs), 2)
            # Direct costs: expenses linked to this client's invoices
            direct_costs = 0.0
            for inv in client_invs:
                for e in expenses_by_invoice.get(inv.id, []):
                    direct_costs += e.amount
            direct_costs = round(direct_costs, 2)
            gross_profit = round(total_collected - direct_costs, 2)
            gross_margin = round(gross_profit / total_collected * 100, 1) if total_collected > 0 else 0.0
            paid_count = sum(1 for inv in client_invs if inv.status == InvoiceStatus.PAID)
            avg_val = round(total_invoiced / len(client_invs), 2) if client_invs else 0.0

            results.append(ClientProfitability(
                client_id=client_id,
                client_name=client_name,
                currency=invoices[0].currency if invoices else "USD",
                total_invoiced=total_invoiced,
                total_collected=total_collected,
                total_outstanding=total_outstanding,
                direct_costs=direct_costs,
                gross_revenue=total_collected,
                gross_profit=gross_profit,
                gross_margin=gross_margin,
                invoice_count=len(client_invs),
                paid_invoice_count=paid_count,
                avg_invoice_value=avg_val,
            ))

        # Sort by gross profit descending
        results.sort(key=lambda c: -c.gross_profit)
        return results

    # -----------------------------------------------------------------------
    # Tax Summary Report (v0.7.0)
    # -----------------------------------------------------------------------

    def generate_tax_summary(
        self,
        period_start: date,
        period_end: date,
        currency: Optional[str] = None,
    ) -> TaxSummaryReport:
        """Generate a tax summary report for a given period.

        Shows total invoiced, tax collected (all invoices and from paid invoices only),
        effective tax rate, tax breakdown by rate, and deductible expenses.
        """
        invoices = self.list_invoices(currency=currency)

        # Filter invoices by issue date within the period
        period_invoices = []
        for inv in invoices:
            if inv.issue_date < period_start or inv.issue_date > period_end:
                continue
            period_invoices.append(inv)

        total_invoiced = 0.0
        total_tax_collected = 0.0
        total_tax_from_paid = 0.0
        tax_by_rate_map: dict[str, dict] = {}
        invoice_details = []

        for inv in period_invoices:
            inv_subtotal = inv.subtotal
            inv_tax = inv.total_tax
            total_invoiced += inv_subtotal
            total_tax_collected += inv_tax
            if inv.status == InvoiceStatus.PAID:
                total_tax_from_paid += inv_tax

            # Compute blended tax rate for this invoice
            blended_rate = round(inv_tax / inv_subtotal * 100, 2) if inv_subtotal > 0 else 0.0
            invoice_details.append(TaxLineItemSummary(
                invoice_id=inv.id,
                client_name=inv.client_name,
                issue_date=inv.issue_date,
                subtotal=inv_subtotal,
                tax_amount=inv_tax,
                tax_rate=blended_rate,
                currency=inv.currency,
            ))

            # Aggregate by per-line-item tax rates
            for item in inv.line_items:
                rate_key = f"{item.tax_rate:.1f}%"
                if rate_key not in tax_by_rate_map:
                    tax_by_rate_map[rate_key] = {"rate": item.tax_rate, "count": 0, "tax_amount": 0.0, "subtotal": 0.0}
                tax_by_rate_map[rate_key]["count"] += 1
                tax_by_rate_map[rate_key]["tax_amount"] = round(tax_by_rate_map[rate_key]["tax_amount"] + (item.tax_amount or 0), 2)
                tax_by_rate_map[rate_key]["subtotal"] = round(tax_by_rate_map[rate_key]["subtotal"] + (item.total or 0), 2)

        total_invoiced = round(total_invoiced, 2)
        total_tax_collected = round(total_tax_collected, 2)
        total_tax_from_paid = round(total_tax_from_paid, 2)
        effective_tax_rate = round(total_tax_collected / total_invoiced * 100, 2) if total_invoiced > 0 else 0.0

        tax_by_rate = []
        for rate_key, data in sorted(tax_by_rate_map.items(), key=lambda x: -x[1]["tax_amount"]):
            tax_by_rate.append({
                "rate_label": rate_key,
                "rate": data["rate"],
                "count": data["count"],
                "tax_amount": data["tax_amount"],
                "subtotal": data["subtotal"],
            })

        # Deductible expenses in the period
        expenses = self.list_expenses(currency=currency, date_from=period_start, date_to=period_end)
        tax_deductible_expenses = round(sum(e.amount for e in expenses if e.tax_deductible), 2)
        net_taxable = round(total_invoiced - tax_deductible_expenses, 2)

        return TaxSummaryReport(
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            total_invoiced=total_invoiced,
            total_tax_collected=total_tax_collected,
            total_tax_from_paid=total_tax_from_paid,
            effective_tax_rate=effective_tax_rate,
            tax_by_rate=tax_by_rate,
            invoice_details=invoice_details,
            tax_deductible_expenses=tax_deductible_expenses,
            net_taxable_income=net_taxable,
        )

    # -----------------------------------------------------------------------
    # Bulk Operations (v0.7.0)
    # -----------------------------------------------------------------------

    def bulk_mark_sent(self, invoice_ids: list[str]) -> dict:
        """Mark multiple invoices as sent.

        Returns: {"success": [...], "errors": [{"id": ..., "error": "..."}]}
        """
        results: dict = {"success": [], "errors": []}
        for inv_id in invoice_ids:
            inv = self.store.get_invoice(inv_id)
            if not inv:
                results["errors"].append({"id": inv_id, "error": "Invoice not found."})
                continue
            try:
                if inv.status != InvoiceStatus.DRAFT:
                    results["errors"].append({"id": inv_id, "error": f"Cannot mark as sent: status is '{inv.status.value}' (must be draft)."})
                    continue
                inv.mark_sent()
                self.store.save_invoice(inv)
                results["success"].append(inv_id)
            except Exception as exc:
                results["errors"].append({"id": inv_id, "error": str(exc)})
        return results

    def bulk_mark_paid(self, invoice_ids: list[str]) -> dict:
        """Mark multiple invoices as paid.

        Returns: {"success": [...], "errors": [{"id": ..., "error": "..."}]}
        """
        results: dict = {"success": [], "errors": []}
        for inv_id in invoice_ids:
            inv = self.store.get_invoice(inv_id)
            if not inv:
                results["errors"].append({"id": inv_id, "error": "Invoice not found."})
                continue
            try:
                if inv.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                    results["errors"].append({"id": inv_id, "error": f"Cannot mark as paid: status is '{inv.status.value}'."})
                    continue
                inv.mark_paid()
                self.store.save_invoice(inv)
                results["success"].append(inv_id)
            except Exception as exc:
                results["errors"].append({"id": inv_id, "error": str(exc)})
        return results

    def bulk_cancel(self, invoice_ids: list[str]) -> dict:
        """Cancel multiple invoices.

        Returns: {"success": [...], "errors": [{"id": ..., "error": "..."}]}
        """
        results: dict = {"success": [], "errors": []}
        for inv_id in invoice_ids:
            inv = self.store.get_invoice(inv_id)
            if not inv:
                results["errors"].append({"id": inv_id, "error": "Invoice not found."})
                continue
            try:
                if inv.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                    results["errors"].append({"id": inv_id, "error": f"Cannot cancel: status is '{inv.status.value}'."})
                    continue
                inv.status = InvoiceStatus.CANCELLED
                inv.updated_at = datetime.now(tz=timezone.utc)
                self.store.save_invoice(inv)
                results["success"].append(inv_id)
            except Exception as exc:
                results["errors"].append({"id": inv_id, "error": str(exc)})
        return results

    def bulk_export(self, invoice_ids: list[str], format: str = "markdown") -> dict:
        """Export multiple invoices to the specified format.

        Returns: {"exports": [{"id": ..., "format": ..., "content": ...}], "errors": [...]}
        """
        results: dict = {"exports": [], "errors": []}
        for inv_id in invoice_ids:
            inv = self.store.get_invoice(inv_id)
            if not inv:
                results["errors"].append({"id": inv_id, "error": "Invoice not found."})
                continue
            try:
                if format == "markdown":
                    content = inv.to_markdown()
                elif format == "json":
                    content = inv.model_dump_json(indent=2)
                else:
                    results["errors"].append({"id": inv_id, "error": f"Unsupported format: {format}"})
                    continue
                results["exports"].append({"id": inv_id, "format": format, "content": content})
            except Exception as exc:
                results["errors"].append({"id": inv_id, "error": str(exc)})
        return results
