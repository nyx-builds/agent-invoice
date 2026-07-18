"""Business logic / service layer for Agent Invoice."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import (
    ARAgingBucket,
    ARAgingReport,
    BUILTIN_PLANS,
    BUILTIN_TEMPLATES,
    BillingCycle,
    CURRENCIES,
    Client,
    ClientARAging,
    ClientProfitability,
    ClientStatement,
    CostAnomaly,
    CostProjection,
    CostTrend,
    CreditNote,
    CreditNoteStatus,
    DunningAction,
    DunningConfig,
    DunningLevel,
    EarningsSummary,
    EfficiencyReport,
    Estimate,
    EstimateStatus,
    Expense,
    ExpenseCategory,
    Invoice,
    InvoiceStatus,
    InvoiceTemplate,
    LineItem,
    ModelEfficiency,
    MonthlyRevenue,
    MRRSummary,
    NumberingConfig,
    Payment,
    ProviderComparison,
    ProfitAnalysis,
    AnomalyReport,
    BatchUsageResult,
    ModelPricing,
    RateCard,
    RecurrenceFrequency,
    RecurringInvoice,
    RevenueAnalytics,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    TaxLineItemSummary,
    TaxSummaryReport,
    UsageEvent,
    UsageSummary,
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

    # -----------------------------------------------------------------------
    # Usage Metering & Agent Billing (v0.8.0)
    # -----------------------------------------------------------------------

    def record_usage(
        self,
        description: str,
        cost: float,
        client_identifier: Optional[str] = None,
        provider: str = "openai",
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_count: int = 1,
        currency: str = "USD",
        metadata: Optional[dict] = None,
    ) -> UsageEvent:
        """Record a usage event for metering and billing.

        Captures API/agent resource consumption tied to a client so it can
        be aggregated into usage records and billed via invoices.

        Args:
            description: Human-readable description of the usage.
            cost: Dollar cost of this usage event.
            client_identifier: Client ID or name to attribute this usage to.
            provider: AI provider (openai, anthropic, google, custom, etc.).
            model: Specific model used (e.g. gpt-4, claude-3-opus).
            input_tokens: Input/prompt tokens consumed.
            output_tokens: Output/completion tokens generated.
            cache_read_tokens: Tokens read from cache.
            cache_write_tokens: Tokens written to cache.
            request_count: Number of API requests in this event.
            currency: Currency code for the cost.
            metadata: Arbitrary key-value tags (project, task, agent_id).

        Returns:
            The created UsageEvent.
        """
        if cost < 0:
            raise ValueError("Usage cost cannot be negative.")

        client_id = None
        client_name = None
        if client_identifier:
            client = self.get_client(client_identifier)
            if not client:
                raise ValueError(f"Client '{client_identifier}' not found.")
            client_id = client.id
            client_name = client.name

        event = UsageEvent(
            client_id=client_id,
            client_name=client_name,
            description=description,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            request_count=request_count,
            cost=round(cost, 6),
            currency=currency.upper(),
            metadata=metadata or {},
        )
        return self.store.save_usage_event(event)

    def get_usage_event(self, event_id: str) -> Optional[UsageEvent]:
        """Get a usage event by ID."""
        return self.store.get_usage_event(event_id)

    def list_usage_events(
        self,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        billed: Optional[bool] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[UsageEvent]:
        """List usage events with optional filters."""
        client_id = None
        if client_identifier:
            c = self.get_client(client_identifier)
            if c:
                client_id = c.id
        return self.store.list_usage_events(
            client_id=client_id,
            provider=provider,
            model=model,
            billed=billed,
            date_from=date_from,
            date_to=date_to,
        )

    def remove_usage_event(self, event_id: str) -> bool:
        """Delete a usage event. Cannot delete billed events."""
        event = self.store.get_usage_event(event_id)
        if not event:
            return False
        if event.billed:
            raise ValueError(f"Cannot delete billed usage event '{event_id}'. Remove from invoice first.")
        return self.store.delete_usage_event(event_id)

    def get_usage_summary(
        self,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> UsageSummary:
        """Get aggregated usage summary across events with optional filters.

        Provides totals, billed vs unbilled breakdowns, and per-provider,
        per-model, per-client, and daily breakdowns.
        """
        client_id = None
        if client_identifier:
            c = self.get_client(client_identifier)
            if c:
                client_id = c.id

        events = self.store.list_usage_events(
            client_id=client_id,
            provider=provider,
            model=model,
            date_from=date_from,
            date_to=date_to,
        )

        if currency:
            events = [e for e in events if e.currency == currency.upper()]

        total_cost = 0.0
        total_input = 0
        total_output = 0
        billed_cost = 0.0
        unbilled_cost = 0.0
        billed_events = 0
        unbilled_events = 0

        provider_map: dict[str, dict] = {}
        model_map: dict[str, dict] = {}
        client_map: dict[str, dict] = {}
        daily_map: dict[str, dict] = {}

        for e in events:
            total_cost += e.cost
            total_input += e.input_tokens + e.cache_read_tokens + e.cache_write_tokens
            total_output += e.output_tokens

            if e.billed:
                billed_cost += e.cost
                billed_events += 1
            else:
                unbilled_cost += e.cost
                unbilled_events += 1

            # By provider
            p = e.provider
            if p not in provider_map:
                provider_map[p] = {"provider": p, "events": 0, "cost": 0.0, "tokens": 0}
            provider_map[p]["events"] += 1
            provider_map[p]["cost"] = round(provider_map[p]["cost"] + e.cost, 6)
            provider_map[p]["tokens"] += e.total_tokens

            # By model
            m = e.model or "unknown"
            if m not in model_map:
                model_map[m] = {"model": m, "events": 0, "cost": 0.0, "tokens": 0}
            model_map[m]["events"] += 1
            model_map[m]["cost"] = round(model_map[m]["cost"] + e.cost, 6)
            model_map[m]["tokens"] += e.total_tokens

            # By client
            cid = e.client_id or "unattributed"
            cname = e.client_name or "Unattributed"
            if cid not in client_map:
                client_map[cid] = {"client_id": cid, "client_name": cname, "events": 0, "cost": 0.0}
            client_map[cid]["events"] += 1
            client_map[cid]["cost"] = round(client_map[cid]["cost"] + e.cost, 6)

            # Daily
            day_key = e.recorded_at.strftime("%Y-%m-%d")
            if day_key not in daily_map:
                daily_map[day_key] = {"date": day_key, "events": 0, "cost": 0.0}
            daily_map[day_key]["events"] += 1
            daily_map[day_key]["cost"] = round(daily_map[day_key]["cost"] + e.cost, 6)

        return UsageSummary(
            period_start=date_from,
            period_end=date_to,
            currency=currency.upper() if currency else None,
            client_id=client_id,
            total_events=len(events),
            total_cost=round(total_cost, 6),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_input + total_output,
            billed_cost=round(billed_cost, 6),
            unbilled_cost=round(unbilled_cost, 6),
            billed_events=billed_events,
            unbilled_events=unbilled_events,
            by_provider=sorted(provider_map.values(), key=lambda x: -x["cost"]),
            by_model=sorted(model_map.values(), key=lambda x: -x["cost"]),
            by_client=sorted(client_map.values(), key=lambda x: -x["cost"]),
            daily=sorted(daily_map.values(), key=lambda x: x["date"]),
        )

    def aggregate_usage_to_record(
        self,
        client_identifier: str,
        period_start: date,
        period_end: date,
        currency: str = "USD",
        include_billed: bool = False,
    ) -> dict:
        """Aggregate unbilled usage events for a client into a usage record.

        Collects all usage events for the specified client within the date
        range, groups them by provider and model, and returns a structured
        record that can be turned into invoice line items.

        Args:
            client_identifier: Client ID or name.
            period_start: Start of usage period.
            period_end: End of usage period.
            currency: Filter by currency.
            include_billed: Include already-billed events (default: only unbilled).

        Returns:
            Dict with aggregated usage data and derived line items.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")

        billed_filter = None if include_billed else False
        events = self.store.list_usage_events(
            client_id=client.id,
            billed=billed_filter,
            date_from=period_start,
            date_to=period_end,
        )
        events = [e for e in events if e.currency == currency.upper()]

        if not events:
            return {
                "client_id": client.id,
                "client_name": client.name,
                "period_start": str(period_start),
                "period_end": str(period_end),
                "currency": currency.upper(),
                "total_cost": 0.0,
                "event_count": 0,
                "line_items": [],
                "event_ids": [],
            }

        # Aggregate by (provider, model)
        agg: dict[tuple[str, str], dict] = {}
        all_event_ids = []
        for e in events:
            key = (e.provider, e.model or "unknown")
            if key not in agg:
                agg[key] = {
                    "provider": e.provider,
                    "model": key[1],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "request_count": 0,
                    "cost": 0.0,
                    "event_count": 0,
                    "event_ids": [],
                }
            agg[key]["input_tokens"] += e.input_tokens
            agg[key]["output_tokens"] += e.output_tokens
            agg[key]["cache_read_tokens"] += e.cache_read_tokens
            agg[key]["cache_write_tokens"] += e.cache_write_tokens
            agg[key]["request_count"] += e.request_count
            agg[key]["cost"] = round(agg[key]["cost"] + e.cost, 6)
            agg[key]["event_count"] += 1
            agg[key]["event_ids"].append(e.id)
            all_event_ids.append(e.id)

        # Build line items
        line_items = []
        for (provider, model), data in sorted(agg.items()):
            description = f"AI Usage: {provider}/{model}"
            if data["request_count"] > 1:
                description += f" ({data['request_count']} requests)"
            if data["input_tokens"] > 0 or data["output_tokens"] > 0:
                total_toks = data["input_tokens"] + data["output_tokens"]
                description += f" [{total_toks:,} tokens]"
            line_items.append({
                "description": description,
                "quantity": 1,
                "unit_price": round(data["cost"], 2),
            })

        # Provider breakdown
        provider_breakdown = []
        model_breakdown = []
        for (provider, model), data in agg.items():
            provider_breakdown.append({
                "provider": provider,
                "model": model,
                "requests": data["request_count"],
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "cost": round(data["cost"], 6),
            })
            model_breakdown.append({
                "model": model,
                "provider": provider,
                "requests": data["request_count"],
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "cost": round(data["cost"], 6),
            })

        total_cost = sum(d["cost"] for d in agg.values())

        return {
            "client_id": client.id,
            "client_name": client.name,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "currency": currency.upper(),
            "total_cost": round(total_cost, 2),
            "event_count": len(events),
            "line_items": line_items,
            "provider_breakdown": sorted(provider_breakdown, key=lambda x: -x["cost"]),
            "model_breakdown": sorted(model_breakdown, key=lambda x: -x["cost"]),
            "event_ids": all_event_ids,
        }

    def create_invoice_from_usage(
        self,
        client_identifier: str,
        period_start: date,
        period_end: date,
        currency: str = "USD",
        due_days: int = 30,
        markup_percent: float = 0.0,
        notes: Optional[str] = None,
    ) -> tuple[Invoice, dict]:
        """Create an invoice from accumulated usage events for a client.

        Aggregates all unbilled usage events within the period, creates an
        invoice with line items per provider/model, and marks events as billed.

        Args:
            client_identifier: Client ID or name.
            period_start: Start of usage period.
            period_end: End of usage period.
            currency: Currency for the invoice.
            due_days: Days until invoice due date.
            markup_percent: Optional markup percentage to add on top of cost
                (e.g. 20.0 for 20% markup on usage cost).
            notes: Additional notes on the invoice.

        Returns:
            Tuple of (created Invoice, usage record dict with details).
        """
        usage_record = self.aggregate_usage_to_record(
            client_identifier=client_identifier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            include_billed=False,
        )

        if usage_record["event_count"] == 0:
            raise ValueError(
                f"No unbilled usage events found for client '{client_identifier}' "
                f"in period {period_start} to {period_end}."
            )

        # Apply markup if requested
        line_items = usage_record["line_items"]
        if markup_percent > 0:
            multiplier = 1 + markup_percent / 100
            for item in line_items:
                item["unit_price"] = round(item["unit_price"] * multiplier, 2)

        default_notes = (
            f"Usage-based billing for period {period_start} to {period_end}. "
            f"{usage_record['event_count']} events across "
            f"{len(usage_record.get('provider_breakdown', []))} provider(s)."
        )
        if notes:
            default_notes = notes + "\n\n" + default_notes

        # Create the invoice
        invoice = self.create_invoice(
            client_identifier=client_identifier,
            line_items=line_items,
            due_days=due_days,
            notes=default_notes,
            currency=currency,
        )

        # Mark events as billed
        for event_id in usage_record["event_ids"]:
            event = self.store.get_usage_event(event_id)
            if event:
                event.billed = True
                event.invoice_id = invoice.id
                self.store.save_usage_event(event)

        return invoice, usage_record

    # -----------------------------------------------------------------------
    # v0.9.0: Usage Analytics & Cost Intelligence
    # -----------------------------------------------------------------------

    def _filter_usage_events(
        self,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> list[UsageEvent]:
        """Get filtered usage events (shared helper)."""
        client_id = None
        if client_identifier:
            c = self.get_client(client_identifier)
            if c:
                client_id = c.id
        events = self.store.list_usage_events(
            client_id=client_id,
            provider=provider,
            model=model,
            billed=None,
            date_from=date_from,
            date_to=date_to,
        )
        if currency:
            events = [e for e in events if e.currency == currency.upper()]
        return events

    def get_cost_trend(
        self,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
        granularity: str = "daily",
    ) -> CostTrend:
        """Get cost trend over time — daily, weekly, or monthly breakdown.

        Returns a time series of cost/events/tokens, plus trend direction
        and percentage change from first to last period.
        """
        events = self._filter_usage_events(
            client_identifier=client_identifier,
            provider=provider,
            model=model,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
        )

        if not events:
            return CostTrend(
                granularity=granularity,
                currency=currency,
                period_start=date_from,
                period_end=date_to,
                data_points=[],
            )

        def _period_key(d: date) -> str:
            if granularity == "weekly":
                iso = d.isocalendar()
                return f"{iso[0]}-W{iso[1]:02d}"
            elif granularity == "monthly":
                return f"{d.year}-{d.month:02d}"
            else:
                return d.isoformat()

        buckets: dict[str, dict] = {}
        for e in events:
            key = _period_key(e.recorded_at.date() if isinstance(e.recorded_at, datetime) else e.recorded_at)
            if key not in buckets:
                buckets[key] = {
                    "period": key,
                    "cost": 0.0,
                    "events": 0,
                    "tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            buckets[key]["cost"] = round(buckets[key]["cost"] + e.cost, 6)
            buckets[key]["events"] += 1
            buckets[key]["tokens"] += e.total_tokens
            buckets[key]["input_tokens"] += e.input_tokens
            buckets[key]["output_tokens"] += e.output_tokens

        sorted_keys = sorted(buckets.keys())
        data_points = [buckets[k] for k in sorted_keys]
        costs = [dp["cost"] for dp in data_points]

        total_cost = round(sum(costs), 6)
        avg_cost = round(total_cost / len(data_points), 6) if data_points else 0.0

        # Determine trend direction
        trend_direction = "stable"
        trend_percent = 0.0
        if len(costs) >= 2 and costs[0] > 0:
            change = ((costs[-1] - costs[0]) / costs[0]) * 100
            trend_percent = round(change, 1)
            if change > 10:
                trend_direction = "increasing"
            elif change < -10:
                trend_direction = "decreasing"

        return CostTrend(
            granularity=granularity,
            currency=currency,
            period_start=date_from,
            period_end=date_to,
            data_points=data_points,
            total_cost=total_cost,
            total_events=sum(dp["events"] for dp in data_points),
            avg_cost_per_period=avg_cost,
            min_cost=round(min(costs), 6) if costs else 0.0,
            max_cost=round(max(costs), 6) if costs else 0.0,
            trend_direction=trend_direction,
            trend_percent=trend_percent,
        )

    def get_cost_projection(
        self,
        projection_days: int = 30,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        currency: Optional[str] = None,
        lookback_days: int = 30,
    ) -> CostProjection:
        """Project future cost based on historical spending patterns.

        Uses moving average of daily costs over the lookback period to
        project forward. Confidence is based on data volume.
        """
        date_to = date.today()
        date_from = date_to - timedelta(days=lookback_days)

        events = self._filter_usage_events(
            client_identifier=client_identifier,
            provider=provider,
            model=model,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
        )

        if not events:
            return CostProjection(
                currency=currency,
                projected_cost=0.0,
                methodology="No historical data in lookback period.",
            )

        # Calculate daily averages
        daily_costs: dict[str, float] = {}
        for e in events:
            d = e.recorded_at.date() if isinstance(e.recorded_at, datetime) else e.recorded_at
            key = d.isoformat()
            daily_costs[key] = round(daily_costs.get(key, 0.0) + e.cost, 6)

        # How many days actually had data
        days_with_data = len(daily_costs)
        total_historical = round(sum(daily_costs.values()), 6)

        # Average daily cost across all lookback days
        actual_days = max(1, (date_to - date_from).days + 1)
        avg_daily = round(total_historical / actual_days, 6)

        projected_total = round(avg_daily * projection_days, 6)

        # Confidence level
        if days_with_data >= 14:
            confidence = "high"
        elif days_with_data >= 7:
            confidence = "medium"
        else:
            confidence = "low"

        # Build projected breakdown
        projected_breakdown = []
        for i in range(projection_days):
            future_date = date_to + timedelta(days=i + 1)
            projected_breakdown.append({
                "period": future_date.isoformat(),
                "projected_cost": avg_daily,
                "is_projection": True,
            })

        methodology = (
            f"Moving average of {total_historical:.4f} cost over {days_with_data} active days "
            f"in {lookback_days}-day lookback period. Average daily cost: {avg_daily:.4f}. "
            f"Projected {projection_days} days forward."
        )

        return CostProjection(
            currency=currency,
            historical_periods=days_with_data,
            projection_periods=projection_days,
            granularity="daily",
            avg_daily_cost=avg_daily,
            projected_cost=projected_total,
            projected_breakdown=projected_breakdown,
            confidence=confidence,
            methodology=methodology,
        )

    def detect_cost_anomalies(
        self,
        client_identifier: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
        threshold_percent: float = 50.0,
    ) -> AnomalyReport:
        """Detect cost anomalies — days where spending deviates from baseline.

        Computes a baseline average daily cost and flags any day where actual
        cost exceeds baseline by threshold_percent (default 50%).
        """
        events = self._filter_usage_events(
            client_identifier=client_identifier,
            provider=provider,
            model=model,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
        )

        if not events:
            return AnomalyReport(
                period_start=date_from,
                period_end=date_to,
                currency=currency,
                anomaly_threshold_percent=threshold_percent,
                anomalies=[],
                baseline_avg_cost=0.0,
            )

        # Group by day
        daily: dict[str, dict] = {}
        for e in events:
            d = e.recorded_at.date() if isinstance(e.recorded_at, datetime) else e.recorded_at
            key = d.isoformat()
            if key not in daily:
                daily[key] = {"cost": 0.0, "events": 0, "providers": {}, "clients": {}}
            daily[key]["cost"] = round(daily[key]["cost"] + e.cost, 6)
            daily[key]["events"] += 1
            daily[key]["providers"][e.provider] = daily[key]["providers"].get(e.provider, 0.0) + e.cost
            if e.client_name:
                daily[key]["clients"][e.client_name] = daily[key]["clients"].get(e.client_name, 0.0) + e.cost

        sorted_days = sorted(daily.keys())
        costs = [daily[d]["cost"] for d in sorted_days]
        baseline_avg = round(sum(costs) / len(costs), 6) if costs else 0.0

        anomalies: list[CostAnomaly] = []
        for day in sorted_days:
            actual = daily[day]["cost"]
            if baseline_avg > 0:
                deviation = ((actual - baseline_avg) / baseline_avg) * 100
            else:
                deviation = 0.0 if actual == 0 else 100.0

            if deviation >= threshold_percent:
                # Determine severity
                if deviation >= 200:
                    severity = "critical"
                elif deviation >= 100:
                    severity = "warning"
                else:
                    severity = "info"

                # Top provider and client for this day
                top_provider = max(daily[day]["providers"], key=daily[day]["providers"].get) if daily[day]["providers"] else None
                top_client = max(daily[day]["clients"], key=daily[day]["clients"].get) if daily[day]["clients"] else None

                anomalies.append(CostAnomaly(
                    period=day,
                    expected_cost=baseline_avg,
                    actual_cost=round(actual, 6),
                    deviation_percent=round(deviation, 1),
                    severity=severity,
                    event_count=daily[day]["events"],
                    top_provider=top_provider,
                    top_client=top_client,
                ))

        return AnomalyReport(
            period_start=date_from,
            period_end=date_to,
            currency=currency,
            baseline_avg_cost=baseline_avg,
            anomaly_threshold_percent=threshold_percent,
            anomalies=anomalies,
            total_anomalies=len(anomalies),
        )

    def get_model_efficiency(
        self,
        client_identifier: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> EfficiencyReport:
        """Compare cost efficiency across all models/providers.

        Metrics: cost per 1K tokens, cost per request, average tokens per
        event, output ratio, cache hit ratio.
        """
        events = self._filter_usage_events(
            client_identifier=client_identifier,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
        )

        if not events:
            return EfficiencyReport(
                currency=currency,
                period_start=date_from,
                period_end=date_to,
                models=[],
            )

        # Aggregate by (provider, model)
        agg: dict[tuple[str, str], dict] = {}
        for e in events:
            key = (e.provider, e.model or "unknown")
            if key not in agg:
                agg[key] = {
                    "provider": e.provider,
                    "model": key[1],
                    "cost": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "total_tokens": 0,
                    "requests": 0,
                    "events": 0,
                }
            agg[key]["cost"] = round(agg[key]["cost"] + e.cost, 6)
            agg[key]["input_tokens"] += e.input_tokens
            agg[key]["output_tokens"] += e.output_tokens
            agg[key]["cache_read_tokens"] += e.cache_read_tokens
            agg[key]["cache_write_tokens"] += e.cache_write_tokens
            agg[key]["total_tokens"] += e.total_tokens
            agg[key]["requests"] += e.request_count
            agg[key]["events"] += 1

        models: list[ModelEfficiency] = []
        for (provider, model), d in sorted(agg.items(), key=lambda x: -x[1]["cost"]):
            total_toks = d["total_tokens"]
            cost_per_1k = round(d["cost"] / (total_toks / 1000), 6) if total_toks > 0 else 0.0
            cost_per_req = round(d["cost"] / d["requests"], 6) if d["requests"] > 0 else 0.0
            avg_toks = round(total_toks / d["events"], 1) if d["events"] > 0 else 0.0
            output_ratio = round(d["output_tokens"] / total_toks, 4) if total_toks > 0 else 0.0
            cache_hit = round(
                d["cache_read_tokens"] / (d["input_tokens"] + d["cache_read_tokens"]), 4
            ) if (d["input_tokens"] + d["cache_read_tokens"]) > 0 else 0.0

            models.append(ModelEfficiency(
                provider=d["provider"],
                model=d["model"],
                event_count=d["events"],
                total_cost=round(d["cost"], 6),
                total_input_tokens=d["input_tokens"],
                total_output_tokens=d["output_tokens"],
                total_tokens=total_toks,
                total_requests=d["requests"],
                cost_per_1k_tokens=cost_per_1k,
                cost_per_request=cost_per_req,
                avg_tokens_per_event=avg_toks,
                output_ratio=output_ratio,
                cache_hit_ratio=cache_hit,
            ))

        # Find best in each category
        cheapest_1k = min(models, key=lambda m: m.cost_per_1k_tokens) if models else None
        cheapest_req = min(models, key=lambda m: m.cost_per_request) if models else None
        best_output = max(models, key=lambda m: m.output_ratio) if models else None
        best_cache = max(models, key=lambda m: m.cache_hit_ratio) if models else None

        return EfficiencyReport(
            currency=currency,
            period_start=date_from,
            period_end=date_to,
            models=models,
            cheapest_per_1k_tokens={
                "provider": cheapest_1k.provider,
                "model": cheapest_1k.model,
                "cost_per_1k": cheapest_1k.cost_per_1k_tokens,
            } if cheapest_1k else None,
            cheapest_per_request={
                "provider": cheapest_req.provider,
                "model": cheapest_req.model,
                "cost_per_request": cheapest_req.cost_per_request,
            } if cheapest_req else None,
            most_efficient_output={
                "provider": best_output.provider,
                "model": best_output.model,
                "output_ratio": best_output.output_ratio,
            } if best_output else None,
            best_cache_utilization={
                "provider": best_cache.provider,
                "model": best_cache.model,
                "cache_hit_ratio": best_cache.cache_hit_ratio,
            } if best_cache else None,
        )

    def compare_providers(
        self,
        client_identifier: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> ProviderComparison:
        """Side-by-side comparison of AI providers.

        Shows total cost, event count, token volume, average cost per event,
        market share, and model count for each provider.
        """
        events = self._filter_usage_events(
            client_identifier=client_identifier,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
        )

        if not events:
            return ProviderComparison(
                currency=currency,
                period_start=date_from,
                period_end=date_to,
                providers=[],
                total_cost=0.0,
            )

        # Aggregate by provider
        prov_agg: dict[str, dict] = {}
        for e in events:
            p = e.provider
            if p not in prov_agg:
                prov_agg[p] = {
                    "provider": p,
                    "total_cost": 0.0,
                    "events": 0,
                    "tokens": 0,
                    "models": set(),
                }
            prov_agg[p]["total_cost"] = round(prov_agg[p]["total_cost"] + e.cost, 6)
            prov_agg[p]["events"] += 1
            prov_agg[p]["tokens"] += e.total_tokens
            if e.model:
                prov_agg[p]["models"].add(e.model)

        total_cost = round(sum(d["total_cost"] for d in prov_agg.values()), 6)

        providers = []
        for p, d in sorted(prov_agg.items(), key=lambda x: -x[1]["total_cost"]):
            share = round(d["total_cost"] / total_cost * 100, 1) if total_cost > 0 else 0.0
            avg_cost = round(d["total_cost"] / d["events"], 6) if d["events"] > 0 else 0.0
            providers.append({
                "provider": p,
                "total_cost": d["total_cost"],
                "events": d["events"],
                "tokens": d["tokens"],
                "avg_cost_per_event": avg_cost,
                "share_percent": share,
                "model_count": len(d["models"]),
                "models": sorted(d["models"]),
            })

        dominant = providers[0]["provider"] if providers else None

        return ProviderComparison(
            currency=currency,
            period_start=date_from,
            period_end=date_to,
            providers=providers,
            total_cost=total_cost,
            dominant_provider=dominant,
        )

    # ===================================================================
    # v1.0.0 — Rate Cards: automatic per-token cost calculation
    # ===================================================================

    def create_rate_card(
        self,
        name: str,
        currency: str = "USD",
        description: Optional[str] = None,
        models: Optional[list[dict]] = None,
        active: bool = True,
    ) -> RateCard:
        """Create a rate card mapping provider+model to per-token pricing.

        Args:
            name: Human-readable name (e.g. "Production 2026-Q3").
            currency: ISO currency code for all rates in this card.
            description: Optional notes.
            models: Optional list of pricing entries, each:
                {provider, model, input_rate, output_rate,
                 cache_read_rate?, cache_write_rate?, request_rate?}
                Rates are per 1,000,000 tokens (request_rate is per-request flat $).
            active: Whether this card is active.

        Returns:
            The created RateCard.
        """
        if not name or not name.strip():
            raise ValueError("Rate card name is required.")
        currency = (currency or "USD").upper()
        card = RateCard(
            name=name.strip(),
            currency=currency,
            description=description,
            active=active,
        )
        for entry in models or []:
            pricing = ModelPricing(
                input_rate=float(entry.get("input_rate", 0.0)),
                output_rate=float(entry.get("output_rate", 0.0)),
                cache_read_rate=float(entry.get("cache_read_rate", 0.0)),
                cache_write_rate=float(entry.get("cache_write_rate", 0.0)),
                request_rate=float(entry.get("request_rate", 0.0)),
            )
            card.set_pricing(
                provider=entry["provider"],
                model=entry["model"],
                pricing=pricing,
            )
        return self.store.save_rate_card(card)

    def get_rate_card(self, card_id: str) -> Optional[RateCard]:
        """Get a rate card by ID."""
        return self.store.get_rate_card(card_id)

    def list_rate_cards(self, active_only: bool = False) -> list[RateCard]:
        """List rate cards, optionally filtered to active only."""
        return self.store.list_rate_cards(active_only=active_only)

    def update_rate_card(self, card_id: str, **updates) -> RateCard:
        """Update a rate card's metadata (name, currency, description, active).

        For model pricing changes, use add_model_pricing / remove_model_pricing.
        """
        card = self.store.get_rate_card(card_id)
        if not card:
            raise ValueError(f"Rate card '{card_id}' not found.")
        if "name" in updates:
            if not updates["name"] or not str(updates["name"]).strip():
                raise ValueError("Rate card name cannot be empty.")
            card.name = str(updates["name"]).strip()
        if "currency" in updates:
            card.currency = str(updates["currency"]).upper()
        if "description" in updates:
            card.description = updates["description"]
        if "active" in updates:
            card.active = bool(updates["active"])
        card.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_rate_card(card)

    def remove_rate_card(self, card_id: str) -> bool:
        """Delete a rate card. Returns True if found and deleted."""
        return self.store.delete_rate_card(card_id)

    def add_model_pricing(
        self,
        card_id: str,
        provider: str,
        model: str,
        input_rate: float,
        output_rate: float,
        cache_read_rate: float = 0.0,
        cache_write_rate: float = 0.0,
        request_rate: float = 0.0,
    ) -> RateCard:
        """Add or update per-token pricing for a provider+model on a rate card."""
        card = self.store.get_rate_card(card_id)
        if not card:
            raise ValueError(f"Rate card '{card_id}' not found.")
        if input_rate < 0 or output_rate < 0 or cache_read_rate < 0 or cache_write_rate < 0 or request_rate < 0:
            raise ValueError("Pricing rates cannot be negative.")
        pricing = ModelPricing(
            input_rate=input_rate,
            output_rate=output_rate,
            cache_read_rate=cache_read_rate,
            cache_write_rate=cache_write_rate,
            request_rate=request_rate,
        )
        card.set_pricing(provider=provider, model=model, pricing=pricing)
        return self.store.save_rate_card(card)

    def remove_model_pricing(self, card_id: str, provider: str, model: str) -> RateCard:
        """Remove pricing for a provider+model from a rate card."""
        card = self.store.get_rate_card(card_id)
        if not card:
            raise ValueError(f"Rate card '{card_id}' not found.")
        if not card.remove_pricing(provider=provider, model=model):
            raise ValueError(f"No pricing found for {provider}:{model}.")
        return self.store.save_rate_card(card)

    def calculate_usage_cost(
        self,
        card_id: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_count: int = 1,
    ) -> Optional[float]:
        """Calculate cost for usage against a rate card. Returns None if no pricing."""
        card = self.store.get_rate_card(card_id)
        if not card:
            raise ValueError(f"Rate card '{card_id}' not found.")
        return card.calculate_cost(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            request_count=request_count,
        )

    def record_usage_with_rate_card(
        self,
        card_id: str,
        description: str,
        provider: str,
        model: str,
        client_identifier: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_count: int = 1,
        metadata: Optional[dict] = None,
    ) -> UsageEvent:
        """Record a usage event with cost auto-calculated from a rate card.

        This is the key workflow: agent provides tokens + provider/model, the
        rate card computes the cost. No manual cost entry needed.

        Raises ValueError if the rate card has no pricing for provider+model.
        """
        card = self.store.get_rate_card(card_id)
        if not card:
            raise ValueError(f"Rate card '{card_id}' not found.")
        cost = card.calculate_cost(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            request_count=request_count,
        )
        if cost is None:
            raise ValueError(
                f"Rate card '{card.name}' has no pricing for {provider}:{model}. "
                f"Use add_model_pricing to set it."
            )
        return self.record_usage(
            description=description,
            cost=cost,
            client_identifier=client_identifier,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            request_count=request_count,
            currency=card.currency,
            metadata=metadata or {},
        )

    def batch_record_usage(
        self,
        events: list[dict],
        card_id: Optional[str] = None,
    ) -> BatchUsageResult:
        """Record multiple usage events in one call.

        Each event dict: {description, provider, model, input_tokens,
        output_tokens?, cache_read_tokens?, cache_write_tokens?,
        request_count?, client?, cost?, metadata?}

        If card_id is provided, cost is auto-calculated per event (overrides
        any explicit cost). Otherwise each event must include 'cost'.

        Returns a BatchUsageResult with totals, per-event IDs, and any errors.
        """
        if not events:
            raise ValueError("No events provided.")
        card = None
        if card_id:
            card = self.store.get_rate_card(card_id)
            if not card:
                raise ValueError(f"Rate card '{card_id}' not found.")

        result = BatchUsageResult()
        if card:
            result.currency = card.currency

        for i, ev in enumerate(events):
            try:
                provider = ev["provider"]
                model = ev["model"]
                description = ev.get("description", f"{provider}/{model} usage")
                input_tokens = int(ev.get("input_tokens", 0))
                output_tokens = int(ev.get("output_tokens", 0))
                cache_read_tokens = int(ev.get("cache_read_tokens", 0))
                cache_write_tokens = int(ev.get("cache_write_tokens", 0))
                request_count = int(ev.get("request_count", 1))

                if card:
                    cost = card.calculate_cost(
                        provider=provider,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_write_tokens=cache_write_tokens,
                        request_count=request_count,
                    )
                    if cost is None:
                        raise ValueError(
                            f"No pricing for {provider}:{model} on card '{card.name}'."
                        )
                    currency = card.currency
                else:
                    if "cost" not in ev:
                        raise ValueError(
                            f"Event {i} has no 'cost' and no card_id provided."
                        )
                    cost = float(ev["cost"])
                    currency = (ev.get("currency") or "USD").upper()

                event = self.record_usage(
                    description=description,
                    cost=cost,
                    client_identifier=ev.get("client"),
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    request_count=request_count,
                    currency=currency,
                    metadata=ev.get("metadata"),
                )
                result.event_ids.append(event.id)
                result.total_recorded += 1
                result.total_cost = round(result.total_cost + cost, 6)
            except (ValueError, KeyError) as e:
                result.total_failed += 1
                result.errors.append({"index": i, "error": str(e)})

        return result

    # ===================================================================
    # v1.0.0 — Subscription Plans
    # ===================================================================

    def create_plan(
        self,
        name: str,
        price: float,
        currency: str = "USD",
        billing_cycle: str = "monthly",
        description: Optional[str] = None,
        trial_days: int = 0,
        tax_rate: float = 0.0,
        due_days: int = 15,
        active: bool = True,
        quota_requests: Optional[int] = None,
        quota_tokens: Optional[int] = None,
        overage_rate: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> SubscriptionPlan:
        """Create a reusable subscription plan.

        Args:
            name: Plan name (e.g. "Pro Agent").
            price: Price per billing cycle.
            currency: ISO currency code.
            billing_cycle: daily, weekly, monthly, quarterly, yearly.
            trial_days: Free trial length (0 = no trial).
            tax_rate: Tax percentage.
            due_days: Days after generation that invoices are due.
            active: Whether the plan is available for new subscriptions.
            quota_requests: Max API requests per period (optional).
            quota_tokens: Max tokens per period (optional).
            overage_rate: $ per unit over quota (optional).
            metadata: Arbitrary tags.

        Returns:
            The created SubscriptionPlan.
        """
        if not name or not name.strip():
            raise ValueError("Plan name is required.")
        cycle = BillingCycle(billing_cycle.lower()) if isinstance(billing_cycle, str) else billing_cycle
        plan = SubscriptionPlan(
            name=name.strip(),
            price=price,
            currency=(currency or "USD").upper(),
            billing_cycle=cycle,
            description=description,
            trial_days=trial_days,
            tax_rate=tax_rate,
            due_days=due_days,
            active=active,
            quota_requests=quota_requests,
            quota_tokens=quota_tokens,
            overage_rate=overage_rate,
            metadata=metadata or {},
        )
        return self.store.save_plan(plan)

    def get_plan(self, plan_id: str) -> Optional[SubscriptionPlan]:
        """Get a subscription plan by ID."""
        return self.store.get_plan(plan_id)

    def list_plans(self, active_only: bool = False) -> list[SubscriptionPlan]:
        """List subscription plans, optionally filtered to active."""
        return self.store.list_plans(active_only=active_only)

    def update_plan(self, plan_id: str, **updates) -> SubscriptionPlan:
        """Update a plan's mutable fields. Price, name, tax, quotas, active, etc."""
        plan = self.store.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found.")
        if "name" in updates:
            if not str(updates["name"]).strip():
                raise ValueError("Plan name cannot be empty.")
            plan.name = str(updates["name"]).strip()
        if "price" in updates:
            plan.price = float(updates["price"])
            if plan.price < 0:
                raise ValueError("Plan price cannot be negative.")
        if "currency" in updates:
            plan.currency = str(updates["currency"]).upper()
        if "billing_cycle" in updates:
            plan.billing_cycle = BillingCycle(updates["billing_cycle"].lower())
        if "description" in updates:
            plan.description = updates["description"]
        if "trial_days" in updates:
            plan.trial_days = int(updates["trial_days"])
        if "tax_rate" in updates:
            plan.tax_rate = float(updates["tax_rate"])
        if "due_days" in updates:
            plan.due_days = int(updates["due_days"])
        if "quota_requests" in updates:
            plan.quota_requests = updates["quota_requests"]
        if "quota_tokens" in updates:
            plan.quota_tokens = updates["quota_tokens"]
        if "overage_rate" in updates:
            plan.overage_rate = updates["overage_rate"]
        if "active" in updates:
            plan.active = bool(updates["active"])
        if "metadata" in updates:
            plan.metadata = updates["metadata"]
        plan.updated_at = datetime.now(tz=timezone.utc)
        return self.store.save_plan(plan)

    def remove_plan(self, plan_id: str) -> bool:
        """Delete a plan. Active subscriptions referencing it are unaffected."""
        return self.store.delete_plan(plan_id)

    def seed_builtin_plans(self, overwrite: bool = False) -> list[SubscriptionPlan]:
        """Create the built-in agent subscription plans (Starter/Pro/Enterprise).

        Args:
            overwrite: If True, replace existing plans with the same IDs.

        Returns:
            List of created (or existing) plans.
        """
        created = []
        for entry in BUILTIN_PLANS:
            existing = self.store.get_plan(entry["id"])
            if existing and not overwrite:
                created.append(existing)
                continue
            plan = SubscriptionPlan(
                id=entry["id"],
                name=entry["name"],
                description=entry.get("description"),
                price=entry["price"],
                currency=entry.get("currency", "USD"),
                billing_cycle=BillingCycle(entry.get("billing_cycle", "monthly")),
                trial_days=entry.get("trial_days", 0),
                quota_requests=entry.get("quota_requests"),
                quota_tokens=entry.get("quota_tokens"),
            )
            created.append(self.store.save_plan(plan))
        return created

    # ===================================================================
    # v1.0.0 — Subscriptions (recurring billing lifecycle)
    # ===================================================================

    def create_subscription(
        self,
        client_identifier: str,
        plan_id: str,
        start_date: Optional[date] = None,
        metadata: Optional[dict] = None,
    ) -> Subscription:
        """Subscribe a client to a plan.

        Initializes trial if the plan has trial days. If no trial, the
        subscription is active and immediately billable.

        Args:
            client_identifier: Client ID or name.
            plan_id: The plan to subscribe to.
            start_date: Subscription start (defaults to today).
            metadata: Arbitrary tags.

        Returns:
            The created Subscription.
        """
        client = self.get_client(client_identifier)
        if not client:
            raise ValueError(f"Client '{client_identifier}' not found.")
        plan = self.store.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found.")
        if not plan.active:
            raise ValueError(f"Plan '{plan.name}' is not active.")

        sub = Subscription(
            client_id=client.id,
            client_name=client.name,
            plan_id=plan.id,
            plan_name=plan.name,
            price=plan.price,
            currency=plan.currency,
            billing_cycle=plan.billing_cycle,
            tax_rate=plan.tax_rate,
            due_days=plan.due_days,
            trial_days=plan.trial_days,
            start_date=start_date or date.today(),
            metadata=metadata or {},
        )
        sub.init_trial()
        return self.store.save_subscription(sub)

    def get_subscription(self, sub_id: str) -> Optional[Subscription]:
        """Get a subscription by ID."""
        return self.store.get_subscription(sub_id)

    def list_subscriptions(
        self,
        client_identifier: Optional[str] = None,
        plan_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[Subscription]:
        """List subscriptions with optional filters."""
        client_id = None
        if client_identifier:
            c = self.get_client(client_identifier)
            if c:
                client_id = c.id
        status_enum = None
        if status:
            status_enum = SubscriptionStatus(status.lower())
        return self.store.list_subscriptions(
            client_id=client_id,
            plan_id=plan_id,
            status=status_enum,
        )

    def cancel_subscription(self, sub_id: str, immediately: bool = False) -> Subscription:
        """Cancel a subscription. If not immediate, stays active until period end."""
        sub = self.store.get_subscription(sub_id)
        if not sub:
            raise ValueError(f"Subscription '{sub_id}' not found.")
        if sub.status == SubscriptionStatus.CANCELLED:
            raise ValueError(f"Subscription '{sub_id}' is already cancelled.")
        sub.cancel(immediately=immediately)
        return self.store.save_subscription(sub)

    def pause_subscription(self, sub_id: str) -> Subscription:
        """Pause a subscription. Billing resumes on resume."""
        sub = self.store.get_subscription(sub_id)
        if not sub:
            raise ValueError(f"Subscription '{sub_id}' not found.")
        sub.pause()
        return self.store.save_subscription(sub)

    def resume_subscription(self, sub_id: str) -> Subscription:
        """Resume a paused subscription."""
        sub = self.store.get_subscription(sub_id)
        if not sub:
            raise ValueError(f"Subscription '{sub_id}' not found.")
        sub.resume()
        return self.store.save_subscription(sub)

    def remove_subscription(self, sub_id: str) -> bool:
        """Delete a subscription record. Does NOT cancel invoices already issued."""
        return self.store.delete_subscription(sub_id)

    def generate_subscription_invoice(self, sub_id: str) -> Invoice:
        """Generate an invoice for a subscription's current billing period.

        Only billable subscriptions (active or past_due) can be invoiced.
        After generating, the subscription advances to the next period.

        Args:
            sub_id: The subscription to bill.

        Returns:
            The generated Invoice.
        """
        sub = self.store.get_subscription(sub_id)
        if not sub:
            raise ValueError(f"Subscription '{sub_id}' not found.")
        if not sub.is_billable:
            raise ValueError(
                f"Subscription '{sub_id}' is {sub.status.value} — only active "
                f"or past_due subscriptions can be invoiced."
            )

        line_items = [
            {
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "tax_rate": li.tax_rate,
            }
            for li in sub.generate_line_items()
        ]
        inv = self.create_invoice(
            client_identifier=sub.client_id,
            line_items=line_items,
            due_days=sub.due_days,
            currency=sub.currency,
            notes=f"Subscription billing: {sub.plan_name} "
                  f"({sub.current_period_start} to {sub.current_period_end})",
        )
        sub.last_invoice_id = inv.id
        sub.invoice_ids.append(inv.id)
        sub.advance_period()
        self.store.save_subscription(sub)
        return inv

    def process_due_subscriptions(self, as_of: Optional[date] = None) -> list[Invoice]:
        """Generate invoices for all subscriptions due for billing.

        A subscription is due if it's billable and next_billing_date <= as_of.

        Args:
            as_of: Cutoff date (defaults to today).

        Returns:
            List of generated invoices.
        """
        as_of = as_of or date.today()
        generated = []
        for sub in self.store.list_subscriptions():
            if not sub.is_billable:
                continue
            if sub.next_billing_date is None:
                continue
            if sub.next_billing_date <= as_of:
                try:
                    inv = self.generate_subscription_invoice(sub.id)
                    generated.append(inv)
                except ValueError:
                    # Skip subs that error out (e.g. no client)
                    continue
        return generated

    def get_mrr_summary(self, currency: Optional[str] = None) -> MRRSummary:
        """Compute Monthly Recurring Revenue summary across all subscriptions.

        Args:
            currency: Filter to a specific currency.

        Returns:
            MRRSummary with counts, MRR, ARR, and breakdowns.
        """
        subs = self.store.list_subscriptions()
        if currency:
            currency = currency.upper()
            subs = [s for s in subs if s.currency == currency]
        summary_currency = currency or "USD"

        active = [s for s in subs if s.status == SubscriptionStatus.ACTIVE]
        trialing = [s for s in subs if s.status == SubscriptionStatus.TRIALING]
        past_due = [s for s in subs if s.status == SubscriptionStatus.PAST_DUE]
        paused = [s for s in subs if s.status == SubscriptionStatus.PAUSED]
        cancelled = [s for s in subs if s.status == SubscriptionStatus.CANCELLED]

        mrr = round(sum(s.monthly_revenue for s in active + past_due), 2)
        trial_mrr = round(sum(s.monthly_revenue for s in trialing), 2)
        paused_mrr = round(sum(s.monthly_revenue for s in paused), 2)

        billable = active + past_due
        avg_value = round(mrr / len(billable), 2) if billable else 0.0

        # By plan
        plan_map: dict[str, dict] = {}
        for s in billable:
            key = s.plan_id
            if key not in plan_map:
                plan_map[key] = {
                    "plan_id": s.plan_id,
                    "plan_name": s.plan_name or s.plan_id,
                    "count": 0,
                    "mrr": 0.0,
                }
            plan_map[key]["count"] += 1
            plan_map[key]["mrr"] = round(plan_map[key]["mrr"] + s.monthly_revenue, 2)

        # By billing cycle
        cycle_map: dict[str, dict] = {}
        for s in billable:
            key = s.billing_cycle.value
            if key not in cycle_map:
                cycle_map[key] = {"cycle": key, "count": 0, "mrr": 0.0}
            cycle_map[key]["count"] += 1
            cycle_map[key]["mrr"] = round(cycle_map[key]["mrr"] + s.monthly_revenue, 2)

        # Top clients by MRR
        client_map: dict[str, dict] = {}
        for s in billable:
            key = s.client_id
            if key not in client_map:
                client_map[key] = {
                    "client_id": s.client_id,
                    "client_name": s.client_name or s.client_id,
                    "plan_name": s.plan_name,
                    "mrr": 0.0,
                }
            client_map[key]["mrr"] = round(client_map[key]["mrr"] + s.monthly_revenue, 2)
        top_clients = sorted(
            client_map.values(), key=lambda c: c["mrr"], reverse=True
        )[:10]

        return MRRSummary(
            currency=summary_currency,
            active_count=len(active),
            trialing_count=len(trialing),
            past_due_count=len(past_due),
            paused_count=len(paused),
            cancelled_count=len(cancelled),
            total_count=len(subs),
            mrr=mrr,
            arr=round(mrr * 12, 2),
            trial_mrr=trial_mrr,
            paused_mrr=paused_mrr,
            lost_mrr=0.0,
            by_plan=sorted(plan_map.values(), key=lambda p: p["mrr"], reverse=True),
            by_cycle=sorted(cycle_map.values(), key=lambda c: c["mrr"], reverse=True),
            top_clients=top_clients,
            avg_subscription_value=avg_value,
        )
