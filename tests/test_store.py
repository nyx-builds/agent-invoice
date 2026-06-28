"""Tests for JSON file storage."""

import json
import pytest
import tempfile
from pathlib import Path

from agent_invoice.models import Client, Invoice, InvoiceStatus, LineItem
from agent_invoice.store import InvoiceStore


@pytest.fixture
def store(tmp_path):
    return InvoiceStore(data_dir=str(tmp_path))


class TestClientStorage:
    def test_save_and_get_client(self, store):
        client = Client(name="Acme Corp", email="billing@acme.com")
        store.save_client(client)
        retrieved = store.get_client(client.id)
        assert retrieved is not None
        assert retrieved.name == "Acme Corp"
        assert retrieved.email == "billing@acme.com"

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

    def test_delete_invoice(self, store):
        inv = Invoice(id="INV-0001", client_id="CLT-1")
        store.save_invoice(inv)
        assert store.delete_invoice("INV-0001") is True
        assert store.get_invoice("INV-0001") is None

    def test_get_next_invoice_number(self, store):
        inv1 = Invoice(id="INV-0001", client_id="CLT-1")
        store.save_invoice(inv1)
        next_num = store.get_next_invoice_number()
        assert next_num == "INV-0002"

    def test_get_next_invoice_number_empty(self, store):
        next_num = store.get_next_invoice_number()
        assert next_num == "INV-0001"
