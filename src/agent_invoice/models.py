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


class LineItem(BaseModel):
    """A single line item on an invoice."""

    description: str
    quantity: float = 1.0
    unit_price: float
    total: Optional[float] = None

    def model_post_init(self, __context: object) -> None:
        if self.total is None:
            self.total = round(self.quantity * self.unit_price, 2)


class Client(BaseModel):
    """A client that can be billed."""

    id: str = Field(default_factory=lambda: f"CLT-{uuid.uuid4().hex[:8].upper()}")
    name: str
    email: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Invoice(BaseModel):
    """An invoice for work completed."""

    id: str = Field(default_factory=lambda: f"INV-{uuid.uuid4().hex[:6].upper()}")
    client_id: str
    client_name: Optional[str] = None
    line_items: list[LineItem] = []
    status: InvoiceStatus = InvoiceStatus.DRAFT
    issue_date: date = Field(default_factory=date.today)
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def subtotal(self) -> float:
        return round(sum(item.total or 0 for item in self.line_items), 2)

    @property
    def is_overdue(self) -> bool:
        if self.due_date and self.status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
            return date.today() > self.due_date
        return False

    def set_due_date(self, days: int) -> None:
        self.due_date = date.today() + timedelta(days=days)

    def mark_paid(self) -> None:
        self.status = InvoiceStatus.PAID
        self.paid_date = date.today()
        self.updated_at = datetime.now(tz=timezone.utc)

    def mark_sent(self) -> None:
        self.status = InvoiceStatus.SENT
        self.updated_at = datetime.now(tz=timezone.utc)

    def check_overdue(self) -> None:
        if self.is_overdue and self.status == InvoiceStatus.SENT:
            self.status = InvoiceStatus.OVERDUE
            self.updated_at = datetime.now(tz=timezone.utc)

    def to_markdown(self) -> str:
        """Export invoice as markdown."""
        lines = [
            f"# Invoice {self.id}",
            "",
            f"**Client:** {self.client_name or self.client_id}",
            f"**Status:** {self.status.value.upper()}",
            f"**Issue Date:** {self.issue_date}",
            f"**Due Date:** {self.due_date or 'N/A'}",
            "",
            "## Line Items",
            "",
            "| Description | Qty | Unit Price | Total |",
            "|---|---|---|---|",
        ]
        for item in self.line_items:
            lines.append(
                f"| {item.description} | {item.quantity} | ${item.unit_price:.2f} | ${item.total:.2f} |"
            )
        lines.append("")
        lines.append(f"**Subtotal: ${self.subtotal:.2f}**")
        if self.notes:
            lines.append("")
            lines.append(f"**Notes:** {self.notes}")
        if self.paid_date:
            lines.append("")
            lines.append(f"**Paid on:** {self.paid_date}")
        return "\n".join(lines)


class EarningsSummary(BaseModel):
    """Summary of earnings across all invoices."""

    total_invoiced: float = 0.0
    total_paid: float = 0.0
    total_pending: float = 0.0
    total_overdue: float = 0.0
    invoice_count: int = 0
    paid_count: int = 0
    pending_count: int = 0
    overdue_count: int = 0
