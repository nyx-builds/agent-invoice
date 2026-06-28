"""Tests for the service layer."""

import pytest
import tempfile
from datetime import date
from pathlib import Path

from agent_invoice.models import InvoiceStatus, Payment, RecurrenceFrequency
from agent_invoice.service import InvoiceService
from agent_invoice.store import InvoiceStore


@pytest.fixture
def service(tmp_path):
    store = InvoiceStore(data_dir=str(tmp_path))
    return InvoiceService(store=store)


class TestClientService:
    def test_add_client(self, service):
        client = service.add_client(name="Acme Corp", email="billing@acme.com")
        assert client.name == "Acme Corp"
        assert client.email == "billing@acme.com"

    def test_add_client_with_currency(self, service):
        client = service.add_client(name="Euro Corp", currency="EUR")
        assert client.currency == "EUR"

    def test_add_client_invalid_currency(self, service):
        with pytest.raises(ValueError, match="Unsupported currency"):
            service.add_client(name="Bad", currency="XYZ")

    def test_add_duplicate_client_fails(self, service):
        service.add_client(name="Acme Corp")
        with pytest.raises(ValueError, match="already exists"):
            service.add_client(name="Acme Corp")

    def test_get_client_by_id(self, service):
        created = service.add_client(name="Acme Corp")
        found = service.get_client(created.id)
        assert found is not None
        assert found.name == "Acme Corp"

    def test_get_client_by_name(self, service):
        service.add_client(name="Acme Corp")
        found = service.get_client("Acme Corp")
        assert found is not None
        assert found.name == "Acme Corp"

    def test_list_clients(self, service):
        service.add_client(name="Alpha")
        service.add_client(name="Beta")
        clients = service.list_clients()
        assert len(clients) == 2

    def test_remove_client_by_name(self, service):
        service.add_client(name="Acme Corp")
        assert service.remove_client("Acme Corp") is True
        assert service.get_client("Acme Corp") is None

    def test_remove_nonexistent_client(self, service):
        assert service.remove_client("Ghost") is False


class TestNumberingConfig:
    def test_get_default_config(self, service):
        config = service.get_numbering_config()
        assert config.prefix == "INV"

    def test_update_prefix(self, service):
        config = service.update_numbering_config(prefix="BIL")
        assert config.prefix == "BIL"

    def test_update_full_config(self, service):
        config = service.update_numbering_config(
            prefix="2026",
            separator="/",
            digits=3,
            next_number=5,
        )
        assert config.prefix == "2026"
        assert config.separator == "/"
        assert config.digits == 3
        assert config.next_number == 5

    def test_numbering_affects_invoice_creation(self, service):
        service.update_numbering_config(prefix="BIL", separator="/", digits=3)
        service.add_client(name="Acme")
        inv = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        assert inv.id.startswith("BIL/")


class TestInvoiceService:
    def _setup_client(self, service):
        return service.add_client(name="Acme Corp", email="billing@acme.com")

    def test_create_invoice(self, service):
        client = self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[
                {"description": "Code review", "quantity": 10, "unit_price": 150.0},
                {"description": "Bug fixes", "quantity": 5, "unit_price": 200.0},
            ],
            due_days=30,
        )
        assert inv.id.startswith("INV-")
        assert inv.client_name == "Acme Corp"
        assert inv.subtotal == 2500.0
        assert inv.status == InvoiceStatus.DRAFT
        assert inv.due_date is not None
        assert inv.payments == []

    def test_create_invoice_with_tax_per_item(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[
                {"description": "Service", "quantity": 1, "unit_price": 100.0, "tax_rate": 10.0},
            ],
        )
        assert inv.subtotal == 100.0
        assert inv.total_tax == 10.0
        assert inv.total == 110.0

    def test_create_invoice_with_invoice_level_tax(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[
                {"description": "Service A", "quantity": 1, "unit_price": 100.0},
                {"description": "Service B", "quantity": 1, "unit_price": 200.0},
            ],
            tax_rate=8.5,
        )
        # Both items should get the invoice-level tax rate
        assert inv.total_tax == 25.5  # (100 + 200) * 0.085
        assert inv.total == 325.5

    def test_create_invoice_mixed_tax(self, service):
        """Items with their own tax rate override invoice-level."""
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[
                {"description": "Taxable", "quantity": 1, "unit_price": 100.0, "tax_rate": 20.0},
                {"description": "Default tax", "quantity": 1, "unit_price": 200.0},
            ],
            tax_rate=10.0,
        )
        # Item 1: 100 * 0.20 = 20 tax, Item 2: 200 * 0.10 = 20 tax
        assert inv.total_tax == 40.0
        assert inv.total == 340.0

    def test_create_invoice_with_discount(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
            discount_amount=25.0,
        )
        assert inv.subtotal == 100.0
        assert inv.discount_amount == 25.0
        assert inv.total == 75.0

    def test_create_invoice_with_currency_override(self, service):
        service.add_client(name="Euro Client", currency="EUR")
        inv = service.create_invoice(
            client_identifier="Euro Client",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        assert inv.currency == "EUR"

    def test_create_invoice_explicit_currency_override(self, service):
        service.add_client(name="USD Client", currency="USD")
        inv = service.create_invoice(
            client_identifier="USD Client",
            line_items=[{"description": "Work", "unit_price": 100.0}],
            currency="GBP",
        )
        assert inv.currency == "GBP"

    def test_create_invoice_invalid_currency(self, service):
        self._setup_client(service)
        with pytest.raises(ValueError, match="Unsupported currency"):
            service.create_invoice(
                client_identifier="Acme Corp",
                line_items=[{"description": "Work", "unit_price": 100.0}],
                currency="XYZ",
            )

    def test_create_invoice_unknown_client(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.create_invoice(
                client_identifier="Unknown",
                line_items=[{"description": "Work", "unit_price": 100.0}],
            )

    def test_mark_paid(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        paid = service.mark_paid(inv.id)
        assert paid.status == InvoiceStatus.PAID
        assert paid.paid_date is not None

    def test_mark_paid_already_paid(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.mark_paid(inv.id)
        with pytest.raises(ValueError, match="already paid"):
            service.mark_paid(inv.id)

    def test_mark_sent(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        sent = service.mark_sent(inv.id)
        assert sent.status == InvoiceStatus.SENT

    def test_cancel_invoice(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        cancelled = service.cancel_invoice(inv.id)
        assert cancelled.status == InvoiceStatus.CANCELLED

    def test_cancel_paid_invoice_fails(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.mark_paid(inv.id)
        with pytest.raises(ValueError, match="Cannot cancel a paid invoice"):
            service.cancel_invoice(inv.id)

    def test_list_invoices(self, service):
        self._setup_client(service)
        service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work A", "unit_price": 100.0}],
        )
        service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work B", "unit_price": 200.0}],
        )
        invoices = service.list_invoices()
        assert len(invoices) == 2

    def test_list_invoices_by_status(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.mark_paid(inv.id)
        paid = service.list_invoices(status=InvoiceStatus.PAID)
        assert len(paid) == 1
        drafts = service.list_invoices(status=InvoiceStatus.DRAFT)
        assert len(drafts) == 0

    def test_list_invoices_by_currency(self, service):
        service.add_client(name="USD Client", currency="USD")
        service.add_client(name="EUR Client", currency="EUR")
        service.create_invoice(
            client_identifier="USD Client",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.create_invoice(
            client_identifier="EUR Client",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        usd = service.list_invoices(currency="USD")
        assert len(usd) == 1
        assert usd[0].currency == "USD"

    def test_remove_invoice(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        assert service.remove_invoice(inv.id) is True
        assert service.get_invoice(inv.id) is None

    def test_invoice_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.mark_paid("INV-9999")

    def test_apply_discount(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        updated = service.apply_discount(inv.id, 25.0)
        assert updated.discount_amount == 25.0
        assert updated.total == 75.0

    def test_apply_discount_paid_invoice_fails(self, service):
        self._setup_client(service)
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.mark_paid(inv.id)
        with pytest.raises(ValueError, match="Cannot apply discount"):
            service.apply_discount(inv.id, 25.0)


class TestPaymentService:
    def _setup_invoice(self, service, amount=100.0):
        """Helper to create a client and invoice."""
        service.add_client(name="Acme")
        return service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": amount}],
        )

    def test_record_payment_full(self, service):
        inv = self._setup_invoice(service, 100.0)
        updated = service.record_payment(inv.id, 100.0)
        assert updated.status == InvoiceStatus.PAID
        assert updated.amount_paid == 100.0
        assert updated.amount_remaining == 0.0
        assert len(updated.payments) == 1
        assert updated.paid_date is not None

    def test_record_payment_partial(self, service):
        inv = self._setup_invoice(service, 100.0)
        updated = service.record_payment(inv.id, 50.0, method="bank_transfer")
        assert updated.status == InvoiceStatus.PARTIALLY_PAID
        assert updated.amount_paid == 50.0
        assert updated.amount_remaining == 50.0
        assert len(updated.payments) == 1

    def test_record_payment_two_partials(self, service):
        inv = self._setup_invoice(service, 100.0)
        service.record_payment(inv.id, 60.0, method="credit_card")
        updated = service.record_payment(inv.id, 40.0, method="bank_transfer")
        assert updated.status == InvoiceStatus.PAID
        assert updated.amount_paid == 100.0
        assert updated.amount_remaining == 0.0
        assert len(updated.payments) == 2

    def test_record_payment_with_method_and_reference(self, service):
        inv = self._setup_invoice(service, 500.0)
        updated = service.record_payment(
            inv.id, 500.0,
            method="crypto",
            reference="0xabc123",
            notes="ETH payment",
        )
        assert updated.payments[0].method == "crypto"
        assert updated.payments[0].reference == "0xabc123"
        assert updated.payments[0].notes == "ETH payment"

    def test_record_payment_custom_date(self, service):
        inv = self._setup_invoice(service, 100.0)
        updated = service.record_payment(inv.id, 100.0, payment_date=date(2026, 1, 15))
        assert updated.payments[0].payment_date == date(2026, 1, 15)

    def test_record_payment_zero_fails(self, service):
        inv = self._setup_invoice(service, 100.0)
        with pytest.raises(ValueError, match="must be positive"):
            service.record_payment(inv.id, 0.0)

    def test_record_payment_negative_fails(self, service):
        inv = self._setup_invoice(service, 100.0)
        with pytest.raises(ValueError, match="must be positive"):
            service.record_payment(inv.id, -50.0)

    def test_record_payment_overpayment_fails(self, service):
        inv = self._setup_invoice(service, 100.0)
        with pytest.raises(ValueError, match="exceeds remaining"):
            service.record_payment(inv.id, 150.0)

    def test_record_payment_cancelled_invoice_fails(self, service):
        inv = self._setup_invoice(service, 100.0)
        service.cancel_invoice(inv.id)
        with pytest.raises(ValueError, match="cancelled"):
            service.record_payment(inv.id, 50.0)

    def test_record_payment_already_paid_fails(self, service):
        inv = self._setup_invoice(service, 100.0)
        service.record_payment(inv.id, 100.0)
        with pytest.raises(ValueError, match="already fully paid"):
            service.record_payment(inv.id, 10.0)

    def test_record_payment_invoice_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.record_payment("INV-9999", 50.0)

    def test_list_payments(self, service):
        inv = self._setup_invoice(service, 100.0)
        service.record_payment(inv.id, 30.0, method="credit_card")
        service.record_payment(inv.id, 70.0, method="bank_transfer")
        payments = service.list_payments(inv.id)
        assert len(payments) == 2
        assert payments[0].amount == 30.0
        assert payments[0].method == "credit_card"
        assert payments[1].amount == 70.0
        assert payments[1].method == "bank_transfer"

    def test_list_payments_empty(self, service):
        inv = self._setup_invoice(service, 100.0)
        payments = service.list_payments(inv.id)
        assert payments == []

    def test_list_payments_invoice_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.list_payments("INV-9999")

    def test_remove_payment(self, service):
        inv = self._setup_invoice(service, 100.0)
        updated = service.record_payment(inv.id, 50.0, method="credit_card")
        payment_id = updated.payments[0].id

        result = service.remove_payment(inv.id, payment_id)
        assert result.amount_paid == 0.0
        assert result.amount_remaining == 100.0
        assert result.status == InvoiceStatus.DRAFT

    def test_remove_payment_from_paid_invoice(self, service):
        inv = self._setup_invoice(service, 100.0)
        updated = service.record_payment(inv.id, 100.0)
        assert updated.status == InvoiceStatus.PAID

        payment_id = updated.payments[0].id
        result = service.remove_payment(inv.id, payment_id)
        assert result.status == InvoiceStatus.DRAFT
        assert result.paid_date is None

    def test_remove_payment_nonexistent(self, service):
        inv = self._setup_invoice(service, 100.0)
        with pytest.raises(ValueError, match="not found on invoice"):
            service.remove_payment(inv.id, "PMT-NONEXIST")

    def test_payment_with_tax_and_discount(self, service):
        """Test partial payment on invoice with tax and discount."""
        service.add_client(name="Acme")
        inv = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": 100.0, "tax_rate": 10.0}],
            discount_amount=10.0,
        )
        # total = 100 + 10 - 10 = 100
        updated = service.record_payment(inv.id, 50.0)
        assert updated.amount_paid == 50.0
        assert updated.amount_remaining == 50.0
        assert updated.status == InvoiceStatus.PARTIALLY_PAID


class TestPDFExport:
    def test_export_pdf_basic(self, service, tmp_path):
        service.add_client(name="Acme Corp")
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Code review", "quantity": 10, "unit_price": 150.0}],
        )
        output = str(tmp_path / "test_invoice.pdf")
        result = service.export_pdf(inv.id, output_path=output)
        assert result == output
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_export_pdf_with_company_info(self, service, tmp_path):
        service.add_client(name="Acme Corp")
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Service", "unit_price": 500.0}],
        )
        output = str(tmp_path / "test_company.pdf")
        result = service.export_pdf(
            inv.id,
            output_path=output,
            company_name="Test Company LLC",
            company_address="123 Main St, Anytown, USA",
            company_email="billing@testcompany.com",
        )
        assert result == output
        assert Path(output).exists()

    def test_export_pdf_with_tax_and_discount(self, service, tmp_path):
        service.add_client(name="Acme Corp")
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0, "tax_rate": 10.0}],
            discount_amount=15.0,
        )
        output = str(tmp_path / "test_tax_discount.pdf")
        result = service.export_pdf(inv.id, output_path=output)
        assert Path(output).exists()

    def test_export_pdf_with_payments(self, service, tmp_path):
        service.add_client(name="Acme Corp")
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.record_payment(inv.id, 40.0, method="credit_card", reference="TXN-001")
        service.record_payment(inv.id, 60.0, method="bank_transfer", reference="TXN-002")

        output = str(tmp_path / "test_payments.pdf")
        result = service.export_pdf(inv.id, output_path=output)
        assert Path(output).exists()

    def test_export_pdf_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.export_pdf("INV-9999")

    def test_export_pdf_auto_path(self, service):
        """Test PDF export with auto-generated path."""
        service.add_client(name="Acme Corp")
        inv = service.create_invoice(
            client_identifier="Acme Corp",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        result = service.export_pdf(inv.id)
        assert result.endswith(".pdf")
        assert Path(result).exists()
        # Cleanup
        Path(result).unlink(missing_ok=True)


class TestRecurringInvoiceService:
    def test_create_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
            frequency="monthly",
        )
        assert rec.id.startswith("REC-")
        assert rec.client_name == "Acme"
        assert rec.frequency == RecurrenceFrequency.MONTHLY
        assert rec.subtotal == 500.0
        assert rec.active is True

    def test_create_recurring_weekly(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Support", "unit_price": 200.0}],
            frequency="weekly",
        )
        assert rec.frequency == RecurrenceFrequency.WEEKLY

    def test_create_recurring_invalid_frequency(self, service):
        service.add_client(name="Acme")
        with pytest.raises(ValueError, match="Invalid frequency"):
            service.create_recurring(
                client_identifier="Acme",
                line_items=[{"description": "Work", "unit_price": 100.0}],
                frequency="daily",
            )

    def test_create_recurring_with_tax(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
            tax_rate=10.0,
        )
        assert rec.total_tax == 50.0
        assert rec.total == 550.0

    def test_create_recurring_unknown_client(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.create_recurring(
                client_identifier="Ghost",
                line_items=[{"description": "Work", "unit_price": 100.0}],
            )

    def test_list_recurring(self, service):
        service.add_client(name="Acme")
        service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        recs = service.list_recurring()
        assert len(recs) == 1

    def test_list_recurring_active_only(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        service.pause_recurring(rec.id)
        active = service.list_recurring(active_only=True)
        assert len(active) == 0
        all_rec = service.list_recurring(active_only=False)
        assert len(all_rec) == 1

    def test_pause_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        paused = service.pause_recurring(rec.id)
        assert paused.active is False

    def test_resume_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        service.pause_recurring(rec.id)
        resumed = service.resume_recurring(rec.id)
        assert resumed.active is True
        assert resumed.next_date == date.today()

    def test_pause_nonexistent_fails(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.pause_recurring("REC-NONEXIST")

    def test_remove_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        assert service.remove_recurring(rec.id) is True

    def test_generate_from_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        inv = service.generate_from_recurring(rec.id)
        assert inv.client_name == "Acme"
        assert inv.subtotal == 500.0
        assert inv.status == InvoiceStatus.DRAFT
        assert inv.due_date is not None
        # Verify the recurring template was updated
        updated_rec = service.get_recurring(rec.id)
        assert inv.id in updated_rec.invoice_ids

    def test_generate_from_paused_recurring_fails(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        service.pause_recurring(rec.id)
        with pytest.raises(ValueError, match="paused"):
            service.generate_from_recurring(rec.id)

    def test_process_due_recurring(self, service):
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
            frequency="monthly",
        )
        # Since next_date is today, it should be due
        generated = service.process_due_recurring()
        assert len(generated) >= 1
        assert generated[0].client_name == "Acme"

    def test_process_due_recurring_future(self, service):
        """Recurring with future next_date should not generate."""
        service.add_client(name="Acme")
        rec = service.create_recurring(
            client_identifier="Acme",
            line_items=[{"description": "Retainer", "unit_price": 500.0}],
        )
        # Manually set next_date to future
        from agent_invoice.models import RecurringInvoice
        rec_obj = service.get_recurring(rec.id)
        rec_obj.next_date = date.today().replace(year=date.today().year + 1)
        from agent_invoice.store import InvoiceStore
        # Use the same store
        store = service.store
        store.save_recurring(rec_obj)
        generated = service.process_due_recurring()
        assert len(generated) == 0


class TestEarningsSummary:
    def test_empty_summary(self, service):
        summary = service.earnings_summary()
        assert summary.total_invoiced == 0.0
        assert summary.invoice_count == 0

    def test_summary_with_invoices(self, service):
        service.add_client(name="Acme")
        inv1 = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work A", "unit_price": 500.0}],
        )
        inv2 = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work B", "unit_price": 300.0}],
        )
        service.mark_paid(inv1.id)

        summary = service.earnings_summary()
        assert summary.total_invoiced == 800.0
        assert summary.total_paid == 500.0
        assert summary.total_pending == 300.0
        assert summary.paid_count == 1
        assert summary.pending_count == 1

    def test_summary_with_tax(self, service):
        service.add_client(name="Acme")
        inv = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": 100.0, "tax_rate": 10.0}],
        )
        service.mark_paid(inv.id)
        summary = service.earnings_summary()
        assert summary.total_tax == 10.0
        assert summary.total_paid == 110.0  # grand total including tax

    def test_summary_with_discount(self, service):
        service.add_client(name="Acme")
        inv = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": 100.0}],
            discount_amount=25.0,
        )
        service.mark_paid(inv.id)
        summary = service.earnings_summary()
        assert summary.total_discounts == 25.0
        assert summary.total_paid == 75.0  # discounted total

    def test_summary_by_currency(self, service):
        service.add_client(name="USD Client", currency="USD")
        service.add_client(name="EUR Client", currency="EUR")
        service.create_invoice(
            client_identifier="USD Client",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.create_invoice(
            client_identifier="EUR Client",
            line_items=[{"description": "Work", "unit_price": 200.0}],
        )
        usd_summary = service.earnings_summary(currency="USD")
        assert usd_summary.invoice_count == 1
        assert usd_summary.currency == "USD"
        eur_summary = service.earnings_summary(currency="EUR")
        assert eur_summary.invoice_count == 1
        assert eur_summary.currency == "EUR"

    def test_summary_with_partial_payments(self, service):
        service.add_client(name="Acme")
        inv = service.create_invoice(
            client_identifier="Acme",
            line_items=[{"description": "Work", "unit_price": 100.0}],
        )
        service.record_payment(inv.id, 60.0, method="credit_card")
        summary = service.earnings_summary()
        assert summary.partially_paid_count == 1
        assert summary.total_payments == 60.0
        assert summary.total_paid == 60.0  # amount actually paid
        assert summary.total_pending == 40.0  # remaining amount
