"""Tests for JSON file storage."""

import json
import pytest
import tempfile
from pathlib import Path

from agent_invoice.models import Client, Invoice, InvoiceStatus, LineItem, NumberingConfig, RecurringInvoice, RecurrenceFrequency
from agent_invoice.store import InvoiceStore


@pytest.fixture
def store(tmp_path):
    return InvoiceStore(data_dir=str(tmp_path))


class TestNumberingConfig:
    def test_default_config(self, store):
        config = store.get_numbering_config()
        assert config.prefix == "INV"
        assert config.next_number == 1

    def test_save_and_load_config(self, store):
        config = store.get_numbering_config()
        config.prefix = "BIL"
        config.separator = "/"
        config.digits = 3
        store.save_numbering_config(config)
        loaded = store.get_numbering_config()
        assert loaded.prefix == "BIL"
        assert loaded.separator == "/"
        assert loaded.digits == 3

    def test_get_next_invoice_number(self, store):
        n1 = store.get_next_invoice_number()
        assert n1 == "INV-0001"
        n2 = store.get_next_invoice_number()
        assert n2 == "INV-0002"

    def test_get_next_invoice_number_custom(self, store):
        config = store.get_numbering_config()
        config.prefix = "2026"
        config.separator = "/"
        config.digits = 3
        store.save_numbering_config(config)
        n1 = store.get_next_invoice_number()
        assert n1 == "2026/001"
        n2 = store.get_next_invoice_number()
        assert n2 == "2026/002"


class TestClientStorage:
    def test_save_and_get_client(self, store):
        client = Client(name="Acme Corp", email="billing@acme.com")
        store.save_client(client)
        retrieved = store.get_client(client.id)
        assert retrieved is not None
        assert retrieved.name == "Acme Corp"
        assert retrieved.email == "billing@acme.com"

    def test_save_client_with_currency(self, store):
        client = Client(name="Euro Corp", currency="EUR")
        store.save_client(client)
        retrieved = store.get_client(client.id)
        assert retrieved.currency == "EUR"

    def test_get_nonexistent_client(self, store):
        assert store.get_client("CLT-NONEXIST") is None

    def test_find_client_by_name(self, store):
        client = Client(name="Test Client", email="test@test.com")
        store.save_client(client)
        found = store.find_client_by_name("Test Client")
        assert found is not None
        assert found.id == client.id

    def test_find_client_by_name_case_insensitive(self, store):
        client = Client(name="Test Client")
        store.save_client(client)
        found = store.find_client_by_name("test client")
        assert found is not None

    def test_find_client_not_found(self, store):
        assert store.find_client_by_name("Ghost") is None

    def test_list_clients_empty(self, store):
        assert store.list_clients() == []

    def test_list_clients_multiple(self, store):
        c1 = Client(name="Alpha")
        c2 = Client(name="Beta")
        store.save_client(c1)
        store.save_client(c2)
        clients = store.list_clients()
        assert len(clients) == 2

    def test_delete_client(self, store):
        client = Client(name="To Delete")
        store.save_client(client)
        assert store.delete_client(client.id) is True
        assert store.get_client(client.id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete_client("CLT-NONEXIST") is False


class TestInvoiceStorage:
    def test_save_and_get_invoice(self, store):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            client_name="Test",
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0)],
        )
        store.save_invoice(inv)
        retrieved = store.get_invoice("INV-0001")
        assert retrieved is not None
        assert retrieved.client_id == "CLT-123"
        assert retrieved.subtotal == 100.0

    def test_save_and_get_invoice_with_tax(self, store):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0, tax_rate=10.0)],
        )
        store.save_invoice(inv)
        retrieved = store.get_invoice("INV-0001")
        assert retrieved.total_tax == 10.0
        assert retrieved.total == 110.0

    def test_save_and_get_invoice_with_currency(self, store):
        inv = Invoice(
            id="INV-0001",
            client_id="CLT-123",
            currency="EUR",
            line_items=[LineItem(description="Work", quantity=1, unit_price=100.0)],
        )
        store.save_invoice(inv)
        retrieved = store.get_invoice("INV-0001")
        assert retrieved.currency == "EUR"

    def test_get_nonexistent_invoice(self, store):
        assert store.get_invoice("INV-NONEXIST") is None

    def test_list_invoices_empty(self, store):
        assert store.list_invoices() == []

    def test_list_invoices_filter_status(self, store):
        inv1 = Invoice(id="INV-0001", client_id="CLT-1", status=InvoiceStatus.DRAFT)
        inv2 = Invoice(id="INV-0002", client_id="CLT-1", status=InvoiceStatus.PAID)
        store.save_invoice(inv1)
        store.save_invoice(inv2)
        paid = store.list_invoices(status=InvoiceStatus.PAID)
        assert len(paid) == 1
        assert paid[0].id == "INV-0002"

    def test_list_invoices_filter_client(self, store):
        inv1 = Invoice(id="INV-0001", client_id="CLT-1")
        inv2 = Invoice(id="INV-0002", client_id="CLT-2")
        store.save_invoice(inv1)
        store.save_invoice(inv2)
        filtered = store.list_invoices(client_id="CLT-1")
        assert len(filtered) == 1
        assert filtered[0].id == "INV-0001"

    def test_list_invoices_filter_currency(self, store):
        inv1 = Invoice(id="INV-0001", client_id="CLT-1", currency="USD")
        inv2 = Invoice(id="INV-0002", client_id="CLT-1", currency="EUR")
        store.save_invoice(inv1)
        store.save_invoice(inv2)
        usd = store.list_invoices(currency="USD")
        assert len(usd) == 1
        assert usd[0].currency == "USD"

    def test_delete_invoice(self, store):
        inv = Invoice(id="INV-0001", client_id="CLT-1")
        store.save_invoice(inv)
        assert store.delete_invoice("INV-0001") is True
        assert store.get_invoice("INV-0001") is None


class TestRecurringInvoiceStorage:
    def test_save_and_get_recurring(self, store):
        rec = RecurringInvoice(
            id="REC-0001",
            client_id="CLT-123",
            client_name="Test",
            line_items=[LineItem(description="Retainer", quantity=1, unit_price=500.0)],
            frequency=RecurrenceFrequency.MONTHLY,
        )
        store.save_recurring(rec)
        retrieved = store.get_recurring("REC-0001")
        assert retrieved is not None
        assert retrieved.client_id == "CLT-123"
        assert retrieved.frequency == RecurrenceFrequency.MONTHLY
        assert retrieved.subtotal == 500.0

    def test_get_nonexistent_recurring(self, store):
        assert store.get_recurring("REC-NONEXIST") is None

    def test_list_recurring(self, store):
        rec1 = RecurringInvoice(id="REC-0001", client_id="CLT-1", frequency=RecurrenceFrequency.MONTHLY)
        rec2 = RecurringInvoice(id="REC-0002", client_id="CLT-2", frequency=RecurrenceFrequency.WEEKLY)
        store.save_recurring(rec1)
        store.save_recurring(rec2)
        all_rec = store.list_recurring()
        assert len(all_rec) == 2

    def test_list_recurring_active_only(self, store):
        rec1 = RecurringInvoice(id="REC-0001", client_id="CLT-1", frequency=RecurrenceFrequency.MONTHLY, active=True)
        rec2 = RecurringInvoice(id="REC-0002", client_id="CLT-2", frequency=RecurrenceFrequency.WEEKLY, active=False)
        store.save_recurring(rec1)
        store.save_recurring(rec2)
        active = store.list_recurring(active_only=True)
        assert len(active) == 1
        assert active[0].id == "REC-0001"

    def test_delete_recurring(self, store):
        rec = RecurringInvoice(id="REC-0001", client_id="CLT-1", frequency=RecurrenceFrequency.MONTHLY)
        store.save_recurring(rec)
        assert store.delete_recurring("REC-0001") is True
        assert store.get_recurring("REC-0001") is None

    def test_delete_nonexistent_recurring(self, store):
        assert store.delete_recurring("REC-NONEXIST") is False
