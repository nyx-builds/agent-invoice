"""Tests for data models."""

import pytest
from datetime import date, timedelta

from agent_invoice.models import Client, Invoice, InvoiceStatus, LineItem, EarningsSummary


class TestLineItem:
    def test_basic_creation(self):
        item = LineItem(description="Code review", quantity=10, unit_price=150.0)
        assert item.description == "Code review"
        assert item.quantity == 10
        assert item.unit_price == 150.0
        assert item.total == 1500.0

    def test_default_quantity(self):
        item = LineItem(description="Bug fix", unit_price=200.0)
        assert item.quantity == 1.0
        assert item.total == 200.0

    def test_explicit_total(self):
        item = LineItem(description="Custom", quantity=1, unit_price=100.0, total=95.0)
        assert item.total == 95.0

    def test_rounding(self):
        item = LineItem(description="Test", quantity=3, unit_price=33.33)
        assert item.total == 99.99


class TestClient:
    def test_create_client(self):
        client = Client(name="Acme Corp", email="billing@acme.com")
        assert client.name == "Acme Corp"
        assert client.email == "billing@acme.com"
        assert client.id.startswith("CLT-")

    def test_client_id_unique(self):
        c1 = Client(name="A")
        c2 = Client(name="B")
        assert c1.id != c2.id


class TestInvoice:
    def test_create_invoice(self):
        inv = Invoice(client_id="CLT-123", client_name="Acme")
        assert inv.id.startswith("INV-")
        assert inv.status == InvoiceStatus.DRAFT
        assert inv.subtotal == 0.0

    def test_subtotal_with_items(self):
        inv = Invoice(
            client_id="CLT-123",
            line_items=[
                LineItem(description="Work A", quantity=5, unit_price=100.0),
                LineItem(description="Work B", quantity=2, unit_price=200.0),
            ],
        )
        assert inv.subtotal == 900.0

    def test_set_due_date(self):
        inv = Invoice(client_id="CLT-123")
        inv.set_due_date(30)
        assert inv.due_date == date.today() + timedelta(days=30)

    def test_mark_paid(self):
        inv = Invoice(client_id="CLT-123")
        inv.mark_paid()
        assert inv.status == InvoiceStatus.PAID
        assert inv.paid_date == date.today()

    def test_mark_sent(self):
        inv = Invoice(client_id="CLT-123")
        inv.mark_sent()
        assert inv.status == InvoiceStatus.SENT

    def test_is_overdue(self):
        inv = Invoice(client_id="CLT-123", status=InvoiceStatus.SENT)
        inv.due_date = date.today() - timedelta(days=1)
        assert inv.is_overdue is True

    def test_not_overdue_if_paid(self):
        inv = Invoice(client_id="CLT-123", status=InvoiceStatus.PAID)
        inv.due_date = date.today() - timedelta(days=1)
        assert inv.is_overdue is False

    def test_check_overdue(self):
        inv = Invoice(client_id="CLT-123", status=InvoiceStatus.SENT)
        inv.due_date = date.today() - timedelta(days=1)
        inv.check_overdue()
        assert inv.status == InvoiceStatus.OVERDUE

    def test_to_markdown(self):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            client_name="Acme Corp",
            line_items=[
                LineItem(description="Code review", quantity=10, unit_price=150.0),
            ],
        )
        md = inv.to_markdown()
        assert "# Invoice INV-0001" in md
        assert "Acme Corp" in md
        assert "Code review" in md
        assert "$1500.00" in md

    def test_cancel_invoice(self):
        inv = Invoice(client_id="CLT-123", status=InvoiceStatus.DRAFT)
        inv.status = InvoiceStatus.CANCELLED
        assert inv.status == InvoiceStatus.CANCELLED


class TestEarningsSummary:
    def test_default_summary(self):
        summary = EarningsSummary()
        assert summary.total_invoiced == 0.0
        assert summary.total_paid == 0.0
        assert summary.invoice_count == 0
