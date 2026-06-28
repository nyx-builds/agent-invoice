"""Tests for the service layer."""

import pytest

from agent_invoice.models import InvoiceStatus
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
