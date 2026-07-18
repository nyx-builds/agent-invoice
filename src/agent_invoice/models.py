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


# ---------------------------------------------------------------------------
# A/R (Accounts Receivable) Aging
# ---------------------------------------------------------------------------

class ARAgingBucket(BaseModel):
    """A single aging bucket (e.g. 0-30 days)."""

    label: str  # e.g. "0-30", "31-60", "61-90", "90+"
    days_low: int  # inclusive lower bound
    days_high: Optional[int]  # inclusive upper bound, None for "90+"
    invoice_count: int = 0
    total_outstanding: float = 0.0


class ClientARAging(BaseModel):
    """A/R aging breakdown for a single client."""

    client_id: str
    client_name: Optional[str] = None
    total_outstanding: float = 0.0
    buckets: list[ARAgingBucket] = []
    invoice_details: list[dict] = []  # [{id, total, amount_remaining, days_overdue, bucket}]


class ARAgingReport(BaseModel):
    """Full A/R aging report across all clients with outstanding balances."""

    as_of_date: date
    currency: Optional[str] = None  # None = all currencies
    total_outstanding: float = 0.0
    client_count: int = 0
    bucket_totals: list[ARAgingBucket] = []
    clients: list[ClientARAging] = []


# ---------------------------------------------------------------------------
# Revenue Analytics
# ---------------------------------------------------------------------------

class MonthlyRevenue(BaseModel):
    """Revenue data for a single month."""

    period: str  # "YYYY-MM"
    invoiced: float = 0.0
    collected: float = 0.0  # payments received that month
    outstanding: float = 0.0  # still-unpaid invoices issued that month
    invoice_count: int = 0
    paid_invoice_count: int = 0
    avg_invoice_value: float = 0.0


class RevenueAnalytics(BaseModel):
    """Revenue analytics over a period."""

    currency: str = "USD"
    period_start: str = ""
    period_end: str = ""
    months: list[MonthlyRevenue] = []
    total_invoiced: float = 0.0
    total_collected: float = 0.0
    avg_days_to_pay: float = 0.0  # average days from issue to full payment
    collection_rate: float = 0.0  # total_collected / total_invoiced
    fastest_payment_days: Optional[int] = None
    slowest_payment_days: Optional[int] = None
    top_clients: list[dict] = []  # [{client_id, client_name, total_invoiced, total_paid}]


# ---------------------------------------------------------------------------
# Estimates / Quotes
# ---------------------------------------------------------------------------

class EstimateStatus(str, Enum):
    """Status of an estimate/quote."""
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CONVERTED = "converted"  # turned into an invoice


class Estimate(BaseModel):
    """A quote or estimate sent to a client before work begins.

    Can be converted to an invoice once accepted.
    """

    id: str = Field(default_factory=lambda: f"EST-{uuid.uuid4().hex[:6].upper()}")
    client_id: str
    client_name: Optional[str] = None
    line_items: list[LineItem] = []
    status: EstimateStatus = EstimateStatus.DRAFT
    issue_date: date = Field(default_factory=date.today)
    expiry_date: Optional[date] = None  # Quote validity date
    accepted_date: Optional[date] = None
    converted_invoice_id: Optional[str] = None  # set when converted to an invoice
    currency: str = "USD"
    tax_rate: float = 0.0
    discount_amount: float = 0.0
    notes: Optional[str] = None
    terms: Optional[str] = None  # Payment terms or scope description
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

    @property
    def is_expired(self) -> bool:
        if self.expiry_date and self.status not in (EstimateStatus.ACCEPTED, EstimateStatus.CONVERTED, EstimateStatus.DECLINED):
            return date.today() > self.expiry_date
        return False

    def set_expiry(self, days: int) -> None:
        """Set the expiry date N days from today."""
        self.expiry_date = date.today() + timedelta(days=days)

    def mark_sent(self) -> None:
        self.status = EstimateStatus.SENT
        self.updated_at = datetime.now(tz=timezone.utc)

    def mark_accepted(self) -> None:
        self.status = EstimateStatus.ACCEPTED
        self.accepted_date = date.today()
        self.updated_at = datetime.now(tz=timezone.utc)

    def mark_declined(self) -> None:
        self.status = EstimateStatus.DECLINED
        self.updated_at = datetime.now(tz=timezone.utc)

    def check_expired(self) -> None:
        if self.is_expired and self.status in (EstimateStatus.DRAFT, EstimateStatus.SENT):
            self.status = EstimateStatus.EXPIRED
            self.updated_at = datetime.now(tz=timezone.utc)

    def to_markdown(self) -> str:
        """Export estimate as markdown."""
        sym = get_currency_symbol(self.currency)
        lines = [
            f"# Estimate {self.id}",
            "",
            f"**Client:** {self.client_name or self.client_id}",
            f"**Status:** {self.status.value.upper()}",
            f"**Currency:** {self.currency}",
            f"**Issue Date:** {self.issue_date}",
            f"**Valid Until:** {self.expiry_date or 'N/A'}",
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
        if self.terms:
            lines.append("")
            lines.append(f"**Terms:** {self.terms}")
        if self.notes:
            lines.append("")
            lines.append(f"**Notes:** {self.notes}")
        if self.accepted_date:
            lines.append("")
            lines.append(f"**Accepted on:** {self.accepted_date}")
        if self.converted_invoice_id:
            lines.append("")
            lines.append(f"**Converted to Invoice:** {self.converted_invoice_id}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Expenses (v0.7.0)
# ---------------------------------------------------------------------------

class ExpenseCategory(str, Enum):
    """Standard expense categories for agent businesses."""
    SOFTWARE = "software"
    API_COSTS = "api_costs"
    INFRASTRUCTURE = "infrastructure"
    CONTRACTORS = "contractors"
    MARKETING = "marketing"
    TRAVEL = "travel"
    OFFICE = "office"
    LEGAL = "legal"
    INSURANCE = "insurance"
    BANK_FEES = "bank_fees"
    TAXES = "taxes"
    OTHER = "other"


class Expense(BaseModel):
    """A business expense — cost incurred by the agent."""

    id: str = Field(default_factory=lambda: f"EXP-{uuid.uuid4().hex[:6].upper()}")
    description: str
    amount: float
    currency: str = "USD"
    category: ExpenseCategory = ExpenseCategory.OTHER
    vendor: Optional[str] = None  # Who the expense was paid to
    invoice_id: Optional[str] = None  # Link to a supplier invoice (if any)
    expense_date: date = Field(default_factory=date.today)
    payment_method: Optional[str] = None  # e.g. "credit_card", "bank_transfer", "crypto"
    reference: Optional[str] = None  # External reference number
    notes: Optional[str] = None
    tax_deductible: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Expense amount must be positive.")
        return v


# ---------------------------------------------------------------------------
# Profit / Profitability Analysis (v0.7.0)
# ---------------------------------------------------------------------------

class ClientProfitability(BaseModel):
    """Profitability analysis for a single client."""

    client_id: str
    client_name: Optional[str] = None
    currency: str = "USD"
    total_invoiced: float = 0.0
    total_collected: float = 0.0
    total_outstanding: float = 0.0
    direct_costs: float = 0.0  # Expenses linked to this client (via invoice_id)
    gross_revenue: float = 0.0  # total_collected
    gross_profit: float = 0.0  # gross_revenue - direct_costs
    gross_margin: float = 0.0  # gross_profit / gross_revenue * 100
    invoice_count: int = 0
    paid_invoice_count: int = 0
    avg_invoice_value: float = 0.0


class ProfitAnalysis(BaseModel):
    """Overall profit analysis across all revenue and expenses."""

    currency: str = "USD"
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_revenue: float = 0.0  # From collected invoice payments
    total_expenses: float = 0.0  # All expenses
    gross_profit: float = 0.0  # revenue - expenses
    gross_margin: float = 0.0  # gross_profit / total_revenue * 100
    expense_breakdown: list[dict] = []  # [{category, amount, percentage, count}]
    client_profitability: list[ClientProfitability] = []


# ---------------------------------------------------------------------------
# Tax Summary Report (v0.7.0)
# ---------------------------------------------------------------------------

class TaxLineItemSummary(BaseModel):
    """Tax summary for a single invoice's line items."""

    invoice_id: str
    client_name: Optional[str] = None
    issue_date: date
    subtotal: float = 0.0
    tax_amount: float = 0.0
    tax_rate: float = 0.0
    currency: str = "USD"


class TaxSummaryReport(BaseModel):
    """Tax summary report for a given period — collected and owed taxes."""

    period_start: date
    period_end: date
    currency: Optional[str] = None  # None = all currencies
    total_invoiced: float = 0.0
    total_tax_collected: float = 0.0
    total_tax_from_paid: float = 0.0  # Tax from fully paid invoices only
    effective_tax_rate: float = 0.0  # total_tax / total_invoiced * 100
    tax_by_rate: list[dict] = []  # [{rate, count, tax_amount, subtotal}]
    invoice_details: list[TaxLineItemSummary] = []
    tax_deductible_expenses: float = 0.0  # Deductible expenses in the period
    net_taxable_income: float = 0.0  # (total_invoiced - deductible expenses)


# ---------------------------------------------------------------------------
# Usage Metering & Agent Billing (v0.8.0)
# ---------------------------------------------------------------------------

class UsageEvent(BaseModel):
    """A single usage event — one API call, one agent run, one token batch.

    Records raw resource consumption so it can be metered, aggregated,
    and billed to a client.
    """

    id: str = Field(default_factory=lambda: f"USE-{uuid.uuid4().hex[:8].upper()}")
    client_id: Optional[str] = None  # Which client to bill for this usage
    client_name: Optional[str] = None  # Denormalized client name for convenience
    description: str  # Human-readable: "Claude Sonnet inference", "API gateway"
    provider: str = "openai"  # openai, anthropic, google, custom, etc.
    model: Optional[str] = None  # gpt-4, claude-3-opus, etc.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_count: int = 1  # Number of requests in this event
    cost: float  # Dollar cost of this usage event
    currency: str = "USD"
    metadata: dict = {}  # Arbitrary key-value tags (project, task, agent_id)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    billed: bool = False  # Has this been included in an invoice?
    invoice_id: Optional[str] = None  # Invoice this was billed on

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


class UsageRecord(BaseModel):
    """An aggregated usage record — bundles multiple events for billing.

    Created when you want to invoice a client for accumulated usage.
    Can be converted into invoice line items.
    """

    id: str = Field(default_factory=lambda: f"USG-{uuid.uuid4().hex[:8].upper()}")
    client_id: str
    client_name: Optional[str] = None
    period_start: date = Field(default_factory=date.today)
    period_end: date = Field(default_factory=date.today)
    currency: str = "USD"

    # Aggregated totals
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_cost: float = 0.0
    event_count: int = 0

    # Per-provider breakdown
    provider_breakdown: list[dict] = []  # [{provider, model, requests, input, output, cost}]
    # Per-model breakdown
    model_breakdown: list[dict] = []  # [{model, requests, input, output, cost}]

    # Line items derived from usage (for invoicing)
    line_items: list[dict] = []

    # Status
    billed: bool = False
    invoice_id: Optional[str] = None  # Created invoice ID
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def total_tokens(self) -> int:
        return (self.total_input_tokens + self.total_output_tokens +
                self.total_cache_read_tokens + self.total_cache_write_tokens)


class UsageSummary(BaseModel):
    """Summary of all usage across a period — for dashboards."""

    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = None
    client_id: Optional[str] = None

    total_events: int = 0
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    billed_cost: float = 0.0
    unbilled_cost: float = 0.0
    billed_events: int = 0
    unbilled_events: int = 0

    # Breakdowns
    by_provider: list[dict] = []  # [{provider, events, cost, tokens}]
    by_model: list[dict] = []  # [{model, events, cost, tokens}]
    by_client: list[dict] = []  # [{client_id, client_name, events, cost}]
    daily: list[dict] = []  # [{date, events, cost}]


# ---------------------------------------------------------------------------
# Usage Analytics & Cost Intelligence (v0.9.0)
# ---------------------------------------------------------------------------

class CostTrend(BaseModel):
    """Cost trend over a time series — for dashboards and analysis."""
    granularity: str = "daily"  # daily, weekly, monthly
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    data_points: list[dict] = []  # [{period, cost, events, tokens, input_tokens, output_tokens}]
    total_cost: float = 0.0
    total_events: int = 0
    avg_cost_per_period: float = 0.0
    min_cost: float = 0.0
    max_cost: float = 0.0
    trend_direction: str = "stable"  # increasing, decreasing, stable
    trend_percent: float = 0.0  # % change from first to last period


class CostProjection(BaseModel):
    """Projected future cost based on historical patterns."""
    currency: Optional[str] = None
    historical_periods: int = 0
    projection_periods: int = 0
    granularity: str = "daily"
    avg_daily_cost: float = 0.0
    projected_cost: float = 0.0
    projected_breakdown: list[dict] = []  # [{period, projected_cost, is_projection: true}]
    confidence: str = "low"  # low, medium, high based on data volume
    methodology: str = ""  # Description of projection method


class CostAnomaly(BaseModel):
    """Detected cost anomaly — spending spike or outlier."""
    period: str  # date or period label
    expected_cost: float = 0.0
    actual_cost: float = 0.0
    deviation_percent: float = 0.0
    severity: str = "info"  # info, warning, critical
    event_count: int = 0
    top_provider: Optional[str] = None
    top_client: Optional[str] = None


class AnomalyReport(BaseModel):
    """Report of all detected cost anomalies in a period."""
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = None
    baseline_avg_cost: float = 0.0
    anomaly_threshold_percent: float = 50.0  # Configurable threshold
    anomalies: list[CostAnomaly] = []
    total_anomalies: int = 0


class ModelEfficiency(BaseModel):
    """Efficiency metrics for a specific model."""
    provider: str
    model: str
    event_count: int = 0
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_requests: int = 0
    cost_per_1k_tokens: float = 0.0
    cost_per_request: float = 0.0
    avg_tokens_per_event: float = 0.0
    output_ratio: float = 0.0  # output_tokens / total_tokens
    cache_hit_ratio: float = 0.0  # cache_read / (input + cache_read)


class EfficiencyReport(BaseModel):
    """Comparative efficiency report across all models/providers."""
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    models: list[ModelEfficiency] = []
    cheapest_per_1k_tokens: Optional[dict] = None  # {provider, model, cost_per_1k}
    cheapest_per_request: Optional[dict] = None
    most_efficient_output: Optional[dict] = None  # Highest output ratio
    best_cache_utilization: Optional[dict] = None


class ProviderComparison(BaseModel):
    """Side-by-side comparison of providers."""
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    providers: list[dict] = []  # [{provider, total_cost, events, tokens, avg_cost, share_percent, models}]
    total_cost: float = 0.0
    dominant_provider: Optional[str] = None


# ---------------------------------------------------------------------------
# Rate Cards — Automatic Cost Calculation (v1.0.0)
# ---------------------------------------------------------------------------

class ModelPricing(BaseModel):
    """Pricing for a single model — per-million-token rates.

    All rates are in the parent RateCard's currency, per 1,000,000 tokens.
    """

    input_rate: float = 0.0      # $/M input tokens
    output_rate: float = 0.0     # $/M output tokens
    cache_read_rate: float = 0.0  # $/M cache-read tokens (often discounted)
    cache_write_rate: float = 0.0  # $/M cache-write tokens
    request_rate: float = 0.0    # $/request flat fee (per-call surcharge, $ not $/M)

    def cost_for(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_count: int = 1,
    ) -> float:
        """Calculate cost for given usage based on this pricing."""
        token_cost = (
            input_tokens * self.input_rate / 1_000_000
            + output_tokens * self.output_rate / 1_000_000
            + cache_read_tokens * self.cache_read_rate / 1_000_000
            + cache_write_tokens * self.cache_write_rate / 1_000_000
        )
        request_cost = self.request_rate * request_count
        return round(token_cost + request_cost, 6)


class RateCard(BaseModel):
    """A rate card mapping provider+model to per-token pricing.

    Agents record usage with just tokens and provider/model — the rate card
    calculates the cost automatically. No manual cost entry needed.
    """

    id: str = Field(default_factory=lambda: f"RATE-{uuid.uuid4().hex[:6].upper()}")
    name: str  # Human-readable name: "Production 2026-Q3", "Enterprise"
    currency: str = "USD"
    active: bool = True
    models: dict[str, ModelPricing] = {}  # key: "provider:model" e.g. "openai:gpt-4o"
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @staticmethod
    def model_key(provider: str, model: str) -> str:
        """Canonical key for a provider:model pair."""
        return f"{provider.lower()}:{model.lower()}"

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """Look up pricing for a provider+model. Returns None if not found."""
        return self.models.get(self.model_key(provider, model))

    def set_pricing(self, provider: str, model: str, pricing: ModelPricing) -> None:
        """Set or update pricing for a provider+model."""
        self.models[self.model_key(provider, model)] = pricing
        self.updated_at = datetime.now(tz=timezone.utc)

    def remove_pricing(self, provider: str, model: str) -> bool:
        """Remove pricing for a provider+model. Returns True if found."""
        key = self.model_key(provider, model)
        if key in self.models:
            del self.models[key]
            self.updated_at = datetime.now(tz=timezone.utc)
            return True
        return False

    def list_models(self) -> list[dict]:
        """Return all model entries as a list of dicts."""
        result = []
        for key, pricing in sorted(self.models.items()):
            provider, model = key.split(":", 1)
            result.append({
                "provider": provider,
                "model": model,
                "input_rate": pricing.input_rate,
                "output_rate": pricing.output_rate,
                "cache_read_rate": pricing.cache_read_rate,
                "cache_write_rate": pricing.cache_write_rate,
                "request_rate": pricing.request_rate,
            })
        return result

    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_count: int = 1,
    ) -> Optional[float]:
        """Calculate cost for usage based on this rate card. None if no pricing."""
        pricing = self.get_pricing(provider, model)
        if pricing is None:
            return None
        return pricing.cost_for(
            input_tokens, output_tokens,
            cache_read_tokens, cache_write_tokens,
            request_count,
        )


class BatchUsageResult(BaseModel):
    """Result of a batch usage recording operation."""

    total_recorded: int = 0
    total_failed: int = 0
    total_cost: float = 0.0
    event_ids: list[str] = []
    errors: list[dict] = []  # [{index, error}]
    currency: str = "USD"


# ---------------------------------------------------------------------------
# Subscription Plans & MRR (v0.10.0)
# ---------------------------------------------------------------------------

class BillingCycle(str, Enum):
    """Billing cycle for subscription plans."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class SubscriptionStatus(str, Enum):
    """Lifecycle status of a subscription."""
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SubscriptionPlan(BaseModel):
    """A reusable subscription product/plan.

    Defines pricing, billing cycle, trial period, and optional usage quotas.
    Clients subscribe to a plan to receive recurring invoices.
    """

    id: str = Field(default_factory=lambda: f"PLN-{uuid.uuid4().hex[:6].upper()}")
    name: str
    description: Optional[str] = None
    price: float
    currency: str = "USD"
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    trial_days: int = 0  # Free trial period; 0 = no trial
    tax_rate: float = 0.0
    due_days: int = 15  # Invoice due period after generation
    active: bool = True  # Plans can be deprecated without deleting

    # Usage quotas / limits (optional)
    quota_requests: Optional[int] = None  # Max API requests per billing period
    quota_tokens: Optional[int] = None  # Max tokens per billing period
    overage_rate: Optional[float] = None  # $ per unit over quota

    # Metadata
    metadata: dict = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @field_validator("price")
    @classmethod
    def price_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Plan price cannot be negative.")
        return v

    @property
    def monthly_price(self) -> float:
        """Normalized monthly price for MRR comparisons."""
        cycle_days = {
            BillingCycle.DAILY: 1,
            BillingCycle.WEEKLY: 7,
            BillingCycle.MONTHLY: 30,
            BillingCycle.QUARTERLY: 90,
            BillingCycle.YEARLY: 365,
        }
        days = cycle_days[self.billing_cycle]
        return round(self.price * 30 / days, 2)

    @property
    def has_trial(self) -> bool:
        return self.trial_days > 0

    def cycle_delta(self) -> timedelta:
        """timedelta for one billing cycle."""
        return {
            BillingCycle.DAILY: timedelta(days=1),
            BillingCycle.WEEKLY: timedelta(weeks=1),
            BillingCycle.MONTHLY: timedelta(days=30),
            BillingCycle.QUARTERLY: timedelta(days=90),
            BillingCycle.YEARLY: timedelta(days=365),
        }[self.billing_cycle]

    def generate_line_items(self) -> list[LineItem]:
        """Generate invoice line items for one billing cycle."""
        items = [LineItem(
            description=f"{self.name} — {self.billing_cycle.value} subscription",
            quantity=1,
            unit_price=self.price,
            tax_rate=self.tax_rate,
        )]
        return items


class Subscription(BaseModel):
    """A client's subscription to a plan.

    Manages the full lifecycle: trial → active → past due / cancelled.
    Generates invoices on each billing cycle.
    """

    id: str = Field(default_factory=lambda: f"SUB-{uuid.uuid4().hex[:8].upper()}")
    client_id: str
    client_name: Optional[str] = None
    plan_id: str
    plan_name: Optional[str] = None

    # Billing details (copied from plan at subscription time)
    price: float
    currency: str = "USD"
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    tax_rate: float = 0.0
    due_days: int = 15
    trial_days: int = 0

    # Lifecycle
    status: SubscriptionStatus = SubscriptionStatus.TRIALING
    start_date: date = Field(default_factory=date.today)
    trial_end_date: Optional[date] = None
    current_period_start: date = Field(default_factory=date.today)
    current_period_end: date = Field(default_factory=date.today)
    cancelled_at: Optional[date] = None
    ended_at: Optional[date] = None

    # Billing tracking
    next_billing_date: Optional[date] = None
    last_invoice_id: Optional[str] = None
    invoice_ids: list[str] = []

    # Metadata
    metadata: dict = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @field_validator("price")
    @classmethod
    def price_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Subscription price cannot be negative.")
        return v

    @property
    def monthly_revenue(self) -> float:
        """Normalized MRR contribution of this subscription."""
        cycle_days = {
            BillingCycle.DAILY: 1,
            BillingCycle.WEEKLY: 7,
            BillingCycle.MONTHLY: 30,
            BillingCycle.QUARTERLY: 90,
            BillingCycle.YEARLY: 365,
        }
        days = cycle_days[self.billing_cycle]
        return round(self.price * 30 / days, 2)

    @property
    def is_in_trial(self) -> bool:
        return self.status == SubscriptionStatus.TRIALING and self.trial_end_date is not None

    @property
    def trial_days_remaining(self) -> int:
        """Days remaining in trial; 0 if not trialing or trial ended."""
        if not self.is_in_trial:
            return 0
        remaining = (self.trial_end_date - date.today()).days
        return max(0, remaining)

    @property
    def is_billable(self) -> bool:
        """True if this subscription should be invoiced (active or past_due)."""
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)

    def _cycle_delta(self) -> timedelta:
        """timedelta for one billing cycle."""
        return {
            BillingCycle.DAILY: timedelta(days=1),
            BillingCycle.WEEKLY: timedelta(weeks=1),
            BillingCycle.MONTHLY: timedelta(days=30),
            BillingCycle.QUARTERLY: timedelta(days=90),
            BillingCycle.YEARLY: timedelta(days=365),
        }[self.billing_cycle]

    def init_trial(self) -> None:
        """Initialize trial period if the plan has trial days."""
        if self.trial_days > 0:
            self.status = SubscriptionStatus.TRIALING
            self.trial_end_date = self.start_date + timedelta(days=self.trial_days)
            # First billing happens after trial ends
            self.next_billing_date = self.trial_end_date
            self.current_period_end = self.trial_end_date
        else:
            self.status = SubscriptionStatus.ACTIVE
            self.current_period_start = self.start_date
            self.current_period_end = self.start_date + self._cycle_delta()
            self.next_billing_date = self.start_date
        self.updated_at = datetime.now(tz=timezone.utc)

    def activate_from_trial(self) -> None:
        """Convert from trialing to active when trial ends."""
        self.status = SubscriptionStatus.ACTIVE
        self.current_period_start = date.today()
        self.current_period_end = date.today() + self._cycle_delta()
        self.next_billing_date = date.today()
        self.updated_at = datetime.now(tz=timezone.utc)

    def advance_period(self) -> None:
        """Advance to the next billing period after an invoice is generated."""
        self.current_period_start = self.current_period_end
        self.current_period_end = self.current_period_end + self._cycle_delta()
        self.next_billing_date = self.current_period_end
        self.updated_at = datetime.now(tz=timezone.utc)

    def mark_past_due(self) -> None:
        """Mark subscription as past due (invoice unpaid)."""
        self.status = SubscriptionStatus.PAST_DUE
        self.updated_at = datetime.now(tz=timezone.utc)

    def cancel(self, immediately: bool = False) -> None:
        """Cancel the subscription.

        Args:
            immediately: If True, ends right now. If False, stays active until period end.
        """
        self.cancelled_at = date.today()
        if immediately:
            self.status = SubscriptionStatus.CANCELLED
            self.ended_at = date.today()
            self.next_billing_date = None
        else:
            self.status = SubscriptionStatus.ACTIVE  # still active until period ends
            self.next_billing_date = None  # won't renew
        self.updated_at = datetime.now(tz=timezone.utc)

    def pause(self) -> None:
        """Pause the subscription (billing resumes on resume)."""
        self.status = SubscriptionStatus.PAUSED
        self.updated_at = datetime.now(tz=timezone.utc)

    def resume(self) -> None:
        """Resume a paused subscription."""
        if self.status != SubscriptionStatus.PAUSED:
            raise ValueError("Only paused subscriptions can be resumed.")
        self.status = SubscriptionStatus.ACTIVE
        self.current_period_start = date.today()
        self.current_period_end = date.today() + self._cycle_delta()
        self.next_billing_date = date.today()
        self.updated_at = datetime.now(tz=timezone.utc)

    def generate_line_items(self) -> list[LineItem]:
        """Generate invoice line items for this subscription's billing cycle."""
        item = LineItem(
            description=f"{self.plan_name or 'Subscription'} — {self.billing_cycle.value} subscription"
                        + (f" (period: {self.current_period_start} to {self.current_period_end})"
                           if self.current_period_start else ""),
            quantity=1,
            unit_price=self.price,
            tax_rate=self.tax_rate,
        )
        return [item]


class MRRSummary(BaseModel):
    """Monthly Recurring Revenue summary dashboard."""
    currency: str = "USD"
    as_of_date: date = Field(default_factory=date.today)

    # Active subscriptions
    active_count: int = 0
    trialing_count: int = 0
    past_due_count: int = 0
    paused_count: int = 0
    cancelled_count: int = 0
    total_count: int = 0

    # Revenue metrics
    mrr: float = 0.0  # Monthly Recurring Revenue (active + past_due only)
    arr: float = 0.0  # Annual Recurring Revenue (MRR * 12)
    trial_mrr: float = 0.0  # Potential MRR from trialing subscriptions
    paused_mrr: float = 0.0  # MRR currently paused
    lost_mrr: float = 0.0  # MRR from cancelled subs in this period

    # By plan
    by_plan: list[dict] = []  # [{plan_id, plan_name, count, mrr, monthly_price}]
    # By billing cycle
    by_cycle: list[dict] = []  # [{cycle, count, mrr}]
    # By client
    top_clients: list[dict] = []  # [{client_id, client_name, plan_name, mrr}]

    # Churn metrics
    avg_subscription_value: float = 0.0


# Built-in subscription plans for agent services
BUILTIN_PLANS: list[dict] = [
    {
        "id": "PLN-STARTER",
        "name": "Starter Agent",
        "description": "Basic agent API access with monthly quota",
        "price": 49.0,
        "currency": "USD",
        "billing_cycle": "monthly",
        "trial_days": 14,
        "quota_requests": 10000,
        "quota_tokens": 1_000_000,
    },
    {
        "id": "PLN-PRO",
        "name": "Professional Agent",
        "description": "Higher quotas and priority routing",
        "price": 199.0,
        "currency": "USD",
        "billing_cycle": "monthly",
        "trial_days": 14,
        "quota_requests": 100000,
        "quota_tokens": 10_000_000,
    },
    {
        "id": "PLN-ENTERPRISE",
        "name": "Enterprise Agent",
        "description": "Unlimited requests with dedicated support",
        "price": 999.0,
        "currency": "USD",
        "billing_cycle": "monthly",
        "trial_days": 0,
        "quota_requests": None,
        "quota_tokens": None,
    },
    {
        "id": "PLN-YEARLY-PRO",
        "name": "Annual Professional",
        "description": "Annual billing with 2 months free",
        "price": 1990.0,
        "currency": "USD",
        "billing_cycle": "yearly",
        "trial_days": 14,
        "quota_requests": 1200000,
        "quota_tokens": 120_000_000,
    },
]
