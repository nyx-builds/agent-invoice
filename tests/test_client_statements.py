"""Tests for client statement generation — opening/closing balances, period activity."""

import pytest
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore
from datetime import date, timedelta
import shutil
import tempfile


@pytest.fixture
def svc():
    tmpdir = tempfile.mkdtemp()
    service = InvoiceService(InvoiceStore(data_dir=tmpdir))
    yield service
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def client(svc):
    return svc.create_client(name="Acme Corp", email="billing@acme.com", currency="USD")


class TestClientStatement:
    def test_empty_statement(self, svc, client):
        """Statement with no activity."""
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert stmt.client_id == client.id
        assert stmt.opening_balance == 0.0
        assert stmt.closing_balance == 0.0
        assert stmt.total_invoiced == 0.0
        assert stmt.total_paid == 0.0
        assert len(stmt.invoices) == 0
        assert len(stmt.payments) == 0
        assert len(stmt.credit_notes) == 0

    def test_statement_with_invoices_in_period(self, svc, client):
        """Invoices issued within the period are included."""
        # Create invoices
        inv1 = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Work A", "quantity": 10, "unit_price": 100.0}],
        )
        inv2 = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Work B", "quantity": 5, "unit_price": 200.0}],
        )
        today = date.today()
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=today - timedelta(days=365),
            period_end=today + timedelta(days=365),
        )
        assert len(stmt.invoices) == 2
        assert stmt.total_invoiced == 2000.0  # 1000 + 1000
        assert stmt.closing_balance == 2000.0

    def test_statement_opening_balance_from_prior_invoices(self, svc, client):
        """Invoices issued before the period contribute to opening balance."""
        # Create an invoice (issued today = before our future period)
        inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Prior work", "quantity": 1, "unit_price": 500.0}],
        )
        # Statement for a future period
        future_start = date.today() + timedelta(days=30)
        future_end = date.today() + timedelta(days=60)
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=future_start,
            period_end=future_end,
        )
        assert stmt.opening_balance == 500.0
        assert stmt.closing_balance == 500.0
        assert len(stmt.invoices) == 0  # invoice was before the period

    def test_statement_with_payment(self, svc, client):
        """Payments reduce the balance."""
        inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Work", "quantity": 10, "unit_price": 100.0}],
        )
        svc.add_payment(inv.id, amount=400.0)
        today = date.today()
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=today - timedelta(days=1),
            period_end=today + timedelta(days=1),
        )
        assert stmt.total_invoiced == 1000.0
        assert stmt.total_paid == 400.0
        assert stmt.closing_balance == 600.0

    def test_statement_with_credit_note(self, svc, client):
        """Credit notes reduce the balance."""
        inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Work", "quantity": 10, "unit_price": 100.0}],
        )
        credit = svc.create_credit_note(
            client_identifier=client.id, amount=250.0, reason="refund"
        )
        today = date.today()
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=today - timedelta(days=1),
            period_end=today + timedelta(days=1),
        )
        assert stmt.total_invoiced == 1000.0
        assert stmt.total_credits == 250.0
        assert stmt.closing_balance == 750.0

    def test_statement_closing_equals_opening_plus_activity(self, svc, client):
        """Closing = opening + invoiced - paid - credits."""
        # Prior period invoice (contributes to opening)
        old_inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Old work", "quantity": 1, "unit_price": 300.0}],
        )
        # Period invoice
        new_inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "New work", "quantity": 5, "unit_price": 100.0}],
        )
        svc.add_payment(new_inv.id, amount=200.0)
        svc.create_credit_note(client_identifier=client.id, amount=50.0)

        today = date.today()
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=today,
            period_end=today + timedelta(days=365),
        )
        expected_closing = stmt.opening_balance + stmt.total_invoiced - stmt.total_paid - stmt.total_credits
        assert stmt.closing_balance == round(expected_closing, 2)

    def test_statement_invalid_date_range(self, svc, client):
        """period_start > period_end should raise."""
        with pytest.raises(ValueError, match="before"):
            svc.generate_client_statement(
                client_identifier=client.id,
                period_start=date(2026, 6, 1),
                period_end=date(2026, 5, 1),
            )

    def test_statement_client_not_found(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.generate_client_statement(
                client_identifier="nope",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
            )

    def test_statement_currency_filter(self, svc):
        """Statement respects currency filter for multi-currency clients."""
        client_usd = svc.create_client(name="USD Client", currency="USD")
        client_eur = svc.create_client(name="EUR Client", currency="EUR")
        inv_usd = svc.create_invoice(
            client_identifier=client_usd.id,
            line_items=[{"description": "Work", "quantity": 1, "unit_price": 100.0}],
        )
        inv_eur = svc.create_invoice(
            client_identifier=client_eur.id,
            line_items=[{"description": "Work", "quantity": 1, "unit_price": 100.0}],
            currency="EUR",
        )
        today = date.today()
        stmt_usd = svc.generate_client_statement(
            client_identifier=client_usd.id,
            period_start=today - timedelta(days=1),
            period_end=today + timedelta(days=1),
        )
        assert stmt_usd.currency == "USD"
        assert stmt_usd.total_invoiced == 100.0

        stmt_eur = svc.generate_client_statement(
            client_identifier=client_eur.id,
            period_start=today - timedelta(days=1),
            period_end=today + timedelta(days=1),
        )
        assert stmt_eur.currency == "EUR"
        assert stmt_eur.total_invoiced == 100.0

    def test_statement_payments_from_prior_invoices(self, svc, client):
        """Payments within period on old invoices are captured in the period."""
        old_inv = svc.create_invoice(
            client_identifier=client.id,
            line_items=[{"description": "Old work", "quantity": 1, "unit_price": 1000.0}],
        )
        # Now make a payment (today)
        svc.add_payment(old_inv.id, amount=500.0)

        today = date.today()
        stmt = svc.generate_client_statement(
            client_identifier=client.id,
            period_start=today,
            period_end=today + timedelta(days=1),
        )
        # Opening balance should include old invoice but not today's payment
        # Payments within period should include today's payment
        assert stmt.total_paid == 500.0
        assert len(stmt.payments) == 1
