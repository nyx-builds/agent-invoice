"""Data models for Agent Invoice."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    PARTIALLY_PAID = "partially_paid"


class RecurrenceFrequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


# Currency definitions with symbol and decimal places
CURRENCIES: dict[str, dict] = {
    "USD": {"symbol": "$", "name": "US Dollar", "decimals": 2},
    "EUR": {"symbol": "€", "name": "Euro", "decimals": 2},
    "GBP": {"symbol": "£", "name": "British Pound", "decimals": 2},
    "JPY": {"symbol": "¥", "name": "Japanese Yen", "decimals": 0},
    "CAD": {"symbol": "C$", "name": "Canadian Dollar", "decimals": 2},
    "AUD": {"symbol": "A$", "name": "Australian Dollar", "decimals": 2},
    "CHF": {"symbol": "CHF", "name": "Swiss Franc", "decimals": 2},
    "CNY": {"symbol": "¥", "name": "Chinese Yuan", "decimals": 2},
    "INR": {"symbol": "₹", "name": "Indian Rupee", "decimals": 2},
    "BRL": {"symbol": "R$", "name": "Brazilian Real", "decimals": 2},
    "KRW": {"symbol": "₩", "name": "South Korean Won", "decimals": 0},
    "MXN": {"symbol": "MX$", "name": "Mexican Peso", "decimals": 2},
    "SGD": {"symbol": "S$", "name": "Singapore Dollar", "decimals": 2},
    "SEK": {"symbol": "kr", "name": "Swedish Krona", "decimals": 2},
    "NZD": {"symbol": "NZ$", "name": "New Zealand Dollar", "decimals": 2},
}


def get_currency_symbol(currency: str) -> str:
    """Get the symbol for a currency code."""
    info = CURRENCIES.get(currency.upper())
    return info["symbol"] if info else currency


def format_amount(amount: float, currency: str = "USD") -> str:
    """Format an amount with the appropriate currency symbol and decimal places."""
    info = CURRENCIES.get(currency.upper(), {"symbol": currency, "decimals": 2})
    decimals = info["decimals"]
    symbol = info["symbol"]
    return f"{symbol}{amount:,.{decimals}f}"


class Payment(BaseModel):
    """A payment applied to an invoice."""

    id: str = Field(default_factory=lambda: f"PMT-{uuid.uuid4().hex[:6].upper()}")
    amount: float
    method: Optional[str] = None  # e.g. "bank_transfer", "credit_card", "crypto", "cash"
    reference: Optional[str] = None  # External payment reference / transaction ID
    notes: Optional[str] = None
    payment_date: date = Field(default_factory=date.today)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class LineItem(BaseModel):
    """A single line item on an invoice."""

    description: str
    quantity: float = 1.0
    unit_price: float
    tax_rate: float = 0.0  # Tax rate as percentage (e.g. 8.5 for 8.5%)
    total: Optional[float] = None
    tax_amount: Optional[float] = None

    def model_post_init(self, __context: object) -> None:
        if self.total is None:
            self.total = round(self.quantity * self.unit_price, 2)
        if self.tax_amount is None and self.tax_rate > 0:
            self.tax_amount = round(self.total * self.tax_rate / 100, 2)

    @property
    def total_with_tax(self) -> float:
        return round(self.total + (self.tax_amount or 0), 2)


class Client(BaseModel):
    """A client that can be billed."""

    id: str = Field(default_factory=lambda: f"CLT-{uuid.uuid4().hex[:8].upper()}")
    name: str
    email: Optional[str] = None
    address: Optional[str] = None
    currency: str = "USD"  # Default billing currency
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class Invoice(BaseModel):
    """An invoice for work completed."""

    id: str = Field(default_factory=lambda: f"INV-{uuid.uuid4().hex[:6].upper()}")
    client_id: str
    client_name: Optional[str] = None
    line_items: list[LineItem] = []
    payments: list[Payment] = []
    status: InvoiceStatus = InvoiceStatus.DRAFT
    issue_date: date = Field(default_factory=date.today)
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None
    currency: str = "USD"
    tax_rate: float = 0.0  # Invoice-level tax rate applied to items without their own tax
    discount_amount: float = 0.0  # Flat discount amount
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def subtotal(self) -> float:
        return round(sum(item.total or 0 for item in self.line_items), 2)

    @property
    def total_tax(self) -> float:
        """Total tax across all line items."""
        return round(sum(item.tax_amount or 0 for item in self.line_items), 2)

    @property
    def total(self) -> float:
        """Grand total: subtotal + tax - discount."""
        return round(self.subtotal + self.total_tax - self.discount_amount, 2)

    @property
    def amount_paid(self) -> float:
        """Total amount paid across all payments."""
        return round(sum(p.amount for p in self.payments), 2)

    @property
    def amount_remaining(self) -> float:
        """Amount still owed on this invoice."""
        return round(self.total - self.amount_paid, 2)

    @property
    def is_overdue(self) -> bool:
        if self.due_date and self.status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
            return date.today() > self.due_date
        return False

    def set_due_date(self, days: int) -> None:
        self.due_date = date.today() + timedelta(days=days)

    def add_payment(self, payment: Payment) -> None:
        """Add a payment and update invoice status accordingly."""
        self.payments.append(payment)
        self.updated_at = datetime.now(tz=timezone.utc)
        # Update status based on payment
        if self.amount_remaining <= 0:
            self.status = InvoiceStatus.PAID
            self.paid_date = date.today()
        elif self.amount_paid > 0:
            self.status = InvoiceStatus.PARTIALLY_PAID

    def remove_payment(self, payment_id: str) -> bool:
        """Remove a payment by ID. Returns True if found and removed."""
        for i, p in enumerate(self.payments):
            if p.id == payment_id:
                self.payments.pop(i)
                self.updated_at = datetime.now(tz=timezone.utc)
                # Recalculate status
                if self.amount_paid == 0:
                    self.status = InvoiceStatus.DRAFT
                    self.paid_date = None
                elif self.amount_remaining <= 0:
                    self.status = InvoiceStatus.PAID
                    self.paid_date = date.today()
                else:
                    self.status = InvoiceStatus.PARTIALLY_PAID
                    self.paid_date = None
                return True
        return False

    def mark_paid(self) -> None:
        self.status = InvoiceStatus.PAID
        self.paid_date = date.today()
        self.updated_at = datetime.now(tz=timezone.utc)

    def mark_sent(self) -> None:
        self.status = InvoiceStatus.SENT
        self.updated_at = datetime.now(tz=timezone.utc)

    def check_overdue(self) -> None:
        if self.is_overdue and self.status in (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID):
            self.status = InvoiceStatus.OVERDUE
            self.updated_at = datetime.now(tz=timezone.utc)

    def to_markdown(self) -> str:
        """Export invoice as markdown."""
        sym = get_currency_symbol(self.currency)
        lines = [
            f"# Invoice {self.id}",
            "",
            f"**Client:** {self.client_name or self.client_id}",
            f"**Status:** {self.status.value.upper()}",
            f"**Currency:** {self.currency}",
            f"**Issue Date:** {self.issue_date}",
            f"**Due Date:** {self.due_date or 'N/A'}",
            "",
            "## Line Items",
            "",
            "| Description | Qty | Unit Price | Tax % | Tax | Total |",
            "|---|---|---|---|---|---|",
        ]
        for item in self.line_items:
            tax_pct = f"{item.tax_rate}%" if item.tax_rate > 0 else "—"
            tax_amt = f"{sym}{item.tax_amount:.2f}" if item.tax_amount else "—"
            lines.append(
                f"| {item.description} | {item.quantity} | {sym}{item.unit_price:.2f} | {tax_pct} | {tax_amt} | {sym}{item.total:.2f} |"
            )
        lines.append("")
        lines.append(f"**Subtotal: {sym}{self.subtotal:.2f}**")
        if self.total_tax > 0:
            lines.append(f"**Tax: {sym}{self.total_tax:.2f}**")
        if self.discount_amount > 0:
            lines.append(f"**Discount: -{sym}{self.discount_amount:.2f}**")
        lines.append(f"**Total: {sym}{self.total:.2f}**")

        # Payments section
        if self.payments:
            lines.append("")
            lines.append("## Payments")
            lines.append("")
            lines.append("| Date | Amount | Method | Reference |")
            lines.append("|---|---|---|---|")
            for p in self.payments:
                method = p.method or "—"
                ref = p.reference or "—"
                lines.append(f"| {p.payment_date} | {sym}{p.amount:.2f} | {method} | {ref} |")
            lines.append("")
            lines.append(f"**Amount Paid: {sym}{self.amount_paid:.2f}**")
            lines.append(f"**Amount Remaining: {sym}{self.amount_remaining:.2f}**")

        if self.notes:
            lines.append("")
            lines.append(f"**Notes:** {self.notes}")
        if self.paid_date:
            lines.append("")
            lines.append(f"**Paid on:** {self.paid_date}")
        return "\n".join(lines)


class RecurringInvoice(BaseModel):
    """A recurring invoice template that generates invoices on a schedule."""

    id: str = Field(default_factory=lambda: f"REC-{uuid.uuid4().hex[:6].upper()}")
    client_id: str
    client_name: Optional[str] = None
    line_items: list[LineItem] = []
    frequency: RecurrenceFrequency = RecurrenceFrequency.MONTHLY
    currency: str = "USD"
    tax_rate: float = 0.0
    discount_amount: float = 0.0
    due_days: int = 30
    notes: Optional[str] = None
    active: bool = True
    next_date: Optional[date] = None  # Next date to generate an invoice
    last_generated: Optional[date] = None
    invoice_ids: list[str] = []  # IDs of generated invoices
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def subtotal(self) -> float:
        return round(sum(item.total or 0 for item in self.line_items), 2)

    @property
    def total_tax(self) -> float:
        return round(sum(item.tax_amount or 0 for item in self.line_items), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.total_tax - self.discount_amount, 2)

    def compute_next_date(self, from_date: Optional[date] = None) -> date:
        """Compute the next invoice date based on frequency."""
        base = from_date or self.next_date or date.today()
        freq_map = {
            RecurrenceFrequency.WEEKLY: timedelta(weeks=1),
            RecurrenceFrequency.BIWEEKLY: timedelta(weeks=2),
            RecurrenceFrequency.MONTHLY: timedelta(days=30),  # approximate
            RecurrenceFrequency.QUARTERLY: timedelta(days=90),
            RecurrenceFrequency.YEARLY: timedelta(days=365),
        }
        delta = freq_map[self.frequency]
        return base + delta

    def generate_invoice(self, invoice_id: str) -> Invoice:
        """Generate an Invoice from this recurring template."""
        invoice = Invoice(
            id=invoice_id,
            client_id=self.client_id,
            client_name=self.client_name,
            line_items=[item.model_copy() for item in self.line_items],
            status=InvoiceStatus.DRAFT,
            currency=self.currency,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            notes=self.notes,
        )
        invoice.set_due_date(self.due_days)
        self.last_generated = date.today()
        self.next_date = self.compute_next_date()
        self.invoice_ids.append(invoice_id)
        self.updated_at = datetime.now(tz=timezone.utc)
        return invoice


class NumberingConfig(BaseModel):
    """Configuration for invoice numbering."""

    prefix: str = "INV"
    separator: str = "-"
    digits: int = 4
    next_number: int = 1

    def format_number(self, number: Optional[int] = None) -> str:
        """Format an invoice number using the configured template."""
        n = number if number is not None else self.next_number
        return f"{self.prefix}{self.separator}{n:0{self.digits}d}"

    def advance(self) -> str:
        """Get the next number and advance the counter."""
        num = self.format_number()
        self.next_number += 1
        return num


class InvoiceTemplate(BaseModel):
    """A reusable invoice template for quick invoice creation."""

    id: str = Field(default_factory=lambda: f"TPL-{uuid.uuid4().hex[:6].upper()}")
    name: str
    description: Optional[str] = None
    line_items: list[LineItem] = []
    tax_rate: float = 0.0
    discount_amount: float = 0.0
    due_days: int = 30
    currency: str = "USD"
    notes: Optional[str] = None
    category: Optional[str] = None  # e.g. "consulting", "retainer", "project"
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def subtotal(self) -> float:
        return round(sum(item.total or 0 for item in self.line_items), 2)

    @property
    def total_tax(self) -> float:
        return round(sum(item.tax_amount or 0 for item in self.line_items), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.total_tax - self.discount_amount, 2)


# Built-in invoice templates
BUILTIN_TEMPLATES: list[dict] = [
    {
        "id": "TPL-HOURLY",
        "name": "Hourly Consulting",
        "description": "Standard hourly consulting engagement",
        "category": "consulting",
        "line_items": [
            {"description": "Consulting hours", "quantity": 1, "unit_price": 150.0},
        ],
        "tax_rate": 0.0,
        "due_days": 30,
        "currency": "USD",
    },
    {
        "id": "TPL-RETAINER",
        "name": "Monthly Retainer",
        "description": "Monthly retainer for ongoing services",
        "category": "retainer",
        "line_items": [
            {"description": "Monthly retainer", "quantity": 1, "unit_price": 2000.0},
        ],
        "tax_rate": 0.0,
        "due_days": 15,
        "currency": "USD",
    },
    {
        "id": "TPL-PROJECT",
        "name": "Fixed-Price Project",
        "description": "Fixed-price project with milestone payments",
        "category": "project",
        "line_items": [
            {"description": "Project delivery", "quantity": 1, "unit_price": 5000.0},
        ],
        "tax_rate": 0.0,
        "due_days": 30,
        "currency": "USD",
    },
    {
        "id": "TPL-SUPPORT",
        "name": "Support & Maintenance",
        "description": "Monthly support and maintenance package",
        "category": "support",
        "line_items": [
            {"description": "Support & maintenance", "quantity": 1, "unit_price": 500.0},
        ],
        "tax_rate": 0.0,
        "due_days": 30,
        "currency": "USD",
    },
    {
        "id": "TPL-DEV",
        "name": "Development Sprint",
        "description": "Two-week development sprint",
        "category": "development",
        "line_items": [
            {"description": "Development sprint (2 weeks)", "quantity": 1, "unit_price": 4000.0},
        ],
        "tax_rate": 0.0,
        "due_days": 14,
        "currency": "USD",
    },
]


class DunningLevel(str, Enum):
    """Escalation levels for dunning reminders."""
    FIRST_REMINDER = "first_reminder"
    SECOND_REMINDER = "second_reminder"
    FINAL_NOTICE = "final_notice"


class DunningAction(BaseModel):
    """A dunning action/reminder sent for an overdue invoice."""
    id: str = Field(default_factory=lambda: f"DUN-{uuid.uuid4().hex[:6].upper()}")
    invoice_id: str
    level: DunningLevel
    message: Optional[str] = None
    sent_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    days_overdue: int = 0


class DunningConfig(BaseModel):
    """Configuration for dunning (overdue reminder) automation."""
    first_reminder_days: int = 7   # Send first reminder N days after due date
    second_reminder_days: int = 14  # Send second reminder N days after due date
    final_notice_days: int = 30    # Send final notice N days after due date
    enabled: bool = True

    def get_level_for_days_overdue(self, days_overdue: int) -> Optional[DunningLevel]:
        """Determine which dunning level applies for a given number of days overdue."""
        if days_overdue >= self.final_notice_days:
            return DunningLevel.FINAL_NOTICE
        elif days_overdue >= self.second_reminder_days:
            return DunningLevel.SECOND_REMINDER
        elif days_overdue >= self.first_reminder_days:
            return DunningLevel.FIRST_REMINDER
        return None

    def get_message_for_level(self, level: DunningLevel, invoice_id: str, days_overdue: int, amount: float, currency: str = "USD") -> str:
        """Get a default dunning message for a given level."""
        sym = get_currency_symbol(currency)
        messages = {
            DunningLevel.FIRST_REMINDER: (
                f"Reminder: Invoice {invoice_id} is {days_overdue} days overdue. "
                f"Amount due: {sym}{amount:,.2f}. Please submit payment at your earliest convenience."
            ),
            DunningLevel.SECOND_REMINDER: (
                f"Second Notice: Invoice {invoice_id} is now {days_overdue} days overdue. "
                f"Amount due: {sym}{amount:,.2f}. Please remit payment immediately to avoid further action."
            ),
            DunningLevel.FINAL_NOTICE: (
                f"FINAL NOTICE: Invoice {invoice_id} is {days_overdue} days overdue. "
                f"Amount due: {sym}{amount:,.2f}. This is our final notice before escalating collection efforts."
            ),
        }
        return messages.get(level, "")


class CreditNoteStatus(str, Enum):
    """Status for a credit note."""
    OPEN = "open"       # Available to apply
    APPLIED = "applied" # Fully applied to invoices
    VOID = "void"       # Cancelled


class CreditNote(BaseModel):
    """A credit note that can be applied to invoices or issued standalone (refunds/credits)."""
    id: str = Field(default_factory=lambda: f"CN-{uuid.uuid4().hex[:6].upper()}")
    client_id: str
    client_name: Optional[str] = None
    invoice_id: Optional[str] = None  # Original invoice this credit relates to (if any)
    amount: float
    currency: str = "USD"
    status: CreditNoteStatus = CreditNoteStatus.OPEN
    reason: Optional[str] = None  # e.g. "overpayment", "refund", "billing error"
    issue_date: date = Field(default_factory=date.today)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    # Applications: list of (invoice_id, amount) where this credit was applied
    applications: list[dict] = []  # [{"invoice_id": "...", "amount": 100.00, "applied_at": "2026-..."}]

    @property
    def applied_amount(self) -> float:
        """Total amount already applied to invoices."""
        return round(sum(a["amount"] for a in self.applications), 2)

    @property
    def remaining_amount(self) -> float:
        """Credit amount still available to apply."""
        return round(self.amount - self.applied_amount, 2)

    def apply(self, invoice_id: str, amount: float) -> None:
        """Apply a portion of this credit to an invoice."""
        amount = round(amount, 2)
        if amount <= 0:
            raise ValueError("Application amount must be positive.")
        if amount > self.remaining_amount + 0.01:
            raise ValueError(
                f"Application amount ({amount}) exceeds remaining credit ({self.remaining_amount})."
            )
        self.applications.append({
            "invoice_id": invoice_id,
            "amount": amount,
            "applied_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(tz=timezone.utc)
        if self.remaining_amount <= 0.01:
            self.status = CreditNoteStatus.APPLIED


class ClientStatement(BaseModel):
    """A financial statement for a client over a period — invoices, payments, credits, and balances."""
    client_id: str
    client_name: Optional[str] = None
    currency: str = "USD"
    period_start: date
    period_end: date

    # Opening balance (carried forward debt/credit before period start)
    opening_balance: float = 0.0  # Positive = client owes you; negative = credit in their favor

    # Activity during the period
    invoices: list[dict] = []  # [{"id": "...", "issue_date": "...", "total": 100.00, "status": "paid"}]
    payments: list[dict] = []  # [{"id": "...", "invoice_id": "...", "amount": 100.00, "date": "..."}]
    credit_notes: list[dict] = []  # [{"id": "...", "amount": 50.00, "reason": "refund", "date": "..."}]

    # Totals during the period
    total_invoiced: float = 0.0
    total_paid: float = 0.0
    total_credits: float = 0.0

    # Closing balance
    closing_balance: float = 0.0  # Positive = client owes; negative = credit in their favor

    @property
    def balance_due(self) -> float:
        """Amount the client currently owes (positive) or credit available (negative)."""
        return self.closing_balance


class EarningsSummary(BaseModel):
    """Summary of earnings across all invoices."""

    total_invoiced: float = 0.0
    total_paid: float = 0.0
    total_pending: float = 0.0
    total_overdue: float = 0.0
    total_tax: float = 0.0
    total_discounts: float = 0.0
    total_payments: float = 0.0
    invoice_count: int = 0
    paid_count: int = 0
    pending_count: int = 0
    overdue_count: int = 0
    partially_paid_count: int = 0
    currency: str = "USD"
