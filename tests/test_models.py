"""Tests for data models."""

import pytest
from datetime import date, timedelta

from agent_invoice.models import (
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
    get_currency_symbol,
)


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

    def test_tax_rate(self):
        item = LineItem(description="Service", quantity=1, unit_price=100.0, tax_rate=8.5)
        assert item.tax_rate == 8.5
        assert item.tax_amount == 8.5
        assert item.total == 100.0

    def test_zero_tax_rate(self):
        item = LineItem(description="Service", quantity=1, unit_price=100.0, tax_rate=0.0)
        assert item.tax_amount is None
        assert item.total_with_tax == 100.0

    def test_total_with_tax(self):
        item = LineItem(description="Consulting", quantity=10, unit_price=200.0, tax_rate=10.0)
        assert item.total == 2000.0
        assert item.tax_amount == 200.0
        assert item.total_with_tax == 2200.0

    def test_tax_rounding(self):
        item = LineItem(description="Small item", quantity=1, unit_price=33.33, tax_rate=7.25)
        assert item.total == 33.33
        assert item.tax_amount == 2.42  # 33.33 * 0.0725 = 2.416425 -> 2.42

    def test_explicit_tax_amount(self):
        item = LineItem(description="Custom", quantity=1, unit_price=100.0, tax_rate=10.0, tax_amount=12.0)
        assert item.tax_amount == 12.0  # explicit override


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

    def test_client_default_currency(self):
        client = Client(name="Test")
        assert client.currency == "USD"

    def test_client_custom_currency(self):
        client = Client(name="Euro Client", currency="EUR")
        assert client.currency == "EUR"


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

    def test_total_with_tax(self):
        inv = Invoice(
            client_id="CLT-123",
            line_items=[
                LineItem(description="Work", quantity=1, unit_price=100.0, tax_rate=10.0),
                LineItem(description="Work 2", quantity=1, unit_price=200.0, tax_rate=10.0),
            ],
        )
        assert inv.subtotal == 300.0
        assert inv.total_tax == 30.0
        assert inv.total == 330.0

    def test_total_with_discount(self):
        inv = Invoice(
            client_id="CLT-123",
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0)],
            discount_amount=20.0,
        )
        assert inv.subtotal == 100.0
        assert inv.total == 80.0

    def test_total_with_tax_and_discount(self):
        inv = Invoice(
            client_id="CLT-123",
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0, tax_rate=10.0)],
            discount_amount=15.0,
        )
        assert inv.subtotal == 100.0
        assert inv.total_tax == 10.0
        assert inv.total == 95.0  # 100 + 10 - 15

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
            currency="USD",
            line_items=[
                LineItem(description="Code review", quantity=10, unit_price=150.0),
            ],
        )
        md = inv.to_markdown()
        assert "# Invoice INV-0001" in md
        assert "Acme Corp" in md
        assert "Code review" in md
        assert "$1500.00" in md

    def test_to_markdown_with_tax(self):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            client_name="Acme Corp",
            currency="USD",
            line_items=[
                LineItem(description="Service", quantity=1, unit_price=100.0, tax_rate=10.0),
            ],
        )
        md = inv.to_markdown()
        assert "Tax:" in md
        assert "$10.00" in md  # tax amount
        assert "Total:" in md

    def test_to_markdown_with_discount(self):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            client_name="Acme Corp",
            discount_amount=25.0,
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0)],
        )
        md = inv.to_markdown()
        assert "Discount:" in md
        assert "$25.00" in md

    def test_to_markdown_eur(self):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            client_name="Euro Client",
            currency="EUR",
            line_items=[LineItem(description="Service", quantity=1, unit_price=500.0)],
        )
        md = inv.to_markdown()
        assert "€500.00" in md

    def test_cancel_invoice(self):
        inv = Invoice(client_id="CLT-123", status=InvoiceStatus.DRAFT)
        inv.status = InvoiceStatus.CANCELLED
        assert inv.status == InvoiceStatus.CANCELLED

    def test_default_currency(self):
        inv = Invoice(client_id="CLT-123")
        assert inv.currency == "USD"

    def test_custom_currency(self):
        inv = Invoice(client_id="CLT-123", currency="EUR")
        assert inv.currency == "EUR"


class TestRecurringInvoice:
    def test_create_recurring(self):
        rec = RecurringInvoice(
            client_id="CLT-123",
            client_name="Acme",
            line_items=[LineItem(description="Retainer", quantity=1, unit_price=500.0)],
            frequency=RecurrenceFrequency.MONTHLY,
        )
        assert rec.id.startswith("REC-")
        assert rec.frequency == RecurrenceFrequency.MONTHLY
        assert rec.active is True
        assert rec.subtotal == 500.0

    def test_recurring_with_tax(self):
        rec = RecurringInvoice(
            client_id="CLT-123",
            line_items=[LineItem(description="Service", quantity=1, unit_price=100.0, tax_rate=10.0)],
            frequency=RecurrenceFrequency.MONTHLY,
        )
        assert rec.total_tax == 10.0
        assert rec.total == 110.0

    def test_compute_next_date_weekly(self):
        rec = RecurringInvoice(client_id="CLT-123", frequency=RecurrenceFrequency.WEEKLY, next_date=date(2026, 1, 1))
        next_d = rec.compute_next_date()
        assert next_d == date(2026, 1, 8)

    def test_compute_next_date_monthly(self):
        rec = RecurringInvoice(client_id="CLT-123", frequency=RecurrenceFrequency.MONTHLY, next_date=date(2026, 1, 15))
        next_d = rec.compute_next_date()
        assert next_d == date(2026, 2, 14)

    def test_generate_invoice(self):
        rec = RecurringInvoice(
            client_id="CLT-123",
            client_name="Acme",
            line_items=[LineItem(description="Retainer", quantity=1, unit_price=500.0)],
            frequency=RecurrenceFrequency.MONTHLY,
            next_date=date.today(),
        )
        inv = rec.generate_invoice("INV-0001")
        assert inv.id == "INV-0001"
        assert inv.client_id == "CLT-123"
        assert inv.client_name == "Acme"
        assert inv.subtotal == 500.0
        assert inv.status == InvoiceStatus.DRAFT
        assert "INV-0001" in rec.invoice_ids
        assert rec.last_generated == date.today()

    def test_pause_resume(self):
        rec = RecurringInvoice(client_id="CLT-123", active=True)
        rec.active = False
        assert rec.active is False
        rec.active = True
        assert rec.active is True


class TestNumberingConfig:
    def test_default_config(self):
        config = NumberingConfig()
        assert config.prefix == "INV"
        assert config.separator == "-"
        assert config.digits == 4
        assert config.next_number == 1

    def test_format_number(self):
        config = NumberingConfig()
        assert config.format_number() == "INV-0001"
        assert config.format_number(5) == "INV-0005"
        assert config.format_number(100) == "INV-0100"

    def test_custom_prefix(self):
        config = NumberingConfig(prefix="BIL", separator="/", digits=3, next_number=42)
        assert config.format_number() == "BIL/042"

    def test_advance(self):
        config = NumberingConfig()
        n1 = config.advance()
        assert n1 == "INV-0001"
        n2 = config.advance()
        assert n2 == "INV-0002"
        assert config.next_number == 3


class TestCurrencyHelpers:
    def test_get_currency_symbol(self):
        assert get_currency_symbol("USD") == "$"
        assert get_currency_symbol("EUR") == "€"
        assert get_currency_symbol("GBP") == "£"
        assert get_currency_symbol("JPY") == "¥"
        assert get_currency_symbol("XYZ") == "XYZ"  # unknown code returns the code

    def test_format_amount_usd(self):
        assert format_amount(1234.56, "USD") == "$1,234.56"

    def test_format_amount_eur(self):
        assert format_amount(1000.0, "EUR") == "€1,000.00"

    def test_format_amount_jpy(self):
        assert format_amount(5000, "JPY") == "¥5,000"

    def test_format_amount_unknown(self):
        assert format_amount(100.0, "XYZ") == "XYZ100.00"


class TestEarningsSummary:
    def test_default_summary(self):
        summary = EarningsSummary()
        assert summary.total_invoiced == 0.0
        assert summary.total_paid == 0.0
        assert summary.invoice_count == 0
        assert summary.total_tax == 0.0
        assert summary.currency == "USD"

    def test_summary_with_currency(self):
        summary = EarningsSummary(currency="EUR")
        assert summary.currency == "EUR"


class TestCurrencies:
    def test_major_currencies_exist(self):
        for code in ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR"]:
            assert code in CURRENCIES
            assert "symbol" in CURRENCIES[code]
            assert "name" in CURRENCIES[code]
            assert "decimals" in CURRENCIES[code]
